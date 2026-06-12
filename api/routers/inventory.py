#!/usr/bin/env python3
"""
Inventory Router - Model catalog, install/remove, memory management

Exposes the MODEL_REGISTRY from models/download.py as an API,
with hardware auto-detection and live install status from Ollama.
"""

import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

import psutil
import requests
import yaml
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from ..logging_config import logger
from ..services.discovery_service import (
    get_cached_or_discover,
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


def _host_ram_gb() -> int:
    """Total host RAM in GB. Prefers ENCLAVE_HOST_RAM_GB (compose injects
    this from sysctl/proc) over psutil, which on Docker Desktop sees only
    the Linux VM's allocation rather than the real machine."""
    env = os.getenv("ENCLAVE_HOST_RAM_GB", "").strip()
    if env.isdigit():
        return int(env)
    return round(psutil.virtual_memory().total / (1024**3))


def _host_cpu_cores() -> int:
    """Host physical core count. Same env-var-first pattern as RAM."""
    env = os.getenv("ENCLAVE_HOST_CPU_CORES", "").strip()
    if env.isdigit():
        return int(env)
    return psutil.cpu_count() or 0


def _host_cpu_brand() -> str:
    """Host CPU brand string, injected by compose (sysctl machdep.cpu.brand_string)."""
    return os.getenv("ENCLAVE_HOST_CPU_BRAND", "").strip()


def _host_gpu() -> str:
    """Host GPU model string (e.g. "NVIDIA RTX 4000 Blackwell").

    Set by `scripts/host-preset.sh` on hosts with a discrete GPU. Empty
    string indicates CPU-only inference. The SPA surfaces this in the
    system strip so the operator can see GPU acceleration is live.
    """
    return os.getenv("ENCLAVE_HOST_GPU", "").strip()


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
        "cpu": _host_cpu_brand() or "Apple M4 Pro",
        "threads": _host_cpu_cores() or 12,
        "ram_gb": _host_ram_gb(),
        "max_model_ram_gb": round(_host_ram_gb() * 0.75),
    },
}


def detect_hardware() -> dict:
    """Auto-detect which hardware profile matches this machine.

    When running in a container, `sysctl` and /proc/cpuinfo describe
    the container kernel — useless for picking the right profile.
    The host's docker-compose entry sets ENCLAVE_HOST_CPU_BRAND /
    ENCLAVE_HOST_RAM_GB / ENCLAVE_HOST_CPU_CORES / ENCLAVE_HOST_GPU
    via scripts/host-preset.sh, so we prefer those when present and
    fall back to native detection only outside containers.
    """
    import platform

    host_cpu = os.environ.get("ENCLAVE_HOST_CPU_BRAND", "").strip()
    host_ram = os.environ.get("ENCLAVE_HOST_RAM_GB", "").strip()
    host_cores = os.environ.get("ENCLAVE_HOST_CPU_CORES", "").strip()
    host_gpu = os.environ.get("ENCLAVE_HOST_GPU", "").strip()
    host_platform = os.environ.get("ENCLAVE_HOST_PLATFORM", "").strip()

    cpu_brand = host_cpu
    if not cpu_brand:
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
            cpu_brand = platform.processor() or ""
    # Final fallback so the UI never shows an empty "Detected: " label.
    if not cpu_brand:
        cpu_brand = platform.processor() or platform.machine() or "unknown CPU"

    cpu_lower = cpu_brand.lower()
    try:
        total_ram = int(host_ram) if host_ram else _host_ram_gb()
    except ValueError:
        total_ram = _host_ram_gb()
    try:
        thread_count = int(host_cores) if host_cores else _host_cpu_cores()
    except ValueError:
        thread_count = _host_cpu_cores()

    # Match known profiles — keyword scan against the CPU brand string.
    if "7945hx" in cpu_lower or "bd790i" in cpu_lower:
        profile_key = "bd790i"
    elif "13900h" in cpu_lower or ("i9" in cpu_lower and total_ram <= 64):
        profile_key = "ms01"
    elif (
        "apple" in cpu_lower
        or "m4" in cpu_lower
        or "m3" in cpu_lower
        or "m2" in cpu_lower
        or host_platform == "darwin"
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
            "gpu": host_gpu or "",
        }

    profile = HARDWARE_PROFILES[profile_key].copy()
    profile["profile"] = profile_key
    # Override RAM + cores + GPU with detected values so the UI shows
    # the host's reality rather than a hardcoded profile sample.
    profile["ram_gb"] = total_ram
    profile["threads"] = thread_count
    # The profile's max_model_ram_gb is sized for the profile's *sample* RAM
    # (e.g. the bd790i spec assumes 96 GB). If this physical host actually has
    # less RAM than the sample, clamp so we never advertise a model budget the
    # box can't hold — otherwise the model-fit filter (size <= max_model_ram_gb)
    # would surface models that OOM. Preserves the invariant max_model <= ram.
    profile["max_model_ram_gb"] = min(
        profile["max_model_ram_gb"], round(total_ram * 0.75)
    )
    if host_gpu:
        profile["gpu"] = host_gpu
    # Make the CPU string explicit even on a matched profile.
    profile["cpu"] = cpu_brand or profile.get("cpu", "")
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
    }


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


@router.get("/enrichment")
async def model_enrichment():
    """Curated model enrichment — benchmark figures, role-fit profiles, and
    operator notes for the deep-dive cards. Shipped as repo data
    (data/discovery/model_benchmarks.json): privacy-first, no runtime
    phone-home; absence of a benchmark block means no credible published
    figure exists for that variant."""
    import json as _json
    from pathlib import Path as _Path

    path = _Path("data/discovery/model_benchmarks.json")
    if not path.exists():
        return {}
    try:
        return _json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"enrichment file unreadable: {e}")
        return {}


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
