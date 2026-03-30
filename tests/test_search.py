#!/usr/bin/env python3
"""
Search Service Tests — Unit tests (mocked) and Integration tests

Unit tests:   Always run, no external dependencies
Integration:  Require Ollama running + internet access

Run all:      pytest tests/test_search.py -v
Run unit:     pytest tests/test_search.py -v -k "not integration"
"""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Test client with auth disabled"""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import importlib
    import api.middleware
    importlib.reload(api.middleware)
    import api.main
    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


# ── Unit Tests: Intent Detection ──────────────────────────────────────────


class TestIntentDetection:
    """Tests for search intent heuristics"""

    def test_question_with_recency(self):
        from api.services.search_service import detect_search_intent

        assert detect_search_intent("What happened in tech news today?")
        assert detect_search_intent("Who won the election in 2026?")
        assert detect_search_intent("What is the latest iPhone model?")

    def test_lookup_queries(self):
        from api.services.search_service import detect_search_intent

        assert detect_search_intent("Search for the best Python frameworks")
        assert detect_search_intent("Look up the current Bitcoin price")
        assert detect_search_intent("Find me the top rated restaurants nearby")

    def test_pure_chat_no_search(self):
        from api.services.search_service import detect_search_intent

        # Simple greetings and coding tasks should NOT trigger search
        assert not detect_search_intent("Hello!")
        assert not detect_search_intent("Write a Python function to sort a list")
        assert not detect_search_intent("Explain how recursion works")

    def test_edge_cases(self):
        from api.services.search_service import detect_search_intent

        assert not detect_search_intent("")
        assert not detect_search_intent("ok")
        assert not detect_search_intent("yes")


# ── Unit Tests: Context Formatting ────────────────────────────────────────


class TestContextFormatting:
    """Tests for search result formatting into system prompts"""

    def test_format_with_results(self):
        from api.services.search_service import format_search_context, SearchResult

        results = [
            SearchResult(title="Python 3.12 Release", url="https://python.org/3.12", snippet="Python 3.12 adds..."),
            SearchResult(title="What's New", url="https://docs.python.org/whatsnew", snippet="New features include..."),
        ]

        context = format_search_context("python 3.12 features", results)
        assert "[1]" in context
        assert "[2]" in context
        assert "Python 3.12 Release" in context
        assert "https://python.org/3.12" in context
        assert "INSTRUCTIONS" in context
        assert "cite" in context.lower()

    def test_format_empty_results(self):
        from api.services.search_service import format_search_context

        assert format_search_context("query", []) == ""

    def test_format_preserves_all_results(self):
        from api.services.search_service import format_search_context, SearchResult

        results = [
            SearchResult(title=f"Result {i}", url=f"https://example.com/{i}", snippet=f"Snippet {i}")
            for i in range(5)
        ]
        context = format_search_context("test", results)
        for i in range(5):
            assert f"[{i+1}]" in context
            assert f"Result {i}" in context


# ── Unit Tests: Data Structures ───────────────────────────────────────────


class TestDataStructures:
    """Tests for SearchResult and SearchResponse"""

    def test_search_result_to_dict(self):
        from api.services.search_service import SearchResult

        r = SearchResult(title="Test", url="https://test.com", snippet="A test")
        d = r.to_dict()
        assert d == {"title": "Test", "url": "https://test.com", "snippet": "A test"}

    def test_search_response_to_dict(self):
        from api.services.search_service import SearchResponse, SearchResult

        sr = SearchResponse(
            query="test",
            results=[SearchResult(title="T", url="https://t.com", snippet="S")],
            backend="duckduckgo",
        )
        d = sr.to_dict()
        assert d["query"] == "test"
        assert d["backend"] == "duckduckgo"
        assert len(d["results"]) == 1
        assert d["error"] is None


# ── Unit Tests: Backend Functions ─────────────────────────────────────────


class TestSearchBackends:
    """Tests for individual search backends (mocked HTTP)"""

    @pytest.mark.asyncio
    async def test_searxng_disabled_when_no_url(self):
        from api.services.search_service import _search_searxng

        with patch.dict(os.environ, {"SEARXNG_URL": ""}):
            # Re-import to pick up env change
            import api.services.search_service as ss
            original = ss.SEARXNG_URL
            ss.SEARXNG_URL = ""
            results = await ss._search_searxng("test", 5)
            assert results == []
            ss.SEARXNG_URL = original

    @pytest.mark.asyncio
    async def test_brave_disabled_when_no_key(self):
        from api.services.search_service import _search_brave

        import api.services.search_service as ss
        original = ss.BRAVE_SEARCH_API_KEY
        ss.BRAVE_SEARCH_API_KEY = ""
        results = await ss._search_brave("test", 5)
        assert results == []
        ss.BRAVE_SEARCH_API_KEY = original


# ── Unit Tests: Chat with Web Search ──────────────────────────────────────


class TestChatWithSearch:
    """Tests for chat endpoint with web_search parameter"""

    def test_web_search_field_accepted(self, client):
        """web_search parameter should be accepted without error"""
        # This will fail at Ollama level (mocked out below), but shouldn't 422
        with patch("api.services.ollama_service.requests.post") as mock_post, \
             patch("api.services.search_service.search", new_callable=AsyncMock) as mock_search:

            # Mock search
            from api.services.search_service import SearchResponse, SearchResult
            mock_search.return_value = SearchResponse(
                query="test",
                results=[
                    SearchResult(title="Result 1", url="https://example.com/1", snippet="Test snippet"),
                ],
                backend="duckduckgo",
            )

            # Mock Ollama
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "message": {"content": "Based on [1], the answer is..."},
                "prompt_eval_count": 50,
                "eval_count": 20,
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "dolphin3:latest",
                    "messages": [{"role": "user", "content": "What is the latest news?"}],
                    "web_search": True,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "choices" in data
            assert "sources" in data
            assert len(data["sources"]) == 1
            assert data["sources"][0]["title"] == "Result 1"

    def test_web_search_false_no_sources(self, client):
        """When web_search is false, no sources should be in response"""
        with patch("api.services.ollama_service.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "message": {"content": "Hello!"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "dolphin3:latest",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "web_search": False,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "sources" not in data

    def test_web_search_default_false(self, client):
        """web_search should default to false (backward compatible)"""
        with patch("api.services.ollama_service.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "message": {"content": "Hi"},
                "prompt_eval_count": 5,
                "eval_count": 3,
            }
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            # No web_search field at all
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "dolphin3:latest",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
            assert resp.status_code == 200
            assert "sources" not in resp.json()


# ── Unit Tests: HTML Stripping ────────────────────────────────────────────


class TestUtilities:
    """Tests for utility functions"""

    def test_strip_html(self):
        from api.services.search_service import _strip_html

        assert _strip_html("<b>bold</b>") == "bold"
        assert _strip_html("no tags") == "no tags"
        assert _strip_html("<a href='x'>link</a> text") == "link text"
        assert _strip_html("&amp; &lt;") == "& <"
        assert _strip_html("") == ""


# ── Unit Tests: Search Settings API ────────────────────────────────────────


class TestSearchSettings:
    """Tests for search settings GET/POST endpoints"""

    def test_get_settings(self, client):
        resp = client.get("/api/inventory/settings/search")
        assert resp.status_code == 200
        data = resp.json()
        assert "searxng_url" in data
        assert "brave_api_key_masked" in data
        assert "active_backend" in data
        assert "search_timeout" in data
        assert "max_results" in data
        assert "default_backend" in data
        # Default backend should be duckduckgo when nothing is configured
        assert data["active_backend"] in ("duckduckgo", "searxng", "brave", "auto")

    def test_update_settings_backend(self, client):
        resp = client.post(
            "/api/inventory/settings/search",
            json={"default_backend": "duckduckgo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"
        assert data["config"]["default_backend"] == "duckduckgo"

    def test_update_settings_searxng_url(self, client):
        resp = client.post(
            "/api/inventory/settings/search",
            json={"searxng_url": "http://localhost:8888"},
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["searxng_url"] == "http://localhost:8888"

        # Clean up
        client.post("/api/inventory/settings/search", json={"searxng_url": ""})

    def test_update_settings_brave_key_masked(self, client):
        resp = client.post(
            "/api/inventory/settings/search",
            json={"brave_api_key": "BSA_test1234567890"},
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        # Key should be masked in response
        assert "test1234567890" not in cfg.get("brave_api_key_masked", "")
        assert cfg["brave_api_key_masked"].startswith("***")

        # Clean up
        client.post("/api/inventory/settings/search", json={"brave_api_key": ""})

    def test_update_settings_partial(self, client):
        """Only provided fields should update, others preserved"""
        # Set timeout
        client.post("/api/inventory/settings/search", json={"search_timeout": 15})
        # Update only max_results
        resp = client.post(
            "/api/inventory/settings/search",
            json={"max_results": 8},
        )
        cfg = resp.json()["config"]
        assert cfg["max_results"] == 8
        assert cfg["search_timeout"] == 15

        # Clean up
        client.post("/api/inventory/settings/search", json={"search_timeout": 10, "max_results": 5})

    def test_settings_persists(self, client):
        """Settings should persist across reads"""
        client.post("/api/inventory/settings/search", json={"max_results": 7})
        resp = client.get("/api/inventory/settings/search")
        assert resp.json()["max_results"] == 7

        # Clean up
        client.post("/api/inventory/settings/search", json={"max_results": 5})


# ── Unit Tests: Runtime Config ─────────────────────────────────────────────


class TestRuntimeConfig:
    """Tests for the search service runtime config"""

    def test_get_config_returns_defaults(self):
        from api.services.search_service import get_config
        cfg = get_config()
        assert "searxng_url" in cfg
        assert "brave_api_key_masked" in cfg
        assert "active_backend" in cfg
        assert isinstance(cfg["search_timeout"], int)
        assert isinstance(cfg["max_results"], int)

    def test_resolve_backend_defaults_to_ddg(self):
        from api.services.search_service import _resolve_backend
        cfg = {"searxng_url": "", "brave_api_key": "", "default_backend": "auto"}
        assert _resolve_backend(cfg) == "duckduckgo"

    def test_resolve_backend_prefers_searxng(self):
        from api.services.search_service import _resolve_backend
        cfg = {"searxng_url": "http://localhost:8888", "brave_api_key": "", "default_backend": "auto"}
        assert _resolve_backend(cfg) == "searxng"

    def test_resolve_backend_explicit_override(self):
        from api.services.search_service import _resolve_backend
        cfg = {"searxng_url": "http://localhost:8888", "brave_api_key": "key", "default_backend": "brave"}
        assert _resolve_backend(cfg) == "brave"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
