#!/usr/bin/env python3
"""
Runner Service — inference backend abstraction layer.

Third orthogonal axis alongside Architecture (memory model) and Deployment
(process/packaging). Each Runner is one inference backend: Ollama for the
universal fallback path, vLLM for NVIDIA discrete-VRAM hosts with native
NVFP4 / continuous batching.

Two runner kinds at launch:
    ollama  — universal fallback; GGUF via Ollama daemon
    vllm    — NVIDIA Blackwell+ optimal; NVFP4 / FP8 / AWQ-INT4

Architecture detection drives runner selection at startup. The operator
escape hatch is ENCLAVE_PREFERRED_RUNNER (dev/testing only). See
docs/plans/2026-05-23-gpu-runner-abstraction.md for the full design.

This module defines the Protocol + supporting Pydantic models only.
Concrete implementations live in api/services/runner_impl/.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────


class RunnerKind(str, Enum):
    """Closed set of supported inference backends.

    Expansion (llama_cpp, tensorrt_llm, sglang) is a deliberate registry
    change — adding a value here requires adding a runner_impl/ module and
    an entry in the architecture impl's recommended_runner() / fallback_runners().
    """

    OLLAMA = "ollama"
    VLLM = "vllm"


class Quant(str, Enum):
    """Closed set of quantization formats a Runner may advertise via
    supports_quantizations.

    NVFP4 is the Blackwell-native 4-bit floating-point format; FP8 is the
    practical alternative on Ada/Hopper; AWQ-INT4 is the cross-vendor
    4-bit weight quant. GGUF_* are Ollama's GGML formats.
    """

    NVFP4 = "nvfp4"
    FP8 = "fp8"
    AWQ_INT4 = "awq_int4"
    GGUF_Q4_K_M = "gguf_q4_k_m"
    GGUF_Q5_K_M = "gguf_q5_k_m"
    GGUF_Q3_K_M = "gguf_q3_k_m"
    FP16 = "fp16"
    BF16 = "bf16"


# ── Generate request / response shapes ────────────────────────────────────


class GenerateRequest(BaseModel):
    """Backend-agnostic generation request.

    Shape mirrors OpenAI chat completions — both Ollama and vLLM speak this
    natively. options is a passthrough dict; each runner impl decides which
    keys it honors (e.g. Ollama accepts `num_ctx`, vLLM accepts
    `max_tokens` + `top_p` etc.).
    """

    model: str
    messages: List[Dict[str, Any]]
    stream: bool = False
    options: Dict[str, Any] = Field(default_factory=dict)
    keep_alive: Optional[str] = None  # Ollama honors; vLLM ignores (logged)


class GenerateResponse(BaseModel):
    """Non-streaming generation result.

    load_seconds is the cold-load cost paid by THIS request. vLLM pinned
    servers always report 0.0 because the model loaded at server start.
    Ollama reports the /api/generate load_duration when the model wasn't
    already resident.
    """

    model: str
    content: str
    tokens_in: int
    tokens_out: int
    total_seconds: float
    runner: RunnerKind
    load_seconds: float = 0.0
    finish_reason: Optional[str] = None


class GenerateChunk(BaseModel):
    """One streaming delta.

    done=True is the terminal chunk; totals are populated only there.
    """

    model: str
    delta: str
    done: bool
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    total_seconds: Optional[float] = None
    finish_reason: Optional[str] = None


# ── Model / load / health ────────────────────────────────────────────────


class ModelInfo(BaseModel):
    """One available model, as advertised by Runner.list_models()."""

    id: str
    family: Optional[str] = None
    quant: Optional[Quant] = None
    context_window: Optional[int] = None
    size_gb: Optional[float] = None


class LoadedModel(BaseModel):
    """One currently-resident model, as reported by Runner.list_loaded().

    vram_gb is the runner's best estimate of VRAM/RAM footprint; pulled
    from Ollama's /api/ps for OllamaRunner, from vLLM's metrics endpoint
    for VllmRunner.
    """

    id: str
    loaded_at: float
    vram_gb: Optional[float] = None


class LoadResult(BaseModel):
    """Outcome of an explicit Runner.load() call."""

    model: str
    loaded: bool
    load_seconds: float = 0.0
    reason: Optional[str] = None


class UnloadResult(BaseModel):
    """Outcome of an explicit Runner.unload() call.

    For pinned-server vLLM, unloaded=False with reason="vllm_pinned_server"
    is the expected shape — the engine logs the no-op and moves on.
    """

    model: str
    unloaded: bool
    reason: Optional[str] = None


class RunnerHealth(BaseModel):
    """Runner.health() output. extras is runner-specific (e.g. gpu_memory_pct
    for vLLM, num_loaded for Ollama)."""

    reachable: bool
    version: Optional[str] = None
    loaded_models: List[str] = Field(default_factory=list)
    extras: Dict[str, Any] = Field(default_factory=dict)


# ── Protocol ──────────────────────────────────────────────────────────────


@runtime_checkable
class Runner(Protocol):
    """The capability interface every inference backend satisfies.

    Detected at startup; the *active* runner is accessed via Runner.current().
    Multiple Runners may coexist in RunnerRegistry (Phase 1.3) — for example
    Ollama on :11434 alongside vLLM on :8001 on a Blackwell host. The
    per-model dispatch decision picks the right one via the registry.

    Implementations live in api/services/runner_impl/.
    """

    # ── identity / capabilities ───
    name: RunnerKind
    base_url: str
    supports_keep_alive: bool
    supports_hot_swap: bool
    supports_continuous_batching: bool
    supports_quantizations: List[Quant]
    version: str
    max_concurrent_requests: int

    # ── runtime methods ───
    def list_models(self) -> List[ModelInfo]:
        """Models the runner can currently serve.

        Ollama: /api/tags. vLLM: /v1/models on each configured base_url.
        """
        ...

    def list_loaded(self) -> List[LoadedModel]:
        """Models currently resident.

        Ollama: /api/ps. vLLM (pinned): models the server was started with.
        """
        ...

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        """Synchronous, non-streaming generation."""
        ...

    def generate_stream(self, req: GenerateRequest) -> Iterator[GenerateChunk]:
        """Streaming generation — yields GenerateChunk until done=True."""
        ...

    def load(self, model_id: str) -> LoadResult:
        """Explicit load. Ollama: pre_warm via empty generate. vLLM pinned:
        no-op (model loaded at server start). vLLM managed: spawn server."""
        ...

    def unload(self, model_id: str) -> UnloadResult:
        """Explicit unload. Ollama: keep_alive:0 on a synthetic generate.
        vLLM pinned: no-op. vLLM managed: stop server process."""
        ...

    def health(self) -> RunnerHealth:
        """Liveness + capability probe. Used at startup (Phase 3) and by
        /api/system/runner."""
        ...


# ── Singleton state + accessor ────────────────────────────────────────────
# Phase 1: only the singleton accessor exists. Phase 3 (architecture-driven
# selection) populates this from detect_runners().


_current_runner: Optional[Runner] = None


def _set_current(runner: Runner) -> None:
    """Used by detect_runners() (Phase 3). Not part of the public API."""
    global _current_runner
    _current_runner = runner


def _get_current() -> Runner:
    if _current_runner is None:
        raise RuntimeError(
            "Runner.current() called before detect_runners(). "
            "Call detect_runners() during app startup (api/main.py)."
        )
    return _current_runner


# Attach `current()` as an ergonomic class-level accessor on the Protocol,
# mirroring Architecture.current() and Deployment.current(). Type checkers
# may not see this (Protocol attributes are typically declared in the body),
# but at runtime Runner.current() returns the singleton.
def _runner_current_static() -> "Runner":
    return _get_current()


Runner.current = staticmethod(_runner_current_static)  # type: ignore[attr-defined]
