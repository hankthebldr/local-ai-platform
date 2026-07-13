#!/usr/bin/env python3
"""LB5-U2 — plugin file management, versioning, reload flow.

Covers the spec's verify list:
  - system-layer file routes 403 (mirroring uninstall) — PUT and both GETs;
  - traversal rejected on every file route (../, encoded dot-dot, backslash,
    dot segments, bad charset) — this repo had a real glob-traversal
    incident, so every file-serving/file-writing route gets explicit tests;
  - malformed plugin.yaml save is a 400 (scan_plugins can't be broken);
  - version bumps ONCE per reload cycle across multiple saves;
  - explicit version (request body, or a changed version line inside a
    saved plugin.yaml) is always honored;
  - reload re-registers the edited skill on the live singleton;
  - tarball reinstall response carries {replaced_version};
  - writes and reads 401 with auth on and no key.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routers.plugins as plugins_router
from api.services.plugin_service import PluginService

SKILL_BODY = "---\nname: Hello\ninject: system\n---\n\nSay hello politely.\n"


def _make_plugin(base: Path, plugin_id: str, version: str = "0.1.0") -> Path:
    pdir = base / plugin_id
    (pdir / "skills").mkdir(parents=True)
    (pdir / "skills" / "hello.md").write_text(SKILL_BODY, encoding="utf-8")
    manifest = {
        "id": plugin_id,
        "name": plugin_id,
        "version": version,
        "skills": [
            {
                "id": "hello",
                "file": "skills/hello.md",
                "triggers": [{"keyword": "greet"}],
            }
        ],
        "tools": [],
    }
    (pdir / "plugin.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return pdir


def _make_tarball(tmp_path: Path, plugin_id: str, version: str) -> Path:
    src = tmp_path / "src" / plugin_id
    if src.exists():
        import shutil

        shutil.rmtree(src)
    src.mkdir(parents=True)
    (src / "plugin.yaml").write_text(
        f'id: {plugin_id}\nname: {plugin_id}\nversion: "{version}"\n'
        "skills: []\ntools: []\n"
    )
    tarball = tmp_path / f"{plugin_id}-{version}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    return tarball


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Real two-layer PluginService swapped onto the router singleton."""
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    system.mkdir(parents=True)
    user.mkdir(parents=True)
    _make_plugin(system, "ootb", version="1.0.0")
    _make_plugin(user, "mine", version="0.1.0")
    svc = PluginService(system_dir=system, user_dir=user)
    svc.scan_plugins()
    monkeypatch.setattr(plugins_router, "plugin_service", svc)

    app = FastAPI()
    app.include_router(plugins_router.router)
    return TestClient(app), svc, user


def _manifest_version(user: Path, plugin_id: str) -> str:
    doc = yaml.safe_load((user / plugin_id / "plugin.yaml").read_text())
    return str(doc.get("version"))


# ── Listing + reading ───────────────────────────────────────────────────────


def test_list_files_returns_relative_paths(env):
    client, _, _ = env
    r = client.get("/api/plugins/mine/files")
    assert r.status_code == 200
    body = r.json()
    assert body["plugin_id"] == "mine"
    assert body["layer"] == "user"
    assert body["version"] == "0.1.0"
    paths = [f["path"] for f in body["files"]]
    assert "plugin.yaml" in paths
    assert "skills/hello.md" in paths
    assert all(not p.startswith("/") and ".." not in p for p in paths)


def test_read_file_body(env):
    client, _, _ = env
    r = client.get("/api/plugins/mine/files/skills/hello.md")
    assert r.status_code == 200
    body = r.json()
    assert body["body"] == SKILL_BODY
    assert body["size"] == len(SKILL_BODY.encode("utf-8"))


def test_unknown_plugin_404(env):
    client, _, _ = env
    assert client.get("/api/plugins/ghost/files").status_code == 404
    assert client.get("/api/plugins/ghost/files/plugin.yaml").status_code == 404


def test_missing_file_404(env):
    client, _, _ = env
    assert client.get("/api/plugins/mine/files/skills/nope.md").status_code == 404


# ── System layer is read-only image content (403, mirroring uninstall) ─────


def test_system_layer_routes_403(env):
    client, _, _ = env
    assert client.get("/api/plugins/ootb/files").status_code == 403
    assert client.get("/api/plugins/ootb/files/plugin.yaml").status_code == 403
    r = client.put(
        "/api/plugins/ootb/files/skills/hello.md", json={"content": "hacked"}
    )
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"]


# ── Traversal (the real-incident class) ─────────────────────────────────────

BAD_PATHS = [
    "skills/%2e%2e/%2e%2e/%2e%2e/etc/passwd",  # encoded dot-dot escape
    "%2e%2e/secret.txt",  # encoded parent escape
    "skills/%2e/hello.md",  # encoded dot segment
    "skills%5Chello.md",  # backslash
    "skills/a%20b.md",  # space fails charset
    "skills/h%C3%A9llo.md",  # non-ascii fails charset
]


def test_traversal_rejected_on_read_and_write(env, tmp_path):
    client, _, _ = env
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    for bad in BAD_PATHS:
        r = client.get(f"/api/plugins/mine/files/{bad}")
        assert r.status_code == 400, f"GET {bad!r} should be rejected"
        r = client.put(f"/api/plugins/mine/files/{bad}", json={"content": "x"})
        assert r.status_code == 400, f"PUT {bad!r} should be rejected"
    assert outside.read_text() == "secret"


def test_traversal_rejected_at_service_layer_too(env):
    # Belt AND suspenders: even if a route regression let a dot-dot through,
    # the service containment check refuses to resolve outside the plugin dir.
    _, svc, _ = env
    with pytest.raises(ValueError):
        svc.read_file("mine", "../../etc/passwd")
    with pytest.raises(ValueError):
        svc.write_file("mine", "../evil.md", "x")


def test_bad_plugin_id_charset_400(env):
    client, _, _ = env
    assert client.get("/api/plugins/%2e%2e/files").status_code == 400


# ── plugin.yaml validation ──────────────────────────────────────────────────


def test_malformed_plugin_yaml_save_400(env):
    client, _, user = env
    before = (user / "mine" / "plugin.yaml").read_text()
    r = client.put(
        "/api/plugins/mine/files/plugin.yaml", json={"content": "id: [unclosed"}
    )
    assert r.status_code == 400
    r = client.put(
        "/api/plugins/mine/files/plugin.yaml", json={"content": "just a string"}
    )
    assert r.status_code == 400
    assert "mapping" in r.json()["detail"]
    # nothing was written — scan_plugins can't be broken by a bad edit
    assert (user / "mine" / "plugin.yaml").read_text() == before


# ── Version policy ──────────────────────────────────────────────────────────


def test_version_bumps_once_per_reload_cycle(env):
    client, _, user = env
    # first save since scan → patch bump 0.1.0 → 0.1.1
    r = client.put("/api/plugins/mine/files/skills/hello.md", json={"content": "one"})
    assert r.status_code == 200
    assert r.json() == {
        "saved": True,
        "plugin_id": "mine",
        "path": "skills/hello.md",
        "version": "0.1.1",
        "reload_required": True,
    }
    # second save in the same cycle → NO further bump
    r = client.put("/api/plugins/mine/files/skills/hello.md", json={"content": "two"})
    assert r.json()["version"] == "0.1.1"
    assert _manifest_version(user, "mine") == "0.1.1"
    # reload closes the cycle
    assert client.post("/api/plugins/reload").status_code == 200
    # next save opens a new cycle → 0.1.2
    r = client.put("/api/plugins/mine/files/skills/hello.md", json={"content": "three"})
    assert r.json()["version"] == "0.1.2"
    assert _manifest_version(user, "mine") == "0.1.2"


def test_explicit_version_in_body_honored(env):
    client, _, user = env
    r = client.put(
        "/api/plugins/mine/files/skills/hello.md",
        json={"content": "x", "version": "2.0.0"},
    )
    assert r.status_code == 200
    assert r.json()["version"] == "2.0.0"
    assert _manifest_version(user, "mine") == "2.0.0"
    # explicit version wins even in a dirty cycle
    r = client.put(
        "/api/plugins/mine/files/skills/hello.md",
        json={"content": "y", "version": "2.0.5"},
    )
    assert r.json()["version"] == "2.0.5"


def test_version_edited_inside_manifest_honored_no_bump(env):
    client, _, user = env
    manifest = yaml.safe_load((user / "mine" / "plugin.yaml").read_text())
    manifest["version"] = "3.1.4"
    r = client.put(
        "/api/plugins/mine/files/plugin.yaml",
        json={"content": yaml.safe_dump(manifest, sort_keys=False)},
    )
    assert r.status_code == 200
    assert r.json()["version"] == "3.1.4"
    assert _manifest_version(user, "mine") == "3.1.4"


def test_bad_version_string_rejected(env):
    client, _, _ = env
    r = client.put(
        "/api/plugins/mine/files/skills/hello.md",
        json={"content": "x", "version": 'evil"\nid: pwn'},
    )
    assert r.status_code == 400


# ── Reload flow ─────────────────────────────────────────────────────────────


def test_reload_reregisters_edited_skill_on_live_singleton(env):
    client, svc, _ = env
    new_body = "---\nname: Hello\ninject: system\n---\n\nZEBRA PROTOCOL.\n"
    r = client.put(
        "/api/plugins/mine/files/skills/hello.md", json={"content": new_body}
    )
    assert r.status_code == 200 and r.json()["reload_required"] is True
    # before reload the live registry still serves the old body
    assert "ZEBRA" not in svc.get_skill("mine", "hello")["content"]
    r = client.post("/api/plugins/reload")
    assert r.status_code == 200
    assert "ZEBRA PROTOCOL." in svc.get_skill("mine", "hello")["content"]
    # ...and the chat-path trigger match serves the edited content too
    matched = svc.get_skills("please greet the operator")
    assert any("ZEBRA" in s["content"] for s in matched)


def test_new_file_write_then_listed(env):
    client, _, user = env
    r = client.put(
        "/api/plugins/mine/files/skills/extra.md", json={"content": "# extra\n"}
    )
    assert r.status_code == 200
    assert (user / "mine" / "skills" / "extra.md").read_text() == "# extra\n"
    paths = [f["path"] for f in client.get("/api/plugins/mine/files").json()["files"]]
    assert "skills/extra.md" in paths


# ── Tarball reinstall surfaces the replaced version ─────────────────────────


def test_reinstall_response_carries_replaced_version(env, tmp_path):
    client, _, _ = env
    with open(_make_tarball(tmp_path, "dup", "1.2.0"), "rb") as fh:
        r = client.post("/api/plugins/install", files={"plugin": fh})
    assert r.status_code == 200
    assert r.json()["replaced_version"] is None
    # silent replace kept (only-add) — but the downgrade is now visible
    with open(_make_tarball(tmp_path, "dup", "1.0.0"), "rb") as fh:
        r = client.post("/api/plugins/install", files={"plugin": fh})
    assert r.status_code == 200
    assert r.json()["replaced_version"] == "1.2.0"
    assert r.json()["plugin"]["version"] == "1.0.0"


# ── Auth gate ───────────────────────────────────────────────────────────────


def test_file_routes_401_with_auth_on_and_no_key(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    assert client.get("/api/plugins/mine/files").status_code == 401
    assert client.get("/api/plugins/mine/files/plugin.yaml").status_code == 401
    r = client.put("/api/plugins/mine/files/skills/hello.md", json={"content": "x"})
    assert r.status_code == 401
