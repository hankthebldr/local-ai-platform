"""Tests for workflow data models — enhanced with DAG, conditions, loops, gates"""

import pytest
from api.models.workflow_models import (
    AgentStep,
    ExecutionBatch,
    ExecutionPlan,
    GateOperator,
    LoopConfig,
    OutputFormat,
    OutputParserConfig,
    QualityGate,
    RunStatus,
    StepCondition,
    StepConfig,
    StepResult,
    StepStatus,
    WorkflowContext,
    WorkflowDefaults,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowHook,
    WorkflowMetadata,
    WorkflowRun,
)


class TestStepConfig:
    def test_defaults(self):
        config = StepConfig()
        assert config.temperature is None
        assert config.max_tokens is None
        assert config.seed is None

    def test_full_config(self):
        config = StepConfig(temperature=0.5, max_tokens=4096, retries=3, timeout=120, seed=42)
        assert config.temperature == 0.5
        assert config.seed == 42


class TestOutputParserConfig:
    def test_defaults(self):
        parser = OutputParserConfig()
        assert parser.format == OutputFormat.RAW
        assert parser.strict is False

    def test_json_parser(self):
        parser = OutputParserConfig(format=OutputFormat.JSON, strict=True)
        assert parser.format == OutputFormat.JSON


class TestQualityGate:
    def test_gate(self):
        gate = QualityGate(name="has_data", field="entities", operator=GateOperator.NOT_EMPTY)
        assert gate.name == "has_data"
        assert gate.severity == "error"

    def test_warning_gate(self):
        gate = QualityGate(name="check", field="x", operator=GateOperator.GT, value=5, severity="warning")
        assert gate.severity == "warning"


class TestStepCondition:
    def test_basic(self):
        cond = StepCondition(ref="step_a.status", operator=GateOperator.EQUALS, value="completed")
        assert cond.logic == "all"


class TestLoopConfig:
    def test_loop(self):
        loop = LoopConfig(over="seed.files", as_var="file", collect_as="results")
        assert loop.max_parallel == 1


class TestAgentStep:
    def test_minimal(self):
        step = AgentStep(id="s1", name="Step 1", system_prompt="Do work", outputs=["result"])
        assert step.depends_on == []
        assert step.output_parser.format == OutputFormat.RAW

    def test_full_step(self):
        step = AgentStep(
            id="analyze",
            name="Analyze",
            role="reasoning",
            system_prompt="Analyze {{seed.input}}",
            user_prompt="Focus on {{seed.target}}",
            inputs=["seed.input"],
            outputs=["entities", "relationships"],
            depends_on=["prior"],
            output_parser=OutputParserConfig(format=OutputFormat.JSON),
            quality_gates=[QualityGate(name="check", field="entities", operator=GateOperator.NOT_EMPTY)],
            condition=StepCondition(ref="seed.enabled", operator=GateOperator.EQUALS, value=True),
            tags=["analysis"],
            cache_key="v1",
        )
        assert len(step.quality_gates) == 1
        assert step.cache_key == "v1"

    def test_empty_system_prompt_fails(self):
        with pytest.raises(ValueError):
            AgentStep(id="s1", name="S", system_prompt="   ", outputs=["r"])


class TestWorkflowDefinition:
    def test_minimal(self):
        defn = WorkflowDefinition(
            id="test", name="Test",
            steps=[AgentStep(id="s1", name="S1", system_prompt="Do it", outputs=["r"])],
        )
        assert defn.max_parallel == 4

    def test_with_metadata(self):
        defn = WorkflowDefinition(
            id="test", name="Test",
            steps=[AgentStep(id="s1", name="S1", system_prompt="Do", outputs=["r"])],
            metadata=WorkflowMetadata(author="test", category="security", tags=["xsiam"]),
        )
        assert defn.metadata.category == "security"

    def test_empty_steps_fails(self):
        with pytest.raises(ValueError):
            WorkflowDefinition(id="test", name="Test", steps=[])


class TestWorkflowContext:
    def test_three_layers(self):
        ctx = WorkflowContext(seed={"key": "value"})
        assert ctx.get_seed("key") == "value"
        ctx.set_workspace("s1", "out", "data")
        assert ctx.get_workspace("s1", "out") == "data"
        ctx.set_shared("flag", True)
        assert ctx.get_shared("flag") is True

    def test_resolve_input(self):
        ctx = WorkflowContext(seed={"topic": "sec"}, workspace={"s1": {"result": "found"}}, shared={"mode": "fast"})
        assert ctx.resolve_input("seed.topic") == "sec"
        assert ctx.resolve_input("s1.result") == "found"
        assert ctx.resolve_input("shared.mode") == "fast"

    def test_dot_walk_nested(self):
        ctx = WorkflowContext(workspace={"s1": {"data": {"nested": {"deep": "val"}}}})
        assert ctx.resolve_input("s1.data.nested.deep") == "val"

    def test_snapshot_restore(self):
        ctx = WorkflowContext(seed={"x": 1})
        ctx.set_workspace("s1", "out", "original")
        ctx.snapshot("cp1")
        ctx.set_workspace("s1", "out", "modified")
        assert ctx.get_workspace("s1", "out") == "modified"
        ctx.restore("cp1")
        assert ctx.get_workspace("s1", "out") == "original"

    def test_to_template_vars(self):
        ctx = WorkflowContext(seed={"a": 1}, workspace={"s1": {"b": 2}}, shared={"c": 3})
        v = ctx.to_template_vars()
        assert v["seed"]["a"] == 1
        assert v["s1"]["b"] == 2
        assert v["shared"]["c"] == 3

    def test_get_step_outputs(self):
        ctx = WorkflowContext()
        ctx.set_workspace("s1", "a", 1)
        ctx.set_workspace("s1", "b", 2)
        assert ctx.get_step_outputs("s1") == {"a": 1, "b": 2}


class TestStepResult:
    def test_defaults(self):
        r = StepResult(step_id="s1")
        assert r.status == StepStatus.PENDING
        assert r.cached is False

    def test_full(self):
        r = StepResult(step_id="s1", status=StepStatus.COMPLETED, cached=True, raw_output="text", parsed_output={"k": "v"})
        assert r.cached is True


class TestExecutionPlan:
    def test_plan(self):
        plan = ExecutionPlan(
            workflow_id="test", total_steps=3, total_batches=2,
            batches=[
                ExecutionBatch(batch_index=0, step_ids=["a", "b"]),
                ExecutionBatch(batch_index=1, step_ids=["c"], depends_on_batches=[0]),
            ],
            step_order=["a", "b", "c"], parallelism=2,
        )
        assert plan.batches[0].step_ids == ["a", "b"]


class TestWorkflowRun:
    def test_defaults(self):
        run = WorkflowRun(workflow_id="test", context=WorkflowContext())
        assert run.status == RunStatus.PENDING
        assert run.total_tokens == 0
        assert run.checkpoints == []


class TestWorkflowEvent:
    def test_event(self):
        e = WorkflowEvent(event_type="step.completed", run_id="abc", step_id="s1")
        assert e.data == {}


class TestEnums:
    def test_step_status(self):
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.CANCELLED.value == "cancelled"

    def test_output_formats(self):
        assert OutputFormat.JSON.value == "json"
        assert OutputFormat.REGEX.value == "regex"
        assert OutputFormat.CSV.value == "csv"

    def test_gate_operators(self):
        assert GateOperator.HAS_KEY.value == "has_key"
        assert GateOperator.ALL_KEYS.value == "all_keys"
