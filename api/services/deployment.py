#!/usr/bin/env python3
"""
Deployment Service — process / packaging abstraction layer.

Orthogonal to Architecture (memory model). Detects whether Enclave is
running as a DMG bundle, inside a container, or as a bare-metal host
process. Each mode has different resource visibility (psutil vs cgroup),
different storage paths, and different Ollama integration shape.

Three modes:
    dmg_native    — py2app bundle on macOS
    container     — Docker/Podman with sibling Ollama service
    host_native   — `python api/main.py` directly on Linux or Mac

This module defines the Protocol and supporting Pydantic models only.
Concrete implementations live in api/services/deployment_impl/.

See docs/plans/2026-05-19-architecture-aware-orchestration-design.md
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, List, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────


class DeploymentMode(str, Enum):
    """Closed set of supported deployment modes."""

    DMG_NATIVE = "dmg_native"
    CONTAINER = "container"
    HOST_NATIVE = "host_native"


# ── Resource accounting ───────────────────────────────────────────────────


ResourceLimitSource = Literal[
    "cgroup_v1",
    "cgroup_v2",
    "psutil_host",
    "darwin_sysctl",
    "unlimited",
]


class ResourceLimits(BaseModel):
    """What memory / CPU the process actually has access to.

    For container deployments, this respects cgroup limits even when the
    host has more available. For DMG and host_native, this is the host's
    psutil-reported total (minus configured headroom).

    None values mean "no enforced limit detected" — the engine treats
    the host's psutil reading as the budget.
    """

    memory_gb: Optional[float]
    cpu_cores: Optional[float]
    source: ResourceLimitSource


# ── Config validation ─────────────────────────────────────────────────────


Severity = Literal["error", "warning", "info"]


class ConfigIssue(BaseModel):
    """One configuration discrepancy surfaced by the validator."""

    code: str
    message: str
    severity: Severity = "warning"
    setting: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None


class ConfigValidationResult(BaseModel):
    """Output of Deployment.validate_config(arch).

    The api/main.py startup hook reads this; in STRICT_CONFIG_VALIDATION
    mode any errors block startup. Otherwise warnings + errors are logged
    and surfaced at /api/system/health.
    """

    warnings: List[dict] = Field(default_factory=list)
    errors: List[dict] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.warnings and not self.errors

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


# ── Protocol ──────────────────────────────────────────────────────────────


@runtime_checkable
class Deployment(Protocol):
    """The capability interface every deployment-mode impl satisfies."""

    # ── identity ───
    mode: DeploymentMode

    # ── storage layout (used by PluginService, MCPService, run records) ───
    storage_root: Path  # where data/ lives; alias for user_storage_root
    system_storage_root: Path  # read-only OOTB plugins/binaries; ships with app/image
    user_storage_root: Path  # writable; persists across DMG/container updates

    # ── ollama integration ───
    ollama_url: str
    ollama_reachable: bool

    # ── resource accounting ───
    resource_limits: ResourceLimits

    # ── runtime methods ───
    def effective_memory_gb(self) -> float:
        """Effective memory budget for model + KV cache.

        For container: respects cgroup limits (cgroup memory.max wins
        over host total). For DMG / host_native: psutil host total
        minus configured headroom (default 20%).
        """
        ...

    def daemon_env(self) -> dict:
        """Best-effort read of Ollama daemon's environment.

        Container: read from container env. DMG / host_native: parse
        OLLAMA_* from os.environ. Returns {} if introspection fails.
        """
        ...

    def recommended_env(self, arch: Any) -> dict:
        """Per-(arch × deployment) recommended Ollama env settings.

        Source of truth for the config validator. Each entry maps
        env var name → expected value or None (meaning "should not be set").
        """
        ...

    def validate_config(self, arch: Any) -> ConfigValidationResult:
        """Compare daemon_env() against recommended_env(arch); produce
        a typed validation result. Called at startup by api/main.py.
        """
        ...

    def ensure_user_storage(self) -> None:
        """Create user_storage_root/{plugins,mcp/binaries,cache,workflows}
        with chmod 0700 if any are missing. Idempotent.
        """
        ...


# ── Singleton state ───────────────────────────────────────────────────────


_current_deployment: Optional[Deployment] = None


def _set_current(deployment: Deployment) -> None:
    """Used by detect_deployment(). Not part of the public API."""
    global _current_deployment
    _current_deployment = deployment


def _get_current() -> Deployment:
    if _current_deployment is None:
        raise RuntimeError(
            "Deployment.current() called before detect_deployment(). "
            "Call detect_deployment() during app startup (api/main.py)."
        )
    return _current_deployment


# Attach `current()` as an ergonomic class-level accessor on the Protocol.
def _dep_current_static() -> "Deployment":
    return _get_current()


Deployment.current = staticmethod(_dep_current_static)  # type: ignore[attr-defined]


# ── Top-level detector ────────────────────────────────────────────────────


def detect_deployment() -> Deployment:
    """Detect the deployment mode and install it as the singleton.

    Decision tree (checked in order):
        1. /.dockerenv exists OR /proc/1/cgroup mentions container runtime
           → ContainerDeployment
        2. sys.frozen == True AND sys.platform == "darwin"
           → DmgDeployment
        3. Else → HostNativeDeployment

    Container is checked first because Docker Desktop on Mac sets both
    /.dockerenv (inside the VM) and sys.platform == "darwin" (host process).
    The container detection wins; the arch detector handles the Linux-VM
    side of that case.

    Idempotent: calling repeatedly replaces the singleton.
    """
    import sys

    # 1. Container check
    if _is_container():
        from .deployment_impl.container import ContainerDeployment

        deployment: Deployment = ContainerDeployment.detect()
        _set_current(deployment)
        return deployment

    # 2. DMG check (py2app frozen on Mac)
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        from .deployment_impl.dmg import DmgDeployment

        deployment = DmgDeployment.detect()
        _set_current(deployment)
        return deployment

    # 3. Host native default
    from .deployment_impl.host_native import HostNativeDeployment

    deployment = HostNativeDeployment.detect()
    _set_current(deployment)
    return deployment


def _is_container() -> bool:
    """Return True if running inside a container.

    Checks /.dockerenv (Docker convention) and /proc/1/cgroup (podman/
    containerd). Either signal flags container.
    """
    import os

    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup") as f:
            content = f.read()
        return any(marker in content for marker in ("docker", "podman", "containerd"))
    except (FileNotFoundError, PermissionError, OSError):
        return False
