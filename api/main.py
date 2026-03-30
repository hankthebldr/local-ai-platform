#!/usr/bin/env python3
"""
Local AI Platform - FastAPI Server
OpenAI-compatible API for local LLM inference
"""

import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from .routers import chat, completions, models, inventory
from .services.ollama_service import OllamaService
from .middleware import APIKeyAuthMiddleware, RateLimitMiddleware
from .exceptions import register_exception_handlers
from .logging_config import logger

# Load environment variables
load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))

# Parse CORS origins from env (supports JSON array string)
_cors_raw = os.getenv("CORS_ORIGINS", '["*"]')
try:
    CORS_ORIGINS = json.loads(_cors_raw)
except (json.JSONDecodeError, TypeError):
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# ── Services ───────────────────────────────────────────────────────────────

ollama_service = OllamaService(OLLAMA_HOST)


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the application"""
    auth_status = "enabled" if os.getenv("ENABLE_API_AUTH", "false").lower() == "true" else "disabled"
    logger.info("Starting Local AI Platform API")
    logger.info(f"  Ollama Host: {OLLAMA_HOST}")
    logger.info(f"  API Port: {API_PORT}")
    logger.info(f"  Auth: {auth_status}")
    logger.info(f"  CORS Origins: {CORS_ORIGINS}")
    logger.info(f"  Rate Limit: {os.getenv('RATE_LIMIT_RPM', '60')} rpm")
    logger.info(f"  Request Timeout: {REQUEST_TIMEOUT}s")

    if ollama_service.health_check():
        model_list = ollama_service.list_models()
        logger.info(f"  Ollama: healthy ({len(model_list)} models loaded)")
    else:
        logger.warning("  Ollama: NOT responding")

    yield
    logger.info("Shutting down Local AI Platform API")


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Local AI Platform API",
    description="OpenAI-compatible API for local LLM inference with streaming support",
    version="1.0.0",
    lifespan=lifespan,
)

# Register exception handlers (must come before middleware)
register_exception_handlers(app)

# Middleware (order matters: last added = first executed)
# 1. Rate limiting runs first
app.add_middleware(RateLimitMiddleware)

# 2. Auth runs second
app.add_middleware(APIKeyAuthMiddleware)

# 3. CORS runs last (outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router)
app.include_router(completions.router)
app.include_router(models.router)
app.include_router(inventory.router)


# ── Public Endpoints ───────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint with system metrics"""
    import psutil

    ollama_healthy = ollama_service.health_check()
    model_count = 0
    model_names = []
    if ollama_healthy:
        try:
            models = ollama_service.list_models()
            model_count = len(models)
            model_names = [m["name"] for m in models]
        except Exception:
            pass

    mem = psutil.virtual_memory()

    return {
        "status": "healthy" if ollama_healthy else "degraded",
        "version": "1.0.0",
        "ollama": {
            "host": OLLAMA_HOST,
            "status": "healthy" if ollama_healthy else "unhealthy",
            "models_loaded": model_count,
            "models": model_names,
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": round(mem.total / (1024**3), 1),
            "memory_used_gb": round(mem.used / (1024**3), 1),
            "memory_percent": mem.percent,
        },
    }


# ── Dashboard & Static Files ──────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
@app.head("/")
async def root():
    """Serve the HTML dashboard"""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    # Fallback to JSON if static files missing
    return {
        "message": "Local AI Platform API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/api/info")
async def api_info():
    """JSON API information endpoint"""
    return {
        "message": "Local AI Platform API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "completions": "/v1/completions",
            "models": "/v1/models",
        },
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
