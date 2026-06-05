from api.models.workflow_models import GatePending, WorkflowRun, WorkflowContext


def test_gate_defaults_and_run_field():
    g = GatePending(
        gate_id="r1:c1",
        run_id="r1",
        step_id="c1",
        step_kind="code",
        proposed_code="print(1)",
        network="none",
        tier=1,
    )
    assert g.decision is None and g.files == []
    run = WorkflowRun(
        run_id="r1", workflow_id="w1", status="running", context=WorkflowContext()
    )
    assert run.pending_gate is None
    run.pending_gate = g
    assert WorkflowRun.model_validate(run.model_dump()).pending_gate.gate_id == "r1:c1"
