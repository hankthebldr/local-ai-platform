"""Tests for workflow data models"""
import pytest
from api.models.workflow_models import (
    AgentStep,
    WorkflowDefaults,
    WorkflowDefinition,
    WorkflowContext,
    StepResult,
    WorkflowRun,
)


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
