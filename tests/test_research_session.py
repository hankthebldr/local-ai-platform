#!/usr/bin/env python3
"""Research session tests (RX-1) — mint / persist / followup / MOC.

Covers the stateful research surface:
  - deep-dive mints a ResearchSession and returns a session_id (graph shim)
  - the session persists to disk with the {topic,model,source_ids,turns,moc_path}
    shape and round-trips
  - a session MOC is rendered into the shared `research` workspace
  - POST /api/research/followup appends a grounded turn (web_search OFF by
    default → no background egress)

Run:  ENABLE_API_AUTH=false pytest tests/test_research_session.py -q
"""

import importlib
import os

import pytest

from api.services import research_session
from api.services.search_service import SearchResponse, SearchResult


# ── Isolation ───────────────────────────────────────────────────────────────


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Point the session store + workspace root at a tmp dir and reset the
    workspace registry singleton so nothing leaks between tests / real data."""
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(research_session, "RESEARCH_DATA_DIR", str(sessions_dir))
    monkeypatch.setenv("ENCLAVE_DATA_DIR", str(tmp_path))
    import api.services.workspace as ws_mod

    monkeypatch.setattr(ws_mod, "_registry", None, raising=False)
    yield tmp_path
    monkeypatch.setattr(ws_mod, "_registry", None, raising=False)


# ── Service level ───────────────────────────────────────────────────────────


def test_record_deep_dive_mints_and_persists(isolated):
    session = research_session.record_deep_dive(
        topic="How do local LLMs handle long context?",
        model="dolphin3:latest",
        source_ids=["https://a.example/x", "https://b.example/y"],
        synthesis="## Summary\nLocal models use RoPE scaling.",
        sub_questions=["What is RoPE?", "What is YaRN?"],
        mirror_conversation=False,
    )
    assert session.id and len(session.id) >= 8
    assert session.topic.startswith("How do local LLMs")
    assert session.source_ids == ["https://a.example/x", "https://b.example/y"]
    assert len(session.turns) == 1
    assert session.turns[0]["kind"] == "synthesis"

    # Round-trips from disk with the documented shape.
    reloaded = research_session.get_session(session.id)
    assert reloaded is not None
    dumped = reloaded.model_dump()
    for field in ("topic", "model", "source_ids", "turns", "moc_path"):
        assert field in dumped


def test_deep_dive_writes_moc_into_research_workspace(isolated):
    session = research_session.record_deep_dive(
        topic="Vector databases",
        model="dolphin3:latest",
        source_ids=["https://chroma.example"],
        synthesis="Chroma is a local vector store.",
        mirror_conversation=False,
    )
    assert session.moc_path == f"sessions/{session.id}.md"

    from api.services.workspace import get_workspace_registry

    ws = get_workspace_registry().get(research_session.RESEARCH_WORKSPACE)
    body = ws.read(session.moc_path)
    assert "# Research: Vector databases" in body
    assert "Chroma is a local vector store." in body
    assert "https://chroma.example" in body


def test_append_followup_grows_session_and_moc(isolated):
    session = research_session.record_deep_dive(
        topic="Prompt caching",
        model="dolphin3:latest",
        synthesis="Prompt caching reuses KV state.",
        mirror_conversation=False,
    )
    updated = research_session.append_followup(
        session.id,
        question="Does Ollama support it?",
        answer="Yes, via keep_alive and slot reuse.",
        sources=[{"kind": "web", "title": "Ollama docs", "url": "https://ollama.example"}],
        web_search=True,
        grounded=True,
        mirror_conversation=False,
    )
    assert updated is not None
    assert len(updated.turns) == 2
    assert updated.turns[1]["kind"] == "followup"
    assert updated.turns[1]["grounded"] is True
    assert "https://ollama.example" in updated.source_ids

    from api.services.workspace import get_workspace_registry

    ws = get_workspace_registry().get(research_session.RESEARCH_WORKSPACE)
    body = ws.read(updated.moc_path)
    assert "Does Ollama support it?" in body
    assert "Yes, via keep_alive and slot reuse." in body


def test_append_followup_missing_session_returns_none(isolated):
    assert research_session.append_followup("nope", "q", "a") is None


def test_unsafe_session_id_is_rejected(isolated):
    # Path-traversal ids never resolve to a file.
    assert research_session.get_session("../etc/passwd") is None


# ── Router level ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(isolated, monkeypatch):
    """TestClient with auth + rate limiting off; ollama + web search stubbed so
    no model or network is touched."""
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")

    import api.middleware
    importlib.reload(api.middleware)
    import api.main
    importlib.reload(api.main)

    import api.routers.graph as graph_mod
    import api.routers.research as research_mod

    # Stub the local model — deterministic, no Ollama needed.
    def _fake_chat(*args, **kwargs):
        return {"content": "STUB ANSWER"}

    monkeypatch.setattr(graph_mod._ollama, "chat", _fake_chat)
    monkeypatch.setattr(research_mod._ollama, "chat", _fake_chat)

    # A web search that MUST NOT be called unless web_search=True.
    calls = {"search": 0}

    async def _fake_search(query, *a, **k):
        calls["search"] += 1
        return SearchResponse(
            query=query,
            results=[SearchResult(title="Hit", url="https://hit.example", snippet="x")],
            backend="stub",
        )

    monkeypatch.setattr(graph_mod, "search_web", _fake_search)
    monkeypatch.setattr(research_mod, "search_web", _fake_search)

    from fastapi.testclient import TestClient
    from api.main import app

    c = TestClient(app)
    c._search_calls = calls  # type: ignore[attr-defined]
    return c


def test_deep_dive_returns_session_id(client):
    r = client.post(
        "/api/research/deep-dive",
        json={"topic": "Edge inference", "model": "dolphin3:latest", "depth": 2},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("session_id"), "deep-dive must return a session_id"
    # Session is retrievable via the research router.
    sid = data["session_id"]
    g = client.get(f"/api/research/sessions/{sid}")
    assert g.status_code == 200
    assert g.json()["topic"] == "Edge inference"


def test_followup_appends_turn_web_search_off_by_default(client):
    # Seed a session (no web search performed for the seed synthesis stub path
    # is fine — deep-dive stub search increments the counter; reset after).
    r = client.post(
        "/api/research/deep-dive",
        json={"topic": "RAG grounding", "model": "dolphin3:latest", "depth": 1},
    )
    sid = r.json()["session_id"]
    client._search_calls["search"] = 0  # ignore deep-dive's own searches

    fr = client.post(
        "/api/research/followup",
        json={"session_id": sid, "question": "Which store is fastest?"},
    )
    assert fr.status_code == 200, fr.text
    body = fr.json()
    assert body["answer"] == "STUB ANSWER"
    assert body["web_search"] is False
    assert body["turns"] == 2
    # PRIVACY: no web search when the operator did not opt in.
    assert client._search_calls["search"] == 0, "followup must not egress by default"


def test_followup_web_search_opt_in_egresses_once(client):
    r = client.post(
        "/api/research/deep-dive",
        json={"topic": "Latest models", "model": "dolphin3:latest", "depth": 1},
    )
    sid = r.json()["session_id"]
    client._search_calls["search"] = 0

    fr = client.post(
        "/api/research/followup",
        json={"session_id": sid, "question": "What shipped this week?", "web_search": True},
    )
    assert fr.status_code == 200, fr.text
    assert fr.json()["web_search"] is True
    assert client._search_calls["search"] == 1


def test_followup_missing_session_404(client):
    fr = client.post(
        "/api/research/followup",
        json={"session_id": "does-not-exist", "question": "hi"},
    )
    assert fr.status_code == 404
