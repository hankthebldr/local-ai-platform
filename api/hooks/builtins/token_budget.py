"""
token_budget hook — estimates prompt tokens and truncates the Context section
when the prompt would exceed the configured budget.

Never truncates Task or Constraints — those are load-bearing.
Stage: before_step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from api.services.hook_bus import HookContext, HookResult


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate. Tries tiktoken, falls back to chars/4."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


@dataclass
class TokenBudgetHook:
    max_prompt_tokens: int = 3500
    reserve_for_output: int = 1024

    name: str = "token_budget"
    stage: str = "before_step"

    def __call__(self, ctx: HookContext) -> HookResult:
        if ctx.prompt is None:
            return HookResult(action="continue")

        budget = max(1, self.max_prompt_tokens - self.reserve_for_output)
        system = ctx.prompt.system or ""
        user = ctx.prompt.user or ""
        total = _estimate_tokens(system) + _estimate_tokens(user)

        if total <= budget:
            return HookResult(action="continue")

        new_system = self._truncate_context_block(system, budget - _estimate_tokens(user))
        ctx.prompt.system = new_system
        return HookResult(action="continue")

    @staticmethod
    def _truncate_context_block(system: str, allowed_tokens: int) -> str:
        """Shrink the '## Context' section to fit. Task/Constraints/OutputFormat untouched."""
        context_match = re.search(r"(## Context\s*\n)(.*?)(?=\n## (?:Task|Constraints|Output Format)\b|$)", system, re.DOTALL)
        if not context_match:
            return system
        before = system[: context_match.start(2)]
        after = system[context_match.end(2):]
        ctx_body = context_match.group(2)

        fixed_tokens = _estimate_tokens(before) + _estimate_tokens(after)
        remaining = max(100, allowed_tokens - fixed_tokens)
        chars_per_token = max(1, len(ctx_body) // max(1, _estimate_tokens(ctx_body)))
        max_chars = remaining * chars_per_token
        if len(ctx_body) > max_chars:
            ctx_body = ctx_body[:max_chars] + "\n…[truncated for token budget]…\n"
        return before + ctx_body + after
