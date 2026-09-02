"""CH-1 — resume-from-failed + workflow-scoped run index.

Covers the two add-only workflow routes CH-1 introduces:

  POST /api/workflows/runs/{run_id}/resume-from-failed
  GET  /api/workflows/{workflow_id}/runs

Guards (404 missing / 409 not-failed / 400 traversal), the happy-path load-
definition-then-flip-then-resume (mirrors resolve_approval — the definition is
confirmed loadable FIRST, then the failed run is flipped to running,
checkpointed, then engine.resume re-dispatches with that definition), the
fail-safe paths (no definition → 404 with the run untouched; resume blowing up
→ the pre-flip snapshot is restored, never a `running` zombie), the inline
definition sidecar prepare_run persists for unsaved Composer runs, and the
read-model filter.

No live engine / ollama needed: engine.resume is stubbed so the test exercises
the ROUTER contract (status guards, the status flip + checkpoint, the response
shape), not the engine internals (the frozen engine is covered elsewhere).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # Auth + rate limiting off explicitly so the file is order-independent
    # (it used to inherit that state from whichever test ran before it).
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
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


@pytest.fixture
def workflows_dir(tmp_path, monkeypatch):
    """Point saved-yaml resolution at an empty tmp dir (and the private overlay
    at a non-existent one) so a test's `wf-x` never accidentally resolves to a
    real ./workflows/*.yaml on disk."""
    d = tmp_path / "wf"
    d.mkdir()
    monkeypatch.setattr("api.routers.workflows.WORKFLOWS_DIR", str(d))
    monkeypatch.setenv("WORKFLOWS_PRIVATE_DIR", str(tmp_path / "wf-private-missing"))
    return d


def _defn(workflow_id="wf-x", system_prompt="Analyze.") -> dict:
    """A minimal definition the engine's load_from_dict accepts offline."""
    return {
        "id": workflow_id,
        "name": "Test WF",
        "defaults": {"role": "general", "retries": 0, "retry_delay": 0},
        "steps": [
            {
                "id": "s1",
                "name": "Step 1",
                "role": "fast",
                "system_prompt": system_prompt,
                "inputs": ["seed.task"],
                "outputs": ["result"],
            },
            {
                "id": "s2",
                "name": "Step 2",
                "role": "fast",
                "system_prompt": "Refine.",
                "inputs": ["s1.result"],
                "outputs": ["final"],
            },
        ],
    }


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


def _write_sidecar(data_dir: Path, run_id: str, definition) -> Path:
    """The inline definition sidecar prepare_run keeps for unsaved runs."""
    rd = data_dir / run_id
    rd.mkdir(parents=True, exist_ok=True)
    p = rd / "definition.json"
    p.write_text(definition if isinstance(definition, str) else json.dumps(definition))
    return p


def _persisted_status(data_dir: Path, run_id: str) -> str:
    return json.loads((data_dir / run_id / "run.json").read_text())["status"]


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


def test_resume_from_failed_flips_and_resumes(client, data_dir, workflows_dir):
    """A failed run (with its inline definition sidecar) is flipped to running,
    checkpointed, then resumed WITH the loaded definition."""
    from api.models.workflow_models import WorkflowRun

    _write_run(
        data_dir,
        "run-failed",
        "failed",
        step_results=[{"step_id": "s1", "status": "completed"},
                      {"step_id": "s2", "status": "failed", "error": "boom"}],
    )
    _write_sidecar(data_dir, "run-failed", _defn())

    resumed = WorkflowRun(
        run_id="run-failed", workflow_id="wf-x", status="completed",
        context={"seed": {}},
    )

    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume",
        return_value=resumed,
    ) as mock_resume:
        r = client.post("/api/workflows/runs/run-failed/resume-from-failed")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resumed_from_failed"] is True
    assert body["status"] == "completed"
    assert body["run_id"] == "run-failed"
    mock_resume.assert_called_once()
    # The router hands the engine the definition it already confirmed loads —
    # an inline run has no yaml the engine could reload on its own.
    passed = mock_resume.call_args.kwargs.get("definition")
    assert passed is not None and passed.id == "wf-x"
    # The checkpoint BEFORE resume must have flipped the persisted snapshot off
    # its terminal 'failed' state so a crash mid-resume leaves it recoverable.
    # (resume is stubbed, so nothing wrote a terminal state afterwards.)
    assert _persisted_status(data_dir, "run-failed") == "running"


def test_resume_from_failed_prefers_saved_yaml_over_sidecar(
    client, data_dir, workflows_dir
):
    """Fix&Resume: the operator's just-SAVED yaml wins over the inline
    definition the run was originally started with."""
    from api.models.workflow_models import WorkflowRun

    _write_run(data_dir, "run-f", "failed")
    _write_sidecar(data_dir, "run-f", _defn(system_prompt="ORIGINAL"))
    (workflows_dir / "wf-x.yaml").write_text(
        yaml.safe_dump(_defn(system_prompt="EDITED"))
    )
    resumed = WorkflowRun(run_id="run-f", workflow_id="wf-x", status="completed",
                          context={"seed": {}})
    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume", return_value=resumed
    ) as mock_resume:
        r = client.post("/api/workflows/runs/run-f/resume-from-failed")
    assert r.status_code == 200, r.text
    passed = mock_resume.call_args.kwargs["definition"]
    assert passed.steps[0].system_prompt == "EDITED"


def test_resume_from_failed_without_definition_is_404_and_stays_failed(
    client, data_dir, workflows_dir
):
    """The zombie defect: no saved yaml + no sidecar used to flip the run to
    `running` and THEN 500 on FileNotFoundError. Now: 404, run untouched."""
    _write_run(data_dir, "orphan", "failed")
    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume"
    ) as mock_resume:
        r = client.post("/api/workflows/runs/orphan/resume-from-failed")
    assert r.status_code == 404, r.text
    assert "no definition" in r.json()["detail"]
    mock_resume.assert_not_called()
    assert _persisted_status(data_dir, "orphan") == "failed"


def test_resume_from_failed_invalid_sidecar_is_422_and_stays_failed(
    client, data_dir, workflows_dir
):
    _write_run(data_dir, "bad", "failed")
    _write_sidecar(data_dir, "bad", {"id": "wf-x", "steps": "not-a-list"})
    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume"
    ) as mock_resume:
        r = client.post("/api/workflows/runs/bad/resume-from-failed")
    assert r.status_code == 422, r.text
    mock_resume.assert_not_called()
    assert _persisted_status(data_dir, "bad") == "failed"


def test_resume_blowing_up_restores_failed_snapshot(client, data_dir, workflows_dir):
    """If engine.resume raises after the flip, the pre-flip snapshot is put
    back — a failed run stays failed and Fix&Resume-able, never a `running`
    zombie nothing is executing."""
    _write_run(data_dir, "boom", "failed",
               step_results=[{"step_id": "s2", "status": "failed", "error": "x"}])
    _write_sidecar(data_dir, "boom", _defn())
    with patch(
        "api.services.workflow_engine.WorkflowEngine.resume",
        side_effect=RuntimeError("engine exploded"),
    ):
        r = client.post("/api/workflows/runs/boom/resume-from-failed")
    assert r.status_code == 500
    assert "engine exploded" in r.json()["detail"]
    persisted = json.loads((data_dir / "boom" / "run.json").read_text())
    assert persisted["status"] == "failed"
    assert persisted["step_results"][0]["status"] == "failed"


def test_run_async_inline_definition_persists_sidecar(client, data_dir, monkeypatch):
    """prepare_run keeps the originating inline definition next to the run
    checkpoint so an unsaved Composer run can be resumed later."""
    monkeypatch.setattr(
        "api.services.run_dispatch.dispatch_blocking", lambda *a, **k: None
    )
    r = client.post(
        "/api/workflows/run-async",
        json={"definition": _defn("inline-wf"), "seed": {"task": "hi"}},
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    sidecar = json.loads((data_dir / run_id / "definition.json").read_text())
    assert sidecar["id"] == "inline-wf"
    assert [s["id"] for s in sidecar["steps"]] == ["s1", "s2"]
    # Round-trips through the reader the resume path uses.
    from api.services.run_dispatch import read_definition_sidecar

    assert read_definition_sidecar(run_id)["id"] == "inline-wf"


def test_run_async_saved_workflow_writes_no_sidecar(client, data_dir, tmp_path, monkeypatch):
    """A run started from a saved yaml has a yaml to reload — no sidecar."""
    wfd = tmp_path / "wfs"
    wfd.mkdir()
    (wfd / "saved-wf.yaml").write_text(yaml.safe_dump(_defn("saved-wf")))
    monkeypatch.setattr("api.services.run_dispatch.WORKFLOWS_DIR", str(wfd))
    monkeypatch.setenv("WORKFLOWS_PRIVATE_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(
        "api.services.run_dispatch.dispatch_blocking", lambda *a, **k: None
    )
    r = client.post(
        "/api/workflows/run-async",
        json={"workflow_id": "saved-wf", "seed": {"task": "hi"}},
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    assert not (data_dir / run_id / "definition.json").exists()


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


def test_marked_failed_run_can_then_resume(client, data_dir, workflows_dir):
    """mark-failed → resume-from-failed is the intended zombie-recovery chain."""
    from api.models.workflow_models import WorkflowRun

    _write_run(data_dir, "z2", "running")
    _write_sidecar(data_dir, "z2", _defn())
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
