#!/usr/bin/env python3
"""
Model Registry Router — runner-aware, UI-ready model selection.

`/v1/models` is the OpenAI-compatible flat list. This endpoint is the
selection surface: it groups models by the live inference runner that serves
them (Ollama fallback vs. vLLM/Blackwell performance path) and emits a flat,
dropdown-ready `options` list plus a sensible `default`.

Closes C1 of docs/plans/2026-07-09-fusion-autonomous-local-workspace-feature-request.md:
the operator (or any UI, incl. a LangGraph run-config) can pick *which local
engine + model* a run uses, instead of the model being a hidden code constant.

The `value` for each option is `"<runner>/<model>"` — the same provider/model
convention opencode/OpenWork use — so a run-config can carry the choice
unambiguously and the platform can dispatch it via the RunnerRegistry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ..logging_config import logger

router = APIRouter(prefix="/api", tags=["models"])

# Runner preference when the operator hasn't pinned ENCLAVE_PREFERRED_RUNNER:
# vLLM is the Blackwell performance path on this box, so it's the sensible
# default chat engine; Ollama is the fallback.
_DEFAULT_RUNNER_ORDER = ["vllm", "ollama"]


def _quant_label(quant: Optional[str]) -> str:
    return f" ({quant.upper()})" if quant else ""


def _is_embedding(option: Dict[str, Any]) -> bool:
    """Embedding models (nomic-embed-text, bge, all-minilm, …) must never be
    the default *chat* model — they can't drive a conversation."""
    mid = option.get("model", "").lower()
    return any(tag in mid for tag in ("embed", "bge", "minilm"))


def _pick_default(options: List[Dict[str, Any]], preferred: Optional[str]) -> Optional[str]:
    """First reachable, non-embedding model — trying the preferred runner, then
    the Blackwell/vLLM performance path, then Ollama, then anything reachable."""
    def first_for(runner: Optional[str]) -> Optional[str]:
        return next(
            (
                o["value"]
                for o in options
                if o["reachable"]
                and not _is_embedding(o)
                and (runner is None or o["runner"] == runner)
            ),
            None,
        )

    # order: pinned preferred runner (if any) → vLLM/Blackwell → Ollama →
    # any reachable non-embedding model (None = no runner filter).
    order = ([preferred] if preferred else []) + _DEFAULT_RUNNER_ORDER + [None]
    for runner in order:
        value = first_for(runner)
        if value:
            return value
    return None


def _runner_payload(kind_value: str, runner) -> Dict[str, Any]:
    """Probe one runner's health + model list. Never raises — a dead runner
    yields reachable:false with an empty model list so the endpoint still 200s."""
    reachable = False
    version: Optional[str] = None
    models: List[Dict[str, Any]] = []
    error: Optional[str] = None

    try:
        health = runner.health()
        reachable = bool(getattr(health, "reachable", False))
        version = getattr(health, "version", None)
    except Exception as e:  # health probe must never 500 the endpoint
        error = str(e)

    if reachable:
        try:
            for m in runner.list_models():
                quant = getattr(m, "quant", None)
                models.append(
                    {
                        "id": m.id,
                        "family": getattr(m, "family", None),
                        "quant": quant.value if hasattr(quant, "value") else quant,
                        "context_window": getattr(m, "context_window", None),
                        "size_gb": getattr(m, "size_gb", None),
                    }
                )
        except Exception as e:  # a serving runner that fails to list → log, empty
            logger.warning("list_models failed for runner %s: %s", kind_value, e)
            error = error or str(e)

    return {
        "runner": kind_value,
        "reachable": reachable,
        "base_url": getattr(runner, "base_url", None),
        "version": version,
        "capabilities": {
            "continuous_batching": getattr(
                runner, "supports_continuous_batching", False
            ),
            "keep_alive": getattr(runner, "supports_keep_alive", False),
            "quantizations": [
                q.value if hasattr(q, "value") else q
                for q in getattr(runner, "supports_quantizations", [])
            ],
        },
        "models": models,
        **({"error": error} if error else {}),
    }


@router.get("/models")
def list_models_by_runner() -> Dict[str, Any]:
    """List selectable models grouped by live runner, with a UI-ready flat
    `options` list and a `default` selection.

    503 if the RunnerRegistry was never populated (detect_runners didn't run —
    degraded startup), mirroring /api/system/runner.
    """
    from ..services.runner_registry import get_current_registry

    try:
        registry = get_current_registry()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    preferred = getattr(registry, "preferred_runner", None)
    preferred_value = preferred.value if preferred else None

    runners: List[Dict[str, Any]] = []
    options: List[Dict[str, Any]] = []
    for kind in sorted(registry.kinds(), key=lambda k: k.value):
        payload = _runner_payload(kind.value, registry.get(kind))
        runners.append(payload)
        for m in payload["models"]:
            options.append(
                {
                    "value": f"{payload['runner']}/{m['id']}",
                    "runner": payload["runner"],
                    "model": m["id"],
                    "label": f"{m['id']} — {payload['runner']}{_quant_label(m['quant'])}",
                    "reachable": payload["reachable"],
                    "context_window": m["context_window"],
                }
            )

    default = _pick_default(options, preferred_value)

    return {
        "runners": runners,
        "options": options,
        "default": default,
        "preferred_runner": preferred_value,
    }
