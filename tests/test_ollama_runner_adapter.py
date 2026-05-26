"""Tests for the OllamaRunner adapter.

Phase 1 / Task 1.2 of gpu-runner-abstraction.

The adapter wraps the existing OllamaService and exposes the Runner
protocol surface. No behavior change in OllamaService itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.services.runner import (
    RunnerKind,
    Quant,
    GenerateRequest,
    GenerateResponse,
    UnloadResult,
    LoadResult,
    RunnerHealth,
    ModelInfo,
)
from api.services.runner_impl.ollama import OllamaRunner


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_ollama_service():
    """A MagicMock OllamaService — used to assert call translation
    without hitting the real daemon."""
    svc = MagicMock()
    svc.host = "http://localhost:11434"
    svc.get_version.return_value = "0.23.4"
    svc.health_check.return_value = True
    svc.list_models.return_value = [
        {
            "name": "qwen2.5-coder:7b",
            "details": {"family": "qwen2", "quantization_level": "Q4_K_M"},
            "size": 4_700_000_000,
        },
        {
            "name": "dolphin3:latest",
            "details": {"family": "llama", "quantization_level": "Q4_K_M"},
            "size": 4_900_000_000,
        },
    ]
    svc.chat.return_value = {
        "content": "def fib(n): return n",
        "prompt_eval_count": 10,
        "eval_count": 6,
        "total_duration_ms": 420,
        "load_duration_ms": 0,
    }
    svc.pre_warm.return_value = {"model": "m", "load_duration_ms": 1234}
    return svc


@pytest.fixture
def runner(mock_ollama_service):
    return OllamaRunner(service=mock_ollama_service)


# ── Identity / capability surface ─────────────────────────────────────────


class TestRunnerIdentity:
    def test_name_is_ollama(self, runner):
        assert runner.name == RunnerKind.OLLAMA

    def test_base_url_proxies_service_host(self, runner, mock_ollama_service):
        assert runner.base_url == mock_ollama_service.host

    def test_supports_keep_alive(self, runner):
        # Ollama's per-request keep_alive TTL is the whole reason the
        # arch-aware eviction policy was designed; this MUST be True.
        assert runner.supports_keep_alive is True

    def test_supports_hot_swap(self, runner):
        # Ollama loads + evicts models dynamically on demand.
        assert runner.supports_hot_swap is True

    def test_does_not_support_continuous_batching(self, runner):
        # Ollama serializes via the OllamaService _LLM_SEMAPHORE.
        # If/when that changes, the runner cap should change too.
        assert runner.supports_continuous_batching is False

    def test_advertises_gguf_quants(self, runner):
        quants = set(runner.supports_quantizations)
        assert Quant.GGUF_Q4_K_M in quants
        assert Quant.GGUF_Q5_K_M in quants
        assert Quant.GGUF_Q3_K_M in quants
        # Should NOT claim NVFP4 / FP8 — those are vLLM territory.
        assert Quant.NVFP4 not in quants
        assert Quant.FP8 not in quants

    def test_max_concurrent_requests_is_one(self, runner):
        # Matches OllamaService._LLM_SEMAPHORE serialization (MAX_CONCURRENT_LLM=1).
        assert runner.max_concurrent_requests == 1

    def test_version_proxies_service(self, runner):
        assert runner.version == "0.23.4"


# ── list_models translation ───────────────────────────────────────────────


class TestListModels:
    def test_returns_model_infos(self, runner):
        infos = runner.list_models()
        assert len(infos) == 2
        assert all(isinstance(i, ModelInfo) for i in infos)

    def test_translates_qwen_entry(self, runner):
        infos = {i.id: i for i in runner.list_models()}
        qwen = infos["qwen2.5-coder:7b"]
        assert qwen.family == "qwen2"
        # GGUF Q4_K_M from the Ollama metadata maps to the Quant enum.
        assert qwen.quant == Quant.GGUF_Q4_K_M
        # size_gb derived from bytes
        assert qwen.size_gb is not None and 4.5 < qwen.size_gb < 5.0

    def test_handles_unknown_quant_string_gracefully(self, mock_ollama_service):
        # If Ollama returns a quant string the enum doesn't know, the
        # adapter should fall through to quant=None rather than crash.
        mock_ollama_service.list_models.return_value = [
            {
                "name": "weird:model",
                "details": {"family": "x", "quantization_level": "Q8_0"},
                "size": 1_000_000_000,
            },
        ]
        runner = OllamaRunner(service=mock_ollama_service)
        infos = runner.list_models()
        assert infos[0].quant is None


# ── generate translation ──────────────────────────────────────────────────


class TestGenerate:
    def test_translates_request_to_chat_call(self, runner, mock_ollama_service):
        req = GenerateRequest(
            model="qwen2.5-coder:7b",
            messages=[{"role": "user", "content": "def fib(n):"}],
            options={"temperature": 0.2, "max_tokens": 256},
            keep_alive="0",
        )
        resp = runner.generate(req)

        # Service was called with translated kwargs
        mock_ollama_service.chat.assert_called_once()
        kwargs = mock_ollama_service.chat.call_args.kwargs
        assert kwargs["model"] == "qwen2.5-coder:7b"
        assert kwargs["temperature"] == 0.2
        assert kwargs["max_tokens"] == 256
        assert kwargs["keep_alive"] == "0"

        # Response was translated back to GenerateResponse
        assert isinstance(resp, GenerateResponse)
        assert resp.content == "def fib(n): return n"
        assert resp.tokens_in == 10
        assert resp.tokens_out == 6
        assert resp.runner == RunnerKind.OLLAMA

    def test_defaults_when_options_missing(self, runner, mock_ollama_service):
        req = GenerateRequest(model="m", messages=[{"role": "user", "content": "hi"}])
        runner.generate(req)
        kwargs = mock_ollama_service.chat.call_args.kwargs
        # Adapter must pass through *something* sensible for temp/max_tokens
        assert "temperature" in kwargs
        assert "max_tokens" in kwargs


# ── load / unload ─────────────────────────────────────────────────────────


class TestLoadUnload:
    def test_load_wraps_pre_warm(self, runner, mock_ollama_service):
        result = runner.load("qwen2.5-coder:7b")
        mock_ollama_service.pre_warm.assert_called_once_with(
            "qwen2.5-coder:7b", keep_alive=None
        )
        assert isinstance(result, LoadResult)
        assert result.loaded is True
        assert result.load_seconds == pytest.approx(1.234, rel=0.01)

    def test_unload_via_synthetic_generate(self, runner, mock_ollama_service):
        # Ollama's eviction mechanism: a synthetic call with keep_alive:"0".
        # The adapter implements this via service.pre_warm(model, keep_alive="0")
        # which is the same /api/generate path with num_predict=0.
        result = runner.unload("qwen2.5-coder:7b")
        mock_ollama_service.pre_warm.assert_called_with(
            "qwen2.5-coder:7b", keep_alive="0"
        )
        assert isinstance(result, UnloadResult)
        assert result.unloaded is True


# ── health ────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_reachable_proxies(self, runner, mock_ollama_service):
        h = runner.health()
        assert isinstance(h, RunnerHealth)
        assert h.reachable is True
        assert h.version == "0.23.4"

    def test_health_unreachable(self, mock_ollama_service):
        mock_ollama_service.health_check.return_value = False
        mock_ollama_service.get_version.return_value = None
        runner = OllamaRunner(service=mock_ollama_service)
        h = runner.health()
        assert h.reachable is False
        assert h.version is None
