#!/usr/bin/env python3
"""
Chat Router - OpenAI-compatible chat completion endpoints

Uses Ollama's /api/chat for proper template handling (thinking models, etc.)
Supports optional web search augmentation via web_search parameter.
"""

import json
import uuid
from typing import Optional, List
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.ollama_service import OllamaService
from ..services import search_service
from ..services.memory_service import MemoryService
from .plugins import plugin_service as _plugin_service
from . import context as _context_router
from ..services.sandbox_fs import SandboxedFS
from . import profiles as _profiles_router
from . import documents as _documents_router
from ..services.tool_executor import ToolExecutor
from ..logging_config import logger

router = APIRouter(prefix="/v1", tags=["chat"])
ollama_service = OllamaService()
_tool_executor = ToolExecutor(ollama_service, _plugin_service)
_memory_service = MemoryService()


class Message(BaseModel):
    """Chat message"""

    role: str = Field(
        ..., description="Role of the message sender (system, user, assistant)"
    )
    content: str = Field(..., description="Content of the message")


class ChatCompletionRequest(BaseModel):
    """Chat completion request"""

    model: str = Field(..., description="Model to use for completion")
    messages: List[Message] = Field(..., description="List of messages")
    temperature: Optional[float] = Field(
        0.7, description="Sampling temperature (0.0-2.0)"
    )
    max_tokens: Optional[int] = Field(2048, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Stream the response")
    web_search: Optional[bool] = Field(
        False, description="Enable web search augmentation"
    )
    tools: Optional[bool] = Field(True, description="Enable plugin tool calling")
    max_tool_iterations: Optional[int] = Field(
        10, description="Max tool-call iterations"
    )
    rag: Optional[bool] = Field(
        False, description="Enable RAG retrieval for this request"
    )
    rag_top_k: Optional[int] = Field(5, description="Number of chunks to retrieve")


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest, req: Request):
    """OpenAI-compatible chat completion endpoint with optional web search"""
    logger.info(
        f"Chat request: model={request.model}, messages={len(request.messages)}, "
        f"stream={request.stream}, web_search={request.web_search}"
    )

    # ── Live singleton resolution ─────────────────────────────────────
    # Resolve shared module-level singletons at call time, not import time.
    # `from .documents import rag_service as _rag_service` binds the value as
    # it stood when chat.py was first imported; if documents / context /
    # profiles are reloaded or re-initialized (tests do this, and a runtime
    # re-init is possible), that copied binding goes stale. Reading the
    # attribute off the module object here re-resolves the current instance
    # on every request. See test_chat_rag_uses_live_rag_service.
    _context_store = _context_router.context_store
    _profile_service = _profiles_router.profile_service
    _rag_service = _documents_router.rag_service

    # ── Conversation Tracking ─────────────────────────────────────────
    conversation_id = req.headers.get("X-Conversation-ID", str(uuid.uuid4()))
    if not _context_store.get(conversation_id):
        _context_store.create(conversation_id, request.model)
    _context_store.update_activity(conversation_id)

    # ── Profile Resolution ────────────────────────────────────────────
    profile_header = req.headers.get("X-Profile-ID")
    profile_id = _profile_service.resolve(header=profile_header, key_id=None)
    ctx = _context_store.get(conversation_id)
    if ctx is not None:
        ctx.metadata["profile_id"] = profile_id

    # ── Sandbox Setup ────────────────────────────────────────────────
    profile = _profile_service.get_profile(profile_id) or {}
    sandbox_cfg = profile.get("sandbox") or {}
    sandbox = None
    if sandbox_cfg.get("mode") and sandbox_cfg["mode"] != "none":
        sandbox = SandboxedFS(
            sandbox_root=f"data/sandboxes/{conversation_id}",
            max_file_size_mb=sandbox_cfg.get("max_file_size_mb", 10),
            allowed_extensions=sandbox_cfg.get("allowed_extensions"),
        )

    # Convert Pydantic models to dicts for Ollama
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    # ── Memory Injection ──────────────────────────────────────────────
    memory_context = _memory_service.get_injection_context()
    if memory_context:
        messages = [{"role": "system", "content": memory_context}] + messages

    # ── Plugin Skill Injection ────────────────────────────────────────
    last_user_content = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            last_user_content = msg["content"]
            break

    matched_skills = _plugin_service.get_skills(last_user_content)
    for skill in matched_skills:
        _context_store.record_skill(conversation_id, skill.get("id", ""))
        if skill["inject"] == "system":
            messages = [{"role": "system", "content": skill["content"]}] + messages
        elif skill["inject"] == "context":
            messages.append({"role": "system", "content": skill["content"]})

    # ── RAG Augmentation ────────────────────────────────────────────
    rag_sources = []
    rag_allowed = True
    if request.rag:
        # Profile gate
        profile_rag = (profile.get("rag") or {}).get("enabled", True)
        if profile_rag is False:
            rag_allowed = False
            logger.info(f"RAG disabled by profile '{profile_id}'")
        elif _rag_service is None:
            rag_allowed = False
            logger.warning("RAG requested but rag_service is unavailable")

    if request.rag and rag_allowed:
        last_user_msg = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_msg = msg["content"]
                break
        if last_user_msg:
            results = _rag_service.search(last_user_msg, top_k=request.rag_top_k)
            if results["total"] > 0:
                messages = [
                    {"role": "system", "content": _rag_service.format_context(results)}
                ] + messages
                rag_sources = results["results"]
                logger.info(f"Injected {results['total']} RAG chunks")

    # ── Web Search Augmentation ────────────────────────────────────────
    sources = []
    if request.web_search:
        # Extract the last user message as the search query
        last_user_msg = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_msg = msg["content"]
                break

        if last_user_msg:
            logger.info(f"Web search triggered for: '{last_user_msg[:80]}...'")
            search_result = await search_service.search(last_user_msg)

            if search_result.results:
                # Format search results as a context system message
                context = search_service.format_search_context(
                    search_result.query, search_result.results
                )
                # Prepend search context as system message (don't mutate original history)
                messages = [{"role": "system", "content": context}] + messages

                # Collect sources for the response
                sources = [r.to_dict() for r in search_result.results]
                logger.info(
                    f"Injected {len(search_result.results)} search results "
                    f"from {search_result.backend}"
                )
            else:
                logger.warning(
                    f"Web search returned no results for: '{last_user_msg[:50]}'"
                )

    # ── Streaming ──────────────────────────────────────────────────────
    if request.stream:

        async def generate():
            """Generate streaming response in OpenAI SSE format"""
            from ..exceptions import APIError

            try:
                async for chunk_text in ollama_service.chat_stream(
                    model=request.model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                ):
                    chunk = {
                        "id": "chatcmpl-local",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": request.model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": chunk_text},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
            except APIError as e:
                # Once we've returned StreamingResponse, FastAPI has already
                # sent 200 headers — we can't re-issue a 4xx. Best we can
                # do is emit an OpenAI-shaped error event in the SSE stream
                # so the client surfaces the actual cause (e.g. embedding
                # model selected for chat) instead of silently truncating.
                logger.warning(f"Chat stream aborted: {e.message}")
                err_payload = {
                    "error": {
                        "message": e.message,
                        "type": e.error_type,
                        "code": e.code,
                    }
                }
                yield f"data: {json.dumps(err_payload)}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Emit sources as a custom event before DONE (if search was used)
            if sources:
                yield f"data: {json.dumps({'sources': sources})}\n\n"

            final_chunk = {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": request.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # ── Non-Streaming ──────────────────────────────────────────────────
    if request.tools and _plugin_service.get_ollama_tools():
        # Use tool executor for agentic loop
        _tool_executor.set_context(_context_store, conversation_id)
        _tool_executor.set_policy(_profile_service, profile_id, sandbox)
        result = _tool_executor.execute(
            model=request.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            max_iterations=request.max_tool_iterations,
        )

        response = {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": 0,
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result["content"]},
                    "finish_reason": (
                        "stop" if result["stopped_reason"] == "complete" else "length"
                    ),
                }
            ],
            "usage": {
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0),
                "total_tokens": result.get("prompt_eval_count", 0)
                + result.get("eval_count", 0),
            },
        }
        if result["tool_calls_made"]:
            response["tool_calls"] = result["tool_calls_made"]
        if sources:
            response["sources"] = sources
        response["conversation_id"] = conversation_id
        if request.rag or rag_sources:
            response["rag_sources"] = rag_sources
        response["profile_id"] = profile_id
        return response

    # ── Non-Streaming (no tools) ───────────────────────────────────────
    result = ollama_service.chat(
        model=request.model,
        messages=messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    response = {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "created": 0,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result["content"]},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
            "total_tokens": result.get("prompt_eval_count", 0)
            + result.get("eval_count", 0),
        },
    }
    if sources:
        response["sources"] = sources
    response["conversation_id"] = conversation_id
    if request.rag:
        response["rag_sources"] = rag_sources
    elif rag_sources:
        response["rag_sources"] = rag_sources
    response["profile_id"] = profile_id
    return response
