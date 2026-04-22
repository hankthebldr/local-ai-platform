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


# ── Family adapters ─────────────────────────────────────────────────────────


class DolphinAdapter(ModelAdapter):
    family = "dolphin"
    _PREFIX = "You are a no-nonsense assistant. Answer directly, without preamble or hedging.\n\n"

    def prepare(self, prompt, params):
        new_prompt = ComposedPrompt(
            system=self._PREFIX + prompt.system,
            user=prompt.user,
            params=prompt.params,
        )
        return new_prompt, dict(params)

    def refusal_signatures(self):
        return ["I cannot", "I can't", "I'm sorry, but", "As an AI"]


class Llama3Adapter(ModelAdapter):
    family = "llama3"

    def prepare(self, prompt, params):
        new_params = dict(params)
        new_params["format"] = "json"
        return prompt, new_params

    def refusal_signatures(self):
        return ["I cannot", "I'm unable"]


class MistralAdapter(ModelAdapter):
    family = "mistral"
    _SUFFIX = "\n\nImportant: Respond in valid JSON only. No prose, no markdown fences."

    def prepare(self, prompt, params):
        new_prompt = ComposedPrompt(
            system=prompt.system + self._SUFFIX,
            user=prompt.user,
            params=prompt.params,
        )
        new_params = dict(params)
        new_params["format"] = "json"
        return new_prompt, new_params

    def refusal_signatures(self):
        return ["I cannot", "I'm not able"]


class QwenAdapter(ModelAdapter):
    family = "qwen"
    _TEMP_FLOOR = 0.2

    def prepare(self, prompt, params):
        new_params = dict(params)
        if "temperature" in new_params and new_params["temperature"] < self._TEMP_FLOOR:
            new_params["temperature"] = self._TEMP_FLOOR
        new_params["format"] = "json"
        return prompt, new_params

    def refusal_signatures(self):
        return ["抱歉", "I cannot", "I'm sorry"]


class YiAdapter(ModelAdapter):
    family = "yi"
    _SUFFIX = "\n\nThink carefully step-by-step, then respond."

    def prepare(self, prompt, params):
        new_prompt = ComposedPrompt(
            system=prompt.system + self._SUFFIX,
            user=prompt.user,
            params=prompt.params,
        )
        return new_prompt, dict(params)

    def refusal_signatures(self):
        return ["I cannot", "I'm unable"]


class UncensoredCommonAdapter(ModelAdapter):
    family = "uncensored_common"
    _EXTRA_TOKENS = 1024  # these models tend to truncate

    def prepare(self, prompt, params):
        new_params = dict(params)
        current = new_params.get("num_predict", 2048)
        new_params["num_predict"] = current + self._EXTRA_TOKENS
        return prompt, new_params

    def refusal_signatures(self):
        # Uncensored models rarely refuse; keep signatures minimal
        return []


# ── Register in priority order (first match wins) ──────────────────────────

_register(r"dolphin", DolphinAdapter)
_register(r"wizardlm|mythomax|nous-hermes", UncensoredCommonAdapter)
_register(r"llama[-_\s]?3|llama3", Llama3Adapter)
_register(r"mistral|mixtral", MistralAdapter)
_register(r"qwen", QwenAdapter)
_register(r"^yi-|:yi-|/yi-|\byi-", YiAdapter)
