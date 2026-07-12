"""GP-2 commit 5 — agent chat executes through the /v1 pipeline.

The old /api/agents/{id}/chat called ollama.chat directly, so an agent's tools
never ran and its web_search builtin was a silent no-op. It now routes through
chat_completions: plugin tools execute, web_search is honored when the agent
declares it, and errors are OpenAI-shaped.

The ollama + search backends are stubbed so the test exercises the ROUTER wiring
(model resolution → /v1 hand-off → response mapping), not real inference.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"

    # Isolated agents dir with a web-search-enabled agent.
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "searcher.yaml").write_text(
        "id: searcher\n"
        "name: Searcher\n"
        "system_prompt: You search the web.\n"
        "tools:\n"
        "  - type: web_search\n"
    )
    (agents_dir / "plain.yaml").write_text(
        "id: plain\nname: Plain\nsystem_prompt: You are plain.\n"
    )

    import importlib

    import api.routers.agents as agents_mod
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)

    # Reroute the router's service singleton at the isolated dir.
    from api.services.agent_service import AgentService

    monkeypatch.setattr(agents_mod, "_service", AgentService(str(agents_dir)))

    # Fake resolver — no real model registry / ollama needed.
    class _FakeResolver:
        def resolve(self, model=None, role=None, default_role=None):
            return model or "llama3.2:3b"

    monkeypatch.setattr(agents_mod, "_resolver", _FakeResolver())

    from api.main import app

    return TestClient(app)


def _stub_chat(monkeypatch, reply="stubbed answer"):
    import api.routers.chat as chat_mod

    def _fake_chat(model, messages, temperature=None, max_tokens=None):
        return {"content": reply, "prompt_eval_count": 3, "eval_count": 5}

    monkeypatch.setattr(chat_mod.ollama_service, "chat", _fake_chat)
    # Force the no-tool branch so the stubbed ollama_service.chat is what runs.
    monkeypatch.setattr(
        chat_mod._plugin_service, "get_ollama_tools", lambda: [], raising=False
    )


def test_agent_chat_returns_content_via_v1(client, monkeypatch):
    _stub_chat(monkeypatch, "hello from v1")
    r = client.post(
        "/api/agents/plain/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "plain"
    assert body["content"] == "hello from v1"
    assert body["usage"]["total_tokens"] == 8


def test_agent_chat_honors_web_search_when_declared(client, monkeypatch):
    _stub_chat(monkeypatch)

    called = {"n": 0}

    async def _fake_search(query, *a, **k):
        called["n"] += 1
        from api.services.search_service import SearchResponse

        return SearchResponse(query=query, results=[], backend="stub")

    import api.routers.chat as chat_mod

    monkeypatch.setattr(chat_mod.search_service, "search", _fake_search)

    r = client.post(
        "/api/agents/searcher/chat",
        json={"messages": [{"role": "user", "content": "latest news"}]},
    )
    assert r.status_code == 200
    # The agent declares web_search → the /v1 pipeline invoked the search backend.
    assert called["n"] == 1


def test_agent_chat_no_web_search_when_not_declared(client, monkeypatch):
    _stub_chat(monkeypatch)

    called = {"n": 0}

    async def _fake_search(query, *a, **k):
        called["n"] += 1
        from api.services.search_service import SearchResponse

        return SearchResponse(query=query, results=[], backend="stub")

    import api.routers.chat as chat_mod

    monkeypatch.setattr(chat_mod.search_service, "search", _fake_search)

    r = client.post(
        "/api/agents/plain/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert called["n"] == 0  # plain agent has no web_search tool → no egress


def test_agent_chat_unknown_agent_404(client):
    r = client.post(
        "/api/agents/ghost/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
