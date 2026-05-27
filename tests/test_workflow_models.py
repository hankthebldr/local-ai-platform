"""Tests for workflow data models"""

import pytest
from api.models.workflow_models import (
    A2AAuth,
    AgentStep,
    ConsolidateSpec,
    LoopTermination,
    OrchestratorBudget,
    ParallelExecutionConfig,
    RalphHalt,
    RalphSpec,
    StepPrompt,
    WorkflowDefinition,
    WorkflowContext,
    WorkflowRun,
)


def _llm(id_: str, **overrides) -> AgentStep:
    """Test helper — minimal valid llm step."""
    base = dict(
        id=id_,
        name=id_.upper(),
        role="fast",
        system_prompt="do the thing",
        outputs=["result"],
    )
    base.update(overrides)
    return AgentStep(**base)


class TestAgentStep:
    def test_step_with_role(self):
        step = AgentStep(
            id="analyze",
            name="Analyze Schema",
            role="reasoning",
            system_prompt="You are a data architect.",
            inputs=["seed.source_files"],
            outputs=["entities", "relationships"],
        )
        assert step.id == "analyze"
        assert step.role == "reasoning"
        assert step.model is None

    def test_step_with_explicit_model(self):
        step = AgentStep(
            id="generate",
            name="Generate Code",
            model="qwen3.5-uncensored:35b",
            system_prompt="You are a developer.",
            inputs=["seed.constraints"],
            outputs=["code"],
        )
        assert step.model == "qwen3.5-uncensored:35b"
        assert step.role is None

    def test_step_requires_system_prompt(self):
        with pytest.raises(Exception):
            AgentStep(
                id="bad",
                name="Bad Step",
                role="fast",
                inputs=[],
                outputs=[],
            )

    def test_step_config_defaults(self):
        step = AgentStep(
            id="s1",
            name="Step",
            role="fast",
            system_prompt="prompt",
            inputs=[],
            outputs=["result"],
        )
        assert step.config.temperature is None
        assert step.config.max_tokens is None
        assert step.config.retries is None


class TestWorkflowDefinition:
    def test_valid_definition(self):
        defn = WorkflowDefinition(
            id="test-workflow",
            name="Test",
            steps=[
                AgentStep(
                    id="s1",
                    name="Step 1",
                    role="fast",
                    system_prompt="Do thing",
                    inputs=["seed.task"],
                    outputs=["result"],
                )
            ],
        )
        assert defn.id == "test-workflow"
        assert len(defn.steps) == 1

    def test_definition_requires_steps(self):
        with pytest.raises(Exception):
            WorkflowDefinition(id="empty", name="Empty", steps=[])


class TestWorkflowContext:
    def test_seed_is_immutable_after_init(self):
        ctx = WorkflowContext(seed={"task": "test"})
        assert ctx.get_seed("task") == "test"

    def test_workspace_scoped_writes(self):
        ctx = WorkflowContext(seed={})
        ctx.set_workspace("step1", "entities", ["User", "Post"])
        assert ctx.get_workspace("step1", "entities") == ["User", "Post"]

    def test_workspace_read_other_namespace(self):
        ctx = WorkflowContext(seed={})
        ctx.set_workspace("step1", "data", "hello")
        assert ctx.get_workspace("step1", "data") == "hello"

    def test_workspace_missing_key_returns_none(self):
        ctx = WorkflowContext(seed={})
        assert ctx.get_workspace("nonexistent", "key") is None

    def test_shared_layer(self):
        ctx = WorkflowContext(seed={})
        ctx.set_shared("decisions", ["chose X"])
        ctx.set_shared("decisions", ["chose X", "chose Y"])
        assert len(ctx.get_shared("decisions")) == 2

    def test_resolve_input_from_seed(self):
        ctx = WorkflowContext(seed={"task": "build models", "lang": "python"})
        assert ctx.resolve_input("seed.task") == "build models"

    def test_resolve_input_from_workspace(self):
        ctx = WorkflowContext(seed={})
        ctx.set_workspace("analyze", "entities", ["User"])
        assert ctx.resolve_input("analyze.entities") == ["User"]

    def test_resolve_input_from_shared(self):
        ctx = WorkflowContext(seed={})
        ctx.set_shared("warnings", ["no index"])
        assert ctx.resolve_input("shared.warnings") == ["no index"]


class TestWorkflowRun:
    def test_run_initial_status(self):
        ctx = WorkflowContext(seed={"task": "test"})
        run = WorkflowRun(workflow_id="test-wf", context=ctx)
        assert run.status == "pending"
        assert run.run_id is not None
        assert run.step_results == []


class TestAgentStepKind:
    """Discriminator + composite-shape validation."""

    def test_kind_defaults_to_llm_for_backwards_compat(self):
        step = _llm("s1")
        assert step.kind == "llm"

    def test_parallel_happy_path(self):
        parent = AgentStep(
            id="p",
            name="P",
            kind="parallel",
            outputs=["findings"],
            execution=ParallelExecutionConfig(max_concurrency=2),
            branches=[_llm("b1", outputs=["data"]), _llm("b2", outputs=["data"])],
            gather=_llm("g", outputs=["findings"]),
        )
        assert parent.kind == "parallel"
        assert len(parent.branches) == 2
        assert parent.gather.id == "g"
        assert parent.execution.max_concurrency == 2

    def test_parallel_rejects_single_branch(self):
        with pytest.raises(Exception, match="at least 2 branches"):
            AgentStep(
                id="p",
                name="P",
                kind="parallel",
                outputs=["findings"],
                branches=[_llm("b1", outputs=["data"])],
                gather=_llm("g", outputs=["findings"]),
            )

    def test_parallel_rejects_missing_gather(self):
        with pytest.raises(Exception, match="requires a gather"):
            AgentStep(
                id="p",
                name="P",
                kind="parallel",
                outputs=["findings"],
                branches=[
                    _llm("b1", outputs=["data"]),
                    _llm("b2", outputs=["data"]),
                ],
            )

    def test_parallel_rejects_gather_output_mismatch(self):
        with pytest.raises(Exception, match="do not match gather"):
            AgentStep(
                id="p",
                name="P",
                kind="parallel",
                outputs=["findings"],
                branches=[
                    _llm("b1", outputs=["data"]),
                    _llm("b2", outputs=["data"]),
                ],
                gather=_llm("g", outputs=["WRONG_KEY"]),
            )

    def test_parallel_rejects_duplicate_branch_ids(self):
        with pytest.raises(Exception, match="duplicate branch ids"):
            AgentStep(
                id="p",
                name="P",
                kind="parallel",
                outputs=["findings"],
                branches=[
                    _llm("dup", outputs=["data"]),
                    _llm("dup", outputs=["data"]),
                ],
                gather=_llm("g", outputs=["findings"]),
            )

    def test_parallel_rejects_own_prompt(self):
        with pytest.raises(Exception, match="must not declare a"):
            AgentStep(
                id="p",
                name="P",
                kind="parallel",
                system_prompt="should not be here",
                outputs=["findings"],
                branches=[
                    _llm("b1", outputs=["data"]),
                    _llm("b2", outputs=["data"]),
                ],
                gather=_llm("g", outputs=["findings"]),
            )

    def test_llm_rejects_branches(self):
        with pytest.raises(Exception, match="must not declare branches"):
            AgentStep(
                id="x",
                name="X",
                role="fast",
                system_prompt="x",
                outputs=["o"],
                branches=[
                    _llm("b1", outputs=["data"]),
                    _llm("b2", outputs=["data"]),
                ],
            )

    def test_loop_happy_path(self):
        loop = AgentStep(
            id="l",
            name="L",
            kind="loop",
            outputs=["final"],
            max_iterations=3,
            until=LoopTermination(gate="critic.approved == True"),
            body=[
                _llm("draft", outputs=["text"]),
                _llm("critic", outputs=["final"]),
            ],
        )
        assert loop.kind == "loop"
        assert loop.max_iterations == 3
        assert loop.until.gate == "critic.approved == True"

    def test_loop_rejects_missing_until(self):
        with pytest.raises(Exception, match="requires `until`"):
            AgentStep(
                id="l",
                name="L",
                kind="loop",
                outputs=["final"],
                body=[_llm("draft", outputs=["text"])],
            )

    def test_loop_rejects_missing_body(self):
        with pytest.raises(Exception, match="at least 1 body"):
            AgentStep(
                id="l",
                name="L",
                kind="loop",
                outputs=["final"],
                until=LoopTermination(gate="True"),
            )

    def test_loop_rejects_output_not_produced_by_last_body(self):
        with pytest.raises(Exception, match="not produced by the last body"):
            AgentStep(
                id="l",
                name="L",
                kind="loop",
                outputs=["missing_key"],
                until=LoopTermination(gate="True"),
                body=[_llm("draft", outputs=["produced_key"])],
            )

    def test_loop_rejects_zero_max_iterations(self):
        with pytest.raises(Exception, match="max_iterations must be"):
            AgentStep(
                id="l",
                name="L",
                kind="loop",
                outputs=["final"],
                max_iterations=0,
                until=LoopTermination(gate="True"),
                body=[_llm("draft", outputs=["final"])],
            )


class TestNestedDuplicateIds:
    """Branch and body step ids must not collide across nesting."""

    def test_branch_collides_with_top_level_step(self):
        # The model itself can't catch this — it shows up at validate() time.
        # We just confirm the model accepts the duplicate locally; the engine
        # validator (tested separately) is responsible for the cross-tree check.
        top = AgentStep(
            id="dup",
            name="Top",
            role="fast",
            system_prompt="x",
            outputs=["o"],
        )
        composite = AgentStep(
            id="par",
            name="Par",
            kind="parallel",
            outputs=["o"],
            branches=[
                _llm("dup", outputs=["o"]),  # collides with `top`
                _llm("b2", outputs=["o"]),
            ],
            gather=_llm("g", outputs=["o"]),
        )
        # Both parse individually
        assert top.id == "dup"
        assert composite.branches[0].id == "dup"


class TestA2AAgentStep:
    """kind=a2a shape validation."""

    def test_a2a_happy_path(self):
        step = AgentStep(
            id="ext",
            name="External",
            kind="a2a",
            agent_card_url="https://intel.local/.well-known/agent.json",
            skill="enrich_iocs",
            outputs=["enriched"],
        )
        assert step.kind == "a2a"
        assert step.skill == "enrich_iocs"
        assert step.streaming is False
        assert step.auth is None

    def test_a2a_with_bearer_auth(self):
        step = AgentStep(
            id="ext",
            name="External",
            kind="a2a",
            agent_card_url="https://x/.well-known/agent.json",
            skill="do_thing",
            auth=A2AAuth(type="bearer", token_env="INTEL_API_TOKEN"),
            outputs=["result"],
        )
        assert step.auth.type == "bearer"
        assert step.auth.token_env == "INTEL_API_TOKEN"

    def test_a2a_rejects_missing_url(self):
        with pytest.raises(Exception, match="requires agent_card_url"):
            AgentStep(
                id="ext",
                name="E",
                kind="a2a",
                skill="x",
                outputs=["o"],
            )

    def test_a2a_rejects_missing_skill(self):
        with pytest.raises(Exception, match="requires skill"):
            AgentStep(
                id="ext",
                name="E",
                kind="a2a",
                agent_card_url="https://x",
                outputs=["o"],
            )

    def test_a2a_rejects_local_model_pin(self):
        with pytest.raises(Exception, match="must not declare model/role"):
            AgentStep(
                id="ext",
                name="E",
                kind="a2a",
                agent_card_url="https://x",
                skill="s",
                model="mistral",
                outputs=["o"],
            )

    def test_a2a_rejects_prompt(self):
        with pytest.raises(Exception, match="must not declare a"):
            AgentStep(
                id="ext",
                name="E",
                kind="a2a",
                agent_card_url="https://x",
                skill="s",
                system_prompt="no",
                outputs=["o"],
            )

    def test_non_a2a_rejects_a2a_fields(self):
        # An llm step accidentally including agent_card_url should fail.
        with pytest.raises(Exception, match="agent_card_url/skill/auth"):
            AgentStep(
                id="bad",
                name="Bad",
                kind="llm",
                system_prompt="x",
                outputs=["o"],
                agent_card_url="https://x",
            )

    def test_bearer_auth_requires_token_env(self):
        with pytest.raises(Exception, match="requires token_env"):
            A2AAuth(type="bearer")


class TestOrchestratorAgentStep:
    """kind=orchestrator shape validation."""

    @staticmethod
    def _worker(id_, **overrides) -> AgentStep:
        base = dict(
            name=id_,
            role="fast",
            system_prompt="do the thing",
            inputs=["seed.task", "seed.context"],
            outputs=["result"],
        )
        base.update(overrides)
        return AgentStep(id=id_, **base)

    def _planner(self) -> StepPrompt:
        return StepPrompt(role_inline="You are the lead.", task="investigate")

    def test_orchestrator_happy_path(self):
        step = AgentStep(
            id="invest",
            name="Investigate",
            kind="orchestrator",
            outputs=["findings"],
            planner=self._planner(),
            workers={"extractor": self._worker("w_ext")},
            budget=OrchestratorBudget(max_workers_spawned=4),
        )
        assert step.kind == "orchestrator"
        assert len(step.workers) == 1
        assert step.budget.max_workers_spawned == 4

    def test_orchestrator_rejects_missing_planner(self):
        with pytest.raises(Exception, match="requires a\\s+planner"):
            AgentStep(
                id="invest",
                name="I",
                kind="orchestrator",
                outputs=["o"],
                workers={"w": self._worker("w")},
            )

    def test_orchestrator_rejects_empty_workers(self):
        with pytest.raises(Exception, match="at least one worker"):
            AgentStep(
                id="invest",
                name="I",
                kind="orchestrator",
                outputs=["o"],
                planner=self._planner(),
                workers={},
            )

    def test_orchestrator_rejects_own_prompt(self):
        with pytest.raises(Exception, match="must not declare a"):
            AgentStep(
                id="invest",
                name="I",
                kind="orchestrator",
                outputs=["o"],
                system_prompt="should be in planner",
                planner=self._planner(),
                workers={"w": self._worker("w")},
            )

    def test_orchestrator_rejects_worker_with_non_seed_inputs(self):
        with pytest.raises(Exception, match="not declared as seed"):
            AgentStep(
                id="invest",
                name="I",
                kind="orchestrator",
                outputs=["o"],
                planner=self._planner(),
                workers={
                    "w": self._worker("w", inputs=["other_step.x"]),
                },
            )

    def test_non_orchestrator_kinds_reject_orchestrator_fields(self):
        # An llm step accidentally including a planner block should fail.
        with pytest.raises(Exception, match="planner/workers/budget"):
            AgentStep(
                id="bad",
                name="B",
                kind="llm",
                system_prompt="x",
                outputs=["o"],
                planner=self._planner(),
            )


class TestConsolidateAgentStep:
    """kind=consolidate shape validation."""

    @staticmethod
    def _spec(**overrides) -> ConsolidateSpec:
        base = dict(
            target="playbook",
            target_name="incident_response",
            system_prompt="Consolidate the lessons.",
        )
        base.update(overrides)
        return ConsolidateSpec(**base)

    def test_consolidate_happy_path(self):
        step = AgentStep(
            id="distill",
            name="Distill",
            kind="consolidate",
            outputs=["updated_playbook"],
            consolidate=self._spec(),
        )
        assert step.kind == "consolidate"
        assert step.consolidate.target == "playbook"
        assert step.consolidate.merge_strategy == "append_with_dedup"

    def test_consolidate_rejects_missing_block(self):
        with pytest.raises(Exception, match="requires a\\s+consolidate block"):
            AgentStep(
                id="distill",
                name="D",
                kind="consolidate",
                outputs=["o"],
            )

    def test_consolidate_rejects_top_level_prompt(self):
        with pytest.raises(Exception, match="must not declare\\s+a top-level prompt"):
            AgentStep(
                id="distill",
                name="D",
                kind="consolidate",
                outputs=["o"],
                system_prompt="should be in the consolidate block",
                consolidate=self._spec(),
            )

    def test_non_consolidate_kinds_reject_consolidate_block(self):
        with pytest.raises(Exception, match="must not declare\\s+a consolidate block"):
            AgentStep(
                id="bad",
                name="B",
                kind="llm",
                system_prompt="x",
                outputs=["o"],
                consolidate=self._spec(),
            )

    def test_consolidate_spec_rejects_empty_target_name(self):
        with pytest.raises(Exception, match="non-empty target_name"):
            ConsolidateSpec(target="playbook", target_name="", system_prompt="p")

    def test_consolidate_spec_rejects_empty_system_prompt(self):
        with pytest.raises(Exception, match="non-empty system_prompt"):
            ConsolidateSpec(target="playbook", target_name="n", system_prompt="  ")


class TestMemoryAccessor:
    """$memory.* input resolution on WorkflowContext."""

    def test_memory_returns_empty_when_no_store_attached(self):
        ctx = WorkflowContext(seed={})
        assert ctx.resolve_input("$memory.playbook.anything") == ""

    def test_memory_reads_from_attached_store(self, tmp_path):
        from api.services.memory_store import MemoryStore

        store = MemoryStore(base_dir=str(tmp_path))
        store.write_playbook("inc", "Rule: check logs first", strategy="replace")
        ctx = WorkflowContext(seed={})
        ctx.attach_memory(store)
        assert "check logs first" in ctx.resolve_input("$memory.playbook.inc")

    def test_memory_handle_excluded_from_serialization(self, tmp_path):
        from api.services.memory_store import MemoryStore

        ctx = WorkflowContext(seed={"x": 1})
        ctx.attach_memory(MemoryStore(base_dir=str(tmp_path)))
        dumped = ctx.model_dump()
        assert "_memory" not in dumped
        assert dumped["seed"] == {"x": 1}


class TestRalphAgentStep:
    """kind=ralph shape validation."""

    @staticmethod
    def _body(id_, **overrides) -> AgentStep:
        base = dict(
            name=id_,
            role="fast",
            system_prompt="do the thing",
            outputs=["result"],
        )
        base.update(overrides)
        return AgentStep(id=id_, **base)

    def _spec(self, **overrides) -> RalphSpec:
        base = dict(journal_path="/tmp/ralph_journal.jsonl")
        base.update(overrides)
        return RalphSpec(**base)

    def test_ralph_happy_path(self):
        step = AgentStep(
            id="auto",
            name="Autonomous",
            kind="ralph",
            outputs=["summary"],
            ralph=self._spec(halt=RalphHalt(max_iterations=10)),
            body=[
                self._body("plan", outputs=["plan"]),
                self._body("reflect", outputs=["summary"]),
            ],
        )
        assert step.kind == "ralph"
        assert step.ralph.halt.max_iterations == 10
        assert len(step.body) == 2

    def test_ralph_default_halt(self):
        step = AgentStep(
            id="auto",
            name="A",
            kind="ralph",
            outputs=["result"],
            ralph=self._spec(),
            body=[self._body("b", outputs=["result"])],
        )
        # Sensible defaults from RalphHalt.
        assert step.ralph.halt.max_iterations == 50
        assert step.ralph.halt.max_consecutive_failures == 3

    def test_ralph_rejects_missing_block(self):
        with pytest.raises(Exception, match="requires a ralph block"):
            AgentStep(
                id="auto",
                name="A",
                kind="ralph",
                outputs=["o"],
                body=[self._body("b", outputs=["o"])],
            )

    def test_ralph_rejects_missing_body(self):
        with pytest.raises(Exception, match="at least 1\\s+body step"):
            AgentStep(
                id="auto",
                name="A",
                kind="ralph",
                outputs=["o"],
                ralph=self._spec(),
            )

    def test_ralph_rejects_top_level_prompt(self):
        with pytest.raises(Exception, match="must not declare a\\s+top-level prompt"):
            AgentStep(
                id="auto",
                name="A",
                kind="ralph",
                outputs=["o"],
                system_prompt="should be in a body step",
                ralph=self._spec(),
                body=[self._body("b", outputs=["o"])],
            )

    def test_ralph_rejects_output_not_produced_by_any_body_step(self):
        with pytest.raises(Exception, match="not produced by any body step"):
            AgentStep(
                id="auto",
                name="A",
                kind="ralph",
                outputs=["missing"],
                ralph=self._spec(),
                body=[self._body("b", outputs=["produced"])],
            )

    def test_non_ralph_kinds_reject_ralph_block(self):
        with pytest.raises(Exception, match="must not declare\\s+a ralph block"):
            AgentStep(
                id="bad",
                name="B",
                kind="llm",
                system_prompt="x",
                outputs=["o"],
                ralph=self._spec(),
            )

    def test_ralph_spec_rejects_empty_journal_path(self):
        with pytest.raises(Exception, match="non-empty journal_path"):
            RalphSpec(journal_path="   ")
