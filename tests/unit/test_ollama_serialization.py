"""Tests for the global LLM serialization guarantee in OllamaService.

Two LLM calls against a CPU-only Ollama daemon must never overlap —
loading a second GGUF alongside the first thrashes the L2/L3 cache and
makes BOTH calls slower than running them serially. The semaphore in
ollama_service.py is what enforces this; these tests pin the
invariant.
"""

from __future__ import annotations

import threading
import time

import pytest

from api.services import ollama_service
from api.services.ollama_service import OllamaService, _LLM_SEMAPHORE


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_chat_requests_include_keep_alive(monkeypatch):
    """Every chat request should carry a keep_alive directive so
    adjacent same-model steps reuse the loaded GGUF."""
    svc = OllamaService(host="http://fake")
    captured = {}

    def fake_post(url, json=None, timeout=None, **kw):
        captured["json"] = json
        return _FakeResponse(
            {
                "message": {"content": "hello"},
                "prompt_eval_count": 1,
                "eval_count": 2,
            }
        )

    monkeypatch.setattr(ollama_service.requests, "post", fake_post)
    svc.chat(model="m", messages=[{"role": "user", "content": "hi"}])
    assert "keep_alive" in captured["json"]
    assert captured["json"]["keep_alive"]  # non-empty


def test_chat_passes_explicit_keep_alive(monkeypatch):
    svc = OllamaService(host="http://fake")
    captured = {}

    def fake_post(url, json=None, **kw):
        captured["json"] = json
        return _FakeResponse(
            {
                "message": {"content": "ok"},
                "prompt_eval_count": 1,
                "eval_count": 2,
            }
        )

    monkeypatch.setattr(ollama_service.requests, "post", fake_post)
    svc.chat(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        keep_alive="1h",
    )
    assert captured["json"]["keep_alive"] == "1h"


def test_concurrent_chats_are_serialized(monkeypatch):
    """Two simultaneous chat() calls must NOT overlap inside requests.post.

    We instrument the fake transport to assert at-most-one-in-flight, and
    spin up two threads. If the semaphore is bypassed the assertion fires.
    """
    svc = OllamaService(host="http://fake")
    in_flight = 0
    in_flight_lock = threading.Lock()
    peak = 0

    def fake_post(url, json=None, timeout=None, **kw):
        nonlocal in_flight, peak
        with in_flight_lock:
            in_flight += 1
            peak = max(peak, in_flight)
        # Hold the "model" briefly so the second thread has time to race in
        time.sleep(0.05)
        with in_flight_lock:
            in_flight -= 1
        return _FakeResponse(
            {
                "message": {"content": "ok"},
                "prompt_eval_count": 1,
                "eval_count": 1,
            }
        )

    monkeypatch.setattr(ollama_service.requests, "post", fake_post)

    def call():
        svc.chat(model="m", messages=[{"role": "user", "content": "x"}])

    t1 = threading.Thread(target=call)
    t2 = threading.Thread(target=call)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert peak == 1, f"expected serialized LLM calls, observed peak={peak}"


def test_semaphore_is_released_on_exception(monkeypatch):
    """A failed HTTP request must still release the semaphore so the
    next caller isn't blocked forever."""
    svc = OllamaService(host="http://fake")

    def boom(url, json=None, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(ollama_service.requests, "post", boom)
    with pytest.raises(Exception):
        svc.chat(model="m", messages=[{"role": "user", "content": "x"}])
    # If the semaphore leaked, acquire(blocking=False) returns False.
    acquired = _LLM_SEMAPHORE.acquire(blocking=False)
    assert acquired, "semaphore was not released after exception"
    _LLM_SEMAPHORE.release()


def test_chat_fallback_to_generate_does_not_deadlock(monkeypatch):
    """When /api/chat returns empty, OllamaService falls back to
    /api/generate. The fallback runs while the chat call still holds
    the semaphore, so it must use the inner path (no second acquire)."""
    svc = OllamaService(host="http://fake")
    calls = []

    def fake_post(url, json=None, timeout=None, **kw):
        calls.append(url)
        if url.endswith("/api/chat"):
            # Empty content + no tool_calls triggers the fallback
            return _FakeResponse(
                {
                    "message": {"content": ""},
                    "prompt_eval_count": 0,
                    "eval_count": 0,
                }
            )
        # /api/generate
        return _FakeResponse(
            {
                "response": "filled-in",
                "prompt_eval_count": 3,
                "eval_count": 4,
            }
        )

    monkeypatch.setattr(ollama_service.requests, "post", fake_post)
    # If the fallback re-acquired the (1-permit) semaphore we'd deadlock.
    # Use a short timeout to catch that case loudly.
    done = threading.Event()
    result = {}

    def go():
        result["v"] = svc.chat(model="m", messages=[{"role": "user", "content": "x"}])
        done.set()

    t = threading.Thread(target=go)
    t.start()
    finished = done.wait(timeout=5)
    assert finished, "chat → generate fallback deadlocked on the LLM semaphore"
    assert result["v"]["content"] == "filled-in"
    assert any(u.endswith("/api/chat") for u in calls)
    assert any(u.endswith("/api/generate") for u in calls)
