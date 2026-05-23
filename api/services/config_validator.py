"""
Per-arch × per-deployment configuration validator (Phase 6 task 6.1).

Validates the host's Ollama daemon environment against the recommended
settings for the detected (Architecture, Deployment) pair. Same arch
under different deployments has different "right answers" — e.g.
`OLLAMA_HOST=127.0.0.1:11434` is correct for DMG, `http://ollama:11434`
is correct for container. The validator dispatches through both dimensions.

The output (ConfigValidationResult) is consumed by:
  - api/main.py startup hook   — in STRICT_CONFIG_VALIDATION mode, errors abort
  - GET /api/system/health     — embeds the warning/error lists
  - GET /api/system/config/recommendations — generates daemon snippets

Each Recommendation declares:
  - `key`      env var name
  - `expected` recommended value (or pattern, or None = should NOT be set)
  - `severity` "error" | "warn" | "arch_env_mismatch"
  - `code`     stable identifier for UI lookup
  - `message`  human-readable explanation

Recommendations live in a single dict keyed by (ArchClass, DeploymentMode)
so the table reads top-to-bottom as a deployment matrix.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..logging_config import logger
from .architecture import ArchClass
from .deployment import ConfigValidationResult, DeploymentMode


# ── Recommendation record ────────────────────────────────────────────────


@dataclass
class Recommendation:
    """One env-var recommendation for an arch × deployment pair."""

    key: str
    expected: Optional[str]  # None = should NOT be set
    severity: str = "warn"  # "error" | "warn" | "arch_env_mismatch"
    code: Optional[str] = None  # stable identifier; defaults to f"{severity}_{key}"
    message: Optional[str] = None

    def __post_init__(self):
        if self.code is None:
            self.code = f"{self.severity}_{self.key.lower()}"


# ── Recommendation matrix ────────────────────────────────────────────────
#
# Read this top-to-bottom. Each block is (arch, deployment) → list of
# recommendations. Empty list means "no specific recommendations for
# this pair" — validator passes any daemon env clean.


RECOMMENDATIONS: Dict[tuple, List[Recommendation]] = {
    # ── Apple Silicon / unified ─────────────────────────────────────────
    (ArchClass.APPLE_UNIFIED, DeploymentMode.DMG_NATIVE): [
        Recommendation("OLLAMA_HOST", "127.0.0.1:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "3", severity="warn"),
        Recommendation(
            "OLLAMA_NUM_PARALLEL",
            "1",
            severity="warn",
            message="Unified memory benefits from KV-cache locality; "
            "keep concurrency low.",
        ),
        Recommendation(
            "CUDA_VISIBLE_DEVICES",
            None,
            severity="arch_env_mismatch",
            code="arch_env_mismatch",
            message="CUDA env vars on macOS are meaningless (no NVIDIA).",
        ),
        Recommendation(
            "NVIDIA_VISIBLE_DEVICES",
            None,
            severity="arch_env_mismatch",
            code="arch_env_mismatch",
            message="NVIDIA env vars on macOS are meaningless.",
        ),
    ],
    (ArchClass.APPLE_UNIFIED, DeploymentMode.HOST_NATIVE): [
        Recommendation("OLLAMA_HOST", "127.0.0.1:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "3", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn"),
        Recommendation(
            "CUDA_VISIBLE_DEVICES",
            None,
            severity="arch_env_mismatch",
            code="arch_env_mismatch",
        ),
    ],
    # ── x86 CPU-only ────────────────────────────────────────────────────
    (ArchClass.CPU_X86, DeploymentMode.CONTAINER): [
        Recommendation("OLLAMA_HOST", "http://ollama:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "1", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn"),
        Recommendation(
            "OLLAMA_NUM_THREAD",
            "physical-core-count",
            severity="warn",
            code="missing_num_thread",
            message="On CPU prefill dominates; set to physical (not logical) cores.",
        ),
        Recommendation(
            "CUDA_VISIBLE_DEVICES",
            None,
            severity="arch_env_mismatch",
            code="arch_env_mismatch",
            message="CPU-only deployment shouldn't reference GPU devices.",
        ),
    ],
    (ArchClass.CPU_X86, DeploymentMode.HOST_NATIVE): [
        Recommendation("OLLAMA_HOST", "127.0.0.1:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "1", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn"),
        Recommendation(
            "OLLAMA_NUM_THREAD",
            "physical-core-count",
            severity="warn",
            code="missing_num_thread",
        ),
    ],
    # ── NVIDIA single GPU ───────────────────────────────────────────────
    (ArchClass.GPU_NVIDIA_SINGLE, DeploymentMode.CONTAINER): [
        Recommendation("OLLAMA_HOST", "http://ollama:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "2", severity="warn"),
        Recommendation(
            "OLLAMA_NUM_PARALLEL",
            "1",
            severity="warn",
            message="KV cache competes with weights in single VRAM pool.",
        ),
        Recommendation("OLLAMA_FLASH_ATTENTION", "1", severity="warn"),
    ],
    (ArchClass.GPU_NVIDIA_SINGLE, DeploymentMode.HOST_NATIVE): [
        Recommendation("OLLAMA_HOST", "127.0.0.1:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "2", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn"),
        Recommendation("OLLAMA_FLASH_ATTENTION", "1", severity="warn"),
    ],
    # ── NVIDIA multi-GPU ────────────────────────────────────────────────
    (ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.CONTAINER): [
        Recommendation(
            "OLLAMA_SCHED_SPREAD",
            "1",
            severity="error",
            code="missing_sched_spread",
            message="Required for parallel multi-GPU execution. Without this "
            "Ollama serializes all model loads onto GPU 0.",
        ),
        Recommendation("OLLAMA_HOST", "http://ollama:11434", severity="warn"),
        Recommendation(
            "OLLAMA_MAX_LOADED_MODELS",
            "3",  # 3*gpu_count is the spec; conservative default
            severity="warn",
            message="Scale with gpu_count; 3 per GPU is a sane starting point.",
        ),
        Recommendation(
            "OLLAMA_NUM_PARALLEL",
            "1",
            severity="warn",
            message="Let DAG drive parallelism, not per-runner.",
        ),
        Recommendation("OLLAMA_FLASH_ATTENTION", "1", severity="warn"),
    ],
    (ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.HOST_NATIVE): [
        Recommendation(
            "OLLAMA_SCHED_SPREAD",
            "1",
            severity="error",
            code="missing_sched_spread",
        ),
        Recommendation("OLLAMA_HOST", "127.0.0.1:11434", severity="warn"),
        Recommendation("OLLAMA_MAX_LOADED_MODELS", "3", severity="warn"),
        Recommendation("OLLAMA_NUM_PARALLEL", "1", severity="warn"),
        Recommendation("OLLAMA_FLASH_ATTENTION", "1", severity="warn"),
    ],
    # Unknown architecture: no specific recommendations. Validator passes clean.
    (ArchClass.UNKNOWN, DeploymentMode.HOST_NATIVE): [],
    (ArchClass.UNKNOWN, DeploymentMode.CONTAINER): [],
    (ArchClass.UNKNOWN, DeploymentMode.DMG_NATIVE): [],
}


# ── Validator ────────────────────────────────────────────────────────────


def _matches(expected: str, actual: str) -> bool:
    """Check whether `actual` satisfies `expected`.

    Special tokens:
      - "physical-core-count": passes if actual parses as an int > 0
        (we can't determine "physical" cores portably; trust the operator).
      - "enumerate": passes if actual is a comma-separated list of ints.
      - "*": passes for any non-empty value.
      - "N-M" range: passes if actual is between N and M inclusive.
      - Otherwise: exact string match.
    """
    if expected == "*":
        return bool(actual)
    if expected == "physical-core-count":
        try:
            return int(actual) > 0
        except ValueError:
            return False
    if expected == "enumerate":
        try:
            [int(x.strip()) for x in actual.split(",") if x.strip()]
            return True
        except ValueError:
            return False
    if "-" in expected and all(p.isdigit() for p in expected.split("-")):
        lo, hi = (int(p) for p in expected.split("-"))
        try:
            return lo <= int(actual) <= hi
        except ValueError:
            return False
    return expected == actual


def _gpu_passthrough_works() -> bool:
    """Heuristic: confirm `nvidia-smi` is reachable from this process.

    Used as a final cross-check when a container deployment reports an
    NVIDIA arch but the daemon environment looks correct — the actual
    failure mode is usually missing `--gpus all` on `docker run` or a
    misconfigured `runtime: nvidia` in compose.
    """
    try:
        import subprocess

        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and "GPU" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False


def validate_config(
    arch_name: ArchClass,
    deployment_mode: DeploymentMode,
    daemon_env: Dict[str, str],
) -> ConfigValidationResult:
    """Apply the recommendation matrix to a daemon env dict.

    Pure function: takes the arch + deployment enums and the env dict,
    returns a ConfigValidationResult. No I/O except the GPU-passthrough
    cross-check (subprocess to nvidia-smi).
    """
    key = (arch_name, deployment_mode)
    recs = RECOMMENDATIONS.get(key, [])
    warnings: List[dict] = []
    errors: List[dict] = []

    for rec in recs:
        actual = daemon_env.get(rec.key)
        if rec.expected is None:
            # Should NOT be set
            if actual is not None and actual != "":
                bucket = errors if rec.severity == "error" else warnings
                bucket.append(
                    {
                        "code": rec.code,
                        "key": rec.key,
                        "actual": actual,
                        "expected": None,
                        "message": rec.message
                        or f"{rec.key} should not be set on this deployment",
                        "severity": rec.severity,
                    }
                )
        else:
            # Should be set to expected value
            if actual is None:
                bucket = errors if rec.severity == "error" else warnings
                bucket.append(
                    {
                        "code": rec.code,
                        "key": rec.key,
                        "actual": None,
                        "expected": rec.expected,
                        "message": rec.message
                        or f"{rec.key} should be set to {rec.expected}",
                        "severity": rec.severity,
                    }
                )
            elif not _matches(rec.expected, actual):
                bucket = errors if rec.severity == "error" else warnings
                bucket.append(
                    {
                        "code": rec.code,
                        "key": rec.key,
                        "actual": actual,
                        "expected": rec.expected,
                        "message": rec.message
                        or f"{rec.key} should be {rec.expected}, got {actual}",
                        "severity": rec.severity,
                    }
                )

    # Deployment-special cross-checks
    if deployment_mode == DeploymentMode.CONTAINER and arch_name.value.startswith(
        "gpu_"
    ):
        if not _gpu_passthrough_works():
            errors.append(
                {
                    "code": "gpu_passthrough_misconfigured",
                    "key": None,
                    "actual": None,
                    "expected": None,
                    "message": (
                        "Container deployment with NVIDIA arch but nvidia-smi "
                        "not reachable. Check `--gpus all` / `runtime: nvidia` "
                        "in compose."
                    ),
                    "severity": "error",
                }
            )

    if deployment_mode == DeploymentMode.CONTAINER and sys.platform == "darwin":
        warnings.append(
            {
                "code": "docker_desktop_mac_vm",
                "key": None,
                "actual": None,
                "expected": None,
                "message": (
                    "Docker Desktop on macOS runs a Linux VM; the daemon "
                    "won't see Apple unified memory. Use the DMG build for "
                    "Apple Silicon performance."
                ),
                "severity": "warn",
            }
        )

    return ConfigValidationResult(warnings=warnings, errors=errors)


def validate_config_or_exit(
    arch_name: ArchClass,
    deployment_mode: DeploymentMode,
    daemon_env: Dict[str, str],
) -> ConfigValidationResult:
    """Like validate_config but aborts the process when STRICT_CONFIG_VALIDATION
    is set and any errors surface. Used by api/main.py startup."""
    result = validate_config(arch_name, deployment_mode, daemon_env)
    strict = os.environ.get("STRICT_CONFIG_VALIDATION", "").lower() == "true"
    if result.errors:
        for e in result.errors:
            logger.error(f"Config error [{e.get('code')}]: {e.get('message')}")
        if strict:
            raise SystemExit(1)
    for w in result.warnings:
        logger.warning(f"Config warning [{w.get('code')}]: {w.get('message')}")
    return result


# ── Phase 6.2: Daemon env probe ──────────────────────────────────────────


def probe_daemon_env() -> Dict[str, str]:
    """Try to read the Ollama daemon's environment.

    Order:
      1. OllamaService.get_daemon_env() if implemented (newer Ollama
         exposes some of this via /api/show; this is the spec-future path)
      2. Our own process env (when API and Ollama share the same container)
      3. Empty dict — caller's recommendations become advisory

    Never raises. Logs at debug level on failure.
    """
    known_keys = [
        "OLLAMA_HOST",
        "OLLAMA_KEEP_ALIVE",
        "OLLAMA_MAX_LOADED_MODELS",
        "OLLAMA_NUM_PARALLEL",
        "OLLAMA_NUM_THREAD",
        "OLLAMA_SCHED_SPREAD",
        "OLLAMA_FLASH_ATTENTION",
        "OLLAMA_GPU_LAYERS",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "NVIDIA_DRIVER_CAPABILITIES",
    ]
    # Try the OllamaService method first (Task 6.2 future extension)
    try:
        from .ollama_service import OllamaService

        svc = OllamaService()
        getter = getattr(svc, "get_daemon_env", None)
        if getter is not None:
            try:
                env = getter()
                if env:
                    return dict(env)
            except NotImplementedError:
                pass
            except Exception as e:
                logger.debug(f"Ollama get_daemon_env failed: {e}")
    except Exception as e:
        logger.debug(f"Ollama probe import failed: {e}")

    # Fall back to our own process env, filtered to known keys.
    # When API and Ollama share a container/host, these match.
    return {k: os.environ[k] for k in known_keys if k in os.environ}
