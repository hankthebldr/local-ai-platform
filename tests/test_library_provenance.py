#!/usr/bin/env python3
"""LB0-U3 — layered prompt storage, provenance annotations, physical promote.

(Named test_library_provenance.py: the spec's tests/test_provenance.py is
already taken by the pre-existing citation-provenance suite — only-add.)

Covers the unit's verify list:
  - layered listing merges oob + user with user shadowing oob by id;
  - create lands in the user layer (never the shipped tree);
  - PATCH of an oob id copies-on-write into the user layer (auto-promote);
  - DELETE of a pure-oob id → 403 with explanation; DELETE of a user copy
    reverts to oob;
  - POST /{kind}/{pid}/promote → 201 then 409; 404 without an oob source;
    master-key gated; traversal ids rejected (new file-writing route);
  - api/config/oob_manifest.json agent ids all resolve to agents/<id>.yaml;
  - plugin records carry `layer` (mirror of origin);
  - MCP server records carry `provenance` (catalog vs manual);
  - render resolves templates across layers (user template renders).

Run:  pytest tests/test_library_provenance.py -q
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.routers import prompts as prompts_router

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
def layers(tmp_path, monkeypatch):
    """Isolated two-layer prompt store: seeded oob tree + empty user tree."""
    oob = tmp_path / "oob-prompts"
    user = tmp_path / "user-prompts"
    (oob / "roles").mkdir(parents=True)
    (oob / "templates").mkdir(parents=True)
    (oob / "roles" / "shipped_role.md").write_text(
        "# Shipped Role\nYou review {{ artifact }} carefully.", encoding="utf-8"
    )
    (oob / "roles" / "shipped_two.md").write_text("# Shipped Two\nBody.", encoding="utf-8")
    # Real shipped template so render keeps working against the fixture oob layer.
    shutil.copy(
        _REPO / "prompts" / "templates" / "five_part.jinja",
        oob / "templates" / "five_part.jinja",
    )
    monkeypatch.setattr(prompts_router, "_OOB_ROOT", oob)
    monkeypatch.setattr(prompts_router, "_user_root", lambda: user)
    return {"oob": oob, "user": user}


def _seed_user(layers, kind_dir, name, body):
    p = layers["user"] / kind_dir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ── Layered listing ────────────────────────────────────────────────────────


def test_layered_listing_merges_and_user_shadows_oob(client, layers):
    _seed_user(layers, "roles", "user_role.md", "# User Role\nOperator-made.")
    _seed_user(layers, "roles", "shipped_role.md", "# Shadowed\nUser copy wins.")

    data = client.get("/api/prompts").json()
    by_id = {}
    for rec in data:
        key = (rec["kind"], rec["id"])
        assert key not in by_id, f"duplicate record for {key} — merge must dedupe"
        by_id[key] = rec

    assert by_id[("role", "user_role")]["provenance"] == "user"
    assert by_id[("role", "shipped_two")]["provenance"] == "oob"
    assert by_id[("template", "five_part")]["provenance"] == "oob"
    # user shadows oob by id — one record, provenance flipped
    assert by_id[("role", "shipped_role")]["provenance"] == "user"

    # GET serves the winning (user) copy
    body = client.get("/api/prompts/role/shipped_role").json()
    assert "User copy wins." in body["body"]
    assert body["provenance"] == "user"


# ── Create → user layer ────────────────────────────────────────────────────


def test_create_lands_in_user_layer(client, layers):
    r = client.post(
        "/api/prompts",
        json={"id": "fresh_role", "kind": "role", "body": "# Fresh\nHi {{ name }}."},
    )
    assert r.status_code == 201
    assert r.json()["provenance"] == "user"
    assert (layers["user"] / "roles" / "fresh_role.md").is_file()
    assert not (layers["oob"] / "roles" / "fresh_role.md").exists()

    # duplicate user create → 409; create over a shipped id → 409 too
    assert client.post(
        "/api/prompts", json={"id": "fresh_role", "kind": "role", "body": "x"}
    ).status_code == 409
    r = client.post(
        "/api/prompts", json={"id": "shipped_role", "kind": "role", "body": "x"}
    )
    assert r.status_code == 409
    assert "oob" in r.json()["detail"]


# ── PATCH oob → copy-on-write ──────────────────────────────────────────────


def test_oob_patch_copies_on_write(client, layers):
    oob_file = layers["oob"] / "roles" / "shipped_role.md"
    original = oob_file.read_text(encoding="utf-8")

    r = client.patch(
        "/api/prompts/role/shipped_role", json={"body": "# Edited\nv2 body."}
    )
    assert r.status_code == 200
    assert r.json()["provenance"] == "user"  # auto-promoted, honestly
    assert "v2 body." in r.json()["body"]
    # shipped file untouched; user copy created
    assert oob_file.read_text(encoding="utf-8") == original
    assert (layers["user"] / "roles" / "shipped_role.md").is_file()

    # PATCH of an id in neither layer → 404
    assert client.patch(
        "/api/prompts/role/no_such_role", json={"body": "x"}
    ).status_code == 404


# ── DELETE semantics ───────────────────────────────────────────────────────


def test_oob_delete_403_and_user_delete_reverts(client, layers):
    # pure-oob delete is refused with an explanation
    r = client.delete("/api/prompts/role/shipped_role")
    assert r.status_code == 403
    assert "oob" in r.json()["detail"]
    assert (layers["oob"] / "roles" / "shipped_role.md").is_file()

    # shadow it, then delete → user copy removed, oob copy back in charge
    client.patch("/api/prompts/role/shipped_role", json={"body": "# Shadow"})
    r = client.delete("/api/prompts/role/shipped_role")
    assert r.status_code == 200
    assert r.json()["reverted_to_oob"] is True
    assert not (layers["user"] / "roles" / "shipped_role.md").exists()
    body = client.get("/api/prompts/role/shipped_role").json()
    assert body["provenance"] == "oob"
    assert "Shipped Role" in body["body"]

    # user-only delete removes the prompt outright
    client.post("/api/prompts", json={"id": "ephemeral", "kind": "role", "body": "x"})
    r = client.delete("/api/prompts/role/ephemeral")
    assert r.status_code == 200
    assert r.json()["reverted_to_oob"] is False
    assert client.get("/api/prompts/role/ephemeral").status_code == 404


# ── Promote ────────────────────────────────────────────────────────────────


def test_promote_201_then_409(client, layers):
    oob_file = layers["oob"] / "roles" / "shipped_role.md"
    r = client.post("/api/prompts/role/shipped_role/promote")
    assert r.status_code == 201
    assert r.json()["provenance"] == "user"
    user_file = layers["user"] / "roles" / "shipped_role.md"
    assert user_file.read_text(encoding="utf-8") == oob_file.read_text(encoding="utf-8")

    # second promote → 409 (user copy exists)
    assert client.post("/api/prompts/role/shipped_role/promote").status_code == 409
    # nothing shipped under that id → 404 (also for user-only ids)
    assert client.post("/api/prompts/role/no_such_role/promote").status_code == 404
    client.post("/api/prompts", json={"id": "user_only", "kind": "role", "body": "x"})
    assert client.post("/api/prompts/role/user_only/promote").status_code == 404


def test_promote_requires_master_key_when_auth_on(client, layers, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.post("/api/prompts/role/shipped_role/promote").status_code == 401
    # reads stay open regardless
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    assert client.get("/api/prompts/role/shipped_role").status_code == 200


def test_promote_rejects_traversal_and_bad_ids(client, layers):
    # New file-writing route — same charset + containment discipline as the
    # rest of the router (the workspace glob-traversal incident lesson).
    for bad in ("..", ".hidden", "a b", "x" * 90, "%2e%2e"):
        r = client.post(f"/api/prompts/role/{bad}/promote")
        assert r.status_code in (400, 404), f"{bad!r} must not reach the filesystem"
    assert client.post("/api/prompts/bogus/x/promote").status_code in (400, 422)
    # nothing leaked into the user layer
    roles_dir = layers["user"] / "roles"
    assert not roles_dir.exists() or not any(roles_dir.iterdir())


# ── Render across layers ───────────────────────────────────────────────────


def test_render_resolves_layered_templates(client, layers):
    # user-layer template renders through the composer
    r = client.post(
        "/api/prompts",
        json={"id": "user_tpl", "kind": "template",
              "body": "{{ role }}\nUSERLAYER-TEMPLATE\n## Task\n{{ task }}"},
    )
    assert r.status_code == 201
    r = client.post("/api/prompts/template/user_tpl/render", json={"task": "Do it"})
    assert r.status_code == 200
    assert "USERLAYER-TEMPLATE" in r.json()["system"]

    # a user five_part.jinja shadows the shipped one for role renders
    _seed_user(layers, "templates", "five_part.jinja",
               "{{ role }}\nSHADOWED-FIVE-PART\n{{ task }}")
    r = client.post("/api/prompts/role/shipped_role/render", json={"task": "Go"})
    assert r.status_code == 200
    assert "SHADOWED-FIVE-PART" in r.json()["system"]


# ── OOB manifest (agents — the kind without a physical layer) ─────────────


def test_oob_manifest_agent_ids_resolve():
    manifest = json.loads((_REPO / "api" / "config" / "oob_manifest.json").read_text())
    ids = manifest.get("agents") or []
    assert ids, "manifest must list shipped agent seed ids"
    assert len(ids) == len(set(ids)), "duplicate ids in oob_manifest.json"
    for aid in ids:
        f = _REPO / "agents" / f"{aid}.yaml"
        assert f.is_file(), f"manifest id '{aid}' has no agents/{aid}.yaml"
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert doc.get("id") == aid, f"agents/{aid}.yaml id field mismatch"


# ── Plugin layer + MCP provenance annotations ──────────────────────────────


def test_plugin_records_carry_layer(client):
    from api.routers import plugins as plugins_router

    rec = plugins_router._with_layer({"id": "x", "origin": "system"})
    assert rec["layer"] == "system" and rec["origin"] == "system"

    r = client.get("/api/plugins")
    assert r.status_code == 200
    records = r.json()
    assert records, "repo plugins/ ships plugins — list must not be empty"
    for p in records:
        assert p.get("layer") in ("system", "user")
        assert p["layer"] == p.get("origin")


def test_mcp_servers_carry_provenance(client):
    r = client.get("/api/mcp/servers")
    assert r.status_code == 200
    for s in r.json():
        assert s.get("provenance") in ("oob", "user")
