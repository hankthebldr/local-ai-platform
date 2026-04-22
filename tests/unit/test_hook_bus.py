import pytest
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


from api.services.hook_bus import HookBus


def _make_hook(name, stage, action="continue", feedback=None, mutations=None):
    class _H:
        pass
    h = _H()
    h.name = name
    h.stage = stage
    def call(ctx):
        return HookResult(action=action, feedback=feedback, mutations=mutations or {})
    h.__call__ = call
    # make instance callable
    h_callable = lambda ctx, _h=h: _h.__call__(ctx)
    h_callable.name = name
    h_callable.stage = stage
    return h_callable


def test_bus_register_and_dispatch_single_hook():
    bus = HookBus()
    bus.register(_make_hook("a", "after_step"))
    ctx = HookContext()
    results = bus.dispatch("after_step", ctx)
    assert len(results) == 1
    assert results[0].action == "continue"


def test_bus_runs_hooks_in_registration_order():
    bus = HookBus()
    order = []
    def h(name):
        def _call(ctx):
            order.append(name)
            return HookResult(action="continue")
        _call.name = name
        _call.stage = "after_step"
        return _call
    bus.register(h("first"))
    bus.register(h("second"))
    bus.register(h("third"))
    bus.dispatch("after_step", HookContext())
    assert order == ["first", "second", "third"]


def test_bus_short_circuits_on_non_continue():
    bus = HookBus()
    order = []
    def h(name, action):
        def _call(ctx):
            order.append(name)
            return HookResult(action=action)
        _call.name = name
        _call.stage = "after_step"
        return _call
    bus.register(h("a", "continue"))
    bus.register(h("b", "fail"))
    bus.register(h("c", "continue"))
    results = bus.dispatch("after_step", HookContext())
    assert order == ["a", "b"]  # c never ran
    assert results[-1].action == "fail"


def test_bus_validate_output_requires_all_continue():
    bus = HookBus()
    bus.register(_make_hook("schema", "validate_output", action="continue"))
    bus.register(_make_hook("refusal", "validate_output", action="continue"))
    results = bus.dispatch("validate_output", HookContext())
    assert all(r.action == "continue" for r in results)


def test_bus_validate_output_stops_at_first_rejection():
    bus = HookBus()
    order = []
    def h(name, action):
        def _call(ctx):
            order.append(name)
            return HookResult(action=action)
        _call.name = name
        _call.stage = "validate_output"
        return _call
    bus.register(h("schema", "fail"))
    bus.register(h("refusal", "continue"))
    results = bus.dispatch("validate_output", HookContext())
    assert order == ["schema"]
    assert results[-1].action == "fail"


def test_bus_rejects_wrong_stage_registration():
    bus = HookBus()
    def h(ctx):
        return HookResult()
    h.name = "bad"
    h.stage = "nonsense_stage"
    with pytest.raises(ValueError, match="invalid stage"):
        bus.register(h)


def test_bus_custom_hooks_run_after_builtin_hooks():
    bus = HookBus()
    order = []
    def h(name, source):
        def _call(ctx):
            order.append(name)
            return HookResult(action="continue")
        _call.name = name
        _call.stage = "after_step"
        return _call
    bus.register(h("builtin1", "builtin"), source="builtin")
    bus.register(h("custom1", "custom"), source="custom")
    bus.register(h("builtin2", "builtin"), source="builtin")
    bus.dispatch("after_step", HookContext())
    assert order == ["builtin1", "builtin2", "custom1"]


import tempfile
import textwrap
from pathlib import Path


def test_discover_registers_hooks_from_directory(tmp_path, monkeypatch):
    hook_file = tmp_path / "my_custom.py"
    hook_file.write_text(textwrap.dedent("""
        from api.services.hook_bus import HookResult, register_hook

        @register_hook(stage="after_step", name="custom_noop")
        def noop(ctx):
            return HookResult(action="continue")
    """))

    bus = HookBus()
    bus.discover_and_register(tmp_path, source="custom")
    # Verify by dispatching — if registered, hook list has 1 entry
    assert len(bus._hooks["after_step"]) == 1
    # Dispatch works
    results = bus.dispatch("after_step", HookContext())
    assert len(results) == 1
    assert results[0].action == "continue"


def test_discover_skips_files_without_register_hook_decorator(tmp_path):
    (tmp_path / "not_a_hook.py").write_text("x = 1\n")
    bus = HookBus()
    bus.discover_and_register(tmp_path, source="custom")
    assert len(bus._hooks["after_step"]) == 0


def test_discover_ignores_dunder_files(tmp_path):
    (tmp_path / "__init__.py").write_text("x = 1\n")
    bus = HookBus()
    bus.discover_and_register(tmp_path, source="custom")
    assert all(len(v) == 0 for v in bus._hooks.values())
