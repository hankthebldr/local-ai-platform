#!/usr/bin/env python3
"""
Profile Service — YAML-declared policy for which plugins/tools are available.

Profiles live in data/profiles/*.yaml. Resolution priority:
  1. X-Profile-ID header
  2. API key binding
  3. DEFAULT_PROFILE env var
  4. "default" profile
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger


class ProfileService:
    """Loads and queries agent permission profiles."""

    def __init__(self, profiles_dir: Optional[str] = None):
        self._dir = Path(profiles_dir) if profiles_dir else Path("data/profiles")
        self._profiles: dict = {}

    def load_profiles(self) -> list:
        """Scan the profiles directory and load all YAML files."""
        self._profiles.clear()
        if not self._dir.exists():
            logger.warning(f"Profiles directory not found: {self._dir}")
            return []

        loaded = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if not isinstance(data, dict) or "id" not in data:
                    logger.error(f"Invalid profile (missing id): {path}")
                    continue
                self._profiles[data["id"]] = data
                loaded.append(data)
                logger.info(f"Loaded profile: {data['id']}")
            except yaml.YAMLError as e:
                logger.error(f"Invalid YAML in {path}: {e}")
        return loaded

    def reload(self) -> list:
        """Re-scan the profiles directory."""
        return self.load_profiles()

    def get_profile(self, profile_id: str) -> Optional[dict]:
        return self._profiles.get(profile_id)

    def list_profiles(self) -> list:
        return list(self._profiles.values())

    def resolve(self, header: Optional[str], key_id: Optional[str]) -> str:
        """
        Resolve which profile to use.
        Priority: header > key binding > DEFAULT_PROFILE env > "default".
        Falls back to "default" if resolved ID doesn't exist.
        """
        if header and header in self._profiles:
            return header
        if key_id:
            for pid, profile in self._profiles.items():
                if key_id in (profile.get("bound_to_keys") or []):
                    return pid
        env_profile = os.getenv("DEFAULT_PROFILE", "default")
        if env_profile in self._profiles:
            return env_profile
        if "default" in self._profiles:
            return "default"
        if self._profiles:
            return next(iter(self._profiles))
        logger.warning("No profiles loaded — returning 'default' by convention")
        return "default"

    def is_tool_allowed(self, plugin_id: str, tool_id: str, profile_id: str) -> bool:
        """Check if a specific tool invocation is permitted by the profile."""
        profile = self.get_profile(profile_id)
        if profile is None:
            return False

        allowed_plugins = profile.get("allowed_plugins", [])
        if "*" not in allowed_plugins and plugin_id not in allowed_plugins:
            return False

        tool_rules = profile.get("tool_rules") or {}
        plugin_rule = tool_rules.get(plugin_id)
        if plugin_rule:
            allowed_tools = plugin_rule.get("allowed_tools")
            if allowed_tools is not None and tool_id not in allowed_tools:
                return False

        return True

    def filter_tools(self, ollama_tools: list, profile_id: str) -> list:
        """Remove disallowed tools from an Ollama-format tool list."""
        filtered = []
        for tool in ollama_tools:
            name = tool.get("function", {}).get("name", "")
            parts = name.split("__", 1)
            if len(parts) != 2:
                continue
            plugin_id, tool_id = parts
            if self.is_tool_allowed(plugin_id, tool_id, profile_id):
                filtered.append(tool)
        return filtered
