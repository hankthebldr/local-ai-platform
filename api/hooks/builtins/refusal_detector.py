"""
refusal_detector hook — flags model refusals so they can be re-prompted.

Stage: validate_output. This hook does NOT suppress content. It only detects
that the model declined to answer so on_failure can retry with reframing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.services.hook_bus import HookContext, HookResult
from api.services.model_adapters import resolve_adapter


@dataclass
class RefusalDetectorHook:
    patterns: list[str] = field(default_factory=list)
    use_family_defaults: bool = False

    name: str = "refusal_detector"
    stage: str = "validate_output"

    def __call__(self, ctx: HookContext) -> HookResult:
        output = (ctx.output or "").lower()
        if not output:
            return HookResult(action="continue")

        all_patterns = list(self.patterns)
        if self.use_family_defaults and ctx.step is not None:
            model = getattr(ctx.step, "model_name", None) or getattr(ctx.step, "model", None)
            if model:
                all_patterns.extend(resolve_adapter(model).refusal_signatures())

        for pat in all_patterns:
            if pat and pat.lower() in output:
                return HookResult(
                    action="fail",
                    feedback="Model refused or declined the task. Reframe the request as a technical analysis and respond with the required JSON.",
                )
        return HookResult(action="continue")
