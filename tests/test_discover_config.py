#!/usr/bin/env python3
"""LB0-U2 — persisted discovery source config (GET/PUT /api/discover/config).

Covers the spec's verify list:
  - GET /api/discover/config returns the config document, NOT a provider
    404 from the /{source} catch-all (route-ordering hazard C9);
  - PUT persists to discovery_sources.json (atomic, chmod 0600);
  - tokens are masked on GET / never echoed raw;
  - 401 with auth on and no key (GET and PUT);
  - the file is consulted at FETCH time: PUT a new allowlist, then a
    refresh uses it without a restart;
  - 'config' is reserved in the source-name validator;
  - per-source cache TTLs are read at fetch time, not import time.
"""

from __future__ import annotations

import importlib
import json
import os
import stat
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.services import agentic_discovery as ad
from api.services.discovery_providers import skills_marketplace as sm


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


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point the config file at a tmp path + neutralize env overrides."""
    monkeypatch.setattr(ad, "_SOURCES_CONFIG_FILE", tmp_path / "discovery_sources.json")
    for var in (
        "ENCLAVE_SKILL_REPOS",
        "ENCLAVE_GITHUB_TOKEN",
        "GITHUB_TOKEN",
        "ENCLAVE_SKILLS_CATALOG_URL",
        "ENCLAVE_MCP_CATALOG_URL",
    ):
        monkeypatch.delenv(var, raising=False)


# ── Route ordering (C9) ────────────────────────────────────────────────────


def test_get_config_returns_document_not_provider_404(client):
    r = client.get("/api/discover/config")
    assert r.status_code == 200
    body = r.json()
    # The config document — not {"detail": "unknown discovery provider 'config'"}
    assert "skill_repos" in body
    assert "plugin_marketplaces" in body
    assert "prompt_digest_sources" in body
    assert "catalog_urls" in body
    assert "cache_ttls" in body
    assert "detail" not in body


def test_config_is_reserved_source_name():
    with pytest.raises(ValueError):
        ad.register_provider(
            source="config",
            name="Evil",
            description="",
            homepage="",
            kinds=["mcp"],
            fetch=lambda: None,
        )
    assert "config" not in {p["source"] for p in ad.list_providers()}


# ── Merge: file > env > default ────────────────────────────────────────────


def test_file_env_default_merge(monkeypatch):
    # default layer
    assert ad.load_sources_config()["skill_repos"] == ad.DEFAULT_SKILL_REPOS
    # env layer beats default
    monkeypatch.setenv("ENCLAVE_SKILL_REPOS", "acme/skills")
    assert ad.load_sources_config()["skill_repos"] == ["acme/skills"]
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "https://env.example/idx.json")
    assert ad.load_sources_config()["catalog_urls"]["skills"] == "https://env.example/idx.json"
    # file layer beats env
    ad._SOURCES_CONFIG_FILE.write_text(
        json.dumps(
            {
                "skill_repos": ["file/wins"],
                "catalog_urls": {"skills": "https://file.example/idx.json"},
            }
        )
    )
    cfg = ad.load_sources_config()
    assert cfg["skill_repos"] == ["file/wins"]
    assert cfg["catalog_urls"]["skills"] == "https://file.example/idx.json"


# ── PUT persistence + token masking ────────────────────────────────────────


def test_put_persists_chmod_0600_and_masks_token(client):
    r = client.put(
        "/api/discover/config",
        json={
            "skill_repos": ["acme/skills"],
            "plugin_marketplaces": ["acme/plugins"],
            "cache_ttls": {"default": 120, "hf-discovery": 3600},
            "github_token": "ghp_secret_value_1234",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Persisted (file exists, atomic write left no tmp behind, mode 0600).
    path = ad._SOURCES_CONFIG_FILE
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    on_disk = json.loads(path.read_text())
    assert on_disk["skill_repos"] == ["acme/skills"]
    assert on_disk["github_token"] == "ghp_secret_value_1234"
    # Masked on write-response…
    assert "ghp_secret_value_1234" not in r.text
    assert body["github_token_set"] is True
    assert body["github_token_masked"] == "***1234"
    # …and on every subsequent GET.
    g = client.get("/api/discover/config")
    assert "ghp_secret_value_1234" not in g.text
    assert g.json()["github_token_masked"] == "***1234"
    assert g.json()["cache_ttls"]["hf-discovery"] == 3600


def test_put_token_semantics(client):
    client.put("/api/discover/config", json={"github_token": "ghp_original_9999"})
    # Masked echo → keep the stored token.
    client.put("/api/discover/config", json={"github_token": "***9999"})
    assert json.loads(ad._SOURCES_CONFIG_FILE.read_text())["github_token"] == "ghp_original_9999"
    # Absent key → keep.
    client.put("/api/discover/config", json={"skill_repos": ["acme/skills"]})
    assert json.loads(ad._SOURCES_CONFIG_FILE.read_text())["github_token"] == "ghp_original_9999"
    # Empty string → clear.
    r = client.put("/api/discover/config", json={"github_token": ""})
    assert r.json()["github_token_set"] is False
    assert "github_token" not in json.loads(ad._SOURCES_CONFIG_FILE.read_text())


def test_put_validation_rejects_bad_input(client):
    bad_bodies = [
        {"skill_repos": ["../../etc/passwd"]},           # traversal
        {"skill_repos": ["../evil"]},                    # dot-segment owner
        {"skill_repos": ["evil/.."]},                    # dot-segment repo
        {"skill_repos": ["./x"]},                        # dot-segment owner
        {"skill_repos": ["no-slash"]},                   # not owner/repo
        {"plugin_marketplaces": ["https://evil.example/x"]},
        {"catalog_urls": {"skills": "ftp://x"}},         # non-http(s)
        {"catalog_urls": {"bogus": "https://x"}},        # unknown key
        {"cache_ttls": {"default": -5}},                 # negative
        {"cache_ttls": {"BAD KEY": 10}},                 # bad source key
        {"github_token": "a\nb"},                        # control chars
    ]
    for body in bad_bodies:
        r = client.put("/api/discover/config", json=body)
        assert r.status_code == 400, f"{body} should be rejected"
    # Nothing persisted by rejected writes.
    assert not ad._SOURCES_CONFIG_FILE.exists()


# ── Auth gate ──────────────────────────────────────────────────────────────


def test_config_routes_401_with_auth_on_and_no_key(client, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.get("/api/discover/config").status_code == 401
    assert client.put("/api/discover/config", json={"skill_repos": []}).status_code == 401


# ── Fetch-time consultation (no restart needed) ────────────────────────────


def _fake_requests(urls):
    """Stub for skills_marketplace.requests recording every GET URL."""

    def fake_get(url, headers=None, timeout=None):
        urls.append(url)
        r = MagicMock()
        r.raise_for_status.return_value = None
        if "api.github.com" in url:
            r.status_code = 200
            r.json.return_value = {"tree": [{"path": "skills/demo/SKILL.md"}]}
        else:
            r.status_code = 200
            r.text = "---\nname: Demo\n---\nbody"
        return r

    stub = MagicMock()
    stub.get = fake_get
    stub.RequestException = Exception
    return stub


def test_put_then_refresh_uses_new_allowlist_without_restart(client, monkeypatch):
    urls: list = []
    monkeypatch.setattr(sm, "requests", _fake_requests(urls))

    r = client.put("/api/discover/config", json={"skill_repos": ["operator/added-repo"]})
    assert r.status_code == 200

    # Refresh (force=True) — the provider must consult the file NOW.
    r = client.post("/api/discover/skills-sh/refresh")
    assert r.status_code == 200
    tree_calls = [u for u in urls if "api.github.com" in u]
    assert tree_calls, "refresh should have hit the trees API"
    assert all("operator/added-repo" in u for u in tree_calls)
    assert not any("anthropics/skills" in u for u in urls)  # defaults replaced

    # Token set via config is used on the next fetch, also without restart.
    urls.clear()
    client.put("/api/discover/config", json={"github_token": "ghp_live_token_5678"})
    assert sm._headers().get("Authorization") == "Bearer ghp_live_token_5678"


def test_cache_ttl_consulted_at_fetch_time():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return ad.DiscoveryFeed(
            source="ttltest", name="t", description="", homepage="",
            kinds=["mcp"], implemented=True,
        )

    entry = ad._ProviderEntry(
        source="ttltest", name="t", description="", homepage="",
        kinds=["mcp"], fetch=fetch,
    )
    # TTL 0 → every get() refetches.
    ad.update_sources_config({"cache_ttls": {"ttltest": 0}})
    entry.get()
    entry.get()
    assert calls["n"] == 2
    # Raise the TTL → the cache holds, no new fetch.
    ad.update_sources_config({"cache_ttls": {"ttltest": 3600}})
    entry.get()
    assert calls["n"] == 2
