#!/usr/bin/env python3
"""
API Tests - Basic tests for the Local AI Platform API
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app

client = TestClient(app)


class TestHealthEndpoints:
    """Test health and info endpoints"""

    def test_health_check(self):
        """Test the health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert data["version"] == "1.0.0"

    def test_root_endpoint(self):
        """Test the root endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "endpoints" in data


class TestModelsEndpoint:
    """Test models listing endpoint"""

    @patch('api.services.ollama_service.requests.get')
    def test_list_models_success(self, mock_get):
        """Test successful model listing"""
        # Mock Ollama response
        mock_response = Mock()
        mock_response.json.return_value = {
            "models": [
                {"name": "mistral:7b"},
                {"name": "llama3.1:8b"}
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "mistral:7b"
        assert data["data"][0]["object"] == "model"

    @patch('api.services.ollama_service.requests.get')
    def test_list_models_empty(self, mock_get):
        """Test model listing when no models available"""
        mock_response = Mock()
        mock_response.json.return_value = {"models": []}
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 0


class TestChatCompletions:
    """Test chat completions endpoint"""

    @patch('api.services.ollama_service.requests.post')
    def test_chat_completion_success(self, mock_post):
        """Test successful chat completion"""
        # Mock Ollama response
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Hello! How can I help you?",
            "prompt_eval_count": 15,
            "eval_count": 8
        }
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        payload = {
            "model": "mistral:7b",
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }

        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello! How can I help you?"
        assert data["usage"]["prompt_tokens"] == 15
        assert data["usage"]["completion_tokens"] == 8

    def test_chat_completion_missing_model(self):
        """Test chat completion with missing model parameter"""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }

        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 422  # Validation error

    def test_chat_completion_missing_messages(self):
        """Test chat completion with missing messages parameter"""
        payload = {
            "model": "mistral:7b"
        }

        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 422  # Validation error


class TestCompletions:
    """Test text completions endpoint"""

    @patch('api.services.ollama_service.requests.post')
    def test_completion_success(self, mock_post):
        """Test successful text completion"""
        # Mock Ollama response
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Once upon a time, in a land far away...",
            "prompt_eval_count": 5,
            "eval_count": 12
        }
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        payload = {
            "model": "mistral:7b",
            "prompt": "Once upon a time"
        }

        response = client.post("/v1/completions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "text_completion"
        assert "choices" in data
        assert len(data["choices"]) == 1
        assert data["choices"][0]["text"] == "Once upon a time, in a land far away..."
        assert data["usage"]["prompt_tokens"] == 5
        assert data["usage"]["completion_tokens"] == 12

    def test_completion_with_temperature(self):
        """Test completion with custom temperature"""
        with patch('api.services.ollama_service.requests.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {
                "response": "Test response",
                "prompt_eval_count": 5,
                "eval_count": 3
            }
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            payload = {
                "model": "mistral:7b",
                "prompt": "Test prompt",
                "temperature": 0.9,
                "max_tokens": 100
            }

            response = client.post("/v1/completions", json=payload)
            assert response.status_code == 200

            # Verify the mock was called with correct parameters
            call_args = mock_post.call_args
            request_json = call_args[1]['json']
            assert request_json['temperature'] == 0.9
            assert request_json['options']['num_predict'] == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
