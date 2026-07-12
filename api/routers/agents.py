"""
Agents Router — API endpoints for custom agent / gem management

Endpoints:
  GET    /api/agents                    — List all agents
  GET    /api/agents/{agent_id}         — Get agent definition
  POST   /api/agents                    — Create a new agent
  PUT    /api/agents/{agent_id}         — Update an agent
  DELETE /api/agents/{agent_id}         — Delete an agent
  POST   /api/agents/{agent_id}/chat    — Chat with an agent
  GET    /api/agents/{agent_id}/context — Preview resolved context
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..exceptions import APIError
from ..logging_config import logger
from ..models.agent_models import AgentDefinition
from ..services.agent_service import AgentService
from ..services.model_resolver import ModelResolver
from ..services.ollama_service import OllamaService

router = APIRouter(prefix="/api/agents", tags=["agents"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
AGENTS_DIR = os.getenv("AGENTS_DIR", "./agents")

# Module-level singletons — avoids per-request creation
_service: Optional[AgentService] = None
_ollama: Optional[OllamaService] = None
_resolver: Optional[ModelResolver] = None


def get_service() -> AgentService:
    global _service
    if _service is None:
        _service = AgentService(AGENTS_DIR)
    return _service


def get_ollama() -> OllamaService:
    global _ollama
    if _ollama is None:
        _ollama = OllamaService(OLLAMA_HOST)
    return _ollama


def get_resolver() -> ModelResolver:
    global _resolver
    if _resolver is None:
        _resolver = ModelResolver(get_ollama())
    return _resolver


# ── Request/Response Models ──────────────────────────────────────────────


class AgentChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("")
async def list_agents():
    """List all available agent definitions"""
    service = get_service()
    return service.list_agents()


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get a specific agent definition"""
    service = get_service()
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent.model_dump(mode="json")


@router.post("")
async def create_agent(defn: AgentDefinition):
    """Create a new agent from a definition"""
    service = get_service()

    # Check if agent already exists
    existing = service.get_agent(defn.id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{defn.id}' already exists. Use PUT to update.",
        )

    try:
        path = service.create_agent(defn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "created", "agent_id": defn.id, "path": path}


@router.put("/{agent_id}")
async def update_agent(agent_id: str, defn: AgentDefinition):
    """Update an existing agent definition"""
    service = get_service()
    try:
        success = service.update_agent(agent_id, defn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not success:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return {"status": "updated", "agent_id": agent_id}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent definition"""
    service = get_service()
    success = service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return {"status": "deleted", "agent_id": agent_id}


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: str, body: AgentChatRequest, http_req: Request):
    """Chat with an agent — resolves the model, builds messages, and executes
    through the SAME /v1/chat/completions pipeline as the main chat surface
    (GP-2 commit 5).

    The old path called ``ollama.chat`` directly, which meant an agent's tools
    never ran and its ``web_search`` builtin was a silent no-op — the agent's
    declared capabilities were ignored at chat time. Routing through
    ``chat_completions`` executes plugin tools (agentic loop), honors
    ``web_search`` when the agent declares it, and surfaces OpenAI-shaped
    errors (APIError bubbles through the shared handler) instead of generic
    500s.
    """
    service = get_service()
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # Resolve model. APIError subclasses (ModelNotFoundError,
    # ModelResolutionError, InvalidRequestError, OllamaConnectionError)
    # already carry the correct status code + OpenAI-shaped body, so let
    # them bubble through the api_error_handler instead of swallowing
    # them as generic 500s.
    resolver = get_resolver()
    try:
        resolved_model = resolver.resolve(
            model=agent.model,
            role=agent.role,
            default_role="general",
        )
    except APIError:
        raise
    except Exception as e:
        logger.error(f"Unexpected model-resolution error for agent {agent_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Model resolution failed: {e}",
        )

    # Whether we fell back from the agent's pinned model.
    fell_back = bool(agent.model and resolved_model != agent.model)

    # Build messages with system prompt + context.
    messages = service.build_messages(agent, body.messages)

    # Use request overrides or agent defaults.
    temperature = body.temperature if body.temperature is not None else agent.temperature
    max_tokens = body.max_tokens if body.max_tokens is not None else agent.max_tokens

    # The agent opts into web search when it declares the built-in web_search
    # tool. Tool execution (plugin agentic loop) is always enabled — the /v1
    # path runs the registered plugin tools when the model requests them.
    wants_web_search = any(
        getattr(t, "type", None) == "web_search" for t in (agent.tools or [])
    )

    from .chat import ChatCompletionRequest, Message, chat_completions

    cc_request = ChatCompletionRequest(
        model=resolved_model,
        messages=[Message(role=m["role"], content=m.get("content", "")) for m in messages],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        web_search=wants_web_search,
        tools=True,
    )
    try:
        completion = await chat_completions(cc_request, http_req)
    except APIError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected chat error for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")

    choice = (completion.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")

    response = {
        "agent_id": agent_id,
        "model": resolved_model,
        "content": content,
        "usage": completion.get("usage", {}),
    }
    # Surface the grounding + tool trail so the agent chat pane can render
    # citations / tool badges, same as the main chat.
    for extra in ("sources", "tool_calls", "provenance", "conversation_id"):
        if extra in completion:
            response[extra] = completion[extra]
    if fell_back:
        response["model_fallback"] = {
            "requested": agent.model,
            "resolved": resolved_model,
            "reason": (
                f"Agent's pinned model '{agent.model}' is not installed. "
                f"Resolved via role '{agent.role}' to '{resolved_model}'. "
                f"Pull '{agent.model}' for the agent's preferred model."
            ),
        }
    return response


@router.get("/{agent_id}/context")
async def preview_context(agent_id: str):
    """Preview the resolved context for an agent"""
    service = get_service()
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    resolved = service.resolve_context(agent)
    return {
        "agent_id": agent_id,
        "context_sources": len(resolved),
        "context": resolved,
    }


# ── Doc → Agent generator ────────────────────────────────────────────────
# Imports kept inline so the project-formatter (ruff/isort) doesn't strip
# them as "unused" between edit passes — they're consumed below.
from ..models.project_models import (  # noqa: E402
    AgentEvaluationRequest,
    AgentGenerationRequest,
)
from ..services.agent_generator import AgentGenerator  # noqa: E402
from ..logging_config import logger as _gen_logger  # noqa: E402

_generator: Optional[AgentGenerator] = None


def get_generator() -> AgentGenerator:
    global _generator
    if _generator is None:
        _generator = AgentGenerator(get_ollama())
    return _generator


class AgentDraftSaveRequest(BaseModel):
    draft: Dict[str, Any]
    overwrite: bool = False


@router.post("/generate")
async def generate_agent(req: AgentGenerationRequest):
    """Produce a draft agent definition from a document or pasted text."""
    if not req.document_id and not req.text:
        raise HTTPException(
            status_code=400, detail="provide either document_id or text"
        )
    gen = get_generator()
    try:
        if req.document_id:
            result = gen.generate_from_document(
                req.document_id,
                name_hint=req.name_hint,
                role_hint=req.role_hint,
                model=req.model,
            )
        else:
            result = gen.generate_from_text(
                req.text or "",
                name_hint=req.name_hint,
                role_hint=req.role_hint,
                model=req.model,
                include_source_as_context=req.include_source_as_context,
            )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="document not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        _gen_logger.warning("Agent generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return result.model_dump(mode="json")


@router.post("/generate/save")
async def save_generated_agent(body: AgentDraftSaveRequest):
    """Persist a (possibly user-edited) draft agent."""
    try:
        path = get_generator().save_draft(body.draft, overwrite=body.overwrite)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"agent '{exc}' already exists; pass overwrite=true to replace",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"saved": True, "path": path, "agent_id": body.draft.get("id")}


@router.post("/{agent_id}/evaluate")
async def evaluate_agent(agent_id: str, req: AgentEvaluationRequest):
    """Run an agent against a list of {prompt, expected_contains} cases."""
    if not req.cases:
        raise HTTPException(status_code=400, detail="at least one case required")
    try:
        report = get_generator().evaluate_agent(agent_id, req.cases)
    except KeyError:
        raise HTTPException(status_code=404, detail="agent not found")
    return report.model_dump(mode="json")
