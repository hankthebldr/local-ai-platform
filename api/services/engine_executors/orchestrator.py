"""
kind=orchestrator executor — lead agent + dynamic worker dispatch.

Multi-turn loop:
  1. Send the planner prompt + protocol description + initial task
  2. Parse the lead's response for a JSON directive
  3. spawn_worker → instantiate worker template, run in child context,
     format result back to lead as a new user message
  4. complete → write outputs to workspace, terminate
  5. Budget-bounded: max_planner_turns, max_workers_spawned,
     max_total_tokens, max_wall_seconds. Any exceeded cap fails the step.

Worker isolation: each spawned worker runs in a CHILD WorkflowContext whose
seed is the spawn directive's inputs. Worker outputs go to the child
workspace and never leak to the parent — the lead synthesizes them and
emits the final answer via `complete`.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime
from typing import Any, Dict, List, TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep,
    OrchestratorBudget,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from ..orchestrator_protocol import (
    CompleteDirective,
    ParseError,
    format_parse_error_feedback,
    format_worker_result,
    parse_last_directive,
    render_protocol_instructions,
)

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


def execute(
    engine: "WorkflowEngine",
    step: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
) -> StepResult:
    """Run a kind=orchestrator step end-to-end."""
    result = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
    budget = step.budget or OrchestratorBudget()

    # Resolve the planner's model. The planner reuses the workflow's
    # default role unless the orchestrator step itself pins one (model/
    # role on the parent step are reserved for the planner).
    try:
        planner_model = engine.resolver.resolve(
            model=step.model,
            role=step.role,
            default_role=definition.defaults.role,
        )
    except Exception as exc:
        result.status = "failed"
        result.error = f"Planner model resolution failed: {exc}"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.error(result.error)
        return result
    result.model_used = planner_model

    budget_summary = (
        f"max_workers_spawned={budget.max_workers_spawned}, "
        f"max_planner_turns={budget.max_planner_turns}, "
        f"max_total_tokens={budget.max_total_tokens}, "
        f"max_wall_seconds={budget.max_wall_seconds}"
    )
    protocol_block = render_protocol_instructions(
        workers=step.workers,
        declared_outputs=step.outputs,
        budget_summary=budget_summary,
    )

    # Build the planner's system message: persona + protocol description.
    # The planner block must use role_inline or role_ref (validator).
    planner_persona = step.planner.role_inline or (
        f"(role file: {step.planner.role_ref})"
    )
    system_message = f"{planner_persona}\n\n{protocol_block}"

    # Initial user message: the task + any resolved inputs from the parent
    # step's declared inputs. Inputs come from the surrounding workflow
    # workspace via the usual resolve_input mechanism.
    resolved_inputs = {ref: context.resolve_input(ref) for ref in step.inputs}
    resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}
    initial_user = _format_orchestrator_task(
        step.planner.task,
        resolved_inputs,
        step.planner.constraints,
    )

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": initial_user},
    ]

    deadline = time.monotonic() + budget.max_wall_seconds
    spawned = 0
    total_tokens = 0
    turn = 0

    while True:
        turn += 1
        if turn > budget.max_planner_turns:
            result.status = "failed"
            result.error = (
                f"Orchestrator '{step.id}' exceeded max_planner_turns="
                f"{budget.max_planner_turns} without emitting `complete`"
            )
            break
        if time.monotonic() > deadline:
            result.status = "failed"
            result.error = (
                f"Orchestrator '{step.id}' exceeded max_wall_seconds="
                f"{budget.max_wall_seconds}"
            )
            break
        if total_tokens > budget.max_total_tokens:
            result.status = "failed"
            result.error = (
                f"Orchestrator '{step.id}' exceeded max_total_tokens="
                f"{budget.max_total_tokens} (used {total_tokens})"
            )
            break

        logger.info(
            f"Orchestrator '{step.id}' planner turn {turn}/{budget.max_planner_turns}"
        )

        # Call the planner. We use the raw ollama.chat path (not the full
        # StepExecutor) because the orchestrator owns its own multi-turn
        # loop, retry logic, and hook lifecycle — wrapping each turn in
        # the standard step pipeline would double up retries and trigger
        # the JsonSchemaHook for content the lead deliberately doesn't
        # conform to (only the `complete` directive matches the schema).
        try:
            llm_response = engine.ollama.chat(
                model=planner_model,
                messages=messages,
                temperature=definition.defaults.temperature,
                max_tokens=definition.defaults.max_tokens,
            )
        except Exception as exc:
            result.status = "failed"
            result.error = f"Planner LLM call failed on turn {turn}: {exc}"
            break

        lead_output = (llm_response or {}).get("content", "")
        total_tokens += int((llm_response or {}).get("prompt_eval_count", 0))
        total_tokens += int((llm_response or {}).get("eval_count", 0))

        directive = parse_last_directive(lead_output)

        if isinstance(directive, ParseError):
            # Soft failure: tell the lead and give it another turn.
            messages.append({"role": "assistant", "content": lead_output})
            messages.append(
                {"role": "user", "content": format_parse_error_feedback(directive)}
            )
            continue

        if isinstance(directive, CompleteDirective):
            missing = set(step.outputs) - set(directive.outputs.keys())
            if missing:
                messages.append({"role": "assistant", "content": lead_output})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"`complete` is missing required output keys: "
                            f"{sorted(missing)}. Emit a new `complete` "
                            f"directive that includes every declared output."
                        ),
                    }
                )
                continue
            # Success — materialize declared outputs into the workspace.
            for key in step.outputs:
                context.set_workspace(step.id, key, directive.outputs.get(key))
            result.status = "completed"
            logger.info(
                f"Orchestrator '{step.id}' completed after {turn} turn(s), "
                f"{spawned} worker(s) spawned"
            )
            break

        # Otherwise it's a SpawnDirective.
        if spawned >= budget.max_workers_spawned:
            # Tell the lead the budget is exhausted and let it decide whether
            # to wrap up. We do NOT terminate here — the lead might emit
            # `complete` next turn with what it already has.
            messages.append({"role": "assistant", "content": lead_output})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"max_workers_spawned={budget.max_workers_spawned} "
                        f"reached. No further spawns will be honored. Emit "
                        f"`complete` with the best synthesis you can produce."
                    ),
                }
            )
            continue

        worker = step.workers.get(directive.worker_id)
        if worker is None:
            messages.append({"role": "assistant", "content": lead_output})
            messages.append(
                {
                    "role": "user",
                    "content": format_worker_result(
                        directive.worker_id,
                        outputs=None,
                        error=(
                            f"worker {directive.worker_id!r} is not in the "
                            f"catalog ({sorted(step.workers.keys())})"
                        ),
                    ),
                }
            )
            continue

        # Instantiate the worker: deep-copy the template, attach a synthetic
        # id so workspace artifacts don't collide across spawns.
        worker_instance = copy.deepcopy(worker)
        worker_instance.id = f"{step.id}__{directive.worker_id}_{spawned}"

        # Build the worker's child context. Seed = spawn directive inputs
        # PLUS the task description (workers can reference `seed.task`).
        child_seed = dict(directive.inputs)
        child_seed.setdefault("task", directive.task)
        child_context = WorkflowContext(seed=child_seed)

        spawned += 1
        logger.info(
            f"Orchestrator '{step.id}' spawning worker "
            f"'{directive.worker_id}' (spawn #{spawned}/{budget.max_workers_spawned})"
        )

        try:
            worker_result = engine._execute_one_step(
                worker_instance,
                definition,
                child_context,
                workflow_run,
                "",  # resolved_model picked inside per kind
            )
        except Exception as exc:
            worker_result = StepResult(
                step_id=worker_instance.id,
                status="failed",
                error=f"Worker dispatch raised: {exc}",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )

        # Roll up worker token usage into the orchestrator's accounting.
        total_tokens += int(worker_result.token_count.get("total_tokens", 0))

        if worker_result.status == "completed":
            worker_outputs = child_context.workspace.get(worker_instance.id, {})
            messages.append({"role": "assistant", "content": lead_output})
            messages.append(
                {
                    "role": "user",
                    "content": format_worker_result(
                        directive.worker_id, outputs=worker_outputs
                    ),
                }
            )
        else:
            messages.append({"role": "assistant", "content": lead_output})
            messages.append(
                {
                    "role": "user",
                    "content": format_worker_result(
                        directive.worker_id,
                        outputs=None,
                        error=worker_result.error or "unknown failure",
                    ),
                }
            )

    result.token_count = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": total_tokens,
    }
    result.retries = max(0, turn - 1)  # repurpose: planner turns past first
    result.completed_at = datetime.utcnow()
    result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
    if result.status != "completed":
        logger.error(f"Orchestrator '{step.id}' failed: {result.error}")
    return result


def _format_orchestrator_task(
    task: str,
    resolved_inputs: Dict[str, Any],
    constraints: List[str],
) -> str:
    """Build the orchestrator's first user message from the planner's task
    line + resolved parent-step inputs + optional constraints."""
    lines = [task.strip(), ""]
    if resolved_inputs:
        lines.append("### Inputs")
        for key, value in resolved_inputs.items():
            lines.append(f"- {key}: {value!r}")
        lines.append("")
    if constraints:
        lines.append("### Constraints")
        for c in constraints:
            lines.append(f"- {c}")
        lines.append("")
    lines.append("Emit your first directive now.")
    return "\n".join(lines)
