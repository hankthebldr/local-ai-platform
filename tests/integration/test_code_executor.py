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


class _Engine:
    pass


def _setup_registry():
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)


def test_code_step_runs_and_writes_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    _setup_registry()
    step = AgentStep(
        id="c1",
        name="run",
        kind="code",
        outputs=["result"],
        code=CodeStepConfig(code="print('forty-two')"),
    )
    ctx = WorkflowContext()
    run = WorkflowRun(
        run_id="r1",
        workflow_id="w1",
        status="running",
        context=ctx,
        started_at=datetime.utcnow(),
    )
    res = code_exec.execute(
        _Engine(), step, WorkflowDefinition(id="w1", name="w", steps=[step]), ctx, run
    )
    assert res.status == "completed" and res.code_exit_code == 0
    assert "forty-two" in ctx.get_workspace("c1", "result")["stdout"]
