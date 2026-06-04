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
    from .code_promote import stage_inputs, promote
    from ..sandbox_fs import SandboxedFS

    scratch = SandboxedFS(spec.scratch_path, max_file_size_mb=50)
    canon = SandboxedFS(
        os.path.join("data", "sandboxes", f"wf-{workflow_run.run_id}", "_workspace")
    )
    stage_inputs(canon, scratch, cfg)

    res = StepResult(step_id=step.id, status="running", started_at=datetime.utcnow())
    out = backend.execute(spec)

    res.code_exit_code = out.exit_code
    res.tier_used = out.tier_used
    res.peak_rss_mb = out.peak_rss_mb
    res.files_produced = out.files_produced
    promoted = (
        promote(scratch, canon, cfg, out.exit_code) if cfg.promote != "gated" else []
    )
    res.promoted = bool(promoted)
    res.status = "completed" if out.exit_code == 0 else "failed"
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
