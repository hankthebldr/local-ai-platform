import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook


def _base_ctx(attempt=0, feedback="missing key 'foo'"):
    from api.hooks.builtins.retry_with_feedback import ValidationFailure
    prompt = ComposedPrompt(system="SYS", user="USR", params={})
    return HookContext(
        prompt=prompt,
        output='{"x": 1}',
        error=ValidationFailure(feedback=feedback),
        attempt=attempt,
    )


def test_first_failure_returns_retry_with_feedback_appended():
    hook = RetryWithFeedbackHook(max_attempts=2)
    ctx = _base_ctx(attempt=0)
    result = hook(ctx)
    assert result.action == "retry"
    assert "missing key 'foo'" in ctx.prompt.user
    assert "previous response" in ctx.prompt.user.lower() or "previous output" in ctx.prompt.user.lower()


def test_max_attempts_respected_returns_fail():
    hook = RetryWithFeedbackHook(max_attempts=2)
    ctx = _base_ctx(attempt=2)  # already at max
    result = hook(ctx)
    assert result.action == "fail"


def test_second_attempt_adds_example_when_enabled():
    hook = RetryWithFeedbackHook(max_attempts=2, include_example=True)
    ctx = _base_ctx(attempt=1)
    result = hook(ctx)
    assert result.action == "retry"
    assert "Example" in ctx.prompt.user or "example" in ctx.prompt.user


def test_no_example_when_disabled():
    hook = RetryWithFeedbackHook(max_attempts=2, include_example=False)
    ctx = _base_ctx(attempt=1)
    hook(ctx)
    assert "## Example" not in ctx.prompt.user


def test_escalate_to_sets_mutation():
    hook = RetryWithFeedbackHook(max_attempts=2, escalate_to="reasoning")
    ctx = _base_ctx(attempt=1)
    result = hook(ctx)
    assert result.action == "retry"
    assert result.mutations.get("escalate_to") == "reasoning"


def test_name_and_stage():
    hook = RetryWithFeedbackHook()
    assert hook.name == "retry_with_feedback"
    assert hook.stage == "on_failure"
