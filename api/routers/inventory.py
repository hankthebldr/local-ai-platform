#!/usr/bin/env python3
"""
Inventory Router - Model catalog, install/remove, memory management

Exposes the MODEL_REGISTRY from models/download.py as an API,
with hardware auto-detection and live install status from Ollama.
"""

import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

import psutil
import requests
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from ..logging_config import logger
from ..middleware import require_master_key
from ..services.discovery_service import (
    get_cached_or_discover,
    is_cache_fresh,
    load_discovery_cache,
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


# ── Hardware Detection (extracted to services/hardware_profile — LB4-U1) ──
#
# The profile table + detection moved to api/services/hardware_profile.py so
# the pure model_fit service can consume them without importing a router.
# Re-exported here so existing imports (tests, scripts) stay valid.

from ..services.hardware_profile import (  # noqa: F401  (re-exports)
    HARDWARE_PROFILES,
    _host_cpu_brand,
    _host_cpu_cores,
    _host_gpu,
    _host_ram_gb,
    detect_hardware,
)

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
        result.update(_vllm_installed_models())
        return result
    except Exception as e:
        logger.error(f"Failed to get installed models: {e}")
        return _vllm_installed_models()


def _vllm_installed_models() -> dict:
    """vLLM-served models, shaped like installed Ollama models so the Models
    tab reflects the full set the platform can serve. Read-only (vLLM weights
    aren't Ollama-pull/remove-managed). Never raises."""
    out: dict = {}
    try:
        from ..services.runner_registry import get_current_registry
        from ..services.runner import RunnerKind

        reg = get_current_registry()
        if RunnerKind.VLLM not in reg.kinds():
            return {}
        for m in reg.get(RunnerKind.VLLM).list_models():
            out[m.id] = {
                "size_bytes": 0,
                "size_gb": m.size_gb or 0,
                "modified_at": "",
                "digest": "",
                "details": {
                    "family": m.family or "vllm",
                    "quantization_level": (m.quant.value if m.quant else None),
                },
                "backend": "vllm",
            }
    except Exception:
        return {}
    return out


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


# ── Task taxonomy + operator tag overrides (LB4-U1) ────────────────────────

# Task tier = dfStepTemplates keys; role tier = dfRoleColors vocabulary.
# Same strings the Composer bench and the prompt recommender use — the
# recommendations route derives task → role → role_fit through this map.
TASK_ROLE_MAP = {
    "analyzer": "reasoning",
    "classifier": "reasoning",
    "planner": "reasoning",
    "retriever": "fast",
    "code_gen": "coding",
    "rule_writer": "coding",
    "composer": "reasoning",
    "validator": "reasoning",
    "reviewer": "reasoning",
    "decision": "reasoning",
    "fast_extract": "fast",
    "uncensored": "uncensored",
    "custom": "general",
}

MODEL_ROLES = ("reasoning", "coding", "fast", "general", "uncensored")

# Model names arrive as HF-style ids ("nvidia/Qwen3-8B-NVFP4") or Ollama
# tags ("huihui_ai/qwen2.5-abliterated:7b") — allow `/ : .` but nothing
# shell- or path-trick-shaped. The store is a PURE dict keyed by name; the
# name is never resolved against the filesystem.
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9_.:/\-]{1,128}$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

_MODEL_TAGS_FILE = Path("data/config/model_tags.json")


def _read_model_tags() -> dict:
    """Operator task-tag overrides: flat {model_name: [tags]}. Never raises."""
    try:
        if not _MODEL_TAGS_FILE.is_file():
            return {}
        data = json.loads(_MODEL_TAGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001 — corrupt overrides ≠ dead catalog
        logger.warning(f"model_tags.json unreadable: {e}")
        return {}


def _write_model_tags(tags: dict) -> None:
    """Atomic whole-file replace (tmp + os.replace) of the overrides store."""
    _MODEL_TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MODEL_TAGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tags, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, _MODEL_TAGS_FILE)


def _agents_referencing(model_name: str) -> list:
    """Agents (agents/*.yaml) whose `model` references this model — exact
    name or same base before the ':tag'. Mirrors _workflows_referencing."""
    out = []
    agents_dir = Path(__file__).parent.parent.parent / "agents"
    if not agents_dir.exists():
        return out
    base = model_name.split(":")[0]
    for f in sorted(agents_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        agent_model = str(data.get("model") or "")
        if not agent_model:
            continue
        if agent_model == model_name or agent_model.split(":")[0] == base:
            out.append(
                {
                    "id": data.get("id") or f.stem,
                    "name": data.get("name") or f.stem,
                    "role": data.get("role"),
                }
            )
    return out


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/system")
async def system_info():
    """Hardware auto-detection and system info for the dashboard.

    Splits two distinct concerns the SPA used to conflate:
      * memory.total_gb / cpu.count = HOST hardware (what models you can
        theoretically run). Pulled from ENCLAVE_HOST_* env vars when set
        so the container reports the real machine, not the Docker VM.
      * memory.used_gb / cpu.percent = CONTAINER live usage (what the API
        process is consuming right now). Always from psutil — accurate
        for the API itself, not the host.
    """
    hw = detect_hardware()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    host_ram_gb = _host_ram_gb()
    host_cores = _host_cpu_cores()
    host_source = "env" if os.getenv("ENCLAVE_HOST_RAM_GB", "").strip() else "container"

    return {
        "hardware": hw,
        "host_source": host_source,
        "memory": {
            # Host total — accurate on Docker Desktop only when the env
            # var is set; otherwise this is the Linux-VM slice.
            "total_gb": float(host_ram_gb),
            # Container-scoped live usage.
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
            "count": host_cores,
            "count_physical": host_cores,
            "brand": _host_cpu_brand(),
        },
        "gpu": {
            # Empty string when no discrete GPU (Mac/CPU-only hosts).
            # Populated by host-preset.sh via ENCLAVE_HOST_GPU env var.
            "model": _host_gpu(),
            "present": bool(_host_gpu()),
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
    from ..services import model_fit

    registry = _get_registry()
    installed = _get_installed_models()
    hw = detect_hardware()
    # One detection pass for the whole catalog — compute_fit never raises.
    budget_gb, fit_basis, arch_name, compute_cap = model_fit.detect_budget()
    tag_overrides = _read_model_tags()

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
            # Which inference engine serves this model. GGUF catalog models
            # default to Ollama; a vLLM-served entry declares runner="vllm".
            # Surfaced so the UI (AssetPeek) can show the serving runner and so
            # ModelResolver.resolve_with_runner() dispatches correctly.
            "runner": info.get("runner", "ollama"),
            # Intrinsic metadata (LB4-U1) — feeds the Weights-architecture
            # detail section and the fit/recommendation scoring.
            "quant": info.get("quant"),
            "params_b": info.get("params_b"),
            "arch_family": info.get("arch_family"),
            "context_tokens": info.get("context_tokens"),
            "min_arch": info.get("min_arch"),
            # Operator overrides (data/config/model_tags.json) win over the
            # registry's curated task tags.
            "task_tags": tag_overrides.get(model_id)
            or tag_overrides.get(ollama_name)
            or info.get("task_tags", []),
        }
        # Load-fit hint (score/class/budget/required/basis) — labeled a hint,
        # not a runtime guarantee; fits_ram retained above for old consumers.
        entry["fit"] = model_fit.compute_fit(
            {**info, "size_gb": info.get("size_gb", size_gb)},
            budget_gb=budget_gb,
            basis=fit_basis,
            arch_name=arch_name,
            compute_capability=compute_cap,
        )
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
                    "task_tags": tag_overrides.get(name, []),
                    "fit": model_fit.compute_fit(
                        {"size_gb": details.get("size_gb", 0)},
                        budget_gb=budget_gb,
                        basis=fit_basis,
                        arch_name=arch_name,
                        compute_capability=compute_cap,
                    ),
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

    # Every model actually resident on this box, catalogued or not — so the
    # operator can see/manage models that were installed natively (yi:34b,
    # qwen2.5, the vLLM-served weights) and aren't in the curated registry.
    installed_local = [
        {
            "name": name,
            "backend": meta.get("backend", "ollama"),
            "size_gb": meta.get("size_gb", 0),
            "in_catalog": any(
                _is_installed(registry[m].get("ollama", ""), {name: meta})
                for m in registry
            ),
        }
        for name, meta in installed.items()
    ]

    return {
        "installed": installed_ids,
        "available": available_ids,
        "installed_count": len(installed_ids),
        "available_count": len(available_ids),
        "total_registry": len(registry),
        "total_ollama": len(installed),
        # Full local inventory (all backends), for the "natively installed"
        # management view — independent of catalog membership.
        "installed_local": installed_local,
        "installed_local_count": len(installed_local),
    }


class PullRequest(BaseModel):
    model: str = Field(..., description="Ollama model name to pull")


@router.post("/pull", dependencies=[Depends(require_master_key)])
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


@router.post("/remove", dependencies=[Depends(require_master_key)])
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
    """Currently loaded models across backends — Ollama (/api/ps) plus vLLM
    resident (pinned) models. With vLLM as the primary GPU backend, omitting
    it left this pane misleadingly empty whenever Ollama had evicted its
    models. Each entry carries a `backend` marker for the UI to badge."""
    running = []
    ollama_err = None
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=10)
        resp.raise_for_status()
        for model in resp.json().get("models", []):
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
                    "backend": "ollama",
                }
            )
    except Exception as e:
        ollama_err = str(e)

    # Fold in vLLM resident models (independent of Ollama reachability).
    running.extend(_vllm_running_models())

    mem = psutil.virtual_memory()
    out = {
        "running_models": running,
        "running_count": len(running),
        "system_memory": {
            "total_gb": round(mem.total / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "available_gb": round(mem.available / (1024**3), 1),
            "percent": mem.percent,
        },
    }
    # Only surface the Ollama error when it actually left us with nothing.
    if ollama_err and not running:
        out["error"] = ollama_err
    return out


def _vllm_running_models() -> list:
    """vLLM's served (GPU-resident) models, in the /api/ps card shape. vLLM
    pins its model at server start, so 'served' == 'resident'. Never raises."""
    out = []
    try:
        from ..services.runner_registry import get_current_registry
        from ..services.runner import RunnerKind

        reg = get_current_registry()
        if RunnerKind.VLLM not in reg.kinds():
            return []
        runner = reg.get(RunnerKind.VLLM)
        if not runner.health().reachable:
            return []
        for m in runner.list_models():
            out.append(
                {
                    "name": m.id,
                    "size_bytes": 0,
                    "size_gb": m.size_gb or 0,
                    "size_vram_bytes": 0,
                    "size_vram_gb": 0,
                    "digest": "",
                    "expires_at": "pinned",
                    "details": {
                        "family": m.family or "vllm",
                        "quantization_level": (m.quant.value if m.quant else None),
                    },
                    "backend": "vllm",
                }
            )
    except Exception:
        return []
    return out


def _workflows_referencing(model_name: str) -> list:
    """Workflows whose steps reference this model (exact name or same base
    before the ':tag'). Powers the 'what workflows it supports' detail view."""
    out = []
    wf_dir = Path(__file__).parent.parent.parent / "workflows"
    if not wf_dir.exists():
        return out
    base = model_name.split(":")[0]
    for f in sorted(wf_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        steps = data.get("steps") or []
        models = {
            (s.get("model") or "")
            for s in steps
            if isinstance(s, dict) and s.get("model")
        }
        if model_name in models or any(m.split(":")[0] == base for m in models):
            out.append(
                {
                    "id": data.get("id") or f.stem,
                    "name": data.get("name") or f.stem,
                    "steps": len(steps),
                }
            )
    return out


@router.get("/model/{name:path}")
async def model_detail(name: str):
    """Rich detail for one installed model — Ollama /api/show metadata (or vLLM
    served-model info) plus which workflows reference it. Backs the
    double-click detail view in the local inventory."""
    # vLLM-served?
    for m in _vllm_running_models():
        if m["name"] == name:
            return {
                "name": name,
                "backend": "vllm",
                "details": m.get("details", {}),
                "model_info": {},
                "capabilities": ["chat", "continuous_batching"],
                "modified_at": None,
                "workflows": _workflows_referencing(name),
                "agents": _agents_referencing(name),
                "note": "Served by vLLM (pinned). Managed via docker compose.",
            }

    # Ollama model — pull the rich /api/show payload.
    from ..services.ollama_service import OllamaService

    try:
        info = OllamaService().get_model_info(name)
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "backend": "ollama",
            "error": str(exc),
            "workflows": _workflows_referencing(name),
            "agents": _agents_referencing(name),
        }

    mi = info.get("model_info") or {}
    # Keep only the high-signal model_info keys (context length, architecture,
    # param/embedding sizes) — the full blob is huge.
    keep = {
        k: v
        for k, v in mi.items()
        if any(
            tok in k
            for tok in ("context_length", "architecture", "parameter", "embedding")
        )
    }
    return {
        "name": name,
        "backend": "ollama",
        "details": info.get("details", {}),
        "model_info": keep,
        "capabilities": info.get("capabilities", []),
        "modified_at": info.get("modified_at"),
        "workflows": _workflows_referencing(name),
        "agents": _agents_referencing(name),
    }


class UnloadRequest(BaseModel):
    model: str = Field(..., description="Model name to unload from memory")


@router.post("/unload", dependencies=[Depends(require_master_key)])
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


# ── Explicit warm (LB1-U1) ─────────────────────────────────────────────────


class WarmRequest(BaseModel):
    model: str = Field(..., description="Model id to pre-warm into memory")


def _warm_runner_for(model_id: str):
    """Pick the runner that serves ``model_id``: vLLM when the id is in its
    served set, else Ollama (the universal fallback). Raises
    RunnerNotConfigured / RuntimeError upward for the route to translate."""
    from ..services.runner import RunnerKind
    from ..services.runner_registry import get_current_registry

    reg = get_current_registry()
    if RunnerKind.VLLM in reg.kinds():
        vllm = reg.get(RunnerKind.VLLM)
        try:
            if model_id in {m.id for m in vllm.list_models()}:
                return vllm
        except Exception as e:  # noqa: BLE001 — unreachable vLLM ≠ warm failure
            logger.debug(f"warm: vLLM model listing failed: {e}")
    return reg.get(RunnerKind.OLLAMA)


@router.post("/warm", dependencies=[Depends(require_master_key)])
async def warm_model(req: WarmRequest):
    """Explicitly load a model via the runner-service load path
    (Runner.load(): Ollama pre-warms with a zero-token generate; a pinned
    vLLM server is a documented no-op — its weights loaded at server start).

    ``noop`` is the capability signal the Test pane uses to disable the Warm
    button with a reason instead of showing a dead control on the flagship
    NVFP4/vLLM models.
    """
    try:
        runner = _warm_runner_for(req.model)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # RunnerNotConfigured
        raise HTTPException(status_code=503, detail=str(e))

    result = runner.load(req.model)
    noop = not getattr(runner, "supports_hot_swap", True)
    return {
        "model": req.model,
        "runner": runner.name.value,
        "loaded": result.loaded,
        "load_duration_ms": round(result.load_seconds * 1000, 1),
        "noop": noop,
        "reason": result.reason,
    }


# ── Discovery Endpoints ───────────────────────────────────────────────────


@router.get("/discover")
async def discover(force: bool = False):
    """
    Discover new abliterated/uncensored models from HuggingFace.

    Theme B (no background egress): a plain read NEVER reaches HuggingFace.
    It used to — ``get_cached_or_discover`` ran a live discovery whenever the
    cache was cold or older than the refresh interval, so merely opening the
    Models tab egressed. Now a stale cache is served AS stale (``cache_fresh``
    already tells the UI, and ``never_discovered`` distinguishes "cold" from
    "old" so the panel can degrade honestly); the network is touched only on
    the operator's explicit ⟳ — ``?force=true`` here, or the background
    ``POST /discover/refresh``.
    """
    hw = detect_hardware()
    max_ram = hw.get("max_model_ram_gb", 50)

    if force:
        result = get_cached_or_discover(max_model_ram_gb=max_ram, force=True)
    else:
        result = load_discovery_cache() or {}
    return {
        "models": result.get("models", []),
        "count": result.get("count", 0),
        "timestamp": result.get("timestamp", ""),
        "cache_fresh": is_cache_fresh(),
        "never_discovered": not result,
        "trusted_authors": TRUSTED_AUTHORS,
        "hardware": hw,
    }


def _read_benchmarks() -> dict:
    """data/discovery/model_benchmarks.json (repo data, CWD-relative like the
    original enrichment route). {} on missing/corrupt — never raises."""
    path = Path("data/discovery/model_benchmarks.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"enrichment file unreadable: {e}")
        return {}


def _read_model_meta() -> dict:
    """api/config/model_meta.json — the curated per-arch-class sidecar
    (repo-shipped, COPY'd tree, resolved relative to this module so it is
    found regardless of CWD). {} on missing/corrupt — never raises."""
    path = Path(__file__).parent.parent / "config" / "model_meta.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"model_meta.json unreadable: {e}")
        return {}


@router.get("/enrichment")
async def model_enrichment():
    """Curated model enrichment — benchmark figures, role-fit profiles, and
    operator notes for the deep-dive cards. Shipped as repo data
    (data/discovery/model_benchmarks.json): privacy-first, no runtime
    phone-home; absence of a benchmark block means no credible published
    figure exists for that variant.

    LB4-U1: the curated api/config/model_meta.json sidecar (per-arch-class
    tok/s expectations, vram notes, per-intent configs) is merged additively
    under the reserved 'model_meta' key — benchmark keys pass through."""
    out = _read_benchmarks()
    meta = _read_model_meta()
    if meta:
        out["model_meta"] = meta
    return out


# ── Recommendations + tag overrides (LB4-U1) ───────────────────────────────


@router.get("/recommendations")
async def model_recommendations(intent: str = "", limit: int = 12):
    """Read-open model-side recommender — the twin of GET /api/prompts/recommend.

    Ranks every catalog model by role_fit × fit-class for an intent (a task
    key from the Composer taxonomy, or a role directly). Derivation is
    task → role → role_fit (model_benchmarks.json), overridable by explicit
    task_tags (registry or operator overrides). Not-installed catalog models
    are included with a Pull affordance. Pure + instant — no model call, no
    network; per-factor breakdown makes the ranking explainable."""
    from ..services import model_fit

    intent_key = (intent or "").strip()
    role = TASK_ROLE_MAP.get(intent_key) or (
        intent_key if intent_key in MODEL_ROLES else "general"
    )
    registry = _get_registry()
    installed = _get_installed_models()
    benchmarks = _read_benchmarks()
    tag_overrides = _read_model_tags()
    budget_gb, fit_basis, arch_name, compute_cap = model_fit.detect_budget()

    results = []
    for model_id, info in registry.items():
        ollama_name = info.get("ollama", "")
        is_inst = _is_installed(ollama_name, installed)
        bench = benchmarks.get(model_id) or {}
        role_fits = bench.get("role_fit") or {}
        raw_fit = role_fits.get(role)
        has_bench = isinstance(raw_fit, (int, float))
        role_fit = float(raw_fit) if has_bench else 50.0
        task_tags = (
            tag_overrides.get(model_id)
            or tag_overrides.get(ollama_name)
            or info.get("task_tags", [])
        )
        # Explicit task_tags override the pure role derivation with a boost.
        tag_match = bool(intent_key) and intent_key in task_tags
        if tag_match:
            role_fit = min(100.0, role_fit + 15.0)
        fit = model_fit.compute_fit(
            info,
            budget_gb=budget_gb,
            basis=fit_basis,
            arch_name=arch_name,
            compute_capability=compute_cap,
        )
        multiplier = model_fit.FIT_CLASS_MULTIPLIER.get(fit["class"], 0.8)
        results.append(
            {
                "id": model_id,
                "name": info["name"],
                "ollama": ollama_name,
                "size": info.get("size", "?"),
                "installed": is_inst,
                # Pull affordance for not-installed catalog models.
                "pull": (
                    None
                    if is_inst
                    else {"action": "pull", "model": ollama_name or None}
                ),
                "score": round(role_fit * multiplier, 1),
                "fit": fit,
                "task_tags": task_tags,
                "factors": {
                    "role_fit": {
                        "role": role,
                        "value": role_fit,
                        "source": "benchmarks" if has_bench else "default",
                        "task_tag_boost": tag_match,
                    },
                    "fit_class": {"class": fit["class"], "multiplier": multiplier},
                },
            }
        )

    results.sort(key=lambda r: (r["score"], r["installed"]), reverse=True)
    return {
        "intent": intent_key or None,
        "role": role,
        "basis": fit_basis,
        "results": results[: max(1, min(limit, 50))],
    }


class ModelTagsRequest(BaseModel):
    tags: list[str] = Field(
        default_factory=list,
        description="Operator task-tag overrides for this model (empty clears)",
    )


@router.patch("/model/{name:path}/tags", dependencies=[Depends(require_master_key)])
async def patch_model_tags(name: str, req: ModelTagsRequest):
    """Set operator task-tag overrides for a model (LB4-U1).

    The name is validated against a charset allowlist (HF/Ollama ids —
    `/ : .` allowed) and stored as a PURE dict key in
    data/config/model_tags.json — it is never resolved against the
    filesystem, so there is no traversal surface. Atomic write. Overrides
    stay user-layer; curation into MODEL_REGISTRY is a manual follow-up."""
    if (
        not _MODEL_NAME_RE.match(name or "")
        or ".." in name
        or name.startswith(("/", "."))
    ):
        raise HTTPException(
            status_code=400,
            detail="invalid model name (allowed: A-Za-z0-9_.:/-, max 128, "
            "no leading / or ., no ..)",
        )
    clean: list[str] = []
    for t in req.tags:
        if not isinstance(t, str) or not _TAG_RE.match(t):
            raise HTTPException(
                status_code=400,
                detail=f"invalid tag {t!r} (allowed: A-Za-z0-9_.:-, max 64)",
            )
        if t not in clean:
            clean.append(t)
    if len(clean) > 32:
        raise HTTPException(status_code=400, detail="too many tags (max 32)")

    store = _read_model_tags()
    if clean:
        store[name] = clean
    else:
        store.pop(name, None)
    _write_model_tags(store)
    logger.info(f"model tag overrides saved: {name} -> {clean}")
    return {"status": "saved", "model": name, "task_tags": clean}


@router.post("/discover/refresh", dependencies=[Depends(require_master_key)])
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


@router.post("/settings/search", dependencies=[Depends(require_master_key)])
async def update_settings_search(req: SearchSettingsRequest):
    """Update search configuration. Only provided fields are updated.

    Master-key gated (LB1-U1): this route persists brave_api_key — a secrets
    write — and the Test pane's promote path writes through it."""
    current = get_search_config()

    # Merge: only update fields that were explicitly provided
    updated = {
        "searxng_url": (
            req.searxng_url
            if req.searxng_url is not None
            else current.get("searxng_url", "")
        ),
        "brave_api_key": (
            req.brave_api_key
            if req.brave_api_key is not None
            else current.get("brave_api_key", "")
        ),
        "search_timeout": (
            req.search_timeout
            if req.search_timeout is not None
            else current.get("search_timeout", 10)
        ),
        "max_results": (
            req.max_results
            if req.max_results is not None
            else current.get("max_results", 5)
        ),
        "default_backend": (
            req.default_backend
            if req.default_backend is not None
            else current.get("default_backend", "auto")
        ),
    }

    save_search_config(updated)
    logger.info(
        f"Search settings updated: backend={updated['default_backend']}, searxng={'set' if updated['searxng_url'] else 'unset'}, brave={'set' if updated['brave_api_key'] else 'unset'}"
    )

    return {"status": "saved", "config": get_search_config()}
