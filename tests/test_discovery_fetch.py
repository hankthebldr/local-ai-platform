#!/usr/bin/env python3
"""LB2-U2 — shared discovery fetcher (services/discovery_fetch.py).

Covers the unit's verify list for the fetcher primitives, with mocked HTTP:
  - allowlist/charset discipline: owner/repo, digest kind, and repo-path
    validation reject traversal and injection shapes (the glob-traversal
    incident lesson applies to every id→path/url seam);
  - sha-pinned raw fetches (bad shas rejected, misses -> None);
  - GitHub rate-budget fail-soft: 403 with a zero remaining header raises
    RateLimited carrying the remaining quota;
  - whole-digest ATOMIC replace with prior-file diff (added/changed/removed
    computed at refresh time — no tombstones, no append log);
  - read path never raises on absent/corrupt files and NEVER fetches;
  - license gate: permissive SPDX allows body copies, proprietary/unknown
    do not, community provenance is pointer-only regardless.

Run:  pytest tests/test_discovery_fetch.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import discovery_fetch as df


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def digest_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(df, "_DIGEST_DIR", tmp_path / "discovery")
    return tmp_path / "discovery"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any un-mocked HTTP in these tests is a bug — fail loudly."""
    def _boom(*a, **k):
        raise AssertionError(f"unexpected network call: {a} {k}")

    monkeypatch.setattr(df.requests, "get", _boom)


# ── License gate ────────────────────────────────────────────────────────────


def test_license_gate_permissive_allows_body():
    for lic in ("MIT", "mit", "Apache-2.0", "BSD-3-Clause", "CC0-1.0"):
        assert df.license_allows_body(lic) is True


def test_license_gate_blocks_proprietary_unknown_and_empty():
    for lic in ("proprietary", "unknown", "", None, "NOASSERTION", "GPL-9.9"):
        assert df.license_allows_body(lic) is False


def test_license_gate_community_provenance_is_pointer_only():
    assert df.license_allows_body("MIT", provenance="community") is False


# ── Charset / containment discipline ────────────────────────────────────────


def test_digest_kind_charset_allowlist(digest_dir):
    assert df.digest_path("prompt").name == "prompt_digest.json"
    for bad in ("../evil", "a/b", "UPPER", "", "x" * 40, "pr ompt", ".."):
        with pytest.raises(ValueError):
            df.digest_path(bad)


def test_repo_allowlist_rejects_traversal_and_injection():
    for bad in ("../x/y", "a/..", "owner", "owner/repo/extra", "o wner/repo",
                "/abs/repo", "owner/.."):
        with pytest.raises(ValueError):
            df._check_repo(bad)
    assert df._check_repo("anthropics/claude-cookbooks") == "anthropics/claude-cookbooks"


def test_raw_path_rejects_traversal_and_absolute():
    for bad in ("../secrets", "a/../b", "/etc/passwd", "", "a\\b", "a/./b", "..%2Fx"):
        with pytest.raises(ValueError):
            df._check_path(bad)
    assert df._check_path("skills/demo/SKILL.md") == "skills/demo/SKILL.md"


def test_fetch_raw_rejects_bad_sha(monkeypatch):
    with pytest.raises(ValueError):
        df.fetch_raw("o/r", "not-a-sha!", "a.md")
    with pytest.raises(ValueError):
        df.repo_tree("o/r", "xyz$")


def test_fetch_raw_none_on_miss(monkeypatch):
    monkeypatch.setattr(
        df.requests, "get", lambda *a, **k: FakeResponse(status_code=404)
    )
    assert df.fetch_raw("o/r", "a" * 40, "missing.md") is None


# ── Rate budget fail-soft ───────────────────────────────────────────────────


def test_api_get_raises_ratelimited_on_exhausted_budget(monkeypatch):
    monkeypatch.setattr(
        df.requests,
        "get",
        lambda *a, **k: FakeResponse(
            status_code=403, headers={"X-RateLimit-Remaining": "0"}
        ),
    )
    with pytest.raises(df.RateLimited) as exc:
        df.api_get("/repos/o/r")
    assert exc.value.remaining == 0


def test_api_get_surfaces_remaining_quota(monkeypatch):
    monkeypatch.setattr(
        df.requests,
        "get",
        lambda *a, **k: FakeResponse(
            json_data={"ok": True}, headers={"X-RateLimit-Remaining": "42"}
        ),
    )
    data, remaining = df.api_get("/repos/o/r")
    assert data == {"ok": True}
    assert remaining == 42


def test_repo_head_resolves_sha_branch_and_license(monkeypatch):
    def fake_get(url, **k):
        if url.endswith("/repos/o/r"):
            return FakeResponse(
                json_data={"default_branch": "main", "license": {"spdx_id": "MIT"}},
                headers={"X-RateLimit-Remaining": "50"},
            )
        if url.endswith("/repos/o/r/commits/main"):
            return FakeResponse(
                json_data={"sha": "a" * 40}, headers={"X-RateLimit-Remaining": "49"}
            )
        raise AssertionError(url)

    monkeypatch.setattr(df.requests, "get", fake_get)
    head = df.repo_head("o/r")
    assert head == {
        "repo": "o/r", "default_branch": "main", "sha": "a" * 40,
        "license": "MIT", "rate_remaining": 49,
    }


def test_repo_head_noassertion_license_becomes_empty(monkeypatch):
    def fake_get(url, **k):
        if url.endswith("/repos/o/r"):
            return FakeResponse(
                json_data={"default_branch": "main", "license": {"spdx_id": "NOASSERTION"}}
            )
        return FakeResponse(json_data={"sha": "b" * 40})

    monkeypatch.setattr(df.requests, "get", fake_get)
    assert df.repo_head("o/r")["license"] == ""


# ── Digest persistence: atomic replace + prior-file diff ────────────────────


def _rec(rid, sha):
    return {"id": rid, "content_sha": sha}


def test_write_digest_computes_diff_against_prior_file(digest_dir):
    doc1 = df.write_digest("prompt", [_rec("a", "1"), _rec("b", "1")])
    assert doc1["diff"] == {"added": ["a", "b"], "changed": [], "removed": []}
    # b changes, a survives, c appears, then a is dropped next round
    doc2 = df.write_digest("prompt", [_rec("a", "1"), _rec("b", "2"), _rec("c", "1")])
    assert doc2["diff"] == {"added": ["c"], "changed": ["b"], "removed": []}
    doc3 = df.write_digest("prompt", [_rec("b", "2"), _rec("c", "1")])
    assert doc3["diff"] == {"added": [], "changed": [], "removed": ["a"]}


def test_write_digest_is_whole_file_atomic_replace(digest_dir):
    df.write_digest("prompt", [_rec("a", "1")])
    p = df.digest_path("prompt")
    assert p.is_file()
    assert not p.with_suffix(p.suffix + ".tmp").exists(), "tmp must be replaced away"
    on_disk = json.loads(p.read_text())
    assert [r["id"] for r in on_disk["records"]] == ["a"]
    assert on_disk["fetched_at"] is not None


def test_read_digest_defaults_when_absent_and_corrupt(digest_dir):
    empty = df.read_digest("prompt")
    assert empty["records"] == [] and empty["fetched_at"] is None
    p = df.digest_path("prompt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    corrupt = df.read_digest("prompt")
    assert corrupt["records"] == [] and corrupt["fetched_at"] is None


def test_read_paths_never_fetch(digest_dir):
    # autouse _no_real_network makes ANY requests call raise — read paths
    # must survive it untouched.
    df.read_digest("prompt")
    df.prior_records("prompt")


def test_prior_records_maps_by_id(digest_dir):
    df.write_digest("prompt", [_rec("a", "1"), _rec("b", "2"), {"noid": True}])
    prior = df.prior_records("prompt")
    assert set(prior) == {"a", "b"}
    assert prior["b"]["content_sha"] == "2"


# ── Call-site discipline: fetcher invoked ONLY from refresh routes ──────────

_API_DIR = Path(__file__).resolve().parents[1] / "api"


def test_network_primitives_used_only_by_prompt_digest_service():
    """The new module's network surface (api_get/repo_head/repo_tree/
    fetch_raw) must be reachable only through services/prompt_digest.py —
    scoped to the modules THIS unit introduces (pre-existing skills/mcp/HF
    read-fetches are named follow-up #15)."""
    offenders = []
    for py in _API_DIR.rglob("*.py"):
        rel = py.relative_to(_API_DIR).as_posix()
        if rel in ("services/discovery_fetch.py", "services/prompt_digest.py"):
            continue
        text = py.read_text(encoding="utf-8")
        if "discovery_fetch" not in text:
            continue
        for fn in ("api_get", "repo_head", "repo_tree", "fetch_raw"):
            if fn in text:
                offenders.append(f"{rel}: {fn}")
    assert offenders == [], f"network primitives leaked outside the digest service: {offenders}"


def test_prompts_router_fetches_only_inside_refresh_route():
    src = (
        _API_DIR / "routers" / "prompts.py"
    ).read_text(encoding="utf-8")
    # exactly one refresh() call site, and it lives in the POST route body
    assert src.count("prompt_digest.refresh()") == 1
    refresh_block = src.split("async def refresh_prompt_discovery", 1)[1]
    refresh_block = refresh_block.split("\n@router", 1)[0]
    assert "prompt_digest.refresh()" in refresh_block
    # the read GET serves the persisted digest only — no refresh/fetch calls
    read_block = src.split("async def discover_prompts", 1)[1].split("\n@router", 1)[0]
    assert "prompt_digest.refresh" not in read_block
    assert "requests." not in read_block
    assert "fetch_raw" not in read_block
    assert "prompt_digest.read()" in read_block
