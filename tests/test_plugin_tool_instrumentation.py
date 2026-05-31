"""Phase 4.2 — plugin_tool_invoker captures PluginToolCall onto the step result.

Coverage:
  - HookContext gained step_result field defaulting to None
  - step_executor passes the in-flight StepResult on both dispatches
  - plugin_tool_invoker records ok / error PluginToolCalls
  - extension_overhead_ms accumulates across multiple calls (for_each)
  - instrumentation no-ops cleanly when no step_result is attached
    (legacy callers, workflow-stage hooks)
  - aggregate_extension_stats picks up plugin_tools_invoked_total
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.hooks.builtins.plugin_tool_invoker import (
    PluginToolInvokerHook,
    set_plugin_service,
)
from api.models.workflow_models import (
    PluginToolCall,
    StepResult,
    WorkflowContext,
    WorkflowRun,
    aggregate_extension_stats,
)
from api.services.hook_bus import HookContext


@pytest.fixture
def fake_service():
    service = MagicMock()
    set_plugin_service(service)
    yield service
    set_plugin_service(None)


def _ctx(step_result, *, step_id="s1", workspace=None):
    context = WorkflowContext(seed={}, workspace=workspace or {})
    workflow_run = SimpleNamespace(context=context)
    step = SimpleNamespace(id=step_id)
    return (
        HookContext(
            workflow=workflow_run,
            step=step,
            prompt=None,
            step_result=step_result,
        ),
        context,
    )


# ── HookContext shape ───────────────────────────────────────────────


def test_hook_context_step_result_defaults_none():
    ctx = HookContext(step=SimpleNamespace(id="x"))
    assert ctx.step_result is None


def test_hook_context_accepts_step_result():
    sr = StepResult(step_id="s1")
    ctx = HookContext(step_result=sr)
    assert ctx.step_result is sr


# ── Instrumentation on success ─────────────────────────────────────


def test_plugin_tool_invoker_records_ok_call(fake_service):
    fake_service.call_tool.return_value = {"echo": "done"}
    hook = PluginToolInvokerHook(
        plugin_id="xdm-toolkit",
        tool_id="validate_xql",
        store_as="result",
        params_from={},
    )
    sr = StepResult(step_id="s1")
    ctx, _ = _ctx(sr)
    hook(ctx)
    assert len(sr.plugin_tools_called) == 1
    call = sr.plugin_tools_called[0]
    assert call.plugin_id == "xdm-toolkit"
    assert call.tool_id == "validate_xql"
    assert call.status == "ok"
    assert call.duration_ms >= 0.0
    assert call.error_class is None
    assert sr.extension_overhead_ms >= call.duration_ms


def test_plugin_tool_invoker_skips_recording_when_no_step_result(fake_service):
    """Legacy callers / workflow-stage hooks don't pass step_result —
    instrumentation must no-op without raising."""
    fake_service.call_tool.return_value = {"ok": True}
    hook = PluginToolInvokerHook(
        plugin_id="p", tool_id="t", store_as="r", params_from={}
    )
    ctx, _ = _ctx(None)  # step_result intentionally absent
    result = hook(ctx)
    # The hook still runs and stores its output normally.
    assert result.action == "continue"


# ── Instrumentation on error ───────────────────────────────────────


def test_plugin_tool_invoker_records_error_call(fake_service):
    fake_service.call_tool.side_effect = RuntimeError("boom")
    hook = PluginToolInvokerHook(
        plugin_id="xdm", tool_id="bad", store_as="r", params_from={}
    )
    sr = StepResult(step_id="s1")
    ctx, _ = _ctx(sr)
    result = hook(ctx)
    # Hook propagates the error as a fail action.
    assert result.action == "fail"
    # But the call was still recorded as an error PluginToolCall.
    assert len(sr.plugin_tools_called) == 1
    call = sr.plugin_tools_called[0]
    assert call.status == "error"
    assert call.error_class == "RuntimeError"
    # extension_overhead_ms still includes the failed call's duration.
    assert sr.extension_overhead_ms >= call.duration_ms


# ── for_each: one record per iteration ─────────────────────────────


def test_for_each_records_one_call_per_iteration(fake_service):
    fake_service.call_tool.side_effect = [
        {"i": 0},
        {"i": 1},
        {"i": 2},
    ]
    hook = PluginToolInvokerHook(
        plugin_id="p",
        tool_id="t",
        store_as="results",
        for_each="seed.items",
        param_template={"i": "{{ item }}"},
    )
    sr = StepResult(step_id="s1")
    context = WorkflowContext(seed={"items": [0, 1, 2]}, workspace={})
    workflow_run = SimpleNamespace(context=context)
    step = SimpleNamespace(id="s1")
    ctx = HookContext(workflow=workflow_run, step=step, prompt=None, step_result=sr)
    hook(ctx)
    assert len(sr.plugin_tools_called) == 3
    # Each iteration's record is recognizably from this hook.
    assert all(c.tool_id == "t" for c in sr.plugin_tools_called)
    # Overhead is the sum of the three iterations.
    expected = sum(c.duration_ms for c in sr.plugin_tools_called)
    assert sr.extension_overhead_ms == pytest.approx(expected, abs=0.01)


# ── Aggregation picks up Phase 4.2 records ─────────────────────────


def test_aggregate_extension_stats_counts_recorded_plugin_calls():
    """When the engine eventually persists this run, the rollup should
    surface the captured tool calls."""
    sr1 = StepResult(
        step_id="s1",
        plugin_tools_called=[
            PluginToolCall(plugin_id="p", tool_id="t1", duration_ms=10.0),
            PluginToolCall(plugin_id="p", tool_id="t2", duration_ms=15.0),
        ],
        extension_overhead_ms=25.0,
    )
    run = WorkflowRun(
        workflow_id="w",
        context=WorkflowContext(seed={}),
        step_results=[sr1],
    )
    aggregate_extension_stats(run)
    assert run.plugin_tools_invoked_total == 2
    assert run.extension_overhead_seconds == pytest.approx(0.025)


# ── step_executor wiring ───────────────────────────────────────────


def test_step_executor_passes_step_result_to_hook_context():
    """Confirm both HookContext dispatches in step_executor.execute carry
    step_result so hooks can record onto it. We don't need to run a full
    LLM call — just confirm the path by inspecting source.

    The previous Phase 4.4 (run rollup) test exercised aggregate +
    persist; this test pins the upstream wiring."""
    import inspect

    from api.services import step_executor as se_mod

    src = inspect.getsource(se_mod.StepExecutor.execute)
    # Both HookContext constructions should mention step_result=result.
    assert (
        src.count("step_result=result") >= 2
    ), "step_executor must pass step_result=result to every HookContext"
