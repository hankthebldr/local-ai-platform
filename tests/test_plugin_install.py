"""Phase 1.4 — plugin install/uninstall against the writable user layer.

install_plugin extracts a tarball into the user layer and re-scans; uninstall
removes user-layer plugins but protects the read-only system layer.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from api.services.plugin_service import PluginService


def _make_plugin_tarball(
    tmp_path: Path, plugin_id: str, *, top_dir: str = None
) -> Path:
    """Build a minimal plugin tarball with a single top-level dir holding a
    plugin.yaml. Returns the tarball path."""
    src = tmp_path / "src" / (top_dir or plugin_id)
    src.mkdir(parents=True)
    (src / "plugin.yaml").write_text(
        f'id: {plugin_id}\nname: {plugin_id.title()}\nversion: "1.0"\n'
        "skills: []\ntools: []\n"
    )
    tarball = tmp_path / f"{plugin_id}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    return tarball


@pytest.fixture
def service(tmp_path):
    system = tmp_path / "system" / "plugins"
    user = tmp_path / "user" / "plugins"
    system.mkdir(parents=True)
    # Ship one system plugin.
    ootb = system / "ootb"
    ootb.mkdir()
    (ootb / "plugin.yaml").write_text(
        'id: ootb\nname: OOTB\nversion: "1.0"\nskills: []\ntools: []\n'
    )
    svc = PluginService(system_dir=system, user_dir=user)
    svc.scan_plugins()
    return svc


def test_install_writes_to_user_layer(service, tmp_path):
    tarball = _make_plugin_tarball(tmp_path, "my-plugin")
    installed = service.install_plugin(tarball)
    assert installed["id"] == "my-plugin"
    assert installed["origin"] == "user"
    # Discoverable immediately after install.
    assert service.has_plugin("my-plugin")
    assert service.get_plugin("my-plugin")["origin"] == "user"


def test_install_rejects_archive_without_manifest(service, tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    (src / "readme.txt").write_text("no manifest here")
    tarball = tmp_path / "empty.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(src, arcname="empty")
    with pytest.raises(ValueError, match="no plugin.yaml"):
        service.install_plugin(tarball)


def test_install_rejects_path_traversal(service, tmp_path):
    tarball = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.yaml"
    payload.write_text("id: evil\n")
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(payload, arcname="../escape/plugin.yaml")
    with pytest.raises(ValueError, match="unsafe path"):
        service.install_plugin(tarball)


def test_uninstall_user_plugin(service, tmp_path):
    tarball = _make_plugin_tarball(tmp_path, "removable")
    service.install_plugin(tarball)
    assert service.has_plugin("removable")
    service.uninstall_plugin("removable")
    assert not service.has_plugin("removable")


def test_uninstall_system_plugin_forbidden(service):
    with pytest.raises(PermissionError, match="system-layer plugin cannot be deleted"):
        service.uninstall_plugin("ootb")


def test_uninstall_unknown_raises_keyerror(service):
    with pytest.raises(KeyError):
        service.uninstall_plugin("does-not-exist")


def test_reinstall_overwrites_existing_user_plugin(service, tmp_path):
    service.install_plugin(_make_plugin_tarball(tmp_path, "dup"))
    # A second install of the same id must not raise and must still resolve.
    again = _make_plugin_tarball(tmp_path / "v2", "dup")
    installed = service.install_plugin(again)
    assert installed["id"] == "dup"
    assert service.has_plugin("dup")
