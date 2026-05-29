"""
kind=consolidate executor — Dreaming-style cross-run memory.

One LLM call over the declared inputs (which may include `$memory.*` refs to
prior memory), then writes the model output into the named memory store via
the configured merge strategy. The same output is mirrored into every
declared workspace output so downstream steps in the same run can read it.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
)

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


def execute(
    engine: "WorkflowEngine",
    step: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
) -> StepResult:
    """Run a kind=consolidate step end-to-end."""
    spec = step.consolidate
    result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())

    # Resolve the consolidation model: spec.model/role override the
    # workflow default role.
    try:
        model = engine.resolver.resolve(
            model=spec.model,
            role=spec.role,
            default_role=definition.defaults.role,
        )
    except Exception as exc:
        result.status = "failed"
        result.error = f"Consolidate model resolution failed: {exc}"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.error(result.error)
        return result
    result.model_used = model

    # Resolve inputs (supports $memory.* via the attached store) and build
    # the consolidation prompt. We render inputs into the user message and
    # use spec.system_prompt as the system role.
    resolved_inputs = {ref: context.resolve_input(ref) for ref in step.inputs}
    resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}

    user_lines: List[str] = ["## Material to consolidate", ""]
    for ref, value in resolved_inputs.items():
        user_lines.append(f"### {ref}")
        user_lines.append(str(value))
        user_lines.append("")
    user_lines.append(
        "Produce the consolidated memory. Output only the content to store."
    )
    messages = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": "\n".join(user_lines)},
    ]

    logger.info(
        f"Consolidate step '{step.id}' → {spec.target}/{spec.target_name} "
        f"(strategy={spec.merge_strategy})"
    )

    try:
        llm_response = engine.ollama.chat(
            model=model,
            messages=messages,
            temperature=definition.defaults.temperature,
            max_tokens=definition.defaults.max_tokens,
        )
    except Exception as exc:
        result.status = "failed"
        result.error = f"Consolidate LLM call failed: {exc}"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.error(result.error)
        return result

    consolidated = (llm_response or {}).get("content", "") or ""
    prompt_tokens = int((llm_response or {}).get("prompt_eval_count", 0))
    completion_tokens = int((llm_response or {}).get("eval_count", 0))
    result.token_count = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }

    if not consolidated.strip():
        result.status = "failed"
        result.error = "Consolidate produced empty output — nothing to store"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.error(result.error)
        return result

    # Write to the target store.
    try:
        if spec.target == "playbook":
            engine.memory.write_playbook(
                spec.target_name, consolidated, strategy=spec.merge_strategy
            )
        elif spec.target == "semantic":
            engine.memory.write_semantic(
                spec.target_name, consolidated, strategy=spec.merge_strategy
            )
        elif spec.target == "episodic":
            engine.memory.append_episodic(spec.target_name, consolidated, run_id=None)
    except Exception as exc:
        result.status = "failed"
        result.error = f"Consolidate store write failed: {exc}"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.error(result.error)
        return result

    # Mirror the consolidated content into every declared workspace output.
    for key in step.outputs:
        context.set_workspace(step.id, key, consolidated)

    result.status = "completed"
    result.completed_at = datetime.utcnow()
    result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
    logger.info(
        f"Consolidate step '{step.id}' wrote {len(consolidated)} chars to "
        f"{spec.target}/{spec.target_name}"
    )
    return result
