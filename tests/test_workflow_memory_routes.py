"""API tests for the workflow memory inspector endpoints.

Exercise GET /api/workflows/memory/{playbooks,semantic,episodic} + the per-key
read endpoints. The Memory tab in the UI consumes these.
"""

from __future__ import annotations


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.workflows import router as workflows_router
from api.services.memory_store import MemoryStore


@pytest.fixture
def store_with_data(tmp_path, monkeypatch):
    """Point MEMORY_DATA_DIR at a tmp dir and seed it with one of each kind."""
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    store = MemoryStore(base_dir=str(tmp_path))
    store.write_playbook("incident", "Rule: check logs first\n", strategy="replace")
    store.write_playbook("runbook", "## XSIAM ops\n", strategy="replace")
    store.write_semantic(
        "xdm_ts", "data_received_time is canonical", strategy="replace"
    )
    store.append_episodic("incident", "event A", run_id="r1")
    store.append_episodic("incident", "event B", run_id="r2")
    return store


@pytest.fixture
def client(store_with_data):
    app = FastAPI()
    app.include_router(workflows_router)
    return TestClient(app)


class TestListEndpoints:
    def test_list_playbooks(self, client):
        resp = client.get("/api/workflows/memory/playbooks")
        assert resp.status_code == 200
        names = sorted(p["name"] for p in resp.json()["playbooks"])
        assert names == ["incident", "runbook"]

    def test_list_semantic(self, client):
        resp = client.get("/api/workflows/memory/semantic")
        assert resp.status_code == 200
        assert [s["name"] for s in resp.json()["semantic"]] == ["xdm_ts"]

    def test_list_episodic_with_record_counts(self, client):
        resp = client.get("/api/workflows/memory/episodic")
        assert resp.status_code == 200
        items = resp.json()["episodic"]
        assert len(items) == 1
        assert items[0]["name"] == "incident"
        assert items[0]["record_count"] == 2

    def test_empty_store_returns_empty_lists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path / "empty"))
        app = FastAPI()
        app.include_router(workflows_router)
        c = TestClient(app)
        assert c.get("/api/workflows/memory/playbooks").json() == {"playbooks": []}
        assert c.get("/api/workflows/memory/semantic").json() == {"semantic": []}
        assert c.get("/api/workflows/memory/episodic").json() == {"episodic": []}


class TestReadEndpoints:
    def test_read_playbook_returns_body(self, client):
        resp = client.get("/api/workflows/memory/playbooks/incident")
        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        assert "check logs first" in data["body"]

    def test_read_missing_playbook_returns_empty(self, client):
        resp = client.get("/api/workflows/memory/playbooks/nonexistent")
        assert resp.status_code == 200
        assert resp.json() == {"name": "nonexistent", "body": "", "exists": False}

    def test_read_semantic(self, client):
        resp = client.get("/api/workflows/memory/semantic/xdm_ts")
        assert resp.status_code == 200
        assert "data_received_time" in resp.json()["body"]

    def test_read_episodic_with_records(self, client):
        resp = client.get("/api/workflows/memory/episodic/incident")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["records"][0]["content"] == "event A"
        assert data["records"][1]["content"] == "event B"

    def test_read_episodic_respects_limit(self, client):
        resp = client.get("/api/workflows/memory/episodic/incident?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        # most-recent-last: with limit=1, we get the latest (event B)
        assert data["records"][0]["content"] == "event B"


class TestRoutePriorityVsWildcard:
    """The router has a catch-all GET /{workflow_id}. The memory routes must
    not be shadowed by it — segment counts protect us, but explicit testing
    pins the invariant."""

    def test_memory_route_does_not_resolve_to_workflow_id(self, client):
        # Hits /api/workflows/memory — would be /{workflow_id} except memory/...
        # is two segments. List endpoint must answer, not the workflow loader.
        resp = client.get("/api/workflows/memory/playbooks")
        assert resp.status_code == 200
        assert "playbooks" in resp.json()
