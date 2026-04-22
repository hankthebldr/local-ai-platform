import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
from tests.integration.conftest import FakeOllamaClient


SCHEMA = {"type": "object", "required": ["k"], "properties": {"k": {"type": "string"}}}


def test_escalate_to_sets_shared_marker(make_executor, empty_bus):
    step = AgentStep(
        id="s", name="S", role="fast",
        prompt=StepPrompt(role_inline="You are X.", task="t", constraints=[]),
        outputs=["k"],
        output_schema=SCHEMA,
        config={"retries": 1, "retry_delay": 0},
    )
    wf = WorkflowDefinition(
        id="w", name="W", schema_version=2,
        defaults=WorkflowDefaults(retries=1, retry_delay=0),
        steps=[step],
    )
    ctx = WorkflowContext()

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=1, escalate_to="reasoning"))

    client = FakeOllamaClient(responses=[
        "bad output",
        json.dumps({"k": "v"}),
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    # Executor surfaces the escalation hint to shared state under a namespaced key
    assert ctx.get_shared("_escalated_s") == "reasoning"
