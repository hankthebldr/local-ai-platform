#!/usr/bin/env python3
"""
Model fit service tests — api/services/model_fit.py (LB4-U1).

The pure load-fit scorer: budget from the detected Architecture's largest
per-pool figure (GPU classes) else the hardware profile's max_model_ram_gb;
required = size_gb × (1 + KV_HEADROOM_PCT); classes good ≤75% / tight ≤100%
/ no-fit (>100% or min_arch unmet — NVFP4 on cpu_x86 is the canonical
no-fit). Never raises: detection failure degrades to class "unknown".

Run:  pytest tests/test_model_fit.py -v
"""

import pytest

from api.services import model_fit
from api.services.co_scheduler import KV_HEADROOM_PCT

# ── Fixtures ───────────────────────────────────────────────────────────────


class _FakeArch:
    """Duck-typed Architecture stand-in for detect_budget tests."""

    def __init__(self, name, per_pool_gb, compute_capability=None):
        self.name = name  # plain string — getattr(name, "value", name) path
        self.per_pool_gb = per_pool_gb
        self.gpus = (
            [{"compute_capability": compute_capability}]
            if compute_capability is not None
            else []
        )


def _fit(model, budget=80.0, arch="cpu_x86", cc=None):
    return model_fit.compute_fit(
        model,
        budget_gb=budget,
        basis="profile:max_model_ram_gb",
        arch_name=arch,
        compute_capability=cc,
    )


# ── Class thresholds ───────────────────────────────────────────────────────


def test_good_when_under_75_pct():
    # 40 GB × 1.15 = 46 GB required on an 80 GB budget → 57.5% → good.
    fit = _fit({"size_gb": 40.0})
    assert fit["class"] == "good"
    assert fit["required_gb"] == pytest.approx(40.0 * (1 + KV_HEADROOM_PCT))
    assert fit["budget_gb"] == 80.0
    assert fit["score"] == pytest.approx(57.5)


def test_good_boundary_exactly_75_pct():
    # required == 60 GB on 80 GB budget → exactly 75% → still good.
    size = 60.0 / (1 + KV_HEADROOM_PCT)
    fit = _fit({"size_gb": size})
    assert fit["class"] == "good"
    assert fit["score"] == pytest.approx(75.0)


def test_tight_between_75_and_100_pct():
    # 60 GB × 1.15 = 69 GB on 80 GB → 86.25% → tight.
    fit = _fit({"size_gb": 60.0})
    assert fit["class"] == "tight"


def test_tight_boundary_exactly_100_pct():
    size = 80.0 / (1 + KV_HEADROOM_PCT)
    fit = _fit({"size_gb": size})
    assert fit["class"] == "tight"
    assert fit["score"] == pytest.approx(100.0)


def test_no_fit_over_budget():
    fit = _fit({"size_gb": 75.0})  # 86.25 GB required on 80 GB budget
    assert fit["class"] == "no-fit"
    assert fit["score"] > 100


def test_size_parsed_from_size_string_when_size_gb_absent():
    fit = _fit({"size": "22GB"})
    assert fit["required_gb"] == pytest.approx(22.0 * (1 + KV_HEADROOM_PCT))
    assert fit["class"] == "good"


# ── min_arch / min_compute_capability ──────────────────────────────────────


def test_nvfp4_on_cpu_x86_is_no_fit():
    """The canonical case: NVFP4 weights require Blackwell-class NVIDIA —
    a hard no-fit on a CPU-only host, regardless of RAM headroom."""
    nvfp4 = {
        "size_gb": 6.0,  # would trivially fit 80 GB of RAM
        "min_arch": "gpu_nvidia_single",
        "min_compute_capability": "10.0",
    }
    fit = _fit(nvfp4, budget=80.0, arch="cpu_x86")
    assert fit["class"] == "no-fit"


def test_min_arch_satisfied_by_gpu_single():
    nvfp4 = {"size_gb": 6.0, "min_arch": "gpu_nvidia_single"}
    fit = _fit(nvfp4, budget=24.0, arch="gpu_nvidia_single")
    assert fit["class"] == "good"


def test_min_arch_single_satisfied_by_multi():
    """More GPUs is never worse — a single-GPU requirement passes on multi."""
    fit = _fit(
        {"size_gb": 6.0, "min_arch": "gpu_nvidia_single"},
        budget=24.0,
        arch="gpu_nvidia_multi",
    )
    assert fit["class"] == "good"


def test_min_arch_unmet_on_unknown_host():
    """An unknown host cannot satisfy a stated requirement — honest no-fit."""
    fit = _fit(
        {"size_gb": 6.0, "min_arch": "gpu_nvidia_single"},
        budget=80.0,
        arch="unknown",
    )
    assert fit["class"] == "no-fit"


def test_min_compute_capability_below_requirement_is_no_fit():
    nvfp4 = {
        "size_gb": 6.0,
        "min_arch": "gpu_nvidia_single",
        "min_compute_capability": "10.0",
    }
    fit = _fit(nvfp4, budget=24.0, arch="gpu_nvidia_single", cc="8.9")
    assert fit["class"] == "no-fit"


def test_min_compute_capability_met():
    nvfp4 = {
        "size_gb": 6.0,
        "min_arch": "gpu_nvidia_single",
        "min_compute_capability": "10.0",
    }
    fit = _fit(nvfp4, budget=24.0, arch="gpu_nvidia_single", cc="12.0")
    assert fit["class"] == "good"


def test_unknown_compute_capability_does_not_fail_the_check():
    """Fit is a hint: an nvidia host with an unprobeable CC passes — the
    min_arch gate already handled the hard cases."""
    nvfp4 = {
        "size_gb": 6.0,
        "min_arch": "gpu_nvidia_single",
        "min_compute_capability": "10.0",
    }
    fit = _fit(nvfp4, budget=24.0, arch="gpu_nvidia_single", cc=None)
    assert fit["class"] == "good"


# ── detect_budget basis ────────────────────────────────────────────────────


def test_budget_from_largest_gpu_pool(monkeypatch):
    arch = _FakeArch("gpu_nvidia_multi", [16.0, 24.0], compute_capability="12.0")
    monkeypatch.setattr(model_fit, "_current_arch", lambda: arch)
    budget, basis, arch_name, cc = model_fit.detect_budget()
    assert budget == 24.0
    assert basis == "arch:per_pool_gb"
    assert arch_name == "gpu_nvidia_multi"
    assert cc == "12.0"


def test_budget_from_profile_on_cpu_class(monkeypatch):
    arch = _FakeArch("cpu_x86", [96.0])
    monkeypatch.setattr(model_fit, "_current_arch", lambda: arch)
    from api.services import hardware_profile

    monkeypatch.setattr(
        hardware_profile, "detect_hardware", lambda: {"max_model_ram_gb": 50}
    )
    budget, basis, arch_name, _cc = model_fit.detect_budget()
    assert budget == 50.0
    assert basis == "profile:max_model_ram_gb"
    assert arch_name == "cpu_x86"


# ── Never raises ───────────────────────────────────────────────────────────


def test_never_raises_on_total_detection_failure(monkeypatch):
    def _boom():
        raise RuntimeError("no architecture, no profile")

    monkeypatch.setattr(model_fit, "_current_arch", lambda: None)
    from api.services import hardware_profile

    monkeypatch.setattr(hardware_profile, "detect_hardware", _boom)
    fit = model_fit.compute_fit({"size_gb": 8.0})
    assert fit["class"] == "unknown"
    assert fit["score"] is None
    assert fit["basis"] == "unknown"


def test_never_raises_on_garbage_model():
    fit = _fit({"size": "not-a-size", "size_gb": None, "min_arch": 42})
    assert fit["class"] in ("good", "tight", "no-fit", "unknown")


def test_zero_budget_is_unknown_not_crash():
    fit = _fit({"size_gb": 8.0}, budget=0.0)
    assert fit["class"] == "unknown"
    assert fit["score"] is None


# ── Fit-class multipliers (recommendations contract) ───────────────────────


def test_fit_class_multipliers_cover_all_classes():
    assert model_fit.FIT_CLASS_MULTIPLIER["good"] == 1.0
    assert model_fit.FIT_CLASS_MULTIPLIER["no-fit"] == 0.0
    assert 0 < model_fit.FIT_CLASS_MULTIPLIER["tight"] < 1
    assert 0 < model_fit.FIT_CLASS_MULTIPLIER["unknown"] <= 1
