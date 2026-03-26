#!/usr/bin/env python3
"""
Completions Router - OpenAI-compatible text completion endpoints
"""

import json
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.ollama_service import OllamaService
from ..logging_config import logger

router = APIRouter(prefix="/v1", tags=["completions"])
ollama_service = OllamaService()


class CompletionRequest(BaseModel):
    """Text completion request"""

    model: str = Field(..., description="Model to use for completion")
    prompt: str = Field(..., description="Prompt for completion")
    temperature: Optional[float] = Field(0.7, description="Sampling temperature (0.0-2.0)")
    max_tokens: Optional[int] = Field(2048, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Stream the response")


@router.post("/completions")
async def completions(request: CompletionRequest):
    """OpenAI-compatible text completion endpoint"""
    logger.info(f"Completion request: model={request.model}, stream={request.stream}")

    # Handle streaming
    if request.stream:

        async def generate():
            """Generate streaming response in OpenAI format"""
            async for chunk_text in ollama_service.generate_stream(
                model=request.model,
                prompt=request.prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                chunk = {
                    "id": "cmpl-local",
                    "object": "text_completion.chunk",
                    "created": 0,
                    "model": request.model,
                    "choices": [
                        {
                            "text": chunk_text,
                            "index": 0,
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            final_chunk = {
                "id": "cmpl-local",
                "object": "text_completion.chunk",
                "created": 0,
                "model": request.model,
                "choices": [
                    {
                        "text": "",
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming — exceptions propagate to global handler
    result = ollama_service.generate(
        model=request.model,
        prompt=request.prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    return {
        "id": "cmpl-local",
        "object": "text_completion",
        "created": 0,
        "model": request.model,
        "choices": [
            {
                "text": result["response"],
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
            "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
        },
    }
