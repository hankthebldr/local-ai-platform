import pytest
from api.services.hook_bus import HookContext
from api.hooks.builtins.refusal_detector import RefusalDetectorHook


class FakeStep:
    def __init__(self, model_name):
        self.model_name = model_name


def test_detects_explicit_refusal():
    hook = RefusalDetectorHook(patterns=["I cannot", "As an AI"])
    ctx = HookContext(output="I cannot help with that request.")
    result = hook(ctx)
    assert result.action == "fail"
    assert "refused" in (result.feedback or "").lower()


def test_passes_non_refusal_content():
    hook = RefusalDetectorHook(patterns=["I cannot"])
    ctx = HookContext(output='{"answer": 42}')
    assert hook(ctx).action == "continue"


def test_case_insensitive_matching():
    hook = RefusalDetectorHook(patterns=["i cannot"])
    ctx = HookContext(output="I CANNOT do that")
    assert hook(ctx).action == "fail"


def test_empty_patterns_always_passes():
    hook = RefusalDetectorHook(patterns=[])
    ctx = HookContext(output="I cannot anything")
    assert hook(ctx).action == "continue"


def test_uses_family_defaults_when_flag_set(monkeypatch):
    from api.hooks.builtins import refusal_detector as mod

    class FakeAdapter:
        def refusal_signatures(self):
            return ["ZZZ-family-refusal"]

    def fake_resolve(name):
        return FakeAdapter()

    monkeypatch.setattr(mod, "resolve_adapter", fake_resolve)

    hook = RefusalDetectorHook(patterns=[], use_family_defaults=True)
    ctx = HookContext(
        output="ZZZ-family-refusal. No can do.",
        step=FakeStep("some-model"),
    )
    ctx.workflow = None
    assert hook(ctx).action == "fail"


def test_name_and_stage():
    hook = RefusalDetectorHook(patterns=[])
    assert hook.name == "refusal_detector"
    assert hook.stage == "validate_output"
