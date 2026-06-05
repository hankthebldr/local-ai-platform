"""HITL approval endpoint — POST /api/workflows/runs/{run_id}/approvals/{gate_id}.

Covers the surface contract (404 for unknown runs, 422 for bad payloads) and a
real end-to-end approve→resume→execute path: a `kind: code` workflow with
``approval="required"`` runs to ``awaiting_approval``, the operator POSTs
``{"action": "approve"}`` to the gate, and the run resumes to ``completed`` with
the gated code step's ``code_exit_code == 0``.

The e2e drives the *actual HTTP endpoint* via TestClient. Two paths must line up
for that to work, and the fixtures below make them coincide:

  * Persistence — the router's ``get_engine()`` builds a fresh WorkflowEngine
    that reads ``run.json`` from ``workflow_engine.DATA_DIR``. We monkeypatch
    that module constant to a tmp dir so the engine that *creates* the paused
    run (in the test) and the engine that *resolves* it (inside the handler)
    share storage.
  * Definition reload — the endpoint resumes exactly like ``resume_run`` does:
    ``engine.resume(run_id)`` with no explicit definition, so the engine reloads
    the workflow from ``./workflows/<workflow_id>.yaml``. We write that YAML to
    the real ``workflows/`` dir under a unique id and delete it on teardown.
"""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


# ── Surface contract ────────────────────────────────────────────────────────


def test_approve_unknown_run_404():
    r = client.post(
        "/api/workflows/runs/does-not-exist/approvals/x", json={"action": "approve"}
    )
    assert r.status_code == 404


def test_approval_request_validation():
    r = client.post("/api/workflows/runs/r/approvals/g", json={"action": "bogus"})
    assert r.status_code in (404, 422)


# ── Real approve → resume → execute ─────────────────────────────────────────

WF_ID = "test-approval-e2e"


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    """Wire up a runnable, resumable `kind: code` workflow for the HTTP e2e.

    Yields the workflow id once persistence + definition reload + the code
    sandbox are all pointed at test-controlled locations. Cleans up the
    on-disk YAML afterward so the repo's workflows/ dir is left untouched.
    """
    from api.services import workflow_engine as we_module
    from api.services.sandbox_registry import SandboxRegistry, _set_current
    from api.services.sandbox_impl.subprocess import SubprocessSandbox

    # Pin run.json storage to a tmp dir shared by the test engine and the
    # router's get_engine() engine (both read this module-level constant).
    monkeypatch.setattr(we_module, "DATA_DIR", str(tmp_path / "workflows"))
    (tmp_path / "workflows").mkdir(parents=True, exist_ok=True)

    # The code executor is opt-in and needs a registered backend. Subprocess
    # is tier-1 / can_auto_run=False, so approval="required" reliably gates.
    monkeypatch.setenv("CODE_EXEC_ENABLED", "true")
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    _set_current(reg)

    # resume() with no definition reloads from ./workflows/<id>.yaml — write a
    # real file there (unique id) and remove it on teardown.
    defn = {
        "id": WF_ID,
        "name": "Approval E2E",
        "schema_version": 2,
        "steps": [
            {
                "id": "c1",
                "name": "run code",
                "kind": "code",
                "outputs": ["result"],
                "code": {
                    "code": "print('approved-and-ran')",
                    "approval": "required",
                },
            }
        ],
    }
    wf_path = Path("workflows") / f"{WF_ID}.yaml"
    wf_path.parent.mkdir(parents=True, exist_ok=True)
    wf_path.write_text(yaml.safe_dump(defn))
    try:
        yield WF_ID
    finally:
        wf_path.unlink(missing_ok=True)


def test_approve_resumes_and_executes(e2e_env):
    """The headline path: a paused code run, approved over HTTP, runs to green."""
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    # 1. Run the workflow until it pauses at the approval gate.
    engine = WorkflowEngine(OllamaService())
    defn = engine.load(str(Path("workflows") / f"{e2e_env}.yaml"))
    run = engine.run(defn, seed={})
    assert run.status == "awaiting_approval"
    assert run.pending_gate is not None
    gate_id = run.pending_gate.gate_id
    assert gate_id == f"{run.run_id}:c1"

    # 2. Operator approves via the real HTTP endpoint.
    r = client.post(
        f"/api/workflows/runs/{run.run_id}/approvals/{gate_id}",
        json={"action": "approve"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "approve"
    assert body["status"] == "completed"

    # 3. The persisted run reflects a completed, green code step.
    final = engine.get_run(run.run_id)
    assert final["status"] == "completed"
    c1 = next(r for r in final["step_results"] if r["step_id"] == "c1")
    assert c1["status"] == "completed"
    assert c1["code_exit_code"] == 0
    # Gate consumed; nothing left pending.
    assert final.get("pending_gate") in (None, {})


def test_reject_fails_the_run(e2e_env):
    """Reject short-circuits the gated step to failed (and surfaces the reason)."""
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    engine = WorkflowEngine(OllamaService())
    defn = engine.load(str(Path("workflows") / f"{e2e_env}.yaml"))
    run = engine.run(defn, seed={})
    assert run.status == "awaiting_approval"
    gate_id = run.pending_gate.gate_id

    r = client.post(
        f"/api/workflows/runs/{run.run_id}/approvals/{gate_id}",
        json={"action": "reject", "reason": "not today"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"

    final = engine.get_run(run.run_id)
    c1 = next(r for r in final["step_results"] if r["step_id"] == "c1")
    assert c1["status"] == "failed"
    assert c1.get("approval_status") == "rejected"


def test_edit_runs_edited_code(e2e_env):
    """Edit swaps in the operator's code before execution; run goes green."""
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    engine = WorkflowEngine(OllamaService())
    defn = engine.load(str(Path("workflows") / f"{e2e_env}.yaml"))
    run = engine.run(defn, seed={})
    assert run.status == "awaiting_approval"
    gate_id = run.pending_gate.gate_id

    r = client.post(
        f"/api/workflows/runs/{run.run_id}/approvals/{gate_id}",
        json={"action": "edit", "edited_code": "print('operator-edited')"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"

    final = engine.get_run(run.run_id)
    c1 = next(r for r in final["step_results"] if r["step_id"] == "c1")
    assert c1["status"] == "completed"
    assert c1["code_exit_code"] == 0
    assert c1.get("approval_status") == "edited"


def test_edit_without_code_is_422(e2e_env):
    """An edit with no edited_code is rejected rather than silently running
    the originally-proposed code."""
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    engine = WorkflowEngine(OllamaService())
    defn = engine.load(str(Path("workflows") / f"{e2e_env}.yaml"))
    run = engine.run(defn, seed={})
    gate_id = run.pending_gate.gate_id

    r = client.post(
        f"/api/workflows/runs/{run.run_id}/approvals/{gate_id}",
        json={"action": "edit"},
    )
    assert r.status_code == 422
    # Gate is still pending — the run was not resumed.
    still = engine.get_run(run.run_id)
    assert still["status"] == "awaiting_approval"
    assert still["pending_gate"]["decision"] is None


def test_double_resolve_is_409(e2e_env):
    """Resolving an already-decided gate is rejected (idempotency)."""
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    engine = WorkflowEngine(OllamaService())
    defn = engine.load(str(Path("workflows") / f"{e2e_env}.yaml"))
    run = engine.run(defn, seed={})
    gate_id = run.pending_gate.gate_id

    first = client.post(
        f"/api/workflows/runs/{run.run_id}/approvals/{gate_id}",
        json={"action": "approve"},
    )
    assert first.status_code == 200, first.text

    # Gate was consumed by resume(); a second resolve finds no pending gate.
    second = client.post(
        f"/api/workflows/runs/{run.run_id}/approvals/{gate_id}",
        json={"action": "approve"},
    )
    assert second.status_code == 409
