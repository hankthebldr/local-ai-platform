#!/usr/bin/env python3
"""
Architecture Service — memory-architecture abstraction layer.

Detects the host's memory architecture at startup and exposes a capability
registry that the rest of the engine dispatches through for memory-aware
decisions (eviction policy, DAG scheduling, placement, error recovery,
observability).

Four classes:
    apple_unified       — Apple Silicon, single unified DRAM pool
    cpu_x86             — Linux/x86 CPU-only, single host RAM pool
    gpu_nvidia_single   — Linux + 1× NVIDIA GPU
    gpu_nvidia_multi    — Linux + N>1 NVIDIA GPUs

Plus:
    unknown             — detection failed; engine runs in degraded mode

This module defines the Protocol and supporting Pydantic models only.
Concrete implementations live in api/services/arch_impl/.

See docs/plans/2026-05-19-architecture-aware-orchestration-design.md for
the architectural reasoning.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel


# ── Enums ─────────────────────────────────────────────────────────────────


class ArchClass(str, Enum):
    """Closed set of supported memory architecture classes."""

    APPLE_UNIFIED = "apple_unified"
    CPU_X86 = "cpu_x86"
    GPU_NVIDIA_SINGLE = "gpu_nvidia_single"
    GPU_NVIDIA_MULTI = "gpu_nvidia_multi"
    UNKNOWN = "unknown"


PressureLevel = Literal["ok", "warning", "critical"]
"""Memory pressure level reported by the architecture's pressure poller.

- ok:       within normal operating budget
- warning:  approaching pressure threshold; engine may slow new dispatch
- critical: at or past threshold; engine pauses new dispatch, evicts LRU
"""


# ── Pressure poller output ────────────────────────────────────────────────


class PressureSnapshot(BaseModel):
    """One sample of memory pressure across all pools.

    For unified architectures pool_count is 1; for multi-GPU it equals
    the GPU count. The shape of per_pool entries is architecture-specific
    but always includes a numeric pool_id and free/used GB.
    """

    level: PressureLevel
    per_pool: List[dict]
    timestamp: float
    swap_active: Optional[bool] = None  # apple_unified / cpu_x86 only


# ── Scheduling decisions ──────────────────────────────────────────────────


class ScheduleDecision(BaseModel):
    """One step's scheduling outcome for the current tick.

    placement is the GPU index for multi-GPU; None for unified or
    single-GPU. deferred=True means the step couldn't be scheduled this
    tick (e.g. memory pressure) and will be re-evaluated next tick.
    """

    step_id: str
    placement: Optional[int] = None
    deferred: bool = False
    defer_reason: Optional[str] = None


class Feasibility(BaseModel):
    """Whether a workload (single step or concurrency island) can fit on
    the current architecture.

    fatal=True means no rearrangement can make it fit — the step's model
    alone exceeds the largest available pool. Validate refuses to run
    such workflows.
    """

    fits: bool
    reason: Optional[str] = None
    fatal: bool = False


# ── Error classification ──────────────────────────────────────────────────


ErrorClass = Literal[
    "hardware", "daemon", "memory", "runner", "scheduler", "dag", "config"
]
SuggestedAction = Literal["retry", "evict_and_retry", "abort_step", "abort_workflow"]


class ClassifiedError(BaseModel):
    """An exception promoted into a structured, typed error.

    The architecture impl's classify_error() turns raw exceptions or
    Ollama error responses into this shape, so the engine can dispatch
    recovery uniformly. error_code is a snake_case identifier; arch and
    deployment are captured for post-mortem analysis.
    """

    error_class: ErrorClass
    error_code: str
    arch: str
    deployment: Optional[str] = None
    recoverable: bool
    suggested_action: SuggestedAction
    human_message: str
    raw_error: Optional[str] = None


# ── Transition planning ───────────────────────────────────────────────────


class TransitionPlan(BaseModel):
    """How the engine should handle the boundary between two steps.

    Computed by the architecture's transition_plan(prev, next).

    - evict_at_prev_step: should prev_step's model be unloaded after it runs
    - evict_via_keep_alive_zero: prefer piggybacked eviction via keep_alive:0
      on prev_step's final generate (vs explicit unload after)
    - pre_warm_next: fire a no-op generate for next_step's model during
      prev_step's inference, to hide cold load cost
    - pre_warm_target_gpu: on multi-GPU, the GPU to load next_step's
      model on (None for unified or single-GPU)
    """

    evict_at_prev_step: bool = False
    evict_via_keep_alive_zero: bool = False
    pre_warm_next: bool = False
    pre_warm_target_gpu: Optional[int] = None
    rationale: Optional[str] = None


# ── Protocol ──────────────────────────────────────────────────────────────


@runtime_checkable
class Architecture(Protocol):
    """The capability interface every memory-architecture impl satisfies.

    Detected once at startup; accessed via Architecture.current().
    The pressure poller updates the impl's internal snapshot at 1 Hz.
    """

    # ── identity / capabilities ───
    name: ArchClass
    memory_model: Literal["unified", "discrete"]
    pool_count: int
    total_memory_gb: float
    per_pool_gb: List[float]
    warm_reload_cost_class: Literal["cheap", "expensive"]
    failure_class: Literal["soft_degradation", "hard_oom", "subprocess_kill"]
    supports_placement: bool
    bandwidth_estimate_gbps: float

    # ── runtime methods ───
    def snapshot(self) -> PressureSnapshot:
        """Take a memory-pressure snapshot. Called at 1 Hz by the poller."""
        ...

    def schedule_ready(self, ready_steps: list) -> List[ScheduleDecision]:
        """Decide which ready steps to dispatch this tick.

        Single-pool architectures schedule against total_memory_gb;
        multi-GPU schedules per-GPU.
        """
        ...

    def feasible(self, island: list) -> Feasibility:
        """Validate-time check: can this island of concurrent steps fit?"""
        ...

    def classify_error(self, exc: Any) -> ClassifiedError:
        """Promote a raw exception into a typed, recoverable ClassifiedError."""
        ...

    def transition_plan(self, prev_step: Any, next_step: Any) -> TransitionPlan:
        """Compute eviction + pre-warm strategy for the step boundary."""
        ...

    def default_keep_alive(self) -> str:
        """Return the arch-appropriate Ollama keep_alive default.

        Phase 3 — different memory architectures want different eviction
        defaults. Unified (Apple Silicon, x86 CPU) wants to keep models
        warm because reload cost dominates and RAM is plentiful; discrete
        (NVIDIA) wants to evict by default because VRAM is scarce and
        multi-model DAGs need it freed. Per-workflow / per-step YAML
        overrides this; OLLAMA_KEEP_ALIVE env var is the deepest fallback.

        Returned strings use Ollama's keep_alive grammar:
            "0"      — evict immediately when the request completes
            "30m"    — keep loaded for 30 minutes
            "-1"     — keep forever (until explicit unload)
        """
        ...


# ── Singleton state + accessors ───────────────────────────────────────────
# Populated by detect_architecture() below. Pre-detection calls to
# Architecture.current() hit a clear guard.


_current_architecture: Optional[Architecture] = None


def _set_current(arch: Architecture) -> None:
    """Used by detect_architecture(). Not part of the public API."""
    global _current_architecture
    _current_architecture = arch


def _get_current() -> Architecture:
    if _current_architecture is None:
        raise RuntimeError(
            "Architecture.current() called before detect_architecture(). "
            "Call detect_architecture() during app startup (api/main.py)."
        )
    return _current_architecture


# Attach `current()` as an ergonomic class-level accessor on the Protocol.
# Type checkers may not see this (Protocol attributes are typically declared in
# the body), but at runtime `Architecture.current()` returns the singleton.
def _arch_current_static() -> "Architecture":
    return _get_current()


Architecture.current = staticmethod(_arch_current_static)  # type: ignore[attr-defined]


# ── Unknown fallback ─────────────────────────────────────────────────────


class UnknownArchitecture:
    """Degraded-mode placeholder when all detection probes fail.

    The engine runs but scheduling, eviction, and validation are no-ops.
    Operator should investigate and fix the underlying detection failure.
    """

    def __init__(self):
        self.name = ArchClass.UNKNOWN
        self.memory_model = "unified"  # conservative
        self.pool_count = 1
        self.total_memory_gb = 0.0
        self.per_pool_gb: List[float] = [0.0]
        self.warm_reload_cost_class = "expensive"
        self.failure_class = "soft_degradation"
        self.supports_placement = False
        self.bandwidth_estimate_gbps = 0.0

    def snapshot(self) -> PressureSnapshot:
        import time

        return PressureSnapshot(
            level="warning",  # never confidently "ok" in unknown mode
            per_pool=[{"pool_id": 0, "free_gb": 0, "used_gb": 0, "unknown": True}],
            timestamp=time.time(),
        )

    def schedule_ready(self, ready_steps: list) -> List[ScheduleDecision]:
        # In unknown mode: schedule head only, defer rest pessimistically
        if not ready_steps:
            return []
        return [
            ScheduleDecision(
                step_id=getattr(ready_steps[0], "id", "unknown"), placement=None
            )
        ] + [
            ScheduleDecision(
                step_id=getattr(s, "id", "unknown"),
                placement=None,
                deferred=True,
                defer_reason="unknown architecture; pessimistic dispatch",
            )
            for s in ready_steps[1:]
        ]

    def feasible(self, island: list) -> Feasibility:
        return Feasibility(
            fits=True, reason="unknown architecture; cannot validate budget"
        )

    def classify_error(self, exc: Any) -> ClassifiedError:
        return ClassifiedError(
            error_class="hardware",
            error_code="unknown_architecture",
            arch=self.name.value,
            recoverable=False,
            suggested_action="abort_step",
            human_message=str(exc) if exc else "unknown error on unknown architecture",
            raw_error=str(exc) if exc else None,
        )

    def transition_plan(self, prev_step: Any, next_step: Any) -> TransitionPlan:
        # Conservative defaults: always evict, never pre-warm
        return TransitionPlan(
            evict_at_prev_step=True,
            evict_via_keep_alive_zero=True,
            pre_warm_next=False,
            rationale="unknown architecture; conservative",
        )

    def default_keep_alive(self) -> str:
        # Unknown arch: defer to Ollama's own default. Picking "5m" here
        # rather than "0" because we may not actually want eviction —
        # detection just failed.
        return "5m"


# ── Top-level detector ───────────────────────────────────────────────────


def detect_architecture(strict: bool = False) -> Architecture:
    """Detect the host's memory architecture and install it as the singleton.

    Decision tree:
        1. macOS → UnifiedArchitecture (apple_unified)
        2. NVML reports >= 1 GPU → NvidiaSingle/Multi
        3. Linux (no NVIDIA) → UnifiedArchitecture (cpu_x86)
        4. Else → UnknownArchitecture (degraded)

    When strict=True, an UNKNOWN result raises RuntimeError instead of
    installing the degraded placeholder. Used by STRICT_ARCH_DETECTION
    env in api/main.py startup.

    Idempotent: calling repeatedly replaces the singleton.
    """
    import sys

    arch: Optional[Architecture] = None

    # 1. macOS short-circuit
    if sys.platform == "darwin":
        try:
            from .arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
        except Exception as e:
            logger_msg = f"apple_unified detect failed: {e}"
            import logging

            logging.getLogger(__name__).warning(logger_msg)

    # 2. NVML / NVIDIA
    if arch is None:
        try:
            from .arch_impl import _nvml

            if _nvml.init_nvml():
                count = _nvml.device_count()
                if count == 1:
                    from .arch_impl.nvidia_single import NvidiaSingleArchitecture

                    arch = NvidiaSingleArchitecture.detect()
                elif count >= 2:
                    from .arch_impl.nvidia_multi import NvidiaMultiArchitecture

                    arch = NvidiaMultiArchitecture.detect()
                # else: count == 0; fall through to cpu_x86
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(f"NVML branch failed: {e}")

    # 3. Linux CPU-only
    if arch is None and sys.platform.startswith("linux"):
        try:
            from .arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"cpu_x86 detect failed: {e}")

    # 4. Unknown fallback
    if arch is None:
        if strict:
            raise RuntimeError(
                "Architecture detection failed and STRICT_ARCH_DETECTION is enabled"
            )
        arch = UnknownArchitecture()

    # 5. Invalid-combo guard: cross-check against detected deployment.
    # Only runs if Deployment has been detected — main.py calls
    # detect_deployment() first.
    _check_invalid_combo(arch, strict)

    _set_current(arch)
    return arch


# ── Invalid combination guard ────────────────────────────────────────────


# Combinations that are structurally impossible. Detected at the boundary
# between architecture and deployment singletons.
INVALID_COMBOS = {
    # DMG mode requires Mac → no NVIDIA, no cpu_x86
    ("dmg_native", "gpu_nvidia_single"),
    ("dmg_native", "gpu_nvidia_multi"),
    ("dmg_native", "cpu_x86"),
}


def _check_invalid_combo(arch: "Architecture", strict: bool) -> None:
    """Verify (deployment, arch) is a supported combination.

    Runs only if Deployment singleton has been detected. If not yet
    detected, this is a no-op — main.py is responsible for calling
    detect_deployment() before detect_architecture().
    """
    try:
        from .deployment import _get_current as _get_deployment

        deployment = _get_deployment()
    except RuntimeError:
        # Deployment not detected yet; defer the check
        return

    pair = (deployment.mode.value, arch.name.value)
    if pair in INVALID_COMBOS:
        msg = (
            f"invalid arch×deployment combination: {pair[1]} × {pair[0]}. "
            f"{_invalid_combo_hint(pair)}"
        )
        if strict:
            raise RuntimeError(msg)
        import logging

        logging.getLogger(__name__).error(msg)


def _invalid_combo_hint(pair: tuple) -> str:
    """Human-friendly explanation for each impossible combination."""
    deployment, arch = pair
    if deployment == "dmg_native" and arch.startswith("gpu_nvidia"):
        return (
            "DMG bundles run on macOS, which has no NVIDIA hardware. "
            "Check that NVML probes aren't being mocked unintentionally."
        )
    if deployment == "dmg_native" and arch == "cpu_x86":
        return (
            "DMG bundles are built with py2app (Mac-only). "
            "If running on Linux, use container or host_native instead."
        )
    return "This combination is not supported."


# ── Ollama version probe ─────────────────────────────────────────────────


# Floor version is the pinned baseline (docker-compose.yml). Operator can
# override via ENCLAVE_OLLAMA_VERSION_FLOOR env var (e.g. for testing
# pre-release versions).
DEFAULT_OLLAMA_VERSION_FLOOR = "0.23.4"


def _parse_version(v: str) -> tuple:
    """Parse "X.Y.Z" into (X, Y, Z) tuple for numeric comparison."""
    parts = v.strip().lstrip("v").split(".")
    try:
        return tuple(int(p.split("-")[0]) for p in parts[:3])
    except ValueError:
        return (0, 0, 0)


def probe_ollama_version(strict: bool = False) -> dict:
    """Probe the Ollama daemon and validate against the version floor.

    Returns a dict:
        {
            "version": "0.23.4" | None,
            "reachable": True | False,
            "meets_floor": True | False,
            "floor": "0.23.4",
        }

    In STRICT mode, a version below the floor raises RuntimeError.
    In lenient mode, surfaces a warning and continues.

    Called by api/main.py startup AFTER detect_architecture(); the result
    is attached to the Deployment singleton as ollama_reachable.
    """
    import os
    import logging

    from .ollama_service import OllamaService
    from .deployment import _get_current as _get_deployment

    floor = os.environ.get("ENCLAVE_OLLAMA_VERSION_FLOOR", DEFAULT_OLLAMA_VERSION_FLOOR)

    # Read ollama URL from the deployment singleton if available
    try:
        deployment = _get_deployment()
        ollama_url = deployment.ollama_url
    except RuntimeError:
        ollama_url = None

    service = OllamaService(host=ollama_url) if ollama_url else OllamaService()
    version = service.get_version()

    if version is None:
        result = {
            "version": None,
            "reachable": False,
            "meets_floor": False,
            "floor": floor,
        }
        logging.getLogger(__name__).warning(
            "Ollama unreachable at startup; running in degraded mode"
        )
        if strict:
            raise RuntimeError("Ollama daemon unreachable and STRICT mode is enabled")
        return result

    meets_floor = _parse_version(version) >= _parse_version(floor)
    result = {
        "version": version,
        "reachable": True,
        "meets_floor": meets_floor,
        "floor": floor,
    }

    # Update deployment.ollama_reachable if we have a deployment
    try:
        deployment = _get_deployment()
        deployment.ollama_reachable = True
    except RuntimeError:
        pass

    if not meets_floor:
        msg = (
            f"Ollama version {version} below floor {floor}; "
            f"architecture-aware features may not work correctly. "
            f"See docs/deployment/ollama-version.md"
        )
        if strict:
            raise RuntimeError(msg)
        logging.getLogger(__name__).warning(msg)

    return result
