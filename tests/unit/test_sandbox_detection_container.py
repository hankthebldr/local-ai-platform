"""Task 15: detection wires Tier-2 container backend when a runtime is present."""
from __future__ import annotations


def test_detection_registers_container_when_runtime_present(monkeypatch):
    import api.services.sandbox_detection as det

    monkeypatch.setattr(
        det.shutil,
        "which",
        lambda name: "/usr/bin/podman" if name == "podman" else None,
    )
    reg = det.detect_sandboxes()
    names = [b.name for b in reg.backends()]
    assert "container" in names
    # strongest-first: container (tier 2) resolves ahead of subprocess (tier 1)
    assert reg.resolve(override=None).name == "container"
