import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
from tests.integration.conftest import FakeOllamaClient


SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "integer"}},
}


def _step():
    return AgentStep(
        id="solve",
        name="Solve",
        role="reasoning",
        prompt=StepPrompt(role_inline="You are X.", task="solve", constraints=[]),
        inputs=[],
        outputs=["answer"],
        output_schema=SCHEMA,
        config={"retries": 2, "retry_delay": 0},
    )


def _workflow(step):
    return WorkflowDefinition(
        id="w", name="W", schema_version=2,
        defaults=WorkflowDefaults(retries=2, retry_delay=0),
        steps=[step],
    )


def test_malformed_json_then_valid_json_succeeds_on_attempt_two(make_executor, empty_bus):
    step = _step()
    wf = _workflow(step)
    ctx = WorkflowContext()

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=2))

    client = FakeOllamaClient(responses=[
        "not valid json at all",
        json.dumps({"answer": 42}),
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    assert result.retries == 1
    assert ctx.get_workspace("solve", "answer") == 42
    assert len(client.calls) == 2
    second_user = client.calls[1]["messages"][1]["content"]
    assert "previous" in second_user.lower()
    assert "json" in second_user.lower()


def test_all_attempts_fail_returns_failed_status(make_executor, empty_bus):
    step = _step()
    wf = _workflow(step)
    ctx = WorkflowContext()

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=2))

    client = FakeOllamaClient(responses=[
        "not json",
        "still not json",
        "still not json",
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "failed"
    assert len(client.calls) == 3  # initial + 2 retries
