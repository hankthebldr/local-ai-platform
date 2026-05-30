"""Phase 1.4 — plugins router: origin surfacing + install/delete endpoints.

The router instantiates its PluginService at import; we swap in a service over
tmp (system, user) layers and disable the master-key gate so we exercise the
endpoint wiring rather than auth.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routers.plugins as plugins_router
from api.services.plugin_service import PluginService


def _make_tarball(tmp_path: Path, plugin_id: str) -> Path:
    src = tmp_path / "src" / plugin_id
    src.mkdir(parents=True)
    (src / "plugin.yaml").write_text(
        f'id: {plugin_id}\nname: {plugin_id}\nversion: "1.0"\nskills: []\ntools: []\n'
    )
    tarball = tmp_path / f"{plugin_id}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    return tarball


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    system.mkdir(parents=True)
    user.mkdir(parents=True)
    ootb = system / "ootb"
    ootb.mkdir()
    (ootb / "plugin.yaml").write_text(
        'id: ootb\nname: OOTB\nversion: "1.0"\nskills: []\ntools: []\n'
    )
    svc = PluginService(system_dir=system, user_dir=user)
    svc.scan_plugins()
    monkeypatch.setattr(plugins_router, "plugin_service", svc)

    app = FastAPI()
    app.include_router(plugins_router.router)
    return TestClient(app)


def test_list_includes_origin(client):
    r = client.get("/api/plugins")
    assert r.status_code == 200
    body = r.json()
    assert all("origin" in p for p in body)
    assert {p["id"]: p["origin"] for p in body}["ootb"] == "system"


def test_install_endpoint_writes_user_plugin(client, tmp_path):
    tarball = _make_tarball(tmp_path, "uploaded")
    with open(tarball, "rb") as fh:
        r = client.post("/api/plugins/install", files={"plugin": fh})
    assert r.status_code == 200
    assert r.json()["installed"] == "uploaded"
    # Now discoverable via list as a user plugin.
    body = client.get("/api/plugins").json()
    assert {p["id"]: p["origin"] for p in body}["uploaded"] == "user"


def test_delete_user_plugin(client, tmp_path):
    with open(_make_tarball(tmp_path, "temp"), "rb") as fh:
        client.post("/api/plugins/install", files={"plugin": fh})
    r = client.delete("/api/plugins/temp")
    assert r.status_code == 200
    assert r.json()["deleted"] == "temp"


def test_delete_system_plugin_returns_403(client):
    r = client.delete("/api/plugins/ootb")
    assert r.status_code == 403
    assert "system-layer plugin cannot be deleted" in r.json()["detail"]


def test_delete_unknown_returns_404(client):
    r = client.delete("/api/plugins/ghost")
    assert r.status_code == 404


def test_install_bad_archive_returns_400(client, tmp_path):
    bad = tmp_path / "bad.tar.gz"
    src = tmp_path / "nope"
    src.mkdir()
    (src / "readme.md").write_text("not a plugin")
    with tarfile.open(bad, "w:gz") as tar:
        tar.add(src, arcname="nope")
    with open(bad, "rb") as fh:
        r = client.post("/api/plugins/install", files={"plugin": fh})
    assert r.status_code == 400
