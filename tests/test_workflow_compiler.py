"""Tests for WorkflowCompiler — DAG validation, cycle detection, batch scheduling"""

import pytest
from api.models.workflow_models import (
    AgentStep,
    StepCondition,
    GateOperator,
    QualityGate,
    WorkflowDefinition,
)
from api.services.workflow_compiler import WorkflowCompiler
from api.exceptions import WorkflowValidationError


def make_step(id, inputs=None, outputs=None, depends_on=None, **kwargs):
    return AgentStep(
        id=id,
        name=id,
        system_prompt=f"Do {id}",
        inputs=inputs or [],
        outputs=outputs or ["result"],
        depends_on=depends_on or [],
        **kwargs,
    )


def make_workflow(steps, **kwargs):
    return WorkflowDefinition(id="test", name="Test", steps=steps, **kwargs)


class TestDAGConstruction:
    def test_sequential_steps(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", outputs=["x"]),
            make_step("b", inputs=["a.x"], outputs=["y"]),
            make_step("c", inputs=["b.y"], outputs=["z"]),
        ])
        plan = compiler.compile(wf)
        assert plan.total_batches == 3
        assert plan.step_order == ["a", "b", "c"]

    def test_parallel_steps(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", outputs=["x"]),
            make_step("b", outputs=["y"]),
            make_step("c", inputs=["a.x", "b.y"], outputs=["z"]),
        ])
        plan = compiler.compile(wf)
        assert plan.total_batches == 2
        # a and b should be in batch 0
        assert set(plan.batches[0].step_ids) == {"a", "b"}
        assert plan.batches[1].step_ids == ["c"]

    def test_diamond_dag(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("root", outputs=["x"]),
            make_step("left", inputs=["root.x"], outputs=["l"]),
            make_step("right", inputs=["root.x"], outputs=["r"]),
            make_step("merge", inputs=["left.l", "right.r"], outputs=["m"]),
        ])
        plan = compiler.compile(wf)
        assert plan.total_batches == 3
        assert set(plan.batches[1].step_ids) == {"left", "right"}

    def test_explicit_depends_on(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", outputs=["x"]),
            make_step("b", depends_on=["a"]),
        ])
        plan = compiler.compile(wf)
        assert plan.total_batches == 2
        assert plan.step_order == ["a", "b"]


class TestCycleDetection:
    def test_self_dependency(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", depends_on=["a"]),
        ])
        with pytest.raises(WorkflowValidationError, match="depends on itself"):
            compiler.compile(wf)

    def test_circular_dependency(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", inputs=["b.x"], outputs=["y"]),
            make_step("b", inputs=["a.y"], outputs=["x"]),
        ])
        with pytest.raises(WorkflowValidationError, match="cycle"):
            compiler.compile(wf)


class TestValidation:
    def test_duplicate_step_ids(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a"),
            make_step("a"),
        ])
        with pytest.raises(WorkflowValidationError, match="Duplicate"):
            compiler.compile(wf)

    def test_unknown_dependency(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", depends_on=["nonexistent"]),
        ])
        with pytest.raises(WorkflowValidationError, match="unknown step"):
            compiler.compile(wf)

    def test_unknown_input_ref(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", inputs=["nonexistent.x"]),
        ])
        with pytest.raises(WorkflowValidationError, match="unknown step"):
            compiler.compile(wf)

    def test_seed_key_validation(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", inputs=["seed.missing"]),
        ])
        with pytest.raises(WorkflowValidationError, match="seed key not provided"):
            compiler.compile(wf, seed_keys=["present"])

    def test_seed_key_valid(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", inputs=["seed.topic"]),
        ])
        plan = compiler.compile(wf, seed_keys=["topic"])
        assert plan.total_steps == 1


class TestParallelismAnalysis:
    def test_fully_parallel(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a"),
            make_step("b"),
            make_step("c"),
        ])
        plan = compiler.compile(wf)
        analysis = compiler.analyze_parallelism(plan)
        assert analysis["total_batches"] == 1
        assert analysis["max_parallel_width"] == 3
        assert analysis["speedup_factor"] == 3.0

    def test_fully_sequential(self):
        compiler = WorkflowCompiler()
        wf = make_workflow([
            make_step("a", outputs=["x"]),
            make_step("b", inputs=["a.x"], outputs=["y"]),
            make_step("c", inputs=["b.y"]),
        ])
        plan = compiler.compile(wf)
        analysis = compiler.analyze_parallelism(plan)
        assert analysis["total_batches"] == 3
        assert analysis["sequential_fraction"] == 1.0
        assert analysis["speedup_factor"] == 1.0
