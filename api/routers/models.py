#!/usr/bin/env python3
"""
Models Router - OpenAI-compatible model listing endpoints
"""

from fastapi import APIRouter

from ..services.ollama_service import OllamaService
from ..logging_config import logger

router = APIRouter(prefix="/v1", tags=["models"])
ollama_service = OllamaService()


@router.get("/models")
async def list_models():
    """List all available models in OpenAI format"""
    logger.info("Listing models")

    # Exceptions propagate to global handler
    ollama_models = ollama_service.list_models()

    models = []
    for model in ollama_models:
        models.append(
            {
                "id": model["name"],
                "object": "model",
                "created": 0,
                # Backend attribution rides the OpenAI-spec field: "ollama"
                # or "vllm" (the merged list marks vLLM entries with a
                # `runner` key). Clients that don't care still see a string.
                "owned_by": model.get("runner", "ollama"),
                "permission": [],
                "root": model["name"],
                "parent": None,
            }
        )

    return {"object": "list", "data": models}
