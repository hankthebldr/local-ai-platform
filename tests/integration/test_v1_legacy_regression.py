import json
from api.models.workflow_models import (
    AgentStep, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from tests.integration.conftest import FakeOllamaClient


def test_v1_system_prompt_step_runs_through_new_executor(make_executor, empty_bus):
    # Step uses v1 system_prompt only — no `prompt` block, no output_schema
    step = AgentStep(
        id="legacy",
        name="Legacy",
        role="coding",
        system_prompt="You are a legacy v1 agent. Respond with JSON {\"k\": \"v\"}.",
        inputs=[],
        outputs=["k"],
    )
    wf = WorkflowDefinition(
        id="legacy_wf", name="Legacy",
        # schema_version omitted → defaults to 1
        defaults=WorkflowDefaults(retries=0),
        steps=[step],
    )
    ctx = WorkflowContext()

    client = FakeOllamaClient(responses=[json.dumps({"k": "v"})])
    executor = make_executor(client, empty_bus)
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model="mistral:latest", defaults=wf.defaults,
    )
    assert result.status == "completed"
    # For v1 w/o json_schema hook, output stored as raw text for all output keys
    stored = ctx.get_workspace("legacy", "k")
    assert stored is not None
