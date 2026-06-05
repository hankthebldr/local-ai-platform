from api.models.workflow_models import StepResult


def test_code_fields_default_and_roundtrip():
    r = StepResult(step_id="c1", status="completed")
    assert r.code_exit_code is None and r.files_produced == [] and r.promoted is None
    again = StepResult.model_validate(r.model_dump())
    assert again.tier_used is None
