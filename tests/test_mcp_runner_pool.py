"""Phase 2 — MCPRunnerPool: warm stdio runners keyed on (run_id, server_id).

Coverage:
  - one spawn per (run_id, server_id); subsequent acquires reuse
  - separate runs spawn separate runners
  - release_server / release_workflow close the subprocess and emit stats
  - dead runner is detected and respawned on next acquire
  - MCPService.invoke_tool(run_id=) routes through the pool
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from api.models.mcp_models import MCPServerConfig, MCPServerCreate
from api.services.mcp_runner_pool import (
    MCPRunnerPool,
    StdioMCPRunner,
    get_mcp_runner_pool,
    reset_mcp_runner_pool,
)
from api.services.mcp_service import MCPService

FAKE_SERVER = Path(__file__).parent / "mocks" / "mcp" / "fake_server.py"


def _fake_cfg(server_id: str = "fake", **env) -> MCPServerConfig:
    """Build a config that spawns the fake server."""
    return MCPServerConfig(
        id=server_id,
        name=server_id,
        transport="stdio",
        command=sys.executable,
        args=[str(FAKE_SERVER)],
        env=env,
        timeout_seconds=10,
    )


@pytest.fixture
def mcp_service(tmp_path):
    """A real MCPService backed by tmp storage so the pool can resolve
    server configs via _require."""
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
    return svc


@pytest.fixture
def pool(mcp_service):
    p = MCPRunnerPool(mcp_service=mcp_service)
    yield p
    # Drain anything still alive so tests don't leak subprocesses.
    for rid, sid in list(p._runners.keys()):
        p.release_server(rid, sid)


# ── lifecycle: one runner per (run, server) ─────────────────────────────


def test_acquire_reuses_runner_within_same_run(pool):
    r1 = pool.acquire("run-A", "fake")
    r2 = pool.acquire("run-A", "fake")
    assert r1 is r2
    assert r1.pid is not None


def test_separate_runs_get_separate_runners(pool):
    a = pool.acquire("run-A", "fake")
    b = pool.acquire("run-B", "fake")
    assert a.pid != b.pid
    assert pool.runner_count() == 2


def test_release_server_closes_subprocess(pool):
    runner = pool.acquire("run-A", "fake")
    pid = runner.pid
    stats = pool.release_server("run-A", "fake")
    assert stats is not None
    assert stats.server_id == "fake"
    assert stats.closed_at is not None
    assert stats.exit_code is not None
    assert pool.runner_count() == 0
    # The subprocess is reaped — the runner reports dead.
    assert not runner.is_alive()
    # No process by that pid that's a child of ours any more.
    import psutil

    if pid is not None:
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() in (
            psutil.STATUS_ZOMBIE,
            psutil.STATUS_DEAD,
        )


def test_release_workflow_drains_all_servers(pool, mcp_service):
    # Register a second server so one run can hold two runners.
    mcp_service.register(
        MCPServerCreate(
            id="fake2",
            name="Fake2",
            transport="stdio",
            command=sys.executable,
            args=[str(FAKE_SERVER)],
        )
    )
    pool.acquire("run-A", "fake")
    pool.acquire("run-A", "fake2")
    pool.acquire("run-B", "fake")  # different run — must survive

    stats = pool.release_workflow("run-A")
    assert {s.server_id for s in stats} == {"fake", "fake2"}
    assert pool.runner_count() == 1  # run-B still holds one


def test_release_workflow_with_no_runners_returns_empty(pool):
    assert pool.release_workflow("never-acquired") == []


# ── tool calls + stats ──────────────────────────────────────────────────


def test_warm_runner_handles_multiple_tool_calls(pool):
    runner = pool.acquire("run-A", "fake")
    for i in range(5):
        result = runner.call("tools/call", {"name": "echo", "arguments": {"i": i}})
        assert result == {"echoed": {"i": i}}
    stats = pool.release_server("run-A", "fake")
    assert stats.requests_handled == 5
    assert stats.errors == 0
    assert stats.handshake_duration_ms > 0
    assert stats.avg_response_ms >= 0


def test_warm_runner_counts_protocol_errors(pool):
    runner = pool.acquire("run-A", "fake")
    runner.call("tools/call", {"name": "echo", "arguments": {}})
    with pytest.raises(RuntimeError, match="boom"):
        runner.call("tools/call", {"name": "boom", "arguments": {}})
    stats = pool.release_server("run-A", "fake")
    assert stats.requests_handled == 2
    assert stats.errors == 1


def test_calling_closed_runner_raises(pool):
    runner = pool.acquire("run-A", "fake")
    pool.release_server("run-A", "fake")
    with pytest.raises(RuntimeError, match="already closed"):
        runner.call("tools/call", {"name": "echo", "arguments": {}})


# ── crash + respawn ─────────────────────────────────────────────────────


def test_dead_runner_respawned_on_next_acquire(pool, mcp_service):
    # Register a crash-on-request variant so the first call kills the subprocess.
    mcp_service.register(
        MCPServerCreate(
            id="crashy",
            name="Crashy",
            transport="stdio",
            command=sys.executable,
            args=[str(FAKE_SERVER)],
            env={"FAKE_MCP_CRASH_ON_REQUEST": "1"},
        )
    )
    runner1 = pool.acquire("run-A", "crashy")
    pid1 = runner1.pid
    # The first tools/call kills the subprocess; our read raises.
    with pytest.raises(RuntimeError):
        runner1.call("tools/call", {"name": "echo", "arguments": {}})
    # Re-acquire — the pool notices the corpse and spawns a fresh one.
    runner2 = pool.acquire("run-A", "crashy")
    assert runner2 is not runner1
    assert runner2.pid != pid1
    # The dead runner's stats were preserved.
    stats = pool.release_workflow("run-A")
    assert len(stats) == 2
    # Exactly one of them belongs to the corpse pid.
    assert any(s.pid == pid1 for s in stats)


def test_spawn_failure_during_handshake_cleans_up(mcp_service):
    mcp_service.register(
        MCPServerCreate(
            id="badboot",
            name="BadBoot",
            transport="stdio",
            command=sys.executable,
            args=[str(FAKE_SERVER)],
            env={"FAKE_MCP_FAIL_INIT": "1"},
        )
    )
    pool = MCPRunnerPool(mcp_service=mcp_service)
    with pytest.raises(Exception):
        pool.acquire("run-A", "badboot")
    assert pool.runner_count() == 0


# ── MCPService routing through the pool ────────────────────────────────


def test_invoke_tool_with_run_id_routes_through_pool(mcp_service):
    """MCPService.invoke_tool(run_id=…) shares one subprocess across calls."""
    reset_mcp_runner_pool()
    pool = get_mcp_runner_pool()
    pool.attach_service(mcp_service)
    try:
        r1 = mcp_service.invoke_tool("fake", "echo", {"a": 1}, run_id="run-X")
        r2 = mcp_service.invoke_tool("fake", "echo", {"a": 2}, run_id="run-X")
        assert r1 == {"echoed": {"a": 1}}
        assert r2 == {"echoed": {"a": 2}}
        assert pool.runner_count() == 1
        stats = pool.release_workflow("run-X")
        assert stats[0].requests_handled == 2
    finally:
        reset_mcp_runner_pool()


def test_invoke_tool_without_run_id_uses_cold_path(mcp_service):
    """No run_id → no pool involvement → no warm runner left behind."""
    reset_mcp_runner_pool()
    pool = get_mcp_runner_pool()
    try:
        result = mcp_service.invoke_tool("fake", "echo", {"a": 1})
        assert result == {"echoed": {"a": 1}}
        assert pool.runner_count() == 0
    finally:
        reset_mcp_runner_pool()


def test_invoke_tool_disabled_server_rejected(mcp_service):
    from api.models.mcp_models import MCPServerUpdate

    mcp_service.update("fake", MCPServerUpdate(enabled=False))
    with pytest.raises(RuntimeError, match="disabled"):
        mcp_service.invoke_tool("fake", "echo", {}, run_id="run-Z")


# ── pool overhead accounting ───────────────────────────────────────────


def test_total_runner_overhead_reports_live_rss(pool):
    pool.acquire("run-A", "fake")
    overhead = pool.total_runner_overhead_mb()
    # A live python subprocess is non-trivially sized; assert ≥ 1 MB.
    assert overhead >= 1.0
    pool.release_workflow("run-A")
    assert pool.total_runner_overhead_mb() == 0.0


def test_list_runners_debug_snapshot(pool):
    pool.acquire("run-A", "fake")
    pool.acquire("run-B", "fake")
    snapshot = pool.list_runners()
    assert len(snapshot) == 2
    assert {entry["run_id"] for entry in snapshot} == {"run-A", "run-B"}
    assert all(entry["server_id"] == "fake" for entry in snapshot)
    assert all(entry["pid"] is not None for entry in snapshot)


# ── scope validation ───────────────────────────────────────────────────


def test_acquire_rejects_unknown_scope(pool):
    with pytest.raises(ValueError, match="invalid scope"):
        pool.acquire("run-A", "fake", scope="forever")


def test_scope_propagates_to_stats(pool):
    pool.acquire("run-A", "fake", scope="step")
    stats = pool.release_server("run-A", "fake")
    assert stats.scope == "step"


# ── direct StdioMCPRunner smoke ────────────────────────────────────────


def test_stdio_runner_direct_use():
    """Bypass the pool — confirm the runner class works standalone."""
    cfg = _fake_cfg()
    runner = StdioMCPRunner.spawn(cfg, scope="workflow")
    try:
        result = runner.call("tools/list", {})
        assert any(t["name"] == "echo" for t in result["tools"])
    finally:
        stats = runner.close()
        assert stats.requests_handled == 1
        assert stats.transport == "stdio"
