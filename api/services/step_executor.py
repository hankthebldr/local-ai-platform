"""
Step Executor — Runs a single workflow step with full feature support

Features:
- Jinja2 prompt rendering with context injection
- Structured output parsing (JSON, markdown, regex, CSV, key-value)
- Quality gate evaluation on outputs
- Retry with exponential backoff
- Timeout enforcement
- Loop iteration over collections
- Condition evaluation for conditional execution
- Result caching for identical inputs
"""

import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..logging_config import logger
from ..exceptions import StepExecutionError
from ..models.workflow_models import (
    AgentStep,
    GateOperator,
    LoopConfig,
    StepCondition,
    StepResult,
    StepStatus,
    WorkflowContext,
    WorkflowDefaults,
)
from .ollama_service import OllamaService
from .prompt_renderer import PromptRenderer
from .output_parsers import OutputParser
from .quality_gates import QualityGateEvaluator


class StepExecutor:
    """
    Executes a single agent step within a workflow.

    Pipeline: check conditions → render prompts → call LLM → parse output
             → evaluate gates → write context
    """

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service
        self.renderer = PromptRenderer()
        self.parser = OutputParser()
        self.gate_eval = QualityGateEvaluator()
        self._cache: Dict[str, Dict[str, Any]] = {}

    def execute(
        self,
        step: AgentStep,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
    ) -> StepResult:
        """
        Execute a single step: conditions → prompt → LLM → parse → gates → context.

        Returns StepResult with full execution details.
        """
        result = StepResult(
            step_id=step.id,
            status=StepStatus.RUNNING,
            started_at=datetime.utcnow(),
            model_used=resolved_model,
        )

        # ── Check conditions ──────────────────────────────────────────────
        if not self._check_conditions(step, context):
            result.status = StepStatus.SKIPPED
            result.completed_at = datetime.utcnow()
            result.duration_seconds = 0.0
            logger.info(f"Step '{step.id}' skipped — condition not met")
            return result

        # ── Check cache ───────────────────────────────────────────────────
        if step.cache_key:
            cached = self._check_cache(step, context)
            if cached is not None:
                for key, value in cached.items():
                    context.set_workspace(step.id, key, value)
                result.status = StepStatus.COMPLETED
                result.cached = True
                result.completed_at = datetime.utcnow()
                result.duration_seconds = 0.0
                result.parsed_output = cached
                logger.info(f"Step '{step.id}' served from cache")
                return result

        # ── Handle loops ──────────────────────────────────────────────────
        if step.loop:
            return self._execute_loop(step, context, resolved_model, defaults)

        # ── Execute with retry ────────────────────────────────────────────
        temperature = step.config.temperature if step.config.temperature is not None else defaults.temperature
        max_tokens = step.config.max_tokens if step.config.max_tokens is not None else defaults.max_tokens
        retries = step.config.retries if step.config.retries is not None else defaults.retries
        retry_delay = step.config.retry_delay if step.config.retry_delay is not None else defaults.retry_delay

        last_error = None
        for attempt in range(retries + 1):
            try:
                logger.info(
                    f"Step '{step.id}' attempt {attempt + 1}/{retries + 1} "
                    f"using model '{resolved_model}'"
                )

                # Render prompts
                prompts = self.renderer.render_step_prompts(step, context)
                messages = [
                    {"role": "system", "content": prompts["system"]},
                    {"role": "user", "content": prompts["user"]},
                ]

                # Call LLM
                llm_result = self.ollama.chat(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = llm_result.get("content", "")
                result.raw_output = content

                # Parse output
                parsed, parse_success = self.parser.parse(
                    content, step.outputs, step.output_parser
                )
                result.parsed_output = parsed

                if not parse_success and step.output_parser.strict:
                    raise StepExecutionError(
                        f"Output parsing failed (strict mode) for step '{step.id}'"
                    )

                # Write outputs to context
                for key, value in parsed.items():
                    context.set_workspace(step.id, key, value)

                # Evaluate quality gates
                if step.quality_gates:
                    gates_passed, gate_results = self.gate_eval.evaluate(
                        step.quality_gates, parsed
                    )
                    result.gate_results = gate_results

                    if not gates_passed:
                        failed_gates = [
                            g for g in gate_results
                            if not g["passed"] and g["severity"] == "error"
                        ]
                        gate_msg = "; ".join(
                            f"{g['gate']}: {g['reason']}" for g in failed_gates
                        )
                        raise StepExecutionError(
                            f"Quality gates failed for step '{step.id}': {gate_msg}"
                        )

                # Record success
                result.status = StepStatus.COMPLETED
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

                # Cache result
                if step.cache_key:
                    self._store_cache(step, context, parsed)

                logger.info(
                    f"Step '{step.id}' completed in {result.duration_seconds:.1f}s "
                    f"({result.token_count['total_tokens']} tokens)"
                )
                return result

            except StepExecutionError:
                raise
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Step '{step.id}' attempt {attempt + 1} failed: {last_error}"
                )
                if attempt < retries:
                    backoff = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Retrying in {backoff}s...")
                    time.sleep(backoff)

        # All retries exhausted
        result.status = StepStatus.FAILED
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

    # ── Condition Evaluation ──────────────────────────────────────────────

    def _check_conditions(self, step: AgentStep, context: WorkflowContext) -> bool:
        """Evaluate step conditions — return True if step should execute"""
        all_conditions = list(step.conditions)
        if step.condition:
            all_conditions.append(step.condition)

        if not all_conditions:
            return True

        # Determine logic: default from single condition, or from conditions list
        logic = "all"
        if step.condition and not step.conditions:
            logic = step.condition.logic
        elif step.conditions:
            logic = step.conditions[0].logic

        results = [self._eval_condition(c, context) for c in all_conditions]

        if logic == "all":
            return all(results)
        return any(results)

    def _eval_condition(self, cond: StepCondition, context: WorkflowContext) -> bool:
        """Evaluate a single condition against context"""
        value = context.resolve_input(cond.ref)

        op = cond.operator
        expected = cond.value

        if op == GateOperator.NOT_EMPTY:
            return value is not None and value != "" and value != [] and value != {}
        if op == GateOperator.EQUALS:
            return value == expected
        if op == GateOperator.NOT_EQUALS:
            return value != expected
        if op == GateOperator.CONTAINS:
            if isinstance(value, str):
                return str(expected) in value
            if isinstance(value, (list, dict)):
                return expected in value
            return False
        if op == GateOperator.MATCHES:
            import re
            return bool(re.search(str(expected), str(value))) if value else False
        if op == GateOperator.GT:
            try:
                return float(value) > float(expected)
            except (TypeError, ValueError):
                return False
        if op == GateOperator.LT:
            try:
                return float(value) < float(expected)
            except (TypeError, ValueError):
                return False

        # Default: just check truthiness
        return bool(value)

    # ── Loop Execution ────────────────────────────────────────────────────

    def _execute_loop(
        self,
        step: AgentStep,
        context: WorkflowContext,
        resolved_model: str,
        defaults: WorkflowDefaults,
    ) -> StepResult:
        """Execute a step iteratively over a collection"""
        loop = step.loop
        collection = context.resolve_input(loop.over)

        if not isinstance(collection, (list, tuple)):
            return StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                error=f"Loop 'over' ref '{loop.over}' is not a list: {type(collection).__name__}",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                duration_seconds=0.0,
            )

        result = StepResult(
            step_id=step.id,
            status=StepStatus.RUNNING,
            started_at=datetime.utcnow(),
            model_used=resolved_model,
        )

        aggregated: List[Dict[str, Any]] = []
        total_tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        for i, item in enumerate(collection):
            logger.info(f"Step '{step.id}' loop iteration {i + 1}/{len(collection)}")

            # Render with loop variable injected
            extra_vars = {loop.as_var: item, "loop_index": i, "loop_length": len(collection)}
            prompts = self.renderer.render_step_prompts(step, context, extra_vars)
            messages = [
                {"role": "system", "content": prompts["system"]},
                {"role": "user", "content": prompts["user"]},
            ]

            temperature = step.config.temperature if step.config.temperature is not None else defaults.temperature
            max_tokens = step.config.max_tokens if step.config.max_tokens is not None else defaults.max_tokens

            try:
                llm_result = self.ollama.chat(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                content = llm_result.get("content", "")
                parsed, _ = self.parser.parse(content, step.outputs, step.output_parser)
                parsed["_loop_index"] = i
                parsed["_loop_item"] = item
                aggregated.append(parsed)

                total_tokens["prompt_tokens"] += llm_result.get("prompt_eval_count", 0)
                total_tokens["completion_tokens"] += llm_result.get("eval_count", 0)
                total_tokens["total_tokens"] += (
                    llm_result.get("prompt_eval_count", 0)
                    + llm_result.get("eval_count", 0)
                )

            except Exception as e:
                logger.error(f"Loop iteration {i} failed: {e}")
                aggregated.append({"_error": str(e), "_loop_index": i})

        # Write aggregated results
        collect_key = loop.collect_as or step.outputs[0]
        context.set_workspace(step.id, collect_key, aggregated)

        # Also write individual outputs from last iteration if single-result expected
        if aggregated and len(step.outputs) > 1:
            last = aggregated[-1]
            for key in step.outputs:
                if key in last:
                    context.set_workspace(step.id, key, last[key])

        result.status = StepStatus.COMPLETED
        result.token_count = total_tokens
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
        result.parsed_output = {collect_key: aggregated}

        return result

    # ── Cache ─────────────────────────────────────────────────────────────

    def _compute_cache_key(self, step: AgentStep, context: WorkflowContext) -> str:
        """Compute a deterministic cache key from step config + resolved inputs"""
        input_data = {}
        for ref in step.inputs:
            input_data[ref] = context.resolve_input(ref)

        key_material = json.dumps(
            {"cache_key": step.cache_key, "inputs": input_data, "model": step.model, "role": step.role},
            sort_keys=True, default=str,
        )
        return hashlib.sha256(key_material.encode()).hexdigest()[:16]

    def _check_cache(self, step: AgentStep, context: WorkflowContext) -> Optional[Dict[str, Any]]:
        """Check if a cached result exists for this step's inputs"""
        cache_key = self._compute_cache_key(step, context)
        return self._cache.get(cache_key)

    def _store_cache(self, step: AgentStep, context: WorkflowContext, outputs: Dict[str, Any]) -> None:
        """Store step outputs in cache"""
        cache_key = self._compute_cache_key(step, context)
        self._cache[cache_key] = outputs
        logger.debug(f"Cached step '{step.id}' result under key {cache_key}")
