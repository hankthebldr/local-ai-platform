"""
Integration test — full workflow execution with mocked Ollama

Tests the complete pipeline: YAML load → validate → execute → persist
"""
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from api.services.workflow_engine import WorkflowEngine


WORKFLOW_YAML = """
id: integration-test
name: Integration Test Workflow
version: "1.0"
defaults:
  role: general
  retries: 0
  retry_delay: 0
steps:
  - id: analyze
    name: Analyze Input
    role: reasoning
    system_prompt: "Analyze the task and return a JSON object with key 'findings'."
    inputs:
      - seed.task
    outputs:
      - findings
  - id: synthesize
    name: Synthesize Results
    role: coding
    system_prompt: "Take the findings and generate a summary with key 'summary'."
    inputs:
      - seed.task
      - analyze.findings
    outputs:
      - summary
  - id: format
    name: Format Output
    role: fast
    system_prompt: "Format the summary as markdown."
    inputs:
      - synthesize.summary
    outputs:
      - formatted_output
"""


class TestEndToEnd:
    def setup_method(self):
        self.ollama = MagicMock()
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
            {"name": "deepseek-r1:32b", "size": 20000000000},
        ]
        # Each step returns different content
        self.ollama.chat.side_effect = [
            {"content": '{"findings": ["finding 1", "finding 2"]}', "prompt_eval_count": 50, "eval_count": 100},
            {"content": '{"summary": "Two key findings identified."}', "prompt_eval_count": 80, "eval_count": 60},
            {"content": "## Summary\n\nTwo key findings identified.", "prompt_eval_count": 40, "eval_count": 30},
        ]
        # Use temp dir for persistence
        self.data_dir = tempfile.mkdtemp()
        self.engine = WorkflowEngine(self.ollama)

    def test_full_workflow_execution(self):
        # Write YAML to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(WORKFLOW_YAML)
            yaml_path = f.name

        # Load
        defn = self.engine.load(yaml_path)
        assert defn.id == "integration-test"
        assert len(defn.steps) == 3

        # Validate
        self.engine.validate(defn, seed_keys=["task"])

        # Execute (patch DATA_DIR so persistence goes to our temp dir)
        with patch("api.services.workflow_engine.DATA_DIR", self.data_dir):
            run = self.engine.run(defn, seed={"task": "Analyze the authentication system"})

        # Verify completion
        assert run.status == "completed"
        assert len(run.step_results) == 3
        assert all(r.status == "completed" for r in run.step_results)

        # Verify context flow
        assert run.context.get_workspace("analyze", "findings") is not None
        assert run.context.get_workspace("synthesize", "summary") is not None
        assert run.context.get_workspace("format", "formatted_output") is not None

        # Verify persistence
        run_dir = os.path.join(self.data_dir, run.run_id)
        assert os.path.exists(os.path.join(run_dir, "run.json"))
        assert os.path.exists(os.path.join(run_dir, "summary.md"))
        assert os.path.exists(os.path.join(run_dir, "artifacts", "analyze.json"))

        # Verify run.json content
        with open(os.path.join(run_dir, "run.json")) as f:
            persisted = json.load(f)
        assert persisted["status"] == "completed"
        assert persisted["workflow_id"] == "integration-test"

        # Cleanup
        os.unlink(yaml_path)

    def test_workflow_fails_mid_execution(self):
        """When step 2 fails, step 3 should not execute"""
        self.ollama.chat.side_effect = [
            {"content": "Step 1 output", "prompt_eval_count": 10, "eval_count": 20},
            Exception("LLM crashed"),
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(WORKFLOW_YAML)
            yaml_path = f.name

        defn = self.engine.load(yaml_path)

        with patch("api.services.workflow_engine.DATA_DIR", self.data_dir):
            run = self.engine.run(defn, seed={"task": "test"})

        assert run.status == "failed"
        assert run.step_results[0].status == "completed"
        assert run.step_results[1].status == "failed"
        assert len(run.step_results) == 2  # step 3 never ran
        assert self.ollama.chat.call_count == 2

        os.unlink(yaml_path)
