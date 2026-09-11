"""Theme B — no background egress: a GET never reaches the network.

Enclave's headline posture is "no telemetry, no cloud inference, every fetch
operator-initiated". Three discovery surfaces quietly broke it by evaluating a
freshness TTL *on read*, so merely opening a tab with a cold or stale cache
egressed to HuggingFace or to the operator's configured marketplace:

  · GET /api/skills/discover     → ENCLAVE_SKILLS_CATALOG_URL
  · GET /api/mcp/discover        → ENCLAVE_MCP_CATALOG_URL
  · GET /api/inventory/discover  → HuggingFace model search

Reads now serve cache only. The network is reachable exclusively through an
explicit operator action: the new POST …/discover/refresh routes, the install
paths, and inventory's existing `?force=true` / POST /discover/refresh.

Every test here fails the request loudly if a fetch happens, so a regression
shows up as an assertion about egress rather than a silent network call.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


class _EgressTripwire:
    """Records every attempted HTTP call and raises, so an egressing read
    surfaces as a failure rather than a real network request."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url, *a, **kw):
        self.calls.append(str(url))
        raise AssertionError(f"network egress on a read: {url}")


@pytest.fixture()
def skills_tripwire(monkeypatch):
    import api.routers.skills as skills

    monkeypatch.setenv(
        "ENCLAVE_SKILLS_CATALOG_URL", "https://marketplace.test/index.json"
    )
    # Cold cache: url mismatch + ts 0 → the OLD code fetched here.
    monkeypatch.setattr(skills, "_remote_cache", {"ts": 0.0, "url": None, "skills": []})
    tw = _EgressTripwire()
    monkeypatch.setattr(skills.requests, "get", tw)
    return tw


@pytest.fixture()
def mcp_tripwire(monkeypatch):
    import api.routers.mcp as mcp

    monkeypatch.setenv("ENCLAVE_MCP_CATALOG_URL", "https://mcp-market.test/index.json")
    monkeypatch.setattr(mcp, "_remote_cache", {"ts": 0.0, "url": None, "servers": []})
    tw = _EgressTripwire()
    monkeypatch.setattr(mcp.requests, "get", tw)
    return tw


# ── skills marketplace ─────────────────────────────────────────────────────


def test_skills_discover_get_does_not_egress(client, skills_tripwire):
    """A cold cache + a configured marketplace used to fetch on GET."""
    r = client.get("/api/skills/discover")
    assert r.status_code == 200, r.text
    assert skills_tripwire.calls == [], "GET /api/skills/discover egressed"
    # Local curated catalog still serves the tab.
    assert r.json()["remote_count"] == 0


def test_skills_discover_one_does_not_egress(client, skills_tripwire):
    r = client.get("/api/skills/discover/does-not-exist")
    assert r.status_code == 404
    assert skills_tripwire.calls == []


def test_skills_refresh_route_is_the_explicit_fetch(
    client, skills_tripwire, monkeypatch
):
    """POST …/discover/refresh is the ⟳ — it MAY fetch. Here the fetch is
    stubbed to succeed so we assert the route really reaches the network."""
    import api.routers.skills as skills

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"skills": [{"id": "remote-skill", "name": "Remote"}]}

    seen: list[str] = []

    def _get(url, *a, **kw):
        seen.append(str(url))
        return _Resp()

    monkeypatch.setattr(skills.requests, "get", _get)
    r = client.post("/api/skills/discover/refresh")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refreshed"] is True
    assert body["remote_count"] == 1
    assert seen == ["https://marketplace.test/index.json"]

    # And the refreshed entry is now visible on a subsequent NON-egressing GET.
    got = client.get("/api/skills/discover")
    assert got.status_code == 200
    assert got.json()["remote_count"] == 1


def test_skills_refresh_without_catalog_url_is_a_noop(client, monkeypatch):
    monkeypatch.delenv("ENCLAVE_SKILLS_CATALOG_URL", raising=False)
    r = client.post("/api/skills/discover/refresh")
    assert r.status_code == 200
    assert r.json()["refreshed"] is False


# ── MCP marketplace ────────────────────────────────────────────────────────


def test_mcp_discover_get_does_not_egress(client, mcp_tripwire):
    r = client.get("/api/mcp/discover")
    assert r.status_code == 200, r.text
    assert mcp_tripwire.calls == [], "GET /api/mcp/discover egressed"
    assert r.json()["remote_count"] == 0


def test_mcp_refresh_route_is_the_explicit_fetch(client, mcp_tripwire, monkeypatch):
    import api.routers.mcp as mcp

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"servers": [{"id": "remote-mcp", "name": "Remote MCP"}]}

    seen: list[str] = []

    def _get(url, *a, **kw):
        seen.append(str(url))
        return _Resp()

    monkeypatch.setattr(mcp.requests, "get", _get)
    r = client.post("/api/mcp/discover/refresh")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "refreshed": True,
        "url": "https://mcp-market.test/index.json",
        "remote_count": 1,
    }
    assert seen == ["https://mcp-market.test/index.json"]
    assert client.get("/api/mcp/discover").json()["remote_count"] == 1


# ── HuggingFace model discovery ────────────────────────────────────────────


def test_inventory_discover_get_does_not_run_discovery(client, monkeypatch):
    """The old code ran a live HuggingFace discovery whenever the cache was
    cold or stale — on a plain GET."""
    import api.routers.inventory as inv

    def _boom(*a, **kw):
        raise AssertionError("GET /api/inventory/discover ran a live discovery")

    monkeypatch.setattr(inv, "get_cached_or_discover", _boom)
    monkeypatch.setattr(inv, "load_discovery_cache", lambda: None)
    monkeypatch.setattr(inv, "is_cache_fresh", lambda: False)

    r = client.get("/api/inventory/discover")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["models"] == [] and body["count"] == 0
    # The UI can tell "never refreshed" from "refreshed a while ago".
    assert body["never_discovered"] is True
    assert body["cache_fresh"] is False


def test_inventory_discover_serves_a_stale_cache_as_stale(client, monkeypatch):
    import api.routers.inventory as inv

    monkeypatch.setattr(
        inv,
        "load_discovery_cache",
        lambda: {
            "models": [{"id": "m1"}],
            "count": 1,
            "timestamp": "2020-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(inv, "is_cache_fresh", lambda: False)
    monkeypatch.setattr(
        inv, "get_cached_or_discover", lambda **kw: pytest.fail("must not discover")
    )

    body = client.get("/api/inventory/discover").json()
    assert body["count"] == 1
    assert body["cache_fresh"] is False
    assert body["never_discovered"] is False


def test_inventory_force_is_the_explicit_refresh(client, monkeypatch):
    """`?force=true` stays the operator's deliberate ⟳ and DOES discover."""
    import api.routers.inventory as inv

    called: dict[str, object] = {}

    def _discover(max_model_ram_gb=50, force=False):
        called["force"] = force
        return {"models": [{"id": "fresh"}], "count": 1, "timestamp": "now"}

    monkeypatch.setattr(inv, "get_cached_or_discover", _discover)
    body = client.get("/api/inventory/discover?force=true").json()
    assert called["force"] is True
    assert body["count"] == 1
