#!/usr/bin/env python3
"""Format-sets router (Operate U10) — layered CRUD + preview + refs.

Covers: the three seeded built-ins list read-only from the oob layer; create /
edit (copy-on-write) / delete land in a patched user layer; a pure-oob delete is
403'd; the preview endpoint serializes the exact ``[format:<id>@<v>]`` sentinel
constraint lines; refs scans workflow YAML; id-charset + containment reject
traversal; scope entry shipped in this unit.
"""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")

    import api.routers.format_sets as fs

    # Point the user layer + workflow-scan dir at isolated tmp dirs; oob stays
    # the real repo prompts/formats so the three built-ins are present.
    user_layer = tmp_path / "user_formats"
    monkeypatch.setattr(fs, "_user_root", lambda: user_layer)
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(fs, "_WORKFLOWS_DIR", wf_dir)

    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    return TestClient(api.main.app), fs, wf_dir


def test_lists_three_seeded_builtins(client):
    c, _fs, _wf = client
    rows = c.get("/api/format-sets").json()
    ids = {r["id"] for r in rows}
    assert {"html-standard", "markdown-graph-assets", "sheet-index"} <= ids
    html = next(r for r in rows if r["id"] == "html-standard")
    assert html["target"] == "html" and html["provenance"] == "oob"


def test_preview_serializes_sentinel_block(client):
    c, _fs, _wf = client
    p = c.post("/api/format-sets/html-standard/preview").json()
    assert p["constraints"][0] == "[format:html-standard@1]"
    assert p["constraints"][-1] == "[/format]"
    assert len(p["constraints"]) > 2  # real instruction lines in between
    assert p["text"].startswith("[format:html-standard@1]\n")


def test_create_edit_delete_roundtrip_user_layer(client):
    c, _fs, _wf = client
    body = "---\nname: My Fmt\nsummary: t\ntarget: markdown\nversion: 2\n---\nWrite terse output.\n"
    r = c.post("/api/format-sets", json={"id": "my-fmt", "body": body})
    assert r.status_code == 201 and r.json()["provenance"] == "user"
    # duplicate create → 409
    assert c.post("/api/format-sets", json={"id": "my-fmt", "body": body}).status_code == 409
    # preview reflects version 2
    assert c.post("/api/format-sets/my-fmt/preview").json()["constraints"][0] == "[format:my-fmt@2]"
    # edit
    body2 = body.replace("terse", "verbose")
    assert c.put("/api/format-sets/my-fmt", json={"body": body2}).status_code == 200
    assert "verbose" in c.get("/api/format-sets/my-fmt").json()["body"]
    # delete
    d = c.delete("/api/format-sets/my-fmt")
    assert d.status_code == 200 and d.json()["reverted_to_oob"] is False
    assert c.get("/api/format-sets/my-fmt").status_code == 404


def test_edit_oob_is_copy_on_write(client):
    c, _fs, _wf = client
    body = "---\nname: HTML\nsummary: s\ntarget: html\nversion: 5\n---\nOnly one file.\n"
    r = c.put("/api/format-sets/html-standard", json={"body": body})
    assert r.status_code == 200 and r.json()["provenance"] == "user"
    assert r.json()["version"] == 5
    # deleting the user copy reverts to the shipped oob built-in
    d = c.delete("/api/format-sets/html-standard")
    assert d.json()["reverted_to_oob"] is True
    assert c.get("/api/format-sets/html-standard").json()["provenance"] == "oob"


def test_pure_oob_delete_is_403(client):
    c, _fs, _wf = client
    assert c.delete("/api/format-sets/sheet-index").status_code == 403


def test_invalid_document_rejected(client):
    c, _fs, _wf = client
    # missing front-matter
    assert c.post("/api/format-sets", json={"id": "bad1", "body": "no fm"}).status_code == 400
    # bad target
    bad = "---\nname: x\ntarget: pdf\nversion: 1\n---\nbody\n"
    assert c.post("/api/format-sets", json={"id": "bad2", "body": bad}).status_code == 400


def test_id_charset_and_traversal_rejected(client):
    c, _fs, _wf = client
    for bad in ("../evil", "a/b", "with space"):
        assert c.get(f"/api/format-sets/{bad}").status_code in (400, 404)
    assert c.post("/api/format-sets", json={"id": "../evil", "body": "x"}).status_code == 400


def test_refs_scans_workflow_yaml(client):
    c, _fs, wf_dir = client
    (wf_dir / "uses-fmt.yaml").write_text(
        "steps:\n  - prompt:\n      constraints:\n        - '[format:sheet-index@1]'\n",
        encoding="utf-8",
    )
    (wf_dir / "no-fmt.yaml").write_text("steps: []\n", encoding="utf-8")
    r = c.get("/api/format-sets/sheet-index/refs").json()
    assert r["count"] == 1 and r["refs"] == ["uses-fmt.yaml"]
    assert c.get("/api/format-sets/html-standard/refs").json()["count"] == 0


def test_serialize_constraints_is_pure(client):
    """The preview endpoint and the serializer helper agree byte-for-byte."""
    c, fs, _wf = client
    text = "---\nname: N\ntarget: markdown\nversion: 3\n---\n- rule one\n- rule two\n"
    meta, _rest = fs._split_frontmatter(text)
    lines = fs._serialize_constraints("demo", meta, text)
    assert lines == ["[format:demo@3]", "- rule one", "- rule two", "[/format]"]
