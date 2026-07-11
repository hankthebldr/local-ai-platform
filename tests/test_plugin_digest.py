#!/usr/bin/env python3
"""LB5-U1 — Claude marketplaces plugin digest provider.

Covers the unit's verify list, with mocked HTTP throughout and BOTH manifest
shapes in the fixtures (critique F13 — no pinned source exposes a repo-root
marketplace.json):
  - manifest resolution ladder: ``.claude-plugin/marketplace.json`` first,
    per-plugin ``**/.claude-plugin/plugin.json`` enumeration as fallback;
  - pointer-only records: per-record license (surfaced before any import),
    component counts, SKILL.md import pointers, version-resolution ladder
    (declared > sha-pinned > unknown);
  - digest persisted ATOMICALLY to data/discovery/plugin_digest.json;
  - offline reads serve the last digest with ZERO network (the registered
    provider fetch() is a digest read — cache-miss GETs stay offline);
  - added/changed sha diffing vs the prior file;
  - malformed manifest / rate limit fail soft to the persisted digest;
  - hostile manifest source paths degrade (no traversal into counts/urls);
  - refresh runs ONLY behind the master-key gated POST
    /api/discover/claude-marketplaces/refresh (401 with auth on).

Run:  pytest tests/test_plugin_digest.py -q
"""

from __future__ import annotations

import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from api.routers import prompts as prompts_router
from api.services import agentic_discovery as ad
from api.services import discovery_fetch as df
from api.services.discovery_providers import claude_marketplaces as cm
from tests.test_discovery_fetch import FakeResponse

REPO_MKT = "anthropics/claude-plugins-official"    # marketplace.json shape
REPO_KWP = "anthropics/knowledge-work-plugins"     # plugin.json fallback shape
HEAD_MKT = "a" * 40
HEAD_KWP = "b" * 40


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
def isolated(tmp_path, monkeypatch):
    """Isolated digest dir + sources config + cold provider cache."""
    monkeypatch.setattr(df, "_DIGEST_DIR", tmp_path / "discovery")
    monkeypatch.setattr(ad, "_SOURCES_CONFIG_FILE", tmp_path / "sources.json")
    for var in ("ENCLAVE_GITHUB_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    entry = ad._REGISTRY[cm.SOURCE]
    entry._cached = None
    entry._fetched_at = 0.0
    return tmp_path


# ── Mocked GitHub: both manifest shapes ─────────────────────────────────────


def _marketplace_json():
    return {
        "name": "official",
        "plugins": [
            {
                "name": "alpha",
                "source": "./plugins/alpha",
                "description": "Alpha productivity bundle",
                "version": "1.2.0",
                "category": "productivity",
                "license": "MIT",
                "keywords": ["notes", "tasks"],
            },
            {   # external source repo — counts honestly unknown
                "name": "beta",
                "source": {"source": "github", "repo": "octo/beta-plugin"},
                "description": "Beta from an external repo",
            },
            {   # hostile source path — must degrade, never traverse
                "name": "evil",
                "source": "../../etc",
                "description": "hostile manifest path",
            },
        ],
    }


class _FakeHub:
    """Two-repo fake for repo_head + trees + raw fetches, with call logs."""

    def __init__(self):
        self.rate_limited = False
        self.raw_calls: list[str] = []
        self.repos = {
            REPO_MKT: {
                "head": HEAD_MKT,
                "license": "MIT",
                "blobs": {
                    ".claude-plugin/marketplace.json": "m1",
                    "plugins/alpha/commands/todo.md": "c1",
                    "plugins/alpha/agents/planner.md": "a1",
                    "plugins/alpha/skills/demo/SKILL.md": "s1",
                    "plugins/alpha/hooks/hooks.json": "h1",
                    "plugins/alpha/.mcp.json": "j1",
                    "plugins/other/README.md": "r1",
                },
                "bodies": {
                    ".claude-plugin/marketplace.json": json.dumps(_marketplace_json()),
                },
            },
            REPO_KWP: {
                "head": HEAD_KWP,
                "license": "NOASSERTION",
                "blobs": {
                    "writing/.claude-plugin/plugin.json": "w1",
                    "writing/skills/draft/SKILL.md": "wd1",
                    "writing/commands/outline.md": "wc1",
                    "sales/.claude-plugin/plugin.json": "q1",
                },
                "bodies": {
                    "writing/.claude-plugin/plugin.json": json.dumps(
                        {"name": "writing", "description": "Writing helpers",
                         "version": "0.3.1", "license": "Apache-2.0"}
                    ),
                    # sales/plugin.json: no version → sha-pinned ladder rung
                    "sales/.claude-plugin/plugin.json": json.dumps(
                        {"name": "sales", "description": "Sales helpers"}
                    ),
                },
            },
        }

    def get(self, url, **kwargs):
        if self.rate_limited and url.startswith(df.GITHUB_API):
            return FakeResponse(status_code=403, headers={"X-RateLimit-Remaining": "0"})
        for repo, spec in self.repos.items():
            if url == f"{df.GITHUB_API}/repos/{repo}":
                return FakeResponse(
                    json_data={"default_branch": "main",
                               "license": {"spdx_id": spec["license"]}},
                    headers={"X-RateLimit-Remaining": "50"},
                )
            if url == f"{df.GITHUB_API}/repos/{repo}/commits/main":
                return FakeResponse(
                    json_data={"sha": spec["head"]},
                    headers={"X-RateLimit-Remaining": "49"},
                )
            if url == f"{df.GITHUB_API}/repos/{repo}/git/trees/{spec['head']}":
                return FakeResponse(
                    json_data={"tree": [
                        {"path": p, "type": "blob", "sha": sha}
                        for p, sha in spec["blobs"].items()
                    ]},
                    headers={"X-RateLimit-Remaining": "48"},
                )
            prefix = f"{df.RAW_BASE}/{repo}/{spec['head']}/"
            if url.startswith(prefix):
                path = url.split(prefix, 1)[1]
                self.raw_calls.append(f"{repo}:{path}")
                body = spec["bodies"].get(path)
                return FakeResponse(status_code=200 if body else 404, text=body or "")
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def hub(isolated, monkeypatch):
    fake = _FakeHub()
    monkeypatch.setattr(df.requests, "get", fake.get)
    monkeypatch.setattr(
        cm, "load_sources_config",
        lambda: {"plugin_marketplaces": [REPO_MKT, REPO_KWP], "github_token": ""},
    )
    return fake


def _boom(*a, **k):
    raise AssertionError("read path must never reach the network")


# ── Manifest resolution ladder ──────────────────────────────────────────────


def test_marketplace_json_shape_normalized(hub):
    doc = cm.refresh()
    by_title = {r["title"]: r for r in doc["records"]}
    mkt = [s for s in doc["sources"] if s["repo"] == REPO_MKT][0]
    assert mkt["ok"] is True and mkt["strategy"] == "marketplace.json"

    alpha = by_title["alpha"]
    assert alpha["subkind"] == "marketplace-entry"
    assert alpha["kind"] == "plugin"
    assert alpha["description"] == "Alpha productivity bundle"
    assert alpha["category"] == "productivity"
    assert alpha["license"] == "MIT"
    assert alpha["tags"] == ["notes", "tasks"]
    # version-resolution ladder: declared semver wins
    assert alpha["version"] == "1.2.0"
    assert alpha["version_resolution"] == "declared"
    # component counts from the pinned tree
    assert alpha["components"] == {
        "commands": 1, "agents": 1, "skills": 1, "hooks": 1, "mcp": 1,
    }
    # SKILL.md pointer bridges into POST /api/skills/import
    assert alpha["skills"] == [{
        "name": "demo",
        "path": "plugins/alpha/skills/demo/SKILL.md",
        "skill_md_url": f"{df.RAW_BASE}/{REPO_MKT}/{HEAD_MKT}/plugins/alpha/skills/demo/SKILL.md",
    }]
    # pointer-only ALWAYS — no body copy, provenance + sha pin on source
    assert alpha["body"] is None and alpha["body_pointer"]
    assert alpha["source"]["ref"] == HEAD_MKT
    assert alpha["source"]["provenance"] == "first-party"


def test_external_source_entry_has_honest_unknown_counts(hub):
    doc = cm.refresh()
    beta = [r for r in doc["records"] if r["title"] == "beta"][0]
    assert beta["components"] == {} and beta["skills"] == []
    # no declared version, head sha available → sha-pinned rung
    assert beta["version"] == HEAD_MKT[:12]
    assert beta["version_resolution"] == "sha-pinned"


def test_hostile_manifest_source_path_degrades_not_traverses(hub):
    doc = cm.refresh()
    evil = [r for r in doc["records"] if r["title"] == "evil"][0]
    # the '../../etc' source path is rejected by the shared charset/dot-segment
    # check and degrades to external (no counts, no skill urls) — and no raw
    # fetch was ever attempted outside the repo tree.
    assert evil["components"] == {} and evil["skills"] == []
    for call in hub.raw_calls:
        assert ".." not in call


def test_plugin_json_fallback_shape_enumerated(hub):
    doc = cm.refresh()
    kwp = [s for s in doc["sources"] if s["repo"] == REPO_KWP][0]
    assert kwp["ok"] is True and kwp["strategy"] == "plugin.json"
    by_title = {r["title"]: r for r in doc["records"]}

    writing = by_title["writing"]
    assert writing["subkind"] == "plugin-manifest"
    assert writing["version"] == "0.3.1"
    assert writing["version_resolution"] == "declared"
    assert writing["license"] == "Apache-2.0"          # per-record license
    assert writing["components"]["skills"] == 1
    assert writing["components"]["commands"] == 1
    assert writing["skills"][0]["path"] == "writing/skills/draft/SKILL.md"

    sales = by_title["sales"]
    assert sales["version"] == HEAD_KWP[:12]
    assert sales["version_resolution"] == "sha-pinned"
    # repo license is NOASSERTION → honest unknown, surfaced before import
    assert sales["license"] == "unknown"


def test_record_ids_are_id_re_safe(hub):
    for rec in cm.refresh()["records"]:
        assert prompts_router._ID_RE.match(rec["id"]), rec["id"]


# ── Persistence + diffing ───────────────────────────────────────────────────


def test_digest_persisted_atomically(hub, isolated):
    cm.refresh()
    p = isolated / "discovery" / "plugin_digest.json"
    assert p.is_file()
    assert not p.with_suffix(p.suffix + ".tmp").exists()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["kind"] == "plugin" and doc["fetched_at"] is not None


def test_added_changed_diff_vs_prior_file(hub):
    first = cm.refresh()
    assert sorted(first["diff"]["added"]) == sorted(
        r["id"] for r in first["records"]
    )
    # change one marketplace entry + add a brand-new one
    mkt = _marketplace_json()
    mkt["plugins"][0]["version"] = "1.3.0"
    mkt["plugins"].append({"name": "gamma", "source": "./plugins/other",
                           "description": "new arrival"})
    hub.repos[REPO_MKT]["bodies"][".claude-plugin/marketplace.json"] = json.dumps(mkt)
    second = cm.refresh()
    by_title = {r["title"]: r for r in second["records"]}
    assert second["diff"]["changed"] == [by_title["alpha"]["id"]]
    assert second["diff"]["added"] == [by_title["gamma"]["id"]]
    assert second["diff"]["removed"] == []


def test_unchanged_plugin_json_skips_body_refetch(hub):
    cm.refresh()
    hub.raw_calls.clear()
    cm.refresh()
    # manifest-first diff: unchanged plugin.json blobs carry forward without
    # a raw fetch; the marketplace.json manifest itself is always consulted.
    kwp_fetches = [c for c in hub.raw_calls if c.startswith(f"{REPO_KWP}:")]
    assert kwp_fetches == []
    assert f"{REPO_MKT}:.claude-plugin/marketplace.json" in hub.raw_calls


# ── Fail-soft ───────────────────────────────────────────────────────────────


def test_malformed_manifest_fails_soft_to_persisted_digest(hub):
    before = cm.refresh()
    hub.repos[REPO_MKT]["bodies"][".claude-plugin/marketplace.json"] = "{not json"
    doc = cm.refresh()
    mkt = [s for s in doc["sources"] if s["repo"] == REPO_MKT][0]
    assert mkt["ok"] is False and mkt["error"]
    # prior records for the broken source carried forward — never emptied
    assert {r["id"] for r in doc["records"]} == {r["id"] for r in before["records"]}
    assert {r["id"] for r in cm.read()["records"]} == {
        r["id"] for r in before["records"]
    }


def test_rate_limited_refresh_fails_soft(hub):
    before = cm.refresh()
    hub.rate_limited = True
    doc = cm.refresh()
    assert doc["rate_remaining"] == 0
    assert any("rate limit" in (s["error"] or "") for s in doc["sources"])
    assert {r["id"] for r in doc["records"]} == {r["id"] for r in before["records"]}


# ── Privacy: reads never fetch; refresh only via the gated POST ─────────────


def test_provider_feed_is_digest_read_zero_network(hub, monkeypatch):
    cm.refresh()
    monkeypatch.setattr(df.requests, "get", _boom)
    # force=True bypasses the in-process cache — a cold read must STILL be
    # offline because the registered fetch() reads the persisted digest.
    feed = ad.get_feed(cm.SOURCE, force=True)
    assert feed.implemented is True
    assert len(feed.items) > 0
    alpha = [i for i in feed.items if i.name == "alpha"][0]
    assert alpha.metadata["license"] == "MIT"          # surfaced pre-import
    assert alpha.metadata["fetched_at"] is not None    # staleness stamp
    assert alpha.metadata["components"]["skills"] == 1
    assert alpha.install["import_endpoint"] == "/api/skills/import"
    assert alpha.install["skills"][0]["skill_md_url"].startswith(df.RAW_BASE)


def test_empty_digest_feed_is_honest_and_offline(isolated, monkeypatch):
    monkeypatch.setattr(df.requests, "get", _boom)
    feed = ad.get_feed(cm.SOURCE, force=True)
    assert feed.items == []
    assert "no digest yet" in (feed.error or "")


def test_refresh_route_fetches_and_get_serves_offline(client, hub, monkeypatch):
    r = client.post(f"/api/discover/{cm.SOURCE}/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == cm.SOURCE and body["count"] > 0
    # the POST persisted the digest; subsequent GETs are offline reads
    monkeypatch.setattr(df.requests, "get", _boom)
    g = client.get(f"/api/discover/{cm.SOURCE}?force=true")
    assert g.status_code == 200
    items = g.json()["items"]
    assert len(items) > 0
    diffs = {i["id"]: i["metadata"]["diff"] for i in items}
    assert set(diffs.values()) <= {"added", "changed", None}


def test_refresh_401_with_auth_on(client, isolated, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.post(f"/api/discover/{cm.SOURCE}/refresh").status_code == 401


def test_stub_replaced_by_real_provider():
    provs = {p["source"]: p for p in ad.list_providers()}
    assert provs[cm.SOURCE]["implemented"] is True
    assert ad._REGISTRY[cm.SOURCE].refresh is cm.refresh
