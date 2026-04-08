"""Tests for WorkflowEngine — load, validate, execute workflows"""
import pytest
import yaml
import tempfile
import os
from unittest.mock import MagicMock, patch
from pathlib import Path

from api.services.workflow_engine import WorkflowEngine
from api.models.workflow_models import WorkflowContext
from api.exceptions import WorkflowValidationError, WorkflowExecutionError


VALID_WORKFLOW_YAML = """
id: test-workflow
name: Test Workflow
version: "1.0"
defaults:
  role: general
  retries: 1
  retry_delay: 0
steps:
  - id: step1
    name: Step One
    role: fast
    system_prompt: "Analyze the input."
    inputs:
      - seed.task
    outputs:
      - analysis
  - id: step2
    name: Step Two
    role: coding
    system_prompt: "Generate code from analysis."
    inputs:
      - seed.task
      - step1.analysis
    outputs:
      - code
"""

INVALID_IO_WORKFLOW_YAML = """
id: broken-workflow
name: Broken
steps:
  - id: step1
    name: Step One
    role: fast
    system_prompt: "Do something."
    inputs:
      - step_nonexistent.data
    outputs:
      - result
"""


class TestWorkflowEngineLoad:
    def setup_method(self):
        self.ollama = MagicMock()
        self.engine = WorkflowEngine(self.ollama)

    def test_load_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
            assert defn.id == "test-workflow"
            assert len(defn.steps) == 2
        os.unlink(f.name)

    def test_load_invalid_file_raises(self):
        with pytest.raises(FileNotFoundError):
            self.engine.load("/nonexistent/path.yaml")

    def test_validate_valid_workflow(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
            # Should not raise
            self.engine.validate(defn, seed_keys=["task"])
        os.unlink(f.name)

    def test_validate_broken_io_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(INVALID_IO_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
            with pytest.raises(WorkflowValidationError, match="step_nonexistent"):
                self.engine.validate(defn, seed_keys=[])
        os.unlink(f.name)


class TestWorkflowEngineExecute:
    def setup_method(self):
        self.ollama = MagicMock()
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000}
        ]
        self.ollama.chat.return_value = {
            "content": "Mock output",
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        self.engine = WorkflowEngine(self.ollama)

    def test_run_completes_all_steps(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
        os.unlink(f.name)

        run = self.engine.run(defn, seed={"task": "test task"})

        assert run.status == "completed"
        assert len(run.step_results) == 2
        assert all(r.status == "completed" for r in run.step_results)
        assert run.context.get_workspace("step1", "analysis") is not None
        assert run.context.get_workspace("step2", "code") is not None

    def test_run_stops_on_step_failure(self):
        self.ollama.chat.side_effect = Exception("LLM down")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(VALID_WORKFLOW_YAML)
            f.flush()
            defn = self.engine.load(f.name)
        os.unlink(f.name)

        run = self.engine.run(defn, seed={"task": "test"})

        assert run.status == "failed"
        assert run.step_results[0].status == "failed"
        # Step 2 should not have executed
        assert len([r for r in run.step_results if r.status == "completed"]) == 0
