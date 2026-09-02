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

Two sidecars sit next to the run checkpoint; the frozen engine is untouched:

  * data/workflows/<run_id>/origin.json      — who/what started the run.
  * data/workflows/<run_id>/definition.json  — the originating INLINE definition
    (Composer "Run ▶ live" only). An inline run has no workflows/<id>.yaml to
    reload from, so without this sidecar resume-from-failed / gate-resolve had
    nothing to rehydrate and 500'd after already flipping the run to
    ``running`` (a zombie). ``read_definition_sidecar`` is the resume-side
    reader; saved-yaml runs never write one. In-process
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


def _run_dir(run_id: str) -> Path:
    # Read DATA_DIR live off the engine module so the run root honours env /
    # test overrides — matching engine._checkpoint's own dynamic lookup.
    from ..services import workflow_engine as _we

    return Path(_we.DATA_DIR) / run_id


def write_definition_sidecar(run_id: str, definition: Dict[str, Any]) -> None:
    """Atomic tmp+replace write of data/workflows/<run_id>/definition.json.

    Persists the originating inline definition so an unsaved (Composer
    "Run ▶ live") run can be resumed later. Best-effort like the origin
    sidecar: a write failure logs and the run still executes — it just can't
    be Fix&Resume'd until the operator saves the workflow.
    """
    run_dir = _run_dir(run_id)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = run_dir / "definition.json.tmp"
        final_path = run_dir / "definition.json"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(definition, f, indent=2, default=str)
        os.replace(tmp_path, final_path)
    except OSError as exc:
        logger.warning(f"definition sidecar write failed for run {run_id}: {exc}")


def read_definition_sidecar(run_id: str) -> Optional[Dict[str, Any]]:
    """Return the persisted inline definition for ``run_id``, or ``None`` when
    the run was started from a saved yaml (no sidecar) or the file is
    unreadable. Malformed JSON is treated as absent (logged) — the caller
    decides how a missing definition surfaces."""
    path = _run_dir(run_id) / "definition.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning(f"definition sidecar unreadable for run {run_id}: {exc}")
        return None
    return data if isinstance(data, dict) else None


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
    if definition:
        # Inline runs keep their originating definition next to the checkpoint
        # so resume-from-failed can rehydrate them (there is no yaml to reload).
        write_definition_sidecar(run_id, definition)
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
