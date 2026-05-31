"""
Hook Bus — Protocol, data types, and dispatch for the 6-point step lifecycle.

Stages (in execution order):
  before_workflow → before_step → transform_prompt → [model call]
    → after_step → validate_output → on_failure (only if rejected)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

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

    workflow: Any = None  # WorkflowRun, forward-ref to avoid import cycle
    step: Any = None  # AgentStep | None at workflow stage
    prompt: Any = None  # ComposedPrompt | None, mutable at transform_prompt
    output: str | None = None  # raw model output, set after model call
    parsed: Any = None  # set after successful validation
    error: Any = None  # ValidationError | None, set at on_failure
    attempt: int = 0
    # Phase 4.2 (MCP & Skills) — the in-flight StepResult so hooks can
    # append instrumentation records (PluginToolCall / MCPCall /
    # SkillActivation) directly onto the run record without round-tripping
    # through the engine. None during workflow-stage hooks; populated
    # for every step-scoped dispatch from step_executor.
    step_result: Any = None


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
    "before_workflow",
    "before_step",
    "transform_prompt",
    "after_step",
    "validate_output",
    "on_failure",
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
        # Fast path: 4-of-6 stages are typically empty on a given step
        # (e.g. before_workflow only fires on workflow start). Skip the
        # sort + tuple unpacking when nothing is registered.
        hooks_for_stage = self._hooks[stage]
        if not hooks_for_stage:
            return []
        ordered = sorted(hooks_for_stage, key=lambda t: (t[0], t[1]))
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


# ── Registration decorator + auto-discovery ────────────────────────────────

import importlib.util
import sys
from pathlib import Path as _Path

# Module-level registry of decorated hooks, keyed by absolute path of declaring file.
# Populated when files are imported; consumed by HookBus.discover_and_register.
_PENDING_HOOKS: list = []


def register_hook(stage: Stage, name: str):
    """Decorator to mark a function as a hook for auto-discovery."""
    if stage not in _VALID_STAGES:
        raise ValueError(f"invalid stage: {stage!r}")

    def _decorate(fn):
        fn.stage = stage
        fn.name = name
        _PENDING_HOOKS.append(fn)
        return fn

    return _decorate


def _extend_HookBus_discovery():
    def discover_and_register(self, directory, source: str = "custom") -> int:
        """Import every *.py file under `directory` (non-recursive) and register
        any functions decorated with @register_hook. Returns count registered."""
        directory = _Path(directory)
        if not directory.is_dir():
            return 0
        before = len(_PENDING_HOOKS)
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("__") or py_file.name == ".gitkeep":
                continue
            module_name = f"_hooks_auto_{py_file.stem}_{id(py_file)}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        newly_added = _PENDING_HOOKS[before:]
        for hook in newly_added:
            self.register(hook, source=source)
        # Clear what we just registered so a second bus doesn't double-register
        del _PENDING_HOOKS[before:]
        return len(newly_added)

    HookBus.discover_and_register = discover_and_register


_extend_HookBus_discovery()
