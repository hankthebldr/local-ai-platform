#!/usr/bin/env python3
"""
Enclave - FastAPI Server
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

from . import __version__
from .routers import (
    chat,
    completions,
    models,
    inventory,
    exports,
    graph,
    workflows,
    workflow_index,
    api_keys,
    plugins,
    mcp,
    cloud_providers,  # noqa: F401 — used below via app.include_router
    setup,
    context,
    memory,
    profiles,
    documents,
    roles,
    a2a,
    agents,
    feedback,  # noqa: F401 — used below via app.include_router
    skills,  # noqa: F401 — used below via app.include_router
    discover,  # noqa: F401 — used below via app.include_router
    system,  # noqa: F401 — architecture-aware orchestration (Phase 1)
)
from .services.ollama_service import OllamaService
from .services.workflow_engine import WorkflowEngine
from .services.a2a_service import A2AService
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
_workflow_engine = WorkflowEngine(ollama_service)
a2a.init_a2a_service(A2AService(ollama_service, _workflow_engine))


# ── Lifespan ───────────────────────────────────────────────────────────────

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _is_network_exposed(host: str) -> bool:
    return host not in _LOOPBACK_HOSTS


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the application"""
    # Default-on auth: 1.x ships with ENABLE_API_AUTH=true. Fresh installs
    # auto-provision a master key on first boot (see _bootstrap_auth_if_needed).
    auth_enabled = os.getenv("ENABLE_API_AUTH", "true").lower() == "true"
    auth_status = "enabled" if auth_enabled else "disabled"
    logger.info("Starting Enclave API")
    logger.info(f"  Ollama Host: {OLLAMA_HOST}")
    logger.info(f"  API Host: {API_HOST}")
    logger.info(f"  API Port: {API_PORT}")
    logger.info(f"  Auth: {auth_status}")
    logger.info(f"  CORS Origins: {CORS_ORIGINS}")
    logger.info(f"  Rate Limit: {os.getenv('RATE_LIMIT_RPM', '60')} rpm")
    logger.info(f"  Request Timeout: {REQUEST_TIMEOUT}s")

    if auth_enabled:
        _bootstrap_auth_if_needed()
    else:
        # Auth off is now an explicit override (dev mode only). Warn loudly,
        # and louder still when the override coincides with a network-exposed
        # bind — that combination would expose workflows, document ingestion,
        # and key management endpoints unauthenticated.
        if _is_network_exposed(API_HOST):
            logger.warning(
                "SECURITY: API_HOST=%s is network-exposed but ENABLE_API_AUTH=false. "
                "Workflow execution, document ingestion, and key management endpoints "
                "are unauthenticated. Remove the override before exposing this service.",
                API_HOST,
            )
        else:
            logger.warning(
                "SECURITY: ENABLE_API_AUTH=false — every endpoint is unauthenticated. "
                "This is dev mode only; remove the override before exposing the API."
            )
    if "*" in CORS_ORIGINS:
        logger.warning(
            "SECURITY: CORS_ORIGINS contains '*' — any browser origin can call "
            "this API. Restrict CORS_ORIGINS before exposing this service."
        )

    if ollama_service.health_check():
        model_list = ollama_service.list_models()
        logger.info(f"  Ollama: healthy ({len(model_list)} models loaded)")
    else:
        logger.warning("  Ollama: NOT responding")

    # ── Architecture-aware orchestration detection (Phase 1) ────────────
    try:
        from .services.deployment import detect_deployment
        from .services.architecture import detect_architecture, probe_ollama_version

        strict_arch = os.getenv("STRICT_ARCH_DETECTION", "false").lower() == "true"
        deployment = detect_deployment()
        arch = detect_architecture(strict=strict_arch)
        ollama_probe = probe_ollama_version(strict=strict_arch)

        logger.info("=" * 64)
        logger.info("Architecture-aware orchestration:")
        logger.info(
            "  🧠 Architecture: %s (%s, %.1f GB, %d pool%s)",
            arch.name.value,
            arch.memory_model,
            arch.total_memory_gb,
            arch.pool_count,
            "s" if arch.pool_count != 1 else "",
        )
        logger.info(
            "  📦 Deployment:   %s (storage=%s)",
            deployment.mode.value,
            deployment.storage_root,
        )
        logger.info(
            "  🦙 Ollama:       %s (reachable=%s, meets_floor=%s, floor=%s)",
            ollama_probe.get("version") or "unreachable",
            ollama_probe.get("reachable"),
            ollama_probe.get("meets_floor"),
            ollama_probe.get("floor"),
        )
        if hasattr(arch, "gpus") and arch.gpus:
            for g in arch.gpus:
                logger.info(
                    "    GPU %d: %s (%.0f GB VRAM, PCIe gen %s)",
                    g.get("gpu_id", 0),
                    g.get("name", "?"),
                    g.get("vram_total_gb", 0),
                    g.get("pcie_gen", "?"),
                )
        logger.info("=" * 64)

        # Ensure user storage exists (idempotent)
        try:
            deployment.ensure_user_storage()
        except Exception as e:
            logger.warning("ensure_user_storage failed: %s", e)
    except Exception as e:
        logger.warning("Architecture detection failed: %s", e)
        logger.warning(
            "Architecture-aware features will run in degraded mode. "
            "See docs/plans/2026-05-19-architecture-aware-orchestration-design.md"
        )

    # ── Inference runner detection (gpu-runner-abstraction Phase 3) ──────
    # Builds the RunnerRegistry: Ollama always, vLLM when ENCLAVE_VLLM_BASE_URLS
    # is set. On the BD790i Blackwell host, vLLM (NVFP4 + continuous batching)
    # is the performance path; Ollama stays as the universal fallback.
    try:
        from .services.runner_detection import detect_runners

        strict_runner = os.getenv("STRICT_RUNNER_DETECTION", "false").lower() == "true"
        registry = detect_runners(ollama_service=ollama_service, strict=strict_runner)
        logger.info(
            "  🚀 Runners:      %s%s",
            sorted(k.value for k in registry.kinds()),
            (
                f" (preferred: {registry.preferred_runner.value})"
                if getattr(registry, "preferred_runner", None)
                else ""
            ),
        )
    except Exception as e:
        logger.warning("Runner detection failed: %s", e)
        logger.warning(
            "Inference runner registry unavailable; chat/completions still use "
            "the OllamaService direct path. See docs/deployment/vllm-backend.md"
        )

    yield
    logger.info("Shutting down Enclave API")


def _bootstrap_auth_if_needed() -> None:
    """
    On first boot with auth enabled, provision a master key and write the
    raw value to data/config/first-run-key.txt (chmod 0600). Subsequent
    boots are no-ops (the keystore won't be empty).

    The raw key is logged ONCE here — never persisted in the YAML, never
    retrievable later. Operators can find it in:
      1. The startup log banner below
      2. data/config/first-run-key.txt
    """
    from .services.api_key_service import APIKeyService, bootstrap_first_run_key

    svc = APIKeyService()
    provisioned = bootstrap_first_run_key(svc)
    if provisioned is None:
        return

    raw_key = provisioned["key"]
    marker_path = (
        Path(os.getenv("DATA_CONFIG_DIR", "data/config")) / "first-run-key.txt"
    )
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(f"{raw_key}\n")
        os.chmod(marker_path, 0o600)
    except OSError as exc:
        logger.warning("Failed to write first-run-key.txt: %s", exc)

    banner = "=" * 70
    logger.warning(banner)
    logger.warning("FIRST-RUN: provisioned master API key (id=%s)", provisioned["id"])
    logger.warning("KEY: %s", raw_key)
    logger.warning("Saved to: %s (mode 0600)", marker_path)
    logger.warning("Use:  Authorization: Bearer %s", raw_key)
    logger.warning("This key has all scopes; rotate it via /api/keys when ready.")
    logger.warning(banner)


# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Enclave API",
    description="OpenAI-compatible API for local LLM inference with streaming support",
    version=__version__,
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
app.include_router(exports.router)
app.include_router(graph.router)
app.include_router(workflows.router)
app.include_router(workflow_index.router)
app.include_router(api_keys.router)
app.include_router(plugins.router)
app.include_router(mcp.router)
app.include_router(cloud_providers.router)
app.include_router(setup.router)
app.include_router(context.router)
app.include_router(memory.router)
app.include_router(profiles.router)
app.include_router(documents.router)
app.include_router(roles.router)
app.include_router(a2a.router)
app.include_router(agents.router)
app.include_router(feedback.router)
app.include_router(skills.router)
app.include_router(discover.router)
app.include_router(system.router)
from .routers import projects as _projects_router  # noqa: E402

app.include_router(_projects_router.router)


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
        "version": __version__,
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

# Mount /static for all assets under api/static/ (favicon, index.html,
# setup.html, vendor fonts, vendor d3, etc). Previously StaticFiles was
# imported but never mounted — favicon and every /static/* request 404'd.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
@app.head("/")
async def root():
    """Serve the HTML dashboard"""
    index = STATIC_DIR / "index.html"
    if index.exists():
        # no-store on the SPA shell so a browser never runs a stale index.html.
        # The single-file SPA bakes its JS inline, so a cached shell means
        # cached auth/boot logic — exactly what broke admin auto-sign-in after
        # we fixed it. Revalidate every load; the file is tiny relative to the
        # API round-trips it gates.
        return FileResponse(
            index,
            media_type="text/html",
            headers={"Cache-Control": "no-store, must-revalidate"},
        )
    # Fallback to JSON if static files missing
    return {
        "message": "Enclave API",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/api/info")
async def api_info():
    """JSON API information endpoint"""
    return {
        "message": "Enclave API",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "completions": "/v1/completions",
            "models": "/v1/models",
        },
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────


def run_server() -> None:
    """Console-script entrypoint for the `enclave-api` command.

    Same behaviour as `python api/main.py` — boots uvicorn against the
    module-level FastAPI app using API_HOST / API_PORT / LOG_LEVEL.
    Auto-reload is OFF when invoked via the console script (suited for
    production / Docker / DMG); set `ENCLAVE_RELOAD=1` to opt in.
    """
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=os.getenv("ENCLAVE_RELOAD", "").lower() in {"1", "true", "yes"},
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
