import pytest
from api.models.workflow_models import (
    StepPrompt,
    HookSpec,
    AgentStep,
    WorkflowDefinition,
    WorkflowDefaults,
)


def test_step_prompt_requires_role_ref_or_inline():
    p = StepPrompt(role_ref="architect", task="t", constraints=["c"])
    assert p.role_ref == "architect"
    p = StepPrompt(role_inline="you are x", task="t", constraints=[])
    assert p.role_inline == "you are x"
    with pytest.raises(ValueError, match="role_ref or role_inline"):
        StepPrompt(task="t", constraints=[])


def test_step_prompt_forbids_both_role_ref_and_inline():
    with pytest.raises(ValueError, match="only one of"):
        StepPrompt(role_ref="a", role_inline="b", task="t", constraints=[])


def test_hook_spec_parses_dict_form():
    spec = HookSpec(name="json_schema", config={"strip_fences": True})
    assert spec.name == "json_schema"
    assert spec.config["strip_fences"] is True


def test_agent_step_v2_with_prompt_block():
    step = AgentStep(
        id="analyze",
        name="Analyze",
        role="reasoning",
        prompt=StepPrompt(role_ref="architect", task="t", constraints=["no prose"]),
        inputs=["seed.files"],
        outputs=["entities"],
        output_schema={"type": "object", "required": ["entities"]},
    )
    assert step.prompt is not None
    assert step.output_schema["type"] == "object"


def test_agent_step_v1_still_works_with_system_prompt():
    step = AgentStep(
        id="analyze",
        name="Analyze",
        role="reasoning",
        system_prompt="You are X. Do Y.",
        inputs=["seed.files"],
        outputs=["entities"],
    )
    assert step.system_prompt == "You are X. Do Y."
    assert step.prompt is None


def test_agent_step_requires_either_prompt_or_system_prompt():
    with pytest.raises(ValueError, match="prompt or system_prompt"):
        AgentStep(
            id="x", name="x", role="reasoning",
            inputs=[], outputs=["y"],
        )


def test_workflow_definition_v2_fields():
    wf = WorkflowDefinition(
        id="w",
        name="W",
        schema_version=2,
        context={"project": "Enclave"},
        schemas={"ent": {"type": "object"}},
        steps=[AgentStep(
            id="s", name="S", role="coding",
            system_prompt="x",
            outputs=["y"],
        )],
    )
    assert wf.schema_version == 2
    assert wf.context["project"] == "Enclave"
    assert "ent" in wf.schemas


def test_workflow_definition_defaults_to_v1():
    wf = WorkflowDefinition(
        id="w", name="W",
        steps=[AgentStep(id="s", name="S", role="coding", system_prompt="x", outputs=["y"])],
    )
    assert wf.schema_version == 1
