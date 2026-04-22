"""
retry_with_feedback hook — rewrites the user prompt with validation feedback
and (optionally) escalates to a larger model on subsequent attempts.

Stage: on_failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.services.hook_bus import HookContext, HookResult


@dataclass
class ValidationFailure:
    """Carrier used by validate_output hooks to communicate failure reasons."""
    feedback: str


@dataclass
class RetryWithFeedbackHook:
    max_attempts: int = 2
    include_example: bool = False
    escalate_to: str | None = None

    name: str = "retry_with_feedback"
    stage: str = "on_failure"

    def __call__(self, ctx: HookContext) -> HookResult:
        if ctx.attempt >= self.max_attempts:
            return HookResult(action="fail")

        feedback = ""
        if isinstance(ctx.error, ValidationFailure):
            feedback = ctx.error.feedback
        elif ctx.error:
            feedback = str(ctx.error)

        prior = ctx.output or ""
        retry_block = (
            "\n\nYour previous response was rejected.\n"
            f"Previous output:\n{prior}\n\n"
            f"Validation error: {feedback}\n\n"
            "Return a new response that strictly satisfies the output schema. "
            "Do not include prose, markdown fences, or commentary."
        )

        if self.include_example and ctx.attempt >= 1:
            retry_block += (
                "\n\n## Example of a valid response shape\n"
                "{\n  \"<key_from_schema>\": <value>,\n  ...\n}\n"
            )

        if ctx.prompt is not None:
            ctx.prompt.user = (ctx.prompt.user or "") + retry_block

        mutations: dict = {}
        if self.escalate_to:
            mutations["escalate_to"] = self.escalate_to

        return HookResult(action="retry", mutations=mutations)
