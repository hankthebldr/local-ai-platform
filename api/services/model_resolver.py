"""
Model Resolver — Maps roles to available models via inventory

Uses the existing OllamaService to query available models and resolves
role-based references (reasoning, fast, coding, etc.) to concrete model names.
"""

import os
import time
from typing import Dict, List, Optional

from ..logging_config import logger
from ..exceptions import ModelResolutionError, ModelNotFoundError
from .ollama_service import OllamaService
from .runner import RunnerKind

# ── Role → Model Mapping ──────────────────────────────────────────────────
# Models are matched by substring in their name. Order = preference (first match wins).
# Larger models are preferred when multiple match.

ROLE_PATTERNS: Dict[str, List[str]] = {
    "reasoning": ["deepseek-r1", "qwen3", "qwen2.5-coder", "nous-hermes"],
    "fast": ["dolphin3:8b", "mistral", "phi"],
    "coding": ["qwen3.5", "qwen2.5-coder", "deepseek-coder", "codellama", "dolphin"],
    "uncensored": ["dolphin", "uncensored", "abliterated", "nous-hermes"],
    "general": ["dolphin", "qwen", "mistral", "llama"],
}


# Per-process cache TTL for ollama.list_models(). Each workflow step
# previously paid one /api/tags round-trip for resolve() — a 10-step
# DAG that all run inside a few seconds was making 10 identical
# requests. 30 s is short enough that a freshly-pulled model becomes
# resolvable within half a minute without restarting the engine.
_LIST_MODELS_TTL = float(os.getenv("MODEL_LIST_TTL", "30"))


class ModelResolver:
    """Resolves model references (explicit or role-based) to concrete model names"""

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service
        self._models_cache: Optional[List[Dict]] = None
        self._models_cache_ts: float = 0.0
        # Phase 1.3 of gpu-runner-abstraction: attached post-init by callers
        # that want runner-aware dispatch. Existing call sites that use the
        # legacy resolve() -> str path don't need to attach anything.
        self._runner_registry = None  # type: ignore[assignment]
        self._model_registry: Optional[Dict[str, Dict]] = None

    def attach_runner_registry(self, registry) -> None:  # type: ignore[no-untyped-def]
        """Attach a RunnerRegistry so resolve_with_runner() can dispatch.

        Optional — only callers that need runner-aware dispatch must call
        this. Legacy resolve() -> str path remains untouched.
        """
        self._runner_registry = registry

    def attach_model_registry(self, registry: Dict[str, Dict]) -> None:
        """Attach the MODEL_REGISTRY (from models/download.py) so
        resolve_with_runner() can read the `runner` field per model id.

        Decoupled from the import so tests can stub it without touching
        the real registry, and so a future fleet feature can override
        per-host. If unattached, resolve_with_runner() defaults every model
        to the OLLAMA runner (matches current behavior).
        """
        self._model_registry = registry

    def resolve_with_runner(
        self,
        model: Optional[str] = None,
        role: Optional[str] = None,
        default_role: str = "general",
    ):
        """Runner-aware variant of resolve().

        Returns a (Runner, model_name) tuple. The Runner is chosen by
        looking up the resolved model id in the attached MODEL_REGISTRY
        and reading its `runner` field (default: ollama). If no model
        registry is attached, every model dispatches to the OLLAMA runner.

        Phase 1.3 — additive, non-breaking. Existing resolve() callers
        keep returning str. New callers (Phase 4 step_executor migration)
        opt into the tuple form.

        Raises RuntimeError if no RunnerRegistry has been attached.
        """
        if self._runner_registry is None:
            raise RuntimeError(
                "resolve_with_runner() requires attach_runner_registry() "
                "to be called first. See docs/plans/2026-05-23-gpu-runner-"
                "abstraction.md Phase 1.3."
            )

        # Short-circuit: if the model is explicitly pinned and the attached
        # MODEL_REGISTRY says it belongs to a non-Ollama runner, skip the
        # Ollama /api/tags validation entirely — that endpoint will not
        # know about vLLM-served weights. Trust the registry.
        if model and self._model_registry is not None:
            entry = self._model_registry.get(model)
            if entry is not None:
                from .runner_registry import runner_for_registry_entry

                kind = runner_for_registry_entry(entry)
                if kind != RunnerKind.OLLAMA:
                    runner = self._runner_registry.for_entry(entry)
                    return runner, model

        # Default path: resolve via the existing Ollama-backed lookup, then
        # consult the registry for runner dispatch (defaults to OLLAMA).
        model_name = self.resolve(model=model, role=role, default_role=default_role)
        entry = {}  # type: ignore[assignment]
        if self._model_registry is not None:
            entry = self._model_registry.get(model_name) or {}
            if not entry and model:
                entry = self._model_registry.get(model) or {}
        runner = self._runner_registry.for_entry(entry)
        return runner, model_name

    def _list_models_cached(self) -> List[Dict]:
        """Return ollama.list_models() with a short TTL cache."""
        now = time.monotonic()
        if (
            self._models_cache is not None
            and (now - self._models_cache_ts) < _LIST_MODELS_TTL
        ):
            return self._models_cache
        models = self.ollama.list_models()
        self._models_cache = models
        self._models_cache_ts = now
        return models

    def invalidate_cache(self) -> None:
        """Drop the cached model list (e.g. after a pull/delete)."""
        self._models_cache = None
        self._models_cache_ts = 0.0

    def resolve(
        self,
        model: Optional[str] = None,
        role: Optional[str] = None,
        default_role: str = "general",
    ) -> str:
        """
        Resolve a model reference to a concrete model name.

        Priority:
        1. Explicit model name — validate it exists; on miss, fall through
           to role-based resolution if a role is provided. Without this
           fallback, an agent that pins a model the operator doesn't
           have installed (e.g. xsiam-analyst pins deepseek-r1:32b @ 19GB)
           is unusable until that model is pulled. With the fallback,
           the agent runs against the best available match for its role.
        2. Role-based resolution — find best matching available model.
        3. Default role — fallback ("general" matches almost anything).
        """
        if model:
            try:
                return self._resolve_explicit(model)
            except ModelNotFoundError:
                if role:
                    logger.warning(
                        f"Pinned model '{model}' not installed; falling back to "
                        f"role '{role}'. Pull '{model}' for the agent's preferred model."
                    )
                    return self._resolve_role(role)
                raise

        effective_role = role or default_role
        return self._resolve_role(effective_role)

    def _resolve_explicit(self, model: str) -> str:
        """Validate an explicit model name exists in Ollama"""
        available = self._list_models_cached()
        names = [m["name"] for m in available]

        if model in names:
            return model

        # Try partial match (e.g., "qwen3.5" matches "qwen3.5-uncensored:35b")
        for name in names:
            if model in name:
                logger.info(f"Model '{model}' resolved to '{name}' via partial match")
                return name

        raise ModelNotFoundError(model)

    def _resolve_role(self, role: str) -> str:
        """Resolve a role to the best available model"""
        available = self._list_models_cached()

        if not available:
            raise ModelResolutionError(role)

        patterns = ROLE_PATTERNS.get(role, ROLE_PATTERNS["general"])

        # Score each available model against role patterns
        candidates = []
        for model_info in available:
            name = model_info["name"].lower()
            size = model_info.get("size", 0)
            for i, pattern in enumerate(patterns):
                if pattern.lower() in name:
                    # Lower pattern index = higher preference, larger size = better
                    candidates.append((model_info["name"], i, size))
                    break

        if not candidates:
            # No pattern match — fall back to largest available model
            largest = max(available, key=lambda m: m.get("size", 0))
            logger.warning(
                f"No model matched role '{role}', falling back to largest: {largest['name']}"
            )
            return largest["name"]

        # Sort: lowest pattern index first, then largest size
        candidates.sort(key=lambda c: (c[1], -c[2]))
        chosen = candidates[0][0]
        logger.info(
            f"Role '{role}' resolved to '{chosen}' (from {len(candidates)} candidates)"
        )
        return chosen
