"""Phase 5.3 — GPU affinity hint on AgentStep + NvidiaMulti placement.

Covers:
  1. AgentStep.gpu_affinity schema acceptance: None, "any", "spread", int,
     "same_as:<id>". Invalid forms (negative int, unknown string, bool)
     fail validation.
  2. NvidiaMultiArchitecture.schedule_ready honors:
     - int → exact GPU placement (bound-checked)
     - "same_as:<id>" → co-locate with prior placement
     - None / "any" / "spread" → best-free
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.models.workflow_models import AgentStep, StepPrompt


# ── Schema validation ────────────────────────────────────────────────────


def _step(**kwargs):
    """Build a minimal AgentStep with gpu_affinity from kwargs."""
    return AgentStep(
        id=kwargs.pop("id", "s1"),
        name=kwargs.pop("name", "s"),
        prompt=StepPrompt(role_inline="r", task="t"),
        outputs=["out"],
        **kwargs,
    )


def test_affinity_none_accepted():
    s = _step(gpu_affinity=None)
    assert s.gpu_affinity is None


def test_affinity_any_accepted():
    assert _step(gpu_affinity="any").gpu_affinity == "any"


def test_affinity_spread_accepted():
    assert _step(gpu_affinity="spread").gpu_affinity == "spread"


def test_affinity_int_accepted():
    assert _step(gpu_affinity=0).gpu_affinity == 0
    assert _step(gpu_affinity=3).gpu_affinity == 3


def test_affinity_same_as_accepted():
    assert _step(gpu_affinity="same_as:step_a").gpu_affinity == "same_as:step_a"


def test_affinity_negative_int_rejected():
    with pytest.raises(Exception) as exc:
        _step(gpu_affinity=-1)
    assert "gpu_affinity" in str(exc.value)


def test_affinity_bool_rejected():
    """bool is a subclass of int — must be rejected explicitly."""
    with pytest.raises(Exception) as exc:
        _step(gpu_affinity=True)
    assert "gpu_affinity" in str(exc.value)


def test_affinity_unknown_string_rejected():
    with pytest.raises(Exception) as exc:
        _step(gpu_affinity="banana")
    assert "gpu_affinity" in str(exc.value)


def test_affinity_same_as_without_id_rejected():
    with pytest.raises(Exception) as exc:
        _step(gpu_affinity="same_as:")
    assert "gpu_affinity" in str(exc.value)


# ── NvidiaMulti placement resolution ─────────────────────────────────────


def _make_multi_arch(per_pool_free=None):
    """Build a NvidiaMultiArchitecture without going through detection."""
    from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

    arch = NvidiaMultiArchitecture(
        gpus=[
            {
                "gpu_id": 0,
                "name": "A100",
                "vram_total_gb": 80.0,
                "vram_free_gb": (per_pool_free or [40.0, 70.0])[0],
                "vram_used_gb": 80.0 - (per_pool_free or [40.0, 70.0])[0],
            },
            {
                "gpu_id": 1,
                "name": "A100",
                "vram_total_gb": 80.0,
                "vram_free_gb": (per_pool_free or [40.0, 70.0])[1],
                "vram_used_gb": 80.0 - (per_pool_free or [40.0, 70.0])[1],
            },
        ],
        nvlink_topology=[],
        driver_version="555.99",
    )
    # snapshot() reads from _nvml live — patch it to return the constructor
    # values without hitting the real driver.
    snap = SimpleNamespace(
        level="ok",
        per_pool=[
            {"pool_id": 0, "free_gb": (per_pool_free or [40.0, 70.0])[0], "used_gb": 0},
            {"pool_id": 1, "free_gb": (per_pool_free or [40.0, 70.0])[1], "used_gb": 0},
        ],
        timestamp=0.0,
    )
    arch.snapshot = lambda: snap  # type: ignore
    return arch


def test_no_affinity_picks_best_free():
    """Default behavior: head step lands on GPU with most free VRAM."""
    arch = _make_multi_arch(per_pool_free=[40.0, 70.0])
    decisions = arch.schedule_ready([_step(id="x")])
    assert decisions[0].placement == 1  # GPU 1 has more free VRAM


def test_int_affinity_pins_to_gpu():
    arch = _make_multi_arch(per_pool_free=[40.0, 70.0])
    decisions = arch.schedule_ready([_step(id="x", gpu_affinity=0)])
    assert decisions[0].placement == 0  # operator override


def test_int_affinity_out_of_range_falls_back():
    """gpu_affinity=5 on a 2-GPU host → best-free fallback."""
    arch = _make_multi_arch(per_pool_free=[40.0, 70.0])
    decisions = arch.schedule_ready([_step(id="x", gpu_affinity=5)])
    assert decisions[0].placement == 1  # fell back to best-free


def test_same_as_colocates_with_prior_step():
    """A step with gpu_affinity='same_as:earlier' lands on whichever GPU
    'earlier' got placed on, even if that wasn't the best-free."""
    arch = _make_multi_arch(per_pool_free=[40.0, 70.0])
    # Step 1: pinned to GPU 0
    arch.schedule_ready([_step(id="earlier", gpu_affinity=0)])
    # Step 2: co-locate with "earlier"
    decisions = arch.schedule_ready([_step(id="later", gpu_affinity="same_as:earlier")])
    assert decisions[0].placement == 0  # follows "earlier", not best-free


def test_same_as_unknown_target_falls_back_to_best_free():
    arch = _make_multi_arch(per_pool_free=[40.0, 70.0])
    # No prior placement for "ghost" — should fall back to best-free
    decisions = arch.schedule_ready([_step(id="x", gpu_affinity="same_as:ghost")])
    assert decisions[0].placement == 1


def test_any_and_spread_are_equivalent_to_none():
    arch = _make_multi_arch(per_pool_free=[40.0, 70.0])
    d_none = arch.schedule_ready([_step(id="a", gpu_affinity=None)])
    d_any = arch.schedule_ready([_step(id="b", gpu_affinity="any")])
    d_spread = arch.schedule_ready([_step(id="c", gpu_affinity="spread")])
    assert d_none[0].placement == d_any[0].placement == d_spread[0].placement


def test_rest_steps_defer_regardless_of_affinity():
    """Only the head step gets placement; subsequent steps defer even
    when they declare their own affinity. (Sequential dispatch policy.)"""
    arch = _make_multi_arch()
    decisions = arch.schedule_ready(
        [_step(id="head", gpu_affinity=0), _step(id="tail", gpu_affinity=1)]
    )
    assert decisions[0].placement == 0
    assert decisions[1].deferred is True
    assert decisions[1].placement is None
