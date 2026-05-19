#!/usr/bin/env python3
"""
Inventory Router - Model catalog, install/remove, memory management

Exposes the MODEL_REGISTRY from models/download.py as an API,
with hardware auto-detection and live install status from Ollama.
"""

import os
import subprocess
import threading
from typing import Optional

import psutil
import requests
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from ..logging_config import logger
from ..services.discovery_service import (
    get_cached_or_discover,
    load_discovery_cache,
    is_cache_fresh,
    TRUSTED_AUTHORS,
)
from ..services.search_service import (
    get_config as get_search_config,
    save_config as save_search_config,
)

load_dotenv()

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ── Pull progress tracking (in-memory) ────────────────────────────────────

_pull_jobs: dict = {}  # model_name -> {status, progress, total, completed}


# ── Hardware Detection ────────────────────────────────────────────────────

HARDWARE_PROFILES = {
    "ms01": {
        "name": "Minisforum MS-01",
        "cpu": "Intel i9-13900H (6P+8E/20T, 5.4GHz)",
        "threads": 20,
        "ram_gb": 64,
        "max_model_ram_gb": 50,
    },
    "bd790i": {
        "name": "ASRock BD790i (Ryzen 9 7945HX)",
        "cpu": "AMD Ryzen 9 7945HX (16C/32T, 5.4GHz)",
        "threads": 32,
        "ram_gb": 96,
        "max_model_ram_gb": 80,
    },
    "mac-m4": {
        "name": "Mac M4 Pro",
        "cpu": "Apple M4 Pro",
        "threads": psutil.cpu_count() or 12,
        "ram_gb": round(psutil.virtual_memory().total / (1024**3)),
        "max_model_ram_gb": round(psutil.virtual_memory().total / (1024**3) * 0.75),
    },
}


def detect_hardware() -> dict:
    """Auto-detect which hardware profile matches this machine."""
    import platform

    cpu_brand = ""
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            cpu_brand = result.stdout.strip()
        else:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        cpu_brand = line.split(":")[1].strip()
                        break
    except Exception:
        cpu_brand = platform.processor() or "unknown"

    cpu_lower = cpu_brand.lower()
    total_ram = round(psutil.virtual_memory().total / (1024**3))
    thread_count = psutil.cpu_count() or 0

    # Match known profiles
    if "7945hx" in cpu_lower or "bd790i" in cpu_lower:
        profile_key = "bd790i"
    elif "13900h" in cpu_lower or ("i9" in cpu_lower and total_ram <= 64):
        profile_key = "ms01"
    elif (
        "apple" in cpu_lower
        or "m4" in cpu_lower
        or "m3" in cpu_lower
        or "m2" in cpu_lower
    ):
        profile_key = "mac-m4"
    else:
        profile_key = "auto"

    if profile_key == "auto" or profile_key not in HARDWARE_PROFILES:
        return {
            "profile": "auto",
            "name": f"Detected: {cpu_brand}",
            "cpu": cpu_brand,
            "threads": thread_count,
            "ram_gb": total_ram,
            "max_model_ram_gb": round(total_ram * 0.75),
        }

    profile = HARDWARE_PROFILES[profile_key].copy()
    profile["profile"] = profile_key
    # Override RAM with actual detected value
    profile["ram_gb"] = total_ram
    profile["threads"] = thread_count
    return profile


# ── Model Registry (imported from models/download.py) ─────────────────────


def _get_registry() -> dict:
    """Import MODEL_REGISTRY from models/download.py at call time."""
    import sys
    from pathlib import Path

    # Add project root to path so we can import
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from models.download import MODEL_REGISTRY

    return MODEL_REGISTRY


def _get_installed_models() -> dict:
    """Get installed models from Ollama."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        resp.raise_for_status()
        result = {}
        for model in resp.json().get("models", []):
            name = model.get("name", "")
            size_bytes = model.get("size", 0)
            result[name] = {
                "size_bytes": size_bytes,
                "size_gb": round(size_bytes / (1024**3), 2) if size_bytes else 0,
                "modified_at": model.get("modified_at", ""),
                "digest": model.get("digest", "")[:12],
                "details": model.get("details", {}),
            }
        return result
    except Exception as e:
        logger.error(f"Failed to get installed models: {e}")
        return {}


def _is_installed(ollama_name: str, installed: dict) -> bool:
    """Check if a registry model is installed in Ollama."""
    if not ollama_name:
        return False
    for inst_name in installed:
        if ollama_name in inst_name or inst_name.startswith(ollama_name):
            return True
    return False


def _get_installed_name(ollama_name: str, installed: dict) -> Optional[str]:
    """Get the exact installed name for a registry model."""
    if not ollama_name:
        return None
    for inst_name in installed:
        if ollama_name in inst_name or inst_name.startswith(ollama_name):
            return inst_name
    return None


# ── Model Scoring ──────────────────────────────────────────────────────────


def _parse_context_k(ctx_str: str) -> int:
    """Parse context string like '128K', '256K', '32K' to integer thousands."""
    if not ctx_str or ctx_str == "—":
        return 0
    ctx_str = ctx_str.upper().strip()
    try:
        if "K" in ctx_str:
            return int(ctx_str.replace("K", ""))
        return int(ctx_str) // 1000
    except (ValueError, TypeError):
        return 0


def score_model(model: dict) -> float:
    """
    Score a model for the default sort order.
    Higher = better fit for uncensored/abliterated + large context use cases.

    Scoring weights:
      - abliterated tag:    +40 points
      - uncensored tag:     +20 points
      - context >= 128K:    +25 points
      - context >= 64K:     +15 points
      - context >= 32K:     +8 points
      - fits in RAM:        +15 points
      - installed:          +10 points
      - reasoning tag:      +5 points
      - 2026 tag (recent):  +5 points
    """
    tags = model.get("tags", [])
    score = 0.0

    if "abliterated" in tags:
        score += 40
    if "uncensored" in tags:
        score += 20
    if "reasoning" in tags:
        score += 5
    if "2026" in tags:
        score += 5

    ctx_k = _parse_context_k(model.get("context", ""))
    if ctx_k >= 128:
        score += 25
    elif ctx_k >= 64:
        score += 15
    elif ctx_k >= 32:
        score += 8

    if model.get("fits_ram", False):
        score += 15
    if model.get("installed", False):
        score += 10

    return score


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/system")
async def system_info():
    """Hardware auto-detection and system info for the dashboard."""
    hw = detect_hardware()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "hardware": hw,
        "memory": {
            "total_gb": round(mem.total / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "available_gb": round(mem.available / (1024**3), 1),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "free_gb": round(disk.free / (1024**3), 1),
            "percent": round(disk.used / disk.total * 100, 1),
        },
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.1),
            "count": psutil.cpu_count(),
            "count_physical": psutil.cpu_count(logical=False),
        },
        "ollama_config": {
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
            "max_concurrent_llm": int(os.getenv("MAX_CONCURRENT_LLM", "1")),
            "model_list_ttl": float(os.getenv("MODEL_LIST_TTL", "30")),
            "request_timeout": int(os.getenv("REQUEST_TIMEOUT", "900")),
        },
    }


@router.get("/catalog")
async def catalog(tag: Optional[str] = None):
    """Full model catalog from MODEL_REGISTRY with install status."""
    registry = _get_registry()
    installed = _get_installed_models()
    hw = detect_hardware()

    models = []
    for model_id, info in registry.items():
        ollama_name = info.get("ollama", "")
        is_inst = _is_installed(ollama_name, installed)
        inst_name = _get_installed_name(ollama_name, installed)
        inst_info = installed.get(inst_name, {}) if inst_name else {}

        tags = info.get("tags", [])
        if tag and tag not in tags:
            continue

        # Determine speed for detected hardware
        speed = info.get("speed", "—")
        if isinstance(speed, dict):
            hw_key = hw.get("profile", "ms01")
            speed_str = speed.get(hw_key, speed.get("ms01", next(iter(speed.values()))))
        else:
            speed_str = speed

        # Parse size for fit check
        size_str = info.get("size", "0GB")
        try:
            size_gb = float(size_str.replace("GB", "").replace("gb", ""))
        except ValueError:
            size_gb = 0

        fits = size_gb <= hw.get("max_model_ram_gb", 50)

        entry = {
            "id": model_id,
            "name": info["name"],
            "ollama": ollama_name,
            "huggingface": info.get("huggingface"),
            "gguf": info.get("gguf"),
            "size": info.get("size", "?"),
            "size_gb": size_gb,
            "speed": speed_str,
            "context": info.get("context", "—"),
            "description": info["description"],
            "tags": tags,
            "installed": is_inst,
            "installed_info": inst_info if is_inst else None,
            "fits_ram": fits,
        }
        entry["score"] = score_model(entry)
        models.append(entry)

    # Also include installed models NOT in registry
    registry_ollama_names = {info.get("ollama", "") for info in registry.values()}
    for name, details in installed.items():
        if not any(
            name.startswith(reg) or reg in name for reg in registry_ollama_names if reg
        ):
            models.append(
                {
                    "id": name,
                    "name": name,
                    "ollama": name,
                    "size": f"{details.get('size_gb', 0):.1f}GB",
                    "size_gb": details.get("size_gb", 0),
                    "speed": "—",
                    "context": "—",
                    "description": "Installed (not in catalog)",
                    "tags": ["extra"],
                    "installed": True,
                    "installed_info": details,
                    "fits_ram": True,
                }
            )

    # Sort by score descending (abliterated + large context first)
    models.sort(key=lambda m: m.get("score", 0), reverse=True)

    return {
        "models": models,
        "total": len(models),
        "installed_count": sum(1 for m in models if m["installed"]),
        "hardware": hw,
    }


@router.get("/status")
async def status():
    """Quick summary: installed vs available counts."""
    registry = _get_registry()
    installed = _get_installed_models()

    installed_ids = []
    available_ids = []
    for model_id, info in registry.items():
        ollama_name = info.get("ollama", "")
        if _is_installed(ollama_name, installed):
            installed_ids.append(model_id)
        else:
            available_ids.append(model_id)

    return {
        "installed": installed_ids,
        "available": available_ids,
        "installed_count": len(installed_ids),
        "available_count": len(available_ids),
        "total_registry": len(registry),
        "total_ollama": len(installed),
    }


class PullRequest(BaseModel):
    model: str = Field(..., description="Ollama model name to pull")


@router.post("/pull")
async def pull_model(req: PullRequest, background_tasks: BackgroundTasks):
    """Start pulling a model in the background. Poll /pull-progress/{model} for status."""
    model = req.model

    if model in _pull_jobs and _pull_jobs[model].get("status") == "pulling":
        return {"status": "already_pulling", "model": model}

    _pull_jobs[model] = {
        "status": "pulling",
        "progress": 0,
        "total": 0,
        "completed": False,
        "error": None,
    }

    def _do_pull():
        try:
            resp = requests.post(
                f"{OLLAMA_HOST}/api/pull",
                json={"name": model, "stream": True},
                stream=True,
                timeout=3600,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    import json

                    data = json.loads(line)
                    _pull_jobs[model]["progress"] = data.get("completed", 0)
                    _pull_jobs[model]["total"] = data.get("total", 0)
                    _pull_jobs[model]["digest"] = data.get("digest", "")
                    status_msg = data.get("status", "")
                    _pull_jobs[model]["status_message"] = status_msg
                    if status_msg == "success":
                        _pull_jobs[model]["status"] = "complete"
                        _pull_jobs[model]["completed"] = True
                        return
            _pull_jobs[model]["status"] = "complete"
            _pull_jobs[model]["completed"] = True
        except Exception as e:
            _pull_jobs[model]["status"] = "error"
            _pull_jobs[model]["error"] = str(e)

    thread = threading.Thread(target=_do_pull, daemon=True)
    thread.start()

    return {"status": "started", "model": model}


@router.get("/pull-progress/{model:path}")
async def pull_progress(model: str):
    """Poll pull progress for a model."""
    if model not in _pull_jobs:
        return {"status": "not_found", "model": model}
    return {**_pull_jobs[model], "model": model}


class RemoveRequest(BaseModel):
    model: str = Field(..., description="Ollama model name to remove")


@router.post("/remove")
async def remove_model(req: RemoveRequest):
    """Remove a model from Ollama."""
    try:
        resp = requests.delete(
            f"{OLLAMA_HOST}/api/delete",
            json={"name": req.model},
            timeout=30,
        )
        if resp.status_code == 200:
            return {"status": "removed", "model": req.model}
        else:
            return {"status": "error", "model": req.model, "detail": resp.text}
    except Exception as e:
        return {"status": "error", "model": req.model, "detail": str(e)}


@router.get("/memory")
async def memory_usage():
    """Currently loaded models with memory usage from Ollama /api/ps."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        running = []
        for model in data.get("models", []):
            running.append(
                {
                    "name": model.get("name", ""),
                    "size_bytes": model.get("size", 0),
                    "size_gb": round(model.get("size", 0) / (1024**3), 2),
                    "size_vram_bytes": model.get("size_vram", 0),
                    "size_vram_gb": round(model.get("size_vram", 0) / (1024**3), 2),
                    "digest": model.get("digest", "")[:12],
                    "expires_at": model.get("expires_at", ""),
                    "details": model.get("details", {}),
                }
            )

        mem = psutil.virtual_memory()
        return {
            "running_models": running,
            "running_count": len(running),
            "system_memory": {
                "total_gb": round(mem.total / (1024**3), 1),
                "used_gb": round(mem.used / (1024**3), 1),
                "available_gb": round(mem.available / (1024**3), 1),
                "percent": mem.percent,
            },
        }
    except Exception as e:
        return {"running_models": [], "running_count": 0, "error": str(e)}


class UnloadRequest(BaseModel):
    model: str = Field(..., description="Model name to unload from memory")


@router.post("/unload")
async def unload_model(req: UnloadRequest):
    """Unload a model from memory by sending a generate request with keep_alive=0."""
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": req.model, "keep_alive": 0},
            timeout=30,
        )
        return {"status": "unloaded", "model": req.model}
    except Exception as e:
        return {"status": "error", "model": req.model, "detail": str(e)}


# ── Discovery Endpoints ───────────────────────────────────────────────────


@router.get("/discover")
async def discover(force: bool = False):
    """
    Discover new abliterated/uncensored models from HuggingFace.
    Returns cached results by default; use ?force=true to refresh.
    """
    hw = detect_hardware()
    max_ram = hw.get("max_model_ram_gb", 50)

    result = get_cached_or_discover(max_model_ram_gb=max_ram, force=force)
    return {
        "models": result.get("models", []),
        "count": result.get("count", 0),
        "timestamp": result.get("timestamp", ""),
        "cache_fresh": is_cache_fresh(),
        "trusted_authors": TRUSTED_AUTHORS,
        "hardware": hw,
    }


@router.post("/discover/refresh")
async def discover_refresh(background_tasks: BackgroundTasks):
    """Trigger a background discovery refresh."""
    hw = detect_hardware()
    max_ram = hw.get("max_model_ram_gb", 50)

    def _run_discovery():
        get_cached_or_discover(max_model_ram_gb=max_ram, force=True)

    background_tasks.add_task(_run_discovery)
    return {
        "status": "refreshing",
        "message": "Discovery running in background. Poll /discover for results.",
    }


# ── Search Settings Endpoints ──────────────────────────────────────────────


@router.get("/settings/search")
async def get_settings_search():
    """Get current search configuration (API keys masked)."""
    return get_search_config()


class SearchSettingsRequest(BaseModel):
    searxng_url: Optional[str] = Field(None, description="SearXNG instance URL")
    brave_api_key: Optional[str] = Field(None, description="Brave Search API key")
    search_timeout: Optional[int] = Field(None, description="Search timeout in seconds")
    max_results: Optional[int] = Field(None, description="Max search results per query")
    default_backend: Optional[str] = Field(
        None, description="Preferred backend: auto, duckduckgo, searxng, brave"
    )


@router.post("/settings/search")
async def update_settings_search(req: SearchSettingsRequest):
    """Update search configuration. Only provided fields are updated."""
    current = get_search_config()

    # Merge: only update fields that were explicitly provided
    updated = {
        "searxng_url": req.searxng_url
        if req.searxng_url is not None
        else current.get("searxng_url", ""),
        "brave_api_key": req.brave_api_key
        if req.brave_api_key is not None
        else current.get("brave_api_key", ""),
        "search_timeout": req.search_timeout
        if req.search_timeout is not None
        else current.get("search_timeout", 10),
        "max_results": req.max_results
        if req.max_results is not None
        else current.get("max_results", 5),
        "default_backend": req.default_backend
        if req.default_backend is not None
        else current.get("default_backend", "auto"),
    }

    save_search_config(updated)
    logger.info(
        f"Search settings updated: backend={updated['default_backend']}, searxng={'set' if updated['searxng_url'] else 'unset'}, brave={'set' if updated['brave_api_key'] else 'unset'}"
    )

    return {"status": "saved", "config": get_search_config()}
