#!/usr/bin/env python3
"""
Plugin Service — Discovery, loading, skill matching, tool invocation
"""

from __future__ import annotations

import importlib.util
import sys
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
                skill_path = child / skill_def["file"]
                if skill_path.exists():
                    parsed = _parse_skill_md(skill_path)
                    skills.append({
                        "id": skill_def["id"],
                        "triggers": skill_def.get("triggers", []),
                        **parsed,
                    })
                else:
                    logger.warning(f"Skill file not found: {skill_path}")

            # Pre-load tool modules
            tools = []
            for tool_def in manifest.get("tools", []):
                tool_path = child / tool_def["file"]
                if tool_path.exists():
                    module = self._load_tool_module(plugin_id, tool_def["id"], tool_path)
                    if module:
                        self._tools[(plugin_id, tool_def["id"])] = {
                            "module": module,
                            "function": tool_def.get("function", "execute"),
                        }
                    tools.append({
                        "id": tool_def["id"],
                        "description": tool_def.get("description", ""),
                        "parameters": tool_def.get("parameters", {}),
                    })
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
        """Dynamically load a Python tool module."""
        module_name = f"plugin_{plugin_id}_{tool_id}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
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

    def call_tool(self, plugin_id: str, tool_id: str, params: dict) -> dict:
        """Execute a tool function and return its result."""
        if plugin_id not in self._plugins:
            raise ValueError(f"Plugin not found: {plugin_id}")

        key = (plugin_id, tool_id)
        if key not in self._tools:
            raise ValueError(f"Tool not found: {plugin_id}/{tool_id}")

        entry = self._tools[key]
        func = getattr(entry["module"], entry["function"])
        return func(**params)
