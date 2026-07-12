#!/usr/bin/env python3
"""
Workspace tests (C2) — durable local-directory runtime.

Service tests cover the traversal guard, policy, and the make / edit / expand
markdown verbs (incl. heading-aware expansion). Router tests drive the same via
HTTP against an isolated registry rooted in a tmp dir.
"""

import os
import importlib

import pytest
from fastapi.testclient import TestClient

from api.services.workspace import (
    Workspace,
    WorkspaceMeta,
    WorkspacePolicy,
    WorkspaceRegistry,
    WorkspaceViolation,
    WorkspaceError,
    WorkspaceQuotaExceeded,
)


def _ws(tmp_path, **policy):
    meta = WorkspaceMeta(name="t", root=str(tmp_path), policy=WorkspacePolicy(**policy))
    return Workspace(meta)


# ── guard ───
def test_rejects_path_escape(tmp_path):
    ws = _ws(tmp_path)
    with pytest.raises(WorkspaceViolation):
        ws.resolve("../../etc/passwd")
    with pytest.raises(WorkspaceViolation):
        ws.resolve("/etc/passwd")


def test_read_only_blocks_writes(tmp_path):
    ws = _ws(tmp_path, read_only=True)
    with pytest.raises(WorkspaceViolation):
        ws.write("a.md", "x")


def test_extension_allowlist(tmp_path):
    ws = _ws(tmp_path, allowed_extensions=["md"])
    ws.write("ok.md", "# ok")
    with pytest.raises(WorkspaceViolation):
        ws.write("nope.txt", "x")


def test_quota(tmp_path):
    ws = _ws(tmp_path, max_file_size_mb=0)  # 0 MB → any non-empty write fails
    with pytest.raises(WorkspaceQuotaExceeded):
        ws.write("big.md", "content")


# ── make / edit / expand ───
def test_make_creates_then_overwrites(tmp_path):
    ws = _ws(tmp_path)
    r1 = ws.write("notes/a.md", "# Title\n")
    assert r1["action"] == "created"
    assert ws.read("notes/a.md") == "# Title\n"
    r2 = ws.write("notes/a.md", "# New\n")
    assert r2["action"] == "overwrote"


def test_edit_replaces_and_errors_when_absent(tmp_path):
    ws = _ws(tmp_path)
    ws.write("a.md", "hello world, hello moon")
    r = ws.edit("a.md", "hello", "hi")
    assert r["replacements"] == 2
    assert ws.read("a.md") == "hi world, hi moon"
    with pytest.raises(WorkspaceError):
        ws.edit("a.md", "absent-text", "x")


def test_expand_appends_when_no_heading(tmp_path):
    ws = _ws(tmp_path)
    ws.write("a.md", "# Doc\n\nintro\n")
    ws.expand("a.md", "more content")
    assert ws.read("a.md") == "# Doc\n\nintro\nmore content\n"


def test_expand_inserts_under_heading(tmp_path):
    ws = _ws(tmp_path)
    ws.write(
        "a.md",
        "# Doc\n\n## Findings\n\n- one\n\n## Sources\n\n- [x](https://x)\n",
    )
    ws.expand("a.md", "- two", heading="Findings")
    out = ws.read("a.md")
    # inserted into Findings, not Sources
    findings = out.split("## Sources")[0]
    assert "- one" in findings and "- two" in findings
    assert out.index("- two") < out.index("## Sources")


def test_expand_creates_section_when_heading_absent(tmp_path):
    ws = _ws(tmp_path)
    ws.write("a.md", "# Doc\n\nbody\n")
    ws.expand("a.md", "detail", heading="Appendix")
    out = ws.read("a.md")
    assert "## Appendix" in out and "detail" in out


def test_expand_creates_file_if_missing(tmp_path):
    ws = _ws(tmp_path)
    ws.expand("new.md", "first line")
    assert "first line" in ws.read("new.md")


# ── search / registry ───
def test_search_finds_lines(tmp_path):
    ws = _ws(tmp_path)
    ws.write("a.md", "alpha\nBETA line\n")
    ws.write("b.md", "gamma\n")
    hits = ws.search("beta")
    assert len(hits) == 1 and hits[0]["path"] == "a.md" and hits[0]["line"] == 2


def test_registry_persists(tmp_path):
    store = tmp_path / "reg.json"
    reg = WorkspaceRegistry(store_path=store)
    reg.create("vault", str(tmp_path / "v"), WorkspacePolicy(allowed_extensions=["md"]))
    # reload from disk
    reg2 = WorkspaceRegistry(store_path=store)
    names = [m.name for m in reg2.list()]
    assert "vault" in names
    assert reg2.get("vault").meta.policy.allowed_extensions == ["md"]


def test_registry_rejects_dupe_and_bad_name(tmp_path):
    reg = WorkspaceRegistry(store_path=tmp_path / "reg.json")
    reg.create("ok", str(tmp_path / "a"))
    with pytest.raises(WorkspaceError):
        reg.create("ok", str(tmp_path / "b"))
    with pytest.raises(WorkspaceError):
        reg.create("Bad Name", str(tmp_path / "c"))


# ── router ───
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


def test_router_make_edit_expand_flow(client, tmp_path):
    # point the registry singleton at an isolated store + root
    import api.services.workspace as wsmod

    wsmod._registry = wsmod.WorkspaceRegistry(store_path=tmp_path / "reg.json")

    root = str(tmp_path / "proj")
    r = client.post("/api/workspaces", json={"name": "proj", "root": root})
    assert r.status_code == 200

    # make
    r = client.put("/api/workspaces/proj/file", json={"path": "doc.md", "content": "# Doc\n\n## Notes\n\n- a\n"})
    assert r.json()["action"] == "created"

    # expand under heading
    r = client.post("/api/workspaces/proj/expand", json={"path": "doc.md", "content": "- b", "heading": "Notes"})
    assert r.status_code == 200 and r.json()["action"] == "expanded"

    # edit
    r = client.post("/api/workspaces/proj/edit", json={"path": "doc.md", "find": "# Doc", "replace": "# Document"})
    assert r.json()["replacements"] == 1

    # read back
    content = client.get("/api/workspaces/proj/file", params={"path": "doc.md"}).json()["content"]
    assert "# Document" in content and "- a" in content and "- b" in content

    # escape is forbidden
    r = client.get("/api/workspaces/proj/file", params={"path": "../../etc/passwd"})
    assert r.status_code == 403


# ── security regressions (found by the whole-effort code review, 2026-07-09) ──
def test_glob_traversal_blocked(tmp_path):
    ws = _ws(tmp_path)
    ws.write("in.md", "hello")
    import pytest as _pt
    for g in ("../../../../etc/passwd", "../*.md", "/etc/*"):
        with _pt.raises(WorkspaceViolation):
            ws.search("x", glob=g)
        with _pt.raises(WorkspaceViolation):
            ws.list("", glob=g)
    # legit globs still work
    assert ws.search("hello", glob="**/*.md")
    assert ws.list("", glob="**/*.md") == ["in.md"]


def test_delete_root_blocked(tmp_path):
    ws = _ws(tmp_path)
    ws.write("keep.md", "x")
    import pytest as _pt
    for p in ("", ".", "./"):
        with _pt.raises(WorkspaceViolation):
            ws.delete(p)
    assert ws.exists("keep.md") and tmp_path.exists()


def test_edit_negative_count_clamped(tmp_path):
    ws = _ws(tmp_path)
    ws.write("a.md", "l l l")
    r = ws.edit("a.md", "l", "L", count=-5)   # negative must not replace-all-misreport
    assert r["replacements"] >= 0 and ws.read("a.md").count("L") == 3


# ── U10: NEW GET /{name}/indexes + write-gate (master-key) hardening ──────────
def test_router_indexes_listing(client, tmp_path):
    """GET /{name}/indexes enumerates the workspace's durable worklists with
    counts + completion — the Artifacts tab Workspaces pane consumes this."""
    import api.services.workspace as wsmod

    wsmod._registry = wsmod.WorkspaceRegistry(store_path=tmp_path / "reg.json")
    root = str(tmp_path / "idxproj")
    assert client.post("/api/workspaces", json={"name": "idxproj", "root": root}).status_code == 200

    # empty at first
    assert client.get("/api/workspaces/idxproj/indexes").json()["indexes"] == []

    # seed one index with two items
    client.post(
        "/api/workspaces/idxproj/index/sites/items",
        json={"items": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]},
    )
    listing = client.get("/api/workspaces/idxproj/indexes").json()["indexes"]
    assert len(listing) == 1
    row = listing[0]
    assert row["name"] == "sites"
    assert row["counts"]["pending"] == 2
    assert row["complete"] is False


def test_write_gate_no_op_when_auth_off(client, tmp_path):
    """With ENABLE_API_AUTH=false the master gate is a no-op — writes succeed
    without any Authorization header (the module-scoped client runs auth-off)."""
    import api.services.workspace as wsmod

    wsmod._registry = wsmod.WorkspaceRegistry(store_path=tmp_path / "reg2.json")
    root = str(tmp_path / "gate")
    assert client.post("/api/workspaces", json={"name": "gate", "root": root}).status_code == 200
    assert client.put(
        "/api/workspaces/gate/file", json={"path": "n.md", "content": "# n"}
    ).status_code == 200


def test_write_gate_requires_master_when_auth_on(tmp_path, monkeypatch):
    """With auth ON and no master key, every real write surface is 401'd while
    reads stay open. This is the U10 hardening on the REAL write endpoints
    (POST '', DELETE /{name}, PUT file, POST edit/expand, index mutations)."""
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    import importlib

    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    authed = TestClient(api.main.app)

    # writes → 401 (no key at all: base auth also blocks, but the gate is the
    # point — an unauth'd write never mutates the filesystem)
    assert authed.post("/api/workspaces", json={"name": "x", "root": str(tmp_path)}).status_code in (401, 403)
    assert authed.put("/api/workspaces/x/file", json={"path": "a.md", "content": "y"}).status_code in (401, 403)
    assert authed.post("/api/workspaces/x/edit", json={"path": "a.md", "find": "a", "replace": "b"}).status_code in (401, 403)
    assert authed.post("/api/workspaces/x/index/i/items", json={"items": []}).status_code in (401, 403)
    assert authed.delete("/api/workspaces/x").status_code in (401, 403)
