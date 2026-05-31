#!/usr/bin/env python3
"""
System router — exposes architecture / deployment / pressure detection state.

Endpoints (all read-only except refresh):
    GET  /api/system/architecture           — Detected arch + deployment + ollama triple
    GET  /api/system/pressure               — Current pressure-poller snapshot
    POST /api/system/architecture/refresh   — Force re-detection (admin)
    GET  /api/system/health                 — Phase 6.3: arch + config_validation
    GET  /api/system/config/recommendations — Phase 6.3: env + compose/systemd snippets

The legacy /api/system/deployment endpoint was removed in PR #90 — its
payload was a strict subset of /api/system/architecture's `.deployment`
field. Callers should switch to `GET /api/system/architecture` and read
`response_json["deployment"]`.

Read endpoints are intentionally unauthenticated so health checks and
the operator UI can call them without an API key. The refresh endpoint
remains unauthenticated for v1 — Phase 6 may gate it behind master key.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ..logging_config import logger
from ..services.architecture import detect_architecture, probe_ollama_version
from ..services.deployment import DeploymentMode, detect_deployment

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
    from ..services.deployment import mcp_overhead_gb

    return {
        "mode": deployment.mode.value,
        "storage_root": str(deployment.storage_root),
        "system_storage_root": str(deployment.system_storage_root),
        "user_storage_root": str(deployment.user_storage_root),
        "ollama_url": deployment.ollama_url,
        "ollama_reachable": deployment.ollama_reachable,
        "effective_memory_gb": deployment.effective_memory_gb(),
        # Phase 6 — what the effective figure reflects. Operators inspecting
        # /api/system/architecture during a workflow with heavy MCPs should
        # see why the budget dropped.
        "mcp_overhead_gb": round(mcp_overhead_gb(), 3),
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


# ── Phase 6.3: Config validation surfaces ────────────────────────────────


@router.get("/health")
def system_health() -> Dict[str, Any]:
    """Phase 6.3 — health endpoint with arch + deployment + config validation.

    Distinct from the root /health endpoint (which is for liveness probes
    on docker/k8s). This one is operator-facing: it tells you whether your
    Ollama daemon environment matches the recommended settings for the
    detected (architecture, deployment) pair.

    Returns 200 even when config_validation has errors — the caller's job
    to act on them. STRICT_CONFIG_VALIDATION=true at startup is the gate
    that prevents the API from coming up in a misconfigured state.
    """
    from ..services.architecture import _get_current as _get_arch
    from ..services.config_validator import probe_daemon_env, validate_config
    from ..services.deployment import _get_current as _get_deployment

    payload: Dict[str, Any] = {"status": "ok"}
    try:
        arch = _get_arch()
        payload["arch"] = arch.name.value
    except RuntimeError:
        payload["arch"] = "unknown"
        payload["status"] = "degraded"
    try:
        deployment = _get_deployment()
        payload["deployment"] = deployment.mode.value
    except RuntimeError:
        payload["deployment"] = "unknown"
        payload["status"] = "degraded"

    if payload["arch"] != "unknown" and payload["deployment"] != "unknown":
        daemon_env = probe_daemon_env()
        result = validate_config(arch.name, deployment.mode, daemon_env)
        payload["config_validation"] = {
            "warnings": result.warnings,
            "errors": result.errors,
            "is_clean": result.is_clean,
            "probed_keys": sorted(daemon_env.keys()),
        }
        if result.errors:
            payload["status"] = "degraded"

    return payload


@router.get("/config/recommendations")
def config_recommendations() -> Dict[str, Any]:
    """Phase 6.3 — return recommended daemon env + deployment snippets
    for the detected (architecture, deployment) pair.

    Snippet generation is inline (Phase 6.3); Phase 6.4 ships parameterised
    templates under docs/deployment/templates/ that supersede the inline
    strings below.
    """
    from ..services.architecture import _get_current as _get_arch
    from ..services.config_validator import RECOMMENDATIONS
    from ..services.deployment import _get_current as _get_deployment

    try:
        arch = _get_arch()
        deployment = _get_deployment()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    recs = RECOMMENDATIONS.get((arch.name, deployment.mode), [])
    recommended_env: Dict[str, Optional[str]] = {}
    explanatory_notes: Dict[str, str] = {}
    for r in recs:
        if r.expected is not None:
            recommended_env[r.key] = r.expected
        if r.message:
            explanatory_notes[r.key] = r.message

    return {
        "arch": arch.name.value,
        "deployment": deployment.mode.value,
        "recommended_env": recommended_env,
        "explanatory_notes": explanatory_notes,
        "docker_compose_snippet": _compose_snippet(arch.name, deployment.mode, recs),
        "systemd_snippet": _systemd_snippet(arch.name, deployment.mode, recs),
    }


def _compose_snippet(arch_class, deployment_mode, recs) -> str:
    """Inline docker-compose env block for the detected arch × deployment."""
    if deployment_mode != DeploymentMode.CONTAINER:
        return (
            f"# (docker-compose not applicable to deployment={deployment_mode.value})"
        )

    env_lines = []
    for r in recs:
        if r.expected is None:
            continue
        # Use placeholder for fuzzy matchers
        value = r.expected
        if value == "physical-core-count":
            value = "${HOST_PHYS_CORES:-8}"
        elif value == "enumerate":
            value = "0,1"
        elif "-" in value and all(p.isdigit() for p in value.split("-")):
            value = value.split("-")[0]  # use the lower bound
        env_lines.append(f"      - {r.key}={value}")

    gpu_block = ""
    if arch_class.value.startswith("gpu_"):
        gpu_block = """
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]"""

    return (
        "services:\n"
        "  ollama:\n"
        "    image: ollama/ollama:0.23.4\n"
        "    environment:\n" + "\n".join(env_lines) + gpu_block
    )


def _systemd_snippet(arch_class, deployment_mode, recs) -> str:
    """Inline systemd override fragment for host-native deployments."""
    if deployment_mode != DeploymentMode.HOST_NATIVE:
        return f"# (systemd not applicable to deployment={deployment_mode.value})"

    env_lines = []
    for r in recs:
        if r.expected is None:
            continue
        value = r.expected
        if value == "physical-core-count":
            value = "$(nproc --all)"
        elif value == "enumerate":
            value = "0,1"
        elif "-" in value and all(p.isdigit() for p in value.split("-")):
            value = value.split("-")[0]
        env_lines.append(f'Environment="{r.key}={value}"')

    return (
        "# /etc/systemd/system/ollama.service.d/override.conf\n"
        "[Service]\n" + "\n".join(env_lines)
    )


# ── Extensions overview (Phase 7.1, MCP & Skills) ────────────────────────


@router.get("/extensions")
def get_extensions() -> Dict[str, Any]:
    """One-stop deployment-aware view of the extension subsystem.

    Surfaces, for the operator dashboard and `enclave status` CLI:
      - **deployment** mode (DMG / container / host_native)
      - **plugin paths** (system layer + writable user layer) — Phase 1
      - **MCP registry path** + binaries dir (the writable user-layer
        locations migrated to during Phase 1.3) and live runner pool
        state (Phase 2 / Phase 3)
      - **cache paths** under the user layer

    All paths are resolved from the active Deployment singleton so the
    answer is correct on every form factor. Tolerates a missing pool
    (no workflow has spawned a runner yet → empty active_runners).
    """
    from ..services.deployment import _get_current as _get_deployment

    try:
        d = _get_deployment()
    except RuntimeError:
        # detect_deployment() hasn't run yet — should be vanishingly rare in
        # practice (api/main.py calls it at startup), but tests sometimes
        # import this module before lifecycle setup.
        raise HTTPException(
            status_code=503,
            detail="deployment not initialized; call detect_deployment() at startup",
        )

    # MCP service path + binaries dir
    mcp_service_block: Dict[str, Any] = {}
    try:
        from ..services.mcp_service import get_mcp_service

        svc = get_mcp_service()
        mcp_service_block = {
            "registry_path": str(svc.storage_path),
            "binaries_dir": str(svc.binaries_dir),
            "registered_count": len(svc.list_servers()),
        }
    except Exception as exc:  # noqa: BLE001 - tolerate transient init failures
        logger.debug("mcp_service block skipped: %s", exc)
        mcp_service_block = {"error": str(exc)}

    # Live runner-pool stats
    pool_block: Dict[str, Any] = {}
    try:
        from ..services.mcp_runner_pool import get_mcp_runner_pool

        pool = get_mcp_runner_pool()
        pool_block = {
            "active_runners": pool.runner_count(),
            "total_overhead_mb": round(pool.total_runner_overhead_mb(), 2),
            "runners": pool.list_runners(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("runner_pool block skipped: %s", exc)
        pool_block = {"error": str(exc)}

    user_plugin_dir = d.user_storage_root / "plugins"
    return {
        "deployment": d.mode.value,
        "plugin_paths": {
            "system": str(d.system_storage_root / "plugins"),
            "user": str(user_plugin_dir),
            "user_writable": _is_writable(user_plugin_dir),
        },
        "mcp": {
            **mcp_service_block,
            "pool": pool_block,
        },
        "cache": {
            "plugins_cache": str(d.user_storage_root / "cache" / "plugins.cache.json"),
            "mcp_tools_cache": str(
                d.user_storage_root / "cache" / "mcp-tools.cache.json"
            ),
        },
    }


def _is_writable(path) -> bool:
    """Honest answer to "can we write here?" — exists + os.W_OK on the
    directory itself, or on its parent if the dir hasn't been created yet."""
    import os
    from pathlib import Path

    p = Path(path)
    if p.exists():
        return os.access(p, os.W_OK)
    # Walk up to the first existing ancestor and test that.
    for ancestor in p.parents:
        if ancestor.exists():
            return os.access(ancestor, os.W_OK)
    return False
