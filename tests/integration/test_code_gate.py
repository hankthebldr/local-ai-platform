"""HITL approval gate for kind=code steps (Task 12).

Covers the three correctness-critical paths:
  1. tier_default on a Tier-1 (subprocess) backend RAISES a gate (pause).
  2. approval=auto executes straight through, recording approval_status="auto".
  3. A real WorkflowEngine.run() with an approval-required code step HALTS the
     run at status="awaiting_approval" with pending_gate set, and the gated
     step is NOT recorded as "completed" (so resume() re-dispatches it).
"""

from datetime import datetime

from api.models.workflow_models import (
    AgentStep,
    CodeStepConfig,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from api.services.sandbox_registry import SandboxRegistry, _set_current
from api.services.sandbox_impl.subprocess import SubprocessSandbox
from api.services.engine_executors import code as code_exec


def _ctx_run():
    ctx = WorkflowContext()
    return ctx, WorkflowRun(
        run_id="r1",
        workflow_id="w1",
        status="running",
        context=ctx,
        started_at=datetime.utcnow(),
    )


def test_tier1_required_raises_gate(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)
    step = AgentStep(
        id="c1",
        name="run",
        kind="code",
        outputs=["result"],
        code=CodeStepConfig(code="print(1)", approval="tier_default"),
    )
    ctx, run = _ctx_run()
    res = code_exec.execute(
        object(),
        step,
        WorkflowDefinition(id="w1", name="w", steps=[step]),
        ctx,
        run,
    )
    assert res.status == "awaiting_approval"
    assert run.pending_gate is not None and run.pending_gate.step_id == "c1"


def test_auto_decision_executes(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)
    step = AgentStep(
        id="c1",
        name="run",
        kind="code",
        outputs=["result"],
        code=CodeStepConfig(code="print('ran')", approval="auto"),
    )
    ctx, run = _ctx_run()
    res = code_exec.execute(
        object(),
        step,
        WorkflowDefinition(id="w1", name="w", steps=[step]),
        ctx,
        run,
    )
    assert res.status == "completed" and res.code_exit_code == 0
    assert res.approval_status == "auto"


def test_engine_run_pauses_on_gate(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    wf = WorkflowDefinition(
        id="wg",
        name="g",
        steps=[
            AgentStep(
                id="c1",
                name="run",
                kind="code",
                outputs=["result"],
                code=CodeStepConfig(code="print(1)", approval="required"),
            ),
        ],
    )
    run = WorkflowEngine(OllamaService()).run(wf, seed={})
    assert run.status == "awaiting_approval"
    assert (
        run.pending_gate is not None and run.pending_gate.gate_id == f"{run.run_id}:c1"
    )
    assert not any(
        r.step_id == "c1" and r.status == "completed" for r in run.step_results
    )


def test_resume_without_decision_does_not_duplicate(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    wf = WorkflowDefinition(
        id="wg2",
        name="g",
        steps=[
            AgentStep(
                id="c1",
                name="run",
                kind="code",
                outputs=["result"],
                code=CodeStepConfig(code="print(1)", approval="required"),
            ),
        ],
    )
    eng = WorkflowEngine(OllamaService())
    run = eng.run(wf, seed={})
    assert run.status == "awaiting_approval"
    # resume WITHOUT setting a decision -> must still be a single
    # awaiting_approval, no duplicate
    # Pass the in-memory definition: this synthetic workflow has no
    # ./workflows/wg2.yaml on disk, and resume() accepts an explicit
    # definition for exactly this case.
    run2 = eng.resume(run.run_id, definition=wf)
    assert run2.status == "awaiting_approval"
    aw = [
        r
        for r in run2.step_results
        if r.step_id == "c1" and r.status == "awaiting_approval"
    ]
    assert len(aw) == 1  # exactly one, not duplicated


def test_approval_auto_tier1_warns(monkeypatch, caplog):
    import logging
    from api.logging_config import logger as proj_logger
    from api.services.engine_executors.code import _approval_required

    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)
    sb = SubprocessSandbox()
    # The project "local-ai" logger has propagate=False, so caplog's root
    # handler can't see it — attach caplog's handler to the logger directly.
    caplog.set_level(logging.WARNING)
    proj_logger.addHandler(caplog.handler)
    try:
        assert (
            _approval_required(CodeStepConfig(code="x", approval="auto"), sb) is False
        )
        assert any("approval=auto on Tier-1" in r.message for r in caplog.records)
        caplog.clear()
        _approval_required(CodeStepConfig(code="x", approval="required"), sb)
        assert not any("approval=auto" in r.message for r in caplog.records)
    finally:
        proj_logger.removeHandler(caplog.handler)
