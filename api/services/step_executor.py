"""
Step Executor — Runs a single workflow step with retry logic

Assembles a prompt from the step's declared inputs, calls OllamaService,
writes outputs to context, and handles retries with exponential backoff.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict

from ..logging_config import logger
from ..exceptions import GenerationError, StepExecutionError
from ..models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefaults,
)
from .ollama_service import OllamaService


class StepExecutor:
    """Executes a single agent step within a workflow"""

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service

    def execute(
        self,
        step: AgentStep,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
    ) -> StepResult:
        """
        Execute a single step: assemble prompt → call LLM → write outputs.

        Returns StepResult with status, timing, and token counts.
        Retries on failure up to configured limit.
        """
        result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
        result.model_used = resolved_model

        # Resolve config (step overrides > workflow defaults)
        temperature = step.config.temperature or defaults.temperature
        max_tokens = step.config.max_tokens or defaults.max_tokens
        retries = step.config.retries if step.config.retries is not None else defaults.retries
        retry_delay = step.config.retry_delay if step.config.retry_delay is not None else defaults.retry_delay

        # Assemble prompt from declared inputs only
        messages = self._build_messages(step, context)

        # Execute with retry
        last_error = None
        for attempt in range(retries + 1):
            try:
                logger.info(
                    f"Step '{step.id}' attempt {attempt + 1}/{retries + 1} "
                    f"using model '{resolved_model}'"
                )

                llm_result = self.ollama.chat(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = llm_result.get("content", "")

                # Write outputs to context workspace
                if len(step.outputs) == 1:
                    # Single output — write the entire response
                    context.set_workspace(step.id, step.outputs[0], content)
                else:
                    # Multiple outputs — try to parse as JSON, fall back to full content
                    parsed = self._try_parse_outputs(content, step.outputs)
                    for key, value in parsed.items():
                        context.set_workspace(step.id, key, value)

                # Record success metrics
                result.status = "completed"
                result.retries = attempt
                result.token_count = {
                    "prompt_tokens": llm_result.get("prompt_eval_count", 0),
                    "completion_tokens": llm_result.get("eval_count", 0),
                    "total_tokens": (
                        llm_result.get("prompt_eval_count", 0)
                        + llm_result.get("eval_count", 0)
                    ),
                }
                result.completed_at = datetime.utcnow()
                result.duration_seconds = (
                    result.completed_at - result.started_at
                ).total_seconds()

                logger.info(
                    f"Step '{step.id}' completed in {result.duration_seconds:.1f}s "
                    f"({result.token_count['total_tokens']} tokens)"
                )
                return result

            except (GenerationError, Exception) as e:
                last_error = str(e)
                logger.warning(
                    f"Step '{step.id}' attempt {attempt + 1} failed: {last_error}"
                )
                if attempt < retries and retry_delay > 0:
                    time.sleep(retry_delay)

        # All retries exhausted
        result.status = "failed"
        result.error = last_error
        result.retries = retries
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()

        logger.error(
            f"Step '{step.id}' failed after {retries + 1} attempts: {last_error}"
        )
        return result

    def _build_messages(
        self, step: AgentStep, context: WorkflowContext
    ) -> list:
        """
        Assemble LLM messages from step's system_prompt and declared inputs.
        Only includes data the step explicitly declared in its inputs list.
        """
        # System message
        messages = [{"role": "system", "content": step.system_prompt}]

        # Resolve declared inputs into a context block
        input_data: Dict[str, Any] = {}
        for input_ref in step.inputs:
            value = context.resolve_input(input_ref)
            if value is not None:
                input_data[input_ref] = value

        # Build user message with resolved context
        if input_data:
            context_block = "## Context\n\n"
            for ref, value in input_data.items():
                if isinstance(value, (dict, list)):
                    context_block += f"### {ref}\n```json\n{json.dumps(value, indent=2)}\n```\n\n"
                else:
                    context_block += f"### {ref}\n{value}\n\n"
            context_block += "## Task\n\nBased on the context above, complete your assigned task."
            messages.append({"role": "user", "content": context_block})
        else:
            messages.append({"role": "user", "content": "Complete your assigned task."})

        return messages

    def _try_parse_outputs(
        self, content: str, output_keys: list
    ) -> Dict[str, Any]:
        """
        Try to parse LLM response into multiple named outputs.
        Falls back to assigning entire content to each output key.
        """
        # Try JSON parse
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                result = {}
                for key in output_keys:
                    result[key] = parsed.get(key, content)
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to find JSON block in markdown
        if "```json" in content:
            try:
                json_start = content.index("```json") + 7
                json_end = content.index("```", json_start)
                json_str = content[json_start:json_end].strip()
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    result = {}
                    for key in output_keys:
                        result[key] = parsed.get(key, content)
                    return result
            except (ValueError, json.JSONDecodeError):
                pass

        # Fallback: assign full content to all output keys
        return {key: content for key in output_keys}
