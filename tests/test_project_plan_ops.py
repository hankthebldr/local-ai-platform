#!/usr/bin/env python3
"""U12 — op2-plan-ops-ai.

Covers the unit's verify list:
  - plan/apply schema reject (malformed op → 400);
  - propose → accept → materialises on the board;
  - reject annuls a proposal (invisible, resolved);
  - per-op errors array (unknown-id update skipped, rest lands);
  - 50-pending cap → 409;
  - SKILL.md fenced schema block deep-equals the router's PLAN_OPS_SCHEMA;
  - the enclave-pm plugin's pm_plan_apply lands PROPOSED (not on the board);
  - auth-on: plan/apply + accept require the master key (401 without);
  - the frozen engine files are untouched.

Run:  pytest tests/test_project_plan_ops.py -v
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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
    """Point the task JSONL store at an isolated tmp tree per test."""
    from api.routers import projects as projects_router

    data_dir = tmp_path / "projects"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(projects_router, "_DATA_DIR", data_dir)
    return {"data_dir": data_dir}


def _tasks(client, pid):
    return client.get(f"/api/projects/{pid}/tasks").json()


def _proposals(client, pid):
    return client.get(f"/api/projects/{pid}/proposals").json()


# ── Schema reject ───────────────────────────────────────────────────────────


def test_plan_apply_schema_reject_bad_op(client, isolate):
    r = client.post(
        "/api/projects/p1/plan/apply",
        json={"ops": [{"op": "nuke_everything", "title": "x"}]},
    )
    assert r.status_code == 400, r.text
    assert "schema" in r.json()["detail"].lower()


def test_plan_apply_schema_reject_missing_required(client, isolate):
    # add_task without title violates the conditional required block.
    r = client.post(
        "/api/projects/p1/plan/apply",
        json={"ops": [{"op": "add_task"}]},
    )
    assert r.status_code == 400


def test_plan_apply_rejects_non_array(client, isolate):
    r = client.post("/api/projects/p1/plan/apply", json={"ops": {"op": "add_task"}})
    assert r.status_code == 400


# ── Propose → accept → board ────────────────────────────────────────────────


def test_propose_is_invisible_until_accepted(client, isolate):
    r = client.post(
        "/api/projects/pa/plan/apply",
        json={"ops": [{"op": "add_task", "title": "Draft model", "column": "todo"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ops_accepted"] == 1
    assert body["pending_count"] == 1
    pid = body["proposal_id"]
    assert pid and pid.startswith("prop_")

    # Board does NOT show the proposed task yet.
    assert _tasks(client, "pa") == []
    # But it shows up in the proposals list.
    props = _proposals(client, "pa")
    assert len(props) == 1 and props[0]["proposal_id"] == pid
    assert props[0]["ops"][0]["op"] == "add_task"

    # Accept → it materialises on the board.
    ar = client.post(f"/api/projects/pa/proposals/{pid}/accept")
    assert ar.status_code == 200, ar.text
    tasks = _tasks(client, "pa")
    assert len(tasks) == 1
    t = tasks[0]
    assert t["title"] == "Draft model" and t["column"] == "todo"
    assert t["origin"] == "agent"
    # Proposal is now resolved (no longer pending).
    assert _proposals(client, "pa") == []


def test_accept_update_and_set_status(client, isolate):
    # Seed a real (operator) task first.
    tid = client.post(
        "/api/projects/pu/tasks", json={"title": "seed", "column": "todo"}
    ).json()["id"]
    r = client.post(
        "/api/projects/pu/plan/apply",
        json={
            "ops": [
                {"op": "update_task", "id": tid, "priority": "p0"},
                {"op": "set_status", "id": tid, "column": "doing"},
                {"op": "set_milestone", "id": tid, "milestone": "v1"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ops_accepted"] == 3
    pid = r.json()["proposal_id"]
    # before-state is exposed for the diff panel.
    props = _proposals(client, "pu")
    assert props[0]["ops"][0]["before"]["id"] == tid
    client.post(f"/api/projects/pu/proposals/{pid}/accept")
    t = next(x for x in _tasks(client, "pu") if x["id"] == tid)
    assert t["priority"] == "p0"
    assert t["column"] == "doing"
    assert t["milestone"] == "v1"


# ── Reject ──────────────────────────────────────────────────────────────────


def test_reject_annuls_proposal(client, isolate):
    r = client.post(
        "/api/projects/pr/plan/apply",
        json={"ops": [{"op": "add_task", "title": "nope"}]},
    )
    pid = r.json()["proposal_id"]
    rr = client.post(f"/api/projects/pr/proposals/{pid}/reject")
    assert rr.status_code == 200, rr.text
    assert _tasks(client, "pr") == []
    assert _proposals(client, "pr") == []
    # Accepting an already-rejected proposal 404s.
    assert client.post(f"/api/projects/pr/proposals/{pid}/accept").status_code == 404


def test_accept_unknown_proposal_404(client, isolate):
    assert (
        client.post("/api/projects/px/proposals/prop_deadbeef/accept").status_code
        == 404
    )


# ── Per-op errors array ─────────────────────────────────────────────────────


def test_per_op_errors_skip_bad_ops(client, isolate):
    r = client.post(
        "/api/projects/pe/plan/apply",
        json={
            "ops": [
                {"op": "add_task", "title": "good"},
                {"op": "update_task", "id": "task_does_not_exist", "priority": "p1"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ops_accepted"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["index"] == 1
    assert "unknown task id" in body["errors"][0]["error"]


# ── 50-pending cap ──────────────────────────────────────────────────────────


def test_pending_cap_409(client, isolate):
    from api.routers.projects import MAX_PENDING_PROPOSALS

    for _ in range(MAX_PENDING_PROPOSALS):
        rr = client.post(
            "/api/projects/pc/plan/apply",
            json={"ops": [{"op": "add_task", "title": "t"}]},
        )
        assert rr.status_code == 200
    over = client.post(
        "/api/projects/pc/plan/apply",
        json={"ops": [{"op": "add_task", "title": "over"}]},
    )
    assert over.status_code == 409, over.text


# ── SKILL.md ↔ router schema drift guard ────────────────────────────────────


def test_skill_schema_matches_router_constant():
    from api.routers.projects import PLAN_OPS_SCHEMA

    skill = (
        _REPO / "docs/superpowers/skills/enclave-pm/SKILL.md"
    ).read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", skill, re.DOTALL)
    # The first fenced json block that parses to a dict with $schema is the
    # authoritative schema; the example plan is an array (skipped).
    parsed = None
    for b in blocks:
        try:
            obj = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("$schema"):
            parsed = obj
            break
    assert parsed is not None, "no fenced json schema block found in SKILL.md"
    assert parsed == PLAN_OPS_SCHEMA


# ── enclave-pm plugin tool lands proposed ───────────────────────────────────


def test_plugin_pm_plan_apply_lands_proposed(client, isolate):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "enclave_pm_tools", _REPO / "plugins/enclave-pm/tools.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    res = mod.pm_plan_apply("pp", json.dumps([{"op": "add_task", "title": "via-plugin"}]))
    assert res["ops_accepted"] == 1
    assert res["proposal_id"]
    # Proposed → NOT on the board.
    assert mod.pm_list_tasks("pp")["tasks"] == []
    # Visible as a pending proposal.
    props = _proposals(client, "pp")
    assert len(props) == 1
    # Accept via HTTP → plugin's list now shows it.
    client.post(f"/api/projects/pp/proposals/{props[0]['proposal_id']}/accept")
    assert len(mod.pm_list_tasks("pp")["tasks"]) == 1


def test_plugin_log_run(client, isolate):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "enclave_pm_tools2", _REPO / "plugins/enclave-pm/tools.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ref = mod.pm_log_run("pl", "run_abc", "a label")
    assert ref["run_id"] == "run_abc" and ref["origin"] == "agent"
    runs = client.get("/api/projects/pl/runs").json()
    assert any(r["run_id"] == "run_abc" for r in runs)


# ── Auth-on: master key required ────────────────────────────────────────────


def test_auth_on_requires_master_key(client, isolate, monkeypatch):
    """With ENABLE_API_AUTH=true, plan/apply + accept/reject demand the master
    key. require_master_key reads the env at call time (see the U2 pattern), so
    no app reload is needed — flip the env and assert."""
    body = {"ops": [{"op": "add_task", "title": "x"}]}
    # Seed a proposal while auth is off so we have a pid to test accept-gating.
    r = client.post("/api/projects/pz/plan/apply", json=body)
    pid = r.json()["proposal_id"]

    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    # No key → 401 on every write surface (mirrors the U2 auth-on pattern).
    assert client.post("/api/projects/pz/plan/apply", json=body).status_code == 401
    assert client.post(f"/api/projects/pz/proposals/{pid}/accept").status_code == 401
    assert client.post(f"/api/projects/pz/proposals/{pid}/reject").status_code == 401


# ── Frozen engine untouched ─────────────────────────────────────────────────


def test_frozen_engine_untouched():
    frozen = [
        "api/services/workflow_engine.py",
        "api/services/step_executor.py",
        "api/models/workflow_models.py",
    ]
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *frozen],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "", f"frozen engine changed: {out.stdout}"
