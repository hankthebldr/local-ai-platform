"""
Workflow Router — API endpoints for multi-agent workflow management

Endpoints:
  GET  /api/workflows              — List available workflow definitions
  POST /api/workflows/validate     — Validate a workflow definition
  POST /api/workflows/run          — Execute a workflow with seed data
  POST /api/workflows/save         — Persist a definition as workflows/{id}.yaml
  GET  /api/workflows/runs         — List recent workflow runs
  GET  /api/workflows/runs/{id}    — Get a specific run's status and results
  GET  /api/workflows/runs/{id}/artifacts/{step_id} — Get a step's output
  GET  /api/workflows/{id}         — Full parsed WorkflowDefinition
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.workflow_engine import WorkflowEngine
from ..exceptions import WorkflowValidationError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")


def get_ollama_service() -> OllamaService:
    """Get or create OllamaService instance"""
    return OllamaService(OLLAMA_HOST)


def get_engine() -> WorkflowEngine:
    """Get or create WorkflowEngine instance"""
    return WorkflowEngine(get_ollama_service())


# ── Request/Response Models ────────────────────────────────────────────────


class WorkflowRunRequest(BaseModel):
    """Request to execute a workflow"""

    workflow_id: Optional[str] = None  # ID to load from workflows/ dir
    definition: Optional[Dict[str, Any]] = None  # inline definition
    seed: Dict[str, Any] = Field(default_factory=dict)


class WorkflowValidateRequest(BaseModel):
    """Request to validate a workflow definition"""

    definition: Dict[str, Any]
    seed_keys: Optional[List[str]] = None


class WorkflowSaveRequest(BaseModel):
    """Request to persist a workflow definition as YAML."""

    definition: Dict[str, Any]
    overwrite: bool = False  # explicit consent to clobber an existing file


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_workflows():
    """List all available workflow definitions from the workflows/ directory"""
    engine = get_engine()
    return engine.list_workflows(WORKFLOWS_DIR)


@router.post("/validate")
async def validate_workflow(req: WorkflowValidateRequest):
    """Validate a workflow definition without executing it"""
    engine = get_engine()
    try:
        defn = engine.load_from_dict(req.definition)
        engine.validate(defn, seed_keys=req.seed_keys)
        return {"valid": True, "workflow_id": defn.id, "steps": len(defn.steps)}
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/save")
async def save_workflow(req: WorkflowSaveRequest):
    """Persist a validated workflow definition to workflows/{id}.yaml.

    Used by the no-code composer's Save action. Validates the definition
    first; refuses to clobber an existing file unless overwrite=true. The
    workflow_id is taken from the definition payload itself (no path
    parameter, so traversal is structurally impossible).
    """
    engine = get_engine()
    # Validate before writing; engine.load_from_dict raises on bad input.
    try:
        defn = engine.load_from_dict(req.definition)
        engine.validate(defn)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Defense in depth: re-check the workflow id is filename-safe even
    # though Pydantic already enforced its shape.
    wf_id = defn.id
    if not wf_id or not all(c.isalnum() or c in "_-" for c in wf_id):
        raise HTTPException(
            status_code=400, detail="invalid workflow id (alphanum/_/- only)"
        )

    workflows_root = Path(WORKFLOWS_DIR).resolve()
    workflows_root.mkdir(parents=True, exist_ok=True)
    target = (workflows_root / f"{wf_id}.yaml").resolve()
    try:
        target.relative_to(workflows_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside workflows directory")

    if target.exists() and not req.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"workflow '{wf_id}' already exists; pass overwrite=true to replace",
        )

    # Round-trip through Pydantic so we serialize the validated, normalized
    # form rather than whatever shape the client sent.
    yaml_text = yaml.safe_dump(
        defn.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    target.write_text(yaml_text, encoding="utf-8")
    logger.info(f"Saved workflow '{wf_id}' to {target}")
    return {
        "saved": True,
        "workflow_id": wf_id,
        "path": (
            str(target.relative_to(Path.cwd()))
            if target.is_relative_to(Path.cwd())
            else str(target)
        ),
        "bytes": len(yaml_text),
    }


# ── Single-step ad-hoc test ──────────────────────────────────────────────


class StepTestRequest(BaseModel):
    """Run a single composer step against a free-form user prompt.

    The composer wires the dashboard chat input to this endpoint when a
    node is selected, so the operator can iterate on one step's
    `system_prompt` + `model`/`role` without saving + running the whole
    workflow. The request carries a step *definition* (not a step id) so
    unsaved canvas edits flow through unmodified.
    """

    step: Dict[str, Any]
    user_message: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@router.post("/test-step")
async def test_step(req: StepTestRequest):
    from ..services.model_resolver import ModelResolver
    from ..exceptions import APIError

    step = req.step or {}
    system_prompt = (step.get("system_prompt") or "").strip()
    if not system_prompt:
        raise HTTPException(
            status_code=400,
            detail="step.system_prompt is required for test-step",
        )

    ollama = get_ollama_service()
    resolver = ModelResolver(ollama)
    try:
        resolved_model = resolver.resolve(
            model=step.get("model") or None,
            role=step.get("role") or None,
            default_role="general",
        )
    except APIError:
        raise

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.user_message},
    ]
    temperature = req.temperature if req.temperature is not None else 0.7
    max_tokens = req.max_tokens if req.max_tokens is not None else 2048

    try:
        result = ollama.chat(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except APIError:
        raise

    response = {
        "step_id": step.get("id"),
        "model": resolved_model,
        "content": result.get("content", ""),
        "usage": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
            "total_tokens": (
                result.get("prompt_eval_count", 0) + result.get("eval_count", 0)
            ),
        },
    }
    # Surface model_fallback when the pinned model wasn't found (mirrors
    # /api/agents/{id}/chat shape so the dashboard can reuse its banner).
    pinned = step.get("model") or None
    if pinned and resolved_model != pinned:
        response["model_fallback"] = {
            "requested": pinned,
            "resolved": resolved_model,
            "reason": (
                f"Step's pinned model '{pinned}' is not installed. "
                f"Resolved to '{resolved_model}'. "
                f"Pull '{pinned}' for the step's preferred model."
            ),
        }
    return response


@router.post("/run")
async def run_workflow(req: WorkflowRunRequest, background_tasks: BackgroundTasks):
    """
    Execute a workflow with seed data.

    Provide either workflow_id (loads from workflows/ dir) or
    definition (inline YAML-equivalent dict).
    """
    engine = get_engine()

    # Load definition
    if req.definition:
        defn = engine.load_from_dict(req.definition)
    elif req.workflow_id:
        yaml_path = f"{WORKFLOWS_DIR}/{req.workflow_id}.yaml"
        defn = engine.load(yaml_path)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'workflow_id' or 'definition'",
        )

    # Validate
    try:
        engine.validate(defn, seed_keys=list(req.seed.keys()) if req.seed else None)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Execute synchronously (future: background task option)
    run = engine.run(defn, seed=req.seed)

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "started_at": str(run.started_at),
        "completed_at": str(run.completed_at),
        "step_results": [
            {
                "step_id": r.step_id,
                "status": r.status,
                "model_used": r.model_used,
                "duration_seconds": r.duration_seconds,
                "token_count": r.token_count,
                "retries": r.retries,
                "error": r.error,
            }
            for r in run.step_results
        ],
        # Expose the three-layer context so the UI can render a context
        # inspector (seed = immutable input, workspace = per-step outputs,
        # shared = cross-cutting state).
        "context": {
            "seed": run.context.seed,
            "workspace": run.context.workspace,
            "shared": run.context.shared,
        },
        "error": run.error,
    }


@router.post("/run-async")
async def run_workflow_async(
    req: WorkflowRunRequest, background_tasks: BackgroundTasks
):
    """
    Kick off a workflow run in the background and return the run_id
    immediately. The caller polls /api/workflows/runs/{run_id} to watch
    step-by-step progress as the engine checkpoints after every step.

    Use this when you want live UI updates. The sync /run endpoint is
    still the right call for short workflows that return quickly.
    """
    import uuid as _uuid
    from datetime import datetime as _dt
    from ..models.workflow_models import WorkflowRun, WorkflowContext

    engine = get_engine()

    if req.definition:
        defn = engine.load_from_dict(req.definition)
    elif req.workflow_id:
        yaml_path = f"{WORKFLOWS_DIR}/{req.workflow_id}.yaml"
        defn = engine.load(yaml_path)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'workflow_id' or 'definition'",
        )

    try:
        engine.validate(defn, seed_keys=list(req.seed.keys()) if req.seed else None)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Pre-create the run id + checkpoint a "queued" record so the client
    # can immediately poll /runs/{id}. The engine generates its own
    # internal run_id otherwise; we hand it in so the URL is stable.
    run_id = str(_uuid.uuid4())
    ctx = WorkflowContext(seed=dict(req.seed or {}))
    placeholder = WorkflowRun(
        run_id=run_id,
        workflow_id=defn.id,
        status="queued",
        context=ctx,
        started_at=_dt.utcnow(),
    )
    try:
        engine._checkpoint(placeholder)
    except Exception:
        pass

    def _run_in_background():
        from ..logging_config import logger as _logger

        try:
            engine.run(defn, seed=req.seed, run_id=run_id)
        except TypeError:
            # Older engine signature without run_id kwarg — fall back and
            # accept the engine's auto-generated id. The pre-checkpoint
            # placeholder is then orphaned (harmless; cleanup elsewhere).
            engine.run(defn, seed=req.seed)
        except Exception as e:
            _logger.error(f"Background workflow run {run_id} failed: {e}")

    background_tasks.add_task(_run_in_background)
    return {
        "run_id": run_id,
        "workflow_id": defn.id,
        "status": "queued",
        "poll_url": f"/api/workflows/runs/{run_id}",
    }


@router.get("/runs")
async def list_runs(limit: int = 20):
    """List recent workflow runs"""
    engine = get_engine()
    return engine.list_runs(limit=limit)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get full details of a specific workflow run"""
    engine = get_engine()
    run_data = engine.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run_data


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str):
    """
    Resume a checkpointed workflow run that was interrupted mid-flight.

    Idempotent for terminal runs (returns the existing snapshot unchanged).
    For runs left in "running" state by a crash, picks up at the first
    step that doesn't have a "completed" StepResult.
    """
    engine = get_engine()
    try:
        run = engine.resume(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "started_at": str(run.started_at),
        "completed_at": str(run.completed_at) if run.completed_at else None,
        "step_results": [
            {
                "step_id": r.step_id,
                "status": r.status,
                "model_used": r.model_used,
                "duration_seconds": r.duration_seconds,
                "token_count": r.token_count,
                "retries": r.retries,
                "error": r.error,
            }
            for r in run.step_results
        ],
        "context": {
            "seed": run.context.seed,
            "workspace": run.context.workspace,
            "shared": run.context.shared,
        },
        "error": run.error,
        "resumed": True,
    }


@router.get("/runs/{run_id}/artifacts/{step_id}")
async def get_artifact(run_id: str, step_id: str):
    """Get a specific step's output artifacts"""
    engine = get_engine()
    run_data = engine.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    workspace = run_data.get("context", {}).get("workspace", {})
    step_data = workspace.get(step_id)
    if not step_data:
        raise HTTPException(
            status_code=404,
            detail=f"No artifacts for step '{step_id}' in run '{run_id}'",
        )

    return {"step_id": step_id, "run_id": run_id, "outputs": step_data}


# NOTE: Dynamic catch-all route kept at the END so /runs, /validate, /run, etc
# match their static handlers first. Moving this up shadows /api/workflows/runs.
@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Return the full parsed WorkflowDefinition (steps, hooks, prompts).

    Used by the UI to render the hook/role chips on the pipeline. The
    list endpoint returns only summaries; this one returns everything.
    """
    if not workflow_id or not all(c.isalnum() or c in "_-" for c in workflow_id):
        raise HTTPException(status_code=400, detail="invalid workflow id")
    engine = get_engine()
    yaml_path = f"{WORKFLOWS_DIR}/{workflow_id}.yaml"
    try:
        defn = engine.load(yaml_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"workflow '{workflow_id}' not found"
        )
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return defn.model_dump(mode="json")
