"""Unit tests for SpecCaptureService — chat thread -> editable spec.

The local LLM is mocked; these run offline and never hit Ollama.
"""

from api.services.spec_capture import SpecCaptureService


class FakeResolver:
    def resolve(self, model=None, role=None, default_role="general"):
        return model or f"local-{role or default_role}"


class FakeOllama:
    def __init__(self, content="", raise_exc=False):
        self._content = content
        self._raise = raise_exc
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise:
            raise RuntimeError("ollama down")
        return {"content": self._content}


THREAD = [
    {
        "role": "user",
        "content": "write a firm but warm vendor email pushing back on a price hike",
    },
    {"role": "assistant", "content": "Sure, here's a draft..."},
]


def test_capture_parses_clean_json():
    ollama = FakeOllama(
        content='{"goal": "Draft a vendor pushback email", '
        '"inputs": [{"key": "vendor", "description": "vendor name"}], '
        '"checks": ["tone is firm but warm", "no over-promising"]}'
    )
    svc = SpecCaptureService(ollama, resolver=FakeResolver())
    out = svc.capture(THREAD, role="reasoning")

    assert out["goal"] == "Draft a vendor pushback email"
    assert out["inputs"] == [{"key": "vendor", "description": "vendor name"}]
    assert out["checks"] == ["tone is firm but warm", "no over-promising"]
    assert out["model"] == "local-reasoning"


def test_capture_tolerates_chatty_prose_around_json():
    ollama = FakeOllama(
        content='Sure! Here is the spec:\n```json\n{"goal": "Do the thing", '
        '"inputs": [], "checks": []}\n```\nHope that helps.'
    )
    svc = SpecCaptureService(ollama, resolver=FakeResolver())
    out = svc.capture(THREAD)
    assert out["goal"] == "Do the thing"
    assert out["inputs"] == []


def test_capture_falls_back_when_model_errors():
    ollama = FakeOllama(raise_exc=True)
    svc = SpecCaptureService(ollama, resolver=FakeResolver())
    out = svc.capture(THREAD)
    # Heuristic goal = last user message (truncated).
    assert "vendor email" in out["goal"]
    assert out["model"] == "local-reasoning"


def test_capture_falls_back_on_garbage_json():
    ollama = FakeOllama(content="absolutely not json at all")
    svc = SpecCaptureService(ollama, resolver=FakeResolver())
    out = svc.capture(THREAD)
    assert out["goal"]  # non-empty heuristic
    assert out["inputs"] == []
    assert out["checks"] == []


class RaisingResolver:
    def resolve(self, model=None, role=None, default_role="general"):
        raise RuntimeError("ollama down (resolve)")


def test_capture_degrades_when_resolve_fails():
    """Regression: with Ollama down, resolve() raises — capture must still
    return a usable spec (heuristic goal + requested model), never 503."""
    ollama = FakeOllama(raise_exc=True)
    svc = SpecCaptureService(ollama, resolver=RaisingResolver())
    out = svc.capture(THREAD, model="hermes3:8b")
    assert out["model"] == "hermes3:8b"  # falls back to the requested model
    assert out["goal"]  # heuristic goal from the thread
    assert out["inputs"] == []
    assert out["checks"] == []


def test_input_keys_are_slugged():
    ollama = FakeOllama(
        content='{"goal": "g", "inputs": [{"key": "Vendor Name!", "description": "d"}], "checks": []}'
    )
    svc = SpecCaptureService(ollama, resolver=FakeResolver())
    out = svc.capture(THREAD)
    assert out["inputs"][0]["key"] == "vendor_name"
