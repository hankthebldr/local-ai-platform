import json
from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
from tests.integration.conftest import FakeOllamaClient


SCHEMA = {"type": "object", "required": ["k"], "properties": {"k": {"type": "string"}}}


class FakeResolver:
    """Maps role strings to fake model names for test isolation."""
    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []
    def resolve(self, model=None, role=None, default_role="general"):
        self.calls.append({"model": model, "role": role})
        if model:
            return model
        return self._mapping[role]


def test_escalate_to_sets_shared_marker(make_executor, empty_bus):
    """Without a resolver, escalate_to still records the marker in shared state."""
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

    client = FakeOllamaClient(responses=["bad output", json.dumps({"k": "v"})])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    assert ctx.get_shared("_escalated_s") == "reasoning"


def test_escalate_to_actually_switches_model_when_resolver_present(composer, empty_bus):
    """With a model_resolver injected, escalate_to swaps the model used on retry."""
    from api.services.step_executor import StepExecutor

    resolver = FakeResolver(mapping={"reasoning": "yi-34b:chat"})
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

    client = FakeOllamaClient(responses=["bad output", json.dumps({"k": "v"})])
    executor = StepExecutor(
        ollama_service=client,
        composer=composer,
        hook_bus=empty_bus,
        model_resolver=resolver,
    )
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    # First call used the original model, second call used the escalated one
    assert client.calls[0]["model"] == "mistral:latest"
    assert client.calls[1]["model"] == "yi-34b:chat"
    # Resolver was invoked once, with role="reasoning"
    assert len(resolver.calls) == 1
    assert resolver.calls[0]["role"] == "reasoning"


def test_escalate_to_falls_back_gracefully_if_resolver_errors(composer, empty_bus):
    """If the resolver raises, we stay on the current model and keep retrying."""
    from api.services.step_executor import StepExecutor

    class FailingResolver:
        def resolve(self, **kwargs):
            raise RuntimeError("no models available")

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

    empty_bus.register(JsonSchemaHook(schema=SCHEMA))
    empty_bus.register(RetryWithFeedbackHook(max_attempts=1, escalate_to="reasoning"))

    client = FakeOllamaClient(responses=["bad output", json.dumps({"k": "v"})])
    executor = StepExecutor(
        ollama_service=client,
        composer=composer,
        hook_bus=empty_bus,
        model_resolver=FailingResolver(),
    )
    result = executor.execute(
        step=step, workflow=wf, context=WorkflowContext(),
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    # Both calls used the original model (resolver error → no swap)
    assert client.calls[0]["model"] == "mistral:latest"
    assert client.calls[1]["model"] == "mistral:latest"
