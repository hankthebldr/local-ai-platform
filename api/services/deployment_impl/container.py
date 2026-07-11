#!/usr/bin/env python3
"""
ContainerDeployment — Docker/Podman with sibling Ollama service.

Detected when /.dockerenv exists OR /proc/1/cgroup mentions docker/podman/containerd.

Storage layout:
    system  -> /app/ (baked into image, read-only)
    user    -> /app/data/ (bind-mounted volume; persists across rebuilds)

cgroup-aware effective memory: respects memory.max (v2) or memory.limit_in_bytes (v1).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from ..deployment import (
    ConfigValidationResult,
    DeploymentMode,
    ResourceLimits,
)
from ...logging_config import logger

_CONTAINER_HEADROOM_PCT = 0.10  # cgroup already constrains; smaller margin


# ── cgroup probes (patched by mocks) ──────────────────────────────────────


def _cgroup_version() -> int:
    """Return 2 if cgroup v2, 1 if v1, 0 if undetected."""
    if Path("/sys/fs/cgroup/cgroup.controllers").exists():
        return 2
    if Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").exists():
        return 1
    return 0


def _read_cgroup_memory_max() -> Optional[int]:
    """Return cgroup memory limit in bytes, or None if no limit / unreadable.

    cgroup v2: /sys/fs/cgroup/memory.max ("max" string = no limit)
    cgroup v1: /sys/fs/cgroup/memory/memory.limit_in_bytes
               (a number close to 2**63 = no limit)
    """
    try:
        v2_path = Path("/sys/fs/cgroup/memory.max")
        if v2_path.exists():
            raw = v2_path.read_text().strip()
            if raw == "max":
                return None
            return int(raw)
        v1_path = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        if v1_path.exists():
            raw = v1_path.read_text().strip()
            value = int(raw)
            # cgroup v1 unlimited is a very large number; threshold conservatively
            if value > 2**62:
                return None
            return value
        return None
    except (OSError, ValueError) as e:
        logger.debug(f"cgroup memory probe failed: {e}")
        return None


def _user_storage_root() -> Path:
    """Container user-data root. /app/data is the bind-mount convention."""
    return Path("/app/data")


# ── Implementation ───────────────────────────────────────────────────────


class ContainerDeployment:
    """Docker/Podman container with sibling Ollama service."""

    def __init__(
        self,
        user_root: Path,
        system_root: Path,
        ollama_url: str,
        cgroup_memory_bytes: Optional[int],
        cgroup_version: int,
        host_total_bytes: int,
    ):
        self.mode = DeploymentMode.CONTAINER
        self.user_storage_root = user_root
        self.system_storage_root = system_root
        self.storage_root = user_root
        self.ollama_url = ollama_url
        self.ollama_reachable = False
        self._cgroup_bytes = cgroup_memory_bytes
        self._cgroup_version = cgroup_version
        self._host_total = host_total_bytes

        if cgroup_memory_bytes is not None:
            limit_gb = cgroup_memory_bytes / (1024**3)
            source = (
                f"cgroup_v{cgroup_version}" if cgroup_version in (1, 2) else "cgroup_v2"
            )
        else:
            limit_gb = host_total_bytes / (1024**3)
            source = "psutil_host"

        self.resource_limits = ResourceLimits(
            memory_gb=round(limit_gb, 2),
            cpu_cores=float(psutil.cpu_count(logical=False) or 0),
            source=source,
        )

    @classmethod
    def detect(cls) -> "ContainerDeployment":
        user_root = _user_storage_root()
        system_root = Path("/app")
        ollama_url = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
        if not ollama_url.startswith("http"):
            ollama_url = f"http://{ollama_url}"
        cgroup_bytes = _read_cgroup_memory_max()
        cgroup_ver = _cgroup_version()
        mem = psutil.virtual_memory()
        return cls(
            user_root=user_root,
            system_root=system_root,
            ollama_url=ollama_url,
            cgroup_memory_bytes=cgroup_bytes,
            cgroup_version=cgroup_ver,
            host_total_bytes=mem.total,
        )

    # ── runtime methods ─────────────────────────────────────────────────

    def effective_memory_gb(self) -> float:
        """cgroup limit (if any) with 10% headroom inside the container, minus
        any live MCP runner RSS (Phase 6) so the scheduler sees the true free
        budget."""
        from ..deployment import mcp_overhead_gb

        if self._cgroup_bytes is not None:
            base = (self._cgroup_bytes / (1024**3)) * (1 - _CONTAINER_HEADROOM_PCT)
        else:
            base = (self._host_total / (1024**3)) * (1 - _CONTAINER_HEADROOM_PCT)
        return round(max(0.0, base - mcp_overhead_gb()), 2)

    def daemon_env(self) -> Dict[str, str]:
        """Read OLLAMA_* from the container's env."""
        return {k: v for k, v in os.environ.items() if k.startswith("OLLAMA_")}

    def recommended_env(self, arch: Any) -> Dict[str, Any]:
        """Container recommendations vary by architecture class."""
        # Default container env
        env: Dict[str, Any] = {
            "OLLAMA_HOST": "http://ollama:11434",
            "OLLAMA_KEEP_ALIVE": "5m",
        }
        arch_name = getattr(arch, "name", None)
        arch_value = (
            getattr(arch_name, "value", str(arch_name)) if arch_name else "unknown"
        )

        if arch_value == "cpu_x86":
            env.update(
                {
                    "OLLAMA_MAX_LOADED_MODELS": "1",
                    "OLLAMA_NUM_PARALLEL": "1",
                    "OLLAMA_NUM_THREAD": "physical-core-count",
                }
            )
        elif arch_value == "gpu_nvidia_single":
            env.update(
                {
                    "OLLAMA_MAX_LOADED_MODELS": "2",
                    "OLLAMA_NUM_PARALLEL": "1",
                    "CUDA_VISIBLE_DEVICES": "0",
                }
            )
        elif arch_value == "gpu_nvidia_multi":
            gpu_count = getattr(arch, "pool_count", 2)
            env.update(
                {
                    "OLLAMA_SCHED_SPREAD": "1",  # required for multi-GPU parallelism
                    "OLLAMA_MAX_LOADED_MODELS": str(3 * gpu_count),
                    "OLLAMA_NUM_PARALLEL": "1",
                    "CUDA_VISIBLE_DEVICES": ",".join(str(i) for i in range(gpu_count)),
                }
            )
        return env

    def validate_config(self, arch: Any) -> ConfigValidationResult:
        """Stub validator; full per-arch×deployment matrix lands in Phase 6."""
        warnings: List[dict] = []
        errors: List[dict] = []
        env = self.daemon_env()
        arch_name = getattr(arch, "name", None)
        arch_value = (
            getattr(arch_name, "value", str(arch_name)) if arch_name else "unknown"
        )

        if arch_value == "gpu_nvidia_multi" and env.get("OLLAMA_SCHED_SPREAD") != "1":
            errors.append(
                {
                    "code": "missing_sched_spread",
                    "message": "OLLAMA_SCHED_SPREAD=1 required for multi-GPU parallelism",
                    "setting": "OLLAMA_SCHED_SPREAD",
                }
            )
        return ConfigValidationResult(warnings=warnings, errors=errors)

    def ensure_user_storage(self) -> None:
        for sub in ("plugins", "mcp/binaries", "cache", "workflows", "config",
                    "prompts/roles", "prompts/templates", "prompts/hooks", "tasks"):
            p = self.user_storage_root / sub
            try:
                p.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(p, 0o700)
            except OSError as e:
                logger.debug(f"mkdir {p} failed: {e}")

    @classmethod
    def current(cls) -> "ContainerDeployment":
        from ..deployment import _get_current

        return _get_current()  # type: ignore[return-value]
