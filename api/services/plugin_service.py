#!/usr/bin/env python3
"""
Plugin Service — Discovery, loading, skill matching, tool invocation
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
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


class PluginService:
    """Discovers and manages plugins from a directory convention"""

    def __init__(self, plugins_dir: Optional[str] = None):
        self._dir = Path(plugins_dir) if plugins_dir else Path("plugins")
        self._plugins: dict = {}
        self._tools: dict = {}

    def scan_plugins(self) -> list:
        """Scan the plugins directory for valid plugins."""
        self._plugins.clear()
        self._tools.clear()

        if not self._dir.exists():
            logger.warning(f"Plugins directory not found: {self._dir}")
            return []

        found = []
        for child in sorted(self._dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith("_"):
                continue

            manifest_path = child / "plugin.yaml"
            if not manifest_path.exists():
                logger.warning(f"Skipping {child.name}: no plugin.yaml")
                continue

            try:
                manifest = yaml.safe_load(manifest_path.read_text())
            except yaml.YAMLError as e:
                logger.error(f"Invalid YAML in {manifest_path}: {e}")
                continue

            plugin_id = manifest.get("id", child.name)

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
                    module = self._load_tool_module(
                        plugin_id, tool_def["id"], tool_path
                    )
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
            }
            self._plugins[plugin_id] = plugin_data
            found.append(plugin_data)
            logger.info(
                f"Loaded plugin: {plugin_id} "
                f"({len(skills)} skills, {len(tools)} tools)"
            )

        return found

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
