import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.token_budget import TokenBudgetHook


def test_passes_when_under_budget():
    hook = TokenBudgetHook(max_prompt_tokens=1000, reserve_for_output=500)
    prompt = ComposedPrompt(system="short", user="short", params={})
    ctx = HookContext(prompt=prompt)
    result = hook(ctx)
    assert result.action == "continue"
    assert ctx.prompt.system == "short"


def test_truncates_context_when_over_budget():
    hook = TokenBudgetHook(max_prompt_tokens=100, reserve_for_output=20)
    system = (
        "ROLE_TEXT\n\n## Context\n"
        + ("filler words " * 200)
        + "\n\n## Task\nDO THE TASK\n\n## Constraints\n- be terse"
    )
    prompt = ComposedPrompt(system=system, user="usr", params={})
    ctx = HookContext(prompt=prompt)
    result = hook(ctx)
    assert result.action == "continue"
    assert "## Task" in ctx.prompt.system
    assert "DO THE TASK" in ctx.prompt.system
    assert "## Constraints" in ctx.prompt.system
    assert "be terse" in ctx.prompt.system
    assert len(ctx.prompt.system) < len(system)


def test_never_truncates_task_or_constraints():
    hook = TokenBudgetHook(max_prompt_tokens=50, reserve_for_output=10)
    system = (
        "ROLE\n\n## Context\nsmall\n\n## Task\n"
        + ("do " * 100)
        + "\n\n## Constraints\n- rule one"
    )
    prompt = ComposedPrompt(system=system, user="usr", params={})
    ctx = HookContext(prompt=prompt)
    hook(ctx)
    assert ("do " * 100) in ctx.prompt.system or "do do do" in ctx.prompt.system
    assert "- rule one" in ctx.prompt.system


def test_name_and_stage():
    hook = TokenBudgetHook()
    assert hook.name == "token_budget"
    assert hook.stage == "before_step"


def test_handles_missing_prompt_gracefully():
    hook = TokenBudgetHook(max_prompt_tokens=100, reserve_for_output=20)
    ctx = HookContext(prompt=None)
    result = hook(ctx)
    assert result.action == "continue"
