#!/usr/bin/env python3
"""Tests for Plugin Service"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path

import yaml


@pytest.fixture
def plugin_dir():
    """Temp plugin directory with example plugin"""
    tmpdir = tempfile.mkdtemp()
    plugin_path = Path(tmpdir) / "test-plugin"
    plugin_path.mkdir()
    (plugin_path / "plugin.yaml").write_text(
        yaml.dump(
            {
                "name": "Test Plugin",
                "id": "test-plugin",
                "version": "1.0.0",
                "description": "A test plugin",
                "author": "test",
                "skills": [
                    {
                        "id": "test-skill",
                        "file": "skills/greeting.md",
                        "triggers": [{"keyword": "hello"}, {"manual": True}],
                    }
                ],
                "tools": [
                    {
                        "id": "echo",
                        "file": "tools/echo_tool.py",
                        "function": "execute",
                        "description": "Echoes input back",
                        "parameters": {
                            "text": {"type": "string", "required": True},
                        },
                    }
                ],
            }
        )
    )
    skills_dir = plugin_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "greeting.md").write_text(
        "---\nname: Greeting\ndescription: Says hello\ninject: system\n---\n\nAlways greet the user warmly."
    )
    tools_dir = plugin_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo_tool.py").write_text(
        'def execute(text: str) -> dict:\n    return {"echo": text}\n'
    )
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def plugin_service(plugin_dir):
    from api.services.plugin_service import PluginService

    return PluginService(plugins_dir=plugin_dir)


class TestPluginDiscovery:
    def test_scan_finds_plugins(self, plugin_service):
        plugins = plugin_service.scan_plugins()
        assert len(plugins) == 1
        assert plugins[0]["id"] == "test-plugin"

    def test_scan_skips_disabled_dir(self, plugin_dir):
        disabled = Path(plugin_dir) / "_disabled"
        disabled.mkdir()
        (disabled / "plugin.yaml").write_text(
            yaml.dump(
                {
                    "name": "Disabled",
                    "id": "disabled",
                    "version": "1.0.0",
                    "description": "Should be skipped",
                    "author": "test",
                }
            )
        )
        from api.services.plugin_service import PluginService

        svc = PluginService(plugins_dir=plugin_dir)
        plugins = svc.scan_plugins()
        assert all(p["id"] != "disabled" for p in plugins)

    def test_list_plugins(self, plugin_service):
        plugin_service.scan_plugins()
        listing = plugin_service.list_plugins()
        assert len(listing) == 1
        assert listing[0]["name"] == "Test Plugin"
        assert len(listing[0]["skills"]) == 1
        assert len(listing[0]["tools"]) == 1


class TestPluginSkills:
    def test_get_skills_by_keyword(self, plugin_service):
        plugin_service.scan_plugins()
        skills = plugin_service.get_skills("hello world")
        assert len(skills) == 1
        assert "greet the user warmly" in skills[0]["content"]
        assert skills[0]["inject"] == "system"

    def test_get_skills_no_match(self, plugin_service):
        plugin_service.scan_plugins()
        skills = plugin_service.get_skills("weather forecast")
        assert len(skills) == 0


class TestPluginTools:
    def test_call_tool(self, plugin_service):
        plugin_service.scan_plugins()
        result = plugin_service.call_tool("test-plugin", "echo", {"text": "ping"})
        assert result == {"echo": "ping"}

    def test_call_tool_unknown_plugin(self, plugin_service):
        plugin_service.scan_plugins()
        with pytest.raises(ValueError, match="Plugin not found"):
            plugin_service.call_tool("nonexistent", "echo", {})

    def test_call_tool_unknown_tool(self, plugin_service):
        plugin_service.scan_plugins()
        with pytest.raises(ValueError, match="Tool not found"):
            plugin_service.call_tool("test-plugin", "nonexistent", {})


import importlib
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def plugin_client():
    """Test client with plugins loaded and master-key auth attached"""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    os.environ["MASTER_API_KEY"] = "test-master"
    os.environ["PLUGINS_DIR"] = str(Path(__file__).parent.parent / "plugins")
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-master"})
    return client


class TestPluginRouter:
    def test_list_plugins(self, plugin_client):
        resp = plugin_client.get("/api/plugins")
        assert resp.status_code == 200
        plugins = resp.json()
        assert isinstance(plugins, list)
        assert any(p["id"] == "web-search" for p in plugins)

    def test_get_plugin_detail(self, plugin_client):
        resp = plugin_client.get("/api/plugins/web-search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "web-search"
        assert len(data["tools"]) >= 1

    def test_invoke_tool(self, plugin_client):
        resp = plugin_client.post(
            "/api/plugins/web-search/tools/web_search",
            json={"query": "test query", "max_results": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_get_unknown_plugin(self, plugin_client):
        resp = plugin_client.get("/api/plugins/nonexistent")
        assert resp.status_code == 404


class TestChatPluginIntegration:
    def test_skill_triggers_inject_system_prompt(self):
        """Verify that plugin skills are found for matching messages"""
        from api.services.plugin_service import PluginService

        svc = PluginService(plugins_dir=str(Path(__file__).parent.parent / "plugins"))
        svc.scan_plugins()

        # "search" should trigger the search-expert skill
        skills = svc.get_skills("please search for quantum computing")
        assert len(skills) >= 1
        assert any("web_search" in s["content"] for s in skills)

    def test_no_skill_for_unmatched_message(self):
        from api.services.plugin_service import PluginService

        svc = PluginService(plugins_dir=str(Path(__file__).parent.parent / "plugins"))
        svc.scan_plugins()

        skills = svc.get_skills("what is the meaning of life")
        assert len(skills) == 0


class TestPluginToolConversion:
    """Test converting plugin tool definitions to Ollama format"""

    def test_get_ollama_tools_format(self):
        import tempfile
        import shutil
        from pathlib import Path
        import yaml

        tmpdir = tempfile.mkdtemp()
        try:
            plugin_path = Path(tmpdir) / "test-plugin"
            plugin_path.mkdir()
            (plugin_path / "plugin.yaml").write_text(
                yaml.dump(
                    {
                        "name": "Test",
                        "id": "test-plugin",
                        "version": "1.0.0",
                        "description": "Test",
                        "author": "test",
                        "tools": [
                            {
                                "id": "my_tool",
                                "file": "tools/my_tool.py",
                                "function": "execute",
                                "description": "Does something useful",
                                "parameters": {
                                    "query": {"type": "string", "required": True},
                                    "limit": {"type": "integer", "default": 10},
                                },
                            }
                        ],
                    }
                )
            )
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
            assert "query" in params["required"]
            assert "limit" not in params["required"]
        finally:
            shutil.rmtree(tmpdir)

    def test_get_ollama_tools_empty(self):
        import tempfile
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            from api.services.plugin_service import PluginService

            svc = PluginService(plugins_dir=tmpdir)
            svc.scan_plugins()
            assert svc.get_ollama_tools() == []
        finally:
            shutil.rmtree(tmpdir)


class TestPluginsAuthGate:
    def test_list_requires_master(self, monkeypatch):
        # Force auth on, otherwise require_master_key is a no-op when a
        # prior test left ENABLE_API_AUTH=false in the global env.
        monkeypatch.setenv("ENABLE_API_AUTH", "true")
        monkeypatch.delenv("MASTER_API_KEY", raising=False)
        import importlib
        import api.middleware
        import api.main

        importlib.reload(api.middleware)
        importlib.reload(api.main)
        from api.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        assert client.get("/api/plugins").status_code == 401

    def test_list_passes_with_master(self, monkeypatch):
        monkeypatch.setenv("ENABLE_API_AUTH", "true")
        monkeypatch.setenv("MASTER_API_KEY", "test-master")
        import importlib
        import api.middleware
        import api.main

        importlib.reload(api.middleware)
        importlib.reload(api.main)
        from api.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get(
            "/api/plugins", headers={"Authorization": "Bearer test-master"}
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_invoke_requires_master(self, monkeypatch):
        monkeypatch.setenv("ENABLE_API_AUTH", "true")
        monkeypatch.delenv("MASTER_API_KEY", raising=False)
        import importlib
        import api.middleware
        import api.main

        importlib.reload(api.middleware)
        importlib.reload(api.main)
        from api.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        assert (
            client.post("/api/plugins/some-id/tools/some-tool", json={}).status_code
            == 401
        )
