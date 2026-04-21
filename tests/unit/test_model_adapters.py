import pytest
from api.services.prompt_composer import ComposedPrompt
from api.services.model_adapters import (
    ModelAdapter,
    DefaultAdapter,
    resolve_adapter,
)


def _mk_prompt():
    return ComposedPrompt(system="sys", user="usr", params={"temperature": 0.5})


def test_default_adapter_leaves_prompt_unchanged():
    adapter = DefaultAdapter()
    prompt, params = adapter.prepare(_mk_prompt(), {"temperature": 0.5})
    assert prompt.system == "sys"
    assert prompt.user == "usr"
    assert params == {"temperature": 0.5}


def test_default_adapter_refusal_signatures_is_empty():
    assert DefaultAdapter().refusal_signatures() == []


def test_default_adapter_stop_sequences_is_empty():
    assert DefaultAdapter().stop_sequences() == []


def test_resolve_adapter_returns_default_for_unknown_model():
    adapter = resolve_adapter("some-unknown-model")
    assert isinstance(adapter, DefaultAdapter)
