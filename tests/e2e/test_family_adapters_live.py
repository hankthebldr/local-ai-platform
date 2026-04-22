"""
E2E smoke tests against a running Ollama. Skipped by default — run locally with
`pytest tests/e2e/ -v` (requires Ollama service up and models pulled).
"""

import json
import os
import pytest
import requests

from api.models.workflow_models import (
    AgentStep, StepPrompt, WorkflowDefinition, WorkflowDefaults, WorkflowContext,
)
from api.services.hook_bus import HookBus
from api.services.prompt_composer import PromptComposer
from api.services.step_executor import StepExecutor
from api.services.ollama_service import OllamaService
from api.hooks.builtins.json_schema import JsonSchemaHook
from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook


pytestmark = pytest.mark.e2e


def _ollama_up() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=1)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_no_ollama():
    if not _ollama_up():
        pytest.skip("Ollama service not reachable at localhost:11434")


@pytest.mark.parametrize("model", [
    os.environ.get("ENCLAVE_E2E_MODEL", "mistral:latest"),
])
def test_end_to_end_simple_step(model, tmp_path):
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[2]
    composer = PromptComposer(
        roles_dir=project_root / "prompts" / "roles",
        templates_dir=project_root / "prompts" / "templates",
    )
    schema = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    bus = HookBus()
    bus.register(JsonSchemaHook(schema=schema, strip_fences=True))
    bus.register(RetryWithFeedbackHook(max_attempts=2))

    step = AgentStep(
        id="e2e", name="E2E", role="general",
        prompt=StepPrompt(
            role_inline="You answer trivia. Be concise.",
            task="What is the capital of France?",
            constraints=["Respond as JSON: {\"answer\": \"<city>\"}", "Exact city name only."],
        ),
        outputs=["answer"],
        output_schema=schema,
        config={"retries": 2, "retry_delay": 1},
    )
    wf = WorkflowDefinition(
        id="e2e", name="E2E", schema_version=2,
        defaults=WorkflowDefaults(retries=2, retry_delay=1),
        steps=[step],
    )

    executor = StepExecutor(
        ollama_service=OllamaService(host="http://localhost:11434"),
        composer=composer,
        hook_bus=bus,
    )
    ctx = WorkflowContext()
    result = executor.execute(
        step=step, workflow=wf, context=ctx,
        resolved_model=model, defaults=wf.defaults,
    )
    assert result.status == "completed", f"failed: {result.error}"
    answer = ctx.get_workspace("e2e", "answer")
    assert answer is not None
    assert "paris" in str(answer).lower()
