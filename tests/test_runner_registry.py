"""Tests for RunnerRegistry + non-breaking ModelResolver extension.

Phase 1 / Task 1.3 of gpu-runner-abstraction.

The registry holds the active Runner instances (Ollama + optionally vLLM).
The ModelResolver gains `resolve_with_runner()` — additive, returns
(Runner, model_name). Existing `resolve()` keeps returning str so the
8 existing call sites need no migration in Phase 1.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.services.runner import RunnerKind
from api.services.runner_registry import (
    RunnerRegistry,
    RunnerNotConfigured,
    runner_for_registry_entry,
)


# ── Helpers ───────────────────────────────────────────────────────────────


def _mock_runner(kind: RunnerKind):
    r = MagicMock()
    r.name = kind
    return r


# ── Registry shape ────────────────────────────────────────────────────────


class TestRegistryBasics:
    def test_empty_registry_has_no_runners(self):
        reg = RunnerRegistry()
        assert reg.kinds() == set()

    def test_register_and_get(self):
        reg = RunnerRegistry()
        ollama = _mock_runner(RunnerKind.OLLAMA)
        reg.register(ollama)
        assert reg.get(RunnerKind.OLLAMA) is ollama

    def test_register_two_runners(self):
        reg = RunnerRegistry()
        ollama = _mock_runner(RunnerKind.OLLAMA)
        vllm = _mock_runner(RunnerKind.VLLM)
        reg.register(ollama)
        reg.register(vllm)
        assert reg.kinds() == {RunnerKind.OLLAMA, RunnerKind.VLLM}

    def test_get_unknown_raises_runner_not_configured(self):
        reg = RunnerRegistry()
        with pytest.raises(RunnerNotConfigured) as ei:
            reg.get(RunnerKind.VLLM)
        # Error message should name the missing runner so debugging is fast.
        assert "vllm" in str(ei.value).lower()

    def test_re_register_replaces(self):
        # Re-registering the same kind overwrites — supports test reset
        # and live runner-swap in dev.
        reg = RunnerRegistry()
        first = _mock_runner(RunnerKind.OLLAMA)
        second = _mock_runner(RunnerKind.OLLAMA)
        reg.register(first)
        reg.register(second)
        assert reg.get(RunnerKind.OLLAMA) is second


# ── for_model_id dispatch ─────────────────────────────────────────────────


class TestForModelId:
    def test_default_when_entry_has_no_runner_field(self):
        # Backwards compat: every existing MODEL_REGISTRY entry implicitly
        # has runner="ollama". Pre-existing 18-entry catalog stays unchanged.
        reg = RunnerRegistry()
        ollama = _mock_runner(RunnerKind.OLLAMA)
        reg.register(ollama)

        entry = {
            "name": "Dolphin 3",
            "ollama": "dolphin3",
            "size": "4.9GB",
            # NO 'runner' field — should default to OLLAMA
        }
        assert reg.for_entry(entry) is ollama

    def test_explicit_runner_vllm(self):
        reg = RunnerRegistry()
        ollama = _mock_runner(RunnerKind.OLLAMA)
        vllm = _mock_runner(RunnerKind.VLLM)
        reg.register(ollama)
        reg.register(vllm)

        entry = {
            "name": "Qwen3-Coder-30B-A3B NVFP4",
            "hf_repo": "nvidia/Qwen3-Coder-30B-A3B-NVFP4",
            "runner": "vllm",
            "quant": "nvfp4",
        }
        assert reg.for_entry(entry) is vllm

    def test_unknown_runner_string_raises(self):
        reg = RunnerRegistry()
        reg.register(_mock_runner(RunnerKind.OLLAMA))
        entry = {"runner": "rocketship"}
        with pytest.raises(ValueError, match="rocketship"):
            reg.for_entry(entry)

    def test_known_runner_but_not_registered_raises(self):
        # vllm in the entry, but no vLLM runner registered on this host.
        # The right behavior is RunnerNotConfigured — clear signal that
        # the model can't be served here.
        reg = RunnerRegistry()
        reg.register(_mock_runner(RunnerKind.OLLAMA))
        entry = {"runner": "vllm"}
        with pytest.raises(RunnerNotConfigured):
            reg.for_entry(entry)


# ── runner_for_registry_entry helper ──────────────────────────────────────


class TestEntryHelper:
    def test_default_ollama_when_missing(self):
        assert runner_for_registry_entry({}) == RunnerKind.OLLAMA

    def test_explicit_ollama(self):
        assert runner_for_registry_entry({"runner": "ollama"}) == RunnerKind.OLLAMA

    def test_explicit_vllm(self):
        assert runner_for_registry_entry({"runner": "vllm"}) == RunnerKind.VLLM

    def test_case_insensitive(self):
        assert runner_for_registry_entry({"runner": "VLLM"}) == RunnerKind.VLLM

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            runner_for_registry_entry({"runner": "tensorrt"})


# ── ModelResolver.resolve_with_runner (non-breaking extension) ───────────


class TestResolveWithRunner:
    def test_returns_runner_and_model_tuple(self):
        from api.services.model_resolver import ModelResolver

        ollama_svc = MagicMock()
        ollama_svc.list_models.return_value = [
            {"name": "dolphin3", "size": 4_900_000_000},
        ]
        resolver = ModelResolver(ollama_service=ollama_svc)

        reg = RunnerRegistry()
        ollama_runner = _mock_runner(RunnerKind.OLLAMA)
        reg.register(ollama_runner)
        resolver.attach_runner_registry(reg)

        runner, model_name = resolver.resolve_with_runner(model="dolphin3")
        assert runner is ollama_runner
        assert model_name == "dolphin3"

    def test_resolve_str_signature_unchanged(self):
        # Backwards compat — existing callers must keep getting back a str.
        from api.services.model_resolver import ModelResolver

        ollama_svc = MagicMock()
        ollama_svc.list_models.return_value = [
            {"name": "dolphin3", "size": 4_900_000_000},
        ]
        resolver = ModelResolver(ollama_service=ollama_svc)
        result = resolver.resolve(model="dolphin3")
        assert isinstance(result, str)
        assert result == "dolphin3"

    def test_resolve_with_runner_uses_registry_dispatch(self):
        # When the model is known in MODEL_REGISTRY with runner=vllm,
        # resolve_with_runner should return the vLLM runner.
        from api.services.model_resolver import ModelResolver

        ollama_svc = MagicMock()
        # Ollama lists nothing relevant — the vLLM-served model
        # isn't in /api/tags, naturally.
        ollama_svc.list_models.return_value = []
        resolver = ModelResolver(ollama_service=ollama_svc)

        reg = RunnerRegistry()
        reg.register(_mock_runner(RunnerKind.OLLAMA))
        vllm_runner = _mock_runner(RunnerKind.VLLM)
        reg.register(vllm_runner)
        resolver.attach_runner_registry(reg)

        # Stub the model_registry probe so the test doesn't depend on
        # whatever's currently in models/download.py.
        resolver.attach_model_registry(
            {"qwen3-coder-30b-a3b-nvfp4": {"runner": "vllm"}}
        )

        runner, model_name = resolver.resolve_with_runner(
            model="qwen3-coder-30b-a3b-nvfp4"
        )
        assert runner is vllm_runner
        assert model_name == "qwen3-coder-30b-a3b-nvfp4"

    def test_resolve_with_runner_without_registry_raises(self):
        # If a caller tries resolve_with_runner before attach_runner_registry,
        # surface a clear programmer error.
        from api.services.model_resolver import ModelResolver

        resolver = ModelResolver(ollama_service=MagicMock())
        with pytest.raises(RuntimeError, match="attach_runner_registry"):
            resolver.resolve_with_runner(model="anything")
