#!/usr/bin/env python3
"""Prompts library router tests — CRUD over roles/templates, render preview,
and path-traversal safety (the workspace glob incident lesson)."""

import os
import importlib

import pytest
from fastapi.testclient import TestClient


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


def test_lists_seeded_roles_and_templates(client):
    data = client.get("/api/prompts").json()
    kinds = {p["kind"] for p in data}
    assert "role" in kinds and "template" in kinds
    ids = {p["id"] for p in data}
    # ships with these on disk
    assert "python_developer" in ids
    assert "five_part" in ids
    # variables parsed from the jinja template
    fp = next(p for p in data if p["id"] == "five_part" and p["kind"] == "template")
    assert isinstance(fp["variables"], list)


def test_get_role_body(client):
    r = client.get("/api/prompts/role/python_developer")
    assert r.status_code == 200
    assert len(r.json()["body"]) > 0


def test_create_update_delete_roundtrip(client):
    # create
    r = client.post("/api/prompts", json={"id": "test_reviewer", "kind": "role",
                                          "body": "# Test Reviewer\nReview {{ artifact }} carefully."})
    assert r.status_code == 201
    assert r.json()["variables"] == ["artifact"]
    # duplicate create -> 409
    assert client.post("/api/prompts", json={"id": "test_reviewer", "kind": "role", "body": "x"}).status_code == 409
    # update
    r = client.patch("/api/prompts/role/test_reviewer", json={"body": "# Test Reviewer v2\nBody."})
    assert "v2" in r.json()["body"]
    # delete
    assert client.delete("/api/prompts/role/test_reviewer").status_code == 200
    assert client.get("/api/prompts/role/test_reviewer").status_code == 404


def test_render_preview_reuses_composer(client):
    r = client.post("/api/prompts/role/python_developer/render",
                    json={"task": "Write a function", "constraints": ["Be concise"]})
    assert r.status_code == 200
    body = r.json()
    assert body["system"] and "system" in body and "user" in body


def test_path_traversal_and_bad_id_rejected(client):
    for bad in ("../../etc/passwd", "..%2f..%2fetc", "a/b", "", "x" * 90):
        assert client.get(f"/api/prompts/role/{bad}").status_code in (400, 404)
    # create with a traversal id is rejected
    assert client.post("/api/prompts", json={"id": "../evil", "kind": "role", "body": "x"}).status_code == 400
    # unknown kind rejected
    assert client.get("/api/prompts/bogus/x").status_code in (400, 422)
