#!/usr/bin/env python3
"""RX-2 backend — actionable results, Obsidian-like RAG store, exploratory walk.

Covers the new operator-triggered research endpoints:
  - POST /api/research/save-source   → writes sources/<slug>.md into the shared
    `research` workspace + RAG-ingests it (rag_ingested truthful); traversal-
    rejecting slug validation; atomic write.
  - POST /api/research/compare-node  → structured sections; web egress OFF by
    default (privacy) — no background search on a plain compare.
  - POST /api/research/graph-walk    → resumable worklist over the workspace
    durable index (/index/{name}/next semantics); survives across calls.
  - /api/workspaces scope gating (MS binding): an unscoped key is 403'd, a
    `workspaces`-scoped key succeeds.

Run:  ENABLE_API_AUTH=false pytest tests/test_research_rx2.py -q
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from api.services import rag_ingest, research_session
from api.services.search_service import SearchResponse, SearchResult


# ── Isolation ───────────────────────────────────────────────────────────────


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Point the session store + workspace root at a tmp dir and reset the
    workspace registry singleton so nothing leaks between tests / real data."""
    monkeypatch.setattr(research_session, "RESEARCH_DATA_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("ENCLAVE_DATA_DIR", str(tmp_path))
    import api.services.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "_registry", None, raising=False)
    yield tmp_path
    monkeypatch.setattr(ws_mod, "_registry", None, raising=False)


@pytest.fixture()
def client(isolated, monkeypatch):
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


class _FakeDocService:
    def __init__(self):
        self.uploaded = []

    def upload(self, filename, content):
        self.uploaded.append((filename, content))
        return {"id": "doc_x", "filename": filename}


def _wire_rag(monkeypatch):
    """Wire a fake DocumentService so rag_ingested reports True."""
    import api.routers.documents as docs

    monkeypatch.setattr(docs, "document_service", _FakeDocService(), raising=False)


def _stub_model(monkeypatch, content):
    """Stub the research router's ollama.chat so no real model is needed."""
    import api.routers.research as research

    monkeypatch.setattr(research._ollama, "chat", lambda **kw: {"content": content})


def _forbid_search(monkeypatch):
    """Fail loudly if a web search egresses when it must not."""
    import api.routers.research as research

    async def _boom(*a, **k):  # pragma: no cover - only hit on a privacy regression
        raise AssertionError("web search egressed when web_search was OFF")

    monkeypatch.setattr(research, "search_web", _boom)


# ── save-source ─────────────────────────────────────────────────────────────


def test_save_source_writes_note_and_ingests(client, monkeypatch):
    _wire_rag(monkeypatch)
    resp = client.post(
        "/api/research/save-source",
        json={"title": "Vector DB tradeoffs", "content": "Chroma vs FAISS.", "url": "https://x/y"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == "sources/vector-db-tradeoffs.md"
    assert body["rag_ingested"] is True
    assert body["workspace"] == "research"
    # The note is really on disk in the research workspace.
    ws = research_session.ensure_research_workspace()
    content = ws.read("sources/vector-db-tradeoffs.md")
    assert "# Vector DB tradeoffs" in content
    assert "https://x/y" in content
    assert "Chroma vs FAISS." in content


def test_save_source_rag_false_when_backend_down(client, monkeypatch):
    import api.routers.documents as docs

    monkeypatch.setattr(docs, "document_service", None, raising=False)
    resp = client.post("/api/research/save-source", json={"title": "N", "content": "b"})
    assert resp.status_code == 200
    assert resp.json()["rag_ingested"] is False
    # The markdown is still written even when RAG is down.
    ws = research_session.ensure_research_workspace()
    assert ws.exists("sources/n.md")


def test_save_source_rejects_traversal_slug(client):
    for bad in ["../evil", "..", "a/b", "x\\y", "/etc/passwd"]:
        resp = client.post(
            "/api/research/save-source",
            json={"title": "t", "content": "b", "slug": bad},
        )
        assert resp.status_code == 400, f"slug {bad!r} was not rejected: {resp.text}"


def test_save_source_rejects_unknown_area(client):
    resp = client.post(
        "/api/research/save-source",
        json={"title": "t", "content": "b", "area": "../../etc"},
    )
    assert resp.status_code == 400


# ── compare-node ────────────────────────────────────────────────────────────

_STRUCTURED = (
    "## Agreements\nBoth agree on locality.\n\n"
    "## Contradictions\nOne claims X, the other not-X.\n\n"
    "## New angles\nConsider quantization.\n\n"
    "## Open questions\nWhat about latency?\n"
)


def test_compare_node_returns_structured_sections(client, monkeypatch):
    _stub_model(monkeypatch, _STRUCTURED)
    _forbid_search(monkeypatch)  # web_search default OFF → must NOT egress
    resp = client.post("/api/research/compare-node", json={"focus": "RoPE scaling"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["web_search"] is False
    assert set(body["sections"].keys()) >= {
        "Agreements",
        "Contradictions",
        "New angles",
        "Open questions",
    }
    assert "locality" in body["sections"]["Agreements"]


def test_compare_node_save_persists_note(client, monkeypatch):
    _wire_rag(monkeypatch)
    _stub_model(monkeypatch, _STRUCTURED)
    _forbid_search(monkeypatch)
    resp = client.post(
        "/api/research/compare-node", json={"focus": "YaRN", "save": True}
    )
    assert resp.status_code == 200
    saved = resp.json()["saved_path"]
    assert saved and saved.startswith("notes/")
    ws = research_session.ensure_research_workspace()
    assert ws.exists(saved)


# ── graph-walk (resumable) ──────────────────────────────────────────────────


def test_graph_walk_is_resumable(client, monkeypatch):
    _stub_model(monkeypatch, _STRUCTURED)
    _forbid_search(monkeypatch)
    # Seed a two-node walk on the first call; it claims + processes node 1.
    r1 = client.post(
        "/api/research/graph-walk", json={"nodes": ["Alpha node", "Beta node"]}
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["item"]["label"] == "Alpha node"
    assert b1["counts"]["done"] == 1
    assert b1["complete"] is False
    # Second call (no new nodes) resumes the SAME worklist and finishes node 2.
    r2 = client.post("/api/research/graph-walk", json={})
    b2 = r2.json()
    assert b2["item"]["label"] == "Beta node"
    assert b2["counts"]["done"] == 2
    assert b2["complete"] is True
    # Third call: worklist drained → no item, complete.
    r3 = client.post("/api/research/graph-walk", json={})
    assert r3.json()["item"] is None
    assert r3.json()["complete"] is True
    # The durable worklist exists under the workspace index — the same seam
    # /index/{name}/next drives, so a walk survives a restart.
    idx = client.get("/api/workspaces/research/index/graph-walk").json()
    assert idx["counts"]["done"] == 2
    assert idx["complete"] is True


def test_graph_walk_writes_report(client, monkeypatch):
    _stub_model(monkeypatch, _STRUCTURED)
    _forbid_search(monkeypatch)
    client.post("/api/research/graph-walk", json={"nodes": ["Gamma"]})
    ws = research_session.ensure_research_workspace()
    assert ws.exists("notes/graph-walk-report.md")
    report = ws.read("notes/graph-walk-report.md")
    assert "Gamma" in report


# ── /api/workspaces scope gating (MS binding) ───────────────────────────────


@pytest.fixture()
def auth_client(isolated, tmp_path, monkeypatch):
    """Auth-enabled client with an isolated keystore, so we can mint scoped
    keys and assert /api/workspaces enforces the `workspaces` scope."""
    cfg = tmp_path / "keycfg"
    cfg.mkdir()
    monkeypatch.setenv("DATA_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")

    from api.services.api_key_service import APIKeyService

    svc = APIKeyService(config_dir=str(cfg))
    scoped = svc.create_key(name="ws", scopes=["workspaces"])["key"]
    unscoped = svc.create_key(name="chatonly", scopes=["chat"])["key"]

    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    client = TestClient(app)
    try:
        yield client, scoped, unscoped
    finally:
        monkeypatch.setenv("ENABLE_API_AUTH", "false")


def test_workspaces_write_requires_scope(auth_client):
    client, scoped, unscoped = auth_client
    # Unscoped key → 403 insufficient_scope on the workspace listing (prefix-gated).
    r_no = client.get(
        "/api/workspaces", headers={"Authorization": f"Bearer {unscoped}"}
    )
    assert r_no.status_code == 403
    assert r_no.json()["error"]["code"] == "insufficient_scope"
    # Scoped key → allowed through auth (200 list).
    r_yes = client.get(
        "/api/workspaces", headers={"Authorization": f"Bearer {scoped}"}
    )
    assert r_yes.status_code == 200
    # No key at all → 401.
    assert client.get("/api/workspaces").status_code == 401
