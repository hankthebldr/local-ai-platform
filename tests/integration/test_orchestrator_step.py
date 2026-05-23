"""Phase 3b — kind=orchestrator step executor.

Drives the engine through real orchestrator runs against a scripted Ollama
stub. The planner emits JSON-fenced directives per the protocol in
api/services/orchestrator_protocol.py; the engine intercepts, dispatches
workers, and feeds results back.
"""

from __future__ import annotations

import json
import textwrap
import threading
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine

# ── Scripted Ollama ─────────────────────────────────────────────────────


class _ScriptedOllama:
    """Returns canned responses keyed by a substring in the user message.

    The orchestrator chats with the planner across multiple turns; the
    user message in the planner's most recent turn is what we key on
    (`worker` results, the parse-error nudge, or the initial task).

    Worker steps also call us — we recognize them by a marker substring
    in the system prompt (the role_inline string).
    """

    def __init__(self, planner_script, worker_responses):
        self._planner = list(planner_script)
        self._workers = worker_responses
        self.call_order: list[str] = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        sys_content = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        # Worker step routing — its system prompt contains the marker substring.
        for marker, response in self._workers.items():
            if marker in sys_content:
                with self._lock:
                    self.call_order.append(f"worker:{marker}")
                return {"content": response, "prompt_eval_count": 3, "eval_count": 3}

        # Otherwise it's the planner — pop the next scripted response.
        with self._lock:
            if not self._planner:
                raise AssertionError(
                    f"Planner ran out of scripted responses. "
                    f"Last user msg: {last_user[:200]!r}"
                )
            response = self._planner.pop(0)
            self.call_order.append(f"planner:turn{len(self.call_order) + 1}")
        return {"content": response, "prompt_eval_count": 10, "eval_count": 5}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


# ── YAML fixtures ───────────────────────────────────────────────────────


_ORCH_HAPPY = textwrap.dedent("""
    id: test-orch-happy
    name: Orchestrator Happy Path
    schema_version: 1
    defaults:
      role: reasoning
      max_tokens: 1024
    steps:
      - id: invest
        name: Investigate
        kind: orchestrator
        outputs: [findings]
        planner:
          role_inline: |
            You are the lead investigator.
          task: "Investigate the alert and produce findings."
        workers:
          extractor:
            id: w_extractor
            name: Extract Facts
            role: fast
            prompt:
              role_inline: marker_extractor_persona
              task: extract
            inputs: [seed.task, seed.raw_text]
            outputs: [facts]
          classifier:
            id: w_classifier
            name: Classify
            role: fast
            prompt:
              role_inline: marker_classifier_persona
              task: classify
            inputs: [seed.task]
            outputs: [labels]
        budget:
          max_workers_spawned: 4
          max_planner_turns: 6
    """)


_ORCH_BUDGET = textwrap.dedent("""
    id: test-orch-budget
    name: Orchestrator Budget Exhaustion
    schema_version: 1
    defaults:
      role: reasoning
    steps:
      - id: invest
        name: Investigate
        kind: orchestrator
        outputs: [findings]
        planner:
          role_inline: "You are the lead."
          task: "Investigate."
        workers:
          extractor:
            id: w_extractor
            name: Extract
            role: fast
            prompt:
              role_inline: marker_extractor_persona
              task: extract
            inputs: [seed.task]
            outputs: [facts]
        budget:
          max_workers_spawned: 2
          max_planner_turns: 8
    """)


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


def _spawn(worker_id, task, **inputs):
    return (
        "Calling worker.\n```json\n"
        + json.dumps(
            {
                "action": "spawn_worker",
                "worker_id": worker_id,
                "task": task,
                "inputs": inputs,
            }
        )
        + "\n```"
    )


def _complete(**outputs):
    return (
        "Synthesis complete.\n```json\n"
        + json.dumps({"action": "complete", "outputs": outputs})
        + "\n```"
    )


# ── Tests ───────────────────────────────────────────────────────────────


def test_orchestrator_spawns_workers_then_completes(isolated_dir):
    """Lead spawns 2 workers across 2 turns, then emits complete."""
    yaml_path = _write_yaml(isolated_dir, _ORCH_HAPPY)
    ollama = _ScriptedOllama(
        planner_script=[
            _spawn("extractor", "find atomic facts", raw_text="X happened"),
            _spawn("classifier", "tag the facts"),
            _complete(findings="Synthesized: X is bad."),
        ],
        worker_responses={
            "marker_extractor_persona": "extracted facts payload",
            "marker_classifier_persona": "classified labels payload",
        },
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=[])

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    assert run.context.get_workspace("invest", "findings") == "Synthesized: X is bad."
    # 3 planner turns + 2 worker calls
    assert len([c for c in ollama.call_order if c.startswith("planner")]) == 3
    assert len([c for c in ollama.call_order if c.startswith("worker")]) == 2


def test_orchestrator_unknown_worker_id_continues(isolated_dir):
    """When the lead spawns a worker that isn't in the catalog, the engine
    feeds back an error and the lead can recover."""
    yaml_path = _write_yaml(isolated_dir, _ORCH_HAPPY)
    ollama = _ScriptedOllama(
        planner_script=[
            _spawn("nonexistent", "go do a thing"),
            _spawn("extractor", "actually use a real worker", raw_text="hi"),
            _complete(findings="ok"),
        ],
        worker_responses={
            "marker_extractor_persona": "facts",
            "marker_classifier_persona": "labels",
        },
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Only the extractor actually ran (nonexistent was rejected by the engine).
    worker_calls = [c for c in ollama.call_order if c.startswith("worker")]
    assert worker_calls == ["worker:marker_extractor_persona"]


def test_orchestrator_max_workers_exhausted(isolated_dir):
    """max_workers_spawned hit — lead is told and emits complete with
    what it has."""
    yaml_path = _write_yaml(isolated_dir, _ORCH_BUDGET)
    ollama = _ScriptedOllama(
        planner_script=[
            _spawn("extractor", "first", info="a"),
            _spawn("extractor", "second", info="b"),
            # max_workers_spawned=2 hit; lead gets the budget message and
            # has to wrap up.
            _spawn("extractor", "third — should be denied", info="c"),
            _complete(findings="best-effort"),
        ],
        worker_responses={"marker_extractor_persona": "result"},
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Exactly 2 worker calls — the third spawn was denied.
    worker_calls = [c for c in ollama.call_order if c.startswith("worker")]
    assert len(worker_calls) == 2


def test_orchestrator_max_planner_turns_fails(isolated_dir):
    """Lead never emits complete within max_planner_turns → step fails."""
    yaml_text = _ORCH_BUDGET.replace("max_planner_turns: 8", "max_planner_turns: 3")
    yaml_path = _write_yaml(isolated_dir, yaml_text)
    # Planner keeps spawning forever — never completes.
    ollama = _ScriptedOllama(
        planner_script=[
            _spawn("extractor", "loop", x="1"),
            _spawn("extractor", "loop", x="2"),
            _spawn("extractor", "loop", x="3"),
            _spawn("extractor", "loop", x="4"),  # never reached
        ],
        worker_responses={"marker_extractor_persona": "result"},
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "failed"
    assert "max_planner_turns" in (run.error or "")


def test_orchestrator_complete_missing_output_keys_retries(isolated_dir):
    """Lead emits complete missing a required output key — engine nudges
    and the lead retries with the full key set."""
    yaml_path = _write_yaml(isolated_dir, _ORCH_HAPPY)
    ollama = _ScriptedOllama(
        planner_script=[
            # First try omits 'findings' — engine nudges
            "Done.\n```json\n"
            + json.dumps({"action": "complete", "outputs": {"wrong_key": "x"}})
            + "\n```",
            # Second try is correct
            _complete(findings="ok"),
        ],
        worker_responses={
            "marker_extractor_persona": "facts",
            "marker_classifier_persona": "labels",
        },
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    assert run.context.get_workspace("invest", "findings") == "ok"


def test_orchestrator_garbage_output_retries(isolated_dir):
    """Lead emits a non-JSON response — engine nudges and lead recovers."""
    yaml_path = _write_yaml(isolated_dir, _ORCH_HAPPY)
    ollama = _ScriptedOllama(
        planner_script=[
            "I'm just rambling without any directive at all.",
            _complete(findings="recovered"),
        ],
        worker_responses={
            "marker_extractor_persona": "facts",
            "marker_classifier_persona": "labels",
        },
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    assert run.context.get_workspace("invest", "findings") == "recovered"
