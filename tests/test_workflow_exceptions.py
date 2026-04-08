"""Tests for workflow-specific exceptions"""
import pytest
from api.exceptions import (
    WorkflowValidationError,
    WorkflowExecutionError,
    ModelResolutionError,
    StepExecutionError,
)


class TestWorkflowExceptions:
    def test_validation_error(self):
        exc = WorkflowValidationError("Step 'foo' input 'bar.baz' has no producer")
        assert exc.status_code == 422
        assert "foo" in exc.message
        assert exc.code == "workflow_validation_failed"

    def test_execution_error(self):
        exc = WorkflowExecutionError("Workflow 'test' failed at step 'analyze'")
        assert exc.status_code == 500
        assert exc.code == "workflow_execution_failed"

    def test_model_resolution_error(self):
        exc = ModelResolutionError("reasoning")
        assert exc.status_code == 404
        assert "reasoning" in exc.message
        assert exc.code == "model_resolution_failed"

    def test_step_execution_error(self):
        exc = StepExecutionError("analyze", "Ollama timeout after 300s")
        assert exc.status_code == 500
        assert "analyze" in exc.message
        assert exc.code == "step_execution_failed"
