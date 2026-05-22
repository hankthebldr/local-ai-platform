#!/usr/bin/env python3
"""
UnifiedArchitecture — single-memory-pool implementation.

Serves two arch classes:
    apple_unified   — Apple Silicon, Metal-backed unified DRAM
    cpu_x86         — Linux CPU-only

Structurally identical (single pool, mmap-backed weights, page-cache
re-loads). Differs only in:
    - failure_class: swap-thrash on Mac vs OOM-killer on Linux
    - pressure signal source: vm_stat (Mac) vs /proc/meminfo (Linux)
    - bandwidth estimate (SoC type vs DDR generation)
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, List, Tuple

import psutil

from ..architecture import (
    ArchClass,
    ClassifiedError,
    Feasibility,
    PressureSnapshot,
    ScheduleDecision,
    TransitionPlan,
)
from ...logging_config import logger


# ── Pressure thresholds (tunable; see CLAUDE.md for calibration notes) ────

_APPLE_USED_PCT_WARN = 0.85
_APPLE_USED_PCT_CRIT = 0.90
_CPU_AVAILABLE_PCT_WARN = 0.20  # < 20% available
_CPU_AVAILABLE_PCT_CRIT = 0.10  # < 10% available


# ── Probes (patched by mocks in tests) ────────────────────────────────────


def _read_psutil_memory() -> Tuple[int, int]:
    """Return (total_bytes, used_bytes) from psutil."""
    mem = psutil.virtual_memory()
    return (mem.total, mem.used)


def _read_proc_meminfo() -> Tuple[int, int]:
    """Linux only. Return (total_bytes, available_bytes) from /proc/meminfo.

    'Available' is preferred over (total - used) because the kernel tracks
    page-cache-reclaimable memory in MemAvailable specifically.
    """
    try:
        with open("/proc/meminfo") as f:
            content = f.read()
        total_kb = _grep_kb(content, "MemTotal")
        avail_kb = _grep_kb(content, "MemAvailable")
        return (total_kb * 1024, avail_kb * 1024)
    except (FileNotFoundError, PermissionError, OSError) as e:
        logger.warning(f"/proc/meminfo unreadable ({e}); falling back to psutil")
        mem = psutil.virtual_memory()
        return (mem.total, mem.available)


def _grep_kb(meminfo: str, label: str) -> int:
    for line in meminfo.splitlines():
        if line.startswith(label + ":"):
            # Format: "MemTotal:       98765432 kB"
            return int(line.split()[1])
    raise ValueError(f"Label '{label}' not found in /proc/meminfo")


def _read_vm_stat_swap() -> bool:
    """macOS only. True if vm_stat shows active swap usage.

    Returns False (don't trigger critical) if probe fails — conservative.
    """
    try:
        result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2)
        # Look for non-zero swap activity. vm_stat reports "Swapouts" and
        # "Swapins" as cumulative counters; any movement = swap is active.
        for line in result.stdout.splitlines():
            if "Swapouts" in line or "Swapins" in line:
                # Format: "Swapouts:           12345."
                parts = line.split()
                if parts:
                    count = parts[-1].rstrip(".").replace(",", "")
                    if count.isdigit() and int(count) > 0:
                        return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"vm_stat probe failed: {e}")
        return False


def _estimate_bandwidth_gbps() -> float:
    """Rough memory bandwidth estimate per platform.

    Mac M-series: 273 GB/s (M4 Pro). Linux DDR5 dual-channel: ~89 GB/s.
    Used by the transition_plan to estimate cold-load durations.
    """
    if sys.platform == "darwin":
        return 273.0  # conservative M4 Pro; M3 Ultra is 800
    return 89.0  # DDR5-5600 dual channel


# ── Implementation ────────────────────────────────────────────────────────


class UnifiedArchitecture:
    """Single-memory-pool architecture (apple_unified or cpu_x86)."""

    def __init__(
        self,
        arch_class: ArchClass,
        total_memory_gb: float,
        bandwidth_gbps: float,
    ):
        self.name = arch_class
        self.memory_model = "unified"
        self.pool_count = 1
        self.total_memory_gb = total_memory_gb
        self.per_pool_gb: List[float] = [total_memory_gb]
        self.warm_reload_cost_class = "cheap"  # page cache helps both Mac and Linux
        self.failure_class = (
            "soft_degradation"
            if arch_class == ArchClass.APPLE_UNIFIED
            else "subprocess_kill"
        )
        self.supports_placement = False
        self.bandwidth_estimate_gbps = bandwidth_gbps

    @classmethod
    def detect(cls) -> "UnifiedArchitecture":
        """Detect from running platform. Distinguishes apple vs cpu_x86."""
        if sys.platform == "darwin":
            total_bytes, _used = _read_psutil_memory()
            total_gb = total_bytes / (1024**3)
            return cls(
                arch_class=ArchClass.APPLE_UNIFIED,
                total_memory_gb=round(total_gb, 1),
                bandwidth_gbps=_estimate_bandwidth_gbps(),
            )

        # Linux CPU-only
        total_bytes, _avail = _read_proc_meminfo()
        total_gb = total_bytes / (1024**3)
        return cls(
            arch_class=ArchClass.CPU_X86,
            total_memory_gb=round(total_gb, 1),
            bandwidth_gbps=_estimate_bandwidth_gbps(),
        )

    # ── runtime methods ─────────────────────────────────────────────────

    def snapshot(self) -> PressureSnapshot:
        """Sample memory pressure. Dispatches per arch_class."""
        if self.name == ArchClass.APPLE_UNIFIED:
            return self._snapshot_apple()
        return self._snapshot_cpu()

    def _snapshot_apple(self) -> PressureSnapshot:
        total_bytes, used_bytes = _read_psutil_memory()
        used_pct = used_bytes / total_bytes if total_bytes else 0
        swap_active = _read_vm_stat_swap()

        if used_pct >= _APPLE_USED_PCT_CRIT and swap_active:
            level = "critical"
        elif used_pct >= _APPLE_USED_PCT_WARN:
            level = "warning"
        else:
            level = "ok"

        free_gb = (total_bytes - used_bytes) / (1024**3)
        used_gb = used_bytes / (1024**3)
        return PressureSnapshot(
            level=level,
            per_pool=[
                {
                    "pool_id": 0,
                    "free_gb": round(free_gb, 2),
                    "used_gb": round(used_gb, 2),
                }
            ],
            timestamp=time.time(),
            swap_active=swap_active,
        )

    def _snapshot_cpu(self) -> PressureSnapshot:
        total_bytes, available_bytes = _read_proc_meminfo()
        avail_pct = available_bytes / total_bytes if total_bytes else 0

        if avail_pct < _CPU_AVAILABLE_PCT_CRIT:
            level = "critical"
        elif avail_pct < _CPU_AVAILABLE_PCT_WARN:
            level = "warning"
        else:
            level = "ok"

        used_bytes = total_bytes - available_bytes
        return PressureSnapshot(
            level=level,
            per_pool=[
                {
                    "pool_id": 0,
                    "free_gb": round(available_bytes / (1024**3), 2),
                    "used_gb": round(used_bytes / (1024**3), 2),
                }
            ],
            timestamp=time.time(),
            swap_active=None,  # CPU Linux doesn't expose swap-active directly
        )

    def schedule_ready(self, ready_steps: list) -> List[ScheduleDecision]:
        """Per-step capacity check against the single pool.

        Sequential execution model: schedule the head step, defer the rest.
        Single-pool + sequential = simple. No bin-packing needed.
        """
        if not ready_steps:
            return []
        head = ready_steps[0]
        decisions = [
            ScheduleDecision(step_id=getattr(head, "id", "unknown"), placement=None)
        ]
        for rest in ready_steps[1:]:
            decisions.append(
                ScheduleDecision(
                    step_id=getattr(rest, "id", "unknown"),
                    placement=None,
                    deferred=True,
                    defer_reason="sequential execution; head step holds the pool",
                )
            )
        return decisions

    def feasible(self, island: list) -> Feasibility:
        """Validate-time check: does the largest model in the island fit
        in the single pool with 15% KV headroom?
        """
        if not island:
            return Feasibility(fits=True)
        # est_size_gb on AgentStep is the Phase 2 schema addition; tolerate absence
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
                f"pool budget {budget:.1f} GB"
            ),
            fatal=(max_size > self.total_memory_gb),
        )

    def classify_error(self, exc: Any) -> ClassifiedError:
        """Map raw errors into typed ClassifiedError for unified pools."""
        msg = str(exc)
        # OOM-killer signatures on Linux
        if self.name == ArchClass.CPU_X86 and (
            "OOM" in msg or "out of memory" in msg.lower() or "killed" in msg.lower()
        ):
            return ClassifiedError(
                error_class="memory",
                error_code="host_oom_killer",
                arch=self.name.value,
                recoverable=False,
                suggested_action="abort_step",
                human_message="Runner subprocess killed by OOM-killer",
                raw_error=msg,
            )
        # Swap-thrash signature on Mac (the snapshot's swap_active flag
        # would have already triggered a pause; this is the post-mortem class)
        if self.name == ArchClass.APPLE_UNIFIED and "swap" in msg.lower():
            return ClassifiedError(
                error_class="memory",
                error_code="unified_swap_thrash",
                arch=self.name.value,
                recoverable=True,
                suggested_action="evict_and_retry",
                human_message="Memory pressure forced swap; pausing and evicting LRU",
                raw_error=msg,
            )
        # Generic fallback
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
        """For unified pools, page cache makes warm re-load nearly free.

        Strategy:
        - Always evict at prev_step (freshness default)
        - Use keep_alive=0 piggybacked (one fewer roundtrip)
        - Pre-warm next_step's model during prev_step's inference
          (cheap on unified — just a re-mmap from page cache)
        """
        if next_step is None:
            return TransitionPlan(
                evict_at_prev_step=True,
                evict_via_keep_alive_zero=True,
                pre_warm_next=False,
                rationale="terminal step",
            )
        return TransitionPlan(
            evict_at_prev_step=True,
            evict_via_keep_alive_zero=True,
            pre_warm_next=True,
            pre_warm_target_gpu=None,  # no GPU concept here
            rationale="unified pool; page cache enables cheap pre-warm",
        )

    def default_keep_alive(self) -> str:
        # Unified memory (Apple Silicon, x86 CPU): reload cost dominates,
        # plenty of RAM relative to model size. Keep models warm — the
        # reload would pay full prefill cost on CPU (10s+ for 7B, 90s+
        # for 34B), and Apple's mmap'd weights stay in page cache anyway.
        return "30m"

    @classmethod
    def current(cls) -> "UnifiedArchitecture":
        # The singleton lives in api.services.architecture; consult it.
        from ..architecture import _get_current

        return _get_current()  # type: ignore[return-value]
