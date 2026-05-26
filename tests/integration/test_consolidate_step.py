"""Phase 4 — kind=consolidate step executor + $memory.* round-trip.

Drives the engine through consolidate steps against a stubbed Ollama, then
verifies the memory store was written and that a subsequent run can read the
consolidated memory back via a $memory.* input.
"""

from __future__ import annotations

import textwrap
import threading
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine


class _MarkerOllama:
    """Returns canned responses keyed by a marker substring in the prompt."""

    def __init__(self, responses_by_marker):
        self._responses = responses_by_marker
        self.call_order: list[str] = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        all_content = " ".join(m.get("content", "") for m in messages)
        marker = next((k for k in self._responses if k in all_content), None)
        with self._lock:
            self.call_order.append(marker or "unknown")
        resp = self._responses.get(marker, "default output")
        return {"content": resp, "prompt_eval_count": 5, "eval_count": 5}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Point both the workflow data dir AND the memory dir at the tmp path so
    the test is fully isolated and we can inspect what got written."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path / "memory_root"))
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    return tmp_path, workflows


def _write_yaml(dirpath: Path, contents: str) -> Path:
    p = dirpath / "wf.yaml"
    p.write_text(contents)
    return p


def _engine():
    # Construct AFTER the monkeypatched env is set so MemoryStore picks up
    # the test MEMORY_DATA_DIR.
    return WorkflowEngine(_MARKER_HOLDER["ollama"])


_MARKER_HOLDER: dict = {}


_CONSOLIDATE_PLAYBOOK = textwrap.dedent("""
    id: test-consolidate
    name: Consolidate Playbook
    schema_version: 1
    defaults:
      role: reasoning
    steps:
      - id: analyze
        name: Analyze
        role: fast
        prompt:
          role_inline: marker_analyze
          task: analyze
        inputs: [seed.report]
        outputs: [findings]
      - id: distill
        name: Distill Lessons
        kind: consolidate
        depends_on: [analyze]
        inputs:
          - analyze.findings
        outputs:
          - updated_playbook
        consolidate:
          target: playbook
          target_name: incident_response
          merge_strategy: append_with_dedup
          system_prompt: marker_consolidate
    """)


_READ_MEMORY = textwrap.dedent("""
    id: test-read-memory
    name: Read Memory
    schema_version: 1
    defaults:
      role: reasoning
    steps:
      - id: plan
        name: Plan With Memory
        role: reasoning
        prompt:
          role_inline: marker_plan
          task: plan using prior lessons
        inputs:
          - seed.task
          - $memory.playbook.incident_response
        outputs: [plan]
    """)


def test_consolidate_writes_to_playbook_store(isolated_dirs):
    tmp_path, workflows = isolated_dirs
    _MARKER_HOLDER["ollama"] = _MarkerOllama(
        {
            "marker_analyze": "the database was misconfigured",
            "marker_consolidate": "Rule: always verify DB config before deploy",
        }
    )
    yaml_path = _write_yaml(workflows, _CONSOLIDATE_PLAYBOOK)
    engine = _engine()
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=["report"])

    run = engine.run(defn, seed={"report": "incident text"})

    assert run.status == "completed", run.error
    # The consolidate step's output is mirrored to the workspace.
    assert "verify DB config" in run.context.get_workspace(
        "distill", "updated_playbook"
    )
    # And persisted to the playbook store on disk.
    playbook_file = tmp_path / "memory_root" / "playbooks" / "incident_response.md"
    assert playbook_file.exists()
    assert "verify DB config" in playbook_file.read_text()


def test_consolidate_then_read_back_via_memory_accessor(isolated_dirs):
    """Run 1 consolidates into the playbook; Run 2 reads it via
    $memory.playbook.incident_response."""
    tmp_path, workflows = isolated_dirs

    # Run 1: consolidate.
    _MARKER_HOLDER["ollama"] = _MarkerOllama(
        {
            "marker_analyze": "auth tokens leaked in logs",
            "marker_consolidate": "Rule: never log auth tokens",
        }
    )
    yaml1 = _write_yaml(workflows, _CONSOLIDATE_PLAYBOOK)
    engine1 = _engine()
    defn1 = engine1.load(str(yaml1))
    run1 = engine1.run(defn1, seed={"report": "x"})
    assert run1.status == "completed", run1.error

    # Run 2: a plan step reads the playbook via $memory.* — the stub captures
    # whether the consolidated rule made it into the prompt.
    captured = {}

    class _CapturingOllama(_MarkerOllama):
        def chat(self, model, messages, **kwargs):
            captured["prompt"] = " ".join(m.get("content", "") for m in messages)
            return super().chat(model, messages, **kwargs)

    _MARKER_HOLDER["ollama"] = _CapturingOllama({"marker_plan": "my plan"})
    yaml2 = workflows / "wf2.yaml"
    yaml2.write_text(_READ_MEMORY)
    engine2 = _engine()
    defn2 = engine2.load(str(yaml2))
    run2 = engine2.run(defn2, seed={"task": "deploy safely"})

    assert run2.status == "completed", run2.error
    # The consolidated rule from run 1 must appear in run 2's planner prompt.
    assert "never log auth tokens" in captured["prompt"]


def test_consolidate_empty_output_fails(isolated_dirs):
    tmp_path, workflows = isolated_dirs
    _MARKER_HOLDER["ollama"] = _MarkerOllama(
        {
            "marker_analyze": "some findings",
            "marker_consolidate": "",  # empty consolidation output
        }
    )
    yaml_path = _write_yaml(workflows, _CONSOLIDATE_PLAYBOOK)
    engine = _engine()
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"report": "x"})

    assert run.status == "failed"
    assert "empty output" in (run.error or "")


def test_consolidate_episodic_appends_record(isolated_dirs):
    tmp_path, workflows = isolated_dirs
    episodic_yaml = _CONSOLIDATE_PLAYBOOK.replace(
        "target: playbook", "target: episodic"
    ).replace("target_name: incident_response", "target_name: incident_log")
    _MARKER_HOLDER["ollama"] = _MarkerOllama(
        {
            "marker_analyze": "findings",
            "marker_consolidate": "Episode digest: incident handled",
        }
    )
    yaml_path = _write_yaml(workflows, episodic_yaml)
    engine = _engine()
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"report": "x"})

    assert run.status == "completed", run.error
    episodic_file = (
        tmp_path / "memory_root" / "memory" / "episodic" / "incident_log.jsonl"
    )
    assert episodic_file.exists()
    assert "incident handled" in episodic_file.read_text()


def test_memory_accessor_empty_on_first_run(isolated_dirs):
    """A workflow reading $memory.* against an empty store still runs — the
    accessor resolves to "" rather than erroring."""
    tmp_path, workflows = isolated_dirs
    captured = {}

    class _CapturingOllama(_MarkerOllama):
        def chat(self, model, messages, **kwargs):
            captured["prompt"] = " ".join(m.get("content", "") for m in messages)
            return super().chat(model, messages, **kwargs)

    _MARKER_HOLDER["ollama"] = _CapturingOllama({"marker_plan": "plan"})
    yaml_path = _write_yaml(workflows, _READ_MEMORY)
    engine = _engine()
    defn = engine.load(str(yaml_path))
    # Validation must accept the $memory.* input.
    engine.validate(defn, seed_keys=["task"])
    run = engine.run(defn, seed={"task": "do it"})

    assert run.status == "completed", run.error
