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


class TestToolExecutor:
    """Test the tool-calling loop"""

    def _make_plugin_service(self):
        import tempfile
        import shutil
        from pathlib import Path
        import yaml

        tmpdir = tempfile.mkdtemp()
        plugin_path = Path(tmpdir) / "echo-plugin"
        plugin_path.mkdir()
        (plugin_path / "plugin.yaml").write_text(yaml.dump({
            "name": "Echo", "id": "echo", "version": "1.0.0",
            "description": "Echo plugin", "author": "test",
            "tools": [{
                "id": "echo",
                "file": "tools/echo.py",
                "function": "execute",
                "description": "Echoes text back",
                "parameters": {"text": {"type": "string", "required": True}},
            }],
        }))
        tools_dir = plugin_path / "tools"
        tools_dir.mkdir()
        (tools_dir / "__init__.py").write_text("")
        (tools_dir / "echo.py").write_text(
            'def execute(text: str) -> dict:\n    return {"echo": text}\n'
        )
        from api.services.plugin_service import PluginService
        svc = PluginService(plugins_dir=tmpdir)
        svc.scan_plugins()
        return svc, tmpdir

    def test_no_tool_calls_returns_content(self):
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService
        plugin_svc, tmpdir = self._make_plugin_service()
        executor = ToolExecutor(OllamaService(), plugin_svc)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello!"},
            "prompt_eval_count": 10, "eval_count": 5,
        }
        with patch("api.services.ollama_service.requests.post", return_value=mock_response):
            result = executor.execute(model="test", messages=[{"role": "user", "content": "hi"}])
            assert result["content"] == "Hello!"
            assert result["tool_calls_made"] == []
        import shutil; shutil.rmtree(tmpdir)

    def test_tool_call_executes_and_loops(self):
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService
        plugin_svc, tmpdir = self._make_plugin_service()
        executor = ToolExecutor(OllamaService(), plugin_svc)

        tc_resp = MagicMock()
        tc_resp.status_code = 200
        tc_resp.json.return_value = {
            "message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "echo__echo", "arguments": {"text": "hello"}}}]},
            "prompt_eval_count": 10, "eval_count": 5,
        }
        final_resp = MagicMock()
        final_resp.status_code = 200
        final_resp.json.return_value = {
            "message": {"role": "assistant", "content": "Echo said: hello"},
            "prompt_eval_count": 20, "eval_count": 10,
        }
        with patch("api.services.ollama_service.requests.post", side_effect=[tc_resp, final_resp]):
            result = executor.execute(model="test", messages=[{"role": "user", "content": "echo hello"}])
            assert result["content"] == "Echo said: hello"
            assert len(result["tool_calls_made"]) == 1
            assert result["tool_calls_made"][0]["result"] == {"echo": "hello"}
        import shutil; shutil.rmtree(tmpdir)

    def test_max_iterations_stops_loop(self):
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService
        plugin_svc, tmpdir = self._make_plugin_service()
        executor = ToolExecutor(OllamaService(), plugin_svc)

        loop_resp = MagicMock()
        loop_resp.status_code = 200
        loop_resp.json.return_value = {
            "message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "echo__echo", "arguments": {"text": "loop"}}}]},
            "prompt_eval_count": 10, "eval_count": 5,
        }
        with patch("api.services.ollama_service.requests.post", return_value=loop_resp):
            result = executor.execute(model="test", messages=[{"role": "user", "content": "loop"}], max_iterations=3)
            assert len(result["tool_calls_made"]) == 3
            assert result["stopped_reason"] == "max_iterations"
        import shutil; shutil.rmtree(tmpdir)

    def test_tool_error_sent_to_model(self):
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService
        plugin_svc, tmpdir = self._make_plugin_service()
        executor = ToolExecutor(OllamaService(), plugin_svc)

        err_resp = MagicMock()
        err_resp.status_code = 200
        err_resp.json.return_value = {
            "message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "echo__nonexistent", "arguments": {}}}]},
            "prompt_eval_count": 10, "eval_count": 5,
        }
        recovery_resp = MagicMock()
        recovery_resp.status_code = 200
        recovery_resp.json.return_value = {
            "message": {"role": "assistant", "content": "That tool failed."},
            "prompt_eval_count": 20, "eval_count": 10,
        }
        with patch("api.services.ollama_service.requests.post", side_effect=[err_resp, recovery_resp]):
            result = executor.execute(model="test", messages=[{"role": "user", "content": "bad tool"}])
            assert result["content"] == "That tool failed."
            assert "error" in result["tool_calls_made"][0]["result"]
        import shutil; shutil.rmtree(tmpdir)


import os
import importlib
from fastapi.testclient import TestClient


class TestChatToolIntegration:
    def test_chat_request_accepts_tools_param(self):
        os.environ["ENABLE_API_AUTH"] = "false"
        os.environ["RATE_LIMIT_RPM"] = "0"
        import api.middleware
        importlib.reload(api.middleware)
        import api.main
        importlib.reload(api.main)
        from api.main import app
        client = TestClient(app)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello"},
            "prompt_eval_count": 10, "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_response):
            resp = client.post("/v1/chat/completions", json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": True,
                "max_tool_iterations": 5,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "Hello"
