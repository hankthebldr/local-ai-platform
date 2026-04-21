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
