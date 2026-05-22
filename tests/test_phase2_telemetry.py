"""Phase 2 — Architecture-aware observability instrumentation.

Covers the pure-function pieces that ship the telemetry capture:
  1. _extract_timings()    in ollama_service — ns → ms + nulls
  2. _apply_telemetry()    in step_executor — StepResult population
  3. _aggregate_telemetry() in workflow_engine — per-run summary
  4. StepResult / WorkflowRun schema — pre-Phase-2 payloads deserialize.
"""

from __future__ import annotations

from api.models.workflow_models import (
    RunTelemetrySummary,
    StepResult,
    WorkflowContext,
    WorkflowRun,
)
from api.services.ollama_service import _extract_timings
from api.services.step_executor import _apply_telemetry
from api.services.workflow_engine import _aggregate_telemetry


# ── _extract_timings ──────────────────────────────────────────────────────


def test_extract_timings_full_payload():
    """Realistic Ollama /api/chat response: all four ns fields present."""
    response = {
        "load_duration": 2_400_000_000,  # 2.4s — cold load
        "prompt_eval_duration": 850_000_000,  # 0.85s
        "eval_duration": 18_100_000_000,  # 18.1s
        "total_duration": 21_350_000_000,
    }
    timings = _extract_timings(response)
    assert timings["load_duration_ms"] == 2400.0
    assert timings["prompt_eval_duration_ms"] == 850.0
    assert timings["eval_duration_ms"] == 18100.0
    assert timings["total_duration_ms"] == 21350.0


def test_extract_timings_warm_load():
    """When the model is warm in VRAM/RAM, load_duration is ~0."""
    response = {"load_duration": 0, "total_duration": 14_700_000_000}
    timings = _extract_timings(response)
    assert timings["load_duration_ms"] == 0.0
    assert timings["total_duration_ms"] == 14700.0
    assert timings["eval_duration_ms"] is None
    assert timings["prompt_eval_duration_ms"] is None


def test_extract_timings_missing_payload():
    """Older Ollama versions or error paths may omit timing fields entirely."""
    timings = _extract_timings({})
    assert all(v is None for v in timings.values())


def test_extract_timings_handles_bad_types():
    """Don't blow up on unexpected types — degrade to None."""
    timings = _extract_timings({"load_duration": "not-a-number"})
    assert timings["load_duration_ms"] is None


# ── _apply_telemetry ──────────────────────────────────────────────────────


def test_apply_telemetry_populates_all_fields():
    """The success-path populator copies timings + arch context onto StepResult."""
    result = StepResult(step_id="s1", status="completed")
    llm_result = {
        "content": "ok",
        "load_duration_ms": 2400.0,
        "eval_duration_ms": 18100.0,
        "prompt_eval_duration_ms": 850.0,
        "total_duration_ms": 21350.0,
    }
    pressure_before = {"level": "ok", "per_pool": [{"free_gb": 80}]}
    pressure_after = {"level": "warning", "per_pool": [{"free_gb": 12}]}

    _apply_telemetry(
        result,
        llm_result,
        arch_name="gpu_nvidia_single",
        pressure_before=pressure_before,
        pressure_after=pressure_after,
    )

    assert result.load_duration_ms == 2400.0
    assert result.eval_duration_ms == 18100.0
    assert result.prompt_eval_duration_ms == 850.0
    assert result.total_duration_ms == 21350.0
    assert result.arch_name == "gpu_nvidia_single"
    assert result.pressure_before == pressure_before
    assert result.pressure_after == pressure_after
    # keep_alive_used is sourced from OLLAMA_KEEP_ALIVE; presence-only check
    # so the test isn't coupled to the env default.
    assert result.keep_alive_used is not None


def test_apply_telemetry_safe_on_empty_llm_result():
    """Failure path: llm_result may be {} if the chat call raised before
    producing a response. Telemetry helper must leave all fields None
    rather than raising KeyError."""
    result = StepResult(step_id="s1", status="failed")
    _apply_telemetry(
        result,
        llm_result={},
        arch_name=None,
        pressure_before=None,
        pressure_after=None,
    )
    assert result.load_duration_ms is None
    assert result.eval_duration_ms is None
    assert result.arch_name is None
    assert result.pressure_before is None
    assert result.pressure_after is None


# ── StepResult backwards-compat ───────────────────────────────────────────


def test_step_result_pre_phase2_payload_deserializes():
    """Checkpoint files written before Phase 2 have no telemetry fields.
    The schema must accept them — every new field is Optional with default."""
    legacy_payload = {
        "step_id": "s1",
        "status": "completed",
        "model_used": "llama3.1:8b",
        "duration_seconds": 12.4,
        "token_count": {
            "prompt_tokens": 120,
            "completion_tokens": 340,
            "total_tokens": 460,
        },
        "retries": 0,
    }
    result = StepResult.model_validate(legacy_payload)
    assert result.status == "completed"
    assert result.load_duration_ms is None
    assert result.arch_name is None
    assert result.pressure_before is None


def test_step_result_round_trip_with_telemetry():
    """A StepResult with telemetry serialises and deserialises losslessly."""
    original = StepResult(
        step_id="s1",
        status="completed",
        model_used="qwen2.5-coder:32b",
        duration_seconds=19.2,
        load_duration_ms=2400.0,
        eval_duration_ms=18100.0,
        arch_name="gpu_nvidia_single",
        pressure_before={"level": "ok"},
        pressure_after={"level": "warning"},
        keep_alive_used="0",
    )
    payload = original.model_dump()
    rehydrated = StepResult.model_validate(payload)
    assert rehydrated.load_duration_ms == 2400.0
    assert rehydrated.arch_name == "gpu_nvidia_single"
    assert rehydrated.pressure_after == {"level": "warning"}


# ── _aggregate_telemetry (Phase 2 task 2.4) ──────────────────────────────


def _step(load_ms, eval_ms=None, arch="gpu_nvidia_single"):
    return StepResult(
        step_id="s",
        status="completed",
        load_duration_ms=load_ms,
        eval_duration_ms=eval_ms,
        prompt_eval_duration_ms=200.0 if eval_ms is not None else None,
        arch_name=arch,
    )


def test_aggregate_telemetry_mixed_warm_cold():
    """Realistic multi-step run: one cold load, two warm reuses, one swap."""
    steps = [
        _step(load_ms=2400.0, eval_ms=18100.0),  # cold
        _step(load_ms=12.0, eval_ms=14700.0),  # warm
        _step(load_ms=45.0, eval_ms=12300.0),  # warm
        _step(load_ms=6800.0, eval_ms=41200.0),  # cold (model swap)
    ]
    summary = _aggregate_telemetry(steps)
    assert summary is not None
    assert summary.cold_load_count == 2
    assert summary.warm_step_count == 2
    assert summary.total_cold_load_ms == 9200.0  # 2400 + 6800
    assert summary.total_eval_ms == 86300.0
    assert summary.arch_name == "gpu_nvidia_single"


def test_aggregate_telemetry_returns_none_when_no_telemetry():
    """A run with no Phase-2 data populated returns None — preserves the
    'observability unavailable' signal rather than emitting zeros."""
    steps = [
        StepResult(step_id="s1", status="completed", duration_seconds=12.4),
        StepResult(step_id="s2", status="completed", duration_seconds=8.1),
    ]
    assert _aggregate_telemetry(steps) is None


def test_aggregate_telemetry_partial_population():
    """Some steps have telemetry, others don't (e.g. early failure before
    the LLM call). The summary aggregates only the steps that have data."""
    steps = [
        _step(load_ms=2400.0, eval_ms=18000.0),  # populated
        StepResult(step_id="s2", status="failed"),  # never ran the LLM
        _step(load_ms=5.0, eval_ms=14000.0),  # populated, warm
    ]
    summary = _aggregate_telemetry(steps)
    assert summary is not None
    assert summary.cold_load_count == 1
    assert summary.warm_step_count == 1
    assert summary.total_eval_ms == 32000.0


def test_workflow_run_with_telemetry_summary_round_trips():
    """The new WorkflowRun.telemetry_summary field deserialises cleanly."""
    run = WorkflowRun(
        workflow_id="w1",
        context=WorkflowContext(workspace={}, shared={}, seed={}),
        telemetry_summary=RunTelemetrySummary(
            total_cold_load_ms=9200.0,
            cold_load_count=2,
            warm_step_count=3,
            total_eval_ms=86300.0,
            arch_name="apple_unified",
        ),
    )
    payload = run.model_dump()
    rehydrated = WorkflowRun.model_validate(payload)
    assert rehydrated.telemetry_summary.cold_load_count == 2
    assert rehydrated.telemetry_summary.arch_name == "apple_unified"


def test_workflow_run_legacy_payload_deserializes():
    """Pre-Phase-2 checkpoint files have no telemetry_summary field."""
    legacy = {
        "run_id": "r1",
        "workflow_id": "w1",
        "status": "completed",
        "context": {"workspace": {}, "shared": {}, "seed": {}},
        "step_results": [],
    }
    rehydrated = WorkflowRun.model_validate(legacy)
    assert rehydrated.telemetry_summary is None
