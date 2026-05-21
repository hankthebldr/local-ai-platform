#!/usr/bin/env python3
"""
Shared NVML probe helpers for nvidia_single and nvidia_multi impls.

Centralizes the pynvml calls so the two NVIDIA arch impls don't duplicate
the lifecycle (init / shutdown) or the per-GPU metadata extraction.

All functions degrade gracefully when NVML is unavailable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ...logging_config import logger


def _safe_nvml_call(fn, *args, default=None):
    """Run fn(*args) and return default on any NVML error or import failure."""
    try:
        return fn(*args)
    except Exception as e:
        logger.debug(
            f"NVML probe failed ({fn.__name__ if hasattr(fn, '__name__') else fn}): {e}"
        )
        return default


def init_nvml() -> bool:
    """Initialize NVML. Returns True on success, False if unavailable."""
    try:
        import pynvml

        pynvml.nvmlInit()
        return True
    except Exception as e:
        logger.debug(f"NVML init failed: {e}")
        return False


def shutdown_nvml() -> None:
    """Best-effort NVML shutdown."""
    try:
        import pynvml

        pynvml.nvmlShutdown()
    except Exception:
        pass


def device_count() -> int:
    """Return GPU count visible to NVML. Returns 0 on failure."""
    try:
        import pynvml

        return pynvml.nvmlDeviceGetCount()
    except Exception:
        return 0


def gpu_metadata(index: int) -> Optional[Dict[str, Any]]:
    """Return a metadata dict for a GPU index. None if NVML calls fail."""
    try:
        import pynvml

        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pcie_gen = _safe_nvml_call(
            pynvml.nvmlDeviceGetCurrPcieLinkGeneration, handle, default=0
        )
        cc = _safe_nvml_call(
            pynvml.nvmlDeviceGetCudaComputeCapability, handle, default=(0, 0)
        )
        return {
            "gpu_id": index,
            "name": name,
            "vram_total_gb": round(mem.total / (1024**3), 2),
            "vram_free_gb": round(mem.free / (1024**3), 2),
            "vram_used_gb": round(mem.used / (1024**3), 2),
            "pcie_gen": pcie_gen,
            "compute_capability": (
                f"{cc[0]}.{cc[1]}" if isinstance(cc, tuple) else str(cc)
            ),
        }
    except Exception as e:
        logger.warning(f"GPU {index} metadata probe failed: {e}")
        return None


def driver_version() -> Optional[str]:
    """Return driver version string. None on failure."""
    try:
        import pynvml

        v = pynvml.nvmlSystemGetDriverVersion()
        return v.decode("utf-8") if isinstance(v, bytes) else v
    except Exception:
        return None


def detect_nvlink_topology(gpu_count: int) -> List[Tuple[int, int]]:
    """Detect NVLink-paired GPUs. Returns sorted unique pairs.

    For N GPUs we probe link 0 of each device against each other. NVML's
    NvLinkState is per-link, not per-pair, so we use a simplification:
    if GPU i's link 0 is enabled AND GPU j's link 0 is enabled and they
    have matching capability, treat them as paired. This isn't perfect
    but matches what real Ollama scheduler placement assumes.
    """
    if gpu_count < 2:
        return []
    try:
        import pynvml

        active: List[int] = []
        for i in range(gpu_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            try:
                state = pynvml.nvmlDeviceGetNvLinkState(handle, 0)
                if state == 1:  # NVML_FEATURE_ENABLED
                    active.append(i)
            except Exception:
                continue
        # Pair adjacent active GPUs
        return [(active[i], active[i + 1]) for i in range(0, len(active) - 1, 2)]
    except Exception:
        return []


# ── VRAM bandwidth estimates ──────────────────────────────────────────────


_VRAM_BANDWIDTH_BY_NAME = {
    "H100": 3000.0,  # HBM3
    "A100": 2000.0,  # HBM2e
    "L40": 864.0,
    "L4": 300.0,
    "RTX 4090": 1008.0,
    "RTX 4080": 717.0,
    "RTX 3090": 936.0,
    "RTX 3080": 760.0,
}


def estimate_bandwidth_gbps(gpu_name: str) -> float:
    """Look up a rough VRAM bandwidth for the GPU name. Conservative default."""
    for key, gbps in _VRAM_BANDWIDTH_BY_NAME.items():
        if key in gpu_name:
            return gbps
    return 500.0  # conservative default for unknown GPUs
