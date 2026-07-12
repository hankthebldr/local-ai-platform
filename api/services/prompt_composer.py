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

    def __init__(
        self,
        roles_dir: Path,
        templates_dir: Path,
        user_roles_dir: Path | None = None,
    ):
        self.roles_dir = Path(roles_dir)
        self.templates_dir = Path(templates_dir)
        # GP-2 / P0-9 (Blocker 1): layered role resolution at RUN time — a
        # user-layer role (LB0-U3 copy-on-write, written to
        # user_storage_root/prompts/roles by prompts.py) must SHADOW the
        # shipped oob role, the same user>oob order prompts.py::_resolve uses.
        # The engine constructs PromptComposer(roles_dir, templates_dir) with
        # no user layer (that construction line stays byte-clean / frozen), so
        # when the arg is None we resolve the user layer OURSELVES via the same
        # deployment resolver prompts.py consults. A missing/undetectable dir
        # is a silent no-op (oob-only behavior, identical to before).
        if user_roles_dir is not None:
            self.user_roles_dir: Path | None = Path(user_roles_dir)
        else:
            self.user_roles_dir = self._default_user_roles_dir()
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
        prefix_locked: bool = False,
    ) -> ComposedPrompt:
        # Prefix-lock mode renders the shared `context` block FIRST so the
        # leading bytes of the system message are byte-identical across
        # sequential pseudo-parallel branches on the same model. The default
        # template puts the divergent `role` block first; that's correct for
        # one-off steps but defeats prompt-cache reuse across branches.
        if prefix_locked and template_name == "five_part.jinja":
            template_name = "five_part_prefix_locked.jinja"
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

    @staticmethod
    def _default_user_roles_dir() -> Path | None:
        """user_storage_root/prompts/roles via the deployment resolver — the
        same layer prompts.py writes copy-on-write edits into. None when no
        deployment is detected (bare unit tests), which degrades to oob-only."""
        try:
            from .deployment import _get_current

            return _get_current().user_storage_root / "prompts" / "roles"
        except Exception:  # noqa: BLE001 — no deployment / import cycle guard
            return None

    @staticmethod
    def _resolve_in_layer(base: Path, ref: str) -> Path | None:
        """Return base/<ref>.md IFF it exists AND is contained in base (per-
        layer containment: a crafted ref can never escape either root). None
        when absent so the caller can fall through to the next layer."""
        root = base.resolve()
        path = (base / f"{ref}.md").resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError(f"role_ref '{ref}' resolves outside roles directory")
        return path if path.is_file() else None

    def _load_role(self, ref: str | None, inline: str | None) -> str:
        if ref:
            cached = self._role_cache.get(ref)
            if cached is not None:
                return cached
            # Layered resolution: user shadows oob (mirrors prompts.py::_resolve).
            path: Path | None = None
            if self.user_roles_dir is not None:
                path = self._resolve_in_layer(self.user_roles_dir, ref)
            if path is None:
                # oob layer. Containment is enforced here too; a missing oob
                # file surfaces as the same read error the pre-layered code
                # raised (FileNotFoundError), preserving the caller contract.
                root = self.roles_dir.resolve()
                candidate = (self.roles_dir / f"{ref}.md").resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    raise ValueError(
                        f"role_ref '{ref}' resolves outside roles directory"
                    )
                path = candidate
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
