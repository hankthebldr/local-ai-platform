#!/usr/bin/env python3
"""
Chat Router - OpenAI-compatible chat completion endpoints

Uses Ollama's /api/chat for proper template handling (thinking models, etc.)
Supports optional web search augmentation via web_search parameter.
"""

import json
from typing import Optional, List
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.ollama_service import OllamaService
from ..services import search_service
from .plugins import plugin_service as _plugin_service
from ..logging_config import logger

router = APIRouter(prefix="/v1", tags=["chat"])
ollama_service = OllamaService()


class Message(BaseModel):
    """Chat message"""

    role: str = Field(..., description="Role of the message sender (system, user, assistant)")
    content: str = Field(..., description="Content of the message")


class ChatCompletionRequest(BaseModel):
    """Chat completion request"""

    model: str = Field(..., description="Model to use for completion")
    messages: List[Message] = Field(..., description="List of messages")
    temperature: Optional[float] = Field(0.7, description="Sampling temperature (0.0-2.0)")
    max_tokens: Optional[int] = Field(2048, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Stream the response")
    web_search: Optional[bool] = Field(False, description="Enable web search augmentation")


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completion endpoint with optional web search"""
    logger.info(
        f"Chat request: model={request.model}, messages={len(request.messages)}, "
        f"stream={request.stream}, web_search={request.web_search}"
    )

    # Convert Pydantic models to dicts for Ollama
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    # ── Plugin Skill Injection ────────────────────────────────────────
    last_user_content = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            last_user_content = msg["content"]
            break

    matched_skills = _plugin_service.get_skills(last_user_content)
    for skill in matched_skills:
        if skill["inject"] == "system":
            messages = [{"role": "system", "content": skill["content"]}] + messages
        elif skill["inject"] == "context":
            messages.append({"role": "system", "content": skill["content"]})

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
                logger.warning(f"Web search returned no results for: '{last_user_msg[:50]}'")

    # ── Streaming ──────────────────────────────────────────────────────
    if request.stream:

        async def generate():
            """Generate streaming response in OpenAI SSE format"""
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
            "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
        },
    }

    # Attach sources if search was used
    if sources:
        response["sources"] = sources

    return response
