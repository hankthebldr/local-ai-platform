"""CH-1 — resume-from-failed + workflow-scoped run index.

Covers the two add-only workflow routes CH-1 introduces:

  POST /api/workflows/runs/{run_id}/resume-from-failed
  GET  /api/workflows/{workflow_id}/runs

Guards (404 missing / 409 not-failed / 400 traversal), the happy-path flip-
then-resume (mirrors resolve_approval — the failed run is flipped to running,
checkpointed, then engine.resume re-dispatches), and the read-model filter.

No live engine / ollama needed: engine.resume is stubbed so the test exercises
the ROUTER contract (status guards, the status flip + checkpoint, the response
shape), not the engine internals (the frozen engine is covered elsewhere).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the engine's run store at a throwaway dir. get_run / list_runs /
    _checkpoint all read the module-global DATA_DIR at call time, so patching
    the attribute reroutes every run-store touch to the tmp tree."""
    d = tmp_path / "runs"
    d.mkdir()
    monkeypatch.setattr("api.services.workflow_engine.DATA_DIR", str(d))
    return d


def _write_run(data_dir: Path, run_id: str, status: str, workflow_id="wf-x",
               step_results=None) -> dict:
    rd = data_dir / run_id
    rd.mkdir(parents=True, exist_ok=True)
    snap = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "context": {"seed": {"task": "x"}},
        "step_results": step_results or [],
    }
    (rd / "run.json").write_text(json.dumps(snap))
    return snap


# ── resume-from-failed guards ──────────────────────────────────────────────


def test_resume_from_failed_missing_run_404(client, data_dir):
    r = client.post("/api/workflows/runs/does-not-exist/resume-from-failed")
    assert r.status_code == 404


def test_resume_from_failed_not_failed_is_409(client, data_dir):
    _write_run(data_dir, "run-completed", "completed")
    r = client.post("/api/workflows/runs/run-completed/resume-from-failed")
    assert r.status_code == 409
    assert "not failed" in r.json()["detail"].lower()


def test_resume_from_failed_rejects_path_traversal(client, data_dir):
    # A crafted id must never traverse out of the run store. The '..' traversal
    # payload contains '.', which is outside the [alnum _ -] allowlist, so the
    # charset guard rejects it with 400 before any filesystem join happens.
    # (Kept a single URL path segment so the assertion targets the guard, not
    # the client's own path normalization of a literal '/'.)
    r = client.post("/api/workflows/runs/etc..passwd/resume-from-failed")
    assert r.status_code == 400


def test_resume_from_failed_flips_and_resumes(client, data_dir):
    """A failed run is flipped to running, checkpointed, then resumed."""
    from api.models.workflow_models import WorkflowRun

    _write_run(
        data_dir,
        "run-failed",
        "failed",
        step_results=[{"step_id": "s1", "status": "completed"},
                      {"step_id": "s2", "status": "failed", "error": "boom"}],
    )

    resumed = WorkflowRun(
        run_id="run-failed", workflow_id="wf-x", status="completed",
        context={"seed": {}},
    )

    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume",
        return_value=resumed,
    ) as mock_resume:
        r = client.post("/api/workflows/runs/run-failed/resume-from-failed")

    assert r.status_code == 200
    body = r.json()
    assert body["resumed_from_failed"] is True
    assert body["status"] == "completed"
    assert body["run_id"] == "run-failed"
    mock_resume.assert_called_once()
    # The checkpoint BEFORE resume must have flipped the persisted snapshot off
    # its terminal 'failed' state so a crash mid-resume leaves it recoverable.
    persisted = json.loads((data_dir / "run-failed" / "run.json").read_text())
    assert persisted["status"] == "running"


# ── workflow-scoped run index ──────────────────────────────────────────────


def test_list_workflow_runs_filters_by_workflow(client, data_dir):
    _write_run(data_dir, "r1", "completed", workflow_id="alpha")
    _write_run(data_dir, "r2", "failed", workflow_id="beta")
    _write_run(data_dir, "r3", "completed", workflow_id="alpha")

    r = client.get("/api/workflows/alpha/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["workflow_id"] == "alpha"
    ids = {run["run_id"] for run in body["runs"]}
    assert ids == {"r1", "r3"}
    assert all(run["workflow_id"] == "alpha" for run in body["runs"])


def test_list_workflow_runs_empty_when_none(client, data_dir):
    _write_run(data_dir, "r1", "completed", workflow_id="alpha")
    r = client.get("/api/workflows/ghost/runs")
    assert r.status_code == 200
    assert r.json()["runs"] == []


def test_list_workflow_runs_rejects_traversal(client, data_dir):
    # '.' is outside the workflow-id allowlist — the traversal '..' payload is
    # rejected 400 (single URL segment so the guard, not path normalization,
    # is what's under test).
    r = client.get("/api/workflows/etc.passwd/runs")
    assert r.status_code == 400


# ── mark-failed (GP-2 commit 7) ─────────────────────────────────────────────


def test_mark_failed_missing_run_404(client, data_dir):
    r = client.post("/api/workflows/runs/nope/mark-failed")
    assert r.status_code == 404


def test_mark_failed_rejects_traversal(client, data_dir):
    r = client.post("/api/workflows/runs/etc..passwd/mark-failed")
    assert r.status_code == 400


def test_mark_failed_flips_zombie_to_failed(client, data_dir):
    """A stalled run stuck in 'running' is persisted as failed so the operator
    can then resume-from-failed (which 409s a non-failed run)."""
    _write_run(data_dir, "zombie", "running")
    r = client.post("/api/workflows/runs/zombie/mark-failed")
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is True
    assert body["status"] == "failed"
    assert body["error"]  # a reason is recorded
    persisted = json.loads((data_dir / "zombie" / "run.json").read_text())
    assert persisted["status"] == "failed"
    assert persisted["completed_at"]


def test_mark_failed_is_noop_on_terminal_run(client, data_dir):
    """A legitimately-completed run is never clobbered."""
    _write_run(data_dir, "done", "completed")
    r = client.post("/api/workflows/runs/done/mark-failed")
    assert r.status_code == 200
    assert r.json()["changed"] is False
    persisted = json.loads((data_dir / "done" / "run.json").read_text())
    assert persisted["status"] == "completed"  # untouched


def test_marked_failed_run_can_then_resume(client, data_dir):
    """mark-failed → resume-from-failed is the intended zombie-recovery chain."""
    from api.models.workflow_models import WorkflowRun

    _write_run(data_dir, "z2", "running")
    assert client.post("/api/workflows/runs/z2/mark-failed").status_code == 200
    # Now it's failed, resume-from-failed accepts it (engine.resume stubbed).
    resumed = WorkflowRun(run_id="z2", workflow_id="wf-x", status="completed",
                          context={"seed": {}})
    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume", return_value=resumed
    ):
        r = client.post("/api/workflows/runs/z2/resume-from-failed")
    assert r.status_code == 200
    assert r.json()["resumed_from_failed"] is True
