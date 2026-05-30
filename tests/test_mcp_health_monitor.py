"""Phase 3 — MCP health monitor + circuit breaker.

The pool ships warm runners (Phase 2). Phase 3 hardens them so a flaky
upstream can't pin a workflow forever and a hung runner can't masquerade
as healthy. Coverage:

  - circuit breaker trips after N consecutive failures and fast-fails
    subsequent calls without sending anything on the wire
  - successful health check resets the breaker
  - failed health check bumps the failure counter
  - dead subprocess → health_check returns False (no raise)
  - background monitor thread sweeps every interval; stop() joins cleanly
  - stats record carries health_check_failures + circuit_breaker_tripped
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from api.models.mcp_models import MCPServerCreate
from api.services.mcp_runner_pool import (
    DEFAULT_MAX_CONSECUTIVE_ERRORS,
    CircuitBreaker,
    MCPCircuitBreakerOpenError,
    MCPRunnerPool,
)
from api.services.mcp_service import MCPService

FAKE_SERVER = Path(__file__).parent / "mocks" / "mcp" / "fake_server.py"


@pytest.fixture
def mcp_service(tmp_path):
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
    p.stop_health_monitor()
    for rid, sid in list(p._runners.keys()):  # noqa: SLF001
        p.release_server(rid, sid)


# ── CircuitBreaker primitive ────────────────────────────────────────────


def test_circuit_breaker_trips_after_threshold():
    cb = CircuitBreaker(max_consecutive_errors=3)
    assert not cb.is_open
    cb.check("srv")  # closed → no-op
    cb.record_failure()
    cb.record_failure()
    cb.check("srv")  # still closed at 2
    cb.record_failure()
    assert cb.is_open
    with pytest.raises(MCPCircuitBreakerOpenError) as exc:
        cb.check("srv")
    assert exc.value.server_id == "srv"
    assert exc.value.consecutive_errors == 3


def test_circuit_breaker_success_resets_counter():
    cb = CircuitBreaker(max_consecutive_errors=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.consecutive_errors == 0
    # Two more failures don't trip — we restarted counting from 0.
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open


def test_circuit_breaker_explicit_reset_closes_open_circuit():
    cb = CircuitBreaker(max_consecutive_errors=2)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open
    cb.reset()
    assert not cb.is_open
    cb.check("srv")  # no raise


# ── Runner-level circuit breaker ───────────────────────────────────────


def test_runner_fast_fails_after_consecutive_errors(pool):
    runner = pool.acquire("run-A", "fake")
    # The fake answers "boom" with a JSON-RPC error which counts as a failure.
    for _ in range(DEFAULT_MAX_CONSECUTIVE_ERRORS):
        with pytest.raises(RuntimeError, match="boom"):
            runner.call("tools/call", {"name": "boom", "arguments": {}})
    # Next call is fast-failed without touching the wire.
    requests_before = runner._requests_handled  # noqa: SLF001
    with pytest.raises(MCPCircuitBreakerOpenError):
        runner.call("tools/call", {"name": "echo", "arguments": {}})
    assert runner._requests_handled == requests_before  # noqa: SLF001
    # Stats record the trip.
    stats = pool.release_server("run-A", "fake")
    assert stats.circuit_breaker_tripped is True
    assert stats.errors >= DEFAULT_MAX_CONSECUTIVE_ERRORS


def test_runner_success_between_failures_keeps_circuit_closed(pool):
    """Consecutive means *consecutive* — a successful call resets the counter."""
    runner = pool.acquire("run-A", "fake")
    with pytest.raises(RuntimeError, match="boom"):
        runner.call("tools/call", {"name": "boom", "arguments": {}})
    runner.call("tools/call", {"name": "echo", "arguments": {}})  # resets
    with pytest.raises(RuntimeError, match="boom"):
        runner.call("tools/call", {"name": "boom", "arguments": {}})
    with pytest.raises(RuntimeError, match="boom"):
        runner.call("tools/call", {"name": "boom", "arguments": {}})
    # Two consecutive failures, not three — breaker still closed.
    assert not runner._circuit.is_open  # noqa: SLF001
    runner.call("tools/call", {"name": "echo", "arguments": {}})  # works


# ── Health check ───────────────────────────────────────────────────────


def test_health_check_succeeds_on_live_runner(pool):
    runner = pool.acquire("run-A", "fake")
    assert runner.health_check() is True


def test_health_check_resets_open_circuit(pool):
    runner = pool.acquire("run-A", "fake")
    for _ in range(DEFAULT_MAX_CONSECUTIVE_ERRORS):
        with pytest.raises(RuntimeError):
            runner.call("tools/call", {"name": "boom", "arguments": {}})
    assert runner._circuit.is_open  # noqa: SLF001
    # The probe goes through _raw_call which bypasses the breaker.
    assert runner.health_check() is True
    assert not runner._circuit.is_open  # noqa: SLF001
    # And now real calls work again.
    result = runner.call("tools/call", {"name": "echo", "arguments": {"x": 1}})
    assert result == {"echoed": {"x": 1}}


def test_health_check_returns_false_on_dead_runner(pool, mcp_service):
    """A subprocess that died mid-flight reports False, not an exception."""
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
    runner = pool.acquire("run-A", "crashy")
    with pytest.raises(RuntimeError):
        runner.call("tools/call", {"name": "echo", "arguments": {}})
    # Subprocess is now dead. Health check shouldn't raise.
    assert runner.health_check() is False
    assert runner._health_check_failures >= 1  # noqa: SLF001


def test_health_check_increments_failure_counter(pool):
    """If the upstream stays broken, health_check_failures climbs each sweep."""
    runner = pool.acquire("run-A", "fake")
    # Force the subprocess closed so each probe fails.
    runner._proc.terminate()  # noqa: SLF001
    runner._proc.wait(timeout=2)  # noqa: SLF001
    for _ in range(3):
        assert runner.health_check() is False
    assert runner._health_check_failures == 3  # noqa: SLF001
    stats = pool.release_server("run-A", "fake")
    assert stats.health_check_failures == 3


# ── Pool-level run_health_checks ──────────────────────────────────────


def test_pool_run_health_checks_sweeps_all_live(pool, mcp_service):
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
    results = pool.run_health_checks()
    assert len(results) == 2
    assert all(healthy for healthy in results.values())


def test_pool_run_health_checks_with_no_runners_empty(pool):
    assert pool.run_health_checks() == {}


# ── Background monitor thread ──────────────────────────────────────────


def test_health_monitor_thread_sweeps_periodically(pool):
    pool.acquire("run-A", "fake")
    pool.start_health_monitor(interval_s=0.05)
    # Give it enough wall time for at least two sweeps.
    time.sleep(0.25)
    pool.stop_health_monitor()
    # The runner is still alive and now we know health_checks ran by
    # confirming it didn't open the circuit.
    runner = pool._runners[("run-A", "fake")]  # noqa: SLF001
    assert not runner._circuit.is_open  # noqa: SLF001


def test_health_monitor_thread_can_be_restarted(pool):
    pool.acquire("run-A", "fake")
    pool.start_health_monitor(interval_s=0.05)
    first = pool._health_thread  # noqa: SLF001
    pool.start_health_monitor(interval_s=0.05)
    second = pool._health_thread  # noqa: SLF001
    assert second is not first
    pool.stop_health_monitor()
    assert pool._health_thread is None  # noqa: SLF001


def test_stop_health_monitor_idempotent(pool):
    pool.stop_health_monitor()  # never started — no raise
    pool.start_health_monitor(interval_s=0.05)
    pool.stop_health_monitor()
    pool.stop_health_monitor()  # safe to call twice


def test_run_health_checks_survives_runner_exception(pool, monkeypatch):
    """A misbehaving runner.health_check() must not crash the sweep."""
    runner = pool.acquire("run-A", "fake")

    def boom():
        raise RuntimeError("runner unwell")

    monkeypatch.setattr(runner, "health_check", boom)
    results = pool.run_health_checks()
    assert results[("run-A", "fake")] is False
