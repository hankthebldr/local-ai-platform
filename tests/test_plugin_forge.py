#!/usr/bin/env python3
"""LB5-U3 — plugin creation wizard backend (local-model forge).

Covers the spec's verify list:
  - fallback spec when the local model is unavailable (one skill, zero
    tools, source='fallback' — the wizard never 5xxs on a cold box);
  - model-drafted spec parsed tolerantly (chatty JSON, id slugging,
    skills-only default drops proposed tools);
  - generate materializes plugin.yaml + skills/*.md (+ tools/*.py stubs
    only behind the explicit opt-in, with an honest omission warning);
  - install 409 on an existing id (both layers);
  - containment rejects escaping file paths (../, absolute, backslash,
    dot segments, bad charset) — this repo had a real glob-traversal
    incident, so every file-writing route gets explicit tests;
  - bad plugin/tool/skill ids rejected;
  - denylist lint flags forbidden imports (and dynamic-exec builtins) in
    wizard-edited *.py at install time;
  - installed plugin is visible after scan_plugins on the live singleton
    (GET detail + chat-path trigger match);
  - all three scaffold routes 401 with auth on and no key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routers.plugins as plugins_router
from api.models.plugin_models import (
    PluginSkillDraft,
    PluginSpecDraft,
    PluginToolDraft,
)
from api.services.plugin_forge import (
    DENYLISTED_IMPORTS,
    PluginForgeService,
    lint_tool_code,
)
from api.services.plugin_service import PluginService


# ── Ollama stubs (nothing in this file talks to a live model) ───────────────


class _DeadOllama:
    """Model unavailable — every call raises (the cold-box path)."""

    def list_models(self):
        raise RuntimeError("ollama is down")

    def chat(self, **kwargs):
        raise RuntimeError("ollama is down")


class _JsonOllama:
    """Model returns a canned (chatty) response wrapping a JSON spec."""

    def __init__(self, payload: dict):
        self._payload = payload

    def list_models(self):
        return [{"name": "qwen3-test:8b"}]

    def chat(self, **kwargs):
        return {"content": "Sure! Here is the spec:\n" + json.dumps(self._payload)}


MODEL_SPEC = {
    "id": "Log Triage!!",  # deliberately messy — must slug to log-triage
    "name": "Log Triage",
    "description": "Coach chat sessions on triaging noisy logs.",
    "skills": [
        {
            "id": "Triage Guide",
            "name": "Triage guide",
            "description": "How to triage.",
            "triggers": ["triage", "Noisy Logs"],
            "inject": "system",
            "body": "Start from the loudest source.",
        }
    ],
    "tools": [
        {
            "id": "count-lines",
            "description": "Count matching lines in a local file.",
            "parameters": {
                "pattern": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False},
            },
        }
    ],
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Real two-layer PluginService on the router singleton + dead model."""
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    system.mkdir(parents=True)
    user.mkdir(parents=True)
    svc = PluginService(system_dir=system, user_dir=user)
    svc.scan_plugins()
    monkeypatch.setattr(plugins_router, "plugin_service", svc)
    monkeypatch.setattr(plugins_router, "OllamaService", lambda *a, **k: _DeadOllama())

    app = FastAPI()
    app.include_router(plugins_router.router)
    return TestClient(app), svc, user


def _spec_body(client, description="Help triage noisy syslog output", **kw):
    payload = {"description": description}
    payload.update(kw)
    r = client.post("/api/plugins/scaffold/spec", json=payload)
    assert r.status_code == 200
    return r.json()


def _generate(client, spec, include_tools=False):
    r = client.post(
        "/api/plugins/scaffold/generate",
        json={"spec": spec, "include_tools": include_tools},
    )
    assert r.status_code == 200
    return r.json()


# ── Spec draft ──────────────────────────────────────────────────────────────


def test_fallback_spec_when_model_unavailable(env):
    client, _, _ = env
    spec = _spec_body(client, name="Syslog Helper")
    assert spec["source"] == "fallback"
    assert len(spec["skills"]) == 1  # one skill …
    assert spec["tools"] == []  # … zero tools
    assert spec["id"] == "syslog-helper"
    sk = spec["skills"][0]
    assert sk["triggers"]  # deterministic keyword triggers
    assert "triage" in " ".join(sk["triggers"])


def test_model_spec_parsed_and_ids_slugged(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(
        plugins_router, "OllamaService", lambda *a, **k: _JsonOllama(MODEL_SPEC)
    )
    spec = _spec_body(client, allow_tools=True)
    assert spec["source"] == "model"
    assert spec["id"] == "log-triage"
    assert spec["skills"][0]["id"] == "triage-guide"
    assert spec["skills"][0]["triggers"] == ["triage", "noisy logs"]
    assert [t["id"] for t in spec["tools"]] == ["count-lines"]


def test_skills_only_default_drops_model_proposed_tools(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(
        plugins_router, "OllamaService", lambda *a, **k: _JsonOllama(MODEL_SPEC)
    )
    spec = _spec_body(client)  # allow_tools defaults to False
    assert spec["tools"] == []


def test_spec_requires_description(env):
    client, _, _ = env
    r = client.post("/api/plugins/scaffold/spec", json={"description": "   "})
    assert r.status_code == 400


# ── Generate ────────────────────────────────────────────────────────────────


def _model_draft(with_tools=True):
    forge = PluginForgeService(_JsonOllama(MODEL_SPEC))
    return forge.draft_spec("triage logs", allow_tools=with_tools).model_dump()


def test_generate_materializes_manifest_and_skills(env):
    client, _, _ = env
    out = _generate(client, _model_draft(with_tools=False))
    paths = [f["path"] for f in out["files"]]
    assert paths[0] == "plugin.yaml"
    assert "skills/triage-guide.md" in paths
    assert not any(p.endswith(".py") for p in paths)
    manifest = yaml.safe_load(out["files"][0]["content"])
    assert manifest["id"] == "log-triage"
    assert manifest["version"] == "0.1.0"
    assert manifest["skills"][0]["file"] == "skills/triage-guide.md"
    assert manifest["skills"][0]["triggers"][0] == {"keyword": "triage"}


def test_generate_tools_are_opt_in_with_warning(env):
    client, _, _ = env
    draft = _model_draft(with_tools=True)
    # opt-in NOT re-confirmed at generate time → tools omitted, honest warning
    out = _generate(client, draft, include_tools=False)
    assert out["tools_included"] is False
    assert any("opt-in" in w for w in out["warnings"])
    assert not any(f["path"].endswith(".py") for f in out["files"])
    # explicit opt-in → constrained stub, lint-clean, required args first
    out = _generate(client, draft, include_tools=True)
    assert out["tools_included"] is True
    stub = next(f for f in out["files"] if f["path"] == "tools/count_lines.py")
    assert "def execute(pattern, limit=None, **kwargs):" in stub["content"]
    assert lint_tool_code(stub["content"]) == []


def test_generate_rejects_bad_ids(env):
    client, _, _ = env
    bad = _model_draft(with_tools=False)
    bad["id"] = "../evil"
    r = client.post(
        "/api/plugins/scaffold/generate", json={"spec": bad, "include_tools": False}
    )
    assert r.status_code == 400


# ── Denylist lint ───────────────────────────────────────────────────────────


def test_lint_flags_every_denylisted_import():
    for mod in sorted(DENYLISTED_IMPORTS):
        assert lint_tool_code(f"import {mod}\n"), mod
        assert lint_tool_code(f"from {mod} import x\n"), mod
    assert lint_tool_code("import subprocess.run\n")  # dotted root
    assert lint_tool_code("x = eval('1')\n")  # dynamic exec builtins
    assert lint_tool_code("__import__('subprocess')\n")
    assert lint_tool_code("def f(:\n")  # unparseable = violation
    assert lint_tool_code("import json\nfrom pathlib import Path\n") == []


def test_install_rejects_denylisted_imports_in_edited_tool(env):
    client, _, user = env
    out = _generate(client, _model_draft(with_tools=True), include_tools=True)
    # the wizard lets the operator edit any file before install — an edit
    # that sneaks in a forbidden import must still be caught server-side
    for f in out["files"]:
        if f["path"].endswith(".py"):
            f["content"] = "import subprocess\n\ndef execute(**kwargs):\n    return {}\n"
    r = client.post("/api/plugins/scaffold/install", json=out)
    assert r.status_code == 400
    assert "subprocess" in r.json()["detail"]
    assert not (user / "log-triage").exists()  # nothing was written


# ── Install ─────────────────────────────────────────────────────────────────


def _install(client, out):
    return client.post("/api/plugins/scaffold/install", json=out)


def test_install_registers_plugin_on_live_singleton(env):
    client, svc, user = env
    out = _generate(client, _model_draft(with_tools=True), include_tools=True)
    r = _install(client, out)
    assert r.status_code == 200
    body = r.json()
    assert body["installed"] == "log-triage"
    assert body["plugin"]["layer"] == "user"
    # visible after scan_plugins: files on disk, detail served, chat-path match
    assert (user / "log-triage" / "plugin.yaml").exists()
    assert (user / "log-triage" / "skills" / "triage-guide.md").exists()
    assert client.get("/api/plugins/log-triage").status_code == 200
    assert svc.has_tool("log-triage", "count-lines")
    matched = svc.get_skills("please triage this mess")
    assert any("loudest source" in s["content"] for s in matched)


def test_install_409_on_existing_id(env):
    client, _, _ = env
    out = _generate(client, _model_draft(with_tools=False))
    assert _install(client, out).status_code == 200
    r = _install(client, out)
    assert r.status_code == 409
    assert "log-triage" in r.json()["detail"]


def test_install_409_on_existing_user_dir_even_unscanned(env):
    client, _, user = env
    (user / "log-triage").mkdir()  # dir exists but not (yet) discoverable
    out = _generate(client, _model_draft(with_tools=False))
    assert _install(client, out).status_code == 409


def test_install_containment_rejects_escaping_paths(env, tmp_path):
    client, _, user = env
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    base = _generate(client, _model_draft(with_tools=False))
    for bad in (
        "../evil.md",
        "/etc/passwd",
        "skills/../../evil.md",
        "skills\\evil.md",
        "skills/./evil.md",
        "skills/a b.md",
        "skills/héllo.md",
    ):
        out = json.loads(json.dumps(base))
        out["files"].append({"path": bad, "content": "pwn"})
        r = _install(client, out)
        assert r.status_code == 400, f"{bad!r} should be rejected"
        assert not (user / "log-triage").exists(), f"{bad!r} wrote files"
    assert outside.read_text() == "secret"


def test_install_rejects_bad_plugin_id_and_manifest_mismatch(env):
    client, _, _ = env
    base = _generate(client, _model_draft(with_tools=False))
    for bad_id in ("../up", "a/b", "a b", "", "-lead"):
        out = json.loads(json.dumps(base))
        out["plugin_id"] = bad_id
        assert _install(client, out).status_code == 400, repr(bad_id)
    # manifest id must match the install id
    out = json.loads(json.dumps(base))
    out["plugin_id"] = "other-id"
    assert _install(client, out).status_code == 400
    # manifest must be present and a mapping
    out = json.loads(json.dumps(base))
    out["files"] = [f for f in out["files"] if f["path"] != "plugin.yaml"]
    assert _install(client, out).status_code == 400
    out = json.loads(json.dumps(base))
    out["files"][0]["content"] = "just a string"
    assert _install(client, out).status_code == 400


def test_install_rejects_bad_manifest_entry_ids(env):
    client, _, _ = env
    out = _generate(client, _model_draft(with_tools=False))
    manifest = yaml.safe_load(out["files"][0]["content"])
    manifest["skills"].append({"id": "../evil", "file": "skills/evil.md"})
    out["files"][0]["content"] = yaml.safe_dump(manifest, sort_keys=False)
    r = _install(client, out)
    assert r.status_code == 400


# ── Fallback spec is installable end-to-end (cold-box wizard path) ─────────


def test_cold_box_end_to_end(env):
    client, svc, _ = env
    spec = _spec_body(client, description="Guide operators through NVFP4 model fit")
    out = _generate(client, spec)
    assert _install(client, out).status_code == 200
    assert svc.has_plugin(spec["id"])


# ── Deployment layer late-binding (live-server forge prerequisite) ─────────


def test_user_layer_late_binds_after_deployment_startup(tmp_path, monkeypatch):
    """plugins.py builds the service singleton at import time — BEFORE
    api/main.py's startup event installs the deployment singleton. The
    auto-resolve path must retry lazily or a live server has no writable
    user layer and every forge install 500s."""
    import types

    import api.services.deployment as dep

    monkeypatch.setattr(dep, "_current_deployment", None)
    svc = PluginService()  # auto-resolve path, pre-startup
    assert svc.user_dir is None
    # startup runs detect_deployment() → the singleton appears
    fake = types.SimpleNamespace(
        system_storage_root=tmp_path / "sys", user_storage_root=tmp_path / "usr"
    )
    monkeypatch.setattr(dep, "_current_deployment", fake)
    assert svc.user_dir == tmp_path / "usr" / "plugins"
    # …and an explicitly-constructed service is never rebound
    pinned = PluginService(system_dir=tmp_path / "a", user_dir=tmp_path / "b")
    assert pinned.user_dir == tmp_path / "b"


# ── Auth gate ───────────────────────────────────────────────────────────────


def test_scaffold_routes_401_with_auth_on_and_no_key(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert (
        client.post(
            "/api/plugins/scaffold/spec", json={"description": "x"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/plugins/scaffold/generate",
            json={"spec": {"id": "x", "skills": [], "tools": []}},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/plugins/scaffold/install",
            json={"plugin_id": "x", "files": []},
        ).status_code
        == 401
    )
