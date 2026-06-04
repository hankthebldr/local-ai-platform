import pytest
from api.services.sandbox import SandboxKind
from api.services.sandbox_registry import SandboxRegistry, SandboxNotAvailable
from api.services.sandbox_impl.subprocess import SubprocessSandbox


def test_resolve_strongest_then_downgrade():
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())
    assert reg.resolve(override=None).name == "subprocess"
    with pytest.raises(SandboxNotAvailable):
        reg.resolve(override="container")


def test_detection_always_has_subprocess(monkeypatch):
    import api.services.sandbox_detection as det

    monkeypatch.setattr(det.shutil, "which", lambda _: None)  # no podman/docker
    reg = det.detect_sandboxes()
    assert SandboxKind.SUBPROCESS.value in [b.name for b in reg.backends()]
