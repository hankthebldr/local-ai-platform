#!/usr/bin/env python3
"""
NvidiaSingleArchitecture — Linux + exactly one NVIDIA GPU.

Single VRAM pool, discrete memory model. Compared to unified architectures:
    - Warm re-loads pay PCIe upload (~2.5 s for 50 GB), can never be sub-second
    - Failure mode is CUDA OOM (hard, immediate) rather than swap-thrash
    - KV cache competes with weights in the same VRAM pool
    - No placement decisions (only one GPU)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from . import _nvml
from ..architecture import (
    ArchClass,
    ClassifiedError,
    Feasibility,
    PressureSnapshot,
    ScheduleDecision,
    TransitionPlan,
)


# ── Pressure thresholds ───────────────────────────────────────────────────

_VRAM_FREE_PCT_WARN = 0.20
_VRAM_FREE_PCT_CRIT = 0.10


class NvidiaSingleArchitecture:
    """Linux + 1× NVIDIA GPU."""

    def __init__(self, gpu_meta: Dict[str, Any], driver_version: str):
        self.name = ArchClass.GPU_NVIDIA_SINGLE
        self.memory_model = "discrete"
        self.pool_count = 1
        self.total_memory_gb = gpu_meta["vram_total_gb"]
        self.per_pool_gb: List[float] = [gpu_meta["vram_total_gb"]]
        self.warm_reload_cost_class = "expensive"
        self.failure_class = "hard_oom"
        self.supports_placement = False
        self.bandwidth_estimate_gbps = _nvml.estimate_bandwidth_gbps(gpu_meta["name"])
        self.gpus: List[Dict[str, Any]] = [gpu_meta]
        self.driver_version = driver_version

    @classmethod
    def detect(cls) -> "NvidiaSingleArchitecture":
        if not _nvml.init_nvml():
            raise RuntimeError("NVML init failed; cannot detect NvidiaSingle")
        meta = _nvml.gpu_metadata(0)
        if meta is None:
            raise RuntimeError("NVML reported GPU but metadata probe failed")
        driver = _nvml.driver_version() or "unknown"
        return cls(gpu_meta=meta, driver_version=driver)

    # ── runtime methods ─────────────────────────────────────────────────

    def snapshot(self) -> PressureSnapshot:
        """Re-probe VRAM. NVML calls are cheap (~ms)."""
        meta = _nvml.gpu_metadata(0)
        if meta is None:
            # Probe failed mid-run — return critical to halt new dispatch
            return PressureSnapshot(
                level="critical",
                per_pool=[{"pool_id": 0, "free_gb": 0, "used_gb": 0}],
                timestamp=time.time(),
            )
        free_pct = meta["vram_free_gb"] / meta["vram_total_gb"]
        if free_pct < _VRAM_FREE_PCT_CRIT:
            level = "critical"
        elif free_pct < _VRAM_FREE_PCT_WARN:
            level = "warning"
        else:
            level = "ok"
        return PressureSnapshot(
            level=level,
            per_pool=[
                {
                    "pool_id": 0,
                    "free_gb": meta["vram_free_gb"],
                    "used_gb": meta["vram_used_gb"],
                }
            ],
            timestamp=time.time(),
        )

    def schedule_ready(self, ready_steps: list) -> List[ScheduleDecision]:
        """Single GPU + sequential: head step gets the GPU, rest deferred."""
        if not ready_steps:
            return []
        head = ready_steps[0]
        decisions = [
            ScheduleDecision(step_id=getattr(head, "id", "unknown"), placement=0)
        ]
        for rest in ready_steps[1:]:
            decisions.append(
                ScheduleDecision(
                    step_id=getattr(rest, "id", "unknown"),
                    placement=None,
                    deferred=True,
                    defer_reason="sequential execution; single GPU",
                )
            )
        return decisions

    def feasible(self, island: list) -> Feasibility:
        if not island:
            return Feasibility(fits=True)
        sizes = [getattr(s, "est_size_gb", None) or 0 for s in island]
        max_size = max(sizes) if sizes else 0
        with_kv = max_size * 1.15
        budget = self.total_memory_gb * 0.85
        if with_kv <= budget:
            return Feasibility(fits=True)
        return Feasibility(
            fits=False,
            reason=(
                f"largest step needs {with_kv:.1f} GB (incl. KV); "
                f"VRAM budget {budget:.1f} GB"
            ),
            fatal=(max_size > self.total_memory_gb),
        )

    def classify_error(self, exc: Any) -> ClassifiedError:
        msg = str(exc)
        lower = msg.lower()
        if "cuda out of memory" in lower or "cudaerrormemoryallocation" in lower:
            return ClassifiedError(
                error_class="memory",
                error_code="vram_oom",
                arch=self.name.value,
                recoverable=True,
                suggested_action="evict_and_retry",
                human_message="CUDA OOM on the single GPU; evicting LRU and retrying",
                raw_error=msg,
            )
        if "runner" in lower and (
            "died" in lower or "crashed" in lower or "exit" in lower
        ):
            return ClassifiedError(
                error_class="runner",
                error_code="runner_crashed",
                arch=self.name.value,
                recoverable=True,
                suggested_action="retry",
                human_message="Runner subprocess died; respawning once",
                raw_error=msg,
            )
        if "driver" in lower and ("disconnect" in lower or "lost" in lower):
            return ClassifiedError(
                error_class="hardware",
                error_code="gpu_driver_disconnect",
                arch=self.name.value,
                recoverable=False,
                suggested_action="abort_workflow",
                human_message="NVIDIA driver disconnect; aborting workflow",
                raw_error=msg,
            )
        return ClassifiedError(
            error_class="runner",
            error_code="unknown",
            arch=self.name.value,
            recoverable=False,
            suggested_action="abort_step",
            human_message=msg or "unclassified error",
            raw_error=msg,
        )

    def transition_plan(self, prev_step: Any, next_step: Any) -> TransitionPlan:
        """Single GPU: piggybacked eviction is key; pre-warm only if next-step
        model can fit alongside current step's remaining inference time.
        """
        if next_step is None:
            return TransitionPlan(
                evict_at_prev_step=True,
                evict_via_keep_alive_zero=True,
                pre_warm_next=False,
                rationale="terminal step",
            )
        # Same model: keep resident only if defaults say so (handled upstream)
        prev_model = getattr(prev_step, "model", None)
        next_model = getattr(next_step, "model", None)
        same_model = prev_model and next_model and prev_model == next_model
        return TransitionPlan(
            evict_at_prev_step=not same_model,
            evict_via_keep_alive_zero=not same_model,
            pre_warm_next=False,  # bandwidth-contention risk; default off, opt-in later
            pre_warm_target_gpu=None,
            rationale=(
                "same model in next step; keep resident"
                if same_model
                else "different model; piggybacked eviction; pre-warm gated by bandwidth guard"
            ),
        )

    def default_keep_alive(self) -> str:
        # NVIDIA single GPU: VRAM is scarce (24 GB on a 4000 Blackwell;
        # a 34B Q4_K_M is ~20 GB by itself). Evict by default so the next
        # step's model can land. Per-workflow / per-step YAML can override
        # for single-model long sessions.
        return "0"

    def recommended_onnx_providers(self) -> "OnnxExecutionPlan":
        """Single NVIDIA GPU -> CUDA EP + CPU floor, fp16. (TensorRT EP is a
        later opportunistic optimization.)"""
        from ..architecture import OnnxExecutionPlan

        return OnnxExecutionPlan(
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            quant="fp16",
            provider_options=[{}, {}],
        )

    @classmethod
    def current(cls):
        from ..architecture import _get_current

        return _get_current()
