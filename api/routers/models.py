#!/usr/bin/env python3
"""
Models Router - OpenAI-compatible model listing endpoints
"""

from fastapi import APIRouter, HTTPException

from ..services.ollama_service import OllamaService

router = APIRouter(prefix="/v1", tags=["models"])
ollama_service = OllamaService()


@router.get("/models")
async def list_models():
    """
    List all available models in OpenAI format

    Returns:
        List of available models with metadata
    """
    try:
        ollama_models = ollama_service.list_models()

        # Convert to OpenAI format
        models = []
        for model in ollama_models:
            models.append({
                "id": model["name"],
                "object": "model",
                "created": 0,
                "owned_by": "local",
                "permission": [],
                "root": model["name"],
                "parent": None
            })

        return {
            "object": "list",
            "data": models
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing models: {str(e)}"
        )
