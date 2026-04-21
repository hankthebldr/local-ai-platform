"""
Prompt Composer — Assembles 5-part prompts from workflow YAML.

Five parts: role, context, task, constraints, output_format.
Composition pipeline:
  load role → merge context → render template → return ComposedPrompt.

Model-family adapters mutate ComposedPrompt AFTER composition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComposedPrompt:
    """A prompt ready to send to an Ollama model."""
    system: str
    user: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]
