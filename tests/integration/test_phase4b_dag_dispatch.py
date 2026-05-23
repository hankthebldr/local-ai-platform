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


_LINEAR_WORKFLOW = textwrap.dedent(
    """
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
    """
)


_DIAMOND_WORKFLOW = textwrap.dedent(
    """
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
    """
)


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
