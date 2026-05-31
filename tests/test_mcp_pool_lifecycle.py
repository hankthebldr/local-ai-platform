"""End-to-end MCP runner pool lifecycle: warm runners spawned during a run
land on WorkflowRun.mcp_runners after the engine finishes.

This ties together Phases 2 (pool) + 4 (StepResult.mcp_calls schema +
WorkflowRun.mcp_runners) + the engine lifecycle hook this PR adds:
``_safe_drain_mcp_pool`` is called by ``_persist_run`` (normal path) and
by the safety try/finally in ``execute``/``resume`` (exception path).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from api.models.mcp_models import MCPServerCreate
from api.services import workflow_engine as we_mod
from api.services.mcp_runner_pool import (
    get_mcp_runner_pool,
    reset_mcp_runner_pool,
)
from api.services.mcp_service import MCPService, reset_mcp_service
from api.services.ollama_service import OllamaService
from api.services.workflow_engine import WorkflowEngine
from api.models.workflow_models import (
    AgentStep,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)

FAKE_SERVER = Path(__file__).parent / "mocks" / "mcp" / "fake_server.py"


@pytest.fixture(autouse=True)
def _hermetic():
    reset_mcp_runner_pool()
    reset_mcp_service()
    yield
    reset_mcp_runner_pool()
    reset_mcp_service()


@pytest.fixture
def mcp_service(tmp_path):
    """Real MCPService routed at a tmp registry so the pool can resolve a
    'fake' stdio server."""
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


def _llm_step(step_id="s") -> AgentStep:
    return AgentStep(id=step_id, name=step_id, system_prompt="p", outputs=["x"])


def _wf(run_id_steps=None) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="drain-me",
        name="drain-me",
        steps=run_id_steps or [_llm_step()],
    )


# ── Drain helper ─────────────────────────────────────────────────────


def test_safe_drain_pool_attaches_stats_to_run(tmp_path, monkeypatch, mcp_service):
    """A workflow that spawned a warm runner gets its stats attached on drain."""
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())

    run = WorkflowRun(workflow_id="drain-me", context=WorkflowContext(seed={}))

    # Spawn a runner under this run_id so the pool has something to drain.
    pool = get_mcp_runner_pool()
    pool.attach_service(mcp_service)
    runner = pool.acquire(run.run_id, "fake")
    # Make at least one call so stats have non-zero handshake_duration_ms.
    runner.call("tools/call", {"name": "echo", "arguments": {"x": 1}})

    engine._safe_drain_mcp_pool(run)  # noqa: SLF001

    assert len(run.mcp_runners) == 1
    stats = run.mcp_runners[0]
    assert stats.server_id == "fake"
    assert stats.requests_handled >= 1
    assert stats.closed_at is not None
    # And the pool is now empty (the drain reaped the subprocess).
    assert pool.runner_count() == 0


def test_safe_drain_pool_is_idempotent(tmp_path, monkeypatch, mcp_service):
    """Calling drain twice doesn't duplicate stats or crash."""
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())

    run = WorkflowRun(workflow_id="drain-me", context=WorkflowContext(seed={}))
    pool = get_mcp_runner_pool()
    pool.attach_service(mcp_service)
    pool.acquire(run.run_id, "fake")

    engine._safe_drain_mcp_pool(run)  # noqa: SLF001
    snapshot = list(run.mcp_runners)
    engine._safe_drain_mcp_pool(run)  # noqa: SLF001
    # No duplicates appended on the second drain.
    assert run.mcp_runners == snapshot


def test_safe_drain_pool_noop_when_no_runners(tmp_path, monkeypatch):
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())
    run = WorkflowRun(workflow_id="drain-me", context=WorkflowContext(seed={}))
    engine._safe_drain_mcp_pool(run)  # noqa: SLF001
    assert run.mcp_runners == []


def test_safe_drain_pool_tolerates_pool_error(tmp_path, monkeypatch):
    """Pool failures during drain must not crash the engine — the run record
    is more important than the rollup."""
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())
    run = WorkflowRun(workflow_id="drain-me", context=WorkflowContext(seed={}))

    def boom():
        raise RuntimeError("simulated pool init crash")

    monkeypatch.setattr("api.services.mcp_runner_pool.get_mcp_runner_pool", boom)
    engine._safe_drain_mcp_pool(run)  # noqa: SLF001 - must not raise
    assert run.mcp_runners == []


# ── _persist_run drains + serializes ─────────────────────────────────


def test_persist_run_drains_pool_and_writes_run_json(
    tmp_path, monkeypatch, mcp_service
):
    """_persist_run calls _safe_drain_mcp_pool, then aggregates, then writes."""
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())

    run = WorkflowRun(workflow_id="drain-me", context=WorkflowContext(seed={}))
    pool = get_mcp_runner_pool()
    pool.attach_service(mcp_service)
    runner = pool.acquire(run.run_id, "fake")
    runner.call("tools/call", {"name": "echo", "arguments": {}})

    engine._persist_run(run, _wf())  # noqa: SLF001

    persisted = json.loads((tmp_path / run.run_id / "run.json").read_text())
    assert len(persisted["mcp_runners"]) == 1
    assert persisted["mcp_runners"][0]["server_id"] == "fake"
    # Pool is fully drained after persist.
    assert pool.runner_count() == 0


# ── Engine entrypoints wrap execution in safety try/finally ──────────


def test_execute_drains_pool_when_steps_raise(tmp_path, monkeypatch, mcp_service):
    """Even if _execute_steps raises, runners must not leak."""
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())
    pool = get_mcp_runner_pool()
    pool.attach_service(mcp_service)

    # Force _execute_steps to raise; check the safety drain still fires.
    def boom(*args, **kwargs):
        # Acquire a runner first so the drain has something to release.
        run = args[0]
        pool.acquire(run.run_id, "fake")
        raise RuntimeError("simulated step crash")

    monkeypatch.setattr(engine, "_execute_steps", boom)

    wf = _wf()
    with pytest.raises(RuntimeError, match="simulated step crash"):
        engine.run(wf, seed={})
    # Pool was drained by the except branch even though _persist_run never ran.
    assert pool.runner_count() == 0


def test_resume_drains_pool_when_steps_raise(tmp_path, monkeypatch, mcp_service):
    """The resume() entrypoint wraps _execute_steps in the same try/finally."""
    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())
    pool = get_mcp_runner_pool()
    pool.attach_service(mcp_service)

    # Seed a checkpointed run so resume() has something to pick up.
    run = WorkflowRun(
        workflow_id="drain-me",
        context=WorkflowContext(seed={}),
        status="running",
    )
    run_dir = tmp_path / run.run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(run.model_dump(mode="json"), default=str)
    )

    def boom(*args, **kwargs):
        rid = args[0].run_id
        pool.acquire(rid, "fake")
        raise RuntimeError("simulated resume crash")

    monkeypatch.setattr(engine, "_execute_steps", boom)

    with pytest.raises(RuntimeError, match="simulated resume crash"):
        engine.resume(run.run_id, definition=_wf())
    assert pool.runner_count() == 0
