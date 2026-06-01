#!/usr/bin/env python3
"""
Ollama Service - Business logic for Ollama API interactions

Uses /api/chat for chat completions (proper template handling for thinking models)
Uses /api/generate for raw text completions
"""

import os
import re
import json
import threading
from typing import Any, AsyncGenerator, Dict, List, Optional

import requests
from dotenv import load_dotenv

from ..logging_config import logger
from ..exceptions import (
    GenerationError,
    InvalidRequestError,
    ModelNotFoundError,
    OllamaConnectionError,
)

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# 300 s was the original default, sized for GPU inference. On the
# CPU-only target hardware in this codebase (Mac M4 Pro / MS-01 / BD790i
# without dedicated GPU), prefilling a multi-thousand-token grounded
# prompt against a 1.5B-3B model can run well past 300 s on the first
# token. Bumped to 900 s (15 min) so long-context steps don't get cut
# off mid-prefill — which is what produced 26 failed runs of
# xsiam-detection-engineering against this stack: every one died on
# the enrich_context step at the 300 s wall, having never produced a
# completion token. Operators on faster hardware can shrink via the
# REQUEST_TIMEOUT env var.
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "900"))

# Default keep_alive: tell Ollama to hold the model in RAM for this long
# after a request. Adjacent workflow steps that use the same model skip
# the reload cost (30-90s for 34B-70B GGUFs). Set to "0" to evict
# immediately, or "-1" for indefinite. Format: Go duration string.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")

# Hard cap on concurrent LLM invocations against this Ollama daemon.
# On CPU-only hardware, two models sharing the same cores deliver
# *worse* total throughput than running serially — they fight for the
# same prefill bandwidth and L2 cache. Default 1 enforces strict
# serialization. Raise only if Ollama is fronting a GPU box where
# parallel decode is actually faster.
MAX_CONCURRENT_LLM = max(1, int(os.getenv("MAX_CONCURRENT_LLM", "1")))

# Process-wide semaphore around every LLM call. Built once at import
# time; all OllamaService instances share it because what matters is
# the Ollama daemon's RAM/CPU, not the Python object identity.
_LLM_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_LLM)

# Regex to strip <think>...</think> blocks from reasoning models
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output (reasoning models)."""
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned if cleaned else text  # Fall back to original if entirely think block


def _format_chat_prompt(messages: List[Dict]) -> str:
    """Format chat messages into a plain-text prompt (fallback for models without chat templates)."""
    prompt = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            prompt += f"System: {content}\n\n"
        elif role == "user":
            prompt += f"User: {content}\n\n"
        elif role == "assistant":
            prompt += f"Assistant: {content}\n\n"
    prompt += "Assistant:"
    return prompt


def _extract_timings(ollama_result: Dict) -> Dict[str, Optional[float]]:
    """Pull timing fields from an Ollama /api/chat or /api/generate response.

    Ollama returns nanoseconds; we convert to milliseconds for readability.
    Returns None for any field the response did not include (older Ollama
    versions, error paths, or fallback codepaths that synthesized a payload).
    """

    def _ns_to_ms(v):
        try:
            return float(v) / 1_000_000.0 if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "load_duration_ms": _ns_to_ms(ollama_result.get("load_duration")),
        "prompt_eval_duration_ms": _ns_to_ms(ollama_result.get("prompt_eval_duration")),
        "eval_duration_ms": _ns_to_ms(ollama_result.get("eval_duration")),
        "total_duration_ms": _ns_to_ms(ollama_result.get("total_duration")),
    }


class OllamaService:
    """Service for interacting with Ollama API"""

    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host
        # vLLM dispatch cache (gpu-runner-abstraction Phase 4): the set of
        # model ids the registered vLLM runner serves, refreshed with a short
        # TTL so chat/generate can route those models to vLLM transparently.
        self._vllm_served_cache: Optional[set] = None
        self._vllm_served_ts: float = 0.0

    # ── vLLM dispatch (full-platform vLLM access) ────────────────────────
    # Every inference caller — chat, completions, workflow steps, agents,
    # graph — funnels through this service, so routing vLLM-served models to
    # the vLLM runner HERE gives vLLM platform-wide reach without touching
    # each call site. Strictly additive: a model the vLLM runner doesn't
    # serve takes the unchanged Ollama path.

    def _vllm_runner(self):
        """Return the registered VLLM Runner, or None. Never raises."""
        try:
            from .runner_registry import get_current_registry
            from .runner import RunnerKind

            reg = get_current_registry()
            if RunnerKind.VLLM in reg.kinds():
                return reg.get(RunnerKind.VLLM)
        except Exception:
            pass
        return None

    def _vllm_served_models(self, runner) -> set:
        """Cached set of model ids the vLLM runner serves (8s TTL)."""
        import time

        now = time.monotonic()
        if self._vllm_served_cache is not None and (now - self._vllm_served_ts) < 8.0:
            return self._vllm_served_cache
        try:
            served = {m.id for m in runner.list_models()}
        except Exception:
            served = set()
        self._vllm_served_cache = served
        self._vllm_served_ts = now
        return served

    def _vllm_runner_for(self, model: str):
        """Return the vLLM runner iff it serves `model`, else None."""
        runner = self._vllm_runner()
        if runner is None:
            return None
        return runner if model in self._vllm_served_models(runner) else None

    def _vllm_chat(self, runner, model, messages, temperature, max_tokens, tools):
        """Dispatch a chat to vLLM and translate the OpenAI result into the
        same dict shape _chat_inner returns, so callers are oblivious."""
        from .runner import GenerateRequest

        opts = {"temperature": temperature, "max_tokens": max_tokens}
        if tools:
            opts["tools"] = tools
        resp = runner.generate(
            GenerateRequest(model=model, messages=messages, options=opts)
        )
        logger.info(
            "Chat complete (vLLM): model=%s, prompt_tokens=%s, completion_tokens=%s",
            model,
            resp.tokens_in,
            resp.tokens_out,
        )
        return {
            "content": strip_think_tags(resp.content or ""),
            "prompt_eval_count": resp.tokens_in,
            "eval_count": resp.tokens_out,
            "total_duration_ms": round((resp.total_seconds or 0.0) * 1000, 2),
            "load_duration_ms": round((resp.load_seconds or 0.0) * 1000, 2),
            "prompt_eval_duration_ms": None,
            "eval_duration_ms": None,
        }

    # ── Version probe (for architecture-aware orchestration) ─────────

    def get_version(self) -> Optional[str]:
        """Return Ollama daemon version string, or None if unreachable.

        Used by the architecture detector at startup to enforce the
        pinned 0.23.4 floor. Never raises — failure returns None.
        """
        try:
            response = requests.get(f"{self.host}/api/version", timeout=5)
            response.raise_for_status()
            return response.json().get("version")
        except Exception as e:
            logger.debug(f"Ollama version probe failed: {e}")
            return None

    # ── Model Management ───────────────────────────────────────────────

    def list_models(self) -> List[Dict]:
        """List all available models — Ollama's /api/tags plus any models the
        vLLM runner serves, so vLLM weights show up in every picker across the
        platform (Composer, chat, completions, agents)."""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=10)
            response.raise_for_status()
            models = response.json().get("models", [])
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            raise OllamaConnectionError(str(e))
        return models + self._vllm_model_entries()

    def _vllm_model_entries(self) -> List[Dict]:
        """vLLM-served models in Ollama /api/tags shape. Never raises."""
        runner = self._vllm_runner()
        if runner is None:
            return []
        entries = []
        try:
            for m in runner.list_models():
                entries.append(
                    {
                        "name": m.id,
                        "model": m.id,
                        "size": int((m.size_gb or 0) * 1e9),
                        "details": {
                            "family": m.family or "vllm",
                            "quantization_level": (m.quant.value if m.quant else None),
                            "context_length": m.context_window,
                        },
                        # Marker so the UI/telemetry can badge the backend.
                        "runner": "vllm",
                    }
                )
        except Exception:
            return []
        return entries

    def get_model_info(self, model: str) -> Dict:
        """Get detailed info about a specific model"""
        try:
            response = requests.post(
                f"{self.host}/api/show",
                json={"name": model},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ModelNotFoundError(model)
            raise OllamaConnectionError(str(e))
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")

    # ── Pre-warm (Phase 5) ─────────────────────────────────────────────

    def pre_warm(self, model: str, keep_alive: Optional[str] = None) -> Dict[str, Any]:
        """Load a model into Ollama's runtime memory without doing real inference.

        Phase 5 — workflow_engine calls this at tick boundaries (after the
        current tick's LLM dispatch begins) for the model the next tick will
        use, so the model is resident by the time the next step needs it.
        Hides cold-load cost behind the previous step's inference.

        **Bypasses _LLM_SEMAPHORE on purpose.** The semaphore exists to
        serialize *inference* (preventing two models from sharing CPU/GPU at
        once). Pre-warm is the inverse case: we *want* Ollama to load model B
        in the background while model A is generating, which Ollama supports
        whenever VRAM/RAM allows. The arch.transition_plan() call upstream is
        responsible for not firing pre_warm when that overlap isn't safe
        (NVIDIA single + bandwidth contention, OOM-pressure, etc).

        Implementation: POST /api/generate with empty prompt + num_predict=0.
        Ollama loads the GGUF but produces no tokens. `keep_alive` controls
        residency after the no-op call returns — defaults to the env setting.
        Returns the raw response dict (includes load_duration for telemetry).
        """
        request_data = {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
            "options": {"num_predict": 0},
        }
        logger.info(
            f"Pre-warming model: {model} (keep_alive={request_data['keep_alive']})"
        )
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            timings = _extract_timings(result)
            logger.info(
                f"Pre-warm complete: model={model} "
                f"load={timings['load_duration_ms']}ms"
            )
            return {"model": model, **timings}
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ModelNotFoundError(model)
            raise GenerationError(f"Pre-warm failed for {model}: {e}")
        except Exception as e:
            logger.warning(f"Pre-warm failed for {model}: {e}")
            raise GenerationError(str(e))

    # ── Chat Completions (uses /api/chat) ──────────────────────────────

    def chat(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        tools: List[Dict] = None,
        keep_alive: str = None,
    ) -> Dict:
        """
        Chat completion using Ollama's native /api/chat endpoint.

        Falls back to /api/generate with manual prompt formatting if /api/chat
        returns empty content (happens with models that lack chat templates,
        e.g. some uncensored/thinking models).

        Serialized via _LLM_SEMAPHORE — concurrent callers (multiple
        workflow runs, parallel chat requests) queue up rather than
        loading a second model into RAM alongside the first.
        """
        request_data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            request_data["tools"] = tools

        logger.info(
            f"Chat request: model={model}, messages={len(messages)}, temp={temperature}"
        )

        # vLLM-served models route to vLLM (continuous batching), bypassing the
        # Ollama serialization lock. Falls through to Ollama on any vLLM error.
        runner = self._vllm_runner_for(model)
        if runner is not None:
            try:
                return self._vllm_chat(
                    runner, model, messages, temperature, max_tokens, tools
                )
            except Exception as e:
                logger.warning(
                    "vLLM chat failed for %s (%s); falling back to Ollama", model, e
                )

        with _LLM_SEMAPHORE:
            return self._chat_inner(
                model, request_data, messages, temperature, max_tokens
            )

    def _chat_inner(self, model, request_data, messages, temperature, max_tokens):
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            # Strip thinking tags from response content
            content = result.get("message", {}).get("content", "")
            content = strip_think_tags(content)

            # Fallback: if /api/chat returned empty AND no tool_calls, use /api/generate
            # (empty content with tool_calls is valid — the model is requesting a tool)
            has_tool_calls = bool(result.get("message", {}).get("tool_calls"))
            if not content.strip() and not has_tool_calls:
                logger.info(
                    f"Chat returned empty for {model}, falling back to /api/generate"
                )
                prompt = _format_chat_prompt(messages)
                # Call the inner path — we already hold _LLM_SEMAPHORE
                # from chat(); going through generate() would attempt a
                # second acquire and deadlock when MAX_CONCURRENT_LLM=1.
                gen_request = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": request_data.get("keep_alive", OLLAMA_KEEP_ALIVE),
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                }
                gen_result = self._generate_inner(model, gen_request)
                content = gen_result.get("response", "")
                result["prompt_eval_count"] = gen_result.get("prompt_eval_count", 0)
                result["eval_count"] = gen_result.get("eval_count", 0)
                # Carry timing fields from the fallback so observability still
                # works when /api/chat returned empty.
                for k in (
                    "load_duration",
                    "prompt_eval_duration",
                    "eval_duration",
                    "total_duration",
                ):
                    if k in gen_result:
                        result[k] = gen_result[k]

            logger.info(
                f"Chat complete: model={model}, "
                f"prompt_tokens={result.get('prompt_eval_count', 0)}, "
                f"completion_tokens={result.get('eval_count', 0)}"
            )

            result_dict = {
                "content": content,
                "prompt_eval_count": result.get("prompt_eval_count", 0),
                "eval_count": result.get("eval_count", 0),
                **_extract_timings(result),
            }
            tool_calls = result.get("message", {}).get("tool_calls")
            if tool_calls:
                result_dict["tool_calls"] = tool_calls
            return result_dict
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except requests.HTTPError as e:
            # Propagate Ollama's 4xx responses as InvalidRequestError so the
            # client gets a useful, OpenAI-shaped error body (e.g. selecting
            # an embedding-only model for chat returns "<model> does not
            # support chat") instead of a generic 500.
            if e.response is not None:
                status = e.response.status_code
                if status == 404:
                    raise ModelNotFoundError(model)
                if 400 <= status < 500:
                    try:
                        body = e.response.json()
                        detail = (
                            body.get("error") or body.get("message") or e.response.text
                        )
                    except ValueError:
                        detail = e.response.text or str(e)
                    raise InvalidRequestError(
                        f"Ollama rejected the request (model={model}): {detail}"
                    )
            raise GenerationError(str(e))
        except (
            OllamaConnectionError,
            ModelNotFoundError,
            GenerationError,
            InvalidRequestError,
        ):
            raise
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            raise GenerationError(str(e))

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        keep_alive: str = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming chat completion using Ollama's /api/chat endpoint.
        Filters out <think> blocks from streaming output.

        Holds _LLM_SEMAPHORE for the entire stream duration — the model
        stays in use until the last token is emitted, so we mustn't let
        a second model load alongside it.
        """
        request_data = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Chat stream: model={model}, messages={len(messages)}")

        # vLLM-served models stream via the vLLM runner (no Ollama lock).
        runner = self._vllm_runner_for(model)
        if runner is not None:
            try:
                from .runner import GenerateRequest

                req = GenerateRequest(
                    model=model,
                    messages=messages,
                    stream=True,
                    options={"temperature": temperature, "max_tokens": max_tokens},
                )
                for chunk in runner.generate_stream(req):
                    if chunk.delta:
                        yield chunk.delta
                return
            except Exception as e:
                logger.warning(
                    "vLLM stream failed for %s (%s); falling back to Ollama",
                    model,
                    e,
                )

        _LLM_SEMAPHORE.acquire()
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()

            in_think_block = False
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")

                    # Track think blocks in streaming mode
                    if "<think>" in content:
                        in_think_block = True
                        # Emit any text before the tag
                        before = content.split("<think>")[0]
                        if before:
                            yield before
                        continue
                    if "</think>" in content:
                        in_think_block = False
                        # Emit any text after the closing tag
                        after = content.split("</think>")[-1]
                        if after:
                            yield after
                        continue
                    if in_think_block:
                        continue

                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except requests.HTTPError as e:
            # Mirror non-streaming path: surface Ollama 4xx as a clean
            # InvalidRequestError so the client sees the actual reason
            # (e.g. embedding-only model rejected for chat).
            if e.response is not None:
                status = e.response.status_code
                if status == 404:
                    raise ModelNotFoundError(model)
                if 400 <= status < 500:
                    try:
                        body = e.response.json()
                        detail = (
                            body.get("error") or body.get("message") or e.response.text
                        )
                    except ValueError:
                        detail = e.response.text or str(e)
                    raise InvalidRequestError(
                        f"Ollama rejected the request (model={model}): {detail}"
                    )
            raise GenerationError(str(e))
        except (
            OllamaConnectionError,
            ModelNotFoundError,
            GenerationError,
            InvalidRequestError,
        ):
            raise
        except Exception as e:
            logger.error(f"Chat stream failed: {e}")
            raise GenerationError(str(e))
        finally:
            _LLM_SEMAPHORE.release()

    # ── Text Completions (uses /api/generate) ──────────────────────────

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        keep_alive: str = None,
    ) -> Dict:
        """Generate a raw text completion using Ollama /api/generate.

        Serialized via _LLM_SEMAPHORE (see chat() for rationale). Note
        the fallback path in _chat_inner reaches here while it already
        holds the lock — BoundedSemaphore with MAX_CONCURRENT_LLM=1
        would deadlock, so callers from _chat_inner pass through
        _generate_inner directly to avoid double-acquire.
        """
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Generate request: model={model}, temp={temperature}")

        # vLLM-served models: satisfy raw completions via a single-message chat
        # and translate to /api/generate's response shape.
        runner = self._vllm_runner_for(model)
        if runner is not None:
            try:
                out = self._vllm_chat(
                    runner,
                    model,
                    [{"role": "user", "content": prompt}],
                    temperature,
                    max_tokens,
                    None,
                )
                return {
                    "response": out["content"],
                    "prompt_eval_count": out["prompt_eval_count"],
                    "eval_count": out["eval_count"],
                    "total_duration": int((out.get("total_duration_ms") or 0) * 1e6),
                }
            except Exception as e:
                logger.warning(
                    "vLLM generate failed for %s (%s); falling back to Ollama",
                    model,
                    e,
                )

        with _LLM_SEMAPHORE:
            return self._generate_inner(model, request_data)

    def _generate_inner(self, model, request_data):
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            # Strip thinking tags
            result["response"] = strip_think_tags(result.get("response", ""))

            logger.info(
                f"Generate complete: model={model}, "
                f"prompt_tokens={result.get('prompt_eval_count', 0)}, "
                f"completion_tokens={result.get('eval_count', 0)}"
            )
            return result
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ModelNotFoundError(model)
            raise GenerationError(str(e))
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise GenerationError(str(e))

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        keep_alive: str = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming text completion using Ollama /api/generate.

        Holds _LLM_SEMAPHORE for the full stream duration; see chat_stream
        for the reasoning.
        """
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": keep_alive if keep_alive is not None else OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Generate stream: model={model}")

        _LLM_SEMAPHORE.acquire()
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()

            in_think_block = False
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    content = chunk.get("response", "")

                    if "<think>" in content:
                        in_think_block = True
                        before = content.split("<think>")[0]
                        if before:
                            yield before
                        continue
                    if "</think>" in content:
                        in_think_block = False
                        after = content.split("</think>")[-1]
                        if after:
                            yield after
                        continue
                    if in_think_block:
                        continue

                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except Exception as e:
            logger.error(f"Generate stream failed: {e}")
            raise GenerationError(str(e))
        finally:
            _LLM_SEMAPHORE.release()

    # ── Utilities ──────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check if Ollama service is healthy"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
