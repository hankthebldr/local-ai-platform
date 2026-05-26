#!/usr/bin/env python3
"""
OllamaRunner — Runner protocol adapter over the existing OllamaService.

Adapter pattern: zero behavior change in OllamaService itself. This class
exposes the Runner surface (RunnerKind.OLLAMA, capability flags, request/
response translation) and forwards to the underlying service.

Phase 1 / Task 1.2 of gpu-runner-abstraction.
See docs/plans/2026-05-23-gpu-runner-abstraction.md
"""

from __future__ import annotations

from typing import Iterator, List

from ..runner import (
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    LoadResult,
    LoadedModel,
    ModelInfo,
    Quant,
    RunnerHealth,
    RunnerKind,
    UnloadResult,
)
from ..ollama_service import OllamaService


# Map Ollama's quantization_level metadata strings to the Quant enum.
# Unknown strings → None (advertised as such in ModelInfo.quant).
_OLLAMA_QUANT_MAP = {
    "Q4_K_M": Quant.GGUF_Q4_K_M,
    "Q5_K_M": Quant.GGUF_Q5_K_M,
    "Q3_K_M": Quant.GGUF_Q3_K_M,
}


class OllamaRunner:
    """Runner protocol adapter wrapping an OllamaService instance.

    One OllamaRunner per OllamaService — typically the singleton created at
    app startup. The wrapped service still does all the HTTP work; this
    class is pure translation.
    """

    # ── identity / capabilities (Runner protocol surface) ────────────────

    name: RunnerKind = RunnerKind.OLLAMA
    supports_keep_alive: bool = True
    supports_hot_swap: bool = True
    supports_continuous_batching: bool = False
    # OllamaService serializes via _LLM_SEMAPHORE with MAX_CONCURRENT_LLM=1.
    # If that env knob is raised, this should track it — for now match the
    # default so the scheduler doesn't over-dispatch.
    max_concurrent_requests: int = 1
    supports_quantizations: List[Quant] = [
        Quant.GGUF_Q4_K_M,
        Quant.GGUF_Q5_K_M,
        Quant.GGUF_Q3_K_M,
    ]

    def __init__(self, service: OllamaService):
        self._service = service

    @property
    def base_url(self) -> str:
        return self._service.host

    @property
    def version(self) -> str:
        # OllamaService.get_version() may return None when the daemon is
        # unreachable; the Protocol declares str, so we coerce. The
        # health() probe is the right place to check reachability.
        return self._service.get_version() or ""

    # ── list_models / list_loaded ────────────────────────────────────────

    def list_models(self) -> List[ModelInfo]:
        raw = self._service.list_models()
        out: List[ModelInfo] = []
        for entry in raw:
            details = entry.get("details") or {}
            quant_str = details.get("quantization_level")
            quant = _OLLAMA_QUANT_MAP.get(quant_str) if quant_str else None
            size_bytes = entry.get("size")
            size_gb = (
                (size_bytes / 1e9) if isinstance(size_bytes, (int, float)) else None
            )
            out.append(
                ModelInfo(
                    id=entry.get("name", ""),
                    family=details.get("family"),
                    quant=quant,
                    context_window=details.get("context_length"),
                    size_gb=size_gb,
                )
            )
        return out

    def list_loaded(self) -> List[LoadedModel]:
        # Phase 1: OllamaService doesn't expose /api/ps directly. Return [].
        # Phase 4 (runner-aware scheduling) will add a thin /api/ps call here.
        # Tests for that behavior live in Phase 4's task block.
        return []

    # ── generate / generate_stream ───────────────────────────────────────

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        # Translate GenerateRequest → OllamaService.chat() kwargs.
        # Defaults match OllamaService.chat()'s own defaults so behavior is
        # identical when the caller omits options.
        temperature = req.options.get("temperature", 0.7)
        max_tokens = req.options.get("max_tokens", 2048)
        tools = req.options.get("tools")

        raw = self._service.chat(
            model=req.model,
            messages=req.messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            keep_alive=req.keep_alive,
        )

        load_ms = raw.get("load_duration_ms", 0) or 0
        total_ms = raw.get("total_duration_ms", 0) or 0
        return GenerateResponse(
            model=req.model,
            content=raw.get("content", ""),
            tokens_in=raw.get("prompt_eval_count", 0) or 0,
            tokens_out=raw.get("eval_count", 0) or 0,
            total_seconds=total_ms / 1000.0,
            load_seconds=load_ms / 1000.0,
            runner=RunnerKind.OLLAMA,
        )

    def generate_stream(self, req: GenerateRequest) -> Iterator[GenerateChunk]:
        # Phase 1: streaming through the Runner protocol is not yet wired.
        # Existing streaming callers go through OllamaService.chat_stream()
        # directly — they keep working unchanged. Phase 4 wires this up.
        raise NotImplementedError(
            "OllamaRunner.generate_stream() — wired in Phase 4 of "
            "gpu-runner-abstraction. Existing callers use OllamaService directly."
        )

    # ── load / unload ────────────────────────────────────────────────────

    def load(self, model_id: str) -> LoadResult:
        # Reuse the existing pre_warm path (POST /api/generate with
        # num_predict=0). keep_alive=None → service default.
        try:
            raw = self._service.pre_warm(model_id, keep_alive=None)
            load_ms = raw.get("load_duration_ms", 0) or 0
            return LoadResult(
                model=model_id,
                loaded=True,
                load_seconds=load_ms / 1000.0,
            )
        except Exception as e:
            return LoadResult(
                model=model_id, loaded=False, load_seconds=0.0, reason=str(e)
            )

    def unload(self, model_id: str) -> UnloadResult:
        # Ollama's eviction grammar: a synthetic call with keep_alive:"0"
        # tells the daemon to drop the model when the request completes.
        # The pre_warm() path (num_predict=0) is the cheapest way to do this.
        try:
            self._service.pre_warm(model_id, keep_alive="0")
            return UnloadResult(model=model_id, unloaded=True)
        except Exception as e:
            return UnloadResult(model=model_id, unloaded=False, reason=str(e))

    # ── health ───────────────────────────────────────────────────────────

    def health(self) -> RunnerHealth:
        reachable = bool(self._service.health_check())
        version = self._service.get_version() if reachable else None
        loaded = [m.id for m in self.list_loaded()] if reachable else []
        return RunnerHealth(
            reachable=reachable,
            version=version,
            loaded_models=loaded,
            extras={},
        )
