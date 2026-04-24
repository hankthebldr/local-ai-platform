"""Tests for the read-only /api/roles router."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
ROLES_DIR = Path(__file__).resolve().parents[1] / "prompts" / "roles"


def test_list_roles_returns_all_md_files():
    resp = client.get("/api/roles")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = {r["id"] for r in data}
    # Three roles ship with the repo as of 2026-04-23.
    assert {"python_developer", "qa_engineer", "senior_data_architect"}.issubset(ids)
    for r in data:
        assert "id" in r and "name" in r and "summary" in r
        assert r["summary"]  # non-empty


def test_get_role_returns_full_content():
    resp = client.get("/api/roles/senior_data_architect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "senior_data_architect"
    assert "senior data architect" in data["content"].lower()


def test_get_missing_role_returns_404():
    resp = client.get("/api/roles/does_not_exist")
    assert resp.status_code == 404


def test_path_traversal_rejected():
    # Must not escape prompts/roles/
    resp = client.get("/api/roles/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)
    # Slashes in path parameter get routed differently, but the validator
    # should still reject once it sees ".." or "/"
    resp = client.get("/api/roles/..%2Fpasswd")
    assert resp.status_code in (400, 404)
