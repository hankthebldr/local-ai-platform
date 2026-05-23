"""Tests for the per-arch × per-deployment config validator (Phase 6.1)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from api.services.architecture import ArchClass
from api.services.config_validator import (
    Recommendation,
    _matches,
    probe_daemon_env,
    validate_config,
    validate_config_or_exit,
)
from api.services.deployment import DeploymentMode


# ── _matches helper ──────────────────────────────────────────────────────


def test_matches_exact_value():
    assert _matches("1", "1")
    assert not _matches("1", "2")


def test_matches_wildcard():
    assert _matches("*", "anything")
    assert _matches("*", "0")
    assert not _matches("*", "")


def test_matches_physical_core_count():
    assert _matches("physical-core-count", "8")
    assert _matches("physical-core-count", "32")
    assert not _matches("physical-core-count", "not-a-number")
    assert not _matches("physical-core-count", "0")  # >0 required


def test_matches_enumerate():
    assert _matches("enumerate", "0")
    assert _matches("enumerate", "0,1,2")
    assert not _matches("enumerate", "a,b,c")


def test_matches_range():
    assert _matches("1-2", "1")
    assert _matches("1-2", "2")
    assert not _matches("1-2", "3")
    assert not _matches("1-2", "0")


# ── Apple DMG: clean baseline ────────────────────────────────────────────


def test_validator_dmg_apple_unified_clean():
    """All recommended env vars set correctly → no warnings, no errors."""
    daemon_env = {
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_MAX_LOADED_MODELS": "3",
        "OLLAMA_NUM_PARALLEL": "1",
    }
    result = validate_config(
        ArchClass.APPLE_UNIFIED, DeploymentMode.DMG_NATIVE, daemon_env
    )
    assert result.is_clean, f"expected clean, got: {result.warnings + result.errors}"


def test_validator_dmg_apple_missing_recommended_warns():
    """Empty daemon env → warnings (not errors) for the unset values."""
    result = validate_config(ArchClass.APPLE_UNIFIED, DeploymentMode.DMG_NATIVE, {})
    assert not result.errors  # no required-error keys for Apple DMG
    keys = {w["key"] for w in result.warnings}
    assert "OLLAMA_HOST" in keys
    assert "OLLAMA_MAX_LOADED_MODELS" in keys


# ── arch_env_mismatch: CUDA on Mac ───────────────────────────────────────


def test_validator_cuda_visible_on_dmg_mismatch():
    """DMG should never have CUDA_VISIBLE_DEVICES set."""
    daemon_env = {
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_MAX_LOADED_MODELS": "3",
        "OLLAMA_NUM_PARALLEL": "1",
        "CUDA_VISIBLE_DEVICES": "0",
    }
    result = validate_config(
        ArchClass.APPLE_UNIFIED, DeploymentMode.DMG_NATIVE, daemon_env
    )
    assert any(w.get("code") == "arch_env_mismatch" for w in result.warnings)


def test_validator_nvidia_visible_on_dmg_mismatch():
    daemon_env = {"NVIDIA_VISIBLE_DEVICES": "all"}
    result = validate_config(
        ArchClass.APPLE_UNIFIED, DeploymentMode.DMG_NATIVE, daemon_env
    )
    assert any(
        w.get("key") == "NVIDIA_VISIBLE_DEVICES"
        and w.get("code") == "arch_env_mismatch"
        for w in result.warnings
    )


# ── NVIDIA multi-GPU: missing SCHED_SPREAD is an error ──────────────────


def test_validator_nvidia_multi_missing_sched_spread_is_error():
    """OLLAMA_SCHED_SPREAD unset on multi-GPU → error, not warning."""
    with patch(
        "api.services.config_validator._gpu_passthrough_works", return_value=True
    ):
        result = validate_config(
            ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.HOST_NATIVE, {}
        )
    assert any(e.get("code") == "missing_sched_spread" for e in result.errors)


def test_validator_nvidia_multi_with_sched_spread_no_error():
    daemon_env = {
        "OLLAMA_SCHED_SPREAD": "1",
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_MAX_LOADED_MODELS": "3",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_FLASH_ATTENTION": "1",
    }
    result = validate_config(
        ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.HOST_NATIVE, daemon_env
    )
    assert not result.errors
    assert result.is_clean


# ── CPU container: num_thread warning ────────────────────────────────────


def test_validator_container_cpu_warns_no_num_thread():
    """CPU-only container without OLLAMA_NUM_THREAD → warning."""
    result = validate_config(ArchClass.CPU_X86, DeploymentMode.CONTAINER, {})
    assert any(w.get("code") == "missing_num_thread" for w in result.warnings)


# ── Container + NVIDIA: GPU passthrough cross-check ──────────────────────


def test_validator_container_nvidia_passthrough_failure_is_error():
    """Container × NVIDIA arch but nvidia-smi unreachable → error."""
    daemon_env = {
        "OLLAMA_HOST": "http://ollama:11434",
        "OLLAMA_MAX_LOADED_MODELS": "2",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_FLASH_ATTENTION": "1",
    }
    with patch(
        "api.services.config_validator._gpu_passthrough_works", return_value=False
    ):
        result = validate_config(
            ArchClass.GPU_NVIDIA_SINGLE, DeploymentMode.CONTAINER, daemon_env
        )
    assert any(e.get("code") == "gpu_passthrough_misconfigured" for e in result.errors)


def test_validator_container_nvidia_passthrough_ok():
    """Same setup but nvidia-smi works → no passthrough error."""
    daemon_env = {
        "OLLAMA_HOST": "http://ollama:11434",
        "OLLAMA_MAX_LOADED_MODELS": "2",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_FLASH_ATTENTION": "1",
    }
    with patch(
        "api.services.config_validator._gpu_passthrough_works", return_value=True
    ):
        result = validate_config(
            ArchClass.GPU_NVIDIA_SINGLE, DeploymentMode.CONTAINER, daemon_env
        )
    assert not any(
        e.get("code") == "gpu_passthrough_misconfigured" for e in result.errors
    )


# ── Docker-on-Mac quirk ──────────────────────────────────────────────────


def test_validator_container_on_mac_logs_vm_warning():
    """Container deployment on macOS → docker_desktop_mac_vm warning."""
    with patch("api.services.config_validator.sys.platform", "darwin"), patch(
        "api.services.config_validator._gpu_passthrough_works", return_value=True
    ):
        result = validate_config(
            ArchClass.CPU_X86, DeploymentMode.CONTAINER, {"OLLAMA_NUM_THREAD": "8"}
        )
    assert any(w.get("code") == "docker_desktop_mac_vm" for w in result.warnings)


# ── Strict mode SystemExit ───────────────────────────────────────────────


def test_validator_strict_mode_exits_on_error():
    """STRICT_CONFIG_VALIDATION=true + any error → SystemExit(1)."""
    with patch.dict(os.environ, {"STRICT_CONFIG_VALIDATION": "true"}), patch(
        "api.services.config_validator._gpu_passthrough_works", return_value=True
    ):
        with pytest.raises(SystemExit) as exc:
            validate_config_or_exit(
                ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.HOST_NATIVE, {}
            )
        assert exc.value.code == 1


def test_validator_strict_mode_no_exit_when_clean():
    daemon_env = {
        "OLLAMA_SCHED_SPREAD": "1",
        "OLLAMA_HOST": "127.0.0.1:11434",
        "OLLAMA_MAX_LOADED_MODELS": "3",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_FLASH_ATTENTION": "1",
    }
    with patch.dict(os.environ, {"STRICT_CONFIG_VALIDATION": "true"}):
        result = validate_config_or_exit(
            ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.HOST_NATIVE, daemon_env
        )
    assert result.is_clean


def test_validator_non_strict_warnings_dont_exit():
    """Errors logged but no SystemExit when STRICT_CONFIG_VALIDATION not set."""
    with patch.dict(os.environ, {}, clear=False), patch(
        "api.services.config_validator._gpu_passthrough_works", return_value=True
    ):
        # ensure unset
        os.environ.pop("STRICT_CONFIG_VALIDATION", None)
        result = validate_config_or_exit(
            ArchClass.GPU_NVIDIA_MULTI, DeploymentMode.HOST_NATIVE, {}
        )
    assert result.errors  # errors exist
    # but no SystemExit raised


# ── Unknown arch ─────────────────────────────────────────────────────────


def test_validator_unknown_arch_passes_clean():
    """Unknown arch has no recommendations → any env passes."""
    result = validate_config(
        ArchClass.UNKNOWN, DeploymentMode.HOST_NATIVE, {"WHATEVER": "anything"}
    )
    assert result.is_clean


# ── probe_daemon_env ─────────────────────────────────────────────────────


def test_probe_daemon_env_reads_known_keys_from_environ():
    """When no OllamaService.get_daemon_env, falls back to os.environ
    filtered to known keys."""
    with patch.dict(
        os.environ,
        {
            "OLLAMA_KEEP_ALIVE": "5m",
            "OLLAMA_NUM_PARALLEL": "2",
            "UNRELATED_VAR": "ignored",
        },
        clear=False,
    ):
        env = probe_daemon_env()
    assert env.get("OLLAMA_KEEP_ALIVE") == "5m"
    assert env.get("OLLAMA_NUM_PARALLEL") == "2"
    assert "UNRELATED_VAR" not in env


def test_probe_daemon_env_empty_when_no_known_vars():
    with patch.dict(os.environ, {}, clear=True):
        env = probe_daemon_env()
    assert env == {}


# ── Recommendation dataclass ─────────────────────────────────────────────


def test_recommendation_code_defaults_to_severity_key():
    r = Recommendation(key="FOO", expected="bar")
    assert r.code == "warn_foo"


def test_recommendation_explicit_code_preserved():
    r = Recommendation(key="FOO", expected="bar", code="custom_code")
    assert r.code == "custom_code"
