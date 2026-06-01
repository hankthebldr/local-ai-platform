#!/usr/bin/env python3
"""
VllmRunner — Runner protocol adapter over a vLLM OpenAI-compatible server.

Phase 2 of gpu-runner-abstraction. On a Linux NVIDIA host (the BD790i
Blackwell box is the reference target) vLLM beats Ollama for sustained
throughput: native NVFP4 / FP8 weights, paged-attention KV cache, and
continuous batching keep the GPU saturated where Ollama's llama.cpp runner
serializes. This adapter lets the engine dispatch a model to vLLM through
the same Runner surface OllamaRunner satisfies.

Design — *pinned server* model:
    vLLM is launched out-of-band (systemd unit / `scripts/vllm-serve.sh`)
    serving one or more models, exposing an OpenAI-compatible API. This
    class is a pure HTTP client against that server — it does NOT import
    vllm, spawn subprocesses, or manage GPU memory. That keeps the Enclave
    venv free of the (heavy, CUDA-specific) vllm dependency: the only
    requirement is a reachable server URL.

    Because the model is loaded at server start:
      - load()   is a no-op (the weights are already resident)
      - unload() is a no-op (reason="vllm_pinned_server")
      - keep_alive is ignored (logged once per request via options)

Endpoints used (all standard vLLM OpenAI surface):
    GET  /v1/models            — served model ids + context window
    POST /v1/chat/completions  — generate (+ stream via SSE)
    GET  /health               — liveness
    GET  /version              — {"version": "..."} (best-effort)
    GET  /metrics              — Prometheus text (KV-cache usage, running reqs)

See docs/deployment/vllm-backend.md for the operator guide.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

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

logger = logging.getLogger("local-ai")


# vLLM advertises a quantization on each /v1/models entry only inconsistently,
# so we map the formats the runner *can* serve for capability reporting. The
# Blackwell-native NVFP4 path is the reason this runner exists.
_VLLM_QUANTS: List[Quant] = [
    Quant.NVFP4,
    Quant.FP8,
    Quant.AWQ_INT4,
    Quant.FP16,
    Quant.BF16,
]

# Map common vLLM `--quantization` / HF quant strings → Quant enum, used when
# a served-model id encodes its quant (best-effort; unknown → None).
_QUANT_HINT_MAP = {
    "nvfp4": Quant.NVFP4,
    "fp8": Quant.FP8,
    "awq": Quant.AWQ_INT4,
    "awq_int4": Quant.AWQ_INT4,
    "int4": Quant.AWQ_INT4,
    "fp16": Quant.FP16,
    "bf16": Quant.BF16,
}


def _guess_quant(model_id: str) -> Optional[Quant]:
    """Best-effort quant inference from the served model id (e.g.
    'nvidia/Qwen3-Coder-30B-A3B-NVFP4' → NVFP4). Returns None when nothing
    in the id matches a known quant token."""
    lowered = model_id.lower()
    for token, quant in _QUANT_HINT_MAP.items():
        if token in lowered:
            return quant
    return None


class VllmRunner:
    """Runner protocol adapter for a vLLM OpenAI-compatible server.

    One VllmRunner per vLLM base_url. Multiple vLLM servers (e.g. one per
    GPU) are modeled as multiple VllmRunner instances in a future fleet
    phase; Phase 2 wires a single server.
    """

    # ── identity / capabilities (Runner protocol surface) ────────────────

    name: RunnerKind = RunnerKind.VLLM
    # vLLM has no keep_alive concept — the model is pinned at server start.
    supports_keep_alive: bool = False
    # A pinned server serves a fixed model set; hot-swapping a different
    # model would require restarting the server, so the runner reports False.
    supports_hot_swap: bool = False
    # The headline reason to prefer vLLM on this host.
    supports_continuous_batching: bool = True
    supports_quantizations: List[Quant] = _VLLM_QUANTS

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        timeout: float = 900.0,
        max_concurrent_requests: int = 256,
        session: Optional[requests.Session] = None,
    ):
        # Normalize: strip a trailing slash and any trailing /v1 so we can
        # build both /v1/* and bare /health, /metrics consistently.
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
        self._root = url
        self.base_url = f"{url}/v1"
        self._api_key = api_key or os.getenv("ENCLAVE_VLLM_API_KEY") or None
        self._timeout = timeout
        # vLLM continuous-batches; the scheduler may dispatch many concurrent
        # requests. Default mirrors vLLM's own --max-num-seqs ballpark; the
        # operator can lower it via ENCLAVE_VLLM_MAX_CONCURRENT.
        self.max_concurrent_requests = max_concurrent_requests
        self._session = session or requests.Session()
        self._version: Optional[str] = None  # lazily probed, cached

    # ── helpers ───────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    @property
    def version(self) -> str:
        """vLLM server version. Cached after first successful probe; coerced
        to "" when unreachable (the Protocol declares str; health() is the
        right place to check reachability)."""
        if self._version is not None:
            return self._version
        try:
            r = self._session.get(
                f"{self._root}/version", headers=self._headers(), timeout=5
            )
            if r.status_code == 200:
                self._version = (r.json() or {}).get("version", "") or ""
                return self._version
        except requests.RequestException:
            pass
        return ""

    # ── list_models / list_loaded ────────────────────────────────────────

    def list_models(self) -> List[ModelInfo]:
        """Models the vLLM server is serving (GET /v1/models)."""
        try:
            r = self._session.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=10
            )
            r.raise_for_status()
            data = (r.json() or {}).get("data", [])
        except requests.RequestException as e:
            logger.warning("vLLM list_models failed at %s: %s", self.base_url, e)
            return []
        out: List[ModelInfo] = []
        for entry in data:
            model_id = entry.get("id", "")
            out.append(
                ModelInfo(
                    id=model_id,
                    family=entry.get("owned_by"),
                    quant=_guess_quant(model_id),
                    context_window=entry.get("max_model_len"),
                    size_gb=None,  # vLLM doesn't report on-disk size via /v1/models
                )
            )
        return out

    def list_loaded(self) -> List[LoadedModel]:
        """For a pinned server every served model is resident. We report each
        served model as loaded; vram_gb is read from /metrics when available
        (best-effort, shared across all served models so left None here)."""
        loaded_at = time.time()
        return [
            LoadedModel(id=m.id, loaded_at=loaded_at, vram_gb=None)
            for m in self.list_models()
        ]

    # ── generate / generate_stream ───────────────────────────────────────

    def _body(self, req: GenerateRequest, stream: bool) -> Dict[str, Any]:
        """Translate a backend-agnostic GenerateRequest → vLLM OpenAI body.

        Only OpenAI-recognized sampling keys are forwarded; Ollama-specific
        keys (num_ctx, num_gpu, …) are dropped. keep_alive is ignored with a
        one-line debug note since vLLM pins the model."""
        opts = req.options or {}
        if req.keep_alive is not None:
            logger.debug(
                "vLLM ignores keep_alive=%r (model pinned at server start)",
                req.keep_alive,
            )
        body: Dict[str, Any] = {
            "model": req.model,
            "messages": req.messages,
            "stream": stream,
        }
        # Forward the sampling params vLLM honors; only when present so we
        # don't override server defaults with our own.
        for key in ("temperature", "max_tokens", "top_p", "top_k", "stop", "seed"):
            if key in opts and opts[key] is not None:
                body[key] = opts[key]
        # Tool-calling passthrough (vLLM supports OpenAI tools for many models).
        if opts.get("tools"):
            body["tools"] = opts["tools"]
        return body

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        """Synchronous, non-streaming generation via POST /v1/chat/completions."""
        t0 = time.perf_counter()
        r = self._session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._body(req, stream=False),
            timeout=self._timeout,
        )
        r.raise_for_status()
        data = r.json() or {}
        elapsed = time.perf_counter() - t0

        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        usage = data.get("usage") or {}
        return GenerateResponse(
            model=data.get("model", req.model),
            content=message.get("content") or "",
            tokens_in=usage.get("prompt_tokens", 0) or 0,
            tokens_out=usage.get("completion_tokens", 0) or 0,
            total_seconds=elapsed,
            # Pinned server: weights loaded at server start, never per-request.
            load_seconds=0.0,
            runner=RunnerKind.VLLM,
            finish_reason=choices[0].get("finish_reason"),
        )

    def generate_stream(self, req: GenerateRequest) -> Iterator[GenerateChunk]:
        """Streaming generation via SSE. Yields a GenerateChunk per delta and
        a terminal done=True chunk carrying totals."""
        t0 = time.perf_counter()
        tokens_out = 0
        finish_reason: Optional[str] = None
        with self._session.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=self._body(req, stream=True),
            timeout=self._timeout,
            stream=True,
        ) as r:
            r.raise_for_status()
            for raw_line in r.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[len("data:") :].strip()
                if line == "[DONE]":
                    break
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices") or [{}]
                delta = (choices[0].get("delta") or {}).get("content") or ""
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr
                if delta:
                    tokens_out += 1  # delta count ≈ token count for progress
                    yield GenerateChunk(
                        model=payload.get("model", req.model),
                        delta=delta,
                        done=False,
                    )
        yield GenerateChunk(
            model=req.model,
            delta="",
            done=True,
            tokens_out=tokens_out,
            total_seconds=time.perf_counter() - t0,
            finish_reason=finish_reason,
        )

    # ── load / unload (no-ops for a pinned server) ───────────────────────

    def load(self, model_id: str) -> LoadResult:
        """No-op: a pinned vLLM server loads its model(s) at start. Reports
        loaded=True when the id is actually served, else loaded=False so the
        scheduler knows this runner can't serve it."""
        served = {m.id for m in self.list_models()}
        if model_id in served:
            return LoadResult(
                model=model_id,
                loaded=True,
                load_seconds=0.0,
                reason="vllm_pinned_server",
            )
        return LoadResult(
            model=model_id,
            loaded=False,
            load_seconds=0.0,
            reason=f"model '{model_id}' not served by vLLM at {self.base_url}",
        )

    def unload(self, model_id: str) -> UnloadResult:
        """No-op: vLLM can't evict a pinned model without a server restart."""
        return UnloadResult(model=model_id, unloaded=False, reason="vllm_pinned_server")

    # ── health ───────────────────────────────────────────────────────────

    def health(self) -> RunnerHealth:
        """Liveness + capability probe. Reachable when GET /health is 200
        (falls back to /v1/models for servers without /health). extras
        carries KV-cache usage + running-request gauges scraped from
        /metrics when present."""
        reachable = False
        try:
            r = self._session.get(f"{self._root}/health", timeout=5)
            reachable = r.status_code == 200
        except requests.RequestException:
            reachable = False
        if not reachable:
            # Some deployments disable /health; treat a successful /v1/models
            # as alive too.
            try:
                r = self._session.get(
                    f"{self.base_url}/models", headers=self._headers(), timeout=5
                )
                reachable = r.status_code == 200
            except requests.RequestException:
                reachable = False

        loaded = [m.id for m in self.list_models()] if reachable else []
        extras: Dict[str, Any] = {"continuous_batching": True}
        if reachable:
            extras.update(self._scrape_metrics())
        return RunnerHealth(
            reachable=reachable,
            version=self.version or None if reachable else None,
            loaded_models=loaded,
            extras=extras,
        )

    def _scrape_metrics(self) -> Dict[str, Any]:
        """Best-effort scrape of a couple of high-signal vLLM gauges from the
        Prometheus /metrics endpoint. Never raises — returns {} on any issue."""
        try:
            r = self._session.get(f"{self._root}/metrics", timeout=5)
            if r.status_code != 200:
                return {}
        except requests.RequestException:
            return {}
        wanted = {
            "vllm:num_requests_running": "num_requests_running",
            "vllm:num_requests_waiting": "num_requests_waiting",
            "vllm:gpu_cache_usage_perc": "gpu_cache_usage_perc",
        }
        out: Dict[str, Any] = {}
        for line in r.text.splitlines():
            if line.startswith("#") or " " not in line:
                continue
            metric = line.split("{", 1)[0].split(" ", 1)[0]
            key = wanted.get(metric)
            if key is None:
                continue
            try:
                out[key] = float(line.rsplit(" ", 1)[1])
            except (ValueError, IndexError):
                continue
        return out

    @classmethod
    def current(cls):
        from ..runner import _get_current

        return _get_current()
