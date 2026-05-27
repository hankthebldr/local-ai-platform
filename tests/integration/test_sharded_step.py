"""Phase 2b — kind=parallel mode=sharded.

One persona is cloned per shard of the resolved shard_input; the gather step
synthesizes all shard outputs via the $shards accessor. Driven against a
stubbed Ollama.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine


class _MarkerOllama:
    """Marker-keyed responses. Records the per-call shard payload so tests can
    assert each shard reached the persona."""

    def __init__(self, responses_by_marker):
        self._responses = responses_by_marker
        self.call_order: list[str] = []
        self.persona_prompts: list[str] = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        all_content = " ".join(m.get("content", "") for m in messages)
        marker = next((k for k in self._responses if k in all_content), None)
        with self._lock:
            self.call_order.append(marker or "unknown")
            if marker == "marker_persona":
                self.persona_prompts.append(all_content)
        resp = self._responses.get(marker, "default")
        return {"content": resp, "prompt_eval_count": 4, "eval_count": 4}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


@pytest.fixture
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    return workflows


def _write_yaml(dirpath: Path, contents: str) -> Path:
    p = dirpath / "wf.yaml"
    p.write_text(contents)
    return p


# A sharded workflow: an ingest step emits a list, the sharded step processes
# each element with one persona, the gather summarizes all shard results.
def _sharded_yaml(
    sharder="by_file",
    shard_input="seed.documents",
    shard_size=None,
    failure_policy="fail_fast",
    max_shards=32,
):
    size_line = f"      shard_size: {shard_size}\n" if shard_size is not None else ""
    return (
        "id: test-sharded\n"
        "name: Sharded\n"
        "schema_version: 1\n"
        "defaults:\n"
        "  role: reasoning\n"
        "  retries: 0\n"
        "  retry_delay: 0\n"
        "steps:\n"
        "  - id: shard_extract\n"
        "    name: Per-Shard Extract\n"
        "    kind: parallel\n"
        "    outputs: [summary]\n"
        "    execution:\n"
        "      mode: sharded\n"
        f"      sharder: {sharder}\n"
        f"      shard_input: {shard_input}\n"
        f"      failure_policy: {failure_policy}\n"
        f"      max_shards: {max_shards}\n"
        f"{size_line}"
        "    branches:\n"
        "      - id: persona\n"
        "        name: Extractor\n"
        "        role: fast\n"
        "        prompt:\n"
        "          role_inline: marker_persona\n"
        "          task: extract from this shard\n"
        "        inputs: [seed.shard]\n"
        "        outputs: [extracted]\n"
        "    gather:\n"
        "      id: synth\n"
        "      name: Synthesize\n"
        "      role: reasoning\n"
        "      prompt:\n"
        "        role_inline: marker_synth\n"
        "        task: combine all shard extractions\n"
        "      inputs: [$shards.extracted]\n"
        "      outputs: [summary]\n"
    )


def test_sharded_by_file_clones_persona_per_shard(isolated_dir):
    """3 documents → persona runs 3 times → gather runs once with $shards."""
    yaml_path = _write_yaml(isolated_dir, _sharded_yaml())
    ollama = _MarkerOllama(
        {"marker_persona": "shard extraction", "marker_synth": "combined summary"}
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=["documents"])

    run = engine.run(defn, seed={"documents": ["doc A", "doc B", "doc C"]})

    assert run.status == "completed", run.error
    # Persona invoked once per shard (3) + gather once.
    assert ollama.call_order.count("marker_persona") == 3
    assert ollama.call_order.count("marker_synth") == 1
    # Gather ran last.
    assert ollama.call_order[-1] == "marker_synth"
    # Each shard's content reached its persona clone.
    joined = " ".join(ollama.persona_prompts)
    assert "doc A" in joined and "doc B" in joined and "doc C" in joined
    # Parent output materialized from gather.
    assert run.context.get_workspace("shard_extract", "summary") == "combined summary"


def test_sharded_by_chunk_groups_elements(isolated_dir):
    """5 items, shard_size=2 → 3 shards (2,2,1) → persona runs 3 times."""
    yaml_path = _write_yaml(
        isolated_dir, _sharded_yaml(sharder="by_chunk", shard_size=2)
    )
    ollama = _MarkerOllama({"marker_persona": "chunk done", "marker_synth": "summary"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"documents": [1, 2, 3, 4, 5]})

    assert run.status == "completed", run.error
    assert ollama.call_order.count("marker_persona") == 3


def test_sharded_gather_receives_shard_outputs(isolated_dir):
    """The gather prompt must contain each shard persona's output via $shards."""
    yaml_path = _write_yaml(isolated_dir, _sharded_yaml())
    # Persona output is JSON so it parses into workspace['extracted'].
    ollama = _MarkerOllama(
        {
            "marker_persona": '{"extracted": "FINDING"}',
            "marker_synth": "ok",
        }
    )
    captured = {}

    class _Cap(_MarkerOllama):
        def chat(self, model, messages, **kwargs):
            content = " ".join(m.get("content", "") for m in messages)
            if "marker_synth" in content:
                captured["gather_prompt"] = content
            return super().chat(model, messages, **kwargs)

    ollama = _Cap({"marker_persona": '{"extracted": "FINDING"}', "marker_synth": "ok"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"documents": ["x", "y"]})

    assert run.status == "completed", run.error
    # $shards.extracted → ["FINDING", "FINDING"] injected into the gather prompt.
    assert "FINDING" in captured["gather_prompt"]


def test_sharded_empty_input_fails(isolated_dir):
    yaml_path = _write_yaml(isolated_dir, _sharded_yaml())
    ollama = _MarkerOllama({"marker_persona": "x", "marker_synth": "y"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"documents": []})

    assert run.status == "failed"
    assert "no shards" in (run.error or "")
    # Neither persona nor gather ran.
    assert ollama.call_order == []


def test_sharded_max_shards_caps_persona_calls(isolated_dir):
    yaml_path = _write_yaml(isolated_dir, _sharded_yaml(max_shards=2))
    ollama = _MarkerOllama({"marker_persona": "x", "marker_synth": "y"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"documents": ["a", "b", "c", "d", "e"]})

    assert run.status == "completed", run.error
    # Capped at 2 shards despite 5 documents.
    assert ollama.call_order.count("marker_persona") == 2


def test_sharded_validation_rejects_two_branches(isolated_dir):
    from api.exceptions import WorkflowValidationError

    bad = _sharded_yaml().replace(
        "    branches:\n" "      - id: persona\n",
        "    branches:\n"
        "      - id: persona2\n"
        "        name: Extra\n"
        "        role: fast\n"
        "        prompt:\n"
        "          role_inline: marker_persona\n"
        "          task: extra\n"
        "        inputs: [seed.shard]\n"
        "        outputs: [extracted]\n"
        "      - id: persona\n",
    )
    yaml_path = _write_yaml(isolated_dir, bad)
    engine = WorkflowEngine(_MarkerOllama({}))
    with pytest.raises(WorkflowValidationError, match="exactly 1 branch"):
        engine.load(str(yaml_path))
