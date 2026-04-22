import json
import textwrap
from api.services.hook_bus import HookBus
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from tests.integration.conftest import FakeOllamaClient


def test_custom_hook_fires_after_step(tmp_path, make_executor):
    # Write a custom after_step hook to a temp dir
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    (custom_dir / "counter_hook.py").write_text(textwrap.dedent("""
        from api.services.hook_bus import HookResult, register_hook

        CALLS = []

        @register_hook(stage="after_step", name="test_counter")
        def count(ctx):
            CALLS.append(ctx.step.id if ctx.step else None)
            return HookResult(action="continue")
    """))

    bus = HookBus()
    bus.register(JsonSchemaHook(schema={
        "type": "object", "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }))
    registered = bus.discover_and_register(custom_dir, source="custom")
    assert registered == 1

    step = AgentStep(
        id="s", name="S", role="coding",
        prompt=StepPrompt(role_inline="You are X.", task="t", constraints=[]),
        outputs=["ok"],
        output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    wf = WorkflowDefinition(id="w", name="W", schema_version=2, defaults=WorkflowDefaults(), steps=[step])
    client = FakeOllamaClient(responses=[json.dumps({"ok": True})])
    executor = make_executor(client, bus)
    executor.execute(
        step=step, workflow=wf, context=WorkflowContext(),
        resolved_model="mistral:latest", defaults=wf.defaults,
    )

    # The custom hook's module was loaded under a unique name; find its CALLS list
    import sys
    counter_mod = next(
        (m for name, m in sys.modules.items() if name.startswith("_hooks_auto_counter_hook_")),
        None,
    )
    assert counter_mod is not None
    assert "s" in counter_mod.CALLS
