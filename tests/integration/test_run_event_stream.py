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


def test_orchestrator_spawn_enriches_plan(tmp_path, monkeypatch):
    """Spawning a worker from an orchestrator step adds a plan item with
    origin='orchestrator' that is visible via reconstruct_from_log."""
    import json

    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None

    def _spawn(worker_id, task, **inputs):
        return (
            "Spawning now.\n```json\n"
            + json.dumps(
                {
                    "action": "spawn_worker",
                    "worker_id": worker_id,
                    "task": task,
                    "inputs": inputs,
                }
            )
            + "\n```"
        )

    def _complete(**outputs):
        return (
            "Done.\n```json\n"
            + json.dumps({"action": "complete", "outputs": outputs})
            + "\n```"
        )

    # Sequential responses: planner spawn → worker reply → planner complete
    fake = _FullFakeOllama(
        [
            _spawn("extractor", "extract things", raw_text="hello"),
            "extracted facts",  # worker response
            _complete(findings="all done"),
        ]
    )

    wf = WorkflowDefinition.model_validate(
        {
            "id": "orch_plan_wf",
            "name": "Orchestrator Plan Test",
            "schema_version": 1,
            "defaults": {"role": "reasoning", "max_tokens": 256},
            "steps": [
                {
                    "id": "lead",
                    "name": "Lead Step",
                    "kind": "orchestrator",
                    "outputs": ["findings"],
                    "planner": {
                        "role_inline": "You are the lead agent.",
                        "task": "Investigate and produce findings.",
                    },
                    "workers": {
                        "extractor": {
                            "id": "w_extractor",
                            "name": "Extractor Worker",
                            "role": "fast",
                            "prompt": {
                                "role_inline": "You extract facts.",
                                "task": "extract",
                            },
                            "inputs": ["seed.raw_text"],
                            "outputs": ["facts"],
                        }
                    },
                    "budget": {
                        "max_workers_spawned": 2,
                        "max_planner_turns": 6,
                    },
                }
            ],
        }
    )

    engine = WorkflowEngine(fake)
    run = engine.run(wf, seed={})

    assert run.status == "completed", f"run failed: {run.error}"

    from api.services.run_plan import PlanBuilder

    plan = PlanBuilder.reconstruct_from_log(reb.get_run_event_bus(), run.run_id)
    assert plan is not None
    orchestrator_items = [i for i in plan.items if i.origin == "orchestrator"]
    assert (
        orchestrator_items
    ), f"No orchestrator-origin plan items found. Items: {[(i.id, i.origin) for i in plan.items]}"


def test_sse_endpoint_replays_run_events(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    engine = WorkflowEngine(_FullFakeOllama(["done"]))
    run = engine.run(_wf(), seed={})  # completed run; log on disk

    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as client:
        with client.stream("GET", f"/api/workflows/runs/{run.run_id}/stream") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            body = ""
            for chunk in r.iter_text():
                body += chunk
                if "stream.end" in body:
                    break
    assert "event: run.status" in body
    assert "event: plan.updated" in body
    assert "event: stream.end" in body


def test_ralph_iterations_enrich_plan(tmp_path, monkeypatch):
    """Each ralph iteration must add a plan item with origin='ralph'."""
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None

    journal = str(tmp_path / "ralph_journal.jsonl")
    wf = WorkflowDefinition.model_validate(
        {
            "id": "ralph_plan_wf",
            "name": "Ralph Plan Test",
            "schema_version": 1,
            "defaults": {"role": "fast", "max_tokens": 128},
            "steps": [
                {
                    "id": "loop",
                    "name": "Autonomous Loop",
                    "kind": "ralph",
                    "outputs": ["result"],
                    "ralph": {
                        "journal_path": journal,
                        "halt": {"max_iterations": 2},
                    },
                    "body": [
                        {
                            "id": "do_work",
                            "name": "Do Work",
                            "role": "fast",
                            "system_prompt": "do the work",
                            "outputs": ["result"],
                        }
                    ],
                }
            ],
        }
    )

    # 2 iterations × 1 body step each = 2 LLM calls
    fake = _FullFakeOllama(["work done iter1", "work done iter2"])
    engine = WorkflowEngine(fake)
    run = engine.run(wf, seed={})

    assert run.status == "completed", f"run failed: {run.error}"

    from api.services.run_plan import PlanBuilder

    plan = PlanBuilder.reconstruct_from_log(reb.get_run_event_bus(), run.run_id)
    assert plan is not None
    iters = [i for i in plan.items if i.origin == "ralph"]
    assert len(iters) >= 2, (
        f"Expected >=2 ralph-origin plan items, got {len(iters)}. "
        f"Items: {[(i.id, i.origin) for i in plan.items]}"
    )
