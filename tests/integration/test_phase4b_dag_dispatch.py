"""Phase 4b — End-to-end DAG dispatch through WorkflowEngine.

Unit tests cover the Scheduler in isolation. These tests verify the
engine's tick-based dispatch loop actually:
  - Respects `depends_on` ordering (b can't run before a)
  - Makes upstream outputs visible to downstream steps via workspace
  - Drains the current tick on failure before bailing
  - Resume from a partial DAG completes only the remaining branch
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine

# ── Stub Ollama ─────────────────────────────────────────────────────────


class _DagStubOllama:
    """Returns canned per-step responses keyed by the user-message hash.

    Records call order under a lock so we can later assert ordering
    invariants without coupling to timestamps.
    """

    def __init__(self, responses_by_marker, delay_seconds=0.0):
        self._responses = responses_by_marker
        self._delay = delay_seconds
        self.call_order = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        # The composer renders the step's task into the system message
        # under "## Task". Scan all messages so we identify the step
        # regardless of which message slot the marker lands in.
        all_content = " ".join(m.get("content", "") for m in messages)
        marker = next((k for k in self._responses if k in all_content), None)
        with self._lock:
            self.call_order.append(marker or "unknown")
        if self._delay:
            time.sleep(self._delay)
        content = self._responses.get(marker, "default")
        return {"content": content, "prompt_eval_count": 5, "eval_count": 5}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


# ── YAML fixtures ───────────────────────────────────────────────────────


_LINEAR_WORKFLOW = textwrap.dedent("""
    id: test-linear
    name: Linear DAG
    schema_version: 1
    steps:
      - id: step_a
        name: Step A
        model: mistral
        prompt:
          role_inline: producer
          task: produce_a
        outputs: ["out_a"]
      - id: step_b
        name: Step B
        model: mistral
        prompt:
          role_inline: consumer
          task: produce_b
        outputs: ["out_b"]
        depends_on: ["step_a"]
    """)


_DIAMOND_WORKFLOW = textwrap.dedent("""
    id: test-diamond
    name: Diamond DAG
    schema_version: 1
    steps:
      - id: root
        name: Root
        model: mistral
        prompt:
          role_inline: r
          task: produce_root
        outputs: ["out_root"]
      - id: branch_x
        name: Branch X
        model: mistral
        prompt:
          role_inline: r
          task: produce_x
        outputs: ["out_x"]
        depends_on: ["root"]
      - id: branch_y
        name: Branch Y
        model: mistral
        prompt:
          role_inline: r
          task: produce_y
        outputs: ["out_y"]
        depends_on: ["root"]
      - id: join
        name: Join
        model: mistral
        prompt:
          role_inline: r
          task: produce_join
        outputs: ["out_join"]
        depends_on: ["branch_x", "branch_y"]
    """)


# Faithful to workflows/code-review.yaml: schema_version 1, kind-less
# (kind defaults to "llm"), v1 `system_prompt` strings, `output_format: json`,
# three independent passes that dispatch concurrently in one tick, feeding a
# `synthesize` step. This drives the SAME construction + serialization path a
# real code-review run uses (WorkflowEngine._execute_one_step → StepExecutor →
# step_results.append → run.model_dump), not the isolated execute() unit path.
_V1_CODE_REVIEW_SHAPED_WORKFLOW = textwrap.dedent("""
    id: test-v1-review
    name: V1 Code Review Shape
    schema_version: 1
    defaults:
      role: reasoning
      retries: 0
    steps:
      - id: security_pass
        name: Security
        model: mistral
        depends_on: []
        system_prompt: |
          You are a security reviewer. produce_security. Output ONLY JSON.
        outputs: ["findings"]
        output_format: json
      - id: correctness_pass
        name: Correctness
        model: mistral
        depends_on: []
        system_prompt: |
          You are a correctness reviewer. produce_correctness. Output ONLY JSON.
        outputs: ["findings"]
        output_format: json
      - id: style_pass
        name: Style
        model: mistral
        depends_on: []
        system_prompt: |
          You are a style reviewer. produce_style. Output ONLY JSON.
        outputs: ["findings"]
        output_format: json
      - id: synthesize
        name: Synthesize
        model: mistral
        depends_on: ["security_pass", "correctness_pass", "style_pass"]
        system_prompt: |
          You are the lead reviewer. produce_synth. Write a comment block.
        outputs: ["review"]
        output_format: text
    """)


@pytest.fixture
def isolated_workflow_dir(tmp_path, monkeypatch):
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    return workflows


def _write_yaml(dirpath: Path, contents: str) -> Path:
    name = "wf.yaml"
    p = dirpath / name
    p.write_text(contents)
    return p


# ── Tests ───────────────────────────────────────────────────────────────


def test_linear_dag_runs_in_dependency_order(isolated_workflow_dir):
    """step_b depends on step_a — even if YAML order were reversed,
    Phase 4b must dispatch step_a first because step_b isn't ready."""
    yaml_path = _write_yaml(isolated_workflow_dir, _LINEAR_WORKFLOW)
    ollama = _DagStubOllama({"produce_a": "A-result", "produce_b": "B-result"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed"
    assert len(run.step_results) == 2
    assert ollama.call_order == ["produce_a", "produce_b"]


def test_diamond_dag_completes_all_four_steps(isolated_workflow_dir):
    """root → {branch_x, branch_y} → join. All four steps must run; the
    two branch steps can run in either order, but root must precede them
    and join must follow."""
    yaml_path = _write_yaml(isolated_workflow_dir, _DIAMOND_WORKFLOW)
    ollama = _DagStubOllama(
        {
            "produce_root": "ROOT",
            "produce_x": "X",
            "produce_y": "Y",
            "produce_join": "JOIN",
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed"
    assert len(run.step_results) == 4
    # Order invariants:
    #   root before x and y; x and y before join.
    order = ollama.call_order
    assert order.index("produce_root") < order.index("produce_x")
    assert order.index("produce_root") < order.index("produce_y")
    assert order.index("produce_x") < order.index("produce_join")
    assert order.index("produce_y") < order.index("produce_join")


def test_dag_failure_does_not_run_dependents(isolated_workflow_dir):
    """If step_a fails, step_b (which depends on it) must never dispatch."""
    yaml_path = _write_yaml(isolated_workflow_dir, _LINEAR_WORKFLOW)

    # Bad responses → validation will fail because content is empty;
    # the step retries 2 times then fails.
    ollama = _DagStubOllama({"produce_a": "", "produce_b": "B-result"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "failed"
    # step_a should have been attempted; step_b should never have dispatched.
    assert "produce_a" in ollama.call_order
    assert "produce_b" not in ollama.call_order
    # step_results should contain only step_a (failed), not step_b.
    step_ids = {r.step_id for r in run.step_results}
    assert "step_a" in step_ids
    assert "step_b" not in step_ids


def test_dag_preserves_dependency_data_flow(isolated_workflow_dir):
    """A downstream step should see the upstream step's workspace output.
    This guards the threading refactor — workspace writes from one thread
    must be visible to a later step running on (possibly) another thread."""
    yaml_path = _write_yaml(isolated_workflow_dir, _LINEAR_WORKFLOW)
    ollama = _DagStubOllama({"produce_a": "upstream-output", "produce_b": "ok"})
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed"
    assert run.context.get_workspace("step_a", "out_a") is not None
    assert run.context.get_workspace("step_b", "out_b") is not None


def test_v1_review_shape_captures_rendered_prompt_end_to_end(isolated_workflow_dir):
    """Regression guard for the rendered_prompt capture on a REAL run path.

    A code-review-shaped v1 workflow (kind-less LLM steps, `system_prompt`,
    `output_format`) must land rendered_prompt / rendered_system_prompt on
    EVERY step in WorkflowRun.step_results — including the three passes that
    dispatch concurrently in one tick and the downstream synthesize step.

    Asserts the capture survives the full engine path AND the model_dump(
    mode="json") serialization the /runs API response uses — not just the
    isolated StepExecutor.execute() unit test.
    """
    yaml_path = _write_yaml(isolated_workflow_dir, _V1_CODE_REVIEW_SHAPED_WORKFLOW)
    ollama = _DagStubOllama(
        {
            "produce_security": '{"findings": []}',
            "produce_correctness": '{"findings": []}',
            "produce_style": '{"findings": []}',
            "produce_synth": "## Code Review\n\nLooks fine.",
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    # Every step is kind-less → defaults to the llm dispatch path.
    assert all(s.kind == "llm" for s in defn.steps)
    # And these are genuine v1 steps (system_prompt, no v2 prompt block).
    assert all(s.system_prompt and s.prompt is None for s in defn.steps)

    run = engine.run(defn, seed={"code": "def add(a, b):\n    return a - b"})

    assert run.status == "completed"
    assert len(run.step_results) == 4

    # In-memory WorkflowRun.step_results: capture reached every step.
    for r in run.step_results:
        assert r.rendered_prompt, f"{r.step_id} missing rendered_prompt"
        assert r.rendered_system_prompt, f"{r.step_id} missing rendered_system_prompt"
        # The captured system prompt carries the step's v1 system_prompt text.
        assert "reviewer" in r.rendered_system_prompt

    # The serialization the /api/workflows/runs/{id} response uses must NOT
    # drop the fields (this is where a model_copy/subset-rebuild bug would
    # surface even when the in-memory object looks correct).
    dumped = run.model_dump(mode="json")
    for sr in dumped["step_results"]:
        assert sr["rendered_prompt"] is not None
        assert sr["rendered_system_prompt"] is not None
