#!/usr/bin/env python3
"""PT-1 — Patterns library router (api/routers/patterns.py).

Covers the unit's verify list:
  - PatternSchema CRUD roundtrip over user_storage_root/patterns/<id>.json;
  - 409 on create-exists (user layer AND shipped/oob id);
  - 404 on patch/delete/get of a missing pattern;
  - copy-on-write PATCH of a builtin id (auto-promote → provenance flips);
  - 403 on DELETE of a pure-oob (builtin-only) id; reverted_to_oob on delete of
    a copy-on-write'd builtin;
  - promote copies a builtin into the user layer (409 when a user copy exists,
    404 when there is no builtin);
  - path containment rejects traversal / bad-charset ids (the real
    glob-traversal incident — every new file route gets this);
  - SAFETY RAIL: a stored pattern whose steps don't construct through the
    frozen WorkflowDefinition is rejected 422 (un-scaffoldable DAG);
  - the 8 curated builtins merge in and each validates as a workflow;
  - writes 401 with auth on (create/patch/delete/promote); reads stay open;
  - the frozen engine files are untouched (router imports read-only).

Run:  pytest tests/test_patterns.py -q
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.routers import patterns as patterns_router

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Isolated empty user pattern store."""
    root = tmp_path / "patterns"
    root.mkdir(parents=True)
    monkeypatch.setattr(patterns_router, "_patterns_root", lambda: root)
    return root


def _simple(pattern_id="my_pattern", **over):
    base = {
        "id": pattern_id,
        "name": "My Pattern",
        "complexity": "SIMPLE",
        "kind": "llm",
        "desc": "A one-step preset.",
        "steps": [
            {
                "id": "step_1",
                "name": "Step 1",
                "kind": "llm",
                "role": "general",
                "system_prompt": "Do the thing.",
                "inputs": ["seed.query"],
                "outputs": ["result"],
            }
        ],
        "tags": ["simple", "llm"],
    }
    base.update(over)
    return base


# ── CRUD roundtrip ──────────────────────────────────────────────────────────


def test_pattern_crud_roundtrip(client, store):
    r = client.post("/api/patterns", json=_simple())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "user"
    assert (store / "my_pattern.json").is_file()

    rows = client.get("/api/patterns").json()
    ids = [x["id"] for x in rows]
    assert "my_pattern" in ids
    # the 8 shipped builtins merge in alongside the user pattern
    assert {"llm_step", "ralph_loop", "research_fanout"} <= set(ids)

    got = client.get("/api/patterns/my_pattern").json()
    assert got["name"] == "My Pattern" and got["kind"] == "llm"

    r = client.patch("/api/patterns/my_pattern", json={"name": "Renamed", "steps": got["steps"]})
    assert r.status_code == 200, r.text
    assert client.get("/api/patterns/my_pattern").json()["name"] == "Renamed"

    assert client.delete("/api/patterns/my_pattern").status_code == 200
    assert client.get("/api/patterns/my_pattern").status_code == 404


def test_create_409_on_user_exists(client, store):
    assert client.post("/api/patterns", json=_simple()).status_code == 201
    assert client.post("/api/patterns", json=_simple()).status_code == 409


def test_create_409_on_shipped_id(client, store):
    r = client.post("/api/patterns", json=_simple("llm_step"))
    assert r.status_code == 409
    assert "oob" in r.json()["detail"] or "promote" in r.json()["detail"]


def test_patch_delete_missing_404(client, store):
    assert client.patch("/api/patterns/ghost", json={"steps": _simple()["steps"]}).status_code == 404
    assert client.delete("/api/patterns/ghost").status_code == 404


# ── Safety rail: un-scaffoldable steps rejected 422 ─────────────────────────


def test_unscaffoldable_dag_rejected_422(client, store):
    # AgentStep requires >=1 output — a step without outputs cannot construct.
    bad = _simple(steps=[{"id": "x", "name": "X", "kind": "llm"}])
    r = client.post("/api/patterns", json=bad)
    assert r.status_code == 422, r.text
    assert "scaffoldable" in r.json()["detail"].lower()
    assert not (store / "my_pattern.json").is_file()


def test_empty_steps_rejected_422(client, store):
    r = client.post("/api/patterns", json=_simple(steps=[]))
    assert r.status_code == 422


# ── Merge / shadow / copy-on-write / promote (the prompts.py model) ─────────


def test_builtin_merge_and_provenance(client, store):
    rows = {r["id"]: r for r in client.get("/api/patterns").json()}
    assert len(rows) >= 8
    for bid in ("llm_step", "ralph_loop", "code_sandbox"):
        assert bid in rows and rows[bid]["source"] == "builtin"


def test_copy_on_write_patch_of_builtin_then_revert(client, store):
    # Editing a builtin id copies it into the user layer (auto-promote).
    got = client.get("/api/patterns/llm_step").json()
    r = client.patch("/api/patterns/llm_step", json={"desc": "operator-tuned", "steps": got["steps"]})
    assert r.status_code == 200, r.text
    assert (store / "llm_step.json").is_file()
    assert client.get("/api/patterns/llm_step").json()["desc"] == "operator-tuned"
    # Deleting the user copy reverts to the shipped builtin (still listable).
    d = client.delete("/api/patterns/llm_step")
    assert d.status_code == 200
    assert d.json()["reverted_to_oob"] is True
    assert client.get("/api/patterns/llm_step").json()["source"] == "builtin"


def test_delete_pure_builtin_403(client, store):
    r = client.delete("/api/patterns/ralph_loop")
    assert r.status_code == 403
    assert "shipped" in r.json()["detail"].lower()


def test_promote_builtin_then_409(client, store):
    r = client.post("/api/patterns/research_fanout/promote", json={})
    assert r.status_code == 201, r.text
    assert (store / "research_fanout.json").is_file()
    assert client.get("/api/patterns/research_fanout").json()["source"] == "user"
    # second promote → a user copy already exists → 409
    assert client.post("/api/patterns/research_fanout/promote", json={}).status_code == 409
    # promote of a non-builtin → 404
    assert client.post("/api/patterns/not_a_pattern/promote", json={}).status_code == 404


# ── Path containment (the glob-traversal incident lesson) ──────────────────


@pytest.mark.parametrize(
    "bad", ["../escape", "..%2fescape", "a/b", "with space", "-lead", "a" * 90]
)
def test_traversal_and_bad_ids_rejected(client, store, bad):
    from urllib.parse import quote

    r = client.get(f"/api/patterns/{quote(bad, safe='')}")
    assert r.status_code in (400, 404)
    assert not any(
        p.name.endswith(".json")
        for p in store.parent.rglob("*.json")
        if store not in p.parents
    )


def test_create_traversal_id_rejected(client, store):
    r = client.post("/api/patterns", json=_simple("../evil"))
    assert r.status_code == 400
    assert not list(store.parent.glob("evil.json"))


# ── Complex user patterns round-trip ────────────────────────────────────────


def test_complex_user_pattern_round_trips(client, store):
    """A COMPLEX (ralph) user pattern with a nested body scaffolds cleanly and
    survives create → get."""
    catalog = patterns_router._catalog_map()
    ralph = {k: v for k, v in catalog["ralph_loop"].items() if k not in ("provenance",)}
    ralph["id"] = "my_ralph"
    ralph["source"] = "user"
    r = client.post("/api/patterns", json=ralph)
    assert r.status_code == 201, r.text
    got = client.get("/api/patterns/my_ralph").json()
    assert got["complexity"] == "COMPLEX" and got["kind"] == "ralph"
    assert got["steps"][0]["body"][0]["id"] == "plan"


# ── Curated catalog validity ────────────────────────────────────────────────


def test_all_builtins_scaffold_as_workflows():
    """Every shipped builtin's steps construct through the frozen model."""
    from api.models.workflow_models import WorkflowDefinition

    for rec in patterns_router._load_catalog():
        WorkflowDefinition(id=f"pattern-{rec['id']}", name=rec["name"], steps=rec["steps"])


def test_catalog_matches_dfpatterntemplates():
    """The catalog seeds mirror the frozen 8 dfPatternTemplates exactly (id,
    name, complexity, kind, steps) — no mirrored copy to drift."""
    import re

    catalog = {c["id"]: c for c in patterns_router._load_catalog()}
    main_js = (_REPO / "api" / "static" / "js" / "main.js").read_text(encoding="utf-8")
    m = re.search(
        r"const dfPatternTemplatesJson = String\.raw`\n(.*?)\n`;", main_js, re.DOTALL
    )
    statics = {t["key"]: t for t in json.loads(m.group(1))}
    assert set(catalog) == set(statics), f"drift: {set(catalog) ^ set(statics)}"
    assert len(statics) == 8
    for key, tpl in statics.items():
        c = catalog[key]
        assert c["name"] == tpl["name"]
        assert c["complexity"] == tpl["complexity"]
        assert c["kind"] == tpl["kind"]
        assert c["steps"] == tpl["steps"], f"{key} steps drift vs dfPatternTemplates"


# ── Auth: writes 401 with auth on; reads stay open ─────────────────────────


def test_writes_401_with_auth_on(client, store, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.post("/api/patterns", json=_simple()).status_code == 401
    assert client.patch("/api/patterns/x", json={"steps": _simple()["steps"]}).status_code == 401
    assert client.delete("/api/patterns/x").status_code == 401
    assert client.post("/api/patterns/llm_step/promote", json={}).status_code == 401


def test_reads_carry_no_master_key_gate():
    """Reads stay open: no read route declares require_master_key."""
    from api.middleware import require_master_key

    read_paths = {"GET /api/patterns", "GET /api/patterns/{pattern_id}"}
    for route in patterns_router.router.routes:
        methods = getattr(route, "methods", set()) or set()
        for m in methods:
            sig = f"{m} {route.path}"
            if sig in read_paths:
                deps = (
                    [d.dependency for d in getattr(route, "dependant", None).dependencies]
                    if getattr(route, "dependant", None)
                    else []
                )
                assert require_master_key not in deps, f"{sig} must stay read-open"


# ── Frozen engine untouched ─────────────────────────────────────────────────


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
