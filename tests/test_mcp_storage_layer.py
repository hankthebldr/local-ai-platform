"""Phase 1.3 (Track B) — MCP registry lives in the deployment user layer.

The registry JSON and any user-installed MCP binaries must sit under the
deployment's user_storage_root so they survive DMG reinstall / container
rebuild. A legacy data/config/mcp_servers.json is migrated once on init.
"""

from __future__ import annotations

import contextlib
import json


import api.services.deployment as deployment_mod
from api.services.deployment import detect_deployment
from api.services.mcp_service import MCPService
from tests.mocks.deployment.mock_host_native import patch_host_native


@contextlib.contextmanager
def _host_native_singleton(**kwargs):
    """Install a host_native deployment as the live singleton, then restore the
    previous singleton on exit so we don't leak a dead tmp path into other
    tests."""
    saved = deployment_mod._current_deployment
    with patch_host_native(**kwargs) as ctx:
        detect_deployment()  # installs the singleton via _set_current
        try:
            yield ctx
        finally:
            deployment_mod._current_deployment = saved


def test_registry_path_resolves_to_user_layer():
    with _host_native_singleton() as ctx:
        service = MCPService()
        assert service.storage_path == ctx["home"] / ".enclave" / "mcp" / "servers.json"


def test_binaries_dir_under_user_layer_created_on_access():
    with _host_native_singleton() as ctx:
        service = MCPService()
        binaries = service.binaries_dir
        assert binaries == ctx["home"] / ".enclave" / "mcp" / "binaries"
        assert binaries.is_dir()


def test_explicit_storage_path_opts_out_of_user_layer(tmp_path):
    """An explicit storage_path (the test convention) bypasses deployment
    resolution AND legacy migration."""
    explicit = tmp_path / "custom.json"
    service = MCPService(storage_path=explicit)
    assert service.storage_path == explicit


def test_legacy_registry_migrates_to_user_layer(monkeypatch, tmp_path):
    # Seed a legacy data/config/mcp_servers.json via DATA_CONFIG_DIR override.
    legacy_dir = tmp_path / "legacy_config"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "mcp_servers.json"
    legacy_file.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "legacy-fs",
                        "name": "Legacy FS",
                        "transport": "stdio",
                        "command": "/usr/bin/echo",
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("DATA_CONFIG_DIR", str(legacy_dir))

    with _host_native_singleton() as ctx:
        service = MCPService()
        # Migrated file exists in the user layer …
        user_file = ctx["home"] / ".enclave" / "mcp" / "servers.json"
        assert user_file.exists()
        # … and the entry was loaded.
        assert service.has_server("legacy-fs")


def test_migration_skipped_when_user_file_present(monkeypatch, tmp_path):
    """If the user-layer file already exists, the legacy file is left alone and
    the user file wins (operator intent)."""
    legacy_dir = tmp_path / "legacy_config"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "mcp_servers.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "legacy",
                        "name": "L",
                        "transport": "stdio",
                        "command": "echo",
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("DATA_CONFIG_DIR", str(legacy_dir))

    with _host_native_singleton() as ctx:
        user_file = ctx["home"] / ".enclave" / "mcp" / "servers.json"
        user_file.parent.mkdir(parents=True, exist_ok=True)
        user_file.write_text(
            json.dumps(
                {
                    "servers": [
                        {
                            "id": "user-only",
                            "name": "U",
                            "transport": "stdio",
                            "command": "echo",
                        }
                    ]
                }
            )
        )
        service = MCPService()
        assert service.has_server("user-only")
        assert not service.has_server("legacy")


def test_has_server_and_has_tool_for_unknown(tmp_path):
    service = MCPService(storage_path=tmp_path / "mcp.json")
    assert service.has_server("nope") is False
    assert service.has_tool("nope", "whatever") is False
    assert service.is_reachable("nope") is False
