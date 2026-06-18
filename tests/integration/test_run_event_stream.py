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
