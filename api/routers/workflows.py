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
from ..exceptions import WorkflowValidationError, WorkflowExecutionError

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
        raise HTTPException(status_code=400, detail="invalid workflow id (alphanum/_/- only)")

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
        "path": str(target.relative_to(Path.cwd())) if target.is_relative_to(Path.cwd()) else str(target),
        "bytes": len(yaml_text),
    }


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
        raise HTTPException(status_code=404, detail=f"workflow '{workflow_id}' not found")
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return defn.model_dump(mode="json")
