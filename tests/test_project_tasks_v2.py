#!/usr/bin/env python3
"""U2 — op2-projects-backend-v2.

Covers the unit's verify list:
  - task field whitelist extension (due/start/estimate/priority/milestone) on
    create + PATCH; origin is server-set and NOT PATCHable;
  - the additive 5-column enum (backlog|todo|doing|review|done) at both the
    create and patch validation sites; legacy todo/doing/done untouched;
  - GET /tasks?history=1 replay accumulates a per-task status trail with zero
    new writes;
  - proposed-event replay semantics: state:"proposed" events are invisible to
    the normal board, an accept re-append materialises them, reject markers are
    skipped, pending-proposal count feeds the 50-cap groundwork;
  - data/projects/<id>/runs.jsonl GET/POST, POST master-key gated;
  - POST /api/projects/{id}/context-workspace: default docs root, idempotent
    skeleton seed, vault→00-Inbox re-root, sets context_workspace, 401 without
    key when auth on, 404 for a missing project;
  - the frozen engine files are untouched.

Run:  pytest tests/test_project_tasks_v2.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.main

    return TestClient(api.main.app)


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    """Point the task/run JSONL store, the project service, and the workspace
    registry at an isolated tmp tree."""
    from api.routers import projects as projects_router
    from api.services import project_service as ps_mod
    from api.services import workspace as ws_mod

    data_dir = tmp_path / "projects"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(projects_router, "_DATA_DIR", data_dir)

    svc = ps_mod.ProjectService(projects_dir=str(data_dir))
    monkeypatch.setattr(ps_mod, "_default_service", svc)

    monkeypatch.setenv("ENCLAVE_DATA_DIR", str(tmp_path / "wsdata"))
    monkeypatch.setattr(ws_mod, "_registry", None)
    return {"data_dir": data_dir, "svc": svc, "tmp": tmp_path}


# ── Task fields extension ──────────────────────────────────────────────────


def test_create_task_carries_extra_fields(client, isolate):
    r = client.post(
        "/api/projects/p1/tasks",
        json={
            "title": "Ship U2",
            "due_date": "2026-07-20",
            "start_date": "2026-07-12",
            "estimate": 8,
            "priority": "p1",
            "milestone": "backend-v2",
        },
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["due_date"] == "2026-07-20"
    assert t["start_date"] == "2026-07-12"
    assert t["estimate"] == 8
    assert t["priority"] == "p1"
    assert t["milestone"] == "backend-v2"
    # origin is server-set on operator creates.
    assert t["origin"] == "operator"


def test_patch_task_updates_fields(client, isolate):
    tid = client.post("/api/projects/p1/tasks", json={"title": "x"}).json()["id"]
    r = client.patch(
        f"/api/projects/p1/tasks/{tid}",
        json={"priority": "p0", "milestone": "m", "estimate": 2},
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["priority"] == "p0" and t["milestone"] == "m" and t["estimate"] == 2


def test_origin_not_patchable(client, isolate):
    tid = client.post("/api/projects/p1/tasks", json={"title": "x"}).json()["id"]
    client.patch(f"/api/projects/p1/tasks/{tid}", json={"origin": "agent"})
    tasks = client.get("/api/projects/p1/tasks").json()
    assert next(t for t in tasks if t["id"] == tid)["origin"] == "operator"


@pytest.mark.parametrize(
    "body,frag",
    [
        ({"title": "x", "due_date": "not-a-date"}, "iso date"),
        ({"title": "x", "priority": "p9"}, "priority"),
        ({"title": "x", "estimate": 99}, "0..16"),
        ({"title": "x", "estimate": "abc"}, "number"),
    ],
)
def test_field_validation_400(client, isolate, body, frag):
    r = client.post("/api/projects/p1/tasks", json=body)
    assert r.status_code == 400
    assert frag in r.json()["detail"].lower()


# ── Additive 5-column enum ─────────────────────────────────────────────────


@pytest.mark.parametrize("col", ["backlog", "todo", "doing", "review", "done"])
def test_all_five_columns_accepted(client, isolate, col):
    r = client.post("/api/projects/p1/tasks", json={"title": "c", "column": col})
    assert r.status_code == 200
    assert r.json()["column"] == col


def test_unknown_column_rejected(client, isolate):
    r = client.post("/api/projects/p1/tasks", json={"title": "c", "column": "nope"})
    assert r.status_code == 400
    r = client.patch(
        f"/api/projects/p1/tasks/"
        + client.post("/api/projects/p1/tasks", json={"title": "y"}).json()["id"],
        json={"column": "nope"},
    )
    assert r.status_code == 400


# ── history=1 replay ───────────────────────────────────────────────────────


def test_history_replay_accumulates_column_trail(client, isolate):
    tid = client.post(
        "/api/projects/p1/tasks", json={"title": "h", "column": "todo"}
    ).json()["id"]
    client.patch(f"/api/projects/p1/tasks/{tid}", json={"column": "doing"})
    client.patch(f"/api/projects/p1/tasks/{tid}", json={"column": "done"})

    plain = client.get("/api/projects/p1/tasks").json()
    assert "history" not in plain[0]

    hist = client.get("/api/projects/p1/tasks?history=1").json()
    trail = next(t for t in hist if t["id"] == tid)["history"]
    cols = [h["column"] for h in trail]
    assert cols == ["todo", "doing", "done"]
    assert all(h["ts"] for h in trail)


# ── Proposed-event replay semantics ────────────────────────────────────────


def test_proposed_events_are_invisible_until_accepted(client, isolate):
    from api.routers import projects as pr

    pid = pr._new_proposal_id()
    # An AI plan-op lands proposed in the same log.
    pr._append_event(
        "p1",
        {
            "id": "task_prop1",
            "title": "proposed task",
            "column": "backlog",
            "origin": "agent",
            "state": "proposed",
            "proposal_id": pid,
        },
    )
    # Invisible to the normal board.
    assert client.get("/api/projects/p1/tasks").json() == []
    # But visible when explicitly including proposals.
    assert len(pr._read_tasks("p1", include_proposed=True)) == 1
    assert pr._pending_proposal_count("p1") == 1

    # Accept: re-append the effective event (no proposed flag) + approved_at.
    pr._append_event(
        "p1",
        {
            "id": "task_prop1",
            "title": "proposed task",
            "column": "backlog",
            "origin": "agent",
            "proposal_id": pid,
            "approved_at": "2026-07-12T00:00:00Z",
        },
    )
    board = client.get("/api/projects/p1/tasks").json()
    assert [t["id"] for t in board] == ["task_prop1"]
    assert pr._pending_proposal_count("p1") == 0


def test_rejected_proposal_stays_invisible(client, isolate):
    from api.routers import projects as pr

    pid = pr._new_proposal_id()
    pr._append_event(
        "p1",
        {
            "id": "task_prop2",
            "title": "rej",
            "column": "todo",
            "state": "proposed",
            "proposal_id": pid,
        },
    )
    pr._append_event("p1", {"proposal_id": pid, "op": "reject"})
    assert client.get("/api/projects/p1/tasks").json() == []
    assert pr._pending_proposal_count("p1") == 0


# ── runs.jsonl ─────────────────────────────────────────────────────────────


def test_runs_get_post_roundtrip(client, isolate):
    assert client.get("/api/projects/p1/runs").json() == []
    r = client.post(
        "/api/projects/p1/runs",
        json={
            "run_id": "run-abc",
            "workflow_id": "wf1",
            "label": "nightly",
            "task_id": "task_1",
        },
    )
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["run_id"] == "run-abc" and ref["task_id"] == "task_1"
    assert ref["origin"] == "operator" and ref["ts"]
    rows = client.get("/api/projects/p1/runs").json()
    assert [x["run_id"] for x in rows] == ["run-abc"]


def test_runs_post_requires_run_id(client, isolate):
    assert client.post("/api/projects/p1/runs", json={}).status_code == 400


# ── context-workspace bind (service level) ─────────────────────────────────


def test_bind_default_root_seeds_skeleton(isolate):
    svc = isolate["svc"]
    from api.models.project_models import ProjectCreate

    svc.create_project(ProjectCreate(id="proj1", name="Proj One"))
    out = svc.bind_context_workspace("proj1")
    assert out["workspace"] == "proj-proj1"
    root = Path(out["root"])
    assert root.name == "docs"
    # Skeleton seeded.
    assert (root / "index.md").is_file()
    assert (root / "notes" / "status.md").is_file()
    assert (root / "decisions" / "log.md").is_file()
    assert (root / "specs").is_dir() and (root / "plans").is_dir()
    # Binding persisted.
    assert svc.get_project("proj1")["context_workspace"] == "proj-proj1"


def test_bind_is_idempotent(isolate):
    svc = isolate["svc"]
    from api.models.project_models import ProjectCreate

    svc.create_project(ProjectCreate(id="proj2", name="Two"))
    svc.bind_context_workspace("proj2")
    root = Path(svc.bind_context_workspace("proj2")["root"])
    # Operator edit survives a re-bind (seed never clobbers).
    (root / "index.md").write_text("# my own MOC\n", encoding="utf-8")
    svc.bind_context_workspace("proj2")
    assert (root / "index.md").read_text(encoding="utf-8") == "# my own MOC\n"


def test_bind_vault_reroots_to_inbox(isolate, tmp_path):
    svc = isolate["svc"]
    from api.models.project_models import ProjectCreate

    vault = tmp_path / "myvault"
    (vault / ".obsidian").mkdir(parents=True)
    svc.create_project(ProjectCreate(id="proj3", name="Three"))
    out = svc.bind_context_workspace("proj3", root=str(vault))
    root = Path(out["root"])
    assert root == (vault / "00-Inbox").resolve()
    # A subdirectory of the vault also re-roots at the vault's 00-Inbox.
    svc.create_project(ProjectCreate(id="proj3b", name="ThreeB"))
    out2 = svc.bind_context_workspace("proj3b", root=str(vault / "sub" / "deep"))
    assert Path(out2["root"]) == (vault / "00-Inbox").resolve()


def test_bind_missing_project_raises(isolate):
    with pytest.raises(KeyError):
        isolate["svc"].bind_context_workspace("ghost")


# ── Auth: master-key gated writes 401 without key when auth on ─────────────


def test_master_gated_writes_401_with_auth_on(client, isolate, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.post("/api/projects/p1/runs", json={"run_id": "r"}).status_code == 401
    assert (
        client.post("/api/projects/p1/context-workspace", json={}).status_code == 401
    )


def test_read_routes_carry_no_master_gate():
    """No project READ route declares require_master_key; only the write
    surfaces do (runs-POST + context-workspace from U2; plan/apply + proposal
    accept/reject from U12)."""
    from api.routers import projects as pr

    gated = set()
    for route in pr.router.routes:
        dep = getattr(route, "dependant", None)
        if not dep:
            continue
        # Compare by function NAME, not object identity: when another test in
        # the session reloads api.middleware, require_master_key is rebound to a
        # new object while the router's already-built routes still reference the
        # original — an identity `in` check then yields an empty set (a test-
        # pollution flake that only bites in the full suite). Name is reload-proof.
        call_names = [
            getattr(getattr(d, "call", None), "__name__", "")
            for d in dep.dependencies
        ]
        if "require_master_key" in call_names:
            for m in getattr(route, "methods", set()) or set():
                gated.add(f"{m} {route.path}")
    assert gated == {
        "POST /api/projects/{project_id}/runs",
        "POST /api/projects/{project_id}/context-workspace",
        "POST /api/projects/{project_id}/plan/apply",
        "POST /api/projects/{project_id}/proposals/{proposal_id}/accept",
        "POST /api/projects/{project_id}/proposals/{proposal_id}/reject",
    }


# ── Frozen engine untouched ────────────────────────────────────────────────


def test_frozen_engine_untouched():
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=_REPO,
        capture_output=True,
        text=True,
    ).stdout
    for frozen in (
        "api/services/workflow_engine.py",
        "api/services/step_executor.py",
        "api/models/workflow_models.py",
    ):
        assert frozen not in out, f"{frozen} is frozen — must not be edited"
