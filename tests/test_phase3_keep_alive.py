"""Phase 3 — Per-step keep_alive resolution + arch-detected defaults.

Covers:
  1. Per-arch default_keep_alive() returns expected policy
  2. _resolve_keep_alive() priority: step > defaults > arch > env
  3. StepConfig + WorkflowDefaults accept the new keep_alive field
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.models.workflow_models import (
    AgentStep,
    StepConfig,
    StepPrompt,
    WorkflowDefaults,
)
from api.services import architecture as arch_mod
from api.services.step_executor import _resolve_keep_alive


# ── Architecture defaults ────────────────────────────────────────────────


def test_unified_default_keep_alive():
    """Apple Silicon + x86 CPU: keep models warm — reload cost dominates."""
    from api.services.arch_impl.unified import UnifiedArchitecture
    from api.services.architecture import ArchClass

    arch = UnifiedArchitecture(
        arch_class=ArchClass.APPLE_UNIFIED,
        total_memory_gb=48.0,
        bandwidth_gbps=400.0,
    )
    assert arch.default_keep_alive() == "30m"

    # Same default on Linux x86 CPU — both subcases of unified.
    cpu_arch = UnifiedArchitecture(
        arch_class=ArchClass.CPU_X86,
        total_memory_gb=64.0,
        bandwidth_gbps=80.0,
    )
    assert cpu_arch.default_keep_alive() == "30m"


def test_nvidia_single_default_keep_alive():
    """Single NVIDIA GPU: evict by default — VRAM is scarce."""
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
    assert arch.default_keep_alive() == "0"


def test_nvidia_multi_default_keep_alive():
    """Multi-GPU shares single-GPU eviction default."""
    from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

    arch = NvidiaMultiArchitecture(
        gpus=[
            {
                "gpu_id": 0,
                "name": "A100",
                "vram_total_gb": 80.0,
                "vram_free_gb": 75.0,
                "vram_used_gb": 5.0,
            },
            {
                "gpu_id": 1,
                "name": "A100",
                "vram_total_gb": 80.0,
                "vram_free_gb": 78.0,
                "vram_used_gb": 2.0,
            },
        ],
        nvlink_topology=[],
        driver_version="555.99",
    )
    assert arch.default_keep_alive() == "0"


def test_unknown_default_keep_alive():
    """Unknown arch: defer to a conservative middle ground."""
    arch = arch_mod.UnknownArchitecture()
    assert arch.default_keep_alive() == "5m"


# ── _resolve_keep_alive priority ─────────────────────────────────────────


def _step_with(keep_alive):
    """Build a minimal step-like object with the given keep_alive on config."""
    return SimpleNamespace(
        id="s1",
        config=SimpleNamespace(keep_alive=keep_alive),
    )


def _defaults_with(keep_alive):
    return SimpleNamespace(keep_alive=keep_alive)


class _MockArch:
    def default_keep_alive(self):
        return "30m"  # unified-style default


def test_resolve_step_overrides_everything():
    """Step-level keep_alive wins over defaults, arch, env."""
    arch_mod._set_current(_MockArch())
    try:
        result = _resolve_keep_alive(
            _step_with("-1"),  # explicit step override
            _defaults_with("10m"),  # workflow default
        )
        assert result == "-1"
    finally:
        arch_mod._current_architecture = None


def test_resolve_defaults_when_step_missing():
    """Workflow defaults win when step has no override."""
    arch_mod._set_current(_MockArch())
    try:
        result = _resolve_keep_alive(
            _step_with(None),
            _defaults_with("15m"),
        )
        assert result == "15m"
    finally:
        arch_mod._current_architecture = None


def test_resolve_arch_default_when_no_yaml_setting():
    """Arch-detected default wins when neither step nor defaults specify."""
    arch_mod._set_current(_MockArch())
    try:
        result = _resolve_keep_alive(
            _step_with(None),
            _defaults_with(None),
        )
        assert result == "30m"  # from _MockArch
    finally:
        arch_mod._current_architecture = None


def test_resolve_env_fallback_when_arch_uninitialised():
    """When architecture singleton isn't set, fall through to env.

    `OLLAMA_KEEP_ALIVE` is imported into step_executor at module load,
    so the patch has to target the symbol at its use site (step_executor),
    not the source module (ollama_service).
    """
    arch_mod._current_architecture = None  # ensure unset
    from api.services import step_executor

    with patch.object(step_executor, "OLLAMA_KEEP_ALIVE", "7m"):
        result = _resolve_keep_alive(
            _step_with(None),
            _defaults_with(None),
        )
        assert result == "7m"


def test_resolve_empty_string_step_value_is_respected():
    """'0' is a valid Ollama keep_alive (immediate evict) and must not be
    confused with 'unset'. The resolver checks for None explicitly."""
    arch_mod._set_current(_MockArch())
    try:
        result = _resolve_keep_alive(
            _step_with("0"),  # explicit "evict immediately"
            _defaults_with("30m"),  # would otherwise win
        )
        assert result == "0"
    finally:
        arch_mod._current_architecture = None


# ── Schema acceptance ────────────────────────────────────────────────────


def test_step_config_accepts_keep_alive():
    """StepConfig.keep_alive accepts any string Ollama supports."""
    for val in ("0", "30m", "1h", "-1", "300", None):
        cfg = StepConfig(keep_alive=val)
        assert cfg.keep_alive == val


def test_workflow_defaults_accepts_keep_alive():
    """WorkflowDefaults.keep_alive defaults to None (arch-detected)."""
    defaults = WorkflowDefaults()
    assert defaults.keep_alive is None

    defaults = WorkflowDefaults(keep_alive="-1")
    assert defaults.keep_alive == "-1"


def test_agent_step_yaml_keep_alive_round_trip():
    """A workflow YAML that sets keep_alive on a step round-trips through
    AgentStep validation."""
    step = AgentStep(
        id="s1",
        name="Test Step",
        prompt=StepPrompt(role_inline="tester", task="do a thing"),
        outputs=["out1"],
        config=StepConfig(keep_alive="0"),
    )
    payload = step.model_dump()
    rehydrated = AgentStep.model_validate(payload)
    assert rehydrated.config.keep_alive == "0"
