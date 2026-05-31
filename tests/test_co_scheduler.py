"""Phase 2b — resource-maximization compiler pass.

Coverage:
  - compute_pressures: per-step model + MCP estimates, recurses into composites
  - pick_smaller_in_archetype: stays in-archetype role family, fits budget
  - _find_chain_slack: detects MCP-free earlier slots
  - choose_action priority: substitute → split → reorder → block
  - apply_co_scheduling_policy: off / recommend / warn_strict / reject /
    auto_substitute behaviors
  - WorkflowDefaults.co_scheduling_policy default + Literal validation
  - WorkflowEngine.validate routes recommendations through the router
"""

from __future__ import annotations

from typing import List

import pytest

from api.models.workflow_models import (
    AgentStep,
    LoopTermination,
    ToolRef,
    WorkflowDefaults,
    WorkflowDefinition,
)
from api.services.co_scheduler import (
    DEFAULT_MCP_RSS_GB,
    StepPressure,
    apply_co_scheduling_policy,
    choose_action,
    compute_pressures,
    pick_smaller_in_archetype,
)

# ── Fixtures ──────────────────────────────────────────────────────────


class _FakeArch:
    """Stand-in for Architecture.current() with a known total_memory_gb."""

    def __init__(self, total_gb: float):
        self.total_memory_gb = total_gb


def _llm_step(step_id="s", **kw) -> AgentStep:
    return AgentStep(
        id=step_id,
        name=step_id,
        system_prompt="p",
        outputs=["x"],
        **kw,
    )


def _workflow(steps: List[AgentStep], **defaults_kw) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="w",
        name="W",
        defaults=WorkflowDefaults(**defaults_kw),
        steps=steps,
    )


# ── compute_pressures ─────────────────────────────────────────────────


def test_compute_pressures_skips_steps_with_no_model_and_no_tools():
    wf = _workflow([_llm_step()])
    out = compute_pressures(wf, arch=_FakeArch(96.0))
    assert out == {}


def test_compute_pressures_model_only_no_contention_in_big_arch():
    wf = _workflow([_llm_step(est_size_gb=4.0)])
    out = compute_pressures(wf, arch=_FakeArch(96.0))
    p = out["s"]
    # 4 × 1.15 = 4.6 GB
    assert p.model_footprint_gb == pytest.approx(4.6, abs=0.01)
    assert p.is_contention is False
    assert p.archetype is None


def test_compute_pressures_mcp_estimate_uses_default_without_history():
    wf = _workflow([_llm_step(tools=[ToolRef(mcp="fs.read")])])
    out = compute_pressures(wf, arch=_FakeArch(96.0))
    p = out["s"]
    assert p.mcp_servers_in_use == ["fs"]
    assert p.mcp_peak_rss_gb_estimate == DEFAULT_MCP_RSS_GB


def test_compute_pressures_uses_service_observed_rss_when_available():
    class FakeMcp:
        def peak_rss_gb_estimate(self, sid):
            return 3.0 if sid == "fs" else None

    wf = _workflow(
        [_llm_step(tools=[ToolRef(mcp="fs.read"), ToolRef(mcp="rag.search")])]
    )
    out = compute_pressures(wf, arch=_FakeArch(96.0), mcp_service=FakeMcp())
    p = out["s"]
    assert p.mcp_peak_rss_gb_estimate == pytest.approx(3.0 + DEFAULT_MCP_RSS_GB)
    assert p.mcp_servers_in_use == ["fs", "rag"]


def test_compute_pressures_flags_contention_on_small_arch():
    """48 GB host × 0.85 = 40.8 GB budget; 40 GB model × 1.15 = 46 GB → over."""
    wf = _workflow([_llm_step(est_size_gb=40.0)])
    out = compute_pressures(wf, arch=_FakeArch(48.0))
    p = out["s"]
    assert p.is_contention is True
    assert p.combined_pressure_gb > p.effective_budget_gb


def test_compute_pressures_recurses_into_parallel_branches():
    branch_a = _llm_step(
        step_id="b1",
        est_size_gb=30.0,
        tools=[ToolRef(mcp="fs.read")],
    )
    branch_b = _llm_step(step_id="b2", est_size_gb=2.0)
    # Gather must produce the parent's declared outputs.
    gather = _llm_step(step_id="g")
    parent = AgentStep(
        id="p",
        name="p",
        kind="parallel",
        outputs=["x"],  # match gather's outputs (default ["x"] from helper)
        branches=[branch_a, branch_b],
        gather=gather,
    )
    wf = _workflow([parent])
    out = compute_pressures(wf, arch=_FakeArch(96.0))
    # Top-level parent has no model/tools → skipped. Branches appear.
    assert "p" not in out
    assert "b1" in out and "b2" in out


def test_compute_pressures_recurses_into_loop_body():
    body = _llm_step(step_id="b", est_size_gb=30.0)
    loop = AgentStep(
        id="lp",
        name="lp",
        kind="loop",
        outputs=["x"],  # match body step's outputs (default ["x"] from helper)
        body=[body],
        max_iterations=2,
        until=LoopTermination(gate="b.x == 'done'"),
    )
    wf = _workflow([loop])
    out = compute_pressures(wf, arch=_FakeArch(96.0))
    assert "b" in out
    assert out["b"].model_footprint_gb == pytest.approx(34.5, abs=0.1)


def test_compute_pressures_carries_archetype():
    step = _llm_step(
        role="coding",
        est_size_gb=4.0,
        tools=[ToolRef(mcp="bash-mcp.run")],
    )
    out = compute_pressures(_workflow([step]), arch=_FakeArch(96.0))
    assert out["s"].archetype == "bash_script"


# ── pick_smaller_in_archetype ────────────────────────────────────────


def _pressure(budget_gb: float, mcp_gb: float = 0.0) -> StepPressure:
    return StepPressure(
        step_id="s",
        model_footprint_gb=0.0,
        mcp_servers_in_use=[],
        mcp_peak_rss_gb_estimate=mcp_gb,
        combined_pressure_gb=mcp_gb,
        effective_budget_gb=budget_gb,
        is_contention=False,
    )


def test_pick_smaller_in_archetype_picks_largest_that_fits():
    """coding role with a 70b current model. Budget 12 GB - 2 GB MCP RSS =
    10 GB headroom; 7b × 1.15 KV = 8.05 GB fits, 32b × 1.15 = 36.8 GB
    doesn't. Picker should choose 7b (largest that fits)."""
    available = ["qwen2.5-coder:32b", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b"]
    rec = pick_smaller_in_archetype(
        "qwen2.5-coder:70b",
        "bash_script",
        _pressure(budget_gb=12.0, mcp_gb=2.0),
        available_models=available,
    )
    assert rec == "qwen2.5-coder:7b"


def test_pick_smaller_strictly_smaller_than_current():
    """Don't suggest the same size or larger."""
    available = ["a:7b", "b:13b"]
    rec = pick_smaller_in_archetype(
        "x:7b",
        "bash_script",
        _pressure(budget_gb=100.0, mcp_gb=0.0),
        available_models=available,
    )
    # Only smaller candidates considered; neither is < 7. Returns None.
    assert rec is None


def test_pick_smaller_returns_none_when_nothing_fits():
    """No candidate is small enough for the headroom."""
    available = ["x:32b", "y:13b"]
    rec = pick_smaller_in_archetype(
        "huge:70b",
        "bash_script",
        _pressure(budget_gb=5.0, mcp_gb=0.0),
        available_models=available,
    )
    assert rec is None


def test_pick_smaller_returns_none_for_unknown_archetype():
    assert (
        pick_smaller_in_archetype("x:7b", "no_such_archetype", _pressure(100.0)) is None
    )


# ── choose_action priority ───────────────────────────────────────────


def test_choose_action_prefers_substitution_when_archetype_fits():
    step = _llm_step(
        role="coding",
        model="qwen2.5-coder:32b",
        est_size_gb=20.0,
        tools=[ToolRef(mcp="bash-mcp.run")],
    )
    wf = _workflow([step])
    pressures = compute_pressures(wf, arch=_FakeArch(48.0))
    rec = choose_action(
        pressures["s"],
        step,
        wf,
        pressures,
        available_models=["qwen2.5-coder:7b"],
    )
    assert rec.action == "recommend_smaller_model"
    assert rec.suggested_substitution == "qwen2.5-coder:7b"
    assert rec.archetype == "bash_script"


def test_choose_action_splits_when_substitution_unavailable():
    """No archetype match → no substitution → falls through to split (one
    MCP bundled with a heavy model)."""
    step = _llm_step(
        model="generic:70b",
        est_size_gb=40.0,
        tools=[ToolRef(mcp="some.read")],
    )
    wf = _workflow([step])
    pressures = compute_pressures(wf, arch=_FakeArch(48.0))
    rec = choose_action(pressures["s"], step, wf, pressures, available_models=[])
    assert rec.action == "recommend_split_step"
    assert rec.suggested_split is not None
    assert rec.suggested_split["model_step"]["model"] == "generic:70b"


def test_choose_action_blocks_when_no_action_available():
    """Heavy model + multiple tools (can't split safely) + no slack."""
    step = _llm_step(
        model="generic:70b",
        est_size_gb=40.0,
        tools=[ToolRef(mcp="a.x"), ToolRef(mcp="b.y")],
    )
    wf = _workflow([step])
    pressures = compute_pressures(wf, arch=_FakeArch(48.0))
    rec = choose_action(pressures["s"], step, wf, pressures, available_models=[])
    assert rec.action == "block_with_error"


# ── apply_co_scheduling_policy ───────────────────────────────────────


def _contention_workflow(**defaults_kw) -> WorkflowDefinition:
    """Builds a workflow with one obvious contention step (40 GB on 48 GB host)."""
    step = _llm_step(
        role="coding",
        model="qwen2.5-coder:32b",
        est_size_gb=40.0,
        tools=[ToolRef(mcp="bash-mcp.run")],
    )
    return _workflow([step], **defaults_kw)


def test_policy_off_emits_nothing(monkeypatch):
    cs = apply_co_scheduling_policy(
        _contention_workflow(),
        policy="off",
        arch=_FakeArch(48.0),
    )
    assert cs.recommendations == []
    assert cs.errors == []
    assert cs.warnings == []
    # pressures map is empty too (no walk happened).
    assert cs.pressures == {}


def test_policy_recommend_emits_recommendations_no_errors():
    cs = apply_co_scheduling_policy(
        _contention_workflow(),
        policy="recommend",
        arch=_FakeArch(48.0),
        available_models=["qwen2.5-coder:7b"],
    )
    assert len(cs.recommendations) == 1
    assert cs.recommendations[0].action == "recommend_smaller_model"
    assert cs.errors == []
    assert cs.warnings == []


def test_policy_warn_strict_emits_warnings():
    cs = apply_co_scheduling_policy(
        _contention_workflow(),
        policy="warn_strict",
        arch=_FakeArch(48.0),
        available_models=["qwen2.5-coder:7b"],
    )
    assert len(cs.warnings) == 1
    assert "[strict]" in cs.warnings[0]
    assert cs.errors == []


def test_policy_reject_blocks_compile_with_errors():
    cs = apply_co_scheduling_policy(
        _contention_workflow(),
        policy="reject",
        arch=_FakeArch(48.0),
        available_models=["qwen2.5-coder:7b"],
    )
    assert cs.has_errors
    assert any("exceeds budget" in e for e in cs.errors)


def test_policy_no_contention_means_no_recommendations():
    wf = _workflow([_llm_step(est_size_gb=2.0)])
    cs = apply_co_scheduling_policy(wf, policy="recommend", arch=_FakeArch(96.0))
    assert cs.recommendations == []


# ── WorkflowDefaults schema ─────────────────────────────────────────


def test_workflow_defaults_co_scheduling_policy_defaults_recommend():
    d = WorkflowDefaults()
    assert d.co_scheduling_policy == "recommend"


def test_workflow_defaults_rejects_unknown_policy():
    with pytest.raises(ValueError):
        WorkflowDefaults(co_scheduling_policy="be_aggressive")


# ── WorkflowEngine.validate integration ─────────────────────────────


def test_engine_validate_stashes_co_scheduling_result(monkeypatch):
    """The engine runs co-scheduling under .validate() and stashes the result
    so the router can surface recommendations. No MCP tools on the step →
    extension preflight stays clean."""
    from api.services.ollama_service import OllamaService
    from api.services.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(OllamaService())

    import api.services.co_scheduler as cs_mod

    monkeypatch.setattr(cs_mod, "_arch_budget_gb", lambda arch=None: 5.0)
    monkeypatch.setattr(
        cs_mod,
        "ROLE_PATTERNS",
        {"coding": ["qwen2.5-coder:1.5b"], "general": []},
    )

    step = _llm_step(
        role="coding",
        model="qwen2.5-coder:32b",
        est_size_gb=10.0,
        archetype="bash_script",
    )
    wf = WorkflowDefinition(
        id="contention",
        name="contention",
        defaults=WorkflowDefaults(co_scheduling_policy="recommend"),
        steps=[step],
    )
    engine.validate(wf)
    result = engine._last_co_scheduling_result  # noqa: SLF001
    assert result is not None
    assert len(result.recommendations) >= 1


def test_engine_validate_reject_policy_raises(monkeypatch):
    """A reject-policy workflow with contention must fail validation."""
    from api.exceptions import WorkflowValidationError
    from api.services.ollama_service import OllamaService
    from api.services.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(OllamaService())

    import api.services.co_scheduler as cs_mod

    monkeypatch.setattr(cs_mod, "_arch_budget_gb", lambda arch=None: 5.0)

    step = _llm_step(
        role="coding",
        model="qwen2.5-coder:32b",
        est_size_gb=10.0,
    )
    wf = WorkflowDefinition(
        id="reject-me",
        name="reject-me",
        defaults=WorkflowDefaults(co_scheduling_policy="reject"),
        steps=[step],
    )
    with pytest.raises(WorkflowValidationError, match="exceeds budget"):
        engine.validate(wf)
