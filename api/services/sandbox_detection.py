from __future__ import annotations

import os
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

    # Tier-3 NVIDIA OpenShell — OPT-IN only. The registry auto-prefers the
    # highest tier, so we don't let an alpha runtime silently hijack code-exec:
    # the operator must set ENCLAVE_ENABLE_OPENSHELL=true AND the `openshell`
    # binary must be present + answer a version probe. Otherwise it's a no-op.
    if os.getenv("ENCLAVE_ENABLE_OPENSHELL", "").lower() in ("1", "true", "yes"):
        from .sandbox_impl.openshell import OpenShellSandbox

        binary = os.getenv("OPENSHELL_BIN", "openshell")
        if shutil.which(binary):
            backend = OpenShellSandbox(binary=binary)
            ok, detail = backend.ping()
            if ok:
                reg.register(backend)
                logger.info(
                    "  📦 Sandbox:      + openshell tier-3 (%s) [DEFAULT]", detail
                )
            else:
                logger.warning(
                    "  📦 Sandbox:      openshell enabled but probe failed (%s) — "
                    "not registered",
                    detail,
                )
        else:
            logger.warning(
                "  📦 Sandbox:      ENCLAVE_ENABLE_OPENSHELL set but '%s' not on "
                "PATH — not registered",
                binary,
            )

    _set_current(reg)
    return reg
