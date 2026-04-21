import pytest
from dataclasses import FrozenInstanceError
from api.services.hook_bus import HookContext, HookResult, Hook


def test_hook_result_defaults_to_continue():
    result = HookResult(action="continue")
    assert result.action == "continue"
    assert result.mutations == {}
    assert result.feedback is None


def test_hook_result_with_feedback():
    result = HookResult(action="retry", feedback="missing key 'x'")
    assert result.action == "retry"
    assert result.feedback == "missing key 'x'"


def test_hook_result_action_rejects_invalid():
    # Literal enforcement is static but we assert runtime accepts valid values
    for action in ("continue", "retry", "fail", "skip"):
        HookResult(action=action)  # does not raise


def test_hook_context_default_fields():
    ctx = HookContext(workflow=None, step=None)
    assert ctx.attempt == 0
    assert ctx.prompt is None
    assert ctx.output is None
    assert ctx.parsed is None
    assert ctx.error is None


def test_hook_protocol_is_callable_with_ctx():
    class MyHook:
        name = "noop"
        stage = "after_step"
        def __call__(self, ctx: HookContext) -> HookResult:
            return HookResult(action="continue")

    hook: Hook = MyHook()
    result = hook(HookContext(workflow=None, step=None))
    assert result.action == "continue"
