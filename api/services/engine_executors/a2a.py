"""
kind=a2a executor — delegate to an external A2A-protocol agent.

Flow:
  1. Resolve declared inputs against the workflow context
  2. Fetch the remote AgentCard, validate the skill exists
  3. POST tasks/send + poll tasks/get OR tasks/sendSubscribe (SSE), per
     step.streaming, until the remote task reaches a terminal state
  4. Map artifacts onto declared outputs and write to workspace

Returns one StepResult; token counts stay at zero (the remote agent owns its
own model billing). The step's `model_used` records `a2a:<skill>@<url>` so
the Runs view can show which agent ran the step at a glance.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import AgentStep, StepResult, WorkflowContext

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


def execute(
    engine: "WorkflowEngine",
    step: AgentStep,
    context: WorkflowContext,
) -> StepResult:
    """Run a kind=a2a step end-to-end. Engine is accepted for signature
    consistency with the other executors but isn't read — a2a steps don't
    touch the resolver, ollama service, or memory store."""
    from ..a2a_client import A2AClient, A2AClientError

    _ = engine  # signature consistency; unused
    result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
    result.model_used = f"a2a:{step.skill}@{step.agent_card_url}"

    resolved_inputs = {ref: context.resolve_input(ref) for ref in step.inputs}
    resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}

    logger.info(
        f"A2A step '{step.id}' delegating to skill '{step.skill}' at "
        f"{step.agent_card_url}"
    )

    client = A2AClient()
    try:
        outputs, _task = client.call_skill(
            agent_card_url=step.agent_card_url,
            skill_id=step.skill,
            resolved_inputs=resolved_inputs,
            declared_outputs=step.outputs,
            auth=step.auth,
            timeout=step.timeout,
            streaming=step.streaming,
        )
    except A2AClientError as exc:
        result.status = "failed"
        result.error = str(exc)
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.error(f"A2A step '{step.id}' failed: {exc}")
        return result
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.error = f"A2A step raised: {exc}"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.exception(f"A2A step '{step.id}' raised")
        return result

    for key, value in outputs.items():
        context.set_workspace(step.id, key, value)

    result.status = "completed"
    result.completed_at = datetime.utcnow()
    result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
    logger.info(
        f"A2A step '{step.id}' completed in {result.duration_seconds:.1f}s "
        f"({len([v for v in outputs.values() if v is not None])} of "
        f"{len(step.outputs)} outputs populated)"
    )
    return result
