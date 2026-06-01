"""Tests for the VllmRunner adapter.

Phase 2 of gpu-runner-abstraction.

VllmRunner is a pure HTTP client against a vLLM OpenAI-compatible server.
These tests inject a fake requests.Session so nothing hits a real server —
they assert request translation (GenerateRequest → OpenAI body), response
parsing (OpenAI → GenerateResponse), SSE stream decoding, the pinned-server
load/unload no-ops, and /health + /metrics handling.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from api.services.runner import (
    GenerateRequest,
    Quant,
    RunnerKind,
)
from api.services.runner_impl.vllm import VllmRunner, _guess_quant

# ── Fake HTTP plumbing ────────────────────────────────────────────────────


def _resp(status=200, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.text = text
    r.raise_for_status.side_effect = (
        None if status < 400 else requests.HTTPError(f"{status}")
    )
    return r


class FakeSession:
    """Routes GET/POST by URL suffix to canned responses."""

    def __init__(self, *, get_map=None, post_resp=None, stream_lines=None):
        self._get_map = get_map or {}
        self._post_resp = post_resp
        self._stream_lines = stream_lines or []
        self.last_post_json = None

    def get(self, url, **kw):
        for suffix, resp in self._get_map.items():
            if url.endswith(suffix):
                return resp
        return _resp(404)

    def post(self, url, json=None, **kw):
        self.last_post_json = json
        if kw.get("stream"):
            return _StreamCtx(self._stream_lines)
        return self._post_resp if self._post_resp is not None else _resp(200, {})


class _StreamCtx:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


# ── Identity / capability surface ─────────────────────────────────────────


class TestIdentity:
    def test_name_and_caps(self):
        r = VllmRunner("http://localhost:8000", session=FakeSession())
        assert r.name == RunnerKind.VLLM
        assert r.supports_continuous_batching is True
        assert r.supports_keep_alive is False
        assert r.supports_hot_swap is False
        assert Quant.NVFP4 in r.supports_quantizations

    def test_base_url_normalization(self):
        # Trailing slash and explicit /v1 both normalize to one canonical form.
        for given in (
            "http://localhost:8000",
            "http://localhost:8000/",
            "http://localhost:8000/v1",
            "http://localhost:8000/v1/",
        ):
            r = VllmRunner(given, session=FakeSession())
            assert r.base_url == "http://localhost:8000/v1"
            assert r._root == "http://localhost:8000"

    def test_guess_quant_from_id(self):
        assert _guess_quant("nvidia/Qwen3-Coder-30B-A3B-NVFP4") == Quant.NVFP4
        assert _guess_quant("some/model-fp8") == Quant.FP8
        assert _guess_quant("plain/model") is None


# ── list_models ───────────────────────────────────────────────────────────


class TestListModels:
    def test_parses_v1_models(self):
        body = {
            "data": [
                {
                    "id": "nvidia/Qwen3-Coder-30B-A3B-NVFP4",
                    "owned_by": "vllm",
                    "max_model_len": 4096,
                }
            ]
        }
        sess = FakeSession(get_map={"/v1/models": _resp(200, body)})
        r = VllmRunner("http://localhost:8000", session=sess)
        models = r.list_models()
        assert len(models) == 1
        assert models[0].id == "nvidia/Qwen3-Coder-30B-A3B-NVFP4"
        assert models[0].context_window == 4096
        assert models[0].quant == Quant.NVFP4

    def test_unreachable_returns_empty(self):
        sess = FakeSession(get_map={})  # 404 for everything
        r = VllmRunner("http://localhost:8000", session=sess)
        assert r.list_models() == []

    def test_list_loaded_mirrors_served(self):
        body = {"data": [{"id": "m1"}, {"id": "m2"}]}
        sess = FakeSession(get_map={"/v1/models": _resp(200, body)})
        r = VllmRunner("http://localhost:8000", session=sess)
        loaded = r.list_loaded()
        assert {m.id for m in loaded} == {"m1", "m2"}


# ── generate ───────────────────────────────────────────────────────────────


class TestGenerate:
    def test_translates_and_parses(self):
        resp = _resp(
            200,
            {
                "model": "served-model",
                "choices": [
                    {
                        "message": {"content": "hello world"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )
        sess = FakeSession(post_resp=resp)
        r = VllmRunner("http://localhost:8000", session=sess)
        out = r.generate(
            GenerateRequest(
                model="served-model",
                messages=[{"role": "user", "content": "hi"}],
                options={"temperature": 0.2, "max_tokens": 64},
                keep_alive="10m",  # must be ignored, not forwarded
            )
        )
        # Response parsed correctly.
        assert out.content == "hello world"
        assert out.tokens_in == 5
        assert out.tokens_out == 2
        assert out.runner == RunnerKind.VLLM
        assert out.finish_reason == "stop"
        assert out.load_seconds == 0.0
        # Request body translated: sampling params forwarded, keep_alive dropped.
        body = sess.last_post_json
        assert body["model"] == "served-model"
        assert body["temperature"] == 0.2
        assert body["max_tokens"] == 64
        assert body["stream"] is False
        assert "keep_alive" not in body

    def test_empty_choices_safe(self):
        sess = FakeSession(post_resp=_resp(200, {"choices": []}))
        r = VllmRunner("http://localhost:8000", session=sess)
        out = r.generate(
            GenerateRequest(model="m", messages=[{"role": "user", "content": "x"}])
        )
        assert out.content == ""


# ── generate_stream ────────────────────────────────────────────────────────


class TestStream:
    def test_sse_decoding(self):
        lines = [
            'data: {"model":"m","choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"model":"m","choices":[{"delta":{"content":"lo"}}]}',
            'data: {"model":"m","choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        sess = FakeSession(stream_lines=lines)
        r = VllmRunner("http://localhost:8000", session=sess)
        chunks = list(
            r.generate_stream(
                GenerateRequest(
                    model="m",
                    messages=[{"role": "user", "content": "hi"}],
                    stream=True,
                )
            )
        )
        deltas = [c.delta for c in chunks if not c.done]
        assert "".join(deltas) == "Hello"
        terminal = chunks[-1]
        assert terminal.done is True
        assert terminal.finish_reason == "stop"
        assert terminal.tokens_out == 2


# ── load / unload (pinned-server no-ops) ───────────────────────────────────


class TestLoadUnload:
    def test_load_served_model_is_noop_success(self):
        body = {"data": [{"id": "served"}]}
        sess = FakeSession(get_map={"/v1/models": _resp(200, body)})
        r = VllmRunner("http://localhost:8000", session=sess)
        res = r.load("served")
        assert res.loaded is True
        assert res.reason == "vllm_pinned_server"

    def test_load_unserved_model_reports_not_loaded(self):
        body = {"data": [{"id": "served"}]}
        sess = FakeSession(get_map={"/v1/models": _resp(200, body)})
        r = VllmRunner("http://localhost:8000", session=sess)
        res = r.load("not-served")
        assert res.loaded is False
        assert "not served" in res.reason

    def test_unload_is_noop(self):
        r = VllmRunner("http://localhost:8000", session=FakeSession())
        res = r.unload("anything")
        assert res.unloaded is False
        assert res.reason == "vllm_pinned_server"


# ── health ─────────────────────────────────────────────────────────────────


class TestHealth:
    def test_healthy_with_metrics(self):
        metrics = (
            "# HELP vllm:num_requests_running\n"
            "vllm:num_requests_running 3.0\n"
            'vllm:gpu_cache_usage_perc{model="m"} 0.42\n'
        )
        sess = FakeSession(
            get_map={
                "/health": _resp(200),
                "/v1/models": _resp(200, {"data": [{"id": "m"}]}),
                "/version": _resp(200, {"version": "0.6.3"}),
                "/metrics": _resp(200, text=metrics),
            }
        )
        r = VllmRunner("http://localhost:8000", session=sess)
        h = r.health()
        assert h.reachable is True
        assert h.version == "0.6.3"
        assert h.loaded_models == ["m"]
        assert h.extras["num_requests_running"] == 3.0
        assert h.extras["gpu_cache_usage_perc"] == 0.42

    def test_unreachable(self):
        sess = FakeSession(get_map={})  # everything 404
        r = VllmRunner("http://localhost:8000", session=sess)
        h = r.health()
        assert h.reachable is False
        assert h.loaded_models == []

    def test_falls_back_to_v1_models_when_no_health(self):
        # Server without /health (404) but /v1/models works → still alive.
        sess = FakeSession(get_map={"/v1/models": _resp(200, {"data": [{"id": "m"}]})})
        r = VllmRunner("http://localhost:8000", session=sess)
        assert r.health().reachable is True
