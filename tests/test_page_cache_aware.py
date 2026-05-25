"""Phase 5.4 — page-cache awareness on UnifiedArchitecture.

When a model was recently evicted on macOS / Linux unified, its weights
typically stay in the OS page cache. A re-mmap is essentially free —
no PCIe transfer, no disk read.

Covers:
  1. UnifiedArchitecture.transition_plan accepts `recently_evicted` kwarg
  2. warm_eviction_candidate flag is set when next.model is in the list
  3. NVIDIA arches don't grow a recently_evicted concept (no page cache
     in VRAM)
  4. Engine helper _recently_evicted_models builds the list from
     workflow_run.step_results within the configured window
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from api.services.architecture import ArchClass
from api.services.arch_impl.unified import UnifiedArchitecture


def _step(model_name):
    return SimpleNamespace(id="s", model=model_name)


# ── UnifiedArchitecture.transition_plan recently_evicted ────────────────


def test_unified_transition_plan_accepts_recently_evicted_kwarg():
    """The new kwarg is optional and doesn't break existing call sites."""
    arch = UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED,
        total_memory_gb=48.0,
        bandwidth_gbps=400.0,
    )
    plan = arch.transition_plan(_step("a"), _step("b"))
    assert plan.pre_warm_next is True
    assert plan.warm_eviction_candidate is False  # no hint passed


def test_unified_marks_warm_when_next_model_recently_evicted():
    """next.model in recently_evicted → warm_eviction_candidate=True."""
    arch = UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED,
        total_memory_gb=48.0,
        bandwidth_gbps=400.0,
    )
    plan = arch.transition_plan(
        _step("a"),
        _step("b"),
        recently_evicted=["b", "c"],
    )
    assert plan.warm_eviction_candidate is True
    assert "page cache" in (plan.rationale or "").lower()


def test_unified_not_warm_when_next_not_in_evicted_list():
    arch = UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED,
        total_memory_gb=48.0,
        bandwidth_gbps=400.0,
    )
    plan = arch.transition_plan(
        _step("a"),
        _step("b"),
        recently_evicted=["c", "d"],  # b not in list
    )
    assert plan.warm_eviction_candidate is False


def test_unified_terminal_step_returns_no_warm_candidate():
    """Terminal step (next_step=None) — no pre-warm, no warm-candidate."""
    arch = UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED,
        total_memory_gb=48.0,
        bandwidth_gbps=400.0,
    )
    plan = arch.transition_plan(_step("a"), None, recently_evicted=["b"])
    assert plan.pre_warm_next is False
    assert plan.warm_eviction_candidate is False


def test_unified_x86_cpu_also_benefits():
    """The same impl serves cpu_x86; page cache still applies."""
    arch = UnifiedArchitecture(
        arch_class=ArchClass.CPU_X86,
        total_memory_gb=64.0,
        bandwidth_gbps=80.0,
    )
    plan = arch.transition_plan(_step("a"), _step("b"), recently_evicted=["b"])
    assert plan.warm_eviction_candidate is True


# ── NVIDIA arches: warm_eviction_candidate stays False ──────────────────


def test_nvidia_single_does_not_set_warm_candidate():
    """NVIDIA discrete-VRAM arches have no page-cache analogue.
    Their transition_plan does not consume recently_evicted."""
    from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

    arch = NvidiaSingleArchitecture(
        gpu_meta={
            "gpu_id": 0,
            "name": "NVIDIA RTX 4000 Blackwell",
            "vram_total_gb": 24.0,
            "vram_free_gb": 22.0,
            "vram_used_gb": 2.0,
        },
        driver_version="555.99",
    )
    # NvidiaSingle.transition_plan signature doesn't take the kwarg; calling
    # without it produces a plan with default warm_eviction_candidate=False.
    plan = arch.transition_plan(_step("a"), _step("b"))
    assert plan.warm_eviction_candidate is False


# ── Engine helper: _recently_evicted_models ─────────────────────────────


def _make_engine():
    """Build a WorkflowEngine with a no-op Ollama stub."""
    from api.services.workflow_engine import WorkflowEngine

    class _Stub:
        def chat(self, *a, **kw):
            return {"content": "", "prompt_eval_count": 0, "eval_count": 0}

        def health_check(self):
            return True

        def list_models(self):
            return []

    return WorkflowEngine(_Stub())


def test_engine_recently_evicted_picks_up_recent_steps():
    engine = _make_engine()
    now = datetime.utcnow()
    workflow_run = SimpleNamespace(
        step_results=[
            SimpleNamespace(
                model_used="model-a", completed_at=now - timedelta(seconds=30)
            ),
            SimpleNamespace(
                model_used="model-b", completed_at=now - timedelta(seconds=120)
            ),
        ]
    )
    evicted = engine._recently_evicted_models(workflow_run)
    assert "model-a" in evicted
    assert "model-b" in evicted


def test_engine_recently_evicted_excludes_old_steps():
    """Steps older than the recency window (300s default) are dropped."""
    engine = _make_engine()
    now = datetime.utcnow()
    workflow_run = SimpleNamespace(
        step_results=[
            SimpleNamespace(
                model_used="fresh", completed_at=now - timedelta(seconds=60)
            ),
            SimpleNamespace(
                model_used="stale", completed_at=now - timedelta(seconds=600)
            ),
        ]
    )
    evicted = engine._recently_evicted_models(workflow_run)
    assert "fresh" in evicted
    assert "stale" not in evicted


def test_engine_recently_evicted_handles_missing_data():
    """Steps with no completed_at or no model_used are skipped silently."""
    engine = _make_engine()
    workflow_run = SimpleNamespace(
        step_results=[
            SimpleNamespace(model_used=None, completed_at=datetime.utcnow()),
            SimpleNamespace(model_used="m", completed_at=None),
            SimpleNamespace(model_used="ok", completed_at=datetime.utcnow()),
        ]
    )
    evicted = engine._recently_evicted_models(workflow_run)
    assert evicted == ["ok"]


def test_engine_recently_evicted_window_configurable():
    """Operators can tighten the window to 30s for aggressive workloads."""
    engine = _make_engine()
    engine._page_cache_recency_seconds = 30.0
    now = datetime.utcnow()
    workflow_run = SimpleNamespace(
        step_results=[
            SimpleNamespace(
                model_used="just_in", completed_at=now - timedelta(seconds=10)
            ),
            SimpleNamespace(
                model_used="just_out", completed_at=now - timedelta(seconds=60)
            ),
        ]
    )
    evicted = engine._recently_evicted_models(workflow_run)
    assert evicted == ["just_in"]
