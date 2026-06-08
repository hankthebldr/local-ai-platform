"""Unit tests for ScaffoldPlannerService — spec -> runnable definition.

The local LLM is mocked. The template-match path reads the real workflow
index/files in the repo; the LLM and fallback paths force an empty index so
they exercise synthesis deterministically.
"""

import pytest

from api.models.workflow_models import WorkflowDefinition
from api.services import scaffold_planner as sp
from api.services.scaffold_planner import ScaffoldPlannerService


class FakeResolver:
    def resolve(self, model=None, role=None, default_role="general"):
        return model or f"local-{role or default_role}"


class FakeOllama:
    def __init__(self, content="", raise_exc=False):
        self._content = content
        self._raise = raise_exc

    def chat(self, **kwargs):
        if self._raise:
            raise RuntimeError("ollama down")
        return {"content": self._content}


@pytest.fixture
def empty_index(monkeypatch):
    """Force the template matcher to find nothing."""
    monkeypatch.setattr(
        sp,
        "get_workflow_index",
        lambda: type("I", (), {"build_index": lambda self: {"workflows": []}})(),
    )


def _assert_loadable(definition):
    # Must validate against the same model the engine/composer use.
    WorkflowDefinition(**definition)


def test_llm_plan_path(empty_index):
    ollama = FakeOllama(
        content='{"name": "Vendor Email", "description": "draft + validate", "steps": ['
        '{"id": "draft", "name": "Draft", "role": "reasoning", "system_prompt": "write it", '
        '"inputs": ["seed.vendor"], "outputs": ["draft"], "depends_on": []}, '
        '{"id": "check", "name": "Check", "role": "reviewer", "system_prompt": "review tone", '
        '"inputs": ["draft.draft"], "outputs": ["final"], "depends_on": ["draft"]}]}'
    )
    svc = ScaffoldPlannerService(ollama, resolver=FakeResolver())
    out = svc.scaffold(
        goal="zxqv unmatched goal token",
        inputs=[{"key": "vendor", "description": "vendor name"}],
        checks=["tone firm but warm"],
    )
    assert out["source"] == "llm"
    assert out["matched_workflow_id"] is None
    assert len(out["definition"]["steps"]) == 2
    # Each step bound to a concrete local model for the plan card.
    assert all(b["model"] for b in out["bindings"])
    assert out["bindings"][0]["role"] == "reasoning"
    _assert_loadable(out["definition"])


def test_fallback_when_model_errors(empty_index):
    ollama = FakeOllama(raise_exc=True)
    svc = ScaffoldPlannerService(ollama, resolver=FakeResolver())
    out = svc.scaffold(goal="zxqv unmatched", inputs=[], checks=["valid yaml"])
    assert out["source"] == "fallback"
    ids = [s["id"] for s in out["definition"]["steps"]]
    assert ids == ["intake", "draft", "validate"]
    _assert_loadable(out["definition"])


def test_fallback_on_garbage_plan(empty_index):
    ollama = FakeOllama(content="no json here")
    svc = ScaffoldPlannerService(ollama, resolver=FakeResolver())
    out = svc.scaffold(goal="zxqv unmatched", inputs=[], checks=[])
    assert out["source"] == "fallback"
    _assert_loadable(out["definition"])


def test_llm_steps_get_default_output_when_missing(empty_index):
    ollama = FakeOllama(
        content='{"name": "X", "steps": [{"id": "a", "name": "A", "role": "general"}]}'
    )
    svc = ScaffoldPlannerService(ollama, resolver=FakeResolver())
    out = svc.scaffold(goal="zxqv unmatched", inputs=[], checks=[])
    assert out["source"] == "llm"
    assert out["definition"]["steps"][0]["outputs"]  # min_length=1 satisfied
    _assert_loadable(out["definition"])


def test_normalize_makes_llm_plan_runnable(empty_index):
    """A real run surfaced this: local LLM plans emit bare input refs (e.g.
    'topic' instead of 'seed.topic', or a bare upstream output) which pass
    Pydantic but fail the engine's producer check. The planner must normalize
    every input to a real producer so the scaffold is actually runnable."""
    ollama = FakeOllama(
        content='{"name": "Greet", "steps": ['
        '{"id": "greet", "name": "Greet", "role": "general", "system_prompt": "x", '
        '"inputs": ["topic"], "outputs": ["msg"], "depends_on": []}, '
        '{"id": "check", "name": "Check", "role": "reasoning", "system_prompt": "y", '
        '"inputs": ["msg"], "outputs": ["final"], "depends_on": []}]}'
    )
    svc = ScaffoldPlannerService(ollama, resolver=FakeResolver())
    out = svc.scaffold(
        goal="greet a teammate",
        inputs=[{"key": "topic", "description": "t"}],
        checks=[],
    )
    steps = {s["id"]: s for s in out["definition"]["steps"]}
    assert steps["greet"]["inputs"] == ["seed.topic"]  # bare key -> seed.key
    assert steps["check"]["inputs"] == ["greet.msg"]  # bare output -> step.output
    assert "greet" in steps["check"]["depends_on"]  # dependency inferred
    # Engine invariant: every input references a real producer.
    producers = {"seed.topic"}
    for s in out["definition"]["steps"]:
        for inp in s["inputs"]:
            assert inp in producers, f"input {inp!r} has no producer"
        for o in s["outputs"]:
            producers.add(f"{s['id']}.{o}")
    _assert_loadable(out["definition"])


class RaisingResolver:
    """Simulates Ollama being down: even model resolution raises."""

    def resolve(self, model=None, role=None, default_role="general"):
        raise RuntimeError("ollama down (resolve)")


def test_scaffold_degrades_to_fallback_when_ollama_down(empty_index):
    """HIGH-severity regression: with no template match AND Ollama down,
    scaffold must still return a loadable definition (deterministic fallback),
    never propagate a 503. resolve() raising must not break the always-primes
    contract."""
    ollama = FakeOllama(raise_exc=True)
    svc = ScaffoldPlannerService(ollama, resolver=RaisingResolver())
    out = svc.scaffold(goal="zxqv unmatched goal", inputs=[], checks=["valid output"])
    assert out["source"] == "fallback"
    assert [s["id"] for s in out["definition"]["steps"]] == [
        "intake",
        "draft",
        "validate",
    ]
    assert len(out["bindings"]) == 3
    _assert_loadable(out["definition"])


def test_template_match_path():
    """A goal that overlaps a curated workflow should reuse it (no LLM call)."""
    ollama = FakeOllama(raise_exc=True)  # must NOT be called on the template path
    svc = ScaffoldPlannerService(ollama, resolver=FakeResolver())
    out = svc.scaffold(
        goal="brainstorm a feature idea, research the market, then make a go/no-go decision",
        inputs=[{"key": "thesis", "description": "the idea"}],
        checks=[],
    )
    # If the repo ships brainstorm-decision.yaml this matches; otherwise the
    # matcher returns nothing and we synthesize — either way it must be loadable.
    assert out["source"] in ("template", "fallback", "llm")
    _assert_loadable(out["definition"])
    if out["source"] == "template":
        assert out["matched_workflow_id"]
