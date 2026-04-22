import json
from api.models.workflow_models import (
    AgentStep,
    StepPrompt,
    WorkflowDefinition,
    WorkflowDefaults,
    WorkflowContext,
)
from api.hooks.builtins.json_schema import JsonSchemaHook
from tests.integration.conftest import FakeOllamaClient


def _workflow_with_one_step():
    step = AgentStep(
        id="analyze",
        name="Analyze",
        role="reasoning",
        prompt=StepPrompt(
            role_inline="You are X.",
            task="analyze the inputs",
            constraints=["JSON only"],
        ),
        inputs=["seed.files"],
        outputs=["entities", "count"],
        output_schema={
            "type": "object",
            "required": ["entities", "count"],
            "properties": {
                "entities": {"type": "array"},
                "count": {"type": "integer"},
            },
        },
    )
    wf = WorkflowDefinition(
        id="w", name="W", schema_version=2,
        context={"project": "Enclave"},
        defaults=WorkflowDefaults(),
        steps=[step],
    )
    return wf, step


def test_happy_path_writes_parsed_outputs_to_workspace(make_executor, empty_bus):
    wf, step = _workflow_with_one_step()
    ctx = WorkflowContext(seed={"files": ["a.py"]})

    empty_bus.register(JsonSchemaHook(schema=step.output_schema))

    client = FakeOllamaClient(responses=[
        json.dumps({"entities": [{"name": "User"}], "count": 1}),
    ])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step,
        workflow=wf,
        context=ctx,
        resolved_model="mistral:latest",
        defaults=wf.defaults,
    )
    assert result.status == "completed"
    assert ctx.get_workspace("analyze", "entities") == [{"name": "User"}]
    assert ctx.get_workspace("analyze", "count") == 1
    assert len(client.calls) == 1
