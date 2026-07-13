#!/usr/bin/env python3
"""
Model fit scoring — pure service (LB4-U1).

Answers one question per catalog entry: does this model's weight file fit
the detected HARDWARE PROFILE's memory budget, with KV-cache headroom?

    budget   = largest per_pool_gb from the detected Architecture (GPU
               classes — VRAM is the binding pool), else
               hardware_profile.detect_hardware()["max_model_ram_gb"]
    required = size_gb × (1 + KV_HEADROOM_PCT)   (co_scheduler's constant)
    class    = good  (required ≤ 75% of budget)
               tight (≤ 100%)
               no-fit (> 100%, or min_arch / min_compute_capability unmet —
                       NVFP4 on cpu_x86 is the canonical no-fit)
               unknown (budget indeterminable — detection failed)

This is a *load-fit* hint for the Library UI, not a runtime guarantee — the
engine's co_scheduler stays the authority at dispatch time. Never raises.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .co_scheduler import KV_HEADROOM_PCT

# Thresholds (fraction of budget).
GOOD_MAX = 0.75
TIGHT_MAX = 1.00

# score multiplier per fit class — used by the recommendations ranking
# (role_fit × fit-class). `unknown` degrades gently rather than zeroing.
FIT_CLASS_MULTIPLIER = {
    "good": 1.0,
    "tight": 0.6,
    "no-fit": 0.0,
    "unknown": 0.8,
}

_GPU_ARCH_NAMES = ("gpu_nvidia_single", "gpu_nvidia_multi")


def _current_arch():
    """The installed Architecture singleton, or a fresh detection, or None.
    Never raises — detection failure degrades to the profile budget."""
    try:
        from .architecture import Architecture, detect_architecture

        try:
            return Architecture.current()
        except Exception:
            return detect_architecture()
    except Exception:
        return None


def detect_budget() -> Tuple[float, str, str, Optional[str]]:
    """(budget_gb, basis, arch_name, compute_capability) for this host.

    GPU classes budget against the largest VRAM pool; unified/CPU classes
    budget against the hardware profile's max_model_ram_gb. Never raises —
    total failure yields (0.0, "unknown", "unknown", None).
    """
    arch = _current_arch()
    arch_name = "unknown"
    compute_capability: Optional[str] = None
    if arch is not None:
        try:
            arch_name = str(getattr(arch.name, "value", arch.name))
            gpus = getattr(arch, "gpus", None) or []
            if gpus and isinstance(gpus[0], dict):
                compute_capability = gpus[0].get("compute_capability")
            if arch_name in _GPU_ARCH_NAMES:
                pools = [float(p) for p in (arch.per_pool_gb or []) if p]
                if pools:
                    return max(pools), "arch:per_pool_gb", arch_name, compute_capability
        except Exception:
            pass
    try:
        from .hardware_profile import detect_hardware

        budget = float(detect_hardware().get("max_model_ram_gb") or 0)
        if budget > 0:
            return budget, "profile:max_model_ram_gb", arch_name, compute_capability
    except Exception:
        pass
    return 0.0, "unknown", arch_name, compute_capability


def _size_gb(model: Dict[str, Any]) -> float:
    """Model weight size in GB from a registry/catalog entry. 0 on failure."""
    raw = model.get("size_gb")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    size_str = str(model.get("size", "") or "")
    try:
        return float(size_str.lower().replace("gb", "").strip() or 0)
    except ValueError:
        return 0.0


def _min_arch_satisfied(min_arch: str, arch_name: str) -> bool:
    """Does the host architecture class satisfy a model's min_arch?

    A generic "gpu_nvidia" requirement is met by either NVIDIA class; a
    "gpu_nvidia_single" requirement is met by single OR multi (more GPUs is
    never worse). Anything else is exact-match. An unknown host cannot
    satisfy a stated requirement — honest no-fit beats a false green.
    """
    if not min_arch or min_arch == "any":
        return True
    if min_arch in ("gpu_nvidia", "gpu_nvidia_single"):
        return arch_name in _GPU_ARCH_NAMES
    return arch_name == min_arch


def _cc_satisfied(min_cc: Any, compute_capability: Optional[str]) -> bool:
    """Compare a model's min_compute_capability against the detected GPU's.
    Unknown host capability does NOT fail the check — fit is a hint and the
    min_arch gate already handled the hard cases."""
    if min_cc in (None, ""):
        return True
    if not compute_capability:
        return True
    try:
        return float(compute_capability) >= float(min_cc)
    except (TypeError, ValueError):
        return True


def compute_fit(
    model: Dict[str, Any],
    budget_gb: Optional[float] = None,
    basis: Optional[str] = None,
    arch_name: Optional[str] = None,
    compute_capability: Optional[str] = None,
) -> Dict[str, Any]:
    """Fit descriptor for one model: {score, class, budget_gb, required_gb, basis}.

    ``score`` is budget utilization in percent (required/budget × 100) —
    the fit dot's number. Callers batching a catalog pass detect_budget()
    once and thread it through; standalone calls detect lazily. Never raises.
    """
    try:
        if budget_gb is None or basis is None:
            budget_gb, basis, det_arch, det_cc = detect_budget()
            arch_name = arch_name if arch_name is not None else det_arch
            if compute_capability is None:
                compute_capability = det_cc
        arch_name = arch_name or "unknown"

        required = round(_size_gb(model) * (1 + KV_HEADROOM_PCT), 2)
        budget = round(float(budget_gb or 0), 2)

        min_arch = model.get("min_arch")
        arch_ok = _min_arch_satisfied(min_arch, arch_name) and _cc_satisfied(
            model.get("min_compute_capability"), compute_capability
        )

        if not arch_ok:
            fit_class = "no-fit"
            score = round(required / budget * 100, 1) if budget > 0 else None
        elif budget <= 0 or required <= 0:
            fit_class = "unknown"
            score = None
        else:
            ratio = required / budget
            score = round(ratio * 100, 1)
            if ratio <= GOOD_MAX:
                fit_class = "good"
            elif ratio <= TIGHT_MAX:
                fit_class = "tight"
            else:
                fit_class = "no-fit"

        return {
            "score": score,
            "class": fit_class,
            "budget_gb": budget,
            "required_gb": required,
            "basis": basis or "unknown",
        }
    except Exception:
        # Absolute floor: a fit hint must never take the catalog down.
        return {
            "score": None,
            "class": "unknown",
            "budget_gb": 0,
            "required_gb": 0,
            "basis": "unknown",
        }
