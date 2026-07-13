#!/usr/bin/env python3
"""DR-1 — composer draft store + router tests.

Covers the durable draft keystone end-to-end through a real TestClient plus
direct service-layer assertions for the security discipline the HTTP layer
delegates: id-charset/containment allowlist, the ~2 MB cap, atomic writes, and
the publish-freeze delete. The store NEVER validates the opaque blob against the
workflow engine — a half-built canvas is precisely the state that must persist.

Run:  ENABLE_API_AUTH=false pytest tests/test_composer_drafts.py -q
"""

import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from api.services import composer_draft_store as store


@pytest.fixture
def drafts_dir(tmp_path, monkeypatch):
    """Point the store at an isolated tmp dir (no deployment needed)."""
    d = tmp_path / "composer" / "drafts"
    monkeypatch.setattr(store, "_drafts_root", lambda: d)
    return d


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
def client_drafts_dir(tmp_path, monkeypatch):
    """Same isolation, but patched on the module the ROUTER imported."""
    import api.routers.composer as composer_router

    d = tmp_path / "composer" / "drafts"
    monkeypatch.setattr(composer_router.drafts, "_drafts_root", lambda: d)
    return d


def _blob(n_steps=2):
    return {
        "export": {"drawflow": {"Home": {"data": {"1": {"name": "seed"}}}}},
        "nodeData": {"1": {"id": "seed", "is_seed": True}},
        "nextId": 5,
        "seedSchema": [{"key": "query", "description": ""}],
        "meta": {"id": "wf", "name": "WF", "steps": n_steps},
    }


# ── service layer ──────────────────────────────────────────────────────────


def test_save_get_roundtrip_preserves_blob_verbatim(drafts_dir):
    b = _blob()
    store.save_draft("abc123", blob=b, name="My draft", step_count=2)
    rec = store.get_draft("abc123")
    assert rec["draft_id"] == "abc123"
    assert rec["name"] == "My draft"
    assert rec["step_count"] == 2
    # Opaque blob survives byte-for-byte (no engine normalization).
    assert rec["blob"] == b


def test_list_sorted_newest_first(drafts_dir):
    store.save_draft("aaa", blob=_blob(), name="first")
    store.save_draft("bbb", blob=_blob(), name="second")
    # bump aaa so it becomes the most-recently-edited
    store.patch_draft("aaa", name="first-edited")
    ids = [r["draft_id"] for r in store.list_drafts()]
    assert ids[0] == "aaa"
    assert set(ids) == {"aaa", "bbb"}
    # summaries are blob-free (the In-Progress row projection)
    assert all("blob" not in r for r in store.list_drafts())


def test_created_at_preserved_across_updates(drafts_dir):
    store.save_draft("keep", blob=_blob(), name="v1")
    created = store.get_draft("keep")["created_at"]
    store.save_draft("keep", blob=_blob(3), name="v2", step_count=3)
    rec = store.get_draft("keep")
    assert rec["created_at"] == created
    assert rec["updated_at"] >= created
    assert rec["step_count"] == 3


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "x" * 81, "", "-lead"])
def test_traversal_and_charset_rejected(drafts_dir, bad):
    with pytest.raises(store.InvalidDraftId):
        store.save_draft(bad, blob=_blob())
    with pytest.raises(store.InvalidDraftId):
        store._draft_path(bad, must_exist=False)


def test_two_mb_cap_enforced(drafts_dir):
    huge = {"pad": "x" * (store.MAX_DRAFT_BYTES + 10)}
    with pytest.raises(store.DraftTooLarge):
        store.save_draft("big", blob=huge)
    # nothing (not even a stray .tmp) was left behind
    assert not any(drafts_dir.glob("*")) if drafts_dir.exists() else True


def test_atomic_write_leaves_no_tmp(drafts_dir):
    store.save_draft("clean", blob=_blob())
    assert (drafts_dir / "clean.json").is_file()
    assert not list(drafts_dir.glob("*.tmp"))


def test_delete_then_missing(drafts_dir):
    store.save_draft("gone", blob=_blob())
    store.delete_draft("gone")
    with pytest.raises(FileNotFoundError):
        store.get_draft("gone")
    with pytest.raises(FileNotFoundError):
        store.delete_draft("gone")


# ── HTTP layer ─────────────────────────────────────────────────────────────


def test_http_crud_and_publish_freeze(client, client_drafts_dir):
    did = "deadbeefcafe0001"
    r = client.post(
        "/api/composer/drafts",
        json={"draft_id": did, "blob": _blob(), "name": "canvas", "step_count": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["draft_id"] == did
    assert "blob" not in r.json()  # summary is blob-free

    # full record carries the blob (restore-on-open payload)
    full = client.get(f"/api/composer/drafts/{did}").json()
    assert full["blob"]["nextId"] == 5

    # list shows it
    assert did in [d["draft_id"] for d in client.get("/api/composer/drafts").json()]

    # rename via PATCH, blob untouched
    client.patch(f"/api/composer/drafts/{did}", json={"name": "renamed"})
    assert client.get(f"/api/composer/drafts/{did}").json()["name"] == "renamed"

    # publish-freeze: delete removes the In-Progress identity
    assert client.delete(f"/api/composer/drafts/{did}").status_code == 200
    assert client.get(f"/api/composer/drafts/{did}").status_code == 404


def test_http_traversal_rejected(client, client_drafts_dir):
    # path param that escapes the store → 400 (never a filesystem write)
    r = client.get("/api/composer/drafts/..%2f..%2fetc")
    assert r.status_code in (400, 404)
    r2 = client.post(
        "/api/composer/drafts", json={"draft_id": "../escape", "blob": {}}
    )
    assert r2.status_code == 400


def test_http_oversized_413(client, client_drafts_dir):
    r = client.post(
        "/api/composer/drafts",
        json={"draft_id": "toobig", "blob": {"pad": "x" * (store.MAX_DRAFT_BYTES + 50)}},
    )
    assert r.status_code == 413


# ── scope gating (SCOPE_MAP /api/composer → workflows) ──────────────────────


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    """Auth-enabled client with an isolated keystore so we can mint scoped keys
    and assert /api/composer enforces the `workflows` scope."""
    cfg = tmp_path / "keycfg"
    cfg.mkdir()
    monkeypatch.setenv("DATA_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")

    from api.services.api_key_service import APIKeyService

    svc = APIKeyService(config_dir=str(cfg))
    scoped = svc.create_key(name="wf", scopes=["workflows"])["key"]
    unscoped = svc.create_key(name="chatonly", scopes=["chat"])["key"]

    importlib.reload(importlib.import_module("api.middleware"))
    importlib.reload(importlib.import_module("api.main"))
    from api.main import app

    c = TestClient(app)
    try:
        yield c, scoped, unscoped
    finally:
        monkeypatch.setenv("ENABLE_API_AUTH", "false")


def test_drafts_write_requires_workflows_scope(auth_client):
    c, scoped, unscoped = auth_client
    # Unscoped key → 403 insufficient_scope (prefix-gated on /api/composer).
    r_no = c.get("/api/composer/drafts", headers={"Authorization": f"Bearer {unscoped}"})
    assert r_no.status_code == 403
    assert r_no.json()["error"]["code"] == "insufficient_scope"
    # workflows-scoped key → allowed through auth (200 list).
    r_yes = c.get("/api/composer/drafts", headers={"Authorization": f"Bearer {scoped}"})
    assert r_yes.status_code == 200
    # No key at all → 401.
    assert c.get("/api/composer/drafts").status_code == 401
