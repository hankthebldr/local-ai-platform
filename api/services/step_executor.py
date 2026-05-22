"""
Step Executor — Runs a single workflow step through the 6-hook lifecycle.

Pipeline:
  resolve inputs → compose prompt → adapt for family → [before_step hooks]
    → [transform_prompt hooks] → model call → [after_step hooks]
    → [validate_output hooks] → on success return; on failure → [on_failure hooks]
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional

from ..logging_config import logger
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
from .ollama_service import OLLAMA_KEEP_ALIVE, OllamaService


def _safe_pressure_snapshot() -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Capture (arch_name, pressure_dict) or (None, None) if arch detection
    is unavailable. Architecture detection may have failed at startup on
    systems without NVML or on detached deployments — never raise from here.
    """
    try:
        from .architecture import _get_current as _get_arch

        arch = _get_arch()
        snap = arch.snapshot()
        snap_dict = snap.model_dump() if hasattr(snap, "model_dump") else snap.dict()
        return arch.name.value, snap_dict
    except Exception:
        return None, None


def _apply_telemetry(
    result: StepResult,
    llm_result: Dict[str, Any],
    arch_name: Optional[str],
    pressure_before: Optional[Dict[str, Any]],
    pressure_after: Optional[Dict[str, Any]],
) -> None:
    """Populate Phase 2 observability fields on a StepResult.

    Safe to call on both success and failure paths; missing values stay None.
    Pulls Ollama timing fields out of the chat result dict (added in
    ollama_service._extract_timings).
    """
    result.load_duration_ms = llm_result.get("load_duration_ms")
    result.prompt_eval_duration_ms = llm_result.get("prompt_eval_duration_ms")
    result.eval_duration_ms = llm_result.get("eval_duration_ms")
    result.total_duration_ms = llm_result.get("total_duration_ms")
    result.arch_name = arch_name
    result.pressure_before = pressure_before
    result.pressure_after = pressure_after
    result.keep_alive_used = OLLAMA_KEEP_ALIVE


class StepExecutor:
    def __init__(
        self,
        ollama_service: OllamaService,
        composer: PromptComposer,
        hook_bus: HookBus,
        model_resolver=None,
    ):
        self.ollama = ollama_service
        self.composer = composer
        self.hook_bus = hook_bus
        self.model_resolver = model_resolver

    def execute(
        self,
        step: AgentStep,
        workflow: WorkflowDefinition,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
        workflow_run=None,
    ) -> StepResult:
        result = StepResult(
            step_id=step.id, status="running", started_at=datetime.utcnow()
        )
        result.model_used = resolved_model

        temperature = step.config.temperature or defaults.temperature
        max_tokens = step.config.max_tokens or defaults.max_tokens
        max_retries = (
            step.config.retries if step.config.retries is not None else defaults.retries
        )
        retry_delay = (
            step.config.retry_delay
            if step.config.retry_delay is not None
            else defaults.retry_delay
        )

        # --- before_step hooks (BEFORE input resolution) ---------------------
        # before_step runs once per step (not per attempt). This lets a hook
        # like plugin_tool_invoker populate a workspace key that the step
        # references as one of its own inputs.
        pre_ctx = HookContext(
            workflow=workflow_run,
            step=step,
            prompt=None,
            attempt=0,
        )
        pre_results = self.hook_bus.dispatch("before_step", pre_ctx)
        if self._short_circuit(pre_results):
            result.status = "failed"
            result.error = next(
                (r.feedback for r in pre_results if r.feedback),
                "before_step hook aborted",
            )
            result.completed_at = datetime.utcnow()
            result.duration_seconds = (
                result.completed_at - result.started_at
            ).total_seconds()
            logger.error(
                f"Step '{step.id}' aborted by before_step hook: {result.error}"
            )
            return result

        # --- Compose prompt ---------------------------------------------------
        resolved_inputs = {ref: context.resolve_input(ref) for ref in step.inputs}
        resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}

        composed = self._compose(
            step,
            workflow,
            resolved_inputs,
            {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        )

        # --- Adapt for model family ------------------------------------------
        adapter = resolve_adapter(resolved_model)
        composed, params = adapter.prepare(composed, composed.params)
        composed.params = params

        # --- Phase 2 observability: snapshot before the LLM call -------------
        # arch_name is fixed for the run; pressure_before is captured once per
        # step (the retry loop reuses the same pre-state for telemetry). Both
        # are None on systems where architecture detection didn't initialise.
        arch_name, pressure_before = _safe_pressure_snapshot()

        # --- Retry loop with hook lifecycle ----------------------------------
        last_error: Any = None
        current_model = resolved_model
        llm_result: Dict[str, Any] = {}
        pressure_after: Optional[Dict[str, Any]] = None

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

            # before_step (post-compose re-dispatch for prompt-aware hooks
            # like token_budget). Hooks that already executed pre-compose
            # (e.g. plugin_tool_invoker) are idempotent and skip themselves.
            # First attempt only — subsequent attempts use the snapshot.
            if attempt == 0:
                if self._short_circuit(self.hook_bus.dispatch("before_step", ctx)):
                    break
                # Refresh originals if before_step mutated the composed prompt
                _original_user = composed.user
                _original_system = composed.system

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
                logger.warning(
                    f"Step '{step.id}' attempt {attempt + 1} model call raised: {e}"
                )
            finally:
                # Snapshot pressure after every attempt — the most recent
                # snapshot wins (interesting case is the final attempt).
                _, pressure_after = _safe_pressure_snapshot()

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
                _apply_telemetry(
                    result, llm_result, arch_name, pressure_before, pressure_after
                )
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
                last_mutations = (
                    failure_results[-1].mutations if failure_results else {}
                )
                escalate_to = last_mutations.get("escalate_to")
                if escalate_to:
                    context.set_shared(f"_escalated_{step.id}", escalate_to)
                    # Actually switch models if the resolver is available
                    if self.model_resolver is not None:
                        try:
                            new_model = self.model_resolver.resolve(role=escalate_to)
                            logger.info(
                                f"Step '{step.id}' escalating from '{current_model}' "
                                f"to '{new_model}' (role={escalate_to}) on retry"
                            )
                            current_model = new_model
                        except Exception as e:
                            logger.warning(
                                f"Step '{step.id}' escalation to role '{escalate_to}' failed: {e}. "
                                f"Continuing with '{current_model}'."
                            )
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
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        # Telemetry is still useful on failure — a non-None load_duration
        # tells the operator the model loaded but the response was rejected,
        # which is a different failure mode than "model never loaded".
        _apply_telemetry(result, llm_result, arch_name, pressure_before, pressure_after)
        logger.error(
            f"Step '{step.id}' failed after {max_retries + 1} attempts: {last_error}"
        )
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
            output_schema={
                "type": "object",
                "properties": {k: {} for k in step.outputs},
            },
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

    def _write_outputs(
        self, step: AgentStep, ctx: HookContext, context: WorkflowContext
    ):
        """Write step results into the workflow context.

        Strategy:
          1. If a validate_output hook (e.g. json_schema) already produced
             a parsed dict, use it — that's authoritative.
          2. Else, when the step declares multiple output keys, try to
             auto-extract JSON from the raw response and split by key.
             This is the implicit-JSON-output behaviour every multi-output
             step needs; otherwise every key gets the same raw text and
             downstream steps see prompt-context noise. (Bug fix May 2026:
             previously the engine wrote ctx.output to every key unless an
             explicit json_schema hook ran, making multi-stage workflows
             un-composable in practice.)
          3. Fall back to writing the raw text. Single-output steps and
             non-JSON multi-output steps both flow through this path.
        """
        parsed = ctx.parsed
        if isinstance(parsed, dict):
            for key in step.outputs:
                if key in parsed:
                    context.set_workspace(step.id, key, parsed[key])
                else:
                    context.set_workspace(step.id, key, ctx.output)
            return

        if len(step.outputs) == 1:
            context.set_workspace(step.id, step.outputs[0], ctx.output)
            return

        auto = self._auto_extract_json(ctx.output)
        if isinstance(auto, dict):
            for key in step.outputs:
                if key in auto:
                    context.set_workspace(step.id, key, auto[key])
                else:
                    # Field absent from parsed JSON: store empty rather than
                    # leaking the whole raw blob into every other key.
                    context.set_workspace(step.id, key, None)
            return

        # Last resort: raw text under every key. Preserves the legacy
        # behaviour for steps that genuinely return prose into multiple
        # named outputs (rare).
        for key in step.outputs:
            context.set_workspace(step.id, key, ctx.output)

    @staticmethod
    def _auto_extract_json(raw: Optional[str]) -> Any:
        """Best-effort JSON extraction from a raw model response.

        Handles three common shapes models actually emit:
          - Pure JSON object / array
          - Markdown-fenced JSON: ```json {...} ```
          - Narrative-then-JSON, where the JSON is the first balanced
            {...} or [...] in the text.

        Returns the parsed Python value on success, or None on failure.
        Never raises — callers should treat None as "not parseable, fall
        back to raw text".
        """
        if not raw or not isinstance(raw, str):
            return None
        text = raw.strip()
        if not text:
            return None

        # Quick path: pure JSON.
        if text[0] in "{[":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Markdown-fenced JSON.
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # Largest balanced {...} or [...] in the text. Use a greedy-then-
        # shrinking strategy so we accept extra prose around a JSON blob.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
        return None
