"""
Workflow Router — API endpoints for multi-agent workflow management

Endpoints:
  GET  /api/workflows                           — List available workflow definitions
  POST /api/workflows/validate                  — Validate + compile a workflow
  POST /api/workflows/compile                   — Compile and return execution plan
  POST /api/workflows/run                       — Execute a workflow with seed data
  GET  /api/workflows/runs                      — List recent workflow runs
  GET  /api/workflows/runs/{id}                 — Get a specific run's details
  GET  /api/workflows/runs/{id}/artifacts/{sid} — Get a step's output
  GET  /api/workflows/runs/{id}/events          — Get execution events for a run
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.workflow_engine import WorkflowEngine
from ..services.workflow_events import WorkflowEventBus
from ..exceptions import WorkflowValidationError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")

# Module-level singletons — avoids per-request creation, preserves cache
_event_bus = WorkflowEventBus()
_engine: Optional["WorkflowEngine"] = None


def get_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine(OllamaService(OLLAMA_HOST), event_bus=_event_bus)
    return _engine


# ── Request/Response Models ──────────────────────────────────────────────


class WorkflowRunRequest(BaseModel):
    workflow_id: Optional[str] = None
    definition: Optional[Dict[str, Any]] = None
    seed: Dict[str, Any] = Field(default_factory=dict)
    resume_from: Optional[str] = None


class WorkflowValidateRequest(BaseModel):
    definition: Dict[str, Any]
    seed_keys: Optional[List[str]] = None


class WorkflowCompileRequest(BaseModel):
    definition: Optional[Dict[str, Any]] = None
    workflow_id: Optional[str] = None
    seed_keys: Optional[List[str]] = None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("")
async def list_workflows():
    """List all available workflow definitions with execution plan metadata"""
    engine = get_engine()
    return engine.list_workflows(WORKFLOWS_DIR)


@router.post("/validate")
async def validate_workflow(req: WorkflowValidateRequest):
    """Validate and compile a workflow definition without executing"""
    engine = get_engine()
    try:
        defn = engine.load_from_dict(req.definition)
        plan = engine.compile(defn, seed_keys=req.seed_keys)
        parallelism = engine.compiler.analyze_parallelism(plan)
        return {
            "valid": True,
            "workflow_id": defn.id,
            "steps": len(defn.steps),
            "execution_plan": plan.model_dump(),
            "parallelism": parallelism,
        }
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/compile")
async def compile_workflow(req: WorkflowCompileRequest):
    """Compile a workflow and return the execution plan (DAG analysis)"""
    engine = get_engine()

    if req.definition:
        defn = engine.load_from_dict(req.definition)
    elif req.workflow_id:
        defn = engine.load(f"{WORKFLOWS_DIR}/{req.workflow_id}.yaml")
    else:
        raise HTTPException(status_code=400, detail="Provide workflow_id or definition")

    try:
        plan = engine.compile(defn, seed_keys=req.seed_keys)
        parallelism = engine.compiler.analyze_parallelism(plan)
        return {
            "workflow_id": defn.id,
            "name": defn.name,
            "execution_plan": plan.model_dump(),
            "parallelism_analysis": parallelism,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "role": s.role,
                    "model": s.model,
                    "depends_on": s.depends_on,
                    "inputs": s.inputs,
                    "outputs": s.outputs,
                    "has_condition": s.condition is not None or len(s.conditions) > 0,
                    "has_loop": s.loop is not None,
                    "has_gates": len(s.quality_gates) > 0,
                    "output_format": s.output_parser.format.value,
                    "tags": s.tags,
                }
                for s in defn.steps
            ],
        }
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/run")
async def run_workflow(req: WorkflowRunRequest):
    """Execute a workflow with seed data"""
    engine = get_engine()

    if req.definition:
        defn = engine.load_from_dict(req.definition)
    elif req.workflow_id:
        defn = engine.load(f"{WORKFLOWS_DIR}/{req.workflow_id}.yaml")
    else:
        raise HTTPException(status_code=400, detail="Provide workflow_id or definition")

    # run() internally compiles (validates) — no need to validate separately
    try:
        run = engine.run(defn, seed=req.seed, resume_from=req.resume_from)
    except WorkflowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "status": run.status.value,
        "started_at": str(run.started_at),
        "completed_at": str(run.completed_at),
        "total_tokens": run.total_tokens,
        "total_duration": run.total_duration,
        "execution_plan": run.execution_plan.model_dump() if run.execution_plan else None,
        "step_results": [
            {
                "step_id": r.step_id,
                "status": r.status.value,
                "model_used": r.model_used,
                "duration_seconds": r.duration_seconds,
                "token_count": r.token_count,
                "cached": r.cached,
                "retries": r.retries,
                "gate_results": r.gate_results,
                "error": r.error,
            }
            for r in run.step_results
        ],
        "checkpoints": run.checkpoints,
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


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, event_type: Optional[str] = None, limit: int = 100):
    """Get execution events for a specific run"""
    events = _event_bus.get_history(run_id=run_id, event_type=event_type, limit=limit)
    return [
        {
            "event_type": e.event_type,
            "step_id": e.step_id,
            "timestamp": str(e.timestamp),
            "data": e.data,
        }
        for e in events
    ]


class WorkflowSaveRequest(BaseModel):
    workflow_id: str
    yaml_content: str


@router.post("/save")
async def save_workflow(req: WorkflowSaveRequest):
    """Save a workflow YAML file to the workflows/ directory"""
    import re
    # Sanitize ID for filesystem safety
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '-', req.workflow_id)
    filepath = os.path.join(WORKFLOWS_DIR, f"{safe_id}.yaml")

    # Validate the YAML parses correctly
    import yaml
    try:
        parsed = yaml.safe_load(req.yaml_content)
        engine = get_engine()
        defn = engine.load_from_dict(parsed)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid workflow YAML: {e}")

    # Write to disk
    os.makedirs(WORKFLOWS_DIR, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(req.yaml_content)

    return {"saved": True, "path": filepath, "workflow_id": defn.id, "steps": len(defn.steps)}
