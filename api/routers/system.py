#!/usr/bin/env python3
"""
System router — exposes architecture / deployment / pressure detection state.

Endpoints (all read-only except refresh):
    GET  /api/system/architecture        — Detected arch + deployment + ollama triple
    GET  /api/system/deployment          — Deployment-only details
    GET  /api/system/pressure            — Current pressure-poller snapshot
    POST /api/system/architecture/refresh — Force re-detection (admin)

Read endpoints are intentionally unauthenticated so health checks and
the operator UI can call them without an API key. The refresh endpoint
remains unauthenticated for v1 — Phase 6 may gate it behind master key.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ..logging_config import logger
from ..services.architecture import detect_architecture, probe_ollama_version
from ..services.deployment import detect_deployment

router = APIRouter(prefix="/api/system", tags=["system"])


# ── Helpers ──────────────────────────────────────────────────────────────


def _arch_payload(arch) -> Dict[str, Any]:
    """Serialize an Architecture singleton for API response."""
    payload = {
        "name": arch.name.value,
        "memory_model": arch.memory_model,
        "pool_count": arch.pool_count,
        "total_memory_gb": arch.total_memory_gb,
        "per_pool_gb": list(arch.per_pool_gb),
        "warm_reload_cost_class": arch.warm_reload_cost_class,
        "failure_class": arch.failure_class,
        "supports_placement": arch.supports_placement,
        "bandwidth_estimate_gbps": arch.bandwidth_estimate_gbps,
    }
    # NVIDIA arches expose extra fields
    if hasattr(arch, "gpus"):
        payload["gpus"] = arch.gpus
    if hasattr(arch, "nvlink_topology"):
        payload["nvlink_topology"] = [list(p) for p in arch.nvlink_topology]
    if hasattr(arch, "driver_version"):
        payload["driver_version"] = arch.driver_version
    return payload


def _deployment_payload(deployment) -> Dict[str, Any]:
    """Serialize a Deployment singleton for API response."""
    return {
        "mode": deployment.mode.value,
        "storage_root": str(deployment.storage_root),
        "system_storage_root": str(deployment.system_storage_root),
        "user_storage_root": str(deployment.user_storage_root),
        "ollama_url": deployment.ollama_url,
        "ollama_reachable": deployment.ollama_reachable,
        "effective_memory_gb": deployment.effective_memory_gb(),
        "resource_limits": {
            "memory_gb": deployment.resource_limits.memory_gb,
            "cpu_cores": deployment.resource_limits.cpu_cores,
            "source": deployment.resource_limits.source,
        },
    }


def _ollama_payload(probe_result: Dict[str, Any]) -> Dict[str, Any]:
    """Re-shape probe_ollama_version output for the API response."""
    return {
        "version": probe_result.get("version"),
        "reachable": probe_result.get("reachable", False),
        "meets_floor": probe_result.get("meets_floor", False),
        "floor": probe_result.get("floor"),
    }


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/architecture")
def get_architecture() -> Dict[str, Any]:
    """Return the (arch, deployment, ollama) triple.

    Reads the current singletons. Calls probe_ollama_version() each request
    so the ollama.reachable signal is fresh.
    """
    from ..services.architecture import _get_current as _get_arch
    from ..services.deployment import _get_current as _get_deployment

    try:
        arch = _get_arch()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        deployment = _get_deployment()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    ollama_probe = probe_ollama_version(strict=False)

    return {
        "arch": _arch_payload(arch),
        "deployment": _deployment_payload(deployment),
        "ollama": _ollama_payload(ollama_probe),
    }


@router.get("/deployment")
def get_deployment() -> Dict[str, Any]:
    """Return deployment-only details."""
    from ..services.deployment import _get_current as _get_deployment

    try:
        deployment = _get_deployment()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return _deployment_payload(deployment)


@router.get("/pressure")
def get_pressure() -> Dict[str, Any]:
    """Return the current architecture pressure snapshot."""
    from ..services.architecture import _get_current as _get_arch

    try:
        arch = _get_arch()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    snap = arch.snapshot()
    return snap.model_dump() if hasattr(snap, "model_dump") else snap.dict()


@router.post("/architecture/refresh")
def refresh_architecture() -> Dict[str, Any]:
    """Force re-detection of architecture + deployment.

    Useful after operator changes (e.g. installs an NVIDIA driver, attaches
    a GPU, modifies cgroup limits). Returns the new triple.
    """
    deployment = detect_deployment()
    arch = detect_architecture(strict=False)
    ollama_probe = probe_ollama_version(strict=False)

    logger.info(
        "System refresh: arch=%s deployment=%s ollama=%s",
        arch.name.value,
        deployment.mode.value,
        ollama_probe.get("version"),
    )
    return {
        "arch": _arch_payload(arch),
        "deployment": _deployment_payload(deployment),
        "ollama": _ollama_payload(ollama_probe),
    }
