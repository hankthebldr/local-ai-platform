# Phase 1: Mac App + Tool-Calling Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a demo-ready macOS DMG with agentic tool-calling — the LLM can invoke plugin tools mid-conversation, and the whole platform runs as a native Mac app.

**Architecture:** Tool executor service converts plugin tools to Ollama format and runs an iterative call-execute-respond loop. PyWebView wraps the FastAPI dashboard as a native Mac window. First-run setup wizard handles Ollama CLI installation and model download. py2app + create-dmg produces the final DMG.

**Tech Stack:** Python 3, FastAPI, pywebview, py2app, create-dmg, Ollama API

**Spec:** `docs/superpowers/specs/2026-04-14-mac-app-tool-calling-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `api/services/tool_executor.py` | Convert plugin tools to Ollama format, run tool-call loop |
| `api/routers/setup.py` | Setup wizard endpoints (Ollama install, model pull, completion) |
| `api/static/setup.html` | First-run setup wizard UI |
| `desktop/app.py` | PyWebView entry point with server lifecycle |
| `desktop/setup_py2app.py` | py2app build configuration |
| `desktop/icon.icns` | App icon (placeholder, Cortex green) |
| `scripts/build_mac.sh` | Build pipeline: py2app → DMG |
| `tests/test_tool_executor.py` | Tool-calling loop tests |
| `tests/test_setup.py` | Setup wizard endpoint tests |

### Modified Files
| File | Change |
|------|--------|
| `api/services/ollama_service.py:90-159` | Add `tools` parameter to `chat()` and return tool_calls |
| `api/services/plugin_service.py` | Add `get_ollama_tools()` method |
| `api/routers/chat.py:31-39,42-171` | Add tools/max_tool_iterations to request model, integrate tool executor |
| `api/main.py:18,100-108` | Register setup router |
| `setup/requirements.txt` | Add pywebview |

---

## Task 1: Add `tools` Support to OllamaService

**Files:**
- Modify: `api/services/ollama_service.py`
- Test: `tests/test_tool_executor.py`

- [ ] **Step 1: Write failing test for Ollama chat with tools**

Create `tests/test_tool_executor.py`:

```python
#!/usr/bin/env python3
"""Tests for tool-calling loop and Ollama tools integration"""

import os
import pytest
from unittest.mock import patch, MagicMock
import json


class TestOllamaToolsFormat:
    """Test that OllamaService accepts and passes tools parameter"""

    def test_chat_accepts_tools_param(self):
        """chat() should accept a tools parameter and include it in the request"""
        from api.services.ollama_service import OllamaService

        svc = OllamaService()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web-search__web_search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ]

        # Mock the requests.post to capture what gets sent
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello"},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_response) as mock_post:
            result = svc.chat(
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
                tools=tools,
            )

            # Verify tools were included in the request body
            call_args = mock_post.call_args
            sent_body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
            assert "tools" in sent_body
            assert sent_body["tools"] == tools
            assert result["content"] == "Hello"

    def test_chat_returns_tool_calls(self):
        """When model responds with tool_calls, they should be in the result"""
        from api.services.ollama_service import OllamaService

        svc = OllamaService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "web-search__web_search",
                            "arguments": {"query": "python tutorials"},
                        }
                    }
                ],
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_response):
            result = svc.chat(
                model="test-model",
                messages=[{"role": "user", "content": "search for python tutorials"}],
                tools=[],
            )

            assert "tool_calls" in result
            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["function"]["name"] == "web-search__web_search"

    def test_chat_without_tools_unchanged(self):
        """chat() without tools parameter should work exactly as before"""
        from api.services.ollama_service import OllamaService

        svc = OllamaService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello there"},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_response) as mock_post:
            result = svc.chat(
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
            )

            call_args = mock_post.call_args
            sent_body = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
            assert "tools" not in sent_body
            assert result["content"] == "Hello there"
            assert "tool_calls" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestOllamaToolsFormat -v`
Expected: FAIL — `chat()` doesn't accept `tools` parameter

- [ ] **Step 3: Update `OllamaService.chat()` to accept tools**

In `api/services/ollama_service.py`, modify the `chat` method signature (line 90) and body:

Change the method signature from:
```python
    def chat(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Dict:
```
to:
```python
    def chat(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        tools: List[Dict] = None,
    ) -> Dict:
```

In the request_data dict (line 104-112), add tools conditionally after the existing fields:
```python
        request_data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            request_data["tools"] = tools
```

In the return dict (line 144-148), add tool_calls if present:
```python
            result_dict = {
                "content": content,
                "prompt_eval_count": result.get("prompt_eval_count", 0),
                "eval_count": result.get("eval_count", 0),
            }
            # Include tool_calls if the model returned them
            tool_calls = result.get("message", {}).get("tool_calls")
            if tool_calls:
                result_dict["tool_calls"] = tool_calls
            return result_dict
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestOllamaToolsFormat -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/ollama_service.py tests/test_tool_executor.py
git commit -m "feat: add tools parameter support to OllamaService.chat()"
```

---

## Task 2: Add `get_ollama_tools()` to PluginService

**Files:**
- Modify: `api/services/plugin_service.py`
- Test: `tests/test_tool_executor.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/test_tool_executor.py`:

```python
class TestPluginToolConversion:
    """Test converting plugin tool definitions to Ollama format"""

    def test_get_ollama_tools_format(self):
        """Plugin tools should convert to Ollama's tools JSON format"""
        import tempfile
        import shutil
        from pathlib import Path
        import yaml

        tmpdir = tempfile.mkdtemp()
        try:
            plugin_path = Path(tmpdir) / "test-plugin"
            plugin_path.mkdir()
            (plugin_path / "plugin.yaml").write_text(yaml.dump({
                "name": "Test", "id": "test-plugin", "version": "1.0.0",
                "description": "Test", "author": "test",
                "tools": [{
                    "id": "my_tool",
                    "file": "tools/my_tool.py",
                    "function": "execute",
                    "description": "Does something useful",
                    "parameters": {
                        "query": {"type": "string", "required": True},
                        "limit": {"type": "integer", "default": 10},
                    },
                }],
            }))
            tools_dir = plugin_path / "tools"
            tools_dir.mkdir()
            (tools_dir / "__init__.py").write_text("")
            (tools_dir / "my_tool.py").write_text(
                'def execute(query: str, limit: int = 10) -> dict:\n    return {"result": query}\n'
            )

            from api.services.plugin_service import PluginService
            svc = PluginService(plugins_dir=tmpdir)
            svc.scan_plugins()

            ollama_tools = svc.get_ollama_tools()

            assert len(ollama_tools) == 1
            tool = ollama_tools[0]
            assert tool["type"] == "function"
            assert tool["function"]["name"] == "test-plugin__my_tool"
            assert tool["function"]["description"] == "Does something useful"

            params = tool["function"]["parameters"]
            assert params["type"] == "object"
            assert "query" in params["properties"]
            assert params["properties"]["query"]["type"] == "string"
            assert "limit" in params["properties"]
            assert params["properties"]["limit"]["type"] == "integer"
            assert "query" in params["required"]
            assert "limit" not in params["required"]
        finally:
            shutil.rmtree(tmpdir)

    def test_get_ollama_tools_empty(self):
        """No plugins = empty tools list"""
        import tempfile
        import shutil
        from pathlib import Path

        tmpdir = tempfile.mkdtemp()
        try:
            from api.services.plugin_service import PluginService
            svc = PluginService(plugins_dir=tmpdir)
            svc.scan_plugins()
            assert svc.get_ollama_tools() == []
        finally:
            shutil.rmtree(tmpdir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestPluginToolConversion -v`
Expected: FAIL — `get_ollama_tools` doesn't exist

- [ ] **Step 3: Add `get_ollama_tools()` to PluginService**

Append to `api/services/plugin_service.py`, after the `call_tool` method:

```python
    def get_ollama_tools(self) -> list:
        """Convert all plugin tools to Ollama's tools format."""
        ollama_tools = []
        for plugin in self._plugins.values():
            for tool in plugin["tools"]:
                # Build properties and required list from parameter schema
                properties = {}
                required = []
                for param_name, param_def in tool.get("parameters", {}).items():
                    prop = {"type": param_def.get("type", "string")}
                    if "default" in param_def:
                        prop["default"] = param_def["default"]
                    if "description" in param_def:
                        prop["description"] = param_def["description"]
                    properties[param_name] = prop
                    if param_def.get("required", False):
                        required.append(param_name)

                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{plugin['id']}__{tool['id']}",
                        "description": tool.get("description", ""),
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                })
        return ollama_tools
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestPluginToolConversion -v`
Expected: All 2 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/plugin_service.py tests/test_tool_executor.py
git commit -m "feat: add get_ollama_tools() for plugin-to-Ollama format conversion"
```

---

## Task 3: Tool Executor Service

**Files:**
- Create: `api/services/tool_executor.py`
- Test: `tests/test_tool_executor.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tool_executor.py`:

```python
class TestToolExecutor:
    """Test the tool-calling loop"""

    def _make_plugin_service(self):
        """Create a plugin service with a mock echo tool"""
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
        """When model doesn't call tools, return content directly"""
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService

        plugin_svc, tmpdir = self._make_plugin_service()
        ollama_svc = OllamaService()
        executor = ToolExecutor(ollama_svc, plugin_svc)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello!"},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_response):
            result = executor.execute(
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
            )

            assert result["content"] == "Hello!"
            assert result["tool_calls_made"] == []

        import shutil
        shutil.rmtree(tmpdir)

    def test_tool_call_executes_and_loops(self):
        """When model calls a tool, execute it and call model again"""
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService

        plugin_svc, tmpdir = self._make_plugin_service()
        ollama_svc = OllamaService()
        executor = ToolExecutor(ollama_svc, plugin_svc)

        # First call: model requests tool
        tool_call_response = MagicMock()
        tool_call_response.status_code = 200
        tool_call_response.json.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "echo__echo",
                        "arguments": {"text": "hello world"},
                    }
                }],
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        # Second call: model responds with final text
        final_response = MagicMock()
        final_response.status_code = 200
        final_response.json.return_value = {
            "message": {"role": "assistant", "content": "The echo returned: hello world"},
            "prompt_eval_count": 20,
            "eval_count": 10,
        }

        with patch("api.services.ollama_service.requests.post", side_effect=[tool_call_response, final_response]):
            result = executor.execute(
                model="test-model",
                messages=[{"role": "user", "content": "echo hello world"}],
            )

            assert result["content"] == "The echo returned: hello world"
            assert len(result["tool_calls_made"]) == 1
            assert result["tool_calls_made"][0]["tool"] == "echo__echo"
            assert result["tool_calls_made"][0]["result"] == {"echo": "hello world"}

        import shutil
        shutil.rmtree(tmpdir)

    def test_max_iterations_stops_loop(self):
        """Loop should stop after max_iterations even if model keeps calling tools"""
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService

        plugin_svc, tmpdir = self._make_plugin_service()
        ollama_svc = OllamaService()
        executor = ToolExecutor(ollama_svc, plugin_svc)

        # Model always requests a tool call
        infinite_tool_response = MagicMock()
        infinite_tool_response.status_code = 200
        infinite_tool_response.json.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "echo__echo",
                        "arguments": {"text": "loop"},
                    }
                }],
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=infinite_tool_response):
            result = executor.execute(
                model="test-model",
                messages=[{"role": "user", "content": "loop forever"}],
                max_iterations=3,
            )

            assert len(result["tool_calls_made"]) == 3
            assert result["stopped_reason"] == "max_iterations"

        import shutil
        shutil.rmtree(tmpdir)

    def test_tool_error_sent_to_model(self):
        """When a tool fails, error is sent back to model as tool result"""
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService

        plugin_svc, tmpdir = self._make_plugin_service()
        ollama_svc = OllamaService()
        executor = ToolExecutor(ollama_svc, plugin_svc)

        # Model calls a nonexistent tool
        tool_call_response = MagicMock()
        tool_call_response.status_code = 200
        tool_call_response.json.return_value = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "echo__nonexistent",
                        "arguments": {},
                    }
                }],
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        # Model recovers after seeing error
        recovery_response = MagicMock()
        recovery_response.status_code = 200
        recovery_response.json.return_value = {
            "message": {"role": "assistant", "content": "Sorry, that tool failed."},
            "prompt_eval_count": 20,
            "eval_count": 10,
        }

        with patch("api.services.ollama_service.requests.post", side_effect=[tool_call_response, recovery_response]):
            result = executor.execute(
                model="test-model",
                messages=[{"role": "user", "content": "use nonexistent tool"}],
            )

            assert result["content"] == "Sorry, that tool failed."
            assert len(result["tool_calls_made"]) == 1
            assert "error" in result["tool_calls_made"][0]["result"]

        import shutil
        shutil.rmtree(tmpdir)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestToolExecutor -v`
Expected: FAIL — `api.services.tool_executor` doesn't exist

- [ ] **Step 3: Implement the tool executor**

Create `api/services/tool_executor.py`:

```python
#!/usr/bin/env python3
"""
Tool Executor — Iterative tool-calling loop for agentic LLM interactions

Converts plugin tools to Ollama format, sends them with chat requests,
executes tool calls from model responses, and feeds results back until
the model produces a final text response or hits the iteration limit.
"""

from __future__ import annotations

import json
from typing import List, Dict, Optional

from ..logging_config import logger
from .ollama_service import OllamaService
from .plugin_service import PluginService


class ToolExecutor:
    """Runs the iterative tool-calling loop between the LLM and plugin tools."""

    def __init__(self, ollama_service: OllamaService, plugin_service: PluginService):
        self.ollama = ollama_service
        self.plugins = plugin_service

    def execute(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        max_iterations: int = 10,
    ) -> Dict:
        """
        Run the tool-calling loop.

        Returns:
            {
                "content": str,              # Final text response
                "tool_calls_made": list,     # Log of all tool calls and results
                "stopped_reason": str,       # "complete" or "max_iterations"
                "prompt_eval_count": int,
                "eval_count": int,
            }
        """
        ollama_tools = self.plugins.get_ollama_tools()
        tool_calls_made = []
        total_prompt_tokens = 0
        total_completion_tokens = 0

        # Working copy of messages (we append tool results as we go)
        working_messages = list(messages)

        for iteration in range(max_iterations):
            logger.info(f"Tool loop iteration {iteration + 1}/{max_iterations}")

            # Call the LLM
            result = self.ollama.chat(
                model=model,
                messages=working_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=ollama_tools if ollama_tools else None,
            )

            total_prompt_tokens += result.get("prompt_eval_count", 0)
            total_completion_tokens += result.get("eval_count", 0)

            # Check if model made tool calls
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                # No tool calls — model produced final response
                return {
                    "content": result["content"],
                    "tool_calls_made": tool_calls_made,
                    "stopped_reason": "complete",
                    "prompt_eval_count": total_prompt_tokens,
                    "eval_count": total_completion_tokens,
                }

            # Process each tool call
            # Append the assistant message with tool_calls to history
            working_messages.append({
                "role": "assistant",
                "content": result.get("content", ""),
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                arguments = func.get("arguments", {})

                # Parse arguments if they're a string
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                # Execute the tool
                tool_result = self._execute_tool(tool_name, arguments)
                tool_calls_made.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": tool_result,
                    "iteration": iteration + 1,
                })

                # Append tool result to message history
                working_messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_result),
                })

                logger.info(
                    f"Tool call: {tool_name}({json.dumps(arguments)[:100]}) "
                    f"-> {json.dumps(tool_result)[:100]}"
                )

        # Hit max iterations
        logger.warning(f"Tool loop hit max iterations ({max_iterations})")
        return {
            "content": result.get("content", "Max tool iterations reached."),
            "tool_calls_made": tool_calls_made,
            "stopped_reason": "max_iterations",
            "prompt_eval_count": total_prompt_tokens,
            "eval_count": total_completion_tokens,
        }

    def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Execute a single tool by its namespaced name (plugin_id__tool_id).
        Returns the result dict or an error dict.
        """
        # Parse namespaced tool name
        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool name format: {tool_name}. Expected 'plugin_id__tool_id'."}

        plugin_id, tool_id = parts

        try:
            return self.plugins.call_tool(plugin_id, tool_id, arguments)
        except (ValueError, RuntimeError) as e:
            logger.error(f"Tool execution failed: {tool_name}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected tool error: {tool_name}: {e}")
            return {"error": f"Unexpected error: {e}"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py -v`
Expected: All 9 tests PASS (3 Ollama + 2 conversion + 4 executor)

- [ ] **Step 5: Commit**

```bash
git add api/services/tool_executor.py tests/test_tool_executor.py
git commit -m "feat: add tool executor with iterative tool-calling loop"
```

---

## Task 4: Integrate Tool Executor into Chat Router

**Files:**
- Modify: `api/routers/chat.py`
- Test: `tests/test_tool_executor.py` (append)

- [ ] **Step 1: Write integration test**

Append to `tests/test_tool_executor.py`:

```python
import importlib
from fastapi.testclient import TestClient


class TestChatToolIntegration:
    """Test that chat endpoint uses tool executor when tools are available"""

    def test_chat_request_accepts_tools_param(self):
        """ChatCompletionRequest should accept tools and max_tool_iterations"""
        os.environ["ENABLE_API_AUTH"] = "false"
        os.environ["RATE_LIMIT_RPM"] = "0"
        import api.middleware
        importlib.reload(api.middleware)
        import api.main
        importlib.reload(api.main)
        from api.main import app
        client = TestClient(app)

        # Just verify the endpoint accepts the new params without error
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Hello"},
            "prompt_eval_count": 10,
            "eval_count": 5,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestChatToolIntegration -v`
Expected: FAIL — `tools` not in ChatCompletionRequest

- [ ] **Step 3: Update ChatCompletionRequest and integrate tool executor**

In `api/routers/chat.py`:

Update the request model (add after `web_search` field, around line 39):
```python
    tools: Optional[bool] = Field(True, description="Enable plugin tool calling")
    max_tool_iterations: Optional[int] = Field(10, description="Max tool-call iterations")
```

Add import at the top (after the plugin import, around line 17):
```python
from ..services.tool_executor import ToolExecutor
```

After `ollama_service = OllamaService()` (line 21), add:
```python
_tool_executor = ToolExecutor(ollama_service, _plugin_service)
```

Replace the non-streaming section (lines 140-171) with:
```python
    # ── Non-Streaming ──────────────────────────────────────────────────
    if request.tools and _plugin_service.get_ollama_tools():
        # Use tool executor for agentic loop
        result = _tool_executor.execute(
            model=request.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            max_iterations=request.max_tool_iterations,
        )

        response = {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": 0,
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result["content"]},
                    "finish_reason": "stop" if result["stopped_reason"] == "complete" else "length",
                }
            ],
            "usage": {
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0),
                "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
            },
        }
        if result["tool_calls_made"]:
            response["tool_calls"] = result["tool_calls_made"]
        if sources:
            response["sources"] = sources
        return response

    # ── Non-Streaming (no tools) ───────────────────────────────────────
    result = ollama_service.chat(
        model=request.model,
        messages=messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    response = {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "created": 0,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result["content"]},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
            "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
        },
    }
    if sources:
        response["sources"] = sources
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/chat.py tests/test_tool_executor.py
git commit -m "feat: integrate tool executor into chat completions endpoint"
```

---

## Task 5: Setup Wizard Router

**Files:**
- Create: `api/routers/setup.py`
- Modify: `api/main.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_setup.py`:

```python
#!/usr/bin/env python3
"""Tests for the setup wizard endpoints"""

import os
import pytest
import importlib
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def setup_client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware
    importlib.reload(api.middleware)
    import api.main
    importlib.reload(api.main)
    from api.main import app
    return TestClient(app)


class TestSetupEndpoints:
    def test_check_ollama_when_running(self, setup_client):
        """Should return running=true when Ollama is reachable"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": []}

        with patch("api.routers.setup.requests.get", return_value=mock_resp):
            resp = setup_client.get("/api/setup/check-ollama")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is True

    def test_check_ollama_when_not_running(self, setup_client):
        """Should return running=false when Ollama is not reachable"""
        with patch("api.routers.setup.requests.get", side_effect=Exception("Connection refused")):
            resp = setup_client.get("/api/setup/check-ollama")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is False

    def test_complete_setup(self, setup_client):
        """Should write setup_complete flag"""
        import tempfile
        tmpdir = tempfile.mkdtemp()

        with patch("api.routers.setup.APP_DIR", tmpdir):
            resp = setup_client.post("/api/setup/complete")
            assert resp.status_code == 200

            flag = os.path.join(tmpdir, "setup_complete")
            assert os.path.exists(flag)

        import shutil
        shutil.rmtree(tmpdir)

    def test_setup_page_served(self, setup_client):
        """GET /setup should return HTML"""
        resp = setup_client.get("/setup")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_setup.py -v`
Expected: FAIL — setup router doesn't exist

- [ ] **Step 3: Create the setup router**

Create `api/routers/setup.py`:

```python
#!/usr/bin/env python3
"""
Setup Router — First-run wizard endpoints

Handles Ollama detection/installation, model pulling, and setup completion.
"""

import os
import shutil
import subprocess
import json

import requests as http_requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path

from ..logging_config import logger

router = APIRouter(tags=["setup"])

APP_DIR = os.path.expanduser("~/.local-ai-platform")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/setup")
async def setup_page():
    """Serve the setup wizard HTML page"""
    setup_html = STATIC_DIR / "setup.html"
    if setup_html.exists():
        return FileResponse(setup_html, media_type="text/html")
    raise HTTPException(status_code=404, detail="Setup page not found")


@router.get("/api/setup/check-ollama")
async def check_ollama():
    """Check if Ollama is installed and running"""
    # Check if binary exists
    ollama_path = shutil.which("ollama")
    installed = ollama_path is not None

    # Check if service is running
    running = False
    try:
        r = http_requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        running = r.status_code == 200
    except Exception:
        pass

    return {"installed": installed, "running": running, "path": ollama_path}


@router.post("/api/setup/install-ollama")
async def install_ollama():
    """Install Ollama via the official CLI installer"""
    # Check if already installed
    if shutil.which("ollama"):
        # Try to start it if not running
        try:
            http_requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
            return {"status": "already_running"}
        except Exception:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"status": "started"}

    # Run the official installer
    logger.info("Installing Ollama via CLI installer...")
    try:
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Ollama install failed: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"Install failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Install timed out after 120s")

    # Start the service
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    logger.info("Ollama installed and started")
    return {"status": "installed"}


@router.post("/api/setup/pull-model")
async def pull_model(body: dict):
    """Pull a model from Ollama with streaming progress"""
    model_name = body.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="model is required")

    def stream_pull():
        try:
            r = http_requests.post(
                f"{OLLAMA_HOST}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=1800,
            )
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    data = json.loads(line)
                    yield f"data: {json.dumps(data)}\n\n"
            yield "data: {\"status\": \"success\"}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(stream_pull(), media_type="text/event-stream")


@router.post("/api/setup/complete")
async def complete_setup():
    """Mark first-run setup as complete"""
    os.makedirs(APP_DIR, exist_ok=True)
    flag_path = os.path.join(APP_DIR, "setup_complete")
    Path(flag_path).touch()
    logger.info(f"Setup complete — flag written to {flag_path}")
    return {"status": "complete"}
```

- [ ] **Step 4: Register the router in `api/main.py`**

In `api/main.py`, update the imports (line 18):
```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, api_keys, plugins, setup
```

Add after `app.include_router(plugins.router)` (line 108):
```python
app.include_router(setup.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_setup.py -v`
Expected: All 4 PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/setup.py api/main.py tests/test_setup.py
git commit -m "feat: add setup wizard router with Ollama install and model pull"
```

---

## Task 6: Setup Wizard UI

**Files:**
- Create: `api/static/setup.html`

- [ ] **Step 1: Create the setup wizard HTML**

Create `api/static/setup.html` — a single-page wizard with 4 steps using the Cortex design tokens. The page uses vanilla JavaScript and the same CSS variables as the main dashboard.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Local AI Platform — Setup</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg-deep: #0a0a0a;
  --bg: #141414;
  --bg-panel: rgba(20, 20, 20, 0.9);
  --border: #2a2a2a;
  --cyan: #00CC66;
  --cyan-dim: #00CC6660;
  --red: #FA582D;
  --text: #e0e0e0;
  --text-dim: #8D8D8D;
  --text-muted: #555555;
  --mono: 'JetBrains Mono', monospace;
  --sans: 'Space Grotesk', system-ui, sans-serif;
}

*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--sans);
  background: var(--bg-deep);
  color: var(--text);
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.wizard {
  width: 560px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 48px;
  position: relative;
}

.step { display: none; }
.step.active { display: block; }

h1 { font-size: 1.6rem; font-weight: 600; margin-bottom: 8px; color: var(--cyan); }
h2 { font-size: 1.2rem; font-weight: 500; margin-bottom: 16px; }
p { color: var(--text-dim); line-height: 1.6; margin-bottom: 24px; }

.btn {
  display: inline-block;
  padding: 12px 28px;
  background: var(--cyan);
  color: #000;
  border: none;
  border-radius: 8px;
  font-family: var(--sans);
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn:hover { opacity: 0.85; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.status { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
.status .dot { width: 10px; height: 10px; border-radius: 50%; }
.status .dot.green { background: var(--cyan); }
.status .dot.red { background: var(--red); }
.status .dot.loading { background: var(--text-muted); animation: pulse 1s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

.model-option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: border-color 0.2s;
}
.model-option:hover, .model-option.selected { border-color: var(--cyan); }
.model-option input { accent-color: var(--cyan); }
.model-name { font-weight: 500; }
.model-meta { font-size: 0.8rem; color: var(--text-dim); }

.progress-bar {
  width: 100%;
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
  margin: 16px 0;
}
.progress-fill {
  height: 100%;
  background: var(--cyan);
  border-radius: 3px;
  transition: width 0.3s;
  width: 0%;
}
.progress-text { font-size: 0.85rem; color: var(--text-dim); font-family: var(--mono); }

.steps-indicator {
  display: flex;
  gap: 8px;
  justify-content: center;
  margin-bottom: 32px;
}
.steps-indicator .pip {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--border);
  transition: background 0.3s;
}
.steps-indicator .pip.active { background: var(--cyan); }
.steps-indicator .pip.done { background: var(--cyan-dim); }
</style>
</head>
<body>
<div class="wizard">
  <div class="steps-indicator">
    <div class="pip active" id="pip-0"></div>
    <div class="pip" id="pip-1"></div>
    <div class="pip" id="pip-2"></div>
    <div class="pip" id="pip-3"></div>
  </div>

  <!-- Step 0: Welcome -->
  <div class="step active" id="step-0">
    <h1>Local AI Platform</h1>
    <h2>Your private AI, running locally.</h2>
    <p>No cloud. No telemetry. Complete autonomy over your models and data. Let's get you set up in a few steps.</p>
    <button class="btn" onclick="goStep(1)">Get Started</button>
  </div>

  <!-- Step 1: Ollama Check -->
  <div class="step" id="step-1">
    <h2>Checking Ollama...</h2>
    <div class="status" id="ollama-status">
      <div class="dot loading" id="ollama-dot"></div>
      <span id="ollama-text">Detecting Ollama...</span>
    </div>
    <p id="ollama-detail"></p>
    <button class="btn" id="ollama-btn" style="display:none" onclick="installOllama()">Install Ollama</button>
    <button class="btn" id="ollama-next" style="display:none" onclick="goStep(2)">Continue</button>
  </div>

  <!-- Step 2: Model Selection -->
  <div class="step" id="step-2">
    <h2>Choose a model</h2>
    <p>Select a model to download. You can add more later from the dashboard.</p>
    <div class="model-option" onclick="selectModel(this, 'dolphin3:8b')">
      <input type="radio" name="model" value="dolphin3:8b">
      <div><div class="model-name">dolphin3:8b</div><div class="model-meta">4.9 GB · ~40 tok/s · Fast, uncensored</div></div>
    </div>
    <div class="model-option" onclick="selectModel(this, 'qwen2.5:14b')">
      <input type="radio" name="model" value="qwen2.5:14b">
      <div><div class="model-name">qwen2.5:14b</div><div class="model-meta">9 GB · ~25 tok/s · Balanced</div></div>
    </div>
    <div class="model-option" onclick="selectModel(this, 'deepseek-r1:32b')">
      <input type="radio" name="model" value="deepseek-r1:32b">
      <div><div class="model-name">deepseek-r1:32b</div><div class="model-meta">19 GB · ~10 tok/s · Best reasoning</div></div>
    </div>
    <button class="btn" id="download-btn" disabled onclick="downloadModel()">Download</button>
    <div id="download-progress" style="display:none">
      <div class="progress-bar"><div class="progress-fill" id="dl-fill"></div></div>
      <div class="progress-text" id="dl-text">Starting download...</div>
    </div>
  </div>

  <!-- Step 3: Done -->
  <div class="step" id="step-3">
    <h1>You're all set!</h1>
    <p>Your local AI platform is ready. Open the dashboard to start chatting.</p>
    <button class="btn" onclick="completeSetup()">Open Dashboard</button>
  </div>
</div>

<script>
let currentStep = 0;
let selectedModel = '';

function goStep(n) {
  document.getElementById(`step-${currentStep}`).classList.remove('active');
  document.getElementById(`step-${n}`).classList.add('active');
  for (let i = 0; i < 4; i++) {
    const pip = document.getElementById(`pip-${i}`);
    pip.className = 'pip' + (i < n ? ' done' : i === n ? ' active' : '');
  }
  currentStep = n;
  if (n === 1) checkOllama();
}

async function checkOllama() {
  const dot = document.getElementById('ollama-dot');
  const text = document.getElementById('ollama-text');
  const detail = document.getElementById('ollama-detail');
  try {
    const r = await fetch('/api/setup/check-ollama');
    const data = await r.json();
    if (data.running) {
      dot.className = 'dot green';
      text.textContent = 'Ollama is running';
      document.getElementById('ollama-next').style.display = '';
    } else if (data.installed) {
      dot.className = 'dot red';
      text.textContent = 'Ollama installed but not running';
      detail.textContent = 'Starting Ollama...';
      await fetch('/api/setup/install-ollama', {method: 'POST'});
      dot.className = 'dot green';
      text.textContent = 'Ollama is running';
      document.getElementById('ollama-next').style.display = '';
    } else {
      dot.className = 'dot red';
      text.textContent = 'Ollama not installed';
      detail.textContent = 'Ollama is required for local inference.';
      document.getElementById('ollama-btn').style.display = '';
    }
  } catch (e) {
    dot.className = 'dot red';
    text.textContent = 'Error checking Ollama';
    detail.textContent = e.message;
    document.getElementById('ollama-btn').style.display = '';
  }
}

async function installOllama() {
  const dot = document.getElementById('ollama-dot');
  const text = document.getElementById('ollama-text');
  const btn = document.getElementById('ollama-btn');
  dot.className = 'dot loading';
  text.textContent = 'Installing Ollama...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/setup/install-ollama', {method: 'POST'});
    const data = await r.json();
    if (r.ok) {
      dot.className = 'dot green';
      text.textContent = 'Ollama installed';
      btn.style.display = 'none';
      document.getElementById('ollama-next').style.display = '';
    } else {
      throw new Error(data.detail || 'Install failed');
    }
  } catch (e) {
    dot.className = 'dot red';
    text.textContent = 'Install failed: ' + e.message;
    btn.disabled = false;
  }
}

function selectModel(el, model) {
  document.querySelectorAll('.model-option').forEach(o => o.classList.remove('selected'));
  el.classList.add('selected');
  el.querySelector('input').checked = true;
  selectedModel = model;
  document.getElementById('download-btn').disabled = false;
}

async function downloadModel() {
  if (!selectedModel) return;
  const btn = document.getElementById('download-btn');
  const prog = document.getElementById('download-progress');
  const fill = document.getElementById('dl-fill');
  const text = document.getElementById('dl-text');
  btn.disabled = true;
  prog.style.display = '';

  try {
    const r = await fetch('/api/setup/pull-model', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: selectedModel}),
    });
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = JSON.parse(line.slice(6));
        if (data.total && data.completed) {
          const pct = Math.round((data.completed / data.total) * 100);
          fill.style.width = pct + '%';
          text.textContent = `${pct}% — ${data.status || 'downloading'}`;
        } else if (data.status) {
          text.textContent = data.status;
          if (data.status === 'success') {
            fill.style.width = '100%';
            setTimeout(() => goStep(3), 500);
          }
        }
      }
    }
  } catch (e) {
    text.textContent = 'Download failed: ' + e.message;
    btn.disabled = false;
  }
}

async function completeSetup() {
  await fetch('/api/setup/complete', {method: 'POST'});
  window.location.href = '/';
}
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the setup page renders**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_setup.py -v`
Expected: All 4 PASS (including the HTML serve test)

- [ ] **Step 3: Commit**

```bash
git add api/static/setup.html
git commit -m "feat: add setup wizard UI with Ollama install and model download"
```

---

## Task 7: Desktop App Entry Point

**Files:**
- Create: `desktop/app.py`
- Create: `desktop/setup_py2app.py`
- Modify: `setup/requirements.txt`

- [ ] **Step 1: Create the desktop directory**

```bash
mkdir -p desktop
```

- [ ] **Step 2: Create `desktop/app.py`**

```python
#!/usr/bin/env python3
"""
Local AI Platform — macOS Desktop App

PyWebView wrapper that:
1. Starts the FastAPI server in a background thread
2. Opens a native macOS window pointing at the dashboard
3. Shows the setup wizard on first run
"""

import os
import sys
import time
import threading

import requests
import webview

# Ensure the platform code is importable
APP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

APP_DIR = os.path.expanduser("~/.local-ai-platform")
SETUP_FLAG = os.path.join(APP_DIR, "setup_complete")
HOST = "127.0.0.1"
PORT = 8000


def start_server():
    """Start the FastAPI server in a background thread."""
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


def wait_for_server(timeout=15):
    """Block until the server responds to /health."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://{HOST}:{PORT}/health", timeout=1)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            time.sleep(0.3)
    return False


def main():
    os.makedirs(APP_DIR, exist_ok=True)

    # Start server
    server = threading.Thread(target=start_server, daemon=True)
    server.start()

    if not wait_for_server():
        print("ERROR: Server failed to start within 15 seconds", file=sys.stderr)
        sys.exit(1)

    # Choose URL based on first-run state
    url = f"http://{HOST}:{PORT}"
    if not os.path.exists(SETUP_FLAG):
        url += "/setup"

    # Open native window
    webview.create_window(
        "Local AI Platform",
        url,
        width=1200,
        height=800,
        min_size=(900, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Create `desktop/setup_py2app.py`**

```python
"""
py2app build configuration for Local AI Platform

Usage:
    python desktop/setup_py2app.py py2app
"""

from setuptools import setup

APP = ["desktop/app.py"]

OPTIONS = {
    "argv_emulation": False,
    "includes": [
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pydantic",
        "yaml",
        "requests",
        "webview",
        "dotenv",
        "psutil",
    ],
    "packages": ["api", "plugins"],
    "plist": {
        "CFBundleName": "Local AI Platform",
        "CFBundleDisplayName": "Local AI Platform",
        "CFBundleIdentifier": "com.localai.platform",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
```

- [ ] **Step 4: Add pywebview to requirements**

Append to `setup/requirements.txt`:
```
# Desktop App
pywebview==5.1
```

- [ ] **Step 5: Verify the entry point runs**

```bash
source ../../../venv/bin/activate && pip install pywebview && python desktop/app.py &
sleep 5 && curl -s http://127.0.0.1:8000/health | python -m json.tool
# Should return health JSON; then kill the process
kill %1 2>/dev/null
```

- [ ] **Step 6: Commit**

```bash
git add desktop/ setup/requirements.txt
git commit -m "feat: add PyWebView desktop app entry point and py2app config"
```

---

## Task 8: Build Pipeline (DMG)

**Files:**
- Create: `scripts/build_mac.sh`

- [ ] **Step 1: Create the build script**

Create `scripts/build_mac.sh`:

```bash
#!/bin/bash
set -e

echo "=== Local AI Platform — macOS Build Pipeline ==="
echo ""

# Ensure we're in the project root
cd "$(dirname "$0")/.."

# ── Step 1: Check prerequisites ─────────────────────────────────────
echo "[1/4] Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

if ! python3 -c "import py2app" 2>/dev/null; then
    echo "Installing py2app..."
    pip install py2app
fi

if ! command -v create-dmg &>/dev/null; then
    echo "Installing create-dmg..."
    if command -v brew &>/dev/null; then
        brew install create-dmg
    else
        echo "ERROR: create-dmg not found. Install via: brew install create-dmg"
        exit 1
    fi
fi

echo "  Prerequisites OK"

# ── Step 2: Clean previous build ────────────────────────────────────
echo "[2/4] Cleaning previous build..."
rm -rf build/ dist/

# ── Step 3: Build .app with py2app ──────────────────────────────────
echo "[3/4] Building .app bundle..."
python3 desktop/setup_py2app.py py2app

if [ ! -d "dist/Local AI Platform.app" ] && [ ! -d "dist/app.app" ]; then
    echo "ERROR: py2app failed to produce .app bundle"
    exit 1
fi

# Rename if py2app used the script name
if [ -d "dist/app.app" ]; then
    mv "dist/app.app" "dist/Local AI Platform.app"
fi

echo "  .app bundle created"

# ── Step 4: Create DMG ──────────────────────────────────────────────
echo "[4/4] Creating DMG..."

create-dmg \
    --volname "Local AI Platform" \
    --volicon "desktop/icon.icns" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon "Local AI Platform.app" 150 200 \
    --app-drop-link 450 200 \
    --no-internet-enable \
    "dist/LocalAIPlatform.dmg" \
    "dist/Local AI Platform.app" \
    2>/dev/null || {
        # Fallback: create DMG with hdiutil if create-dmg fails
        echo "  create-dmg failed, using hdiutil fallback..."
        hdiutil create -volname "Local AI Platform" \
            -srcfolder "dist/Local AI Platform.app" \
            -ov -format UDZO \
            "dist/LocalAIPlatform.dmg"
    }

echo ""
echo "=== Build Complete ==="
echo "  DMG: dist/LocalAIPlatform.dmg"
echo "  Size: $(du -sh "dist/LocalAIPlatform.dmg" | cut -f1)"
```

- [ ] **Step 2: Create placeholder icon**

```bash
# Create a minimal placeholder .icns (will be replaced with proper Cortex-branded icon later)
# For now, use sips to create from a PNG or just touch the file
touch desktop/icon.icns
```

- [ ] **Step 3: Make build script executable**

```bash
chmod +x scripts/build_mac.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/build_mac.sh desktop/icon.icns
git commit -m "feat: add macOS build pipeline (py2app + DMG)"
```

---

## Task 9: Final Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

```bash
source ../../../venv/bin/activate && python -m pytest tests/ -v --tb=short -k "not integration"
```
Expected: All tests pass

- [ ] **Step 2: Verify tool-calling loop end-to-end**

```bash
# Start server
source ../../../venv/bin/activate && python -m api.main &
sleep 3

# Test chat with tools enabled (requires Ollama + a model running)
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dolphin3:latest",
    "messages": [{"role": "user", "content": "search for quantum computing"}],
    "tools": true
  }' | python -m json.tool

# Test setup wizard
curl -s http://localhost:8000/setup | head -5
# Should return HTML

# Test Ollama check
curl -s http://localhost:8000/api/setup/check-ollama | python -m json.tool

kill %1 2>/dev/null
```

- [ ] **Step 3: Verify desktop app launches**

```bash
source ../../../venv/bin/activate && python desktop/app.py
# Should open a native window with the dashboard (or setup wizard)
```

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "chore: final integration verification"
```
