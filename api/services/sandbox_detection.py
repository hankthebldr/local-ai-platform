from __future__ import annotations

import shutil

from ..logging_config import logger
from .sandbox_registry import SandboxRegistry, _set_current
from .sandbox_impl.subprocess import SubprocessSandbox


def detect_sandboxes() -> SandboxRegistry:
    reg = SandboxRegistry()
    reg.register(SubprocessSandbox())  # always available
    runtime = shutil.which("podman") or shutil.which("docker")
    if runtime:
        from .sandbox_impl.container import ContainerSandbox  # Task 15

        reg.register(ContainerSandbox(runtime=runtime))
        logger.info("  📦 Sandbox:      subprocess + container (%s)", runtime)
    else:
        logger.info("  📦 Sandbox:      subprocess only (no container runtime)")
    _set_current(reg)
    return reg
