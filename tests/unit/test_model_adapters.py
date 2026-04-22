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


def test_dolphin_adapter_prepends_no_nonsense_prefix():
    adapter = resolve_adapter("dolphin-mixtral:latest")
    prompt, _ = adapter.prepare(_mk_prompt(), {})
    assert prompt.system.startswith("You are a no-nonsense assistant")
    assert "sys" in prompt.system  # original still there


def test_dolphin_refusal_signatures_include_common_patterns():
    sigs = resolve_adapter("dolphin-mistral:7b").refusal_signatures()
    assert any("cannot" in s.lower() for s in sigs)


def test_llama3_adapter_sets_format_json():
    adapter = resolve_adapter("llama3:8b")
    _, params = adapter.prepare(_mk_prompt(), {})
    assert params.get("format") == "json"


def test_mistral_adapter_appends_json_only_reminder():
    adapter = resolve_adapter("mistral:latest")
    prompt, params = adapter.prepare(_mk_prompt(), {})
    assert "valid JSON only" in prompt.system.lower() or "json only" in prompt.system.lower()
    assert params.get("format") == "json"


def test_qwen_adapter_clamps_temperature_to_minimum():
    adapter = resolve_adapter("qwen2.5:7b")
    _, params = adapter.prepare(_mk_prompt(), {"temperature": 0.1})
    assert params["temperature"] >= 0.2


def test_qwen_adapter_keeps_higher_temperature():
    adapter = resolve_adapter("qwen2.5:7b")
    _, params = adapter.prepare(_mk_prompt(), {"temperature": 0.7})
    assert params["temperature"] == 0.7


def test_yi_adapter_appends_think_carefully():
    adapter = resolve_adapter("yi-34b:chat")
    prompt, _ = adapter.prepare(_mk_prompt(), {})
    assert "think carefully" in prompt.system.lower()


def test_uncensored_common_extends_num_predict():
    adapter = resolve_adapter("wizardlm-uncensored:13b")
    _, params = adapter.prepare(_mk_prompt(), {"num_predict": 1024})
    assert params["num_predict"] > 1024


def test_mythomax_routed_to_uncensored_common():
    adapter = resolve_adapter("mythomax:13b")
    assert type(adapter).__name__ == "UncensoredCommonAdapter"


def test_nous_hermes_routed_to_uncensored_common():
    adapter = resolve_adapter("nous-hermes2-mixtral")
    assert type(adapter).__name__ == "UncensoredCommonAdapter"
