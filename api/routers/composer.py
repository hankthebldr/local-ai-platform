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
