"""
Hook Bus — Protocol, data types, and dispatch for the 6-point step lifecycle.

Stages (in execution order):
  before_workflow → before_step → transform_prompt → [model call]
    → after_step → validate_output → on_failure (only if rejected)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, runtime_checkable


Stage = Literal[
    "before_workflow",
    "before_step",
    "transform_prompt",
    "after_step",
    "validate_output",
    "on_failure",
]

Action = Literal["continue", "retry", "fail", "skip"]


@dataclass
class HookContext:
    """Mutable context passed to every hook invocation."""
    workflow: Any = None                  # WorkflowRun, forward-ref to avoid import cycle
    step: Any = None                      # AgentStep | None at workflow stage
    prompt: Any = None                    # ComposedPrompt | None, mutable at transform_prompt
    output: str | None = None             # raw model output, set after model call
    parsed: Any = None                    # set after successful validation
    error: Any = None                     # ValidationError | None, set at on_failure
    attempt: int = 0


@dataclass
class HookResult:
    """Hook return value. `action` drives dispatcher behavior."""
    action: Action = "continue"
    mutations: dict = field(default_factory=dict)
    feedback: str | None = None


@runtime_checkable
class Hook(Protocol):
    """Any callable with `name` and `stage` attributes matching this signature."""
    name: str
    stage: Stage
    def __call__(self, ctx: HookContext) -> HookResult: ...


# ── HookBus ────────────────────────────────────────────────────────────────

_VALID_STAGES = {
    "before_workflow", "before_step", "transform_prompt",
    "after_step", "validate_output", "on_failure",
}


class HookBus:
    """Registers and dispatches hooks by stage.

    Dispatch rules:
    - Same-stage hooks run in registration order.
    - Built-in hooks (source='builtin') run before custom hooks (source='custom').
    - First hook returning action != 'continue' short-circuits the remainder.
    """

    def __init__(self) -> None:
        self._hooks: dict[Stage, list[tuple[int, int, Hook]]] = {
            stage: [] for stage in _VALID_STAGES
        }
        # priority: 0 = builtin, 1 = custom — sorted ascending on dispatch
        self._counter = 0

    def register(self, hook, source: str = "builtin") -> None:
        stage = getattr(hook, "stage", None)
        if stage not in _VALID_STAGES:
            raise ValueError(f"invalid stage: {stage!r}")
        priority = 0 if source == "builtin" else 1
        self._counter += 1
        # tuple (priority, insertion_order, hook) — stable sort respects insertion
        self._hooks[stage].append((priority, self._counter, hook))

    def dispatch(self, stage: Stage, ctx: HookContext) -> list[HookResult]:
        if stage not in _VALID_STAGES:
            raise ValueError(f"invalid stage: {stage!r}")
        ordered = sorted(self._hooks[stage], key=lambda t: (t[0], t[1]))
        results: list[HookResult] = []
        for _priority, _order, hook in ordered:
            result = hook(ctx)
            results.append(result)
            # apply mutations to ctx
            for k, v in (result.mutations or {}).items():
                setattr(ctx, k, v)
            if result.action != "continue":
                break
        return results

    def clear(self) -> None:
        for stage in self._hooks:
            self._hooks[stage] = []
        self._counter = 0
