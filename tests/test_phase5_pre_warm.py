"""Phase 5 — pre-warm next-step model during current step's inference.

Covers:
  1. OllamaService.pre_warm() — bypasses _LLM_SEMAPHORE, fires /api/generate
     with empty prompt + num_predict=0
  2. Engine wiring — pre_warm fires for next-tick models when arch.transition_plan
     says it's safe; skipped on NVIDIA single + bandwidth contention
  3. Deduplication — same model isn't pre-warmed twice concurrently
  4. Current-tick models aren't pre-warmed (they're already loading)
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from api.services.ollama_service import OllamaService


# ── OllamaService.pre_warm ───────────────────────────────────────────────


def test_pre_warm_posts_empty_prompt_with_num_predict_zero():
    """Pre-warm uses /api/generate with empty prompt + num_predict=0 so
    Ollama loads the GGUF but produces no tokens."""
    svc = OllamaService(host="http://test")
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "model": "qwen2.5-coder:32b",
        "load_duration": 2_400_000_000,
        "total_duration": 2_500_000_000,
    }
    fake_response.raise_for_status = MagicMock()
    with patch(
        "api.services.ollama_service.requests.post", return_value=fake_response
    ) as mock_post:
        result = svc.pre_warm("qwen2.5-coder:32b", keep_alive="30m")
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "http://test/api/generate"
    payload = kwargs["json"]
    assert payload["model"] == "qwen2.5-coder:32b"
    assert payload["prompt"] == ""
    assert payload["keep_alive"] == "30m"
    assert payload["options"]["num_predict"] == 0
    # Telemetry surfaces in the returned dict.
    assert result["load_duration_ms"] == 2400.0


def test_pre_warm_does_not_acquire_llm_semaphore():
    """Pre-warm must NOT touch _LLM_SEMAPHORE — that's the whole point:
    the engine wants to overlap pre-warm with in-flight inference."""
    from api.services import ollama_service

    # Acquire the semaphore and hold it for the test. If pre_warm tries
    # to acquire it, the test will deadlock (timeout would be the only
    # signal). We assert no deadlock by completing within a small budget.
    svc = OllamaService(host="http://test")
    fake_response = MagicMock()
    fake_response.json.return_value = {"load_duration": 0}
    fake_response.raise_for_status = MagicMock()

    acquired = ollama_service._LLM_SEMAPHORE.acquire(blocking=False)
    try:
        with patch(
            "api.services.ollama_service.requests.post",
            return_value=fake_response,
        ):
            start = time.monotonic()
            svc.pre_warm("anything")
            elapsed = time.monotonic() - start
        # Should complete in milliseconds; >100ms suggests we waited on the
        # semaphore we deliberately held.
        assert elapsed < 0.1, (
            f"pre_warm took {elapsed:.2f}s with semaphore held — "
            "it acquired the semaphore (it must not)"
        )
    finally:
        if acquired:
            ollama_service._LLM_SEMAPHORE.release()


# ── Engine wiring ────────────────────────────────────────────────────────


class _FakeArch:
    """Mock arch whose transition_plan can be tuned per-pair."""

    def __init__(self, pre_warm_next=True):
        self.name = SimpleNamespace(value="fake_arch")
        self.total_memory_gb = 48.0
        self._pre_warm_next = pre_warm_next
        self.transition_calls = []

    def transition_plan(self, prev_step, next_step):
        self.transition_calls.append((prev_step.id, next_step.id))
        return SimpleNamespace(
            pre_warm_next=self._pre_warm_next,
            pre_warm_target_gpu=None,
            evict_at_prev_step=True,
            evict_via_keep_alive_zero=True,
            rationale="test",
        )

    def schedule_ready(self, ready):
        # Mock arch is sequential: head + deferred rest, same as nvidia_single.
        if not ready:
            return []
        head = SimpleNamespace(step_id=ready[0].id, placement=0, deferred=False)
        rest = [
            SimpleNamespace(
                step_id=s.id, placement=None, deferred=True, defer_reason="seq"
            )
            for s in ready[1:]
        ]
        return [head] + rest

    def snapshot(self):
        return SimpleNamespace(
            level="ok",
            per_pool=[{"pool_id": 0, "free_gb": 40, "used_gb": 8}],
            timestamp=time.time(),
        )

    def feasible(self, island):
        return SimpleNamespace(fits=True, reason=None)


def _make_engine_with_arch(arch):
    """Build a WorkflowEngine with a stub Ollama + injected arch."""
    from api.services import architecture as arch_mod
    from api.services.workflow_engine import WorkflowEngine

    class _Stub:
        def __init__(self):
            self.calls = []
            self.pre_warm_calls = []

        def chat(self, model, messages, **kw):
            self.calls.append(model)
            return {"content": "ok", "prompt_eval_count": 1, "eval_count": 1}

        def pre_warm(self, model, keep_alive=None):
            self.pre_warm_calls.append(model)
            return {"model": model, "load_duration_ms": 0.0}

        def health_check(self):
            return True

        def list_models(self):
            return [{"name": "model-a:latest"}, {"name": "model-b:latest"}]

    arch_mod._set_current(arch)
    engine = WorkflowEngine(_Stub())
    return engine


def _two_step_diff_models_workflow():
    """step_a uses model-a, step_b uses model-b (depends_on a)."""
    from api.models.workflow_models import (
        AgentStep,
        StepPrompt,
        WorkflowDefaults,
        WorkflowDefinition,
    )

    return WorkflowDefinition(
        id="t",
        name="t",
        steps=[
            AgentStep(
                id="step_a",
                name="A",
                model="model-a",
                prompt=StepPrompt(role_inline="r", task="produce_a"),
                outputs=["out_a"],
            ),
            AgentStep(
                id="step_b",
                name="B",
                model="model-b",
                prompt=StepPrompt(role_inline="r", task="produce_b"),
                outputs=["out_b"],
                depends_on=["step_a"],
            ),
        ],
        defaults=WorkflowDefaults(),
    )


def test_pre_warm_fires_for_next_tick_model(tmp_path, monkeypatch):
    """When tick 1 dispatches step_a (model-a), the engine should fire
    pre_warm for model-b (the next tick's model)."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    from api.services import architecture as arch_mod

    arch = _FakeArch(pre_warm_next=True)
    engine = _make_engine_with_arch(arch)
    try:
        run = engine.run(_two_step_diff_models_workflow(), seed={})
        # Give daemon pre-warm threads a moment to fire (they're fire-and-forget).
        time.sleep(0.1)
        assert run.status == "completed"
        # Stub.pre_warm should have been called at least for model-b.
        assert "model-b:latest" in engine.ollama.pre_warm_calls
    finally:
        arch_mod._current_architecture = None


def test_pre_warm_skipped_when_arch_says_no(tmp_path, monkeypatch):
    """NVIDIA single + bandwidth contention case — arch returns
    pre_warm_next=False. Engine must not fire pre_warm."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    from api.services import architecture as arch_mod

    arch = _FakeArch(pre_warm_next=False)
    engine = _make_engine_with_arch(arch)
    try:
        run = engine.run(_two_step_diff_models_workflow(), seed={})
        time.sleep(0.1)
        assert run.status == "completed"
        # Pre-warm should never have fired.
        assert engine.ollama.pre_warm_calls == []
        # ...but arch.transition_plan WAS consulted.
        assert arch.transition_calls, "arch.transition_plan was never asked"
    finally:
        arch_mod._current_architecture = None


def test_pre_warm_skipped_for_current_tick_models(tmp_path, monkeypatch):
    """If the next-tick step uses the SAME model as a current-tick step,
    skip pre-warm — the model is already loading."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    from api.models.workflow_models import (
        AgentStep,
        StepPrompt,
        WorkflowDefaults,
        WorkflowDefinition,
    )
    from api.services import architecture as arch_mod

    same_model_workflow = WorkflowDefinition(
        id="t",
        name="t",
        steps=[
            AgentStep(
                id="step_a",
                name="A",
                model="model-a",
                prompt=StepPrompt(role_inline="r", task="produce_a"),
                outputs=["out_a"],
            ),
            AgentStep(
                id="step_b",
                name="B",
                model="model-a",  # SAME model as step_a
                prompt=StepPrompt(role_inline="r", task="produce_b"),
                outputs=["out_b"],
                depends_on=["step_a"],
            ),
        ],
        defaults=WorkflowDefaults(),
    )

    arch = _FakeArch(pre_warm_next=True)
    engine = _make_engine_with_arch(arch)
    try:
        run = engine.run(same_model_workflow, seed={})
        time.sleep(0.1)
        assert run.status == "completed"
        # No pre_warm — both steps share model-a.
        assert engine.ollama.pre_warm_calls == []
    finally:
        arch_mod._current_architecture = None


def test_pre_warm_dedup_prevents_double_fire(tmp_path, monkeypatch):
    """If two next-tick steps both need model-b, fire pre_warm only once."""
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    from api.models.workflow_models import (
        AgentStep,
        StepPrompt,
        WorkflowDefaults,
        WorkflowDefinition,
    )
    from api.services import architecture as arch_mod

    fan_out_workflow = WorkflowDefinition(
        id="t",
        name="t",
        steps=[
            AgentStep(
                id="root",
                name="Root",
                model="model-a",
                prompt=StepPrompt(role_inline="r", task="produce_root"),
                outputs=["out_root"],
            ),
            AgentStep(
                id="branch_1",
                name="Branch 1",
                model="model-b",
                prompt=StepPrompt(role_inline="r", task="produce_b1"),
                outputs=["out_b1"],
                depends_on=["root"],
            ),
            AgentStep(
                id="branch_2",
                name="Branch 2",
                model="model-b",  # same model as branch_1
                prompt=StepPrompt(role_inline="r", task="produce_b2"),
                outputs=["out_b2"],
                depends_on=["root"],
            ),
        ],
        defaults=WorkflowDefaults(),
    )

    arch = _FakeArch(pre_warm_next=True)
    engine = _make_engine_with_arch(arch)
    try:
        run = engine.run(fan_out_workflow, seed={})
        time.sleep(0.2)
        assert run.status == "completed"
        # model-b should be pre-warmed once (dedup), not twice (once per branch).
        b_calls = [m for m in engine.ollama.pre_warm_calls if m == "model-b:latest"]
        assert len(b_calls) == 1, (
            f"expected 1 pre-warm for model-b, got {len(b_calls)}: "
            f"{engine.ollama.pre_warm_calls}"
        )
    finally:
        arch_mod._current_architecture = None
