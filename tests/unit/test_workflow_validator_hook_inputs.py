"""Validator awareness of hook-provided virtual inputs.

A step that declares a `plugin_tool_invoker` before_step hook with
`store_as: X` may reference `<step_id>.X` as one of its own inputs.
The static validator must recognise this rather than rejecting the
self-referential input.
"""

from __future__ import annotations

import pytest

from api.exceptions import WorkflowValidationError
from api.models.workflow_models import (
    AgentStep,
    HookSpec,
    StepHooks,
    WorkflowDefinition,
    WorkflowDefaults,
)
from api.services.ollama_service import OllamaService
from api.services.workflow_engine import WorkflowEngine


def _engine():
    return WorkflowEngine(ollama_service=OllamaService())


def _step_with_hook_input():
    return AgentStep(
        id="validate_and_revise",
        name="Validate",
        system_prompt="You are a validator.",
        inputs=[
            "validate_and_revise.validator_report",  # hook-provided
        ],
        outputs=["final_rule"],
        hooks=StepHooks(
            before_step=[
                HookSpec(
                    name="plugin_tool_invoker",
                    config={
                        "plugin_id": "xdm-toolkit",
                        "tool_id": "validate_xql",
                        "store_as": "validator_report",
                        "params_from": {"rule": "seed.rule"},
                    },
                )
            ]
        ),
    )


def test_validator_accepts_hook_provided_virtual_input():
    defn = WorkflowDefinition(
        id="wf-hook-input",
        name="hook-input-test",
        defaults=WorkflowDefaults(),
        steps=[_step_with_hook_input()],
    )
    # Must NOT raise — the hook's `store_as` resolves the self-reference.
    _engine().validate(defn, seed_keys=["rule"])


def test_validator_still_rejects_unrelated_missing_input():
    step = _step_with_hook_input()
    step.inputs.append("nonexistent.thing")
    defn = WorkflowDefinition(
        id="wf-hook-input-bad",
        name="hook-input-test",
        defaults=WorkflowDefaults(),
        steps=[step],
    )
    with pytest.raises(WorkflowValidationError, match="nonexistent.thing"):
        _engine().validate(defn, seed_keys=["rule"])
