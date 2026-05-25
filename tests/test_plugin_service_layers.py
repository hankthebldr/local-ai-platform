"""Track B / Phase 1.2 — PluginService two-layer (system + user) discovery.

Verifies the OOTB + user-installed overlay pattern: system layer ships
with the app/image, user layer is what the operator installs. On id
collision, user wins, and the winning plugin dict is annotated with
origin + overrides_system so the UI can show which layer served the
plugin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.services.plugin_service import PluginService


def _write_minimal_plugin(
    plugin_dir: Path, plugin_id: str, name: str, version: str = "1.0"
):
    """Write a plugin.yaml with no skills/tools — just enough to be loaded.

    Version is quoted in YAML so 2.0 / 1.0 aren't coerced to floats.
    """
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        f"id: {plugin_id}\n"
        f"name: {name}\n"
        f'version: "{version}"\n'
        "skills: []\n"
        "tools: []\n"
    )


# ── two-layer walk ──────────────────────────────────────────────────────


def test_plugin_discovery_walks_both_layers(tmp_path):
    """System ships OOTB; user installs separate plugin. Both visible."""
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    _write_minimal_plugin(system / "ootb-plugin", "ootb-plugin", "OOTB")
    _write_minimal_plugin(user / "my-plugin", "my-plugin", "Mine")

    service = PluginService(system_dir=system, user_dir=user)
    plugins = service.scan_plugins()
    ids = {p["id"]: p for p in plugins}
    assert "ootb-plugin" in ids
    assert "my-plugin" in ids
    assert ids["ootb-plugin"]["origin"] == "system"
    assert ids["my-plugin"]["origin"] == "user"
    assert ids["ootb-plugin"]["overrides_system"] is False
    assert ids["my-plugin"]["overrides_system"] is False


def test_user_plugin_overrides_system_on_same_id(tmp_path):
    """Same plugin id in both layers — user wins, override flag set."""
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    _write_minimal_plugin(system / "shared", "shared", "SystemShared", version="1.0")
    _write_minimal_plugin(user / "shared", "shared", "UserShared", version="2.0")

    service = PluginService(system_dir=system, user_dir=user)
    plugins = {p["id"]: p for p in service.scan_plugins()}
    assert plugins["shared"]["name"] == "UserShared"
    assert plugins["shared"]["version"] == "2.0"
    assert plugins["shared"]["origin"] == "user"
    assert plugins["shared"]["overrides_system"] is True


def test_system_only_when_user_dir_missing(tmp_path):
    """User dir doesn't exist (fresh install) — system plugins still load."""
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"  # not created
    _write_minimal_plugin(system / "ootb", "ootb", "OOTB")

    service = PluginService(system_dir=system, user_dir=user)
    plugins = service.scan_plugins()
    assert len(plugins) == 1
    assert plugins[0]["id"] == "ootb"
    assert plugins[0]["origin"] == "system"


def test_user_only_when_system_dir_missing(tmp_path):
    """System dir missing (degraded) — user plugins still load."""
    system = tmp_path / "system" / "plugins"  # not created
    user = tmp_path / "user" / "plugins"
    _write_minimal_plugin(user / "mine", "mine", "Mine")

    service = PluginService(system_dir=system, user_dir=user)
    plugins = service.scan_plugins()
    assert len(plugins) == 1
    assert plugins[0]["origin"] == "user"


def test_both_empty_returns_empty_list(tmp_path):
    system = tmp_path / "system" / "plugins"
    system.mkdir(parents=True)
    user = tmp_path / "user" / "plugins"
    user.mkdir(parents=True)

    service = PluginService(system_dir=system, user_dir=user)
    assert service.scan_plugins() == []


def test_scan_is_idempotent(tmp_path):
    """Calling scan_plugins twice produces the same result (no duplication)."""
    system = tmp_path / "system" / "plugins"
    _write_minimal_plugin(system / "a", "a", "A")
    _write_minimal_plugin(system / "b", "b", "B")

    service = PluginService(system_dir=system, user_dir=tmp_path / "u")
    first = service.scan_plugins()
    second = service.scan_plugins()
    assert {p["id"] for p in first} == {p["id"] for p in second}
    assert len(first) == len(second) == 2


# ── backwards compatibility ─────────────────────────────────────────────


def test_legacy_plugins_dir_still_works(tmp_path):
    """Constructing with the old `plugins_dir=` arg treats it as system layer."""
    base = tmp_path / "plugins"
    _write_minimal_plugin(base / "legacy", "legacy", "Legacy")

    service = PluginService(plugins_dir=str(base))
    plugins = service.scan_plugins()
    assert len(plugins) == 1
    assert plugins[0]["origin"] == "system"  # treated as system layer


def test_underscore_dirs_are_skipped(tmp_path):
    """Directories starting with _ are skipped (legacy convention preserved)."""
    system = tmp_path / "system" / "plugins"
    _write_minimal_plugin(system / "_hidden", "hidden", "Hidden")
    _write_minimal_plugin(system / "visible", "visible", "Visible")

    service = PluginService(system_dir=system, user_dir=tmp_path / "u")
    ids = {p["id"] for p in service.scan_plugins()}
    assert ids == {"visible"}


def test_user_override_clears_system_tools(tmp_path):
    """When user plugin overrides system, the system plugin's tools are
    no longer reachable via get_tool — only the user plugin's tools win."""
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"

    # System version has a tool
    sys_plugin = system / "shared"
    sys_plugin.mkdir(parents=True)
    (sys_plugin / "plugin.yaml").write_text(
        "id: shared\n"
        "name: SystemShared\n"
        "version: 1.0\n"
        "skills: []\n"
        "tools:\n"
        "  - id: old_tool\n"
        "    file: old_tool.py\n"
    )
    (sys_plugin / "old_tool.py").write_text("def execute(): return 'system'\n")

    # User version has a different tool
    usr_plugin = user / "shared"
    usr_plugin.mkdir(parents=True)
    (usr_plugin / "plugin.yaml").write_text(
        "id: shared\n"
        "name: UserShared\n"
        "version: 2.0\n"
        "skills: []\n"
        "tools:\n"
        "  - id: new_tool\n"
        "    file: new_tool.py\n"
    )
    (usr_plugin / "new_tool.py").write_text("def execute(): return 'user'\n")

    service = PluginService(system_dir=system, user_dir=user)
    service.scan_plugins()
    # Only the user plugin's tool should be registered
    assert ("shared", "new_tool") in service._tools
    assert ("shared", "old_tool") not in service._tools
