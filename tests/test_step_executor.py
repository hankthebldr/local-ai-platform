"""Tests for StepExecutor — single step execution with retry"""
import pytest
from unittest.mock import MagicMock, patch
from api.services.step_executor import StepExecutor
from api.models.workflow_models import (
    AgentStep, StepConfig, WorkflowContext, WorkflowDefaults,
)
from api.exceptions import GenerationError


class TestStepExecutor:
    def setup_method(self):
        self.ollama = MagicMock()
        self.executor = StepExecutor(self.ollama)

    def test_execute_step_success(self):
        """Successful step execution writes outputs to context"""
        step = AgentStep(
            id="analyze",
            name="Analyze",
            role="reasoning",
            system_prompt="Analyze the data. Return JSON with key 'entities'.",
            inputs=["seed.task"],
            outputs=["result"],
        )
        ctx = WorkflowContext(seed={"task": "analyze users"})
        defaults = WorkflowDefaults()

        self.ollama.chat.return_value = {
            "content": "Here is the analysis result.",
            "prompt_eval_count": 50,
            "eval_count": 100,
        }

        result = self.executor.execute(
            step=step,
            context=ctx,
            resolved_model="deepseek-r1:32b",
            defaults=defaults,
        )

        assert result.status == "completed"
        assert result.model_used == "deepseek-r1:32b"
        assert result.token_count["completion_tokens"] == 100
        assert ctx.get_workspace("analyze", "result") is not None

    def test_execute_step_retries_on_failure(self):
        """Step retries on GenerationError then succeeds"""
        step = AgentStep(
            id="draft",
            name="Draft",
            role="coding",
            system_prompt="Draft rules.",
            inputs=["seed.task"],
            outputs=["rules"],
            config=StepConfig(retries=2, retry_delay=0),
        )
        ctx = WorkflowContext(seed={"task": "draft"})
        defaults = WorkflowDefaults()

        # First call fails, second succeeds
        self.ollama.chat.side_effect = [
            GenerationError("timeout"),
            {
                "content": "Here are the rules.",
                "prompt_eval_count": 30,
                "eval_count": 80,
            },
        ]

        result = self.executor.execute(
            step=step,
            context=ctx,
            resolved_model="dolphin3:8b",
            defaults=defaults,
        )

        assert result.status == "completed"
        assert result.retries == 1
        assert self.ollama.chat.call_count == 2

    def test_execute_step_fails_after_retries_exhausted(self):
        """Step fails after all retries exhausted"""
        step = AgentStep(
            id="fail",
            name="Fail",
            role="fast",
            system_prompt="This will fail.",
            inputs=[],
            outputs=["nothing"],
            config=StepConfig(retries=1, retry_delay=0),
        )
        ctx = WorkflowContext(seed={})
        defaults = WorkflowDefaults()

        self.ollama.chat.side_effect = GenerationError("always fails")

        result = self.executor.execute(
            step=step,
            context=ctx,
            resolved_model="dolphin3:8b",
            defaults=defaults,
        )

        assert result.status == "failed"
        assert result.error is not None
        assert result.retries == 1

    def test_prompt_assembly_includes_only_declared_inputs(self):
        """Prompt only contains declared inputs, not entire context"""
        step = AgentStep(
            id="s2",
            name="Step 2",
            role="fast",
            system_prompt="Process the entities.",
            inputs=["seed.task", "s1.entities"],
            outputs=["processed"],
        )
        ctx = WorkflowContext(seed={"task": "test", "secret": "should not appear"})
        ctx.set_workspace("s1", "entities", ["User", "Post"])
        ctx.set_workspace("s1", "other_data", "should not appear in prompt")

        self.ollama.chat.return_value = {
            "content": "Processed.",
            "prompt_eval_count": 20,
            "eval_count": 30,
        }

        defaults = WorkflowDefaults()
        self.executor.execute(step=step, context=ctx, resolved_model="m", defaults=defaults)

        # Check the messages sent to ollama.chat
        call_args = self.ollama.chat.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][1]
        user_content = messages[-1]["content"]
        assert "User" in user_content
        assert "should not appear" not in user_content
