"""Phase 4 — per-step extension instrumentation + run-level rollup.

Schema-only PR: the engine-side capture (step_executor populating
skills_activated / mcp_calls / plugin_tools_called) lands once engine
wiring through MCPRunnerPool is in. This file pins the schema shape and
the aggregation contract so the wiring PR can just write to the fields.
"""

from __future__ import annotations


import pytest

from api.models.workflow_models import (
    MCPCall,
    PluginToolCall,
    SkillActivation,
    StepResult,
    WorkflowContext,
    WorkflowRun,
    aggregate_extension_stats,
)

# ── Pydantic model shape ───────────────────────────────────────────────


def test_skill_activation_defaults():
    s = SkillActivation(
        plugin_id="general-skills",
        skill_id="concise-writer",
        trigger="keyword",
        trigger_match="concise",
        injected_into="system",
        injected_chars=524,
    )
    assert s.plugin_id == "general-skills"
    assert s.trigger_match == "concise"
    # trigger_match is optional (None when trigger is "explicit").
    s_explicit = SkillActivation(
        plugin_id="x",
        skill_id="y",
        trigger="explicit",
        injected_into="messages",
        injected_chars=0,
    )
    assert s_explicit.trigger_match is None


def test_skill_activation_rejects_unknown_trigger():
    with pytest.raises(ValueError):
        SkillActivation(
            plugin_id="x",
            skill_id="y",
            trigger="psychic",  # not in the Literal union
            injected_into="system",
            injected_chars=0,
        )


def test_skill_activation_rejects_unknown_injection_site():
    with pytest.raises(ValueError):
        SkillActivation(
            plugin_id="x",
            skill_id="y",
            trigger="keyword",
            injected_into="footer",
            injected_chars=0,
        )


def test_mcp_call_defaults_and_status_union():
    call = MCPCall(server_id="fs", tool_name="read_file")
    assert call.status == "ok"
    assert call.duration_ms == 0.0
    assert call.request_size_bytes == 0
    timed = MCPCall(
        server_id="fs",
        tool_name="read_file",
        status="timeout",
        duration_ms=30000.0,
    )
    assert timed.status == "timeout"
    with pytest.raises(ValueError):
        MCPCall(server_id="fs", tool_name="x", status="nuked")


def test_plugin_tool_call_carries_error_class():
    ok = PluginToolCall(plugin_id="xdm", tool_id="lookup", duration_ms=12.5)
    assert ok.status == "ok"
    failed = PluginToolCall(
        plugin_id="xdm",
        tool_id="lookup",
        status="error",
        error_class="TimeoutError",
    )
    assert failed.error_class == "TimeoutError"


# ── StepResult instrumentation fields ─────────────────────────────────


def test_step_result_extension_fields_default_empty():
    r = StepResult(step_id="s1")
    assert r.skills_activated == []
    assert r.mcp_calls == []
    assert r.plugin_tools_called == []
    assert r.extension_overhead_ms == 0.0


def test_step_result_accepts_populated_instrumentation():
    r = StepResult(
        step_id="s1",
        skills_activated=[
            SkillActivation(
                plugin_id="gs",
                skill_id="concise",
                trigger="keyword",
                trigger_match="concise",
                injected_into="system",
                injected_chars=400,
            )
        ],
        mcp_calls=[
            MCPCall(
                server_id="fs",
                tool_name="read_file",
                duration_ms=142.5,
                status="ok",
                request_size_bytes=50,
                response_size_bytes=1024,
            )
        ],
        plugin_tools_called=[
            PluginToolCall(plugin_id="xdm", tool_id="lookup", duration_ms=8.0)
        ],
        extension_overhead_ms=150.5,
    )
    assert r.skills_activated[0].injected_chars == 400
    assert r.mcp_calls[0].response_size_bytes == 1024
    assert r.plugin_tools_called[0].tool_id == "lookup"
    assert r.extension_overhead_ms == 150.5


def test_step_result_round_trips_through_json():
    """Forward-compat: serializing then re-loading keeps the new shape."""
    r = StepResult(
        step_id="s1",
        skills_activated=[
            SkillActivation(
                plugin_id="gs",
                skill_id="concise",
                trigger="explicit",
                injected_into="system",
                injected_chars=0,
            )
        ],
    )
    raw = r.model_dump(mode="json")
    rebuilt = StepResult.model_validate(raw)
    assert rebuilt.skills_activated[0].plugin_id == "gs"


def test_legacy_step_result_without_extension_fields_loads_clean():
    """Phase 1-3 runs serialized before Phase 4 must deserialize unchanged."""
    legacy = {
        "step_id": "s1",
        "status": "completed",
        "model_used": "qwen2.5:7b",
        "duration_seconds": 4.2,
    }
    r = StepResult.model_validate(legacy)
    assert r.skills_activated == []
    assert r.mcp_calls == []
    assert r.extension_overhead_ms == 0.0


# ── WorkflowRun aggregates ────────────────────────────────────────────


def _ctx():
    return WorkflowContext(seed={})


def test_workflow_run_defaults_zero_aggregates():
    run = WorkflowRun(workflow_id="w", context=_ctx())
    assert run.skills_activated_total == 0
    assert run.mcp_invocations_total == 0
    assert run.plugin_tools_invoked_total == 0
    assert run.mcp_servers_used == []
    assert run.extension_overhead_seconds == 0.0


def test_aggregate_extension_stats_empty_run_is_idempotent():
    run = WorkflowRun(workflow_id="w", context=_ctx())
    aggregate_extension_stats(run)
    aggregate_extension_stats(run)
    assert run.skills_activated_total == 0
    assert run.extension_overhead_seconds == 0.0


def _populated_run() -> WorkflowRun:
    s1 = StepResult(
        step_id="s1",
        skills_activated=[
            SkillActivation(
                plugin_id="gs",
                skill_id="concise",
                trigger="keyword",
                trigger_match="concise",
                injected_into="system",
                injected_chars=400,
            )
        ],
        mcp_calls=[
            MCPCall(server_id="fs", tool_name="read", duration_ms=200.0),
            MCPCall(server_id="fs", tool_name="list", duration_ms=80.0),
        ],
        plugin_tools_called=[
            PluginToolCall(plugin_id="xdm", tool_id="lookup", duration_ms=8.0)
        ],
        extension_overhead_ms=288.0,
    )
    s2 = StepResult(
        step_id="s2",
        skills_activated=[
            SkillActivation(
                plugin_id="xdm",
                skill_id="xdm-rule-writer",
                trigger="explicit",
                injected_into="system",
                injected_chars=2048,
            )
        ],
        mcp_calls=[
            # Second server makes its appearance — should land in mcp_servers_used.
            MCPCall(server_id="web-search", tool_name="query", duration_ms=1100.0),
        ],
        plugin_tools_called=[],
        extension_overhead_ms=1112.0,
    )
    run = WorkflowRun(workflow_id="w", context=_ctx(), step_results=[s1, s2])
    return run


def test_aggregate_extension_stats_sums_across_steps():
    run = _populated_run()
    aggregate_extension_stats(run)
    assert run.skills_activated_total == 2
    assert run.mcp_invocations_total == 3
    assert run.plugin_tools_invoked_total == 1
    # Server ordering follows first-seen.
    assert run.mcp_servers_used == ["fs", "web-search"]
    # 288 + 1112 = 1400 ms → 1.400 s
    assert run.extension_overhead_seconds == pytest.approx(1.4)


def test_aggregate_extension_stats_dedupes_servers_preserving_order():
    """A workflow with repeated server uses across steps should appear once
    in mcp_servers_used and in first-seen order."""
    s1 = StepResult(
        step_id="s1",
        mcp_calls=[
            MCPCall(server_id="fs", tool_name="r"),
            MCPCall(server_id="rag", tool_name="search"),
        ],
    )
    s2 = StepResult(
        step_id="s2",
        mcp_calls=[
            MCPCall(server_id="fs", tool_name="r"),
            MCPCall(server_id="web", tool_name="q"),
            MCPCall(server_id="rag", tool_name="search"),
        ],
    )
    run = WorkflowRun(workflow_id="w", context=_ctx(), step_results=[s1, s2])
    aggregate_extension_stats(run)
    assert run.mcp_servers_used == ["fs", "rag", "web"]


def test_aggregate_is_idempotent_when_called_repeatedly():
    run = _populated_run()
    aggregate_extension_stats(run)
    snapshot = (
        run.skills_activated_total,
        run.mcp_invocations_total,
        run.plugin_tools_invoked_total,
        list(run.mcp_servers_used),
        run.extension_overhead_seconds,
    )
    aggregate_extension_stats(run)
    aggregate_extension_stats(run)
    assert (
        run.skills_activated_total,
        run.mcp_invocations_total,
        run.plugin_tools_invoked_total,
        list(run.mcp_servers_used),
        run.extension_overhead_seconds,
    ) == snapshot


def test_workflow_run_json_round_trip_with_aggregates():
    run = _populated_run()
    aggregate_extension_stats(run)
    raw = run.model_dump(mode="json")
    rebuilt = WorkflowRun.model_validate(raw)
    assert rebuilt.skills_activated_total == 2
    assert rebuilt.mcp_servers_used == ["fs", "web-search"]
    assert rebuilt.extension_overhead_seconds == pytest.approx(1.4)


# ── Engine integration: _persist_run rolls before serializing ─────────


def test_persist_run_aggregates_before_writing(tmp_path, monkeypatch):
    """workflow_engine._persist_run calls aggregate_extension_stats so
    operators reading /api/workflows/runs/{id} always see populated totals."""
    import json

    from api.services import workflow_engine as we_mod
    from api.services.ollama_service import OllamaService
    from api.services.workflow_engine import WorkflowEngine
    from api.models.workflow_models import AgentStep, WorkflowDefinition

    monkeypatch.setattr(we_mod, "DATA_DIR", str(tmp_path))
    engine = WorkflowEngine(OllamaService())

    # Minimal definition just so _persist_run has something to walk.
    defn = WorkflowDefinition(
        id="phase4-rollup",
        name="P4 rollup",
        steps=[
            AgentStep(
                id="s1",
                name="S1",
                role="fast",
                system_prompt="p",
                outputs=["x"],
            )
        ],
    )

    run = _populated_run()
    run.workflow_id = "phase4-rollup"
    engine._persist_run(run, defn)  # noqa: SLF001

    run_json = tmp_path / run.run_id / "run.json"
    assert run_json.exists()
    persisted = json.loads(run_json.read_text())
    assert persisted["skills_activated_total"] == 2
    assert persisted["mcp_invocations_total"] == 3
    assert persisted["plugin_tools_invoked_total"] == 1
    assert persisted["mcp_servers_used"] == ["fs", "web-search"]
    assert persisted["extension_overhead_seconds"] == pytest.approx(1.4)
