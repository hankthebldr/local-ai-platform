"""kind=code executor — sandboxed code execution.

Phase 1: resolve backend, run, write a result summary into the workspace.
Phase 2 adds three-zone staging + promotion; Phase 3 adds the HITL gate.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep,
    GatePending,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from ..sandbox import CodeExecSpec
from ..sandbox_registry import get_current_sandbox_registry

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


def _scratch_root(run: WorkflowRun, step: AgentStep) -> str:
    return os.path.join("data", "sandboxes", f"wf-{run.run_id}", step.id)


def _approval_required(cfg, backend) -> bool:
    """Decide whether a `kind: code` step must pause for operator approval.

    Policy:
      * approval="auto"     → never gate.
      * approval="required" → always gate.
      * approval="tier_default":
          - Tier-1 (subprocess) always gates: no container isolation, so a
            human must sign off on every run.
          - Tier-2 (container) auto-runs only when fully hardened — network
            is "none" AND the backend advertises can_auto_run. Anything that
            can reach the network, or a backend that hasn't opted in, gates.
    """
    if cfg.approval == "auto":
        if backend.capabilities().isolation_tier == 1:
            logger.warning(
                "code step: approval=auto on Tier-1 subprocess — no HITL gate; "
                "ensure this workflow is trusted (imported/untrusted YAML should not auto-run)"
            )
        return False
    if cfg.approval == "required":
        return True
    caps = backend.capabilities()  # tier_default
    if caps.isolation_tier == 1:
        return True  # subprocess always gates
    return not (
        cfg.network == "none" and caps.can_auto_run
    )  # Tier-2: auto iff hardened


def _consume_decision(run, step_id):
    """Return (and clear) a pending gate decision for this step, if present.

    On re-dispatch after the operator records a decision (Task 13 endpoint +
    engine.resume), the run carries a `pending_gate` whose `decision` is now
    set. We detach it from the run (so a re-run can't re-consume it) and hand
    it back so `execute` proceeds with approved/edited/rejected semantics
    instead of re-pausing.

    Re-pause idempotence: if resume() is called while the gate exists but its
    decision is still None (a mis-timed or direct test resume), this returns
    None, `_approval_required` stays True, and `execute` re-stamps a fresh
    GatePending + returns a second `awaiting_approval` StepResult. That does
    NOT duplicate the step's entry, because resume() drops every non-completed
    step_results row before re-dispatch (workflow_engine.resume keeps only
    status=="completed"), so the prior `awaiting_approval` row is gone and the
    re-stamp leaves exactly one. Proven by
    tests/integration/test_code_gate.py::test_resume_without_decision_does_not_duplicate.
    """
    g = run.pending_gate
    if g and g.step_id == step_id and g.decision is not None:
        run.pending_gate = None
        return g
    return None


def execute(
    engine: "WorkflowEngine",
    step: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
) -> StepResult:
    if os.getenv("CODE_EXEC_ENABLED", "false").lower() != "true":
        return StepResult(
            step_id=step.id,
            status="failed",
            error="code execution disabled (set CODE_EXEC_ENABLED=true)",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )

    cfg = step.code
    code_src = (
        cfg.code
        if cfg.source == "inline"
        else str(context.resolve_input(cfg.code_input))
    )
    backend = get_current_sandbox_registry().resolve(override=cfg.backend_override)

    spec = CodeExecSpec(
        language=cfg.language,
        code=code_src,
        scratch_path=_scratch_root(workflow_run, step),
        files_in=cfg.files_in,
        files_out=cfg.files_out,
        timeout_s=cfg.timeout_s,
        mem_mb=cfg.limits.mem_mb,
        cpus=cfg.limits.cpus,
        pids=cfg.limits.pids,
        network=cfg.network,
    )

    # ── HITL approval gate (Task 12) ──────────────────────────────────────
    # First dispatch: if policy requires approval and no decision has been
    # recorded yet, PAUSE the run. We set workflow_run.pending_gate and return
    # a non-terminal "awaiting_approval" StepResult. The scheduler detects this
    # status, flips the run to "awaiting_approval", checkpoints, and halts.
    #
    # Re-dispatch (after engine.resume): _consume_decision finds the gate's
    # decision populated, clears pending_gate, and we fall through to execute
    # (approved/edited) or short-circuit to failed (rejected).
    decision = _consume_decision(workflow_run, step.id)
    if decision is None and _approval_required(cfg, backend):
        tier = backend.capabilities().isolation_tier
        # Cross-thread write: this runs inside a ThreadPoolExecutor worker
        # (WorkflowEngine._execute_one_step), but `workflow_run.pending_gate`
        # is a shared-run field read by the main thread. Two things make it
        # safe TODAY without a lock here:
        #   1. happens-before — the engine reads pending_gate only AFTER
        #      future.result() for this step returns, which establishes a
        #      happens-before edge so the write is visible before the main
        #      thread checkpoints.
        #   2. single code-gate per tick — current arches dispatch `code`
        #      steps one-per-tick, so no sibling worker writes pending_gate
        #      concurrently (last-writer-wins would otherwise drop a gate).
        # If code steps are ever co-dispatched, this single field becomes a
        # race; _execute_steps' gate-detection guards against silently losing
        # a gate, but the right fix would be per-step gate carriers, not a
        # single run-level slot. Keep the one-per-tick invariant until then.
        workflow_run.pending_gate = GatePending(
            gate_id=f"{workflow_run.run_id}:{step.id}",
            run_id=workflow_run.run_id,
            step_id=step.id,
            step_kind="code",
            proposed_code=code_src,
            network=cfg.network,
            files=cfg.files_out,
            tier=tier,
            question=(
                f"Run {len(code_src.splitlines())}-line {cfg.language} in "
                f"tier-{tier} sandbox?"
            ),
        )
        return StepResult(
            step_id=step.id,
            status="awaiting_approval",
            started_at=datetime.utcnow(),
        )
    if decision and decision.decision == "rejected":
        return StepResult(
            step_id=step.id,
            status="failed",
            approval_status="rejected",
            error=f"rejected by operator: {decision.reason or ''}",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )
    if decision and decision.decision == "edited" and decision.edited_code:
        # Operator edited the code before approving — execute the edited
        # version. Update both code_src (used for staging/logging) and
        # spec.code (what the backend actually runs) BEFORE backend.execute.
        code_src = decision.edited_code
        spec.code = code_src

    from .code_promote import stage_inputs, promote
    from ..sandbox_fs import SandboxedFS

    scratch = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
    canon = SandboxedFS(
        os.path.join("data", "sandboxes", f"wf-{workflow_run.run_id}", "_workspace"),
        max_file_size_mb=50,
    )
    stage_inputs(canon, scratch, cfg)

    res = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
    out = backend.execute(spec)

    res.code_exit_code = out.exit_code
    res.tier_used = out.tier_used
    res.peak_rss_mb = out.peak_rss_mb
    res.files_produced = out.files_produced
    if cfg.promote == "gated" and cfg.files_out:
        logger.info(
            "code step %s: promote=gated with files_out=%s — promotion is deferred "
            "in v1 (files remain in scratch, not copied to the workspace); use "
            "promote=auto_on_green to promote on success",
            step.id,
            cfg.files_out,
        )
    promoted = (
        promote(scratch, canon, cfg, out.exit_code) if cfg.promote != "gated" else []
    )
    res.promoted = bool(promoted)
    res.status = "completed" if out.exit_code == 0 else "failed"
    # Record how this run cleared the gate: "auto" when no approval was
    # required (decision is None), otherwise the operator's decision
    # ("approved" or "edited"; "rejected" short-circuited above).
    res.approval_status = "auto" if decision is None else decision.decision
    if out.exit_code != 0:
        res.error = (
            (out.violations or [out.stderr[:500]])[0]
            if (out.violations or out.stderr)
            else "non-zero exit"
        )
    context.set_workspace(
        step.id,
        step.outputs[0],
        {"stdout": out.stdout, "exit_code": out.exit_code, "files": out.files_produced},
    )
    res.completed_at = datetime.utcnow()
    res.duration_seconds = (res.completed_at - res.started_at).total_seconds()
    logger.info("code step %s exit=%s tier=%s", step.id, out.exit_code, out.tier_used)
    return res
