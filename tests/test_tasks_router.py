#!/usr/bin/env python3
"""LB6 — Task Menu library router (api/routers/tasks.py).

Covers the unit's verify list:
  - TaskSchema CRUD roundtrip over user_storage_root/tasks/<id>.json;
  - 409 on create-exists; 404 on update/delete/get of a missing task;
  - path containment rejects traversal / bad-charset ids (the real
    glob-traversal incident — every new file route gets this);
  - writes 401 with auth on (create/update/delete/refresh/install); reads
    stay open;
  - POST /{id}/render resolves refs through PromptComposer and 400s on a
    missing prompt id; hook-ref names not in the 10-builtin factory are a
    NON-FATAL warnings field;
  - min-1-output AgentStep contract enforced (400 on empty outputs);
  - GET /api/tasks/discover performs ZERO network calls, merges the curated
    catalog (13 builtins) and carries a fetched_at staleness stamp;
  - POST /api/tasks/discover/refresh is master-key gated (401 without key);
  - install copies a discoverable record into the user layer and annotates
    provenance;
  - the frozen engine files are untouched (router imports read-only).

Run:  pytest tests/test_tasks_router.py -q
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.routers import tasks as tasks_router

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
    """Isolated empty user task store + isolated digest dir."""
    root = tmp_path / "tasks"
    root.mkdir(parents=True)
    monkeypatch.setattr(tasks_router, "_tasks_root", lambda: root)
    # isolate the discovery digest dir so refresh/read don't touch real data/
    from api.services import discovery_fetch

    monkeypatch.setattr(discovery_fetch, "_DIGEST_DIR", tmp_path / "discovery")
    return root


def _schema(task_id="my_task", **over):
    base = {
        "id": task_id,
        "name": "My Task",
        "persona": "analyzer",
        "role": "reasoning",
        "instructions": {"system_prompt": "Analyze the input.", "blocks": []},
        "outputs": ["analysis"],
        "format": "json",
        "intended_output": "Findings",
        "pattern_affinity": ["llm"],
        "tags": ["analysis"],
    }
    base.update(over)
    return base


# ── CRUD roundtrip ──────────────────────────────────────────────────────────


def test_task_crud_roundtrip(client, store):
    r = client.post("/api/tasks", json=_schema())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "user"
    assert body["outputs"] == ["analysis"]
    assert (store / "my_task.json").is_file()

    rows = client.get("/api/tasks").json()
    assert [x["id"] for x in rows] == ["my_task"]

    got = client.get("/api/tasks/my_task").json()
    assert got["name"] == "My Task" and got["role"] == "reasoning"

    r = client.put("/api/tasks/my_task", json=_schema(name="Renamed"))
    assert r.status_code == 200
    assert client.get("/api/tasks/my_task").json()["name"] == "Renamed"

    assert client.delete("/api/tasks/my_task").status_code == 200
    assert client.get("/api/tasks/my_task").status_code == 404


def test_create_409_on_exists(client, store):
    assert client.post("/api/tasks", json=_schema()).status_code == 201
    r = client.post("/api/tasks", json=_schema())
    assert r.status_code == 409


def test_update_delete_missing_404(client, store):
    assert client.put("/api/tasks/ghost", json=_schema("ghost")).status_code == 404
    assert client.delete("/api/tasks/ghost").status_code == 404


def test_empty_outputs_rejected_400(client, store):
    r = client.post("/api/tasks", json=_schema(outputs=[]))
    assert r.status_code == 400
    assert "output" in r.json()["detail"].lower()


def test_reserved_id_rejected(client, store):
    r = client.post("/api/tasks", json=_schema("discover"))
    assert r.status_code == 400


def test_list_filters_by_tag_and_pattern(client, store):
    client.post("/api/tasks", json=_schema("a", tags=["x"], pattern_affinity=["llm"]))
    client.post("/api/tasks", json=_schema("b", tags=["y"], pattern_affinity=["loop"]))
    assert {x["id"] for x in client.get("/api/tasks?tag=x").json()} == {"a"}
    assert {x["id"] for x in client.get("/api/tasks?pattern=loop").json()} == {"b"}


def test_unknown_pattern_affinity_dropped(client, store):
    r = client.post("/api/tasks", json=_schema(pattern_affinity=["llm", "bogus"]))
    assert r.status_code == 201
    assert r.json()["pattern_affinity"] == ["llm"]


# ── Path containment (the glob-traversal incident lesson) ──────────────────


@pytest.mark.parametrize(
    "bad", ["../escape", "..%2fescape", "a/b", "with space", "-lead", "a" * 90]
)
def test_traversal_and_bad_ids_rejected(client, store, bad):
    from urllib.parse import quote

    r = client.get(f"/api/tasks/{quote(bad, safe='')}")
    assert r.status_code in (400, 404)
    # no file escaped the store
    assert not any(p.name.endswith(".json") for p in store.parent.rglob("*.json")
                   if store not in p.parents)


def test_create_traversal_id_rejected(client, store):
    r = client.post("/api/tasks", json=_schema("../evil"))
    assert r.status_code == 400
    assert not list(store.parent.glob("evil.json"))


# ── Render (refs resolved; missing prompt 400; hook warning non-fatal) ─────


def test_render_inline_ok(client, store):
    client.post("/api/tasks", json=_schema())
    r = client.post("/api/tasks/my_task/render", json={"task": "Do the thing."})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "Analyze the input." in d["system"]
    assert "Do the thing." in d["system"]
    assert d["warnings"] == []


def test_render_missing_role_ref_400(client, store):
    client.post(
        "/api/tasks",
        json=_schema(refs={"role_ref": "no_such_role", "hooks": []}),
    )
    r = client.post("/api/tasks/my_task/render", json={})
    assert r.status_code == 400
    assert "role ref" in r.json()["detail"].lower()


def test_render_unknown_hook_is_non_fatal_warning(client, store):
    client.post(
        "/api/tasks",
        json=_schema(refs={"hooks": [{"target": "not_a_builtin_hook"}]}),
    )
    r = client.post("/api/tasks/my_task/render", json={})
    assert r.status_code == 200, r.text
    assert any("not_a_builtin_hook" in w for w in r.json()["warnings"])


def test_render_known_hook_no_warning(client, store):
    client.post(
        "/api/tasks",
        json=_schema(refs={"hooks": [{"target": "json_schema"}]}),
    )
    r = client.post("/api/tasks/my_task/render", json={})
    assert r.status_code == 200
    assert r.json()["warnings"] == []


# ── Discovery: read never fetches; refresh gated; install annotates ────────


def test_discover_never_fetches_and_carries_fetched_at(client, store, monkeypatch):
    import requests

    def _boom(*a, **k):  # any network call from the read path is a bug
        raise AssertionError("GET /api/tasks/discover must not touch the network")

    monkeypatch.setattr(requests, "get", _boom)
    r = client.get("/api/tasks/discover")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "fetched_at" in d  # staleness stamp present (None when never refreshed)
    # the 13 curated builtins merge in from the COPY'd catalog
    assert len(d["builtins"]) == 13
    assert {b["id"] for b in d["builtins"]} >= {"analyzer", "custom", "decision"}


def test_discover_builtin_ids_match_dfsteptemplates():
    """The catalog seeds mirror the frozen 13 dfStepTemplates keys exactly."""
    catalog = tasks_router._load_catalog()
    ids = {c["id"] for c in catalog}
    main_js = (_REPO / "api" / "static" / "js" / "main.js").read_text(encoding="utf-8")
    import re

    block = main_js[main_js.index("const dfStepTemplates = ["):]
    block = block[: block.index("];") + 1]
    keys = set(re.findall(r"key:\s*'([a-z_]+)'", block))
    assert ids == keys, f"catalog {ids ^ keys} drift vs dfStepTemplates"
    assert len(keys) == 13


def test_install_annotates_and_409(client, store):
    r = client.post("/api/tasks/discover/analyzer/install", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "analyzer" and body["source"] == "user"
    assert (store / "analyzer.json").is_file()
    saved = json.loads((store / "analyzer.json").read_text())
    assert saved["provenance"]["installed_from"] == "analyzer"
    # second install of the same id → 409
    assert client.post("/api/tasks/discover/analyzer/install", json={}).status_code == 409
    # unknown record → 404
    assert client.post("/api/tasks/discover/nope/install", json={}).status_code == 404


def test_install_with_target_id(client, store):
    r = client.post(
        "/api/tasks/discover/analyzer/install", json={"target_id": "my_analyzer"}
    )
    assert r.status_code == 201
    assert (store / "my_analyzer.json").is_file()


def test_refresh_no_url_failsoft(client, store, monkeypatch):
    monkeypatch.setattr(tasks_router, "_tasks_catalog_url", lambda: "")
    r = client.post("/api/tasks/discover/refresh")
    assert r.status_code == 200
    d = r.json()
    assert d["sources"][0]["ok"] is False
    assert len(d["builtins"]) == 13


# ── Auth: writes 401 with auth on; reads stay open ─────────────────────────


def test_writes_401_with_auth_on(client, store, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.post("/api/tasks", json=_schema()).status_code == 401
    assert client.put("/api/tasks/x", json=_schema("x")).status_code == 401
    assert client.delete("/api/tasks/x").status_code == 401
    assert client.post("/api/tasks/discover/refresh").status_code == 401
    assert client.post("/api/tasks/discover/analyzer/install", json={}).status_code == 401


def test_reads_carry_no_master_key_gate():
    """Reads stay open: no read route declares require_master_key (the global
    API-key layer is separate; with the admin gate lifted, reads answer)."""
    from api.middleware import require_master_key

    read_paths = {"GET /api/tasks", "GET /api/tasks/{task_id}", "GET /api/tasks/discover"}
    for route in tasks_router.router.routes:
        methods = getattr(route, "methods", set()) or set()
        for m in methods:
            sig = f"{m} {route.path}"
            if sig in read_paths:
                deps = [
                    d.dependency for d in getattr(route, "dependant", None).dependencies
                ] if getattr(route, "dependant", None) else []
                assert require_master_key not in deps, f"{sig} must stay read-open"


# ── Frozen engine untouched ─────────────────────────────────────────────────


def test_frozen_engine_untouched():
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=_REPO, capture_output=True, text=True,
    ).stdout
    for frozen in (
        "api/services/workflow_engine.py",
        "api/services/step_executor.py",
        "api/models/workflow_models.py",
    ):
        assert frozen not in out, f"{frozen} is frozen — must not be edited"
