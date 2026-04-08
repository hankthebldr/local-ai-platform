#!/usr/bin/env python3
"""
Local AI Platform - FastAPI Server
OpenAI-compatible API for local LLM inference
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Import routers
try:
    from api.routers import skills
    SKILLS_ROUTER_AVAILABLE = True
except ImportError:
    SKILLS_ROUTER_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configuration
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_KEY = os.getenv("API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", '["*"]')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the application"""
    print("🚀 Starting Local AI Platform API...")
    print(f"   Ollama Host: {OLLAMA_HOST}")
    print(f"   API Port: {API_PORT}")
    yield
    print("👋 Shutting down Local AI Platform API...")


# Initialize FastAPI app
app = FastAPI(
    title="Local AI Platform API",
    description="OpenAI-compatible API for local LLM inference",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
if SKILLS_ROUTER_AVAILABLE:
    app.include_router(skills.router)


# Models
class Message(BaseModel):
    role: str = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Content of the message")


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Model to use for completion")
    messages: list[Message] = Field(..., description="List of messages")
    temperature: Optional[float] = Field(0.7, description="Sampling temperature")
    max_tokens: Optional[int] = Field(2048, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Stream the response")


class CompletionRequest(BaseModel):
    model: str = Field(..., description="Model to use for completion")
    prompt: str = Field(..., description="Prompt for completion")
    temperature: Optional[float] = Field(0.7, description="Sampling temperature")
    max_tokens: Optional[int] = Field(2048, description="Maximum tokens to generate")
    stream: Optional[bool] = Field(False, description="Stream the response")


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "ollama_host": OLLAMA_HOST
    }


# List models
@app.get("/v1/models")
async def list_models():
    """List available models"""
    try:
        import requests
        response = requests.get(f"{OLLAMA_HOST}/api/tags")
        response.raise_for_status()
        ollama_models = response.json().get("models", [])

        # Convert to OpenAI format
        models = []
        for model in ollama_models:
            models.append({
                "id": model["name"],
                "object": "model",
                "created": 0,
                "owned_by": "local"
            })

        return {
            "object": "list",
            "data": models
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing models: {str(e)}")


# Chat completion endpoint
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completion endpoint"""
    try:
        import requests

        # Format messages for Ollama
        prompt = ""
        for msg in request.messages:
            if msg.role == "system":
                prompt += f"System: {msg.content}\n\n"
            elif msg.role == "user":
                prompt += f"User: {msg.content}\n\n"
            elif msg.role == "assistant":
                prompt += f"Assistant: {msg.content}\n\n"

        prompt += "Assistant:"

        # Call Ollama API
        ollama_request = {
            "model": request.model,
            "prompt": prompt,
            "temperature": request.temperature,
            "stream": False,
            "options": {
                "num_predict": request.max_tokens
            }
        }

        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=ollama_request,
            timeout=300
        )
        response.raise_for_status()
        result = response.json()

        # Convert to OpenAI format
        return {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "created": 0,
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result["response"]
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating completion: {str(e)}")


# Text completion endpoint
@app.post("/v1/completions")
async def completions(request: CompletionRequest):
    """OpenAI-compatible text completion endpoint"""
    try:
        import requests

        # Call Ollama API
        ollama_request = {
            "model": request.model,
            "prompt": request.prompt,
            "temperature": request.temperature,
            "stream": False,
            "options": {
                "num_predict": request.max_tokens
            }
        }

        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=ollama_request,
            timeout=300
        )
        response.raise_for_status()
        result = response.json()

        # Convert to OpenAI format
        return {
            "id": "cmpl-local",
            "object": "text_completion",
            "created": 0,
            "model": request.model,
            "choices": [{
                "text": result["response"],
                "index": 0,
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating completion: {str(e)}")


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Local AI Platform API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "completions": "/v1/completions",
            "models": "/v1/models"
        }
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level="info"
    )
