"""Tests for the generic remote-catalog (marketplace) source in the skills
discover endpoint (workstream A).

ENCLAVE_SKILLS_CATALOG_URL points at a remote JSON index; discovery merges it
with the local curated catalog + bundled installs, deduped (local wins), and
fails soft to local-only on any fetch error.

Theme B split *fetching* from *reading*: `_fetch_remote_catalog()` only touches
the network when the caller passes `allow_fetch=True` (the explicit ⟳ refresh
route and the install path). Every fetch/parse/dedup behaviour below is
unchanged — the tests just say explicitly that they are exercising the
fetching half. That a plain read does NOT fetch is covered in
tests/test_no_background_egress.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.routers import skills as S


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Pristine remote cache + no URL by default.
    monkeypatch.setattr(
        S, "_remote_cache", {"ts": 0.0, "url": None, "skills": []}, raising=False
    )
    monkeypatch.delenv("ENCLAVE_SKILLS_CATALOG_URL", raising=False)


def _mock_get(monkeypatch, payload=None, exc=None):
    def fake_get(url, timeout=6):
        if exc:
            raise exc
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status.return_value = None
        r.json.return_value = payload
        return r

    monkeypatch.setattr(S.requests, "get", fake_get)


def test_no_url_returns_empty(monkeypatch):
    assert S._fetch_remote_catalog() == []
    assert S._fetch_remote_catalog(allow_fetch=True) == []


def test_fetches_and_marks_marketplace(monkeypatch):
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "http://x/skills.json")
    _mock_get(monkeypatch, payload={"skills": [{"id": "remote-a", "name": "A"}]})
    out = S._fetch_remote_catalog(allow_fetch=True)
    assert len(out) == 1
    assert out[0]["id"] == "remote-a"
    assert out[0]["marketplace"] is True
    assert out[0]["source"] == "remote"


def test_accepts_bare_list(monkeypatch):
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "http://x/skills.json")
    _mock_get(monkeypatch, payload=[{"id": "remote-b"}])
    assert [s["id"] for s in S._fetch_remote_catalog(allow_fetch=True)] == ["remote-b"]


def test_skips_entries_without_id(monkeypatch):
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "http://x/skills.json")
    _mock_get(monkeypatch, payload={"skills": [{"name": "no id"}, {"id": "ok"}]})
    assert [s["id"] for s in S._fetch_remote_catalog(allow_fetch=True)] == ["ok"]


def test_fails_soft_on_error(monkeypatch):
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "http://x/skills.json")
    _mock_get(monkeypatch, exc=S.requests.RequestException("boom"))
    assert S._fetch_remote_catalog(allow_fetch=True) == []


def test_caches_within_ttl(monkeypatch):
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "http://x/skills.json")
    calls = {"n": 0}

    def fake_get(url, timeout=6):
        calls["n"] += 1
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = {"skills": [{"id": "c"}]}
        return r

    monkeypatch.setattr(S.requests, "get", fake_get)
    S._fetch_remote_catalog(allow_fetch=True)
    S._fetch_remote_catalog(allow_fetch=True)
    assert calls["n"] == 1  # second call served from cache


@pytest.mark.asyncio
async def test_discover_merges_and_dedupes(monkeypatch):
    """Merge + dedup are unchanged; the remote half is whatever a prior
    refresh cached. Primed here the way the ⟳ route would leave it, since a
    read no longer fetches (tests/test_no_background_egress.py pins that)."""
    # Local catalog has 'local-1'; remote has a dup 'local-1' + a new 'remote-1'.
    monkeypatch.setattr(
        S, "_load_catalog", lambda: {"skills": [{"id": "local-1", "name": "Local"}]}
    )
    monkeypatch.setattr(S, "_installed_skills_detail", lambda: {})
    monkeypatch.setattr(S, "_installed_index", lambda: {})
    monkeypatch.setenv("ENCLAVE_SKILLS_CATALOG_URL", "http://x/skills.json")
    _mock_get(
        monkeypatch,
        payload={"skills": [{"id": "local-1", "name": "DUP"}, {"id": "remote-1"}]},
    )
    # The explicit refresh fills the cache …
    assert len(S._fetch_remote_catalog(allow_fetch=True)) == 2
    # … and the read merges it without touching the network again.
    _mock_get(monkeypatch, exc=AssertionError("discover() must not fetch on a read"))
    res = await S.discover()
    ids = [s["id"] for s in res["skills"]]
    assert ids.count("local-1") == 1  # dedup, local wins
    assert "remote-1" in ids
    assert res["remote_count"] == 1
