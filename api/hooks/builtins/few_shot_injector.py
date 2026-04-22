"""
few_shot_injector hook — appends example input/output pairs to the prompt.

Stage: transform_prompt. Opt-in per step via YAML `hooks.transform_prompt`.
Examples live in `{example_dir}/{step_id}/*.json` with shape:
  {"input": "...", "output": {...}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from api.services.hook_bus import HookContext, HookResult


@dataclass
class FewShotInjectorHook:
    example_dir: str | Path
    max_examples: int = 1

    name: str = "few_shot_injector"
    stage: str = "transform_prompt"

    def __call__(self, ctx: HookContext) -> HookResult:
        if ctx.prompt is None or ctx.step is None:
            return HookResult(action="continue")

        step_id = getattr(ctx.step, "id", None)
        if not step_id:
            return HookResult(action="continue")

        base = Path(self.example_dir) / step_id
        if not base.is_dir():
            return HookResult(action="continue")

        examples = sorted(base.glob("*.json"))[: self.max_examples]
        if not examples:
            return HookResult(action="continue")

        blocks = []
        for ex_path in examples:
            try:
                ex = json.loads(ex_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            blocks.append(
                "## Example\n"
                f"Input: {ex.get('input', '')}\n"
                f"Output: {json.dumps(ex.get('output', {}), indent=2)}"
            )

        if not blocks:
            return HookResult(action="continue")

        ctx.prompt.system = ctx.prompt.system.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"
        return HookResult(action="continue")
