"""
Composer Router — chat-led workflow authoring.

  POST /api/composer/capture-spec  — chat thread -> editable {goal, inputs, checks}
  POST /api/composer/scaffold      — spec -> runnable WorkflowDefinition (hybrid:
                                      curated-template match, else local LLM plan)

Pre-execution authoring only. Reuses OllamaService + ModelResolver + the
workflow index; never imports the workflow engine. Auth follows the workflows
router convention (none by default — gate non-localhost exposure with
ENABLE_API_AUTH at the edge).
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import composer_draft_store as drafts
from ..services.ollama_service import OllamaService
from ..services.scaffold_planner import ScaffoldPlannerService
from ..services.spec_capture import SpecCaptureService

router = APIRouter(prefix="/api/composer", tags=["composer"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _ollama() -> OllamaService:
    return OllamaService(OLLAMA_HOST)


# ── request / response models ─────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class SpecInput(BaseModel):
    key: str
    description: str = ""


class CaptureSpecRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    model: Optional[str] = None
    role: Optional[str] = "reasoning"


class CaptureSpecResponse(BaseModel):
    goal: str
    inputs: List[SpecInput] = Field(default_factory=list)
    checks: List[str] = Field(default_factory=list)
    model: str


class ScaffoldRequest(BaseModel):
    goal: str
    inputs: List[SpecInput] = Field(default_factory=list)
    checks: List[str] = Field(default_factory=list)
    model: Optional[str] = None


class ScaffoldResponse(BaseModel):
    definition: Dict[str, Any]
    source: str  # "template" | "llm" | "fallback"
    matched_workflow_id: Optional[str] = None
    bindings: List[Dict[str, Any]] = Field(default_factory=list)


# ── endpoints ─────────────────────────────────────────────────────────
@router.post("/capture-spec", response_model=CaptureSpecResponse)
async def capture_spec(req: CaptureSpecRequest) -> CaptureSpecResponse:
    """Distill a chat thread into an editable workflow spec (local LLM)."""
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages is required")
    svc = SpecCaptureService(_ollama())
    data = svc.capture(
        [m.model_dump() for m in req.messages], model=req.model, role=req.role
    )
    return CaptureSpecResponse(**data)


@router.post("/scaffold", response_model=ScaffoldResponse)
async def scaffold(req: ScaffoldRequest) -> ScaffoldResponse:
    """Turn an (edited) spec into a runnable workflow definition."""
    if not req.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required")
    svc = ScaffoldPlannerService(_ollama())
    result = svc.scaffold(
        goal=req.goal,
        inputs=[i.model_dump() for i in req.inputs],
        checks=req.checks,
        model=req.model,
    )
    return ScaffoldResponse(**result)


# ── DR-1: durable draft store ─────────────────────────────────────────
# An in-progress Composer canvas is a *draft* — the lossless snapshot the
# frontend produces (dfEditor.export() + dfNodeData + dfNextId + dfSeedSchema
# + meta), keyed by a client-minted draft_id (uuid4 hex, distinct from the
# published workflow_id). Persisted VERBATIM: the store never validates the
# blob against the frozen workflow engine — a half-built canvas is exactly the
# state that must survive a reload, and it is not a runnable workflow.
#
# These are data-action WRITE routes; the whole /api/composer prefix is gated
# on the `workflows` scope via SCOPE_MAP (middleware.py), mirroring
# /api/workflows and /api/documents. Path containment + atomic writes live in
# composer_draft_store (charset allowlist + relative_to + tmp/os.replace).


class DraftSaveRequest(BaseModel):
    """Upsert a draft. ``blob`` is the opaque canvas snapshot (stored as-is)."""

    draft_id: str
    blob: Dict[str, Any] = Field(default_factory=dict)
    name: str = ""
    workflow_id: Optional[str] = None
    step_count: int = 0
    published: bool = False
    last_run_status: Optional[str] = None


class DraftPatchRequest(BaseModel):
    """Metadata-only edit — rename / relink / mark published / last-run dot.
    The canvas blob is never touched here."""

    name: Optional[str] = None
    workflow_id: Optional[str] = None
    published: Optional[bool] = None
    last_run_status: Optional[str] = None


def _draft_error(exc: Exception) -> HTTPException:
    if isinstance(exc, drafts.InvalidDraftId):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, drafts.DraftTooLarge):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    raise exc  # unexpected — let FastAPI surface a 500


@router.get("/drafts")
async def list_drafts() -> List[Dict[str, Any]]:
    """In-Progress rows (blob-free summaries), newest-edited first."""
    return drafts.list_drafts()


@router.post("/drafts")
async def save_draft(req: DraftSaveRequest) -> Dict[str, Any]:
    """Create or update a draft (upsert by draft_id). Returns the summary."""
    try:
        return drafts.save_draft(
            req.draft_id,
            blob=req.blob,
            name=req.name,
            workflow_id=req.workflow_id,
            step_count=req.step_count,
            published=req.published,
            last_run_status=req.last_run_status,
        )
    except (drafts.InvalidDraftId, drafts.DraftTooLarge) as e:
        raise _draft_error(e)


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str) -> Dict[str, Any]:
    """Full record INCLUDING the blob — the restore-on-open payload."""
    try:
        return drafts.get_draft(draft_id)
    except (drafts.InvalidDraftId, FileNotFoundError) as e:
        raise _draft_error(e)


@router.patch("/drafts/{draft_id}")
async def patch_draft(draft_id: str, req: DraftPatchRequest) -> Dict[str, Any]:
    """Rename / relink / mark published — metadata only, blob untouched."""
    try:
        return drafts.patch_draft(
            draft_id,
            name=req.name,
            workflow_id=req.workflow_id,
            published=req.published,
            last_run_status=req.last_run_status,
        )
    except (drafts.InvalidDraftId, FileNotFoundError) as e:
        raise _draft_error(e)


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: str) -> Dict[str, Any]:
    """Remove a draft (publish-freeze or explicit delete)."""
    try:
        return drafts.delete_draft(draft_id)
    except (drafts.InvalidDraftId, FileNotFoundError) as e:
        raise _draft_error(e)
