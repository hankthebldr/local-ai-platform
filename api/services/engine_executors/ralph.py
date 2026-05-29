"""
kind=ralph executor — autonomous self-learning loop.

Each iteration runs every body step in order — typically plan → execute →
verify → reflect, where `reflect` is a consolidate step that appends lessons
to a playbook the `plan` step reads back via `$memory.*` (the self-learning
loop). After each iteration the engine appends a journal record and checks
the halt conditions.

Halt conditions (any fires → stop):
  - halt_file exists (operator's graceful emergency brake)
  - goal_gate evaluates true (success)
  - max_iterations / max_wall_seconds / max_total_tokens (hard caps)
  - max_consecutive_failures (stuck-loop guard)

Resume: the journal is read on entry; iterations already recorded are
skipped so a restarted loop continues rather than re-running from zero.
The playbook on disk is the durable learning state — even a cold restart
picks up the accumulated rules.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from .loop import evaluate_gate

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


def execute(
    engine: "WorkflowEngine",
    step: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
) -> StepResult:
    """Run a kind=ralph step end-to-end."""
    spec = step.ralph
    halt = spec.halt
    agg = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())

    journal_path = Path(spec.journal_path)
    already_done = _read_ralph_journal_count(journal_path)
    if already_done:
        logger.info(
            f"Ralph '{step.id}' resuming: {already_done} iteration(s) "
            f"already journaled at {journal_path}"
        )

    deadline = time.monotonic() + halt.max_wall_seconds
    total_tokens = 0
    consecutive_failures = 0
    iteration = already_done
    halt_reason: Optional[str] = None
    goal_reached = False

    while True:
        # ── Halt checks at the iteration boundary ──────────────────
        if halt.halt_file and Path(halt.halt_file).exists():
            halt_reason = f"halt_file present at {halt.halt_file}"
            logger.info(f"Ralph '{step.id}' halting: {halt_reason}")
            break
        if iteration >= halt.max_iterations:
            halt_reason = f"max_iterations={halt.max_iterations} reached"
            break
        if time.monotonic() > deadline:
            halt_reason = f"max_wall_seconds={halt.max_wall_seconds} exceeded"
            break
        if total_tokens > halt.max_total_tokens:
            halt_reason = (
                f"max_total_tokens={halt.max_total_tokens} exceeded "
                f"(used {total_tokens})"
            )
            break
        if consecutive_failures >= halt.max_consecutive_failures:
            halt_reason = (
                f"max_consecutive_failures={halt.max_consecutive_failures} reached"
            )
            break

        iteration += 1
        logger.info(f"Ralph '{step.id}' iteration {iteration}/{halt.max_iterations}")

        iter_failed = False
        iter_error: Optional[str] = None
        iter_tokens = 0
        for body_step in step.body:
            if body_step.kind == "llm":
                try:
                    body_model = engine.resolver.resolve(
                        model=body_step.model,
                        role=body_step.role,
                        default_role=definition.defaults.role,
                    )
                except Exception as e:
                    iter_failed = True
                    iter_error = (
                        f"body step '{body_step.id}' model resolution failed: {e}"
                    )
                    break
            else:
                body_model = ""

            body_res = engine._execute_one_step(
                body_step, definition, context, workflow_run, body_model
            )
            iter_tokens += int(body_res.token_count.get("total_tokens", 0))
            agg.model_used = body_res.model_used
            if body_res.status != "completed":
                iter_failed = True
                iter_error = f"body step '{body_step.id}' failed: {body_res.error}"
                break

        total_tokens += iter_tokens

        # Evaluate the goal gate (only on a successful iteration — a failed
        # iteration's workspace is unreliable).
        if not iter_failed and halt.goal_gate:
            try:
                goal_reached = evaluate_gate(halt.goal_gate, context)
            except Exception as e:
                iter_failed = True
                iter_error = f"goal_gate evaluation failed: {e}"

        # Journal the iteration (append-only, survives restarts).
        _append_ralph_journal(
            journal_path,
            {
                "iteration": iteration,
                "run_id": workflow_run.run_id,
                "status": "failed" if iter_failed else "completed",
                "error": iter_error,
                "tokens": iter_tokens,
                "goal_reached": goal_reached,
            },
        )

        if iter_failed:
            consecutive_failures += 1
            logger.warning(
                f"Ralph '{step.id}' iteration {iteration} failed "
                f"({consecutive_failures} consecutive): {iter_error}"
            )
        else:
            consecutive_failures = 0

        if goal_reached:
            halt_reason = "goal_gate satisfied"
            logger.info(f"Ralph '{step.id}' reached goal at iteration {iteration}")
            break

    # Materialize each declared output from whichever body step produced it
    # (last-producer-wins). The reflect/journal step is usually last but
    # rarely produces the headline output, so we search all body steps.
    for parent_key in step.outputs:
        for body_step in reversed(step.body):
            if parent_key in (body_step.outputs or []):
                value = context.workspace.get(body_step.id, {}).get(parent_key)
                context.set_workspace(step.id, parent_key, value)
                break

    agg.token_count = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": total_tokens,
    }
    # A ralph loop that stopped on max_consecutive_failures is a real failure;
    # every other halt reason (goal, file, iteration/time/token cap) is a
    # normal terminal — the loop did its bounded work.
    ran = iteration - already_done
    if (
        consecutive_failures >= halt.max_consecutive_failures
        and halt.max_consecutive_failures > 0
    ):
        agg.status = "failed"
        agg.error = (
            f"Ralph '{step.id}' stopped: {halt_reason} "
            f"(ran {ran} iteration(s) this invocation)"
        )
    else:
        agg.status = "completed"
    agg.retries = max(0, ran - 1)
    agg.completed_at = datetime.utcnow()
    agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
    logger.info(
        f"Ralph '{step.id}' {agg.status}: {halt_reason} "
        f"({ran} iteration(s) this invocation, {total_tokens} tokens)"
    )
    return agg


# ── Journal helpers ────────────────────────────────────────────────────────


def _read_ralph_journal_count(journal_path: Path) -> int:
    """Return the highest iteration number recorded in the journal, or 0.

    Used for resume: a restarted ralph loop skips iterations it already
    completed. Robust to a torn final line (counts parseable records only).
    """
    if not journal_path.exists():
        return 0
    highest = 0
    try:
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                highest = max(highest, int(rec.get("iteration", 0)))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    except OSError as exc:
        logger.warning(f"Ralph journal read failed for {journal_path}: {exc}")
        return 0
    return highest


def _append_ralph_journal(journal_path: Path, record: Dict[str, Any]) -> None:
    """Append one iteration record to the journal JSONL. Best-effort — a
    journal write failure logs but does not abort the loop."""
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        **record,
    }
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        logger.warning(f"Ralph journal append failed for {journal_path}: {exc}")
