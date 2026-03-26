#!/usr/bin/env python3
"""
API Tests — Unit tests (mocked) and Integration tests (real Ollama)

Unit tests:   Always run, no external dependencies
Integration:  Require Ollama running with at least one model

Run all:      pytest tests/test_api.py -v
Run unit:     pytest tests/test_api.py -v -k "not integration"
Run integ:    pytest tests/test_api.py -v -k "integration"
"""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Test client with auth disabled"""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    from api.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def available_model(client):
    """Get the first available model name from Ollama"""
    resp = client.get("/v1/models")
    models = resp.json().get("data", [])
    if not models:
        pytest.skip("No models available in Ollama")
    # Prefer dolphin3 if available (non-thinking model)
    for m in models:
        if "dolphin" in m["id"]:
            return m["id"]
    return models[0]["id"]


# ── Unit Tests (Mocked) ───────────────────────────────────────────────────


class TestPublicEndpoints:
    """Unit tests for unauthenticated endpoints"""

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1.0.0"
        assert "endpoints" in data

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "ollama" in data
        assert "system" in data
        assert "cpu_percent" in data["system"]

    def test_docs(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


class TestModelsUnit:
    """Unit tests for models endpoint with mocks"""

    @patch("api.services.ollama_service.requests.get")
    def test_list_models_success(self, mock_get, client):
        mock_response = Mock()
        mock_response.json.return_value = {
            "models": [{"name": "mistral:7b"}, {"name": "llama3.1:8b"}]
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 2

    @patch("api.services.ollama_service.requests.get")
    def test_list_models_empty(self, mock_get, client):
        mock_response = Mock()
        mock_response.json.return_value = {"models": []}
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        resp = client.get("/v1/models")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 0


class TestChatUnit:
    """Unit tests for chat completions with mocks"""

    @patch("api.services.ollama_service.requests.post")
    def test_chat_success(self, mock_post, client):
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Hello!",
            "prompt_eval_count": 15,
            "eval_count": 8,
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mistral:7b",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "Hello!"
        assert data["usage"]["total_tokens"] == 23

    def test_chat_missing_model(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 422

    def test_chat_missing_messages(self, client):
        resp = client.post("/v1/chat/completions", json={"model": "x"})
        assert resp.status_code == 422


class TestCompletionsUnit:
    """Unit tests for completions with mocks"""

    @patch("api.services.ollama_service.requests.post")
    def test_completion_success(self, mock_post, client):
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Paris",
            "prompt_eval_count": 5,
            "eval_count": 3,
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        resp = client.post(
            "/v1/completions",
            json={"model": "mistral:7b", "prompt": "Capital of France is"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "text_completion"
        assert data["choices"][0]["text"] == "Paris"


# ── Integration Tests (Real Ollama) ────────────────────────────────────────


class TestIntegrationModels:
    """Integration: test against real Ollama"""

    @pytest.mark.integration
    def test_list_models_real(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        # Should have at least one model
        assert len(data["data"]) > 0


class TestIntegrationChat:
    """Integration: chat against real Ollama"""

    @pytest.mark.integration
    def test_basic_chat(self, client, available_model):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": available_model,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"][0]["message"]["content"]) > 0

    @pytest.mark.integration
    def test_chat_usage_stats(self, client, available_model):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": available_model,
                "messages": [{"role": "user", "content": "Say yes"}],
                "max_tokens": 5,
            },
        )
        usage = resp.json()["usage"]
        assert usage["prompt_tokens"] > 0
        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]

    @pytest.mark.integration
    def test_chat_invalid_model(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "nonexistent-model-xyz",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
            },
        )
        assert resp.status_code in (404, 500)


class TestIntegrationCompletions:
    """Integration: text completions against real Ollama"""

    @pytest.mark.integration
    def test_basic_completion(self, client, available_model):
        resp = client.post(
            "/v1/completions",
            json={
                "model": available_model,
                "prompt": "The capital of France is",
                "max_tokens": 10,
            },
        )
        assert resp.status_code == 200
        assert len(resp.json()["choices"][0]["text"]) > 0


class TestIntegrationStreaming:
    """Integration: streaming against real Ollama"""

    @pytest.mark.integration
    def test_chat_streaming(self, client, available_model):
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": available_model,
                "messages": [{"role": "user", "content": "Say hi"}],
                "max_tokens": 10,
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

            chunks = []
            for line in resp.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunks.append(line)
            assert len(chunks) >= 1

    @pytest.mark.integration
    def test_completion_streaming(self, client, available_model):
        with client.stream(
            "POST",
            "/v1/completions",
            json={
                "model": available_model,
                "prompt": "Count to 3:",
                "max_tokens": 20,
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            chunks = []
            for line in resp.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunks.append(line)
            assert len(chunks) >= 1


# ── Authentication Tests ──────────────────────────────────────────────────


class TestAuthentication:
    """Tests for API key auth (uses module-scoped reload)"""

    @pytest.fixture(autouse=True)
    def auth_client(self):
        """Create auth-enabled client"""
        os.environ["ENABLE_API_AUTH"] = "true"
        os.environ["API_KEY"] = "test-secret-key"
        os.environ["RATE_LIMIT_RPM"] = "0"
        import importlib
        import api.middleware
        importlib.reload(api.middleware)
        import api.main
        importlib.reload(api.main)
        from api.main import app
        self.client = TestClient(app)
        yield
        # Restore defaults
        os.environ["ENABLE_API_AUTH"] = "false"

    def test_no_key_returns_401(self):
        resp = self.client.get("/v1/models")
        assert resp.status_code == 401
        assert "missing_api_key" in resp.json()["error"]["code"]

    def test_wrong_key_returns_401(self):
        resp = self.client.get(
            "/v1/models", headers={"Authorization": "Bearer wrong-key"}
        )
        assert resp.status_code == 401
        assert "invalid_api_key" in resp.json()["error"]["code"]

    def test_correct_key_returns_200(self):
        resp = self.client.get(
            "/v1/models", headers={"Authorization": "Bearer test-secret-key"}
        )
        assert resp.status_code == 200

    def test_health_bypasses_auth(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_query_param_key(self):
        resp = self.client.get("/v1/models?api_key=test-secret-key")
        assert resp.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
