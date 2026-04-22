import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.token_budget import TokenBudgetHook
from tests.integration.conftest import FakeOllamaClient


def test_long_context_gets_truncated_before_model_call(make_executor, empty_bus):
    long_ctx_value = "x " * 5000  # ~10k chars
    step = AgentStep(
        id="s", name="S", role="coding",
        prompt=StepPrompt(
            role_inline="You are X.",
            task="Respond with {\"ok\": true}",
            constraints=["BE BRIEF"],
        ),
        inputs=["seed.big"],
        outputs=["ok"],
        output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    wf = WorkflowDefinition(
        id="w", name="W", schema_version=2,
        context={"big_thing": long_ctx_value},
        defaults=WorkflowDefaults(retries=0),
        steps=[step],
    )
    ctx = WorkflowContext(seed={"big": long_ctx_value})

    empty_bus.register(TokenBudgetHook(max_prompt_tokens=500, reserve_for_output=100))
    empty_bus.register(JsonSchemaHook(schema=step.output_schema))

    client = FakeOllamaClient(responses=[json.dumps({"ok": True})])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"

    sent_system = client.calls[0]["messages"][0]["content"]
    assert "Respond with" in sent_system
    assert "BE BRIEF" in sent_system
    assert "truncated for token budget" in sent_system or len(sent_system) < len(long_ctx_value)
