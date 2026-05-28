"""Unit tests for the workflow router's step-kind decoration helpers.

The Runs view UI needs each step_result to carry its `kind` so it can render
a per-kind chip. We avoid touching all 14 StepResult creation sites by
decorating at the API boundary instead — these tests cover that helper.
"""

from __future__ import annotations


from api.routers.workflows import (
    _collect_step_kinds,
    _decorate_step_results,
)
from api.models.workflow_models import (
    AgentStep,
    ConsolidateSpec,
    LoopTermination,
    OrchestratorBudget,
    ParallelExecutionConfig,
    RalphHalt,
    RalphSpec,
    StepPrompt,
    WorkflowDefinition,
)


def _llm(id_, **kw):
    base = dict(
        name=id_,
        role="fast",
        system_prompt="do thing",
        outputs=["data"],
    )
    base.update(kw)
    return AgentStep(id=id_, **base)


def _planner():
    return StepPrompt(role_inline="You are the lead.", task="investigate")


class TestCollectStepKinds:
    def test_top_level_llm(self):
        wf = WorkflowDefinition(id="t", name="T", steps=[_llm("s1")])
        assert _collect_step_kinds(wf) == {"s1": "llm"}

    def test_parallel_branches_and_gather(self):
        parent = AgentStep(
            id="par",
            name="P",
            kind="parallel",
            outputs=["summary"],
            execution=ParallelExecutionConfig(mode="multi_model_concurrent"),
            branches=[_llm("a"), _llm("b")],
            gather=_llm("g", outputs=["summary"]),
        )
        wf = WorkflowDefinition(id="t", name="T", steps=[parent])
        kinds = _collect_step_kinds(wf)
        assert kinds == {
            "par": "parallel",
            "a": "llm",
            "b": "llm",
            "g": "llm",
        }

    def test_loop_body(self):
        loop = AgentStep(
            id="lp",
            name="L",
            kind="loop",
            outputs=["final"],
            until=LoopTermination(gate="x.done == True"),
            body=[_llm("draft"), _llm("critic", outputs=["final"])],
        )
        wf = WorkflowDefinition(id="t", name="T", steps=[loop])
        assert _collect_step_kinds(wf) == {
            "lp": "loop",
            "draft": "llm",
            "critic": "llm",
        }

    def test_orchestrator_workers(self):
        step = AgentStep(
            id="orch",
            name="O",
            kind="orchestrator",
            outputs=["findings"],
            planner=_planner(),
            workers={
                "extractor": _llm("w_ext", inputs=["seed.x"]),
                "classifier": _llm("w_cls", inputs=["seed.x"]),
            },
            budget=OrchestratorBudget(max_workers_spawned=2),
        )
        wf = WorkflowDefinition(id="t", name="T", steps=[step])
        kinds = _collect_step_kinds(wf)
        assert kinds["orch"] == "orchestrator"
        assert kinds["w_ext"] == "llm"
        assert kinds["w_cls"] == "llm"

    def test_consolidate_and_ralph_walked(self):
        cons = AgentStep(
            id="con",
            name="C",
            kind="consolidate",
            outputs=["lesson"],
            consolidate=ConsolidateSpec(
                target="playbook",
                target_name="inc",
                system_prompt="distill",
            ),
        )
        ralph = AgentStep(
            id="rl",
            name="R",
            kind="ralph",
            outputs=["data"],
            ralph=RalphSpec(journal_path="/tmp/j", halt=RalphHalt(max_iterations=2)),
            body=[_llm("plan"), cons],
        )
        wf = WorkflowDefinition(id="t", name="T", steps=[ralph])
        kinds = _collect_step_kinds(wf)
        assert kinds["rl"] == "ralph"
        assert kinds["plan"] == "llm"
        assert kinds["con"] == "consolidate"


class TestDecorateStepResults:
    def test_kind_added_from_map(self):
        results = [
            {"step_id": "par", "status": "completed"},
            {"step_id": "a", "status": "completed"},
        ]
        kinds = {"par": "parallel", "a": "llm"}
        out = _decorate_step_results(results, kinds)
        assert out == [
            {"step_id": "par", "status": "completed", "kind": "parallel"},
            {"step_id": "a", "status": "completed", "kind": "llm"},
        ]

    def test_unknown_step_id_defaults_to_llm(self):
        """Composite children with synthetic ids (orchestrator workers,
        sharded clones) won't be in the YAML — they should default to 'llm'
        so the UI can render a uniform chip."""
        results = [{"step_id": "orch__extractor_0", "status": "completed"}]
        out = _decorate_step_results(results, {})
        assert out == [
            {
                "step_id": "orch__extractor_0",
                "status": "completed",
                "kind": "llm",
            }
        ]

    def test_preserves_existing_kind(self):
        """If a result already carries a kind (e.g. from an upgraded engine
        that populated it directly), don't overwrite."""
        results = [{"step_id": "x", "status": "completed", "kind": "orchestrator"}]
        out = _decorate_step_results(results, {"x": "llm"})  # map says otherwise
        assert out[0]["kind"] == "orchestrator"

    def test_does_not_mutate_input(self):
        results = [{"step_id": "x", "status": "completed"}]
        original = list(results)
        _decorate_step_results(results, {"x": "loop"})
        # original list of dicts unchanged
        assert results == original
        assert "kind" not in original[0]
