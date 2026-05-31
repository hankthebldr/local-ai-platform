"""Phase 4.3 — mcp_tool_invoker captures MCPCall onto the step result.

Mirrors test_plugin_tool_instrumentation.py for the MCP transport.
Coverage:
  - mcp_tool_invoker registered as a built-in hook
  - records ok / error / timeout MCPCalls with request/response sizes
  - extension_overhead_ms accumulates across for_each iterations
  - instrumentation no-ops cleanly when no step_result is attached
  - routes through MCPService.invoke_tool with the workflow run_id so
    the warm runner pool services the call
  - workspace store_as resolution sees both plugin_tool_invoker and
    mcp_tool_invoker (validator parity)
  - aggregate_extension_stats picks up mcp_invocations_total and
    mcp_servers_used from recorded calls
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.hooks.builtins.mcp_tool_invoker import (
    MCPToolInvokerHook,
    set_mcp_service,
)
from api.models.workflow_models import (
    MCPCall,
    StepResult,
    WorkflowContext,
    WorkflowRun,
    aggregate_extension_stats,
)
from api.services.hook_bus import HookContext


@pytest.fixture
def fake_service():
    service = MagicMock()
    set_mcp_service(service)
    yield service
    set_mcp_service(None)


def _ctx(step_result, *, step_id="s1", run_id="run-X", workspace=None):
    context = WorkflowContext(seed={}, workspace=workspace or {})
    workflow_run = SimpleNamespace(context=context, run_id=run_id)
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


# ── Hook shape ─────────────────────────────────────────────────────────


def test_hook_name_and_stage():
    hook = MCPToolInvokerHook(server_id="fs", tool_name="read", store_as="contents")
    assert hook.name == "mcp_tool_invoker"
    assert hook.stage == "before_step"


# ── ok call ────────────────────────────────────────────────────────────


def test_records_ok_call(fake_service):
    fake_service.invoke_tool.return_value = {"bytes": "hello"}
    hook = MCPToolInvokerHook(
        server_id="filesystem-local",
        tool_name="read_file",
        store_as="contents",
        params_from={"path": "seed.target"},
    )
    sr = StepResult(step_id="s1")
    ctx, context = _ctx(sr)
    context.seed = {"target": "/tmp/x"}
    hook(ctx)
    assert len(sr.mcp_calls) == 1
    call = sr.mcp_calls[0]
    assert call.server_id == "filesystem-local"
    assert call.tool_name == "read_file"
    assert call.status == "ok"
    assert call.duration_ms >= 0.0
    # Both sizes are non-negative; response captured from the dict result.
    assert call.request_size_bytes >= 0
    assert call.response_size_bytes > 0
    # extension_overhead_ms accumulated.
    assert sr.extension_overhead_ms >= call.duration_ms


def test_routes_run_id_and_scope_to_invoke_tool(fake_service):
    fake_service.invoke_tool.return_value = {}
    hook = MCPToolInvokerHook(
        server_id="fs", tool_name="read", store_as="r", scope="step"
    )
    ctx, _ = _ctx(StepResult(step_id="s1"), run_id="abc-123")
    hook(ctx)
    # Confirm the wiring went through the warm-pool path.
    args, kwargs = fake_service.invoke_tool.call_args
    assert kwargs.get("run_id") == "abc-123"
    assert kwargs.get("scope") == "step"


# ── error path ─────────────────────────────────────────────────────────


def test_records_error_call(fake_service):
    fake_service.invoke_tool.side_effect = RuntimeError("upstream broke")
    hook = MCPToolInvokerHook(
        server_id="fs", tool_name="bad", store_as="r", params_from={}
    )
    sr = StepResult(step_id="s1")
    ctx, _ = _ctx(sr)
    result = hook(ctx)
    assert result.action == "fail"
    assert len(sr.mcp_calls) == 1
    call = sr.mcp_calls[0]
    assert call.status == "error"
    assert call.error_message == "upstream broke"


def test_records_timeout_call(fake_service):
    fake_service.invoke_tool.side_effect = TimeoutError("30s deadline")
    hook = MCPToolInvokerHook(
        server_id="fs", tool_name="slow", store_as="r", params_from={}
    )
    sr = StepResult(step_id="s1")
    ctx, _ = _ctx(sr)
    result = hook(ctx)
    assert result.action == "fail"
    assert sr.mcp_calls[0].status == "timeout"


# ── for_each: one record per iteration ─────────────────────────────────


def test_for_each_records_one_call_per_iteration(fake_service):
    fake_service.invoke_tool.side_effect = [
        {"i": 0},
        {"i": 1},
        {"i": 2},
    ]
    hook = MCPToolInvokerHook(
        server_id="fs",
        tool_name="read",
        store_as="results",
        for_each="seed.items",
        param_template={"path": "{{ item }}"},
    )
    sr = StepResult(step_id="s1")
    context = WorkflowContext(seed={"items": ["a", "b", "c"]}, workspace={})
    wf = SimpleNamespace(context=context, run_id="run-Z")
    ctx = HookContext(
        workflow=wf,
        step=SimpleNamespace(id="s1"),
        prompt=None,
        step_result=sr,
    )
    hook(ctx)
    assert len(sr.mcp_calls) == 3
    assert all(c.tool_name == "read" for c in sr.mcp_calls)
    expected = sum(c.duration_ms for c in sr.mcp_calls)
    assert sr.extension_overhead_ms == pytest.approx(expected, abs=0.01)


# ── instrumentation no-op without step_result ──────────────────────────


def test_instrumentation_noop_without_step_result(fake_service):
    fake_service.invoke_tool.return_value = {"ok": True}
    hook = MCPToolInvokerHook(
        server_id="fs", tool_name="read", store_as="r", params_from={}
    )
    ctx, _ = _ctx(None)  # step_result intentionally absent
    result = hook(ctx)
    assert result.action == "continue"
    # No crash, no record (there's nowhere to record).


# ── Aggregation picks up Phase 4.3 records ─────────────────────────────


def test_aggregate_extension_stats_counts_recorded_mcp_calls():
    sr1 = StepResult(
        step_id="s1",
        mcp_calls=[
            MCPCall(server_id="fs", tool_name="read", duration_ms=10.0),
            MCPCall(server_id="rag", tool_name="search", duration_ms=15.0),
        ],
        extension_overhead_ms=25.0,
    )
    sr2 = StepResult(
        step_id="s2",
        mcp_calls=[
            MCPCall(server_id="fs", tool_name="list", duration_ms=8.0),
        ],
        extension_overhead_ms=8.0,
    )
    run = WorkflowRun(
        workflow_id="w",
        context=WorkflowContext(seed={}),
        step_results=[sr1, sr2],
    )
    aggregate_extension_stats(run)
    assert run.mcp_invocations_total == 3
    assert run.mcp_servers_used == ["fs", "rag"]
    assert run.extension_overhead_seconds == pytest.approx(0.033, abs=0.001)


# ── Hook registry recognizes mcp_tool_invoker ──────────────────────────


def test_engine_factory_registers_mcp_tool_invoker():
    """The engine's hook factory must know about mcp_tool_invoker so YAML
    workflows can declare it under hooks.before_step."""
    from api.models.workflow_models import HookSpec
    from api.services.ollama_service import OllamaService
    from api.services.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(OllamaService())
    spec = HookSpec(
        name="mcp_tool_invoker",
        config={
            "server_id": "fs",
            "tool_name": "read",
            "store_as": "contents",
        },
    )
    hook = engine._instantiate_hook(spec, "before_step")  # noqa: SLF001
    assert isinstance(hook, MCPToolInvokerHook)
    assert hook.server_id == "fs"


def test_validator_recognizes_mcp_tool_invoker_store_as():
    """When mcp_tool_invoker declares store_as, the workflow validator must
    treat <step_id>.<store_as> as available — matches plugin_tool_invoker
    parity."""
    from api.models.workflow_models import (
        AgentStep,
        HookSpec,
        StepHooks,
        WorkflowDefinition,
    )
    from api.services.ollama_service import OllamaService
    from api.services.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(OllamaService())
    step = AgentStep(
        id="s1",
        name="s1",
        system_prompt="use {{ s1.contents }}",
        inputs=["s1.contents"],
        outputs=["x"],
        hooks=StepHooks(
            before_step=[
                HookSpec(
                    name="mcp_tool_invoker",
                    config={
                        "server_id": "fs",
                        "tool_name": "read",
                        "store_as": "contents",
                    },
                )
            ]
        ),
    )
    wf = WorkflowDefinition(id="w", name="W", steps=[step])
    # If the validator didn't recognize the hook's store_as, the input
    # `s1.contents` would have no producer and validate() would raise.
    engine.validate(wf)
