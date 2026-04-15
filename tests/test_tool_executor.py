#!/usr/bin/env python3
"""Tests for tool-calling loop and Ollama tools integration"""

import os
import pytest
from unittest.mock import patch, MagicMock
import json


class TestOllamaToolsFormat:
    """Test that OllamaService accepts and passes tools parameter"""

    def test_chat_accepts_tools_param(self):
        from api.services.ollama_service import OllamaService
        svc = OllamaService()
        tools = [{"type": "function", "function": {"name": "test__tool", "description": "Test", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}}]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"role": "assistant", "content": "Hello"}, "prompt_eval_count": 10, "eval_count": 5}

        with patch("api.services.ollama_service.requests.post", return_value=mock_response) as mock_post:
            result = svc.chat(model="test-model", messages=[{"role": "user", "content": "hi"}], tools=tools)
            sent_body = mock_post.call_args[1]["json"]
            assert "tools" in sent_body
            assert sent_body["tools"] == tools
            assert result["content"] == "Hello"

    def test_chat_returns_tool_calls(self):
        from api.services.ollama_service import OllamaService
        svc = OllamaService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "test__tool", "arguments": {"q": "hello"}}}]},
            "prompt_eval_count": 10, "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_response):
            result = svc.chat(model="test-model", messages=[{"role": "user", "content": "hi"}], tools=[])
            assert "tool_calls" in result
            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["function"]["name"] == "test__tool"

    def test_chat_without_tools_unchanged(self):
        from api.services.ollama_service import OllamaService
        svc = OllamaService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"role": "assistant", "content": "Hello there"}, "prompt_eval_count": 10, "eval_count": 5}

        with patch("api.services.ollama_service.requests.post", return_value=mock_response) as mock_post:
            result = svc.chat(model="test-model", messages=[{"role": "user", "content": "hi"}])
            sent_body = mock_post.call_args[1]["json"]
            assert "tools" not in sent_body
            assert result["content"] == "Hello there"
            assert "tool_calls" not in result
