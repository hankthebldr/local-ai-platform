#!/usr/bin/env python3
"""Tests for ProfileService — loading, resolution, tool filtering"""

import os
import pytest
import tempfile
import shutil
import yaml
from pathlib import Path


@pytest.fixture
def profile_dir():
    tmpdir = tempfile.mkdtemp()
    Path(tmpdir, "default.yaml").write_text(yaml.dump({
        "id": "default",
        "name": "Default",
        "description": "All plugins allowed",
        "version": "1.0.0",
        "allowed_plugins": ["*"],
        "tool_rules": {},
        "sandbox": {"mode": "strict", "max_file_size_mb": 10, "allowed_extensions": None},
        "network": {"mode": "unrestricted", "allowed_hosts": []},
        "bound_to_keys": [],
    }))
    Path(tmpdir, "research.yaml").write_text(yaml.dump({
        "id": "research",
        "name": "Research",
        "description": "Search only",
        "version": "1.0.0",
        "allowed_plugins": ["web-search"],
        "tool_rules": {"web-search": {"allowed_tools": ["web_search"]}},
        "sandbox": {"mode": "strict", "max_file_size_mb": 5},
        "network": {"mode": "unrestricted", "allowed_hosts": []},
        "bound_to_keys": [],
    }))
    yield tmpdir
    shutil.rmtree(tmpdir)


class TestProfileLoading:
    def test_load_profiles(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert "default" in [p["id"] for p in svc.list_profiles()]
        assert "research" in [p["id"] for p in svc.list_profiles()]

    def test_get_profile(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        profile = svc.get_profile("research")
        assert profile["id"] == "research"
        assert profile["allowed_plugins"] == ["web-search"]

    def test_get_missing_profile_returns_none(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.get_profile("nonexistent") is None

    def test_reload(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        initial_count = len(svc.list_profiles())
        Path(profile_dir, "new.yaml").write_text(yaml.dump({
            "id": "new", "name": "New", "description": "Test",
            "version": "1.0.0", "allowed_plugins": ["*"], "tool_rules": {},
            "sandbox": {"mode": "strict"}, "network": {"mode": "unrestricted"},
            "bound_to_keys": [],
        }))
        svc.reload()
        assert len(svc.list_profiles()) == initial_count + 1
        assert svc.get_profile("new") is not None


class TestProfileResolution:
    def test_resolve_header_priority(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.resolve(header="research", key_id=None) == "research"

    def test_resolve_default_fallback(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.resolve(header=None, key_id=None) == "default"

    def test_resolve_missing_profile_falls_back_to_default(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.resolve(header="nonexistent", key_id=None) == "default"


class TestToolFiltering:
    def _make_tools(self):
        return [
            {"type": "function", "function": {
                "name": "web-search__web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "web-search__index_site",
                "description": "Index a site",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "file-writer__write_file",
                "description": "Write a file",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
        ]

    def test_filter_tools_wildcard_allows_all(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        filtered = svc.filter_tools(self._make_tools(), "default")
        assert len(filtered) == 3

    def test_filter_tools_restricted_plugin(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        filtered = svc.filter_tools(self._make_tools(), "research")
        names = [t["function"]["name"] for t in filtered]
        assert "file-writer__write_file" not in names
        assert "web-search__web_search" in names

    def test_filter_tools_with_tool_rules(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        filtered = svc.filter_tools(self._make_tools(), "research")
        names = [t["function"]["name"] for t in filtered]
        assert "web-search__index_site" not in names
        assert "web-search__web_search" in names


class TestIsToolAllowed:
    def test_allowed_via_wildcard(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("anything", "whatever", "default") is True

    def test_blocked_plugin(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("file-writer", "write_file", "research") is False

    def test_blocked_tool_within_allowed_plugin(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("web-search", "index_site", "research") is False
        assert svc.is_tool_allowed("web-search", "web_search", "research") is True

    def test_unknown_profile_allows_nothing(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("x", "y", "missing") is False


import importlib
from fastapi.testclient import TestClient


class TestProfileRouter:
    @pytest.fixture(scope="class")
    def client(self):
        os.environ["ENABLE_API_AUTH"] = "false"
        os.environ["RATE_LIMIT_RPM"] = "0"
        import api.middleware
        importlib.reload(api.middleware)
        import api.main
        importlib.reload(api.main)
        from api.main import app
        return TestClient(app)

    def test_list_profiles_endpoint(self, client):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert "default" in ids

    def test_get_profile_detail(self, client):
        resp = client.get("/api/profiles/default")
        assert resp.status_code == 200
        assert resp.json()["id"] == "default"

    def test_get_missing_profile_404(self, client):
        resp = client.get("/api/profiles/nonexistent")
        assert resp.status_code == 404

    def test_reload_profiles(self, client):
        resp = client.post("/api/profiles/reload")
        assert resp.status_code == 200
        assert "loaded" in resp.json()

    def test_active_default(self, client):
        resp = client.get("/api/profiles/active")
        assert resp.status_code == 200
        assert "default_profile_id" in resp.json()
