"""Phase 6 — arch-scheduler integration: effective_memory_gb subtracts the
live MCP runner-pool RSS overhead.

The runner pool already exposes ``total_runner_overhead_mb()`` (Phase 2);
Phase 6 wires it into every ``Deployment.effective_memory_gb()`` impl so
the scheduler / dashboard / system endpoint see the true free budget.
The ``mcp_overhead_gb()`` module-level helper is the shared accessor.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from api.models.mcp_models import MCPServerCreate
from api.services.deployment import mcp_overhead_gb
from api.services.mcp_runner_pool import (
    get_mcp_runner_pool,
    reset_mcp_runner_pool,
)
from api.services.mcp_service import MCPService, reset_mcp_service
from tests.mocks.deployment.mock_container import patch_container
from tests.mocks.deployment.mock_dmg import patch_dmg
from tests.mocks.deployment.mock_host_native import patch_host_native

FAKE_SERVER = Path(__file__).parent / "mocks" / "mcp" / "fake_server.py"


@pytest.fixture(autouse=True)
def _hermetic():
    """Each test starts with a fresh pool + service singleton so prior tests
    don't carry over warm runners or stale service handles."""
    reset_mcp_runner_pool()
    reset_mcp_service()
    yield
    reset_mcp_runner_pool()
    reset_mcp_service()


# ── mcp_overhead_gb helper ───────────────────────────────────────────


def test_mcp_overhead_zero_with_no_pool_state():
    """No workflow has spawned a runner → overhead is 0."""
    assert mcp_overhead_gb() == 0.0


def test_mcp_overhead_zero_when_pool_module_init_fails(monkeypatch):
    """If get_mcp_runner_pool() blows up, overhead is reported as 0 — accounting
    failures must never block a memory query."""
    import api.services.deployment as deployment_mod

    def boom():
        raise RuntimeError("simulated init crash")

    monkeypatch.setattr(
        deployment_mod, "mcp_overhead_gb", deployment_mod.mcp_overhead_gb
    )
    # Inject a failing get_mcp_runner_pool via the module the helper imports.
    monkeypatch.setattr("api.services.mcp_runner_pool.get_mcp_runner_pool", boom)
    assert mcp_overhead_gb() == 0.0


def test_mcp_overhead_reflects_live_runners(tmp_path):
    """An acquired warm runner shows up in overhead_gb."""
    svc = MCPService(storage_path=tmp_path / "mcp.json")
    svc.register(
        MCPServerCreate(
            id="fake",
            name="Fake",
            transport="stdio",
            command=sys.executable,
            args=[str(FAKE_SERVER)],
        )
    )
    pool = get_mcp_runner_pool()
    pool.attach_service(svc)
    pool.acquire("run-A", "fake")
    try:
        # The fake server is a python subprocess; expect non-trivial RSS.
        overhead = mcp_overhead_gb()
        assert overhead > 0.0
        # Sanity bound — python interpreter on this box shouldn't push past
        # 1 GB; keeps the assertion meaningful while leaving headroom.
        assert overhead < 1.0
    finally:
        pool.release_workflow("run-A")
    # After release the overhead drops back to zero.
    assert mcp_overhead_gb() == 0.0


# ── effective_memory_gb subtraction across deployment impls ──────────


def _stub_overhead(monkeypatch, gb: float):
    """Pretend the pool holds ``gb`` GB of warm runners regardless of state.

    The deployment impls call ``from ..deployment import mcp_overhead_gb`` at
    method-call time, so we patch the symbol on the deployment module itself.
    """
    import api.services.deployment as deployment_mod

    monkeypatch.setattr(deployment_mod, "mcp_overhead_gb", lambda: gb)


def test_dmg_effective_memory_subtracts_mcp_overhead(monkeypatch):
    with patch_dmg(host_memory_gb=48.0):
        from api.services.deployment_impl.dmg import DmgDeployment

        d = DmgDeployment.detect()
        # Baseline: 48 * 0.80 = 38.4
        assert d.effective_memory_gb() == pytest.approx(38.4, abs=0.1)
        # With 2 GB of MCP RSS, effective drops by 2.
        _stub_overhead(monkeypatch, 2.0)
        assert d.effective_memory_gb() == pytest.approx(36.4, abs=0.1)


def test_container_effective_memory_subtracts_mcp_overhead(monkeypatch):
    with patch_container(cgroup_memory_max_gb=32.0, host_memory_gb=96.0):
        from api.services.deployment_impl.container import ContainerDeployment

        d = ContainerDeployment.detect()
        # Baseline: 32 * 0.90 = 28.8
        assert d.effective_memory_gb() == pytest.approx(28.8, abs=0.1)
        _stub_overhead(monkeypatch, 4.0)
        assert d.effective_memory_gb() == pytest.approx(24.8, abs=0.1)


def test_host_native_effective_memory_subtracts_mcp_overhead(monkeypatch):
    with patch_host_native(host_memory_gb=96.0):
        from api.services.deployment_impl.host_native import HostNativeDeployment

        d = HostNativeDeployment.detect()
        # Baseline: 96 * 0.80 = 76.8
        assert d.effective_memory_gb() == pytest.approx(76.8, abs=0.1)
        _stub_overhead(monkeypatch, 8.0)
        assert d.effective_memory_gb() == pytest.approx(68.8, abs=0.1)


def test_effective_memory_clamps_at_zero_under_runaway_overhead(monkeypatch):
    """A pathological overhead > base must report 0, never negative."""
    with patch_dmg(host_memory_gb=16.0):
        from api.services.deployment_impl.dmg import DmgDeployment

        d = DmgDeployment.detect()
        # Baseline 16 * 0.80 = 12.8; if overhead is 20 GB we floor at 0.
        _stub_overhead(monkeypatch, 20.0)
        assert d.effective_memory_gb() == 0.0


# ── /api/system/architecture exposes the breakdown ──────────────────


def test_architecture_endpoint_exposes_mcp_overhead_gb():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers.system import router
    from api.services.architecture import detect_architecture
    from api.services.deployment import detect_deployment
    from tests.mocks.arch.mock_apple_unified import patch_apple_unified

    app = FastAPI()
    app.include_router(router)

    with patch_host_native(), patch_apple_unified(total_gb=48.0):
        detect_deployment()
        detect_architecture()
        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value="0.23.4",
        ):
            client = TestClient(app)
            r = client.get("/api/system/architecture")
            assert r.status_code == 200
            dep = r.json()["deployment"]
            assert "mcp_overhead_gb" in dep
            assert dep["mcp_overhead_gb"] == 0.0  # no warm runners
