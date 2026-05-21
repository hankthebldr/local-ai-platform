"""Tests for the Architecture protocol + supporting types.

Phase 1 / Task 1.1 of architecture-aware orchestration.
See docs/plans/2026-05-19-architecture-aware-orchestration-implementation.md
"""

from __future__ import annotations

import time

import pytest

from api.services.architecture import (
    ArchClass,
    PressureSnapshot,
    ScheduleDecision,
    Feasibility,
    ClassifiedError,
    TransitionPlan,
)


class TestArchClass:
    def test_enum_string_values(self):
        assert ArchClass.APPLE_UNIFIED.value == "apple_unified"
        assert ArchClass.CPU_X86.value == "cpu_x86"
        assert ArchClass.GPU_NVIDIA_SINGLE.value == "gpu_nvidia_single"
        assert ArchClass.GPU_NVIDIA_MULTI.value == "gpu_nvidia_multi"
        assert ArchClass.UNKNOWN.value == "unknown"

    def test_arch_class_membership(self):
        # The enum is the closed set of supported arch classes.
        assert len(list(ArchClass)) == 5


class TestPressureSnapshot:
    def test_minimal_construction(self):
        snap = PressureSnapshot(
            level="ok",
            per_pool=[{"pool_id": 0, "free_gb": 50.0, "used_gb": 30.0}],
            timestamp=time.time(),
        )
        assert snap.level == "ok"
        assert len(snap.per_pool) == 1
        assert snap.timestamp > 0

    def test_level_accepts_only_valid_values(self):
        # Pydantic Literal validation
        for level in ("ok", "warning", "critical"):
            PressureSnapshot(level=level, per_pool=[], timestamp=1.0)
        with pytest.raises(ValueError):
            PressureSnapshot(level="exploded", per_pool=[], timestamp=1.0)

    def test_per_pool_is_list_of_dicts(self):
        snap = PressureSnapshot(
            level="warning",
            per_pool=[
                {"pool_id": 0, "free_gb": 10.0, "used_gb": 70.0},
                {"pool_id": 1, "free_gb": 5.0, "used_gb": 75.0},
            ],
            timestamp=1.0,
        )
        assert snap.per_pool[1]["free_gb"] == 5.0


class TestScheduleDecision:
    def test_unplaced_step(self):
        d = ScheduleDecision(step_id="s1", placement=None, deferred=False)
        assert d.placement is None
        assert d.deferred is False

    def test_placed_on_gpu(self):
        d = ScheduleDecision(step_id="s1", placement=1)
        assert d.placement == 1

    def test_deferred_with_reason(self):
        d = ScheduleDecision(
            step_id="big-step",
            placement=None,
            deferred=True,
            defer_reason="no GPU has 80 GB free",
        )
        assert d.deferred is True
        assert "80 GB" in d.defer_reason


class TestFeasibility:
    def test_fits(self):
        f = Feasibility(fits=True, reason=None, fatal=False)
        assert f.fits is True

    def test_does_not_fit_recoverable(self):
        # E.g. concurrent steps could be split sequentially
        f = Feasibility(
            fits=False,
            reason="concurrent island exceeds budget by 12 GB",
            fatal=False,
        )
        assert f.fits is False
        assert f.fatal is False

    def test_does_not_fit_fatal(self):
        # E.g. single step's model exceeds the largest pool, period
        f = Feasibility(
            fits=False,
            reason="step requires 120 GB; largest pool is 80 GB",
            fatal=True,
        )
        assert f.fatal is True


class TestClassifiedError:
    def test_recoverable_with_action(self):
        err = ClassifiedError(
            error_class="memory",
            error_code="vram_oom",
            arch="gpu_nvidia_single",
            deployment="container",
            recoverable=True,
            suggested_action="evict_and_retry",
            human_message="CUDA OOM on the only GPU; evicting LRU model and retrying",
        )
        assert err.error_class == "memory"
        assert err.error_code == "vram_oom"
        assert err.recoverable is True
        assert err.suggested_action == "evict_and_retry"

    def test_terminal_error(self):
        err = ClassifiedError(
            error_class="hardware",
            error_code="gpu_lost_mid_run",
            arch="gpu_nvidia_multi",
            deployment="container",
            recoverable=False,
            suggested_action="abort_workflow",
            human_message="GPU 1 went offline; aborting",
        )
        assert err.recoverable is False


class TestTransitionPlan:
    def test_no_transition_needed(self):
        plan = TransitionPlan(
            evict_at_prev_step=False,
            evict_via_keep_alive_zero=False,
            pre_warm_next=False,
        )
        assert plan.evict_at_prev_step is False

    def test_evict_and_prewarm(self):
        plan = TransitionPlan(
            evict_at_prev_step=True,
            evict_via_keep_alive_zero=True,
            pre_warm_next=True,
            pre_warm_target_gpu=1,
            rationale="next step uses different large model; alt GPU has room",
        )
        assert plan.evict_at_prev_step is True
        assert plan.pre_warm_next is True
        assert plan.pre_warm_target_gpu == 1
