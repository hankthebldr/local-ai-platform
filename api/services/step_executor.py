"""
Step Executor — Runs a single workflow step through the 6-hook lifecycle.

Pipeline:
  resolve inputs → compose prompt → adapt for family → [before_step hooks]
    → [transform_prompt hooks] → model call → [after_step hooks]
    → [validate_output hooks] → on success return; on failure → [on_failure hooks]
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..logging_config import logger
from ..exceptions import GenerationError
from ..models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefaults,
    WorkflowDefinition,
)
from .hook_bus import HookBus, HookContext, HookResult
from .prompt_composer import PromptComposer, ComposedPrompt
from .model_adapters import resolve_adapter
from .ollama_service import OllamaService


class StepExecutor:
    def __init__(
        self,
        ollama_service: OllamaService,
        composer: PromptComposer,
        hook_bus: HookBus,
    ):
        self.ollama = ollama_service
        self.composer = composer
        self.hook_bus = hook_bus

    def execute(
        self,
        step: AgentStep,
        workflow: WorkflowDefinition,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
        workflow_run=None,
    ) -> StepResult:
        result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
        result.model_used = resolved_model

        temperature = step.config.temperature or defaults.temperature
        max_tokens = step.config.max_tokens or defaults.max_tokens
        max_retries = step.config.retries if step.config.retries is not None else defaults.retries
        retry_delay = step.config.retry_delay if step.config.retry_delay is not None else defaults.retry_delay

        # --- Compose prompt ---------------------------------------------------
        resolved_inputs = {
            ref: context.resolve_input(ref) for ref in step.inputs
        }
        resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}

        composed = self._compose(step, workflow, resolved_inputs, {
            "temperature": temperature,
            "num_predict": max_tokens,
        })

        # --- Adapt for model family ------------------------------------------
        adapter = resolve_adapter(resolved_model)
        composed, params = adapter.prepare(composed, composed.params)
        composed.params = params

        # --- Retry loop with hook lifecycle ----------------------------------
        last_error: Any = None
        current_model = resolved_model
        llm_result: Dict[str, Any] = {}

        # Snapshot the composed prompt so each retry attempt starts clean.
        # Hooks (especially retry_with_feedback) mutate ctx.prompt.user in place;
        # without the reset the user message would accumulate feedback across attempts.
        _original_user = composed.user
        _original_system = composed.system

        for attempt in range(max_retries + 1):
            ctx = HookContext(
                workflow=workflow_run,
                step=step,
                prompt=composed,
                attempt=attempt,
            )

            # before_step
            if self._short_circuit(self.hook_bus.dispatch("before_step", ctx)):
                break

            # transform_prompt
            if self._short_circuit(self.hook_bus.dispatch("transform_prompt", ctx)):
                break

            # model call
            try:
                llm_result = self.ollama.chat(
                    model=current_model,
                    messages=ctx.prompt.as_messages(),
                    temperature=ctx.prompt.params.get("temperature", temperature),
                    max_tokens=ctx.prompt.params.get("num_predict", max_tokens),
                )
                ctx.output = llm_result.get("content", "")
            except Exception as e:
                ctx.output = ""
                ctx.error = e
                last_error = str(e)
                logger.warning(f"Step '{step.id}' attempt {attempt + 1} model call raised: {e}")

            # after_step
            self.hook_bus.dispatch("after_step", ctx)

            # validate_output
            validation_results = self.hook_bus.dispatch("validate_output", ctx)
            validation_failed = any(r.action != "continue" for r in validation_results)

            if not validation_failed and ctx.output:
                # Success — write outputs to workspace
                self._write_outputs(step, ctx, context)
                result.status = "completed"
                result.retries = attempt
                result.token_count = self._token_count(llm_result)
                result.completed_at = datetime.utcnow()
                result.duration_seconds = (
                    result.completed_at - result.started_at
                ).total_seconds()
                return result

            # on_failure
            failure_feedback = next(
                (r.feedback for r in validation_results if r.feedback),
                last_error or "unknown validation failure",
            )
            from api.hooks.builtins.retry_with_feedback import ValidationFailure
            ctx.error = ValidationFailure(feedback=str(failure_feedback))

            # Reset the prompt to its composed baseline before on_failure hooks
            # append retry feedback. Without this reset, retry_with_feedback
            # would stack a new feedback block on top of every previous attempt's
            # feedback (the user message grows unbounded across retries).
            composed.user = _original_user
            composed.system = _original_system

            failure_results = self.hook_bus.dispatch("on_failure", ctx)
            decision = failure_results[-1].action if failure_results else "fail"

            if decision == "retry" and attempt < max_retries:
                last_mutations = failure_results[-1].mutations if failure_results else {}
                escalate_to = last_mutations.get("escalate_to")
                if escalate_to:
                    context.set_shared(f"_escalated_{step.id}", escalate_to)
                if retry_delay > 0:
                    time.sleep(retry_delay)
                last_error = failure_feedback
                continue
            else:
                last_error = failure_feedback
                break

        # Failure path
        result.status = "failed"
        result.error = str(last_error)
        result.retries = max_retries
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
        logger.error(f"Step '{step.id}' failed after {max_retries + 1} attempts: {last_error}")
        return result

    # ── helpers ────────────────────────────────────────────────────────────

    def _compose(
        self,
        step: AgentStep,
        workflow: WorkflowDefinition,
        resolved_inputs: dict,
        default_params: dict,
    ) -> ComposedPrompt:
        workflow_context_str = self._render_context(workflow.context)
        # v2 path
        if step.prompt is not None:
            output_schema = step.output_schema or {}
            return self.composer.compose(
                role_ref=step.prompt.role_ref,
                role_inline=step.prompt.role_inline,
                context=workflow_context_str,
                task=step.prompt.task,
                constraints=step.prompt.constraints,
                output_schema=output_schema,
                resolved_inputs=resolved_inputs,
                params=dict(default_params),
            )
        # v1 path — wrap legacy system_prompt
        return self.composer.compose(
            role_ref=None,
            role_inline=step.system_prompt,
            context=workflow_context_str,
            task="(See role description above.)",
            constraints=[],
            output_schema={"type": "object", "properties": {k: {} for k in step.outputs}},
            resolved_inputs=resolved_inputs,
            params=dict(default_params),
        )

    @staticmethod
    def _render_context(context: dict) -> str:
        if not context:
            return "(no workflow context provided)"
        return "\n".join(f"- {k}: {v}" for k, v in context.items())

    @staticmethod
    def _short_circuit(results: list[HookResult]) -> bool:
        return any(r.action == "fail" for r in results)

    @staticmethod
    def _token_count(llm_result) -> dict:
        prompt_tokens = llm_result.get("prompt_eval_count", 0) if llm_result else 0
        completion_tokens = llm_result.get("eval_count", 0) if llm_result else 0
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    def _write_outputs(self, step: AgentStep, ctx: HookContext, context: WorkflowContext):
        # Prefer parsed (from json_schema hook) over raw text
        parsed = ctx.parsed
        if isinstance(parsed, dict):
            for key in step.outputs:
                if key in parsed:
                    context.set_workspace(step.id, key, parsed[key])
                else:
                    context.set_workspace(step.id, key, ctx.output)
        elif len(step.outputs) == 1:
            context.set_workspace(step.id, step.outputs[0], ctx.output)
        else:
            for key in step.outputs:
                context.set_workspace(step.id, key, ctx.output)
