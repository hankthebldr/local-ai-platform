#!/usr/bin/env python3
"""LB2-U2 — prompt digest normalizer, discovery routes, hybrid recommender.

Covers the unit's verify list, with mocked HTTP throughout:
  - manifest-first diff: refresh pulls bodies ONLY for added/changed blob
    shas; unchanged records (and their notebook children) carry forward;
  - normalization: SKILL.md → template, commands/*.md → role prompt,
    notebooks → pointer-only parent + extracted prompt children;
  - GET /api/prompts/discover performs ZERO network calls and carries
    fetched_at (privacy: read-GETs serve the persisted digest only);
  - offline / rate-limited refresh fail-soft: the persisted digest survives
    and the remaining quota is surfaced;
  - install: permissive license copies into the USER layer with provenance
    sha in the sidecar (409 on repeat); proprietary/unknown/pointer-only
    hard-blocked 403; traversal ids rejected;
  - refresh/install/explain 401 without a key when auth is on; discover +
    recommend reads stay open;
  - recommend scorer: deterministic, per-factor breakdown, size-fit
    respects the model's context window;
  - Ask Enclave explain degrades to the deterministic order when the local
    model is unavailable (never 5xx).

Run:  pytest tests/test_prompt_digest.py -q
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from api.routers import prompts as prompts_router
from api.services import agentic_discovery as ad
from api.services import discovery_fetch as df
from api.services import prompt_digest as pd
from api.services import prompt_meta

REPO = "anthropics/claude-cookbooks"
HEAD1 = "a" * 40
HEAD2 = "b" * 40


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


@pytest.fixture
def layers(tmp_path, monkeypatch):
    """Isolated two-layer prompt store + isolated digest dir + config."""
    oob = tmp_path / "oob-prompts"
    user = tmp_path / "user-prompts"
    for sub in ("roles", "templates", "hooks"):
        (oob / sub).mkdir(parents=True)
    (oob / "roles" / "shipped_role.md").write_text(
        "# Shipped Role\nYou review {{ artifact }} carefully.", encoding="utf-8"
    )
    monkeypatch.setattr(prompts_router, "_OOB_ROOT", oob)
    monkeypatch.setattr(prompts_router, "_user_root", lambda: user)
    monkeypatch.setattr(df, "_DIGEST_DIR", tmp_path / "discovery")
    monkeypatch.setattr(ad, "_SOURCES_CONFIG_FILE", tmp_path / "sources.json")
    for var in ("ENCLAVE_GITHUB_TOKEN", "GITHUB_TOKEN", "ENCLAVE_SKILL_REPOS"):
        monkeypatch.delenv(var, raising=False)
    return {"oob": oob, "user": user, "tmp": tmp_path}


# ── Mocked GitHub for anthropics/claude-cookbooks ───────────────────────────


def _notebook_json():
    return json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "source": ["# Basics\n"]},
                {
                    "cell_type": "code",
                    "source": [
                        'system_prompt = """You are a meticulous XQL reviewer.\n',
                        "Always cite the rule ids you touch and explain each fix.\n",
                        '"""\n',
                        "x = 1\n",
                    ],
                },
                {
                    "cell_type": "code",
                    "source": ["short_prompt = '''too short'''\n"],
                },
            ]
        }
    )


class _FakeGitHub:
    """Minimal fake for repo_head + trees + raw fetches, with call logs."""

    def __init__(self, license_spdx="MIT"):
        self.head = HEAD1
        self.license = license_spdx
        self.blobs = {
            "registry.yaml": "r1",
            "skills/demo/SKILL.md": "s1",
            "commands/review.md": "c1",
            "notebooks/basic.ipynb": "n1",
        }
        self.bodies = {
            "registry.yaml": yaml.safe_dump(
                [
                    {"path": "skills/demo/SKILL.md", "title": "Demo Skill",
                     "tags": ["xql", "review"]},
                    {"path": "commands/review.md", "title": "Review Command",
                     "tags": ["review"]},
                    {"path": "notebooks/basic.ipynb", "title": "Basic Notebook",
                     "tags": ["cookbook"]},
                    {"path": "missing/nowhere.md", "title": "Ghost"},
                ]
            ),
            "skills/demo/SKILL.md": "---\nname: demo\n---\n\nUse five-part prompts.",
            "commands/review.md": "# Review\nReview the diff for regressions.",
            "notebooks/basic.ipynb": _notebook_json(),
        }
        self.raw_calls: list[str] = []
        self.rate_limited = False

    def get(self, url, **kwargs):
        from tests.test_discovery_fetch import FakeResponse

        if self.rate_limited and url.startswith(df.GITHUB_API):
            return FakeResponse(
                status_code=403, headers={"X-RateLimit-Remaining": "0"}
            )
        if url == f"{df.GITHUB_API}/repos/{REPO}":
            return FakeResponse(
                json_data={"default_branch": "main",
                           "license": {"spdx_id": self.license}},
                headers={"X-RateLimit-Remaining": "55"},
            )
        if url == f"{df.GITHUB_API}/repos/{REPO}/commits/main":
            return FakeResponse(
                json_data={"sha": self.head},
                headers={"X-RateLimit-Remaining": "54"},
            )
        if url == f"{df.GITHUB_API}/repos/{REPO}/git/trees/{self.head}":
            return FakeResponse(
                json_data={
                    "tree": [
                        {"path": p, "type": "blob", "sha": sha}
                        for p, sha in self.blobs.items()
                    ]
                },
                headers={"X-RateLimit-Remaining": "53"},
            )
        if url.startswith(f"{df.RAW_BASE}/{REPO}/{self.head}/"):
            path = url.split(f"{df.RAW_BASE}/{REPO}/{self.head}/", 1)[1]
            self.raw_calls.append(path)
            body = self.bodies.get(path)
            return FakeResponse(status_code=200 if body else 404, text=body or "")
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def github(layers, monkeypatch):
    fake = _FakeGitHub()
    monkeypatch.setattr(df.requests, "get", fake.get)
    monkeypatch.setattr(
        pd, "load_sources_config",
        lambda: {"prompt_digest_sources": [REPO], "github_token": ""},
    )
    return fake


# ── Normalization ───────────────────────────────────────────────────────────


def test_refresh_normalizes_all_record_kinds(github):
    doc = pd.refresh()
    recs = {r["id"]: r for r in doc["records"]}
    by_path = {r["source"]["path"]: r for r in doc["records"] if not r.get("parent")}

    skill = by_path["skills/demo/SKILL.md"]
    assert skill["prompt_kind"] == "template"
    assert skill["subkind"] == "skill-template"
    assert skill["body"].startswith("---\nname: demo")
    assert skill["license"] == "MIT"
    assert skill["content_sha"] == "s1"
    assert skill["source"]["ref"] == HEAD1
    assert skill["source"]["provenance"] == "first-party"
    assert skill["tags"] == ["xql", "review"]

    cmd = by_path["commands/review.md"]
    assert cmd["prompt_kind"] == "role"
    assert cmd["subkind"] == "command"

    nb = by_path["notebooks/basic.ipynb"]
    assert nb["subkind"] == "notebook"
    assert nb["body"] is None and nb["body_pointer"].endswith("basic.ipynb")
    children = [r for r in doc["records"] if r.get("parent") == nb["id"]]
    assert len(children) == 1  # short_prompt is below the reuse threshold
    assert "meticulous XQL reviewer" in children[0]["body"]
    assert children[0]["subkind"] == "notebook-prompt"

    # ghost manifest entry (not in the tree) is skipped, ids are _ID_RE-safe
    assert "missing/nowhere.md" not in by_path
    for rid in recs:
        assert prompts_router._ID_RE.match(rid), rid
    assert doc["rate_remaining"] == 54
    assert doc["sources"][0]["ok"] is True


def test_manifest_diff_fetches_only_changed_bodies(github):
    pd.refresh()
    first_children = [
        r["id"] for r in pd.read()["records"] if r.get("parent")
    ]
    github.raw_calls.clear()
    # one blob changes; everything else keeps its sha
    github.head = HEAD2
    github.blobs["commands/review.md"] = "c2"
    github.bodies["commands/review.md"] = "# Review v2\nNow with severity."
    doc = pd.refresh()

    # registry.yaml is the manifest (always consulted); the ONLY body pulled
    # is the changed record's.
    assert sorted(github.raw_calls) == ["commands/review.md", "registry.yaml"]
    changed = [r for r in doc["records"] if r["source"]["path"] == "commands/review.md"
               and not r.get("parent")][0]
    assert doc["diff"]["changed"] == [changed["id"]]
    assert doc["diff"]["added"] == [] and doc["diff"]["removed"] == []
    # unchanged notebook children carried forward untouched
    assert [r["id"] for r in doc["records"] if r.get("parent")] == first_children


def test_rate_limited_refresh_fails_soft_to_prior_digest(github):
    before = pd.refresh()
    github.rate_limited = True
    doc = pd.refresh()
    assert "rate limit" in (doc["sources"][0]["error"] or "")
    assert doc["rate_remaining"] == 0
    # prior records carried forward — a rate-limit never empties the digest
    assert {r["id"] for r in doc["records"]} == {r["id"] for r in before["records"]}
    # and the persisted file still serves them offline
    assert {r["id"] for r in pd.read()["records"]} == {
        r["id"] for r in before["records"]
    }


def test_unknown_source_skipped_honestly(github, monkeypatch):
    monkeypatch.setattr(
        pd, "load_sources_config",
        lambda: {"prompt_digest_sources": ["someone/random-repo"]},
    )
    doc = pd.refresh()
    assert doc["records"] == []
    assert "no prompt normalizer" in doc["sources"][0]["error"]


def test_proprietary_source_records_are_pointer_only(layers, monkeypatch):
    fake = _FakeGitHub(license_spdx="NOASSERTION")
    monkeypatch.setattr(df.requests, "get", fake.get)
    monkeypatch.setattr(
        pd, "load_sources_config", lambda: {"prompt_digest_sources": [REPO]}
    )
    doc = pd.refresh()
    for rec in doc["records"]:
        assert not rec.get("body"), rec["id"]
        assert rec["body_pointer"]


# ── Routes: read is open + zero-network; refresh/install gated ─────────────


def test_get_discover_zero_network_and_staleness_stamp(client, layers, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("GET /discover must never reach the network")

    monkeypatch.setattr(df.requests, "get", _boom)
    r = client.get("/api/prompts/discover")
    assert r.status_code == 200
    body = r.json()
    assert "fetched_at" in body and body["records"] == []

    # after a refresh the same GET serves the persisted digest offline
    fake = _FakeGitHub()
    monkeypatch.setattr(df.requests, "get", fake.get)
    monkeypatch.setattr(
        pd, "load_sources_config", lambda: {"prompt_digest_sources": [REPO]}
    )
    assert client.post("/api/prompts/discover/refresh").status_code == 200
    monkeypatch.setattr(df.requests, "get", _boom)
    r2 = client.get("/api/prompts/discover")
    assert r2.status_code == 200
    assert r2.json()["fetched_at"] is not None
    assert len(r2.json()["records"]) > 0


def test_install_copies_body_into_user_layer_with_provenance(client, github, layers):
    client_refresh = client.post("/api/prompts/discover/refresh")
    assert client_refresh.status_code == 200
    rec = next(
        r for r in pd.read()["records"]
        if r["source"]["path"] == "commands/review.md" and not r.get("parent")
    )
    r = client.post(
        f"/api/prompts/discover/{rec['id']}/install", json={"target_id": "review_cmd"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provenance"] == "user"
    assert body["source_sha"] == rec["content_sha"]
    assert body["source_id"] == rec["id"]
    p = layers["user"] / "roles" / "review_cmd.md"
    assert p.is_file()
    meta = prompt_meta.read_meta(p)
    assert meta["provenance"]["content_sha"] == rec["content_sha"]
    assert meta["provenance"]["repo"] == REPO
    assert meta["provenance"]["ref"] == HEAD1
    # 409 on repeat
    assert (
        client.post(
            f"/api/prompts/discover/{rec['id']}/install",
            json={"target_id": "review_cmd"},
        ).status_code
        == 409
    )


def test_install_template_lands_in_templates_dir(client, github, layers):
    client.post("/api/prompts/discover/refresh")
    rec = next(
        r for r in pd.read()["records"]
        if r["source"]["path"] == "skills/demo/SKILL.md"
    )
    r = client.post(f"/api/prompts/discover/{rec['id']}/install", json={})
    assert r.status_code == 201
    assert (layers["user"] / "templates" / f"{rec['id']}.jinja").is_file()


def test_install_blocks_non_permissive_license_403(client, layers, monkeypatch):
    fake = _FakeGitHub(license_spdx="NOASSERTION")
    monkeypatch.setattr(df.requests, "get", fake.get)
    monkeypatch.setattr(
        pd, "load_sources_config", lambda: {"prompt_digest_sources": [REPO]}
    )
    assert client.post("/api/prompts/discover/refresh").status_code == 200
    rec = next(
        r for r in pd.read()["records"]
        if r["source"]["path"] == "commands/review.md" and not r.get("parent")
    )
    r = client.post(f"/api/prompts/discover/{rec['id']}/install", json={})
    assert r.status_code == 403
    assert "license" in r.json()["detail"].lower()
    assert not (layers["user"] / "roles").exists() or not list(
        (layers["user"] / "roles").glob("*.md")
    )


def test_install_blocks_pointer_only_notebook_parent(client, github, layers):
    client.post("/api/prompts/discover/refresh")
    nb = next(
        r for r in pd.read()["records"] if r.get("subkind") == "notebook"
    )
    r = client.post(f"/api/prompts/discover/{nb['id']}/install", json={})
    assert r.status_code == 403
    assert "pointer-only" in r.json()["detail"]


def test_install_rejects_traversal_ids(client, github, layers):
    client.post("/api/prompts/discover/refresh")
    assert (
        client.post("/api/prompts/discover/..%2Fevil/install", json={}).status_code
        in (400, 404)
    )
    rec = next(r for r in pd.read()["records"] if r.get("body"))
    r = client.post(
        f"/api/prompts/discover/{rec['id']}/install",
        json={"target_id": "../escape"},
    )
    assert r.status_code == 400
    assert client.post(
        "/api/prompts/discover/no-such-record/install", json={}
    ).status_code == 404


def test_write_routes_401_with_auth_on_reads_stay_open(client, layers, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.post("/api/prompts/discover/refresh").status_code == 401
    assert (
        client.post("/api/prompts/discover/x/install", json={}).status_code == 401
    )
    assert (
        client.post("/api/prompts/recommend/explain", json={"task": "t"}).status_code
        == 401
    )
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    assert client.get("/api/prompts/discover").status_code == 200
    assert client.get("/api/prompts/recommend?task=x").status_code == 200


# ── Recommender: deterministic scorer + per-factor breakdown ───────────────


def _seed_meta(layers, pid, meta, kind="role", body="# R\nReview things."):
    sub = "roles" if kind == "role" else "templates"
    ext = ".md" if kind == "role" else ".jinja"
    p = layers["user"] / sub / f"{pid}{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    prompt_meta.write_meta(p, meta)
    return p


def test_recommend_scorer_deterministic_with_factor_breakdown(client, layers):
    _seed_meta(layers, "xql_reviewer",
               {"tags": ["xql", "review"], "model_fit": ["reasoning"],
                "token_estimate": 100})
    _seed_meta(layers, "poet", {"tags": ["poetry"], "token_estimate": 100})
    r1 = client.get("/api/prompts/recommend?task=review%20xql%20rules")
    r2 = client.get("/api/prompts/recommend?task=review%20xql%20rules")
    assert r1.status_code == 200
    assert r1.json() == r2.json(), "scorer must be deterministic"
    results = r1.json()["results"]
    assert results[0]["id"] == "xql_reviewer"
    top = results[0]
    assert set(top["factors"]) == {"task_tags", "model_fit", "size_fit"}
    assert "xql" in top["factors"]["task_tags"]["matched"]
    ids = [x["id"] for x in results]
    assert ids.index("xql_reviewer") < ids.index("poet")


def test_recommend_size_fit_respects_context_window(layers, monkeypatch):
    monkeypatch.setattr(
        pd, "model_profile",
        lambda m: {"model": m, "role_classes": ["reasoning"],
                   "context_tokens": 4096, "known": True},
    )
    prompts = [
        {"id": "small", "kind": "role", "name": "Small", "tags": ["review"],
         "model_fit": [], "token_estimate": 500},
        {"id": "huge", "kind": "role", "name": "Huge", "tags": ["review"],
         "model_fit": [], "token_estimate": 50_000},
    ]
    out = pd.score_prompts(prompts, task="review", model="anything")
    by_id = {r["id"]: r for r in out["results"]}
    assert by_id["small"]["factors"]["size_fit"]["score"] == 1.0
    assert by_id["huge"]["factors"]["size_fit"]["score"] == 0.0
    assert by_id["small"]["score"] > by_id["huge"]["score"]
    assert by_id["huge"]["factors"]["size_fit"]["context_tokens"] == 4096


def test_recommend_model_fit_uses_role_classes_and_pins(monkeypatch):
    monkeypatch.setattr(
        pd, "model_profile",
        lambda m: {"model": m, "role_classes": ["coding"],
                   "context_tokens": None, "known": True},
    )
    prompts = [
        {"id": "class_match", "kind": "role", "name": "A", "tags": [],
         "model_fit": ["coding"], "token_estimate": 10},
        {"id": "pin_match", "kind": "role", "name": "B", "tags": [],
         "model_fit": ["qwen2.5-coder"], "token_estimate": 10},
        {"id": "no_match", "kind": "role", "name": "C", "tags": [],
         "model_fit": ["uncensored"], "token_estimate": 10},
    ]
    out = pd.score_prompts(prompts, task="", model="qwen2.5-coder:7b")
    by_id = {r["id"]: r for r in out["results"]}
    assert by_id["pin_match"]["factors"]["model_fit"]["score"] == 1.0
    assert by_id["class_match"]["factors"]["model_fit"]["score"] == 0.5
    assert by_id["no_match"]["factors"]["model_fit"]["score"] == 0.0


def test_model_profile_reads_registry_and_benchmarks():
    profile = pd.model_profile("dolphin3")
    assert profile["known"] is True
    assert profile["context_tokens"] == 128 * 1024
    assert "uncensored" in profile["role_classes"]
    unknown = pd.model_profile("no-such-model-xyz")
    assert unknown == {
        "model": "no-such-model-xyz", "role_classes": [],
        "context_tokens": None, "known": False,
    }


def test_explain_degrades_to_deterministic_when_model_unavailable(
    client, layers, monkeypatch
):
    _seed_meta(layers, "xql_reviewer",
               {"tags": ["xql", "review"], "token_estimate": 100})
    from api.services.model_resolver import ModelResolver

    def _raise(self, **kwargs):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(ModelResolver, "resolve", _raise)
    r = client.post(
        "/api/prompts/recommend/explain", json={"task": "review xql rules"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["explained"] is False
    assert body["items"][0]["id"] == "xql_reviewer"
    assert body["items"][0]["reason"]
