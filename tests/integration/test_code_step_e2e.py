"""End-to-end: the engine dispatches a `kind: code` step to the sandbox executor.

Drives a REAL WorkflowEngine.run() — no engine mocking. Proves dispatch wiring
reaches api/services/engine_executors/code.py and the Tier-1 subprocess backend
actually runs the inline code, surfacing the exit code on the StepResult.
"""


def test_engine_runs_code_workflow(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    from api.services.sandbox_registry import SandboxRegistry, _set_current
    from api.services.sandbox_impl.subprocess import SubprocessSandbox

    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)

    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService
    from api.models.workflow_models import (
        WorkflowDefinition,
        AgentStep,
        CodeStepConfig,
    )

    wf = WorkflowDefinition(
        id="w-code",
        name="code",
        steps=[
            AgentStep(
                id="c1",
                name="run",
                kind="code",
                outputs=["result"],
                code=CodeStepConfig(code="print('engine-ran-code')"),
            ),
        ],
    )
    eng = WorkflowEngine(OllamaService())
    run = eng.run(wf, seed={})

    assert run.status == "completed"
    sr = [r for r in run.step_results if r.step_id == "c1"][0]
    assert sr.code_exit_code == 0
