#!/usr/bin/env python3
"""
Model Registry Router Tests — /api/models runner-aware selection (C1).

Stands up an isolated RunnerRegistry with a reachable fake vLLM and an
unreachable fake Ollama, installs it as the process singleton, and asserts the
endpoint groups by runner, builds UI-ready options, and picks a sane default.
"""

import os
import importlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.services.runner import RunnerKind, RunnerHealth, ModelInfo, Quant
from api.services.runner_registry import RunnerRegistry, _set_current


class _FakeRunner:
    """Minimal Runner satisfying what the router reads."""

    def __init__(self, kind, reachable, models, base_url):
        self.name = kind
        self.base_url = base_url
        self.supports_continuous_batching = kind == RunnerKind.VLLM
        self.supports_keep_alive = kind == RunnerKind.OLLAMA
        self.supports_quantizations = (
            [Quant.NVFP4, Quant.FP8] if kind == RunnerKind.VLLM else [Quant.GGUF_Q4_K_M]
        )
        self._reachable = reachable
        self._models = models

    def health(self):
        return RunnerHealth(reachable=self._reachable, version="test-1")

    def list_models(self):
        return self._models


@pytest.fixture(scope="module")
def client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


def _install_registry():
    reg = RunnerRegistry()
    reg.register(
        _FakeRunner(
            RunnerKind.VLLM,
            reachable=True,
            models=[
                ModelInfo(
                    id="qwen3-coder-30b-a3b",
                    family="qwen",
                    quant=Quant.NVFP4,
                    context_window=32768,
                )
            ],
            base_url="http://127.0.0.1:8000/v1",
        )
    )
    reg.register(
        _FakeRunner(
            RunnerKind.OLLAMA, reachable=False, models=[], base_url="http://127.0.0.1:11434"
        )
    )
    reg.preferred_runner = RunnerKind.VLLM
    _set_current(reg)
    return reg


def test_models_grouped_by_runner(client):
    _install_registry()
    resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    by_kind = {r["runner"]: r for r in data["runners"]}
    assert by_kind["vllm"]["reachable"] is True
    assert by_kind["ollama"]["reachable"] is False
    assert by_kind["vllm"]["capabilities"]["continuous_batching"] is True
    assert "nvfp4" in by_kind["vllm"]["capabilities"]["quantizations"]


def test_options_are_ui_ready(client):
    _install_registry()
    data = client.get("/api/models").json()
    vllm_opt = next(o for o in data["options"] if o["runner"] == "vllm")
    assert vllm_opt["value"] == "vllm/qwen3-coder-30b-a3b"
    assert vllm_opt["model"] == "qwen3-coder-30b-a3b"
    assert vllm_opt["context_window"] == 32768
    assert "NVFP4" in vllm_opt["label"]


def test_default_prefers_reachable_preferred_runner(client):
    _install_registry()
    data = client.get("/api/models").json()
    assert data["preferred_runner"] == "vllm"
    assert data["default"] == "vllm/qwen3-coder-30b-a3b"


def test_default_prefers_vllm_and_skips_embeddings_when_no_preferred(client):
    """No pinned preferred runner + reachable Ollama (embedding first) and vLLM:
    default must be the vLLM chat model, never the embedding model."""
    reg = RunnerRegistry()
    reg.register(
        _FakeRunner(
            RunnerKind.OLLAMA,
            reachable=True,
            models=[
                ModelInfo(id="nomic-embed-text:latest", family="nomic-bert"),
                ModelInfo(id="hermes3:8b", family="llama"),
            ],
            base_url="http://127.0.0.1:11434",
        )
    )
    reg.register(
        _FakeRunner(
            RunnerKind.VLLM,
            reachable=True,
            models=[ModelInfo(id="qwen3-coder-30b-a3b", family="qwen", context_window=32768)],
            base_url="http://127.0.0.1:8000/v1",
        )
    )
    # no reg.preferred_runner set
    _set_current(reg)
    data = client.get("/api/models").json()
    assert data["preferred_runner"] is None
    assert data["default"] == "vllm/qwen3-coder-30b-a3b"


def test_503_when_registry_absent(client):
    import api.services.runner_registry as rr

    rr._current_registry = None  # simulate detect_runners never running
    resp = client.get("/api/models")
    assert resp.status_code == 503
