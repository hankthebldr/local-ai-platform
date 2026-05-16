"""
Model Resolver — Maps roles to available models via inventory

Uses the existing OllamaService to query available models and resolves
role-based references (reasoning, fast, coding, etc.) to concrete model names.
"""

from typing import Dict, List, Optional

from ..logging_config import logger
from ..exceptions import ModelResolutionError, ModelNotFoundError
from .ollama_service import OllamaService


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


class ModelResolver:
    """Resolves model references (explicit or role-based) to concrete model names"""

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service

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
        available = self.ollama.list_models()
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
        available = self.ollama.list_models()

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
