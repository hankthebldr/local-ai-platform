#!/usr/bin/env python3
"""
Plugin Service — Discovery, loading, skill matching, tool invocation
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import re
import shutil
import sys
import tarfile
import tempfile
import types
from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger


def _parse_skill_md(path: Path) -> dict:
    """Parse a skill markdown file with YAML frontmatter."""
    text = path.read_text()
    if not text.startswith("---"):
        return {"name": "", "description": "", "inject": "none", "content": text}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": "", "description": "", "inject": "none", "content": text}

    meta = yaml.safe_load(parts[1]) or {}
    content = parts[2].strip()
    return {
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "inject": meta.get("inject", "none"),
        "content": content,
    }


# ── LB5-U2 version helpers ───────────────────────────────────────────────
# plugin.yaml `version` is the single source of truth. The setter is a
# targeted top-level line replacement (never a safe_dump round-trip) so an
# auto-bump can't clobber the operator's comments/formatting.

_VERSION_LINE_RE = re.compile(r"(?m)^version:\s*.*$")


def _bump_patch(version: str) -> str:
    """0.1.0 → 0.1.1; tolerant of short/odd versions (1.0 → 1.0.1)."""
    parts = str(version or "0.0.0").strip().split(".")
    if parts and parts[-1].isdigit() and len(parts) >= 3:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{'.'.join(parts)}.1" if parts and parts[0] else "0.0.1"


def _set_manifest_version(text: str, version: str) -> str:
    """Rewrite (or add) the top-level ``version:`` line in manifest text."""
    line = f'version: "{version}"'
    if _VERSION_LINE_RE.search(text):
        return _VERSION_LINE_RE.sub(line, text, count=1)
    return text.rstrip("\n") + "\n" + line + "\n"


class PluginService:
    """Discovers and manages plugins from a directory convention.

    Phase 1.2 (Track B) — two-layer discovery:
      system_dir   read-only OOTB plugins shipped with the app/image
      user_dir     writable user-installed plugins; persists across updates

    On id collision, user wins. The returned plugin dict carries:
      origin: "system" | "user"          which layer the winning copy came from
      overrides_system: bool             True if a user plugin shadowed a
                                         system plugin with the same id
    """

    def __init__(
        self,
        plugins_dir: Optional[str] = None,
        *,
        system_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        # Phase 1.2 — prefer the (system_dir, user_dir) two-layer API.
        # Backwards-compatible: plugins_dir maps to system_dir when neither
        # explicit layer is provided. Default falls back to the deployment-
        # resolved storage roots; if detection failed, plugins/ relative
        # to cwd (pre-Phase-1 behavior).
        self._auto_resolve = False
        if system_dir is not None or user_dir is not None:
            self._system_dir = Path(system_dir) if system_dir else None
            self._user_dir = Path(user_dir) if user_dir else None
        elif plugins_dir is not None:
            # Legacy single-dir constructor — treat as system layer
            self._system_dir = Path(plugins_dir)
            self._user_dir = None
        else:
            # Auto-resolve from deployment
            try:
                from .deployment import _get_current as _get_dep

                d = _get_dep()
                self._system_dir = d.system_storage_root / "plugins"
                self._user_dir = d.user_storage_root / "plugins"
            except Exception:
                # Deployment singleton not installed yet — plugins.py builds
                # this service at import time, BEFORE api/main.py's startup
                # event runs detect_deployment(). Fall back to the pre-Phase-1
                # cwd layout for now and retry lazily (LB5-U3): without the
                # retry a live server has NO writable user layer and every
                # user-layer write (install, forge, file PUT) 500s.
                self._system_dir = Path("plugins")
                self._user_dir = None
                self._auto_resolve = True
        # Legacy alias for code paths that still call self._dir
        self._dir = self._system_dir or Path("plugins")
        self._plugins: dict = {}
        self._tools: dict = {}
        # LB5-U2 version policy: ids saved since the last reload. The FIRST
        # save in a reload cycle patch-bumps plugin.yaml's version; further
        # saves ride the same bump until scan_plugins() clears the flag.
        self._dirty: set = set()

    def _maybe_resolve_layers(self) -> None:
        """Late-bind the deployment storage layers (LB5-U3).

        Only active for the auto-resolve constructor path that raced app
        startup (see __init__). The first scan or user_dir access after
        detect_deployment() has installed the singleton picks up the real
        (system, user) layers — the object identity of the router/chat
        shared singleton never changes.
        """
        if not self._auto_resolve:
            return
        try:
            from .deployment import _get_current as _get_dep

            d = _get_dep()
        except Exception:
            return  # still pre-startup — keep the cwd fallback for now
        self._system_dir = d.system_storage_root / "plugins"
        self._user_dir = d.user_storage_root / "plugins"
        self._dir = self._system_dir
        self._auto_resolve = False
        logger.info(
            "Plugin layers late-bound from deployment: system=%s user=%s",
            self._system_dir,
            self._user_dir,
        )

    def scan_plugins(self) -> list:
        """Walk both layers (system first, then user). User overrides on id.

        Returns the union as a list of plugin dicts. Each carries `origin`
        and `overrides_system` so the UI can render which layer won.
        """
        self._maybe_resolve_layers()
        self._plugins.clear()
        self._tools.clear()
        self._dirty.clear()  # reload closes the version-bump cycle (LB5-U2)

        layers = []
        if self._system_dir is not None:
            layers.append(("system", self._system_dir))
        if self._user_dir is not None:
            layers.append(("user", self._user_dir))

        for layer_name, base in layers:
            if not base.exists():
                if layer_name == "system":
                    logger.warning(f"Plugins directory not found: {base}")
                continue
            for child in sorted(base.iterdir()):
                self._load_one_plugin(child, layer_name)

        return list(self._plugins.values())

    def _load_one_plugin(self, child: Path, layer_name: str) -> None:
        """Load a single plugin directory into self._plugins.

        Idempotent for the (id, layer) pair but NOT for (id, *) — a user
        plugin with the same id as a previously-loaded system plugin
        overwrites the system entry and marks overrides_system=True.
        """
        if not child.is_dir():
            return
        if child.name.startswith("_"):
            return

        manifest_path = child / "plugin.yaml"
        if not manifest_path.exists():
            logger.warning(f"Skipping {child.name}: no plugin.yaml")
            return

        try:
            manifest = yaml.safe_load(manifest_path.read_text())
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in {manifest_path}: {e}")
            return

        plugin_id = manifest.get("id", child.name)
        overrides_system = layer_name == "user" and plugin_id in self._plugins

        # Load skills
        skills = []
        for skill_def in manifest.get("skills", []):
            skill_path = (child / skill_def["file"]).resolve()
            if not str(skill_path).startswith(str(child.resolve())):
                logger.error(
                    f"Path traversal blocked: {skill_def['file']} in {plugin_id}"
                )
                continue
            if skill_path.exists():
                parsed = _parse_skill_md(skill_path)
                skills.append(
                    {
                        "id": skill_def["id"],
                        "triggers": skill_def.get("triggers", []),
                        **parsed,
                    }
                )
            else:
                logger.warning(f"Skill file not found: {skill_path}")

        # If we're loading a user plugin that overrides a system one,
        # drop the system tools first so they don't linger in self._tools.
        if overrides_system:
            for key in list(self._tools.keys()):
                if key[0] == plugin_id:
                    del self._tools[key]

        # Pre-load tool modules
        tools = []
        for tool_def in manifest.get("tools", []):
            tool_path = (child / tool_def["file"]).resolve()
            if not str(tool_path).startswith(str(child.resolve())):
                logger.error(
                    f"Path traversal blocked: {tool_def['file']} in {plugin_id}"
                )
                continue
            if tool_path.exists():
                module = self._load_tool_module(plugin_id, tool_def["id"], tool_path)
                if module:
                    self._tools[(plugin_id, tool_def["id"])] = {
                        "module": module,
                        "function": tool_def.get("function", "execute"),
                    }
                tools.append(
                    {
                        "id": tool_def["id"],
                        "description": tool_def.get("description", ""),
                        "parameters": tool_def.get("parameters", {}),
                    }
                )
            else:
                logger.warning(f"Tool file not found: {tool_path}")

        plugin_data = {
            "id": plugin_id,
            "name": manifest.get("name", plugin_id),
            "version": manifest.get("version", "0.0.0"),
            "description": manifest.get("description", ""),
            "author": manifest.get("author", "unknown"),
            "path": str(child),
            "skills": skills,
            "tools": tools,
            # Phase 1.2 (Track B) layer metadata
            "origin": layer_name,
            "overrides_system": overrides_system,
        }
        self._plugins[plugin_id] = plugin_data
        logger.info(
            f"Loaded plugin: {plugin_id} from {layer_name} "
            f"({len(skills)} skills, {len(tools)} tools"
            + (", overrides system" if overrides_system else "")
            + ")"
        )

    def _load_tool_module(self, plugin_id: str, tool_id: str, path: Path):
        """Dynamically load a Python tool module.

        Registers a synthetic package for the plugin's tools/ directory so
        tools that use relative imports (e.g. `from ._engine import …`,
        `from .analyse_xql import …`) resolve correctly without requiring
        changes to the tool files themselves.
        """
        tools_dir = path.parent
        # Sanitize plugin_id for use as a Python identifier (dashes → underscores)
        safe_plugin_id = plugin_id.replace("-", "_")
        pkg_name = f"plugin_{safe_plugin_id}_tools"

        # Register the synthetic package once per plugin so relative imports
        # anchor against it. Python resolves e.g. `from ._engine import x`
        # by looking up pkg_name._engine via pkg.__path__.
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = [str(tools_dir)]
            pkg.__package__ = pkg_name
            sys.modules[pkg_name] = pkg

        sub_name = f"{pkg_name}.{tool_id}"
        module_alias = f"plugin_{plugin_id}_{tool_id}"
        try:
            spec = importlib.util.spec_from_file_location(sub_name, path)
            module = importlib.util.module_from_spec(spec)
            module.__package__ = pkg_name
            sys.modules[sub_name] = module
            sys.modules[module_alias] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.error(f"Failed to load tool {plugin_id}/{tool_id}: {e}")
            return None

    def list_plugins(self) -> list:
        """List all discovered plugins."""
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> Optional[dict]:
        """Return the discovered plugin dict (with origin) or None."""
        return self._plugins.get(plugin_id)

    def has_plugin(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def has_tool(self, plugin_id: str, tool_id: str) -> bool:
        """True if the (plugin, tool) pair was discovered."""
        return (plugin_id, tool_id) in self._tools

    def has_skill(self, plugin_id: str, skill_id: str) -> bool:
        """True if the plugin ships a skill with this id."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False
        return any(s["id"] == skill_id for s in plugin.get("skills", []))

    def get_skill(self, plugin_id: str, skill_id: str) -> Optional[dict]:
        """Return the full skill dict (id, name, description, content,
        inject, triggers) for ``<plugin_id>.<skill_id>``, or None.

        Used by ``skill_injector`` (Phase 4.2 — skill activation capture)
        to look up a skill body when the operator listed it explicitly on
        a step rather than relying on keyword triggers."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        for skill in plugin.get("skills", []):
            if skill["id"] == skill_id:
                return skill
        return None

    # ── user layer access (LB3-U1 skills promote) ───────────────────

    @property
    def user_dir(self) -> Optional[Path]:
        """Writable user-layer plugins directory (None when not configured)."""
        self._maybe_resolve_layers()
        return self._user_dir

    def ensure_user_plugin(
        self,
        plugin_id: str,
        name: Optional[str] = None,
        description: str = "",
    ) -> Path:
        """Create a minimal user-layer plugin skeleton when absent.

        Idempotent — an existing plugin directory (any content) is returned
        as-is. The manifest is written atomically (tmp+replace). Raises
        RuntimeError when no writable user layer is configured. Callers
        should re-scan afterwards if they need the plugin discoverable.
        """
        self._maybe_resolve_layers()
        if self._user_dir is None:
            raise RuntimeError(
                "no writable user plugin layer; deployment not initialised"
            )
        pdir = self._user_dir / plugin_id
        manifest_path = pdir / "plugin.yaml"
        if manifest_path.exists():
            return pdir
        (pdir / "skills").mkdir(parents=True, exist_ok=True)
        doc = {
            "id": plugin_id,
            "name": name or plugin_id.replace("-", " ").replace("_", " ").title(),
            "version": "0.1.0",
            "description": description
            or "User-layer plugin holding operator-promoted skills.",
            "author": "operator",
            "skills": [],
        }
        tmp = manifest_path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        tmp.replace(manifest_path)  # atomic
        logger.info("Created user-layer plugin skeleton: %s", pdir)
        return pdir

    # ── file management plane (LB5-U2) ───────────────────────────────
    # User layer ONLY (PermissionError for system plugins, mirroring
    # uninstall): the system layer is read-only image content. Every
    # id→path resolution is containment-checked — this repo had a real
    # glob-traversal incident, so belt AND suspenders on file routes.

    def _user_plugin_dir(self, plugin_id: str) -> Path:
        """Plugin dir for the management plane. KeyError when unknown,
        PermissionError when the winning copy is system-layer."""
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise KeyError(plugin_id)
        if plugin.get("origin") != "user":
            raise PermissionError(
                f"system-layer plugin files are read-only image content: {plugin_id}"
            )
        return Path(plugin["path"]).resolve()

    @staticmethod
    def _contained(plugin_dir: Path, rel: str) -> Path:
        """Resolve rel against the plugin dir; ValueError when it escapes."""
        target = (plugin_dir / rel).resolve()
        root = plugin_dir.resolve()
        if target != root and not str(target).startswith(str(root) + os.sep):
            raise ValueError("path escapes plugin dir")
        return target

    @staticmethod
    def _write_atomic(p: Path, text: str) -> None:
        """tmp+replace write — same discipline as prompts.py."""
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)  # atomic

    def list_files(self, plugin_id: str) -> list:
        """Relative paths (files only) under a user-layer plugin dir.
        Dotfiles / __pycache__ / tmp remnants are skipped; listing errors
        degrade to what was walkable — never raise mid-walk."""
        pdir = self._user_plugin_dir(plugin_id)
        out = []
        try:
            entries = sorted(pdir.rglob("*"))
        except OSError:
            entries = []
        for p in entries:
            if not p.is_file():
                continue
            rel = p.relative_to(pdir)
            if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
                continue
            if rel.suffix == ".tmp":
                continue
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append({"path": rel.as_posix(), "size": size})
        return out

    def read_file(self, plugin_id: str, rel_path: str) -> dict:
        """Single file body from a user-layer plugin (containment-checked)."""
        pdir = self._user_plugin_dir(plugin_id)
        target = self._contained(pdir, rel_path)
        if not target.is_file():
            raise FileNotFoundError(rel_path)
        size = target.stat().st_size
        return {
            "path": rel_path,
            "name": target.name,
            "size": size,
            "body": target.read_text(encoding="utf-8", errors="replace"),
        }

    def write_file(
        self,
        plugin_id: str,
        rel_path: str,
        content: str,
        explicit_version: Optional[str] = None,
    ) -> dict:
        """Write one file into a user-layer plugin, atomically.

        plugin.yaml saves are YAML-validated first (ValueError → 400) so a
        bad edit can never break scan_plugins. Version policy (LB5-U2):
        plugin.yaml `version` is the source of truth; the FIRST save since
        the last reload patch-bumps it (dirty flag), an explicit version —
        request-body field or a changed version line inside a saved
        plugin.yaml — is always honored as-is.

        Returns {version, reload_required: True}.
        """
        pdir = self._user_plugin_dir(plugin_id)
        target = self._contained(pdir, rel_path)
        manifest_path = (pdir / "plugin.yaml").resolve()
        known = str((self._plugins.get(plugin_id) or {}).get("version") or "")

        if target == manifest_path:
            try:
                doc = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                raise ValueError(f"invalid plugin.yaml: {exc}") from exc
            if not isinstance(doc, dict):
                raise ValueError("plugin.yaml must be a YAML mapping")
            in_file = str(doc.get("version") or "")
            if explicit_version:
                content = _set_manifest_version(content, explicit_version)
                new_version = explicit_version
            elif in_file and in_file != known:
                new_version = in_file  # operator changed it in the file — honored
            elif plugin_id not in self._dirty:
                new_version = _bump_patch(in_file or known)
                content = _set_manifest_version(content, new_version)
            else:
                new_version = in_file or known
            self._write_atomic(target, content)
        else:
            self._write_atomic(target, content)
            manifest_text = manifest_path.read_text(encoding="utf-8")
            if explicit_version:
                new_version = explicit_version
                self._write_atomic(
                    manifest_path, _set_manifest_version(manifest_text, new_version)
                )
            else:
                # Current on-disk version — the registry copy is stale for
                # the rest of the reload cycle (that is the point of the
                # reload_required flag).
                try:
                    on_disk = str(
                        (yaml.safe_load(manifest_text) or {}).get("version") or known
                    )
                except yaml.YAMLError:
                    on_disk = known
                if plugin_id not in self._dirty:
                    new_version = _bump_patch(on_disk)
                    self._write_atomic(
                        manifest_path,
                        _set_manifest_version(manifest_text, new_version),
                    )
                else:
                    new_version = on_disk

        self._dirty.add(plugin_id)
        logger.info(
            "Plugin file saved: %s/%s (v%s, reload required)",
            plugin_id,
            rel_path,
            new_version,
        )
        return {"version": new_version, "reload_required": True}

    # ── install / uninstall (Phase 1.4) ─────────────────────────────

    def install_plugin(self, archive_path: Path) -> dict:
        """Install a plugin tarball into the writable user layer.

        The tarball must contain exactly one top-level directory holding a
        ``plugin.yaml``. Path traversal (absolute paths, ``..`` members) is
        rejected. Re-scans afterwards so the new plugin is immediately
        discoverable. Returns the installed plugin dict.
        """
        self._maybe_resolve_layers()
        if self._user_dir is None:
            raise RuntimeError(
                "no writable user plugin layer; deployment not initialised"
            )
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise ValueError(f"archive not found: {archive_path}")

        with tempfile.TemporaryDirectory() as td:
            staging = Path(td)
            try:
                with tarfile.open(archive_path) as tar:
                    members = tar.getmembers()
                    for m in members:
                        mp = Path(m.name)
                        if mp.is_absolute() or ".." in mp.parts:
                            raise ValueError(f"unsafe path in archive: {m.name}")
                    tar.extractall(staging)  # noqa: S202 - members vetted above
            except tarfile.TarError as exc:
                raise ValueError(f"invalid plugin archive: {exc}") from exc

            # Locate the plugin directory (the one containing plugin.yaml).
            manifests = list(staging.rglob("plugin.yaml"))
            if not manifests:
                raise ValueError("archive contains no plugin.yaml")
            if len(manifests) > 1:
                raise ValueError("archive contains multiple plugin.yaml files")
            plugin_src = manifests[0].parent

            try:
                manifest = yaml.safe_load(manifests[0].read_text()) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"invalid plugin.yaml: {exc}") from exc
            plugin_id = manifest.get("id")
            if not plugin_id:
                raise ValueError("plugin.yaml missing 'id'")

            self._user_dir.mkdir(parents=True, exist_ok=True)
            dest = self._user_dir / plugin_id
            replaced_version = None
            if dest.exists():
                # Reinstall keeps silent replace (only-add), but the previous
                # version is surfaced so the UI can flag a downgrade (LB5-U2).
                try:
                    prev = yaml.safe_load((dest / "plugin.yaml").read_text()) or {}
                    replaced_version = prev.get("version")
                except Exception:  # noqa: BLE001 — a broken prior copy is fine
                    replaced_version = None
                shutil.rmtree(dest)
            shutil.copytree(plugin_src, dest)
            logger.info("Installed plugin %s to user layer: %s", plugin_id, dest)

        self.scan_plugins()
        installed = self._plugins.get(plugin_id)
        if installed is None:
            raise RuntimeError(f"plugin {plugin_id} installed but not discoverable")
        # Copy — replaced_version is response metadata, never registry state.
        return dict(installed, replaced_version=replaced_version)

    def uninstall_plugin(self, plugin_id: str) -> None:
        """Remove a user-layer plugin. Raises PermissionError for a plugin that
        only exists in the read-only system layer, and KeyError if unknown."""
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise KeyError(plugin_id)
        if plugin.get("origin") != "user":
            raise PermissionError(f"system-layer plugin cannot be deleted: {plugin_id}")
        if self._user_dir is None:
            raise RuntimeError("no user plugin layer configured")
        dest = self._user_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        logger.info("Uninstalled user plugin %s", plugin_id)
        self.scan_plugins()

    def get_skills(self, user_message: str) -> list:
        """Find skills whose keyword triggers match the user message."""
        matched = []
        msg_lower = user_message.lower()
        for plugin in self._plugins.values():
            for skill in plugin["skills"]:
                for trigger in skill.get("triggers", []):
                    kw = trigger.get("keyword", "")
                    if kw and kw.lower() in msg_lower:
                        matched.append(skill)
                        break
        return matched

    def call_tool(
        self, plugin_id: str, tool_id: str, params: dict, sandbox=None
    ) -> dict:
        """Execute a tool function and return its result.

        If `sandbox` is provided and the tool function declares a `__sandbox`
        parameter, the sandbox instance is injected before invocation.
        """
        if plugin_id not in self._plugins:
            raise ValueError(f"Plugin not found: {plugin_id}")

        key = (plugin_id, tool_id)
        if key not in self._tools:
            raise ValueError(f"Tool not found: {plugin_id}/{tool_id}")

        entry = self._tools[key]
        func_name = entry["function"]
        func = getattr(entry["module"], func_name, None)
        if func is None:
            raise ValueError(
                f"Function '{func_name}' not found in {plugin_id}/{tool_id}"
            )

        # Inject __sandbox only if the tool declares it
        call_params = dict(params)
        if sandbox is not None:
            try:
                sig = inspect.signature(func)
                if "__sandbox" in sig.parameters:
                    call_params["__sandbox"] = sandbox
            except (TypeError, ValueError):
                pass

        try:
            return func(**call_params)
        except Exception as e:
            logger.error(f"Tool {plugin_id}/{tool_id} failed: {e}")
            raise RuntimeError(f"Tool execution failed: {e}") from e

    def get_ollama_tools(self) -> list:
        """Convert all plugin tools to Ollama's tools format."""
        ollama_tools = []
        for plugin in self._plugins.values():
            for tool in plugin["tools"]:
                properties = {}
                required = []
                for param_name, param_def in tool.get("parameters", {}).items():
                    prop = {"type": param_def.get("type", "string")}
                    if "default" in param_def:
                        prop["default"] = param_def["default"]
                    if "description" in param_def:
                        prop["description"] = param_def["description"]
                    properties[param_name] = prop
                    if param_def.get("required", False):
                        required.append(param_name)

                ollama_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{plugin['id']}__{tool['id']}",
                            "description": tool.get("description", ""),
                            "parameters": {
                                "type": "object",
                                "properties": properties,
                                "required": required,
                            },
                        },
                    }
                )
        return ollama_tools
