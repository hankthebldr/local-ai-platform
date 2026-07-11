#!/usr/bin/env python3
"""
Plugins Router — List, install, and invoke plugin tools.

Discovery walks two layers (Phase 1.2): the read-only system layer that ships
with the app/image and the writable user layer under the deployment's
user_storage_root. ``PLUGINS_DIR`` overrides the system layer (used by tests);
otherwise both layers are resolved from the active Deployment.
"""

import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key
from ..models.plugin_models import PluginFileSet, PluginFileWrite, PluginSpecDraft
from ..services.ollama_service import OllamaService
from ..services.plugin_forge import PluginForgeService
from ..services.plugin_service import PluginService

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _build_service() -> PluginService:
    """Construct a PluginService over (system, user) layers.

    PLUGINS_DIR pins the system layer when set; the user layer always comes
    from the active deployment so installs land somewhere writable. If the
    deployment singleton isn't installed yet, PluginService falls back to its
    own auto-resolution.
    """
    system_override = os.getenv("PLUGINS_DIR")
    user_dir = None
    try:
        from ..services.deployment import _get_current as _get_dep

        d = _get_dep()
        user_dir = d.user_storage_root / "plugins"
        system_dir = (
            Path(system_override)
            if system_override
            else (d.system_storage_root / "plugins")
        )
    except Exception:
        system_dir = Path(system_override) if system_override else None

    if system_dir is None and user_dir is None:
        return PluginService()
    return PluginService(system_dir=system_dir, user_dir=user_dir)


plugin_service = _build_service()
plugin_service.scan_plugins()


def _with_layer(plugin: dict) -> dict:
    """Annotate the physical layer (LB0-U3 provenance seam).

    ``layer`` mirrors the existing ``origin`` field (system|user) — the
    Library shell's uniform provenance vocabulary reads ``layer`` while every
    pre-existing consumer of ``origin`` keeps working (only-add)."""
    rec = dict(plugin)
    rec["layer"] = rec.get("origin")
    return rec


@router.get("", dependencies=[Depends(require_master_key)])
async def list_plugins():
    """List all discovered plugins (each carries origin + layer: system|user)."""
    return [_with_layer(p) for p in plugin_service.list_plugins()]


@router.post("/reload", dependencies=[Depends(require_master_key)])
async def reload_plugins():
    """Re-scan the plugin layers in-process so newly installed/imported skills
    and tools activate WITHOUT an API restart. The chat path reads this same
    PluginService singleton live (chat.py: _plugin_service.get_skills(...)), so
    reloaded skills inject on the very next turn."""
    plugin_service.scan_plugins()
    plugins = plugin_service.list_plugins()
    return {
        "reloaded": True,
        "plugins": len(plugins),
        "skills": sum(len(p.get("skills") or []) for p in plugins),
        "tools": sum(len(p.get("tools") or []) for p in plugins),
    }


@router.post("/install", dependencies=[Depends(require_master_key)])
async def install_plugin(plugin: UploadFile = File(...)):
    """Install a plugin tarball into the writable user layer."""
    suffix = "".join(Path(plugin.filename or "plugin.tar.gz").suffixes) or ".tar.gz"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            shutil.copyfileobj(plugin.file, fh)
            tmp = Path(fh.name)
        installed = plugin_service.install_plugin(tmp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp and tmp.exists():
            tmp.unlink()
    # Reinstall stays a silent replace (only-add), but the previous version
    # rides the response so the UI can surface a downgrade (LB5-U2).
    replaced_version = installed.pop("replaced_version", None)
    return {
        "installed": installed["id"],
        "plugin": _with_layer(installed),
        "replaced_version": replaced_version,
    }


@router.get("/{plugin_id}", dependencies=[Depends(require_master_key)])
async def get_plugin(plugin_id: str):
    """Get plugin details."""
    plugin = plugin_service.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return _with_layer(plugin)


@router.delete("/{plugin_id}", dependencies=[Depends(require_master_key)])
async def uninstall_plugin(plugin_id: str):
    """Remove a user-layer plugin. System-layer plugins are protected (403)."""
    try:
        plugin_service.uninstall_plugin(plugin_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Plugin not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"deleted": plugin_id}


# ── File management plane (LB5-U2) ──────────────────────────────────────
# GET  /{id}/files            relative file paths + current version
# GET  /{id}/files/{path}     single file body
# PUT  /{id}/files/{path}     atomic write + version policy + reload flag
#
# User layer only — system plugins 403 (mirroring uninstall). Every path is
# charset-allowlisted per segment AND containment-checked in the service
# (prompts.py _path / skills.py file-route discipline: this repo had a real
# glob-traversal incident, so belt AND suspenders).

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
# "." and ".." both match the charset, so they are rejected explicitly below.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9.+-]{1,32}$")
_FILE_BYTES_MAX = 1_000_000  # single-file read cap for the Files tab


def _checked_plugin_id(plugin_id: str) -> str:
    if not _ID_RE.match(plugin_id or ""):
        raise HTTPException(status_code=400, detail="invalid plugin id")
    return plugin_id


def _checked_rel_path(path: str) -> str:
    path = (path or "").strip()
    if not path or len(path) > 512 or "\\" in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid path")
    for segment in path.split("/"):
        if segment in ("", ".", "..") or not _SEGMENT_RE.match(segment):
            raise HTTPException(status_code=400, detail="invalid path segment")
    return path


def _user_files_errors(exc: Exception) -> HTTPException:
    """Map service errors onto the management-plane status contract."""
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Plugin not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="file not found")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/{plugin_id}/files", dependencies=[Depends(require_master_key)])
async def list_plugin_files(plugin_id: str):
    """Relative file paths of a user-layer plugin (403 for system layer)."""
    _checked_plugin_id(plugin_id)
    try:
        files = plugin_service.list_files(plugin_id)
    except Exception as exc:  # noqa: BLE001 — mapped onto the status contract
        raise _user_files_errors(exc)
    plugin = plugin_service.get_plugin(plugin_id) or {}
    return {
        "plugin_id": plugin_id,
        "layer": plugin.get("origin"),
        "version": plugin.get("version"),
        "files": files,
    }


@router.get(
    "/{plugin_id}/files/{path:path}", dependencies=[Depends(require_master_key)]
)
async def read_plugin_file(plugin_id: str, path: str):
    """Single file body for the Files tab editor (user layer only)."""
    _checked_plugin_id(plugin_id)
    path = _checked_rel_path(path)
    try:
        rec = plugin_service.read_file(plugin_id, path)
    except Exception as exc:  # noqa: BLE001
        raise _user_files_errors(exc)
    if rec["size"] > _FILE_BYTES_MAX:
        raise HTTPException(status_code=413, detail="file too large to edit inline")
    return {"plugin_id": plugin_id, **rec}


@router.put(
    "/{plugin_id}/files/{path:path}", dependencies=[Depends(require_master_key)]
)
async def write_plugin_file(plugin_id: str, path: str, req: PluginFileWrite):
    """Save one file into a user-layer plugin (atomic tmp+replace).

    plugin.yaml saves are YAML-validated (400 on malformed) so scan_plugins
    cannot be broken by a bad edit. Responds {version, reload_required:true}
    — the edit activates on the next POST /api/plugins/reload.
    """
    _checked_plugin_id(plugin_id)
    path = _checked_rel_path(path)
    if req.version is not None and not _VERSION_RE.match(req.version):
        raise HTTPException(status_code=400, detail="invalid version string")
    try:
        result = plugin_service.write_file(
            plugin_id, path, req.content, explicit_version=req.version
        )
    except Exception as exc:  # noqa: BLE001
        raise _user_files_errors(exc)
    return {"saved": True, "plugin_id": plugin_id, "path": path, **result}


# ── Tool test harness (LB1-U1) ──────────────────────────────────────────


_SECRETISH_RE = re.compile(r"key|token|secret|password|credential", re.IGNORECASE)


def _mask_secretish(d: dict) -> dict:
    """Mask values whose key names look secret-bearing. The test route must
    never echo API keys back to the pane — the operator already has them."""
    return {k: ("***" if _SECRETISH_RE.search(k) else v) for k, v in d.items()}


def _saved_tool_settings() -> dict:
    """The platform's persisted tool-settings store.

    Today that is the search settings document (data/config/search_settings.json)
    — the websearch worked example promotes overrides back through the (now
    master-key-gated) POST /api/inventory/settings/search route. The LB5
    management plane generalizes per-plugin settings later; this helper is the
    single seam it will replace. Computed/masked display fields are stripped so
    the merge operates on raw setting keys only.
    """
    try:
        from ..services.search_service import get_config

        cfg = dict(get_config())
        cfg.pop("brave_api_key_masked", None)
        cfg.pop("active_backend", None)
        return cfg
    except Exception as e:  # noqa: BLE001 — settings store is optional context
        logger.debug(f"tool test: saved settings unavailable: {e}")
        return {}


class ToolTestRequest(BaseModel):
    """One dry-run tool invocation from the Library Test pane.

    ``config_overrides`` is merged over the saved settings for THIS call only
    — nothing persists (promote is a separate, Confirm-gated write through the
    settings route). Merged config keys that match the tool's declared
    parameters fill in call params the operator didn't set explicitly.
    """

    params: dict = Field(default_factory=dict)
    config_overrides: dict = Field(default_factory=dict)


@router.post(
    "/{plugin_id}/tools/{tool_id}/test",
    dependencies=[Depends(require_master_key)],
)
async def test_tool(plugin_id: str, tool_id: str, req: ToolTestRequest):
    """Test-run a plugin tool with session-local config overrides.

    Returns {status, result, latency_ms, meta}. Execution failures come back
    as status="error" (the harness wants to display them, not 500). The
    sandbox divergence is surfaced in meta, never hidden: this route invokes
    the tool in-process with sandbox=None, while chat-path tool calls may run
    under the profile's sandbox (tool_executor.py).
    """
    plugin = plugin_service.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    tool = next((t for t in plugin.get("tools", []) if t.get("id") == tool_id), None)
    if tool is None or not plugin_service.has_tool(plugin_id, tool_id):
        raise HTTPException(status_code=404, detail="Tool not found")

    # Effective config: session overrides win over saved settings. Never
    # persisted — the saved store is read-only in this path.
    saved = _saved_tool_settings()
    effective = {**saved, **(req.config_overrides or {})}

    # Fill declared tool params from the effective config where the operator
    # didn't pass an explicit value (e.g. websearch max_results).
    call_params = dict(req.params or {})
    injected_from_config = {}
    for name in tool.get("parameters", {}):
        if name not in call_params and name in effective:
            call_params[name] = effective[name]
            injected_from_config[name] = effective[name]

    started = time.perf_counter()
    status, result, error = "ok", None, None
    try:
        result = plugin_service.call_tool(plugin_id, tool_id, call_params, sandbox=None)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        status, error = "error", str(e)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    response = {
        "status": status,
        "result": result,
        "latency_ms": latency_ms,
        "meta": {
            "sandbox": None,
            "sandbox_divergence": (
                "tool executed in-process with sandbox=None; chat-path tool "
                "calls may run under the active profile's sandbox"
            ),
            "overrides_applied": sorted((req.config_overrides or {}).keys()),
            "params_from_config": _mask_secretish(injected_from_config),
            "persisted": False,
        },
    }
    if error is not None:
        response["error"] = error
    return response


@router.post("/{plugin_id}/tools/{tool_id}", dependencies=[Depends(require_master_key)])
async def invoke_tool(plugin_id: str, tool_id: str, params: dict):
    """Invoke a plugin tool."""
    try:
        result = plugin_service.call_tool(plugin_id, tool_id, params)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ── Creation forge (LB5-U3) ──────────────────────────────────────────────
# POST /scaffold/spec      NL description → editable PluginSpecDraft
# POST /scaffold/generate  spec → reviewable PluginFileSet (nothing written)
# POST /scaffold/install   reviewed file set → user layer + scan_plugins()
#
# The whole pipeline runs on LOCAL models (OllamaService + ModelResolver;
# deterministic fallback when the model is down — the wizard never 5xxs on
# a cold box). Every route is master-key gated. Skills-only by default:
# tool stubs are an explicit opt-in and every *.py in the reviewed set
# passes the denylisted-imports lint at install time (tools run in-process).
# No path conflicts: "scaffold" matches _ID_RE, but the /{plugin_id} routes
# above are GET/DELETE/PUT — these are POST-only.


def _forge() -> PluginForgeService:
    return PluginForgeService(OllamaService(OLLAMA_HOST))


class ScaffoldSpecRequest(BaseModel):
    """Operator description → draft spec. ``allow_tools`` is the explicit
    opt-in; without it the local model is told to propose zero tools."""

    description: str
    name: str = ""
    allow_tools: bool = False
    model: Optional[str] = None
    role: Optional[str] = "reasoning"


class ScaffoldGenerateRequest(BaseModel):
    """(Edited) spec → file set. ``include_tools`` re-confirms the opt-in at
    generation time — a seeded spec carrying tools still needs it."""

    spec: PluginSpecDraft
    include_tools: bool = False


@router.post("/scaffold/spec", dependencies=[Depends(require_master_key)])
async def scaffold_spec(req: ScaffoldSpecRequest):
    """Draft a plugin spec from a natural-language description (local model;
    deterministic one-skill/zero-tools fallback when the model is down)."""
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="description is required")
    draft = _forge().draft_spec(
        req.description,
        name=req.name,
        allow_tools=req.allow_tools,
        model=req.model,
        role=req.role,
    )
    return draft.model_dump()


@router.post("/scaffold/generate", dependencies=[Depends(require_master_key)])
async def scaffold_generate(req: ScaffoldGenerateRequest):
    """Materialize a (possibly operator-edited) spec into a reviewable file
    set. Nothing is written — install is a separate, reviewed step."""
    try:
        file_set = _forge().generate_files(req.spec, include_tools=req.include_tools)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return file_set.model_dump()


@router.post("/scaffold/install", dependencies=[Depends(require_master_key)])
async def scaffold_install(file_set: PluginFileSet):
    """Install a reviewed file set into the user layer (409 on existing id,
    charset-allowlisted ids, containment on every path, atomic writes,
    denylist lint on every *.py), then re-scan so it registers immediately."""
    try:
        installed = _forge().install(plugin_service, file_set)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"installed": installed["id"], "plugin": _with_layer(installed)}
