#!/usr/bin/env python3
"""
DmgDeployment — macOS DMG bundle deployed via py2app.

Detected when sys.frozen=True AND sys.platform=="darwin".

Storage layout:
    system  -> Enclave.app/Contents/Resources/ (read-only, in bundle)
    user    -> ~/Library/Application Support/Enclave/ (writable, persists)

No cgroup; effective memory = psutil host total minus 20% headroom for
macOS + other apps. No NVML / GPU concept on Mac.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import psutil

from ..deployment import (
    ConfigValidationResult,
    DeploymentMode,
    ResourceLimits,
)
from ...logging_config import logger

_HEADROOM_PCT = 0.20  # reserve 20% for OS + other apps


def _bundle_resources_path() -> Path:
    """Where the .app bundle's Resources/ directory lives.

    When py2app freezes the app, sys.executable resolves to
        /Applications/Enclave.app/Contents/MacOS/Enclave
    Resources sits at ../Resources/.
    """
    if getattr(sys, "frozen", False):
        macos_dir = Path(sys.executable).parent
        return macos_dir.parent / "Resources"
    # Not frozen (dev/test) — return a reasonable fallback
    return Path.cwd() / "_bundle_resources"


class DmgDeployment:
    """py2app bundle on macOS."""

    def __init__(
        self,
        user_root: Path,
        system_root: Path,
        ollama_url: str,
        host_total_bytes: int,
    ):
        self.mode = DeploymentMode.DMG_NATIVE
        self.user_storage_root = user_root
        self.system_storage_root = system_root
        self.storage_root = user_root  # alias for backward-compat
        self.ollama_url = ollama_url
        self.ollama_reachable = False  # set by Ollama probe later (Task 1.4d)
        host_gb = host_total_bytes / (1024**3)
        self.resource_limits = ResourceLimits(
            memory_gb=round(host_gb, 2),
            cpu_cores=float(psutil.cpu_count(logical=False) or 0),
            source="darwin_sysctl",
        )

    @classmethod
    def detect(cls) -> "DmgDeployment":
        user_root = Path.home() / "Library" / "Application Support" / "Enclave"
        system_root = _bundle_resources_path()
        ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        # Normalize OLLAMA_HOST: accept "host:port" or full URL
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
        """Host total minus 20% headroom for OS + other apps, minus any live
        MCP runner RSS (Phase 6) so the scheduler sees the true free budget."""
        if self.resource_limits.memory_gb is None:
            return 0.0
        base = self.resource_limits.memory_gb * (1 - _HEADROOM_PCT)
        from ..deployment import mcp_overhead_gb

        return round(max(0.0, base - mcp_overhead_gb()), 2)

    def daemon_env(self) -> Dict[str, str]:
        """Parse OLLAMA_* from process env."""
        return {k: v for k, v in os.environ.items() if k.startswith("OLLAMA_")}

    def recommended_env(self, arch: Any) -> Dict[str, Any]:
        """Mac DMG recommendations.

        - OLLAMA_HOST stays localhost (Ollama Mac app or bundled)
        - OLLAMA_MAX_LOADED_MODELS small (unified pool, conservative)
        - NO CUDA_* envs (no NVIDIA on Mac)
        """
        return {
            "OLLAMA_HOST": "127.0.0.1:11434",
            "OLLAMA_MAX_LOADED_MODELS": "3",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_KEEP_ALIVE": "5m",
            "CUDA_VISIBLE_DEVICES": None,  # MUST NOT be set
        }

    def validate_config(self, arch: Any) -> ConfigValidationResult:
        """Stub validator; full per-arch check lands in Phase 6."""
        warnings: List[dict] = []
        errors: List[dict] = []
        env = self.daemon_env()
        if env.get("CUDA_VISIBLE_DEVICES") is not None:
            warnings.append(
                {
                    "code": "arch_env_mismatch",
                    "message": "CUDA_VISIBLE_DEVICES set on macOS DMG (no NVIDIA on Mac)",
                    "setting": "CUDA_VISIBLE_DEVICES",
                }
            )
        return ConfigValidationResult(warnings=warnings, errors=errors)

    def ensure_user_storage(self) -> None:
        """Create user_storage_root subdirs with chmod 0700 if missing."""
        for sub in ("plugins", "mcp/binaries", "cache", "workflows", "config"):
            p = self.user_storage_root / sub
            p.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(p, 0o700)
            except OSError as e:
                logger.debug(f"chmod {p} failed: {e}")

    @classmethod
    def current(cls) -> "DmgDeployment":
        from ..deployment import _get_current

        return _get_current()  # type: ignore[return-value]
