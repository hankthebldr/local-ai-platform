"""Phase 5b — pre-warm telemetry + workflow-level opt-out.

Covers:
  1. PreWarmEvent records get emitted to workflow_run.pre_warm_events
  2. Hit/miss resolution against step_results (warm consumer → hit;
     cold consumer or pre-warm error → miss; no consumer → None)
  3. RunTelemetrySummary aggregates pre_warm_count / hits / misses
  4. defaults.disable_pre_warm: true suppresses pre-warm entirely
  5. target_gpu_hint carries through from arch.transition_plan
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from api.models.workflow_models import (
    AgentStep,
    PreWarmEvent,
    StepPrompt,
    StepResult,
    WorkflowContext,
    WorkflowDefaults,
    WorkflowDefinition,
    WorkflowRun,
)
from api.services.workflow_engine import (
    _aggregate_telemetry,
    _resolve_pre_warm_hits,
)


# ── Schema acceptance ────────────────────────────────────────────────────


def test_workflow_defaults_accepts_disable_pre_warm():
    defaults = WorkflowDefaults()
    assert defaults.disable_pre_warm is None  # arch-detected by default

    defaults = WorkflowDefaults(disable_pre_warm=True)
    assert defaults.disable_pre_warm is True


def test_workflow_run_default_pre_warm_events_is_empty_list():
    run = WorkflowRun(
        workflow_id="w",
        context=WorkflowContext(),
    )
    assert run.pre_warm_events == []


def test_pre_warm_event_round_trips():
    event = PreWarmEvent(
        model="qwen2.5-coder:32b",
        dispatched_at=datetime.utcnow(),
        load_duration_ms=2400.0,
        target_gpu_hint=1,
        hit=True,
        hit_step_id="step_b",
    )
    payload = event.model_dump()
    rehydrated = PreWarmEvent.model_validate(payload)
    assert rehydrated.target_gpu_hint == 1
    assert rehydrated.hit is True
    assert rehydrated.hit_step_id == "step_b"


# ── _resolve_pre_warm_hits ────────────────────────────────────────────────


def _make_run(pre_warm_events, step_results):
    return WorkflowRun(
        workflow_id="w",
        context=WorkflowContext(),
        step_results=step_results,
        pre_warm_events=pre_warm_events,
    )


def test_resolve_hit_when_consumer_loaded_warm():
    """Pre-warm fired, consumer step started after, load_duration < 100ms = hit."""
    t0 = datetime.utcnow()
    event = PreWarmEvent(model="m-a", dispatched_at=t0, load_duration_ms=1800.0)
    consumer = StepResult(
        step_id="s2",
        status="completed",
        model_used="m-a",
        started_at=t0 + timedelta(seconds=2),
        load_duration_ms=12.0,  # warm
    )
    run = _make_run([event], [consumer])
    _resolve_pre_warm_hits(run)
    assert run.pre_warm_events[0].hit is True
    assert run.pre_warm_events[0].hit_step_id == "s2"


def test_resolve_miss_when_consumer_paid_cold_load():
    """Pre-warm fired but the consumer still paid a cold load — model was
    evicted between pre-warm and consumption."""
    t0 = datetime.utcnow()
    event = PreWarmEvent(model="m-a", dispatched_at=t0, load_duration_ms=1800.0)
    consumer = StepResult(
        step_id="s2",
        status="completed",
        model_used="m-a",
        started_at=t0 + timedelta(seconds=2),
        load_duration_ms=4200.0,  # cold
    )
    run = _make_run([event], [consumer])
    _resolve_pre_warm_hits(run)
    assert run.pre_warm_events[0].hit is False
    assert run.pre_warm_events[0].hit_step_id == "s2"


def test_resolve_miss_when_pre_warm_errored():
    """A pre-warm that raised always counts as a miss, regardless of how
    the consumer eventually loaded."""
    t0 = datetime.utcnow()
    event = PreWarmEvent(model="m-a", dispatched_at=t0, error="connection refused")
    consumer = StepResult(
        step_id="s2",
        status="completed",
        model_used="m-a",
        started_at=t0 + timedelta(seconds=2),
        load_duration_ms=5.0,  # warm, but pre-warm errored so it's not our hit
    )
    run = _make_run([event], [consumer])
    _resolve_pre_warm_hits(run)
    assert run.pre_warm_events[0].hit is False


def test_resolve_none_when_no_consumer_found():
    """Pre-warm fired but workflow short-circuited (failure, cancel) before
    any step consumed the model. hit=None means "indeterminate"."""
    t0 = datetime.utcnow()
    event = PreWarmEvent(model="m-a", dispatched_at=t0, load_duration_ms=1800.0)
    # No step uses m-a:
    consumer = StepResult(
        step_id="s2",
        status="completed",
        model_used="m-b",
        started_at=t0 + timedelta(seconds=2),
        load_duration_ms=12.0,
    )
    run = _make_run([event], [consumer])
    _resolve_pre_warm_hits(run)
    assert run.pre_warm_events[0].hit is None


def test_resolve_picks_earliest_consumer_when_multiple_match():
    """If two later steps both use the pre-warmed model, the earlier-started
    one is the intended consumer — its load_duration determines hit/miss."""
    t0 = datetime.utcnow()
    event = PreWarmEvent(model="m-a", dispatched_at=t0, load_duration_ms=1800.0)
    earlier = StepResult(
        step_id="s2",
        status="completed",
        model_used="m-a",
        started_at=t0 + timedelta(seconds=2),
        load_duration_ms=12.0,  # warm
    )
    later = StepResult(
        step_id="s3",
        status="completed",
        model_used="m-a",
        started_at=t0 + timedelta(seconds=20),
        load_duration_ms=2400.0,  # cold (evicted by then) — but not our consumer
    )
    run = _make_run([event], [later, earlier])  # intentionally out of order
    _resolve_pre_warm_hits(run)
    assert run.pre_warm_events[0].hit is True
    assert run.pre_warm_events[0].hit_step_id == "s2"


def test_resolve_ignores_consumer_started_before_dispatch():
    """A step that started BEFORE the pre-warm dispatched can't be the
    consumer. (Edge case: pre-warm fired late in the run for a model that
    was already used earlier.)"""
    t0 = datetime.utcnow()
    event = PreWarmEvent(
        model="m-a",
        dispatched_at=t0 + timedelta(seconds=10),
        load_duration_ms=1800.0,
    )
    earlier_step = StepResult(
        step_id="s1",
        status="completed",
        model_used="m-a",
        started_at=t0,  # BEFORE the pre-warm
        load_duration_ms=12.0,
    )
    run = _make_run([event], [earlier_step])
    _resolve_pre_warm_hits(run)
    assert run.pre_warm_events[0].hit is None  # no qualifying consumer


# ── _aggregate_telemetry with pre-warm ───────────────────────────────────


def test_aggregate_includes_pre_warm_fields():
    t0 = datetime.utcnow()
    events = [
        PreWarmEvent(
            model="m-a",
            dispatched_at=t0,
            load_duration_ms=1800.0,
            hit=True,
            hit_step_id="s2",
        ),
        PreWarmEvent(
            model="m-b",
            dispatched_at=t0,
            load_duration_ms=2200.0,
            hit=False,
            hit_step_id="s3",
        ),
        PreWarmEvent(
            model="m-c",
            dispatched_at=t0,
            error="timeout",
            hit=False,
        ),
    ]
    # Need at least one step with telemetry so _aggregate_telemetry doesn't bail
    steps = [
        StepResult(
            step_id="s1",
            status="completed",
            model_used="m-a",
            load_duration_ms=12.0,
            eval_duration_ms=14000.0,
        )
    ]
    summary = _aggregate_telemetry(steps, events)
    assert summary is not None
    assert summary.pre_warm_count == 3
    assert summary.pre_warm_hits == 1
    assert summary.pre_warm_misses == 2
    # Total only counts events that completed (not the errored one)
    assert summary.total_pre_warm_load_ms == 4000.0


def test_aggregate_works_without_pre_warm_events():
    """Backwards-compat: callers can omit pre_warm_events entirely."""
    steps = [
        StepResult(
            step_id="s1",
            status="completed",
            model_used="m-a",
            load_duration_ms=12.0,
            eval_duration_ms=14000.0,
        )
    ]
    summary = _aggregate_telemetry(steps)
    assert summary is not None
    assert summary.pre_warm_count == 0


# ── End-to-end opt-out + telemetry ───────────────────────────────────────


class _FakeArch:
    def __init__(self, pre_warm_next=True):
        self.name = SimpleNamespace(value="fake_arch")
        self.total_memory_gb = 48.0
        self._pre_warm_next = pre_warm_next

    def transition_plan(self, prev_step, next_step):
        return SimpleNamespace(
            pre_warm_next=self._pre_warm_next,
            pre_warm_target_gpu=1,  # arbitrary hint to verify it's recorded
            evict_at_prev_step=True,
            evict_via_keep_alive_zero=True,
            rationale="test",
        )

    def schedule_ready(self, ready):
        if not ready:
            return []
        head = SimpleNamespace(step_id=ready[0].id, placement=0, deferred=False)
        rest = [
            SimpleNamespace(
                step_id=s.id, placement=None, deferred=True, defer_reason="seq"
            )
            for s in ready[1:]
        ]
        return [head] + rest

    def snapshot(self):
        return SimpleNamespace(
            level="ok",
            per_pool=[{"pool_id": 0, "free_gb": 40, "used_gb": 8}],
            timestamp=time.time(),
        )

    def feasible(self, island):
        return SimpleNamespace(fits=True, reason=None)


def _make_engine_with_arch(arch):
    from api.services import architecture as arch_mod
    from api.services.workflow_engine import WorkflowEngine

    class _Stub:
        def __init__(self):
            self.pre_warm_calls = []

        def chat(self, model, messages, **kw):
            return {"content": "ok", "prompt_eval_count": 1, "eval_count": 1}

        def pre_warm(self, model, keep_alive=None):
            self.pre_warm_calls.append(model)
            return {"model": model, "load_duration_ms": 1234.0}

        def health_check(self):
            return True

        def list_models(self):
            return [{"name": "model-a:latest"}, {"name": "model-b:latest"}]

    arch_mod._set_current(arch)
    return WorkflowEngine(_Stub())


def _two_step_diff_models_workflow(disable_pre_warm=None):
    return WorkflowDefinition(
        id="t",
        name="t",
        steps=[
            AgentStep(
                id="step_a",
                name="A",
                model="model-a",
                prompt=StepPrompt(role_inline="r", task="produce_a"),
                outputs=["out_a"],
            ),
            AgentStep(
                id="step_b",
                name="B",
                model="model-b",
                prompt=StepPrompt(role_inline="r", task="produce_b"),
                outputs=["out_b"],
                depends_on=["step_a"],
            ),
        ],
        defaults=WorkflowDefaults(disable_pre_warm=disable_pre_warm),
    )


def test_disable_pre_warm_in_yaml_suppresses_pre_warm(tmp_path, monkeypatch):
    """Setting defaults.disable_pre_warm: true on a workflow stops the
    engine from firing any pre-warm, even when arch.transition_plan
    would say yes."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    from api.services import architecture as arch_mod

    arch = _FakeArch(pre_warm_next=True)
    engine = _make_engine_with_arch(arch)
    try:
        run = engine.run(_two_step_diff_models_workflow(disable_pre_warm=True), seed={})
        time.sleep(0.1)
        assert run.status == "completed"
        # No pre-warm fired (workflow opted out)
        assert engine.ollama.pre_warm_calls == []
        # No pre-warm events recorded
        assert run.pre_warm_events == []
    finally:
        arch_mod._current_architecture = None


def test_pre_warm_events_emitted_with_target_gpu_hint(tmp_path, monkeypatch):
    """Pre-warm dispatches show up as PreWarmEvent records on the run,
    with the arch's pre_warm_target_gpu carried into target_gpu_hint."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    from api.services import architecture as arch_mod

    arch = _FakeArch(pre_warm_next=True)
    engine = _make_engine_with_arch(arch)
    try:
        run = engine.run(_two_step_diff_models_workflow(), seed={})
        time.sleep(0.2)
        assert run.status == "completed"
        # Exactly one pre-warm event for model-b
        assert len(run.pre_warm_events) == 1
        event = run.pre_warm_events[0]
        assert event.model == "model-b:latest"
        assert event.target_gpu_hint == 1  # from arch.transition_plan above
        # The worker should have populated load_duration before we checked
        assert event.load_duration_ms == 1234.0
        # Telemetry summary should include pre-warm counts
        assert run.telemetry_summary is not None
        assert run.telemetry_summary.pre_warm_count == 1
    finally:
        arch_mod._current_architecture = None
