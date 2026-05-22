#!/usr/bin/env python3
"""
NvidiaMultiArchitecture — Linux + N>1 NVIDIA GPUs.

Multi-pool discrete memory model with placement support:
    - Each GPU is an independent VRAM pool
    - Scheduler bin-packs across GPUs (sequential within, parallel across — but
      we ship sequential by operator policy, so placement matters mostly for
      pre-warm on alternate cards)
    - NVLink-paired GPUs preferred for `same_as` affinity
    - Failure mode is per-GPU CUDA OOM
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from . import _nvml
from ..architecture import (
    ArchClass,
    ClassifiedError,
    Feasibility,
    PressureSnapshot,
    ScheduleDecision,
    TransitionPlan,
)
from ...logging_config import logger


_VRAM_FREE_PCT_WARN = 0.20
_VRAM_FREE_PCT_CRIT = 0.10


class NvidiaMultiArchitecture:
    """Linux + N>1 NVIDIA GPUs."""

    def __init__(
        self,
        gpus: List[Dict[str, Any]],
        nvlink_topology: List[Tuple[int, int]],
        driver_version: str,
    ):
        self.name = ArchClass.GPU_NVIDIA_MULTI
        self.memory_model = "discrete"
        self.pool_count = len(gpus)
        self.total_memory_gb = round(sum(g["vram_total_gb"] for g in gpus), 2)
        self.per_pool_gb: List[float] = [g["vram_total_gb"] for g in gpus]
        self.warm_reload_cost_class = "expensive"
        self.failure_class = "hard_oom"
        self.supports_placement = True
        # Bandwidth: use the slowest GPU as the conservative estimate
        self.bandwidth_estimate_gbps = min(
            _nvml.estimate_bandwidth_gbps(g["name"]) for g in gpus
        )
        self.gpus = gpus
        self.nvlink_topology = nvlink_topology
        self.driver_version = driver_version

    @classmethod
    def detect(cls) -> "NvidiaMultiArchitecture":
        if not _nvml.init_nvml():
            raise RuntimeError("NVML init failed; cannot detect NvidiaMulti")
        count = _nvml.device_count()
        if count < 2:
            raise RuntimeError(f"NvidiaMulti requires >=2 GPUs, got {count}")
        gpus = []
        for i in range(count):
            meta = _nvml.gpu_metadata(i)
            if meta is None:
                logger.warning(f"GPU {i} probe failed; excluding from pool")
                continue
            gpus.append(meta)
        if len(gpus) < 2:
            raise RuntimeError(
                f"Fewer than 2 GPUs survived probe ({len(gpus)} from {count}); "
                "cannot run as nvidia_multi"
            )
        nvlink = _nvml.detect_nvlink_topology(len(gpus))
        driver = _nvml.driver_version() or "unknown"
        return cls(gpus=gpus, nvlink_topology=nvlink, driver_version=driver)

    # ── runtime methods ─────────────────────────────────────────────────

    def snapshot(self) -> PressureSnapshot:
        per_pool = []
        worst_level = "ok"
        for i, _gpu in enumerate(self.gpus):
            meta = _nvml.gpu_metadata(i)
            if meta is None:
                per_pool.append(
                    {"pool_id": i, "free_gb": 0, "used_gb": 0, "probe_failed": True}
                )
                worst_level = "critical"
                continue
            free_pct = meta["vram_free_gb"] / meta["vram_total_gb"]
            if free_pct < _VRAM_FREE_PCT_CRIT:
                level = "critical"
            elif free_pct < _VRAM_FREE_PCT_WARN:
                level = "warning"
            else:
                level = "ok"
            per_pool.append(
                {
                    "pool_id": i,
                    "free_gb": meta["vram_free_gb"],
                    "used_gb": meta["vram_used_gb"],
                }
            )
            worst_level = _worst(worst_level, level)
        return PressureSnapshot(
            level=worst_level,
            per_pool=per_pool,
            timestamp=time.time(),
        )

    def schedule_ready(self, ready_steps: list) -> List[ScheduleDecision]:
        """Sequential by operator policy: head step picks the GPU with most
        free VRAM, the rest defer.

        Pre-warm logic (in transition_plan) is where multi-GPU actually wins:
        we can load the NEXT model on a free GPU while the CURRENT step runs
        on its assigned GPU.
        """
        if not ready_steps:
            return []
        snap = self.snapshot()
        # Pick the GPU with most free VRAM
        best_gpu = max(snap.per_pool, key=lambda p: p.get("free_gb", 0))["pool_id"]
        head = ready_steps[0]
        decisions = [
            ScheduleDecision(step_id=getattr(head, "id", "unknown"), placement=best_gpu)
        ]
        for rest in ready_steps[1:]:
            decisions.append(
                ScheduleDecision(
                    step_id=getattr(rest, "id", "unknown"),
                    placement=None,
                    deferred=True,
                    defer_reason="sequential execution; head step holds placement",
                )
            )
        return decisions

    def feasible(self, island: list) -> Feasibility:
        """For sequential workflows, every step is its own island.

        A step fits if its model + KV fits in the LARGEST single GPU's VRAM
        budget. (For Phase 4+ if we ever re-enable parallel: aggregate budget.)
        """
        if not island:
            return Feasibility(fits=True)
        sizes = [getattr(s, "est_size_gb", None) or 0 for s in island]
        max_size = max(sizes) if sizes else 0
        with_kv = max_size * 1.15
        largest_pool = max(self.per_pool_gb)
        budget = largest_pool * 0.85
        if with_kv <= budget:
            return Feasibility(fits=True)
        return Feasibility(
            fits=False,
            reason=(
                f"largest step needs {with_kv:.1f} GB (incl. KV); "
                f"biggest GPU budget {budget:.1f} GB"
            ),
            fatal=(max_size > largest_pool),
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
                human_message="CUDA OOM; evicting LRU and retrying on alternate GPU if possible",
                raw_error=msg,
            )
        if "gpu" in lower and (
            "lost" in lower or "disconnect" in lower or "fallen off" in lower
        ):
            return ClassifiedError(
                error_class="hardware",
                error_code="gpu_lost_mid_run",
                arch=self.name.value,
                recoverable=True,
                suggested_action="evict_and_retry",
                human_message="GPU went offline; rescheduling to surviving GPUs",
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
        """Multi-GPU's win: pre-warm the next-step model on an alternate GPU
        while the current step's GPU is busy with inference.
        """
        if next_step is None:
            return TransitionPlan(
                evict_at_prev_step=True,
                evict_via_keep_alive_zero=True,
                pre_warm_next=False,
                rationale="terminal step",
            )
        prev_model = getattr(prev_step, "model", None)
        next_model = getattr(next_step, "model", None)
        same_model = prev_model and next_model and prev_model == next_model
        if same_model:
            return TransitionPlan(
                evict_at_prev_step=False,
                evict_via_keep_alive_zero=False,
                pre_warm_next=False,
                rationale="same model; keep runner warm on its GPU",
            )

        # Different next-step model: identify a free GPU for pre-warm
        snap = self.snapshot()
        prev_gpu = getattr(prev_step, "_assigned_gpu", None)
        candidates = [
            p
            for p in snap.per_pool
            if p["pool_id"] != prev_gpu and p.get("free_gb", 0) > 0
        ]
        if candidates:
            target = max(candidates, key=lambda p: p["free_gb"])["pool_id"]
            return TransitionPlan(
                evict_at_prev_step=True,
                evict_via_keep_alive_zero=True,
                pre_warm_next=True,
                pre_warm_target_gpu=target,
                rationale=f"different model; pre-warm on free GPU {target}",
            )
        return TransitionPlan(
            evict_at_prev_step=True,
            evict_via_keep_alive_zero=True,
            pre_warm_next=False,
            rationale="different model; no free GPU for pre-warm; cold load at boundary",
        )

    def default_keep_alive(self) -> str:
        # Multi-GPU shares the single-GPU eviction default. The win of
        # multi-GPU is pre-warm-on-alternate-GPU (Phase 5), not lower
        # eviction pressure — each GPU still has scarce VRAM.
        return "0"

    @classmethod
    def current(cls):
        from ..architecture import _get_current

        return _get_current()


# ── helpers ───────────────────────────────────────────────────────────────


_LEVEL_RANK = {"ok": 0, "warning": 1, "critical": 2}


def _worst(a: str, b: str) -> str:
    return a if _LEVEL_RANK[a] >= _LEVEL_RANK[b] else b
