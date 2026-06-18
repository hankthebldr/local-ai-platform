import api.services.run_event_bus as reb
from api.models.run_event import EventType
from api.models.workflow_models import WorkflowDefinition
from api.services.workflow_engine import WorkflowEngine
from tests.integration.conftest import FakeOllamaClient


class _FullFakeOllama(FakeOllamaClient):
    """FakeOllamaClient + stubs needed by ModelResolver."""

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


def _wf():
    return WorkflowDefinition.model_validate(
        {
            "id": "evt_wf",
            "name": "evt_wf",
            "steps": [
                {
                    "id": "a",
                    "name": "Step A",
                    "system_prompt": "do a",
                    "outputs": ["out"],
                }
            ],
        }
    )


def test_run_emits_status_and_baseline_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None  # fresh singleton picks up patched RUNS_DIR
    engine = WorkflowEngine(_FullFakeOllama(["done"]))
    run = engine.run(_wf(), seed={})

    bus = reb.get_run_event_bus()
    types = [e.type for e in bus.read_log(run.run_id)]
    assert types[0] == EventType.RUN_STATUS  # running
    assert EventType.PLAN_UPDATED in types  # baseline plan
    assert types[-1] == EventType.RUN_STATUS  # terminal
    statuses = [
        e.data["status"]
        for e in bus.read_log(run.run_id)
        if e.type == EventType.RUN_STATUS
    ]
    assert statuses[0] == "running" and statuses[-1] == "completed"


def test_emits_step_started_and_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    engine = WorkflowEngine(_FullFakeOllama(["done"]))
    run = engine.run(_wf(), seed={})
    log = reb.get_run_event_bus().read_log(run.run_id)
    started = [e for e in log if e.type == EventType.STEP_STARTED and e.step_id == "a"]
    completed = [
        e for e in log if e.type == EventType.STEP_COMPLETED and e.step_id == "a"
    ]
    assert started and completed
    assert completed[0].data["status"] == "completed"
    assert "duration_ms" in completed[0].data


def test_emits_gate_pending_when_awaiting_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None

    # Enable the code executor and register a Tier-1 subprocess sandbox
    # (tier_default on Tier-1 maps to approval="required", so the run always gates).
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    from api.services.sandbox_registry import SandboxRegistry, _set_current
    from api.services.sandbox_impl.subprocess import SubprocessSandbox

    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)


    wf = WorkflowDefinition.model_validate(
        {
            "id": "evt_gate_wf",
            "name": "evt_gate_wf",
            "steps": [
                {
                    "id": "c",
                    "name": "gated code step",
                    "kind": "code",
                    "outputs": ["result"],
                    "code": {
                        "code": "print('gate-test')",
                        "approval": "required",
                    },
                }
            ],
        }
    )
    engine = WorkflowEngine(_FullFakeOllama([]))
    run = engine.run(wf, seed={})
    assert run.status == "awaiting_approval"
    gate_evs = [
        e
        for e in reb.get_run_event_bus().read_log(run.run_id)
        if e.type == EventType.GATE_PENDING
    ]
    assert gate_evs and gate_evs[0].data["gate_id"]
    assert gate_evs[0].data["step_id"] == "c"
