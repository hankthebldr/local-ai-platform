#!/usr/bin/env python3
"""LB1-U1 — test backend routes.

Covers the spec's verify list:
  - all new routes 401 without a key when auth is on, INCLUDING the
    newly-gated POST /api/inventory/settings/search (secrets write);
  - POST /api/plugins/{id}/tools/{tool_id}/test merges config_overrides
    over saved settings for the call only (never persisted), fills declared
    tool params from the merged config, reports latency + the sandbox=None
    divergence, and never echoes secret values;
  - POST /api/skills/test dry-runs trigger matching and returns the EXACT
    text the skill_injector builtin would inject;
  - POST /api/inventory/warm rides the runner-service explicit-load path,
    returns {runner, load_duration_ms}, and reports no-op runners (pinned
    vLLM) so the UI can disable-with-reason;
  - POST /api/workflows/test-step accepts skills[] with router-side
    injection (parity vs the builtin pinned in tests/parity).
"""

from __future__ import annotations

import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient

import api.routers.plugins as plugins_router
from api.hooks.builtins import skill_injector
from api.services import search_service
from api.services.prompt_composer import ComposedPrompt
from api.services.runner import LoadResult, ModelInfo, RunnerKind
from api.services.runner_registry import RunnerRegistry, _set_current


@pytest.fixture(scope="module")
def client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


# ── Stub plugin service (chat-path shape: plugins carry skills + tools) ────


SEARCH_SKILL_BODY = "Always cross-check at least two sources."
NOTES_SKILL_BODY = "Prefer primary sources."


class StubPluginService:
    def __init__(self):
        self.calls = []
        self._plugins = {
            "websearch": {
                "id": "websearch",
                "name": "Web Search",
                "origin": "system",
                "skills": [
                    {
                        "id": "search-strategy",
                        "name": "Search Strategy",
                        "content": SEARCH_SKILL_BODY,
                        "inject": "system",
                        "triggers": [{"keyword": "search"}, {"keyword": "look up"}],
                    },
                    {
                        "id": "context-notes",
                        "name": "Context Notes",
                        "content": NOTES_SKILL_BODY,
                        "inject": "messages",
                        "triggers": [{"keyword": "notes"}],
                    },
                ],
                "tools": [
                    {
                        "id": "web_search",
                        "description": "Search the web",
                        "parameters": {
                            "query": {"type": "string", "required": True},
                            "max_results": {"type": "integer", "default": 5},
                        },
                    }
                ],
            }
        }

    def get_plugin(self, plugin_id):
        return self._plugins.get(plugin_id)

    def has_tool(self, plugin_id, tool_id):
        plugin = self._plugins.get(plugin_id) or {}
        return any(t["id"] == tool_id for t in plugin.get("tools", []))

    def get_skill(self, plugin_id, skill_id):
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        for skill in plugin.get("skills", []):
            if skill["id"] == skill_id:
                return skill
        return None

    def get_skills(self, user_message):
        matched = []
        msg_lower = (user_message or "").lower()
        for plugin in self._plugins.values():
            for skill in plugin["skills"]:
                for trigger in skill.get("triggers", []):
                    kw = trigger.get("keyword", "")
                    if kw and kw.lower() in msg_lower:
                        matched.append(skill)
                        break
        return matched

    def call_tool(self, plugin_id, tool_id, params, sandbox=None):
        self.calls.append(
            {
                "plugin_id": plugin_id,
                "tool_id": tool_id,
                "params": dict(params),
                "sandbox": sandbox,
            }
        )
        return {"ok": True, "total": 1}


@pytest.fixture()
def stub_service(monkeypatch):
    stub = StubPluginService()
    monkeypatch.setattr(plugins_router, "plugin_service", stub)
    return stub


@pytest.fixture()
def isolated_search_settings(tmp_path, monkeypatch):
    """Point the search-settings store at a tmp file seeded with max_results=7."""
    path = tmp_path / "search_settings.json"
    path.write_text(json.dumps({"max_results": 7}))
    monkeypatch.setattr(search_service, "_SEARCH_CONFIG_FILE", path)
    monkeypatch.setattr(search_service, "_CONFIG_DIR", tmp_path)
    for var in ("SEARXNG_URL", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return path


# ── Auth: every new route 401s without a key when auth is on ──────────────


def test_new_routes_401_with_auth_on_and_no_key(client, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    posts = [
        ("/api/plugins/websearch/tools/web_search/test", {"params": {}}),
        ("/api/skills/test", {"message": "search"}),
        ("/api/inventory/warm", {"model": "m"}),
        ("/api/inventory/settings/search", {"max_results": 3}),  # secrets gate (F3)
    ]
    for path, body in posts:
        r = client.post(path, json=body)
        assert r.status_code == 401, f"{path} should 401 without a master key"


# ── Plugin tool test route ─────────────────────────────────────────────────


def test_tool_test_fills_params_from_saved_settings(
    client, stub_service, isolated_search_settings
):
    r = client.post(
        "/api/plugins/websearch/tools/web_search/test",
        json={"params": {"query": "hello"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["result"] == {"ok": True, "total": 1}
    assert isinstance(body["latency_ms"], (int, float))
    # Saved settings (max_results=7) filled the declared tool param.
    call = stub_service.calls[-1]
    assert call["params"] == {"query": "hello", "max_results": 7}
    # sandbox=None divergence surfaced, never hidden.
    assert call["sandbox"] is None
    assert body["meta"]["sandbox"] is None
    assert "sandbox" in body["meta"]["sandbox_divergence"]


def test_tool_test_overrides_merge_over_saved_and_never_persist(
    client, stub_service, isolated_search_settings
):
    before = isolated_search_settings.read_text()
    r = client.post(
        "/api/plugins/websearch/tools/web_search/test",
        json={"params": {"query": "hello"}, "config_overrides": {"max_results": 3}},
    )
    assert r.status_code == 200
    body = r.json()
    # Override (3) beat the saved setting (7) for this call only.
    assert stub_service.calls[-1]["params"] == {"query": "hello", "max_results": 3}
    assert body["meta"]["overrides_applied"] == ["max_results"]
    assert body["meta"]["persisted"] is False
    # Nothing was written to the saved settings store.
    assert isolated_search_settings.read_text() == before
    assert json.loads(isolated_search_settings.read_text()) == {"max_results": 7}


def test_tool_test_explicit_params_beat_config(client, stub_service, isolated_search_settings):
    client.post(
        "/api/plugins/websearch/tools/web_search/test",
        json={
            "params": {"query": "hello", "max_results": 9},
            "config_overrides": {"max_results": 3},
        },
    )
    assert stub_service.calls[-1]["params"] == {"query": "hello", "max_results": 9}


def test_tool_test_never_echoes_secret_values(
    client, stub_service, isolated_search_settings
):
    secret = "sk-sekrit-9999"
    r = client.post(
        "/api/plugins/websearch/tools/web_search/test",
        json={"params": {"query": "q"}, "config_overrides": {"brave_api_key": secret}},
    )
    assert r.status_code == 200
    assert secret not in r.text
    # Key NAME may be reported; value never.
    assert "brave_api_key" in r.json()["meta"]["overrides_applied"]
    # And the override did not persist to the settings store.
    assert json.loads(isolated_search_settings.read_text()) == {"max_results": 7}


def test_tool_test_404s(client, stub_service):
    assert (
        client.post("/api/plugins/nope/tools/web_search/test", json={}).status_code
        == 404
    )
    assert (
        client.post("/api/plugins/websearch/tools/nope/test", json={}).status_code
        == 404
    )


def test_tool_test_execution_failure_is_status_error(client, stub_service, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Tool execution failed: kaput")

    monkeypatch.setattr(stub_service, "call_tool", boom)
    r = client.post(
        "/api/plugins/websearch/tools/web_search/test", json={"params": {"query": "q"}}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "kaput" in body["error"]
    assert isinstance(body["latency_ms"], (int, float))


# ── Skills trigger dry-run ─────────────────────────────────────────────────


def test_skills_dry_run_keyword_matching(client, stub_service):
    r = client.post("/api/skills/test", json={"message": "please search the web"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    rec = body["matched"][0]
    assert rec["plugin_id"] == "websearch"
    assert rec["skill_id"] == "search-strategy"
    assert rec["trigger"] == "keyword"
    assert rec["trigger_match"] == "search"
    assert rec["keywords"] == ["search", "look up"]
    assert rec["injected_into"] == "system"
    assert rec["injected_text"] == SEARCH_SKILL_BODY + "\n\n"
    assert rec["injected_chars"] == len(SEARCH_SKILL_BODY)


def test_skills_dry_run_text_matches_builtin_injection(client, stub_service):
    """The dry-run's injected_text is EXACTLY what skill_injector writes."""
    r = client.post("/api/skills/test", json={"message": "please search the web"})
    injected = r.json()["matched"][0]["injected_text"]

    saved = skill_injector._plugin_service
    skill_injector.set_plugin_service(stub_service)
    try:
        prompt = ComposedPrompt(system="SYS", user="please search the web")
        ctx_step = type("S", (), {"id": "s1", "skills": []})()
        from api.services.hook_bus import HookContext

        skill_injector.SkillInjectorHook(mode="auto")(
            HookContext(step=ctx_step, prompt=prompt)
        )
    finally:
        skill_injector.set_plugin_service(saved)
    assert prompt.system == injected + "SYS"


def test_skills_dry_run_explicit_lookup(client, stub_service):
    r = client.post(
        "/api/skills/test",
        json={"message": "", "plugin_id": "websearch", "skill_id": "context-notes"},
    )
    assert r.status_code == 200
    rec = r.json()["matched"][0]
    assert rec["trigger"] == "explicit"
    assert rec["injected_into"] == "messages"
    assert rec["injected_text"] == "\n\n" + NOTES_SKILL_BODY


def test_skills_dry_run_unknown_skill_404(client, stub_service):
    r = client.post(
        "/api/skills/test",
        json={"message": "", "plugin_id": "websearch", "skill_id": "nope"},
    )
    assert r.status_code == 404


def test_skills_dry_run_no_match_is_empty(client, stub_service):
    r = client.post("/api/skills/test", json={"message": "unrelated question"})
    assert r.status_code == 200
    assert r.json() == {"message": "unrelated question", "matched": [], "count": 0}


# ── Inventory warm ─────────────────────────────────────────────────────────


class FakeOllamaRunner:
    name = RunnerKind.OLLAMA
    supports_hot_swap = True

    def list_models(self):
        return []

    def load(self, model_id):
        return LoadResult(model=model_id, loaded=True, load_seconds=1.234)


class FakeVllmRunner:
    name = RunnerKind.VLLM
    supports_hot_swap = False

    def list_models(self):
        return [ModelInfo(id="qwen3-coder-nvfp4")]

    def load(self, model_id):
        return LoadResult(
            model=model_id, loaded=True, load_seconds=0.0, reason="vllm_pinned_server"
        )


@pytest.fixture()
def fake_registry():
    import api.services.runner_registry as rr

    saved = rr._current_registry
    reg = RunnerRegistry()
    reg.register(FakeOllamaRunner())
    reg.register(FakeVllmRunner())
    _set_current(reg)
    yield reg
    _set_current(saved)


def test_warm_rides_runner_load_path(client, fake_registry):
    r = client.post("/api/inventory/warm", json={"model": "llama3.2:3b"})
    assert r.status_code == 200
    body = r.json()
    assert body["runner"] == "ollama"
    assert body["loaded"] is True
    assert body["load_duration_ms"] == 1234.0
    assert body["noop"] is False


def test_warm_reports_vllm_pinned_as_noop(client, fake_registry):
    """The flagship NVFP4 model must not get a dead Warm button — the pane
    disables-with-reason off this capability signal."""
    r = client.post("/api/inventory/warm", json={"model": "qwen3-coder-nvfp4"})
    assert r.status_code == 200
    body = r.json()
    assert body["runner"] == "vllm"
    assert body["noop"] is True
    assert body["reason"] == "vllm_pinned_server"
    assert body["load_duration_ms"] == 0.0


def test_warm_503_when_registry_uninitialised(client):
    import api.services.runner_registry as rr

    saved = rr._current_registry
    _set_current(None)
    try:
        r = client.post("/api/inventory/warm", json={"model": "m"})
        assert r.status_code == 503
    finally:
        _set_current(saved)


# ── test-step skills[] router-side injection ───────────────────────────────


class FakeChatOllama:
    def __init__(self):
        self.chats = []

    def chat(self, model, messages, temperature, max_tokens):
        self.chats.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return {"content": "ok", "prompt_eval_count": 3, "eval_count": 4}


class FakeResolver:
    def __init__(self, ollama):
        pass

    def resolve(self, model=None, role=None, default_role=None):
        return model or "fake-model"


@pytest.fixture()
def fake_llm(monkeypatch, stub_service):
    import api.routers.workflows as workflows_router
    import api.services.model_resolver as model_resolver_mod

    fake = FakeChatOllama()
    monkeypatch.setattr(workflows_router, "get_ollama_service", lambda: fake)
    monkeypatch.setattr(model_resolver_mod, "ModelResolver", FakeResolver)
    saved = skill_injector._plugin_service
    skill_injector.set_plugin_service(stub_service)
    yield fake
    skill_injector.set_plugin_service(saved)


def test_test_step_injects_explicit_skills(client, fake_llm):
    r = client.post(
        "/api/workflows/test-step",
        json={
            "step": {"id": "s1", "system_prompt": "SYS", "model": "fake-model"},
            "user_message": "hi",
            "skills": ["websearch.search-strategy", "websearch.context-notes"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    msgs = fake_llm.chats[-1]["messages"]
    # Exact skill_injector semantics: system body prepended, messages body appended.
    assert msgs[0] == {
        "role": "system",
        "content": SEARCH_SKILL_BODY + "\n\n" + "SYS",
    }
    assert msgs[1] == {"role": "user", "content": "hi" + "\n\n" + NOTES_SKILL_BODY}
    acts = body["skills_activated"]
    assert [(a["plugin_id"], a["skill_id"], a["trigger"]) for a in acts] == [
        ("websearch", "search-strategy", "explicit"),
        ("websearch", "context-notes", "explicit"),
    ]
    assert acts[0]["injected_into"] == "system"
    assert acts[1]["injected_into"] == "messages"


def test_test_step_without_skills_is_unchanged(client, fake_llm):
    r = client.post(
        "/api/workflows/test-step",
        json={
            "step": {"id": "s1", "system_prompt": "SYS", "model": "fake-model"},
            "user_message": "hi",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "skills_activated" not in body  # only-add: payload unchanged
    msgs = fake_llm.chats[-1]["messages"]
    assert msgs == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
    ]


def test_test_step_sends_temperature_and_max_tokens(client, fake_llm):
    client.post(
        "/api/workflows/test-step",
        json={
            "step": {"id": "s1", "system_prompt": "SYS", "model": "fake-model"},
            "user_message": "hi",
            "temperature": 0.1,
            "max_tokens": 64,
        },
    )
    assert fake_llm.chats[-1]["temperature"] == 0.1
    assert fake_llm.chats[-1]["max_tokens"] == 64
