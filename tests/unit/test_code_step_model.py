import pytest
from pydantic import ValidationError
from api.models.workflow_models import AgentStep, CodeStepConfig


def test_code_step_validates():
    s = AgentStep(
        id="c1",
        name="run",
        kind="code",
        outputs=["result"],
        code=CodeStepConfig(code="print(1)"),
    )
    assert (
        s.kind == "code" and s.code.language == "python" and s.code.promote == "gated"
    )


def test_code_step_requires_code_block():
    with pytest.raises(ValidationError):
        AgentStep(id="c1", name="run", kind="code", outputs=["result"])  # no .code


def test_non_code_step_rejects_code_block():
    with pytest.raises(ValidationError):
        AgentStep(
            id="x",
            name="n",
            kind="llm",
            outputs=["o"],
            code=CodeStepConfig(code="print(1)"),
        )
