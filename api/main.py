#!/usr/bin/env python3
"""
Local AI Platform - FastAPI Server
OpenAI-compatible API for local LLM inference
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .routers import chat, completions, models
from .services.ollama_service import OllamaService

# Load environment variables
load_dotenv()

# Configuration
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_KEY = os.getenv("API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", '["*"]')

# Initialize services
ollama_service = OllamaService(OLLAMA_HOST)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the application"""
    print("🚀 Starting Local AI Platform API...")
    print(f"   Ollama Host: {OLLAMA_HOST}")
    print(f"   API Port: {API_PORT}")

    # Check Ollama health
    if ollama_service.health_check():
        print("   ✓ Ollama service is healthy")
    else:
        print("   ⚠ Warning: Ollama service is not responding")

    yield
    print("👋 Shutting down Local AI Platform API...")


# Initialize FastAPI app
app = FastAPI(
    title="Local AI Platform API",
    description="OpenAI-compatible API for local LLM inference with streaming support",
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
app.include_router(chat.router)
app.include_router(completions.router)
app.include_router(models.router)


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    ollama_healthy = ollama_service.health_check()

    return {
        "status": "healthy" if ollama_healthy else "degraded",
        "version": "1.0.0",
        "ollama_host": OLLAMA_HOST,
        "ollama_status": "healthy" if ollama_healthy else "unhealthy"
    }


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
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level="info"
    )
