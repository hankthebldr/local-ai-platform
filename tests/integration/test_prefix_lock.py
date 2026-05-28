"""Phase 2c — prompt-prefix locking for single_model_pseudo_parallel.

The cache-hit latency win is only measurable on real hardware; here we
verify the STRUCTURAL invariant the optimization relies on: when
`execution.prefix_lock: true`, the engine renders each branch's system
message with a byte-identical leading block (shared context + output
schema), with the divergent role/task/constraints coming after.

If this invariant breaks, no cache hit is possible. If it holds, the
operator validates the actual latency benefit on the BD790i.
"""

from __future__ import annotations

import textwrap
import threading
from pathlib import Path

import pytest

from api.services.workflow_engine import WorkflowEngine


class _CapturingOllama:
    """Records the system message of every chat() call so the test can
    inspect what the composer produced for each branch."""

    def __init__(self):
        self.system_messages: list[str] = []
        self._lock = threading.Lock()

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        sys = next((m["content"] for m in messages if m["role"] == "system"), "")
        with self._lock:
            self.system_messages.append(sys)
        return {"content": "ok", "prompt_eval_count": 3, "eval_count": 1}

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


# Two branches, same model, same workflow context, divergent personas/tasks.
def _parallel_yaml(prefix_lock: bool):
    pl = "true" if prefix_lock else "false"
    return textwrap.dedent(f"""
        id: test-prefix-lock
        name: Prefix Lock
        schema_version: 1
        context:
          project: Enclave
          objective: parallel-branch prefix-lock check
        defaults:
          role: reasoning
          retries: 0
          retry_delay: 0
        steps:
          - id: par
            name: P
            kind: parallel
            outputs: [summary]
            execution:
              mode: single_model_pseudo_parallel
              prefix_lock: {pl}
            branches:
              - id: branch_a
                name: A
                model: mistral
                prompt:
                  role_inline: persona_A_marker_unique
                  task: do thing A
                outputs: [out]
              - id: branch_b
                name: B
                model: mistral
                prompt:
                  role_inline: persona_B_marker_unique
                  task: do thing B
                outputs: [out]
            gather:
              id: synth
              name: G
              model: mistral
              prompt:
                role_inline: synth_persona
                task: combine
              inputs: [branch_a.out, branch_b.out]
              outputs: [summary]
        """)


def test_prefix_lock_makes_branch_prefixes_byte_identical(isolated_dir):
    """With prefix_lock=true, the shared context+schema block leads each
    branch's system message — the leading bytes must match byte-for-byte
    across branches, and the per-branch persona must appear after."""
    yaml_path = _write_yaml(isolated_dir, _parallel_yaml(prefix_lock=True))
    ollama = _CapturingOllama()
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    # 2 branches + 1 gather (gather is NOT prefix-locked — it uses the
    # default template).
    sys_msgs = ollama.system_messages
    assert len(sys_msgs) == 3
    sys_a, sys_b, _gather = sys_msgs

    # Both branch system messages start with the shared `## Context` block.
    assert sys_a.startswith("## Context\n")
    assert sys_b.startswith("## Context\n")

    # The leading run is byte-identical until at least the first divergent
    # token (the per-branch persona). Find the first byte where they differ.
    common_len = 0
    for ca, cb in zip(sys_a, sys_b):
        if ca != cb:
            break
        common_len += 1
    # The shared prefix must include the full `## Context` and `## Output
    # Format` blocks before any divergence — pick a reasonable lower bound
    # (the rendered context dict is ~80 chars and the schema block another
    # ~150, so >150 is conservatively safe).
    assert common_len > 150, (
        f"prefix_lock branches diverged after only {common_len} chars; "
        f"shared prefix is too short to earn a cache hit. "
        f"sys_a head: {sys_a[:200]!r}"
    )

    # The per-branch discriminator (`A_marker_unique` / `B_marker_unique`)
    # must appear in the divergent tail — confirms the divergence is the
    # persona block, not something incidental. The `persona_` prefix itself
    # is byte-identical between branches so it falls inside the shared
    # leading prefix.
    divergent_a = sys_a[common_len:]
    divergent_b = sys_b[common_len:]
    assert "A_marker_unique" in divergent_a
    assert "B_marker_unique" in divergent_b
    # And the divergence must NOT be in the `## Context` block.
    assert "## Context" not in divergent_a
    assert "## Output Format" not in divergent_a


def test_prefix_lock_off_branches_diverge_immediately(isolated_dir):
    """Without prefix_lock, the persona leads — branches diverge at the
    very start of the system message. This is the baseline that
    prefix_lock=true changes."""
    yaml_path = _write_yaml(isolated_dir, _parallel_yaml(prefix_lock=False))
    ollama = _CapturingOllama()
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={})

    assert run.status == "completed", run.error
    sys_a, sys_b, _ = ollama.system_messages

    # The personas lead, so the two prefixes diverge inside the first
    # ~50 chars (the marker string itself is 25 chars).
    common_len = 0
    for ca, cb in zip(sys_a, sys_b):
        if ca != cb:
            break
        common_len += 1
    assert common_len < 50, (
        f"baseline (prefix_lock=false) branches share unexpectedly long "
        f"{common_len}-char prefix; the test isn't measuring the right thing"
    )


def test_prefix_lock_rejected_on_wrong_mode(isolated_dir):
    """The validator should reject prefix_lock=true on modes that can't
    benefit from it."""
    from api.exceptions import WorkflowValidationError

    bad = _parallel_yaml(prefix_lock=True).replace(
        "mode: single_model_pseudo_parallel",
        "mode: multi_model_concurrent",
    )
    yaml_path = _write_yaml(isolated_dir, bad)
    engine = WorkflowEngine(_CapturingOllama())
    with pytest.raises(WorkflowValidationError, match="prefix_lock=True only applies"):
        engine.load(str(yaml_path))


def test_prefix_lock_allowed_with_auto_mode(isolated_dir):
    """auto can resolve to pseudo_parallel at runtime, so the validator
    allows prefix_lock=true with mode=auto."""
    y = _parallel_yaml(prefix_lock=True).replace(
        "mode: single_model_pseudo_parallel",
        "mode: auto",
    )
    yaml_path = _write_yaml(isolated_dir, y)
    engine = WorkflowEngine(_CapturingOllama())
    defn = engine.load(str(yaml_path))
    # The workflow loads without error; runtime mode resolution happens later.
    assert defn.steps[0].execution.prefix_lock is True
    assert defn.steps[0].execution.mode == "auto"
