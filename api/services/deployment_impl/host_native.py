#!/usr/bin/env python3
"""
HostNativeDeployment — bare-metal `python api/main.py` on Linux or Mac.

Detected when no container markers AND not py2app-frozen.

Storage layout:
    system  -> cwd (the source checkout) — read-only by convention
    user    -> ~/.enclave/ (writable, persists)

No cgroup; effective memory = psutil host total minus 20% headroom.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import psutil

from ..deployment import (
    ConfigValidationResult,
    DeploymentMode,
    ResourceLimits,
)
from ...logging_config import logger

_HEADROOM_PCT = 0.20


class HostNativeDeployment:
    """Bare-metal Linux or Mac, no container."""

    def __init__(
        self,
        user_root: Path,
        system_root: Path,
        ollama_url: str,
        host_total_bytes: int,
    ):
        self.mode = DeploymentMode.HOST_NATIVE
        self.user_storage_root = user_root
        self.system_storage_root = system_root
        self.storage_root = user_root
        self.ollama_url = ollama_url
        self.ollama_reachable = False
        host_gb = host_total_bytes / (1024**3)
        self.resource_limits = ResourceLimits(
            memory_gb=round(host_gb, 2),
            cpu_cores=float(psutil.cpu_count(logical=False) or 0),
            source="psutil_host",
        )

    @classmethod
    def detect(cls) -> "HostNativeDeployment":
        user_root = Path.home() / ".enclave"
        system_root = Path(os.getcwd())
        ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        if not ollama_url.startswith("http"):
            ollama_url = f"http://{ollama_url}"
        mem = psutil.virtual_memory()
        return cls(
            user_root=user_root,
            system_root=system_root,
            ollama_url=ollama_url,
            host_total_bytes=mem.total,
        )

    # ── runtime methods ─────────────────────────────────────────────────

    def effective_memory_gb(self) -> float:
        """Host total minus 20% headroom, minus any live MCP runner RSS
        (Phase 6) so the scheduler sees the true free budget."""
        if self.resource_limits.memory_gb is None:
            return 0.0
        base = self.resource_limits.memory_gb * (1 - _HEADROOM_PCT)
        from ..deployment import mcp_overhead_gb

        return round(max(0.0, base - mcp_overhead_gb()), 2)

    def daemon_env(self) -> Dict[str, str]:
        return {k: v for k, v in os.environ.items() if k.startswith("OLLAMA_")}

    def recommended_env(self, arch: Any) -> Dict[str, Any]:
        """Mirror the container recommendations per architecture."""
        env: Dict[str, Any] = {
            "OLLAMA_HOST": "127.0.0.1:11434",
            "OLLAMA_KEEP_ALIVE": "5m",
        }
        arch_name = getattr(arch, "name", None)
        arch_value = (
            getattr(arch_name, "value", str(arch_name)) if arch_name else "unknown"
        )

        if arch_value == "apple_unified":
            env.update(
                {
                    "OLLAMA_MAX_LOADED_MODELS": "3",
                    "OLLAMA_NUM_PARALLEL": "1",
                    "CUDA_VISIBLE_DEVICES": None,
                }
            )
        elif arch_value == "cpu_x86":
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
                }
            )
        elif arch_value == "gpu_nvidia_multi":
            gpu_count = getattr(arch, "pool_count", 2)
            env.update(
                {
                    "OLLAMA_SCHED_SPREAD": "1",
                    "OLLAMA_MAX_LOADED_MODELS": str(3 * gpu_count),
                    "OLLAMA_NUM_PARALLEL": "1",
                }
            )
        return env

    def validate_config(self, arch: Any) -> ConfigValidationResult:
        warnings: List[dict] = []
        errors: List[dict] = []
        return ConfigValidationResult(warnings=warnings, errors=errors)

    def ensure_user_storage(self) -> None:
        for sub in ("plugins", "mcp/binaries", "cache", "workflows", "config",
                    "prompts/roles", "prompts/templates", "tasks"):
            p = self.user_storage_root / sub
            try:
                p.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(p, 0o700)
            except OSError as e:
                logger.debug(f"mkdir {p} failed: {e}")

    @classmethod
    def current(cls) -> "HostNativeDeployment":
        from ..deployment import _get_current

        return _get_current()  # type: ignore[return-value]
