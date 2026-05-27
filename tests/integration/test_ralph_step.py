"""Phase 5 — kind=ralph autonomous loop.

Drives the engine through ralph loops against a scripted Ollama, exercising
every halt condition plus the journal-based resume and the self-learning
playbook loop (a consolidate body step writes lessons a later iteration's
plan step reads back via $memory.*).
"""

from __future__ import annotations

import json
import textwrap
import threading
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine


class _ScriptedOllama:
    """Marker-keyed responses. Body steps are identified by a marker substring
    in their system prompt (role_inline)."""

    def __init__(self, responses_by_marker):
        self._responses = responses_by_marker
        self.call_order: list[str] = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        all_content = " ".join(m.get("content", "") for m in messages)
        marker = next((k for k in self._responses if k in all_content), None)
        with self._lock:
            self.call_order.append(marker or "unknown")
        resp = self._responses.get(marker, "default")
        if callable(resp):
            resp = resp(self.call_order.count(marker))
        return {"content": resp, "prompt_eval_count": 5, "eval_count": 5}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path / "memory_root"))
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    return tmp_path, workflows


def _write_yaml(dirpath: Path, contents: str) -> Path:
    p = dirpath / "wf.yaml"
    p.write_text(contents)
    return p


_HOLDER: dict = {}


def _engine():
    return WorkflowEngine(_HOLDER["ollama"])


def _ralph_yaml(
    tmp_path, *, goal_gate=None, max_iterations=5, max_consec=3, halt_file=None
):
    """Build a ralph workflow YAML with clean, explicit indentation.

    The `work` step (last body step) produces the ralph output `progress`.
    """
    journal = tmp_path / "ralph_journal.jsonl"
    halt = [
        f"            max_iterations: {max_iterations}",
        f"            max_consecutive_failures: {max_consec}",
    ]
    if goal_gate is not None:
        halt.append(f'            goal_gate: "{goal_gate}"')
    if halt_file is not None:
        halt.append(f"            halt_file: {halt_file}")
    halt_block = "\n".join(halt)
    return (
        "id: test-ralph\n"
        "name: Ralph Loop\n"
        "schema_version: 1\n"
        "defaults:\n"
        "  role: reasoning\n"
        "  max_tokens: 512\n"
        "  retries: 0\n"
        "  retry_delay: 0\n"
        "steps:\n"
        "  - id: auto\n"
        "    name: Autonomous Dev\n"
        "    kind: ralph\n"
        "    outputs: [progress]\n"
        "    ralph:\n"
        f"      journal_path: {journal}\n"
        "      halt:\n"
        f"{halt_block}\n"
        "    body:\n"
        "      - id: plan\n"
        "        name: Plan\n"
        "        role: fast\n"
        "        prompt:\n"
        "          role_inline: marker_plan\n"
        "          task: pick next task\n"
        "        outputs: [chosen_task]\n"
        "      - id: work\n"
        "        name: Work\n"
        "        role: fast\n"
        "        prompt:\n"
        "          role_inline: marker_work\n"
        "          task: do the task\n"
        "        inputs: [plan.chosen_task]\n"
        "        outputs: [progress, done]\n"
    )


def test_ralph_stops_on_goal_gate(isolated_dirs):
    """Loop runs until the goal_gate (work.done == True) is satisfied."""
    tmp_path, workflows = isolated_dirs

    # work.done flips to True on the 3rd iteration.
    def _work_response(call_n):
        done = "true" if call_n >= 3 else "false"
        return json.dumps({"progress": f"step {call_n}", "done": done == "true"})

    _HOLDER["ollama"] = _ScriptedOllama(
        {"marker_plan": "task chosen", "marker_work": _work_response}
    )
    yaml_path = _write_yaml(
        workflows,
        _ralph_yaml(tmp_path, goal_gate="work.done == True", max_iterations=10),
    )
    engine = _engine()
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=[])

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Plan + work each ran 3 times (gate satisfied after 3rd iteration).
    assert len([c for c in _HOLDER["ollama"].call_order if c == "marker_work"]) == 3
    # The journal recorded 3 iterations.
    journal = tmp_path / "ralph_journal.jsonl"
    lines = [l for l in journal.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    assert json.loads(lines[-1])["goal_reached"] is True


def test_ralph_stops_on_max_iterations(isolated_dirs):
    """No goal_gate → loop runs exactly max_iterations and completes."""
    tmp_path, workflows = isolated_dirs
    _HOLDER["ollama"] = _ScriptedOllama(
        {"marker_plan": "task", "marker_work": '{"progress": "p", "done": false}'}
    )
    yaml_path = _write_yaml(workflows, _ralph_yaml(tmp_path, max_iterations=4))
    engine = _engine()
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    assert len([c for c in _HOLDER["ollama"].call_order if c == "marker_work"]) == 4
    journal = tmp_path / "ralph_journal.jsonl"
    assert len([l for l in journal.read_text().splitlines() if l.strip()]) == 4


def test_ralph_fails_on_consecutive_failures(isolated_dirs):
    """Body steps keep failing → max_consecutive_failures fires and the step
    reports failed."""
    tmp_path, workflows = isolated_dirs
    # The work step pins a model that doesn't exist and has no role fallback →
    # actually, simpler: make the plan step return empty so the LLM step fails
    # validation. We force failure by having the work marker return empty.
    _HOLDER["ollama"] = _ScriptedOllama(
        {"marker_plan": "task", "marker_work": ""}  # empty → step fails
    )
    yaml_path = _write_yaml(
        workflows, _ralph_yaml(tmp_path, max_iterations=10, max_consec=2)
    )
    engine = _engine()
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "failed"
    assert "consecutive" in (run.error or "").lower()


def test_ralph_halt_file_stops_gracefully(isolated_dirs):
    """A pre-existing halt_file stops the loop before any iteration runs,
    with success status."""
    tmp_path, workflows = isolated_dirs
    halt_file = tmp_path / "HALT"
    halt_file.write_text("stop")  # exists from the start
    _HOLDER["ollama"] = _ScriptedOllama(
        {"marker_plan": "task", "marker_work": '{"progress": "p", "done": false}'}
    )
    yaml_path = _write_yaml(
        workflows, _ralph_yaml(tmp_path, max_iterations=10, halt_file=str(halt_file))
    )
    engine = _engine()
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # No body steps ran — halted at the first boundary.
    assert _HOLDER["ollama"].call_order == []


def test_ralph_resumes_from_journal(isolated_dirs):
    """A journal with prior iterations causes the loop to skip them — it only
    runs the remaining iterations up to max_iterations."""
    tmp_path, workflows = isolated_dirs
    journal = tmp_path / "ralph_journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    # Pre-seed 3 completed iterations.
    journal.write_text(
        "\n".join(
            json.dumps({"iteration": i, "status": "completed"}) for i in (1, 2, 3)
        )
        + "\n"
    )
    _HOLDER["ollama"] = _ScriptedOllama(
        {"marker_plan": "task", "marker_work": '{"progress": "p", "done": false}'}
    )
    yaml_path = _write_yaml(workflows, _ralph_yaml(tmp_path, max_iterations=5))
    engine = _engine()
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Only iterations 4 and 5 ran this invocation → 2 work calls.
    assert len([c for c in _HOLDER["ollama"].call_order if c == "marker_work"]) == 2
    # Journal now has 5 total iteration records.
    lines = [l for l in journal.read_text().splitlines() if l.strip()]
    assert len(lines) == 5


_RALPH_SELF_LEARNING = textwrap.dedent("""
    id: test-ralph-learning
    name: Ralph Self-Learning
    schema_version: 1
    defaults:
      role: reasoning
      max_tokens: 512
    steps:
      - id: auto
        name: Self-Learning Loop
        kind: ralph
        outputs: [progress]
        ralph:
          journal_path: {journal}
          halt:
            max_iterations: 2
        body:
          - id: plan
            name: Plan With Playbook
            role: fast
            prompt:
              role_inline: marker_plan
              task: plan using prior lessons
            inputs:
              - $memory.playbook.dev_lessons
            outputs: [progress]
          - id: reflect
            name: Reflect Into Playbook
            kind: consolidate
            depends_on: [plan]
            inputs:
              - plan.progress
            outputs: [lesson]
            consolidate:
              target: playbook
              target_name: dev_lessons
              merge_strategy: append_with_dedup
              system_prompt: marker_reflect
    """)


def test_ralph_self_learning_playbook_loop(isolated_dirs):
    """The reflect (consolidate) body step writes a lesson to the playbook;
    a later iteration's plan step reads it back via $memory.* — the
    self-learning loop. We capture the plan prompt on iteration 2 to confirm
    iteration 1's lesson made it into the playbook and back into the prompt."""
    tmp_path, workflows = isolated_dirs
    journal = tmp_path / "ralph_journal.jsonl"

    plan_prompts: list[str] = []

    class _CapturingOllama(_ScriptedOllama):
        def chat(self, model, messages, **kwargs):
            all_content = " ".join(m.get("content", "") for m in messages)
            if "marker_plan" in all_content:
                plan_prompts.append(all_content)
            return super().chat(model, messages, **kwargs)

    _HOLDER["ollama"] = _CapturingOllama(
        {
            "marker_plan": "made progress on the task",
            "marker_reflect": "Lesson: prefer small commits",
        }
    )
    yaml_path = _write_yaml(workflows, _RALPH_SELF_LEARNING.format(journal=journal))
    engine = _engine()
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=[])
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Iteration 2's plan prompt should contain the lesson written in iteration 1.
    assert len(plan_prompts) == 2
    assert "prefer small commits" in plan_prompts[1]
    # And the playbook on disk holds the lesson.
    playbook = tmp_path / "memory_root" / "playbooks" / "dev_lessons.md"
    assert playbook.exists()
    assert "prefer small commits" in playbook.read_text()
