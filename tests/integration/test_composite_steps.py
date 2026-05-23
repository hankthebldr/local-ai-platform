"""Phase 1 — Composite step kinds: parallel + loop.

These tests drive the engine through real fan-out / gather and loop flows
with a stubbed Ollama. The model layer is covered by tests/test_workflow_models.py;
this file verifies the engine actually executes the composite topology.
"""

from __future__ import annotations

import textwrap
import threading
import time
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine, _evaluate_gate
from api.models.workflow_models import WorkflowContext

# ── Stub Ollama ─────────────────────────────────────────────────────────


class _MarkerOllama:
    """Returns canned responses keyed by a marker substring in the prompt.

    Records call order so tests can assert concurrency (parallel branches
    overlap) and iteration counts (loop body runs N times).
    """

    def __init__(self, responses_by_marker, delay_seconds=0.0):
        self._responses = responses_by_marker
        self._delay = delay_seconds
        self.call_order: list[str] = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        all_content = " ".join(m.get("content", "") for m in messages)
        marker = next((k for k in self._responses if k in all_content), None)
        with self._lock:
            self.call_order.append(marker or "unknown")
        if self._delay:
            time.sleep(self._delay)
        resp = self._responses.get(marker, '{"result": "default"}')
        if callable(resp):
            resp = resp(self.call_order.count(marker))
        return {"content": resp, "prompt_eval_count": 3, "eval_count": 3}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


# ── YAML fixtures ───────────────────────────────────────────────────────


_PARALLEL_HAPPY = textwrap.dedent("""
    id: test-parallel-happy
    name: Parallel Happy
    schema_version: 1
    steps:
      - id: par
        name: Parallel Fan-Out
        kind: parallel
        outputs: ["synthesized"]
        execution:
          mode: multi_model_concurrent
          max_concurrency: 3
        branches:
          - id: branch_extract
            name: Extract
            model: mistral
            prompt:
              role_inline: extractor
              task: marker_extract
            outputs: ["data"]
          - id: branch_classify
            name: Classify
            model: mistral
            prompt:
              role_inline: classifier
              task: marker_classify
            outputs: ["data"]
          - id: branch_pii
            name: PII
            model: mistral
            prompt:
              role_inline: pii
              task: marker_pii
            outputs: ["data"]
        gather:
          id: gather_synth
          name: Synthesize
          model: mistral
          prompt:
            role_inline: synth
            task: marker_synth
          inputs:
            - branch_extract.data
            - branch_classify.data
            - branch_pii.data
          outputs: ["synthesized"]
    """)


_PARALLEL_FAIL_FAST = textwrap.dedent("""
    id: test-parallel-fail-fast
    name: Parallel Fail Fast
    schema_version: 1
    steps:
      - id: par
        name: Parallel
        kind: parallel
        outputs: ["synthesized"]
        execution:
          mode: multi_model_concurrent
          failure_policy: fail_fast
        branches:
          - id: branch_ok
            name: OK
            model: mistral
            prompt:
              role_inline: r
              task: marker_ok
            outputs: ["data"]
          - id: branch_bad
            name: Bad
            model: nonexistent-pinned-model-no-fallback
            prompt:
              role_inline: r
              task: marker_bad
            outputs: ["data"]
        gather:
          id: gath
          name: Gather
          model: mistral
          prompt:
            role_inline: r
            task: marker_gather
          inputs:
            - branch_ok.data
            - branch_bad.data
          outputs: ["synthesized"]
    """)


_LOOP_GATE_SATISFIED_FIRST_TRY = textwrap.dedent("""
    id: test-loop-first-try
    name: Loop First Try
    schema_version: 1
    steps:
      - id: refine
        name: Refine Loop
        kind: loop
        outputs: ["final_text"]
        max_iterations: 3
        until:
          type: gate
          gate: "critic.approved == True"
        body:
          - id: drafter
            name: Drafter
            model: mistral
            prompt:
              role_inline: drafter
              task: marker_draft
            outputs: ["draft"]
          - id: critic
            name: Critic
            model: mistral
            prompt:
              role_inline: critic
              task: marker_critic
            inputs:
              - drafter.draft
            outputs: ["approved", "final_text"]
    """)


_LOOP_GATE_SATISFIED_SECOND_TRY = textwrap.dedent("""
    id: test-loop-second-try
    name: Loop Second Try
    schema_version: 1
    steps:
      - id: refine
        name: Refine Loop
        kind: loop
        outputs: ["final_text"]
        max_iterations: 5
        until:
          type: gate
          gate: "critic.approved == True"
        body:
          - id: drafter
            name: Drafter
            model: mistral
            prompt:
              role_inline: drafter
              task: marker_draft
            outputs: ["draft"]
          - id: critic
            name: Critic
            model: mistral
            prompt:
              role_inline: critic
              task: marker_critic
            inputs:
              - drafter.draft
            outputs: ["approved", "final_text"]
    """)


_LOOP_MAX_ITERS_EMIT_BEST = textwrap.dedent("""
    id: test-loop-emit-best
    name: Loop Emit Best
    schema_version: 1
    steps:
      - id: refine
        name: Refine Loop
        kind: loop
        outputs: ["final_text"]
        max_iterations: 2
        until:
          type: gate
          gate: "critic.approved == True"
          on_max_iterations: emit_best
        body:
          - id: drafter
            name: Drafter
            model: mistral
            prompt:
              role_inline: drafter
              task: marker_draft
            outputs: ["draft"]
          - id: critic
            name: Critic
            model: mistral
            prompt:
              role_inline: critic
              task: marker_critic
            inputs:
              - drafter.draft
            outputs: ["approved", "final_text"]
    """)


_LOOP_MAX_ITERS_FAIL = textwrap.dedent("""
    id: test-loop-fail
    name: Loop Fail
    schema_version: 1
    steps:
      - id: refine
        name: Refine Loop
        kind: loop
        outputs: ["final_text"]
        max_iterations: 2
        until:
          type: gate
          gate: "critic.approved == True"
          on_max_iterations: fail
        body:
          - id: drafter
            name: Drafter
            model: mistral
            prompt:
              role_inline: drafter
              task: marker_draft
            outputs: ["draft"]
          - id: critic
            name: Critic
            model: mistral
            prompt:
              role_inline: critic
              task: marker_critic
            inputs:
              - drafter.draft
            outputs: ["approved", "final_text"]
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


# ── Parallel tests ──────────────────────────────────────────────────────


def test_parallel_happy_path_runs_all_branches_then_gather(isolated_dir):
    """All three branches run, then gather synthesizes; parent's workspace
    holds the synthesized output."""
    yaml_path = _write_yaml(isolated_dir, _PARALLEL_HAPPY)
    # Single-output steps write the raw response verbatim — by design, since
    # there's no key-mapping ambiguity. Multi-output steps run JSON auto-extract.
    # See StepExecutor._write_outputs for the contract.
    ollama = _MarkerOllama(
        {
            "marker_extract": "schema_fields",
            "marker_classify": "event_types",
            "marker_pii": "pii_findings",
            "marker_synth": "combined report",
        },
        delay_seconds=0.01,
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=[])

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Three branches + one gather call.
    assert len(ollama.call_order) == 4
    # Gather must run last (after all branches).
    assert ollama.call_order[-1] == "marker_synth"
    # All three branch markers must appear before gather.
    branches_seen = ollama.call_order[:-1]
    assert set(branches_seen) == {"marker_extract", "marker_classify", "marker_pii"}
    # Parent's workspace holds the gather's output (mapped via parent.outputs).
    assert run.context.get_workspace("par", "synthesized") == "combined report"


def test_parallel_fail_fast_aborts_on_branch_failure(isolated_dir):
    """A branch pinning a missing model with no fallback role causes the
    composite to fail before gather runs."""
    yaml_path = _write_yaml(isolated_dir, _PARALLEL_FAIL_FAST)
    ollama = _MarkerOllama(
        {
            "marker_ok": '{"data": "ok"}',
            "marker_bad": '{"data": "should not be called"}',
            "marker_gather": '{"synthesized": "should not run"}',
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "failed"
    assert (
        "model resolution failed" in (run.error or "").lower()
        or "aborted" in (run.error or "").lower()
    )
    # Gather must NOT have run.
    assert "marker_gather" not in ollama.call_order


# ── Loop tests ──────────────────────────────────────────────────────────


def test_loop_gate_satisfied_on_first_iteration(isolated_dir):
    """Critic approves immediately — loop terminates after one iteration."""
    yaml_path = _write_yaml(isolated_dir, _LOOP_GATE_SATISFIED_FIRST_TRY)
    ollama = _MarkerOllama(
        {
            "marker_draft": '{"draft": "first attempt"}',
            "marker_critic": '{"approved": true, "final_text": "blessed v1"}',
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=[])

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # 1 iteration × 2 body steps = 2 LLM calls.
    assert len(ollama.call_order) == 2
    # Parent workspace populated from last body step (critic) via positional
    # mapping: loop.outputs=[final_text] ← critic.outputs[1]=final_text.
    assert run.context.get_workspace("refine", "final_text") == "blessed v1"


def test_loop_iterates_until_gate_satisfied(isolated_dir):
    """Critic rejects first, approves second — loop runs body twice."""
    yaml_path = _write_yaml(isolated_dir, _LOOP_GATE_SATISFIED_SECOND_TRY)

    # Critic returns False on first call, True on second.
    def _critic_response(call_number: int) -> str:
        if call_number == 1:
            return '{"approved": false, "final_text": "rejected v1"}'
        return '{"approved": true, "final_text": "blessed v2"}'

    ollama = _MarkerOllama(
        {
            "marker_draft": '{"draft": "attempt"}',
            "marker_critic": _critic_response,
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # 2 iterations × 2 body steps = 4 LLM calls.
    assert len(ollama.call_order) == 4
    assert run.context.get_workspace("refine", "final_text") == "blessed v2"


def test_loop_emit_best_on_max_iterations(isolated_dir):
    """Critic never approves; loop hits max_iterations with emit_best —
    succeeds with the last iteration's output."""
    yaml_path = _write_yaml(isolated_dir, _LOOP_MAX_ITERS_EMIT_BEST)
    ollama = _MarkerOllama(
        {
            "marker_draft": '{"draft": "attempt"}',
            "marker_critic": '{"approved": false, "final_text": "best-effort"}',
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # max_iterations=2, 2 body steps each = 4 calls.
    assert len(ollama.call_order) == 4
    assert run.context.get_workspace("refine", "final_text") == "best-effort"


def test_loop_fails_on_max_iterations_when_policy_is_fail(isolated_dir):
    """Critic never approves; on_max_iterations=fail surfaces failure."""
    yaml_path = _write_yaml(isolated_dir, _LOOP_MAX_ITERS_FAIL)
    ollama = _MarkerOllama(
        {
            "marker_draft": '{"draft": "attempt"}',
            "marker_critic": '{"approved": false, "final_text": "rejected"}',
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "failed"
    assert "max_iterations" in (run.error or "")


# ── Gate evaluator unit tests ───────────────────────────────────────────


class TestEvaluateGate:
    def _ctx(self, **workspace):
        return WorkflowContext(seed={}, workspace=dict(workspace))

    def test_equality(self):
        ctx = self._ctx(critic={"approved": True})
        assert _evaluate_gate("critic.approved == True", ctx) is True
        assert _evaluate_gate("critic.approved == False", ctx) is False

    def test_compound_boolean(self):
        ctx = self._ctx(critic={"approved": True, "score": 8})
        assert _evaluate_gate("critic.approved and critic.score >= 5", ctx) is True
        assert _evaluate_gate("critic.approved and critic.score > 100", ctx) is False

    def test_not_operator(self):
        ctx = self._ctx(critic={"approved": False})
        assert _evaluate_gate("not critic.approved", ctx) is True

    def test_membership(self):
        ctx = self._ctx(critic={"issues": []})
        assert _evaluate_gate("'foo' not in critic.issues", ctx) is True

    def test_rejects_function_calls(self):
        ctx = self._ctx(critic={"approved": True})
        with pytest.raises(ValueError, match="disallowed construct"):
            _evaluate_gate("__import__('os').system('echo bad')", ctx)

    def test_rejects_attribute_access(self):
        ctx = self._ctx(critic={"approved": "yes"})
        with pytest.raises(ValueError, match="disallowed construct"):
            _evaluate_gate("critic.approved.upper() == 'YES'", ctx)

    def test_rejects_lambda(self):
        ctx = self._ctx(critic={"approved": True})
        with pytest.raises(ValueError, match="disallowed construct"):
            _evaluate_gate("(lambda: True)()", ctx)

    def test_rejects_invalid_syntax(self):
        ctx = self._ctx(critic={"approved": True})
        with pytest.raises(ValueError, match="invalid syntax"):
            _evaluate_gate("critic.approved ===", ctx)


# ── Validator: cross-tree duplicate IDs ─────────────────────────────────


_NESTED_DUPLICATE_IDS = textwrap.dedent("""
    id: test-dupes
    name: Dupes
    schema_version: 1
    steps:
      - id: dup
        name: Top
        model: mistral
        prompt:
          role_inline: r
          task: t
        outputs: ["x"]
      - id: par
        name: Par
        kind: parallel
        outputs: ["x"]
        branches:
          - id: dup
            name: Branch dup
            model: mistral
            prompt:
              role_inline: r
              task: t
            outputs: ["x"]
          - id: branch_b
            name: B
            model: mistral
            prompt:
              role_inline: r
              task: t
            outputs: ["x"]
        gather:
          id: gath
          name: G
          model: mistral
          prompt:
            role_inline: r
            task: t
          inputs:
            - dup.x
            - branch_b.x
          outputs: ["x"]
    """)


def test_validator_rejects_nested_duplicate_ids(isolated_dir):
    from api.exceptions import WorkflowValidationError

    yaml_path = _write_yaml(isolated_dir, _NESTED_DUPLICATE_IDS)
    engine = WorkflowEngine(_MarkerOllama({}))
    defn = engine.load(str(yaml_path))
    with pytest.raises(WorkflowValidationError, match="Duplicate step IDs"):
        engine.validate(defn, seed_keys=[])


# ── Phase 2: single-model parallelism modes ─────────────────────────────


_PSEUDO_PARALLEL_HAPPY = textwrap.dedent("""
    id: test-pseudo-parallel
    name: Pseudo Parallel
    schema_version: 1
    steps:
      - id: par
        name: Pseudo Parallel
        kind: parallel
        outputs: ["synth"]
        execution:
          mode: single_model_pseudo_parallel
          failure_policy: fail_fast
        branches:
          - id: branch_first
            name: First
            model: mistral
            prompt:
              role_inline: r
              task: marker_first
            outputs: ["data"]
          - id: branch_second
            name: Second
            model: mistral
            prompt:
              role_inline: r
              task: marker_second
            outputs: ["data"]
          - id: branch_third
            name: Third
            model: mistral
            prompt:
              role_inline: r
              task: marker_third
            outputs: ["data"]
        gather:
          id: gath
          name: G
          model: mistral
          prompt:
            role_inline: r
            task: marker_gather
          inputs:
            - branch_first.data
            - branch_second.data
            - branch_third.data
          outputs: ["synth"]
    """)


_SINGLE_MODEL_CONCURRENT_MIXED = textwrap.dedent("""
    id: test-single-model-concurrent-bad
    name: Mixed Model Rejection
    schema_version: 1
    steps:
      - id: par
        name: Bad
        kind: parallel
        outputs: ["synth"]
        execution:
          mode: single_model_concurrent
        branches:
          - id: branch_a
            name: A
            model: mistral
            prompt:
              role_inline: r
              task: marker_a
            outputs: ["data"]
          - id: branch_b
            name: B
            model: llama3
            prompt:
              role_inline: r
              task: marker_b
            outputs: ["data"]
        gather:
          id: gath
          name: G
          model: mistral
          prompt:
            role_inline: r
            task: marker_gather
          inputs:
            - branch_a.data
            - branch_b.data
          outputs: ["synth"]
    """)


_AUTO_SAME_MODEL = textwrap.dedent("""
    id: test-auto-same
    name: Auto Same Model
    schema_version: 1
    steps:
      - id: par
        name: Auto
        kind: parallel
        outputs: ["synth"]
        execution:
          mode: auto
        branches:
          - id: branch_a
            name: A
            model: mistral
            prompt:
              role_inline: r
              task: marker_a
            outputs: ["data"]
          - id: branch_b
            name: B
            model: mistral
            prompt:
              role_inline: r
              task: marker_b
            outputs: ["data"]
        gather:
          id: gath
          name: G
          model: mistral
          prompt:
            role_inline: r
            task: marker_gather
          inputs:
            - branch_a.data
            - branch_b.data
          outputs: ["synth"]
    """)


class _MultiModelOllama(_MarkerOllama):
    """Ollama stub that advertises multiple models so resolver doesn't fold
    distinct pinned names into the same canonical resolution."""

    def list_models(self):
        return [{"name": "mistral:latest"}, {"name": "llama3:latest"}]


def test_pseudo_parallel_dispatches_in_declared_order(isolated_dir):
    """single_model_pseudo_parallel must run branches sequentially in YAML
    declaration order — the prompt cache between branches depends on
    deterministic call ordering."""
    yaml_path = _write_yaml(isolated_dir, _PSEUDO_PARALLEL_HAPPY)
    ollama = _MarkerOllama(
        {
            "marker_first": "first_result",
            "marker_second": "second_result",
            "marker_third": "third_result",
            "marker_gather": "synth_result",
        },
        delay_seconds=0.01,
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=[])

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # 3 branches + 1 gather = 4 calls.
    assert len(ollama.call_order) == 4
    # Branches in declared order, gather last.
    assert ollama.call_order == [
        "marker_first",
        "marker_second",
        "marker_third",
        "marker_gather",
    ]


def test_single_model_concurrent_rejects_mixed_models(isolated_dir):
    """Branches resolving to different models under single_model_concurrent
    surface a clear engine-level error rather than silently running."""
    yaml_path = _write_yaml(isolated_dir, _SINGLE_MODEL_CONCURRENT_MIXED)
    ollama = _MultiModelOllama(
        {
            "marker_a": "should_not_run",
            "marker_b": "should_not_run",
            "marker_gather": "should_not_run",
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "failed"
    assert "different" in (run.error or "").lower() or "mode=" in (run.error or "")
    # No LLM calls should have been issued at all — pre-flight check rejected.
    assert ollama.call_order == []


def test_auto_mode_picks_pseudo_parallel_for_same_model(isolated_dir):
    """When all branches resolve to the same model, `mode: auto` resolves to
    `single_model_pseudo_parallel` — branches run in declared order."""
    yaml_path = _write_yaml(isolated_dir, _AUTO_SAME_MODEL)
    ollama = _MarkerOllama(
        {
            "marker_a": "a_result",
            "marker_b": "b_result",
            "marker_gather": "synth_result",
        },
        delay_seconds=0.01,
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Sequential dispatch: a, b, gather (in declared order).
    assert ollama.call_order == ["marker_a", "marker_b", "marker_gather"]


def test_auto_mode_picks_multi_model_concurrent_for_mixed(isolated_dir):
    """When branches resolve to different models, `mode: auto` resolves to
    `multi_model_concurrent` — branches may complete in any order."""
    yaml_text = _AUTO_SAME_MODEL.replace(
        "model: mistral\n            prompt:\n              role_inline: r\n              task: marker_b",
        "model: llama3\n            prompt:\n              role_inline: r\n              task: marker_b",
    )
    yaml_path = _write_yaml(isolated_dir, yaml_text)
    ollama = _MultiModelOllama(
        {
            "marker_a": "a_result",
            "marker_b": "b_result",
            "marker_gather": "synth_result",
        },
        delay_seconds=0.01,
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # Both branches ran, then gather. Order of branches is non-deterministic
    # under concurrent dispatch — assert by set rather than sequence.
    assert len(ollama.call_order) == 3
    assert set(ollama.call_order[:2]) == {"marker_a", "marker_b"}
    assert ollama.call_order[-1] == "marker_gather"


def test_single_model_concurrent_accepts_same_model_branches(isolated_dir):
    """single_model_concurrent passes pre-flight validation when every branch
    resolves to the same model, then executes (subject to the daemon's
    semaphore). The MAX_CONCURRENT_LLM=1 warning is best-effort log output;
    we assert behavior rather than log content to keep the test robust."""
    yaml_text = _PSEUDO_PARALLEL_HAPPY.replace(
        "mode: single_model_pseudo_parallel",
        "mode: single_model_concurrent",
    )
    yaml_path = _write_yaml(isolated_dir, yaml_text)
    ollama = _MarkerOllama(
        {
            "marker_first": "a",
            "marker_second": "b",
            "marker_third": "c",
            "marker_gather": "synth",
        }
    )
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # All 3 branches + gather invoked.
    assert len(ollama.call_order) == 4
    assert set(ollama.call_order[:3]) == {
        "marker_first",
        "marker_second",
        "marker_third",
    }
    assert ollama.call_order[-1] == "marker_gather"
