"""
kind=loop executor — refine-until-good iteration.

Each iteration runs every body step in order. After the body, the `until`
predicate (a boolean expression over the latest workspace) is evaluated. If
satisfied the loop terminates and the last body step's outputs are mapped
onto the parent's declared outputs. If `max_iterations` is hit without
satisfaction, `on_max_iterations` decides between emit_best and fail.

Also home to the gate evaluator (`evaluate_gate`) shared with kind=ralph,
which uses the same expression grammar for its goal_gate.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


# ── Gate evaluator (shared with ralph.goal_gate) ───────────────────────────

# Whitelist of AST node types allowed in a loop `until.gate` expression after
# dotted refs are substituted out. This keeps gate evaluation from being a
# generic eval() — only comparison/boolean/literal logic survives the walk.
_SAFE_GATE_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.In,
    ast.NotIn,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
)

_GATE_REF_RE = re.compile(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+\b")


def evaluate_gate(gate_expr: str, context: WorkflowContext) -> bool:
    """Safely evaluate a loop termination gate against the workspace.

    The gate is a small boolean expression. Dotted refs (e.g. `critic.approved`)
    are resolved against the workspace before evaluation; the residual
    expression is parsed with the `ast` module and rejected unless every node
    is in `_SAFE_GATE_NODES`. No attribute access, no function calls, no
    subscripts — just literals, names, comparisons, and boolean composition.

    Returns the boolean result. Raises ValueError on parse/eval failure so the
    caller can surface a clean engine-level error.
    """
    refs = sorted(set(_GATE_REF_RE.findall(gate_expr)))
    ref_to_var: Dict[str, str] = {}
    sub_expr = gate_expr
    for i, ref in enumerate(refs):
        var = f"__gate_{i}"
        ref_to_var[ref] = var
        sub_expr = re.sub(rf"\b{re.escape(ref)}\b", var, sub_expr)

    eval_locals: Dict[str, Any] = {}
    for ref, var in ref_to_var.items():
        eval_locals[var] = context.resolve_input(ref)

    try:
        tree = ast.parse(sub_expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"gate expression has invalid syntax: {e}")

    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_GATE_NODES):
            raise ValueError(
                f"gate expression uses disallowed construct: {type(node).__name__}"
            )

    try:
        return bool(
            eval(
                compile(tree, "<loop-gate>", "eval"),
                {"__builtins__": {}},
                eval_locals,
            )
        )
    except Exception as e:
        raise ValueError(f"gate evaluation raised: {e}")


# ── kind=loop executor ─────────────────────────────────────────────────────


def execute(
    engine: "WorkflowEngine",
    parent: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
) -> StepResult:
    """Run a kind=loop step."""
    agg = StepResult(step_id=parent.id, status="running", started_at=datetime.utcnow())
    iter_count = 0
    satisfied = False
    last_body_step = parent.body[-1]

    for iteration in range(parent.max_iterations):
        iter_count = iteration + 1
        logger.info(
            f"Loop '{parent.id}' iteration {iter_count}/{parent.max_iterations}"
        )

        for body_step in parent.body:
            # Each body step needs its own model resolution. Composite bodies
            # recurse through _execute_one_step which handles its own resolution.
            if body_step.kind == "llm":
                try:
                    body_model = engine.resolver.resolve(
                        model=body_step.model,
                        role=body_step.role,
                        default_role=definition.defaults.role,
                    )
                except Exception as e:
                    agg.status = "failed"
                    agg.error = (
                        f"Loop body step '{body_step.id}' model resolution "
                        f"failed on iteration {iter_count}: {e}"
                    )
                    agg.completed_at = datetime.utcnow()
                    agg.duration_seconds = (
                        agg.completed_at - agg.started_at
                    ).total_seconds()
                    logger.error(agg.error)
                    return agg
            else:
                body_model = ""

            body_res = engine._execute_one_step(
                body_step, definition, context, workflow_run, body_model
            )
            agg.token_count["prompt_tokens"] += body_res.token_count.get(
                "prompt_tokens", 0
            )
            agg.token_count["completion_tokens"] += body_res.token_count.get(
                "completion_tokens", 0
            )
            agg.token_count["total_tokens"] = (
                agg.token_count["prompt_tokens"] + agg.token_count["completion_tokens"]
            )
            agg.model_used = body_res.model_used

            if body_res.status != "completed":
                agg.status = "failed"
                agg.error = (
                    f"Loop body step '{body_step.id}' failed on "
                    f"iteration {iter_count}: {body_res.error}"
                )
                agg.completed_at = datetime.utcnow()
                agg.duration_seconds = (
                    agg.completed_at - agg.started_at
                ).total_seconds()
                logger.error(agg.error)
                return agg

        # After the body, evaluate the gate.
        try:
            satisfied = evaluate_gate(parent.until.gate, context)
        except Exception as e:
            agg.status = "failed"
            agg.error = (
                f"Loop '{parent.id}' gate evaluation failed on "
                f"iteration {iter_count}: {e}"
            )
            agg.completed_at = datetime.utcnow()
            agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
            logger.error(agg.error)
            return agg

        if satisfied:
            logger.info(
                f"Loop '{parent.id}' gate satisfied after iteration {iter_count}"
            )
            break

    # Map the last body step's outputs onto the parent's declared outputs.
    # Validator guarantees every parent output key is produced by the
    # last body step.
    last_ws = context.workspace.get(last_body_step.id, {})
    for parent_key in parent.outputs:
        context.set_workspace(parent.id, parent_key, last_ws.get(parent_key))

    if not satisfied and parent.until.on_max_iterations == "fail":
        agg.status = "failed"
        agg.error = (
            f"Loop '{parent.id}' hit max_iterations={parent.max_iterations} "
            f"without satisfying gate '{parent.until.gate}'"
        )
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    agg.status = "completed"
    agg.completed_at = datetime.utcnow()
    agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
    agg.retries = iter_count - 1  # repurpose: iterations beyond the first
    logger.info(
        f"Loop '{parent.id}' completed in {agg.duration_seconds:.1f}s "
        f"({iter_count} iteration(s){', gate satisfied' if satisfied else ', emit_best'})"
    )
    return agg
