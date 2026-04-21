"""
Model-Family Adapters — Small per-family tweaks to prompts and Ollama params.

Lookup is keyed by substring match on the resolved Ollama model name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .prompt_composer import ComposedPrompt


@dataclass
class ModelAdapter:
    """Base adapter. Subclasses override methods to add family behavior."""
    family: str = "default"

    def prepare(
        self, prompt: ComposedPrompt, params: dict[str, Any]
    ) -> tuple[ComposedPrompt, dict[str, Any]]:
        """Return possibly-mutated prompt + final Ollama params."""
        return prompt, params

    def refusal_signatures(self) -> list[str]:
        """Patterns refusal_detector uses for this family."""
        return []

    def stop_sequences(self) -> list[str]:
        return []


class DefaultAdapter(ModelAdapter):
    family = "default"


# ── Registry ────────────────────────────────────────────────────────────────

_FAMILY_PATTERNS: list[tuple[re.Pattern, type]] = []  # populated below


def _register(pattern: str, adapter_cls: type) -> None:
    _FAMILY_PATTERNS.append((re.compile(pattern, re.IGNORECASE), adapter_cls))


def resolve_adapter(model_name: str) -> ModelAdapter:
    """Return the adapter instance for a given Ollama model name."""
    for pat, cls in _FAMILY_PATTERNS:
        if pat.search(model_name):
            return cls()
    return DefaultAdapter()
