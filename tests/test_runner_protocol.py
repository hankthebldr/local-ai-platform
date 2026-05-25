"""Tests for the Runner protocol + supporting types.

Phase 1 / Task 1.1 of gpu-runner-abstraction.
See docs/plans/2026-05-23-gpu-runner-abstraction.md
"""

from __future__ import annotations

import time

import pytest

from api.services.runner import (
    RunnerKind,
    Quant,
    GenerateRequest,
    GenerateResponse,
    GenerateChunk,
    LoadResult,
    UnloadResult,
    RunnerHealth,
    LoadedModel,
    ModelInfo,
    Runner,
)


class TestRunnerKind:
    def test_enum_string_values(self):
        assert RunnerKind.OLLAMA.value == "ollama"
        assert RunnerKind.VLLM.value == "vllm"

    def test_runner_kind_membership(self):
        # Closed set; expansion is a deliberate registry change.
        # llama_cpp / tensorrt_llm / sglang are future additions.
        assert set(RunnerKind) == {RunnerKind.OLLAMA, RunnerKind.VLLM}


class TestQuant:
    def test_blackwell_relevant_quants_present(self):
        # NVFP4 is the Blackwell-native 4-bit float format; FP8 and
        # AWQ-INT4 are the practical alternatives for sub-frontier hosts.
        assert Quant.NVFP4.value == "nvfp4"
        assert Quant.FP8.value == "fp8"
        assert Quant.AWQ_INT4.value == "awq_int4"

    def test_gguf_quants_present(self):
        # GGUF quants are what Ollama serves; must be representable here
        # so the OllamaRunner can advertise them via supports_quantizations.
        assert Quant.GGUF_Q4_K_M.value == "gguf_q4_k_m"
        assert Quant.GGUF_Q5_K_M.value == "gguf_q5_k_m"
        assert Quant.GGUF_Q3_K_M.value == "gguf_q3_k_m"

    def test_full_precision_quants_present(self):
        assert Quant.FP16.value == "fp16"
        assert Quant.BF16.value == "bf16"


class TestGenerateRequest:
    def test_minimal_construction(self):
        req = GenerateRequest(
            model="qwen3-coder-30b-a3b-nvfp4",
            messages=[{"role": "user", "content": "def fib(n):"}],
        )
        assert req.model == "qwen3-coder-30b-a3b-nvfp4"
        assert len(req.messages) == 1
        assert req.stream is False  # default

    def test_stream_flag_optional(self):
        req = GenerateRequest(
            model="m", messages=[{"role": "user", "content": "hi"}], stream=True
        )
        assert req.stream is True

    def test_options_passthrough(self):
        # options is an open dict — both Ollama and vLLM accept arbitrary
        # generation params (temperature, top_p, num_ctx, etc.). The runner
        # impl decides which keys it honors.
        req = GenerateRequest(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            options={"temperature": 0.2, "max_tokens": 256},
        )
        assert req.options["temperature"] == 0.2


class TestGenerateResponse:
    def test_minimal_construction(self):
        resp = GenerateResponse(
            model="m",
            content="hello",
            tokens_in=10,
            tokens_out=2,
            total_seconds=0.42,
            runner=RunnerKind.OLLAMA,
        )
        assert resp.content == "hello"
        assert resp.runner == RunnerKind.OLLAMA

    def test_load_seconds_optional(self):
        # vLLM (pinned server): always 0.0. Ollama: positive on cold load,
        # 0.0 when model already warm.
        resp = GenerateResponse(
            model="m",
            content="x",
            tokens_in=1,
            tokens_out=1,
            total_seconds=0.1,
            runner=RunnerKind.VLLM,
            load_seconds=0.0,
        )
        assert resp.load_seconds == 0.0


class TestGenerateChunk:
    def test_streaming_chunk_shape(self):
        chunk = GenerateChunk(model="m", delta="hel", done=False)
        assert chunk.delta == "hel"
        assert chunk.done is False

    def test_terminal_chunk_carries_totals(self):
        chunk = GenerateChunk(
            model="m",
            delta="",
            done=True,
            tokens_in=5,
            tokens_out=12,
            total_seconds=0.3,
        )
        assert chunk.done is True
        assert chunk.tokens_out == 12


class TestLoadAndHealth:
    def test_load_result_shape(self):
        r = LoadResult(model="m", loaded=True, load_seconds=2.5)
        assert r.loaded is True
        assert r.load_seconds == 2.5

    def test_unload_result_with_noop(self):
        # vLLM pinned-server mode: unload is a no-op with a reason.
        r = UnloadResult(model="m", unloaded=False, reason="vllm_pinned_server")
        assert r.unloaded is False
        assert r.reason == "vllm_pinned_server"

    def test_runner_health_shape(self):
        h = RunnerHealth(
            reachable=True,
            version="0.7.2",
            loaded_models=["qwen3-coder-30b-a3b-nvfp4"],
            extras={"gpu_memory_pct": 78.0},
        )
        assert h.reachable is True
        assert "qwen3-coder-30b-a3b-nvfp4" in h.loaded_models

    def test_loaded_model_shape(self):
        m = LoadedModel(id="qwen3", loaded_at=time.time(), vram_gb=17.2)
        assert m.id == "qwen3"
        assert m.vram_gb == 17.2

    def test_model_info_shape(self):
        info = ModelInfo(
            id="qwen3-coder-30b-a3b-nvfp4",
            family="qwen3",
            quant=Quant.NVFP4,
            context_window=262144,
            size_gb=17.2,
        )
        assert info.quant == Quant.NVFP4
        assert info.context_window == 262144


class TestRunnerProtocol:
    def test_protocol_attributes_present(self):
        # The Protocol surface every concrete impl must satisfy.
        expected_attrs = {
            "name",
            "base_url",
            "supports_keep_alive",
            "supports_hot_swap",
            "supports_continuous_batching",
            "supports_quantizations",
            "version",
            "max_concurrent_requests",
        }
        # __annotations__ holds the Protocol's typed-attribute declarations
        actual = set(Runner.__annotations__.keys())
        missing = expected_attrs - actual
        assert not missing, f"Runner protocol missing attrs: {missing}"

    def test_current_singleton_unset_raises(self):
        # Mirrors Architecture / Deployment singleton semantics: calling
        # current() before detection is a programmer error, not a default.
        from api.services import runner as runner_mod

        # Ensure pristine state for this assertion
        runner_mod._current_runner = None
        with pytest.raises(RuntimeError, match="detect_runners"):
            Runner.current()
