"""Tests for the skills.sh GitHub-backed discovery provider.

The provider crawls a curated allow-list of public skill repos via the
GitHub trees API, parses each SKILL.md's frontmatter, and projects it
into the unified DiscoveryItem shape with both install paths attached.
Network is fully mocked here — one fake tree per repo + one fake
SKILL.md per skill.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.services.discovery_providers import skills_marketplace as P


def _resp(status=200, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = text
    r.raise_for_status.return_value = None
    return r


_SKILL_MD = """---
name: Demo Skill
description: A demonstration skill for tests.
version: 1.2.0
tags: [demo, testing]
license: MIT
---

# Demo Skill
body here
"""


@pytest.fixture(autouse=True)
def _one_repo(monkeypatch):
    # Pin the allow-list to a single repo so the crawl is deterministic.
    monkeypatch.setenv("ENCLAVE_SKILL_REPOS", "acme/skills")
    monkeypatch.delenv("ENCLAVE_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def _wire(monkeypatch, *, tree_paths, md=_SKILL_MD, tree_status=200):
    """Route requests.get: trees API → fake tree, raw CDN → fake SKILL.md."""
    tree = {"tree": [{"path": p, "type": "blob"} for p in tree_paths]}

    def fake_get(url, headers=None, timeout=None):
        if "api.github.com" in url:
            return _resp(status=tree_status, json_body=tree)
        return _resp(status=200, text=md)  # raw.githubusercontent.com

    monkeypatch.setattr(P.requests, "get", fake_get)


def test_fetch_projects_skill_md_into_items(monkeypatch):
    _wire(monkeypatch, tree_paths=["skills/demo/SKILL.md", "README.md"])
    feed = P.fetch()

    assert feed.source == "skills-sh"
    assert feed.implemented is True
    assert feed.kinds == ["skill"]
    assert feed.error is None
    assert len(feed.items) == 1  # only the SKILL.md, not README.md

    it = feed.items[0]
    assert it.kind == "skill"
    assert it.name == "Demo Skill"
    assert it.description == "A demonstration skill for tests."
    assert it.version == "1.2.0"
    assert it.id == "acme/skills/demo-skill"
    assert it.metadata["author"] == "acme"
    assert it.metadata["tags"] == ["demo", "testing"]


def test_install_carries_both_paths(monkeypatch):
    _wire(monkeypatch, tree_paths=["skills/demo/SKILL.md"])
    it = P.fetch().items[0]

    # skills.sh CLI path.
    assert it.install["command"] == "npx skills add acme/skills"
    # Enclave-native import path — a raw SKILL.md URL the importer accepts.
    raw = it.install["skill_md_url"]
    assert raw.startswith("https://raw.githubusercontent.com/acme/skills/")
    assert raw.endswith("/skills/demo/SKILL.md")
    assert it.install["import_endpoint"] == "/api/skills/import"


def test_per_repo_cap_truncates(monkeypatch):
    monkeypatch.setattr(P, "_MAX_PER_REPO", 2)
    _wire(
        monkeypatch,
        tree_paths=[f"skills/s{i}/SKILL.md" for i in range(5)],
    )
    feed = P.fetch()
    assert len(feed.items) == 2  # capped


def test_master_fallback_when_main_404(monkeypatch):
    calls = {"refs": []}

    def fake_get(url, headers=None, timeout=None):
        if "api.github.com" in url:
            ref = "main" if "/main?" in url else "master"
            calls["refs"].append(ref)
            if ref == "main":
                return _resp(status=404, json_body={"message": "Not Found"})
            return _resp(
                status=200, json_body={"tree": [{"path": "skills/d/SKILL.md"}]}
            )
        return _resp(status=200, text=_SKILL_MD)

    monkeypatch.setattr(P.requests, "get", fake_get)
    feed = P.fetch()
    assert calls["refs"] == ["main", "master"]
    assert len(feed.items) == 1
    assert feed.items[0].install["ref"] == "master"


def test_repo_failure_recorded_as_error(monkeypatch):
    import requests

    def fake_get(url, headers=None, timeout=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(P.requests, "get", fake_get)
    feed = P.fetch()
    assert feed.items == []
    assert feed.error and "boom" in feed.error


def test_provider_registered():
    from api.services import agentic_discovery as ad

    sources = {p["source"] for p in ad.list_providers()}
    assert "skills-sh" in sources
