"""Run dispatch — the single seam through which a workflow run is prepared
and handed to the frozen engine.

Two entry points express the *exact* contract the async run handler has always
had, factored out so the scheduler loop can reuse it byte-for-byte:

    prepare_run(*, workflow_id | definition, seed, origin) -> (defn, run_id)
        Resolve/validate a definition, mint a uuid4 run_id, checkpoint a
        "queued" placeholder, and drop an atomic origin.json sidecar next to
        the run dir. Expresses BOTH run-async branches (workflow_id AND inline
        definition — the Composer Run ▶ live path builds {definition, seed}).

    dispatch_blocking(defn, seed, run_id) -> None
        Blocking engine.run() with the historical TypeError fallback for older
        engine signatures preserved verbatim. Runs on a worker thread — never
        the event loop.

The origin sidecar (data/workflows/<run_id>/origin.json) is the ONLY new
observable versus the legacy handler; the frozen engine is untouched. In-process
dispatch deliberately bypasses HTTP auth middleware (that only wraps HTTP) — the
loop calls the engine directly rather than loopback-POSTing with a stored key.
Zero network I/O: privacy-first.
"""

from __future__ import annotations

import json
import os
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.workflow_engine import WorkflowEngine

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


# ── Errors (router maps .http_status) ───────────────────────────────────────


class RunPrepareError(Exception):
    """Base for dispatch-prep failures. ``http_status`` tells the router how to
    surface it; ``WorkflowValidationError`` is raised separately (→ 422)."""

    http_status = 400


class WorkflowNotFound(RunPrepareError):
    http_status = 404


def build_engine() -> WorkflowEngine:
    """Construct a WorkflowEngine mirroring the router's factory. Kept local so
    run_dispatch never imports the router (which imports this module)."""
    return WorkflowEngine(OllamaService(OLLAMA_HOST))


def _write_origin_sidecar(
    run_id: str, workflow_id: str, origin: Dict[str, Any]
) -> None:
    """Atomic tmp+replace write of data/workflows/<run_id>/origin.json.

    Best-effort: a sidecar write failure logs but never blocks the run — the
    run still executes, it just renders as an untagged Manual run downstream.
    """
    # Read DATA_DIR live off the engine module so the run root honours env /
    # test overrides — matching engine._checkpoint's own dynamic lookup.
    from ..services import workflow_engine as _we

    run_dir = Path(_we.DATA_DIR) / run_id
    record = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "created_at": datetime.utcnow().isoformat(),
        **(origin or {}),
    }
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = run_dir / "origin.json.tmp"
        final_path = run_dir / "origin.json"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)
        os.replace(tmp_path, final_path)
    except OSError as exc:
        logger.warning(f"origin sidecar write failed for run {run_id}: {exc}")


def prepare_run(
    *,
    workflow_id: Optional[str] = None,
    definition: Optional[Dict[str, Any]] = None,
    seed: Dict[str, Any],
    origin: Dict[str, Any],
    engine: Optional[WorkflowEngine] = None,
):
    """Resolve → validate → checkpoint-placeholder → origin sidecar.

    Returns ``(defn, run_id)``. The caller hands the pair to
    ``dispatch_blocking`` (in a thread / BackgroundTask). Raises:
      * ``RunPrepareError`` (400)  — neither workflow_id nor definition given
      * ``WorkflowNotFound`` (404) — workflow_id has no on-disk file
      * ``WorkflowValidationError`` (422) — engine.validate rejected the defn
    """
    engine = engine or build_engine()

    if definition:
        # The branch the Composer Run ▶ live path depends on — main.js builds
        # {definition, seed} via dfBuildWorkflowDefinition and POSTs it.
        defn = engine.load_from_dict(definition)
    elif workflow_id:
        yaml_path = engine.resolve_workflow_path(workflow_id, WORKFLOWS_DIR)
        if not yaml_path:
            raise WorkflowNotFound(
                f"Workflow '{workflow_id}' not found in public or private overlay"
            )
        defn = engine.load(yaml_path)
    else:
        raise RunPrepareError("Provide either 'workflow_id' or 'definition'")

    # WorkflowValidationError propagates to the caller (router → 422).
    engine.validate(defn, seed_keys=list(seed.keys()) if seed else None)

    # Pre-create the run id + a "queued" checkpoint so the client can poll
    # /runs/{id} immediately. The engine would generate its own id otherwise;
    # we hand it in so the polling URL is stable.
    from ..models.workflow_models import WorkflowContext, WorkflowRun

    run_id = str(_uuid.uuid4())
    ctx = WorkflowContext(seed=dict(seed or {}))
    placeholder = WorkflowRun(
        run_id=run_id,
        workflow_id=defn.id,
        status="queued",
        context=ctx,
        started_at=datetime.utcnow(),
    )
    try:
        engine._checkpoint(placeholder)
    except Exception:
        pass

    _write_origin_sidecar(run_id, defn.id, origin)
    return defn, run_id


def dispatch_blocking(
    defn,
    seed: Dict[str, Any],
    run_id: str,
    engine: Optional[WorkflowEngine] = None,
) -> None:
    """Blocking engine.run() with the historical TypeError fallback preserved
    verbatim (workflows.py legacy handler). Intended to run on a worker thread."""
    engine = engine or build_engine()
    try:
        engine.run(defn, seed=seed, run_id=run_id)
    except TypeError:
        # Older engine signature without run_id kwarg — fall back and accept the
        # engine's auto-generated id. The pre-checkpoint placeholder is then
        # orphaned (harmless; cleanup elsewhere).
        engine.run(defn, seed=seed)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Background workflow run {run_id} failed: {e}")
