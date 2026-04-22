"""Shared fixtures for workflow engine integration tests (no real Ollama)."""

import pytest
from pathlib import Path
from api.services.hook_bus import HookBus
from api.services.prompt_composer import PromptComposer
from api.services.step_executor import StepExecutor


class FakeOllamaClient:
    """Scriptable stand-in for OllamaService.

    Construct with a list of responses; each call to `chat` returns the next.
    Responses may be strings (treated as the `content`) or dicts (passed through).
    """

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = []

    def chat(self, model, messages, temperature=None, max_tokens=None):
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        if not self._responses:
            return {"content": "", "prompt_eval_count": 0, "eval_count": 0}
        resp = self._responses.pop(0)
        if isinstance(resp, str):
            return {"content": resp, "prompt_eval_count": 5, "eval_count": 5}
        return resp


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def composer(project_root):
    return PromptComposer(
        roles_dir=project_root / "prompts" / "roles",
        templates_dir=project_root / "prompts" / "templates",
    )


@pytest.fixture
def empty_bus():
    return HookBus()


@pytest.fixture
def make_executor(composer):
    def _make(fake_client, bus):
        return StepExecutor(
            ollama_service=fake_client,
            composer=composer,
            hook_bus=bus,
        )
    return _make
