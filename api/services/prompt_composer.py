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


# ── PromptComposer ─────────────────────────────────────────────────────────

import json as _json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


class PromptComposer:
    """Composes a 5-part prompt from role, context, task, constraints, schema."""

    def __init__(self, roles_dir: Path, templates_dir: Path):
        self.roles_dir = Path(roles_dir)
        self.templates_dir = Path(templates_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(disabled_extensions=("jinja",), default=False),
            trim_blocks=False,
            lstrip_blocks=False,
        )
        # Cache of role_ref → role text. Roles are small markdown files
        # that don't change mid-process; re-reading them on every step
        # was wasted disk I/O (10-step workflows hit the same role 10x).
        self._role_cache: dict[str, str] = {}

    def compose(
        self,
        role_ref: str | None,
        role_inline: str | None,
        context: str,
        task: str,
        constraints: list[str],
        output_schema: dict,
        resolved_inputs: dict | None = None,
        few_shot_example: dict | None = None,
        template_name: str = "five_part.jinja",
        params: dict | None = None,
    ) -> ComposedPrompt:
        role_text = self._load_role(role_ref, role_inline)
        few_shot_rendered = None
        if few_shot_example:
            few_shot_rendered = {
                "input": few_shot_example.get("input", ""),
                "output_json": _json.dumps(
                    few_shot_example.get("output", {}), indent=2
                ),
            }

        template = self._env.get_template(template_name)
        system = template.render(
            role=role_text.strip(),
            context=context or "",
            task=task or "",
            constraints=constraints or [],
            output_schema_json=_json.dumps(output_schema or {}, indent=2),
            few_shot_example=few_shot_rendered,
        )

        user = self._build_user_message(resolved_inputs or {})
        return ComposedPrompt(system=system, user=user, params=params or {})

    def _load_role(self, ref: str | None, inline: str | None) -> str:
        if ref:
            cached = self._role_cache.get(ref)
            if cached is not None:
                return cached
            roles_root = self.roles_dir.resolve()
            path = (self.roles_dir / f"{ref}.md").resolve()
            # Containment check: reject role_ref values that escape roles_dir
            try:
                path.relative_to(roles_root)
            except ValueError:
                raise ValueError(f"role_ref '{ref}' resolves outside roles directory")
            text = path.read_text(encoding="utf-8")
            self._role_cache[ref] = text
            return text
        if inline:
            return inline
        raise ValueError("PromptComposer.compose requires role_ref or role_inline")

    def _build_user_message(self, inputs: dict) -> str:
        if not inputs:
            return "Complete your assigned task."
        lines = ["## Inputs\n"]
        for key, value in inputs.items():
            if isinstance(value, (dict, list)):
                lines.append(
                    f"### {key}\n```json\n{_json.dumps(value, indent=2)}\n```\n"
                )
            else:
                lines.append(f"### {key}\n{value}\n")
        lines.append("\nComplete your assigned task using the inputs above.")
        return "\n".join(lines)
