"""Phase 7.1 — GET /api/system/extensions: one-stop view of the extension
subsystem.

The endpoint synthesises Phase 1 (deployment storage layering), Phase 2
(MCP runner pool), and Phase 3 (health monitor) into a single operator
dashboard payload. Tests verify it surfaces deployment-correct paths on
each form factor and tolerates a missing pool.
"""

from __future__ import annotations

import contextlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.services.deployment as deployment_mod
from api.routers.system import router as system_router
from api.services.deployment import detect_deployment
from api.services.mcp_runner_pool import reset_mcp_runner_pool
from api.services.mcp_service import reset_mcp_service
from tests.mocks.deployment.mock_host_native import patch_host_native
from tests.mocks.deployment.mock_container import patch_container


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(system_router)
    return app


@contextlib.contextmanager
def _isolated_deployment(patcher):
    """Install a fresh deployment + MCP singletons, run, restore prior state.

    Earlier tests in the suite may have cached an MCPService against a
    different deployment's storage root (the singleton survives across
    tests). We reset both the deployment and the MCP service so the
    /extensions endpoint sees deployment-correct paths.
    """
    saved = deployment_mod._current_deployment
    reset_mcp_service()
    reset_mcp_runner_pool()
    try:
        with patcher as ctx:
            detect_deployment()
            yield ctx
    finally:
        deployment_mod._current_deployment = saved
        reset_mcp_service()
        reset_mcp_runner_pool()


# ── happy path on host_native ─────────────────────────────────────────


def test_extensions_endpoint_returns_host_native_paths():
    with _isolated_deployment(patch_host_native()) as ctx:
        client = TestClient(_make_app())
        r = client.get("/api/system/extensions")
        assert r.status_code == 200
        body = r.json()

        assert body["deployment"] == "host_native"
        # Plugin paths point at the deployment-resolved layers.
        home = str(ctx["home"])
        assert body["plugin_paths"]["user"].startswith(home)
        assert body["plugin_paths"]["user"].endswith("/.enclave/plugins")
        # User dir should be writable (tmp dir we own).
        assert body["plugin_paths"]["user_writable"] is True
        # MCP registry under the user layer.
        assert body["mcp"]["registry_path"].endswith("/.enclave/mcp/servers.json")
        assert body["mcp"]["binaries_dir"].endswith("/.enclave/mcp/binaries")
        # Pool exists and is empty (no workflow has acquired anything).
        assert body["mcp"]["pool"]["active_runners"] == 0
        assert body["mcp"]["pool"]["runners"] == []
        assert body["mcp"]["pool"]["total_overhead_mb"] == 0.0
        # Cache paths.
        assert body["cache"]["plugins_cache"].endswith("plugins.cache.json")
        assert body["cache"]["mcp_tools_cache"].endswith("mcp-tools.cache.json")


# ── container deployment surfaces /app + /app/data ─────────────────────


def test_extensions_endpoint_returns_container_paths():
    with _isolated_deployment(patch_container()):
        client = TestClient(_make_app())
        r = client.get("/api/system/extensions")
        assert r.status_code == 200
        body = r.json()
        assert body["deployment"] == "container"
        # System layer = /app/plugins; user layer = /app/data/plugins.
        assert body["plugin_paths"]["system"] == "/app/plugins"
        assert body["plugin_paths"]["user"].endswith("/plugins")
        # The container fixture points user_storage_root at a tmp dir;
        # /app/data should remain present in the path though.
        # MCP registry under user layer.
        assert "mcp/servers.json" in body["mcp"]["registry_path"]


# ── live pool state surfaces in /extensions ───────────────────────────


def test_extensions_endpoint_reports_active_runners():
    """Acquire a warm runner; /extensions should reflect it in pool block."""
    import sys
    from pathlib import Path

    from api.models.mcp_models import MCPServerCreate
    from api.services.mcp_runner_pool import get_mcp_runner_pool
    from api.services.mcp_service import get_mcp_service

    fake_server = Path(__file__).parent / "mocks" / "mcp" / "fake_server.py"

    with _isolated_deployment(patch_host_native()):
        svc = get_mcp_service()
        svc.register(
            MCPServerCreate(
                id="fake",
                name="Fake",
                transport="stdio",
                command=sys.executable,
                args=[str(fake_server)],
            )
        )
        pool = get_mcp_runner_pool()
        pool.attach_service(svc)
        runner = pool.acquire("run-X", "fake")
        try:
            client = TestClient(_make_app())
            r = client.get("/api/system/extensions")
            assert r.status_code == 200
            body = r.json()
            assert body["mcp"]["pool"]["active_runners"] == 1
            assert body["mcp"]["registered_count"] == 1
            entries = body["mcp"]["pool"]["runners"]
            assert len(entries) == 1
            assert entries[0]["run_id"] == "run-X"
            assert entries[0]["server_id"] == "fake"
            assert entries[0]["pid"] == runner.pid
            # rss_mb may be None on platforms where psutil can't read; just
            # confirm the key exists.
            assert "rss_mb" in entries[0]
            # Overhead is non-zero since a python subprocess is live.
            assert body["mcp"]["pool"]["total_overhead_mb"] >= 1.0
        finally:
            pool.release_workflow("run-X")


# ── failure modes ──────────────────────────────────────────────────────


def test_extensions_endpoint_503_when_deployment_not_initialized():
    """If detect_deployment() hasn't run, the endpoint refuses to guess."""
    saved = deployment_mod._current_deployment
    deployment_mod._current_deployment = None
    try:
        client = TestClient(_make_app())
        r = client.get("/api/system/extensions")
        assert r.status_code == 503
        assert "deployment not initialized" in r.json()["detail"]
    finally:
        deployment_mod._current_deployment = saved
