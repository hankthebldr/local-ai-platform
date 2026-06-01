"""Tests for detect_runners() — RunnerRegistry startup wiring.

Phase 3 of gpu-runner-abstraction.

Ollama is always registered; vLLM is registered when ENCLAVE_VLLM_BASE_URLS
is set. STRICT_RUNNER_DETECTION turns an unreachable configured vLLM into a
hard error. These tests stub VllmRunner.health so nothing touches a network.
"""

from __future__ import annotations

import pytest

from api.services.runner import RunnerKind, RunnerHealth
from api.services import runner_detection
from api.services.runner_detection import detect_runners


@pytest.fixture
def fake_ollama():
    from unittest.mock import MagicMock

    svc = MagicMock()
    svc.host = "http://localhost:11434"
    svc.get_version.return_value = "0.24.0"
    svc.health_check.return_value = True
    return svc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Ensure a pristine env for every test.
    for var in (
        "ENCLAVE_VLLM_BASE_URLS",
        "ENCLAVE_PREFERRED_RUNNER",
        "STRICT_RUNNER_DETECTION",
        "ENCLAVE_VLLM_MAX_CONCURRENT",
    ):
        monkeypatch.delenv(var, raising=False)


def _stub_vllm_health(monkeypatch, reachable: bool):
    def fake_health(self):
        return RunnerHealth(
            reachable=reachable,
            version="0.6.3" if reachable else None,
            loaded_models=["served-model"] if reachable else [],
            extras={},
        )

    monkeypatch.setattr("api.services.runner_impl.vllm.VllmRunner.health", fake_health)


# ── Ollama always present ──────────────────────────────────────────────────


def test_ollama_always_registered(fake_ollama):
    reg = detect_runners(ollama_service=fake_ollama)
    assert RunnerKind.OLLAMA in reg.kinds()
    assert RunnerKind.VLLM not in reg.kinds()


def test_singleton_installed(fake_ollama):
    from api.services.runner_registry import get_current_registry

    detect_runners(ollama_service=fake_ollama)
    assert RunnerKind.OLLAMA in get_current_registry().kinds()


# ── vLLM opt-in ─────────────────────────────────────────────────────────────


def test_vllm_registered_when_configured_and_reachable(monkeypatch, fake_ollama):
    monkeypatch.setenv("ENCLAVE_VLLM_BASE_URLS", "http://localhost:8000")
    _stub_vllm_health(monkeypatch, reachable=True)
    reg = detect_runners(ollama_service=fake_ollama)
    assert reg.kinds() == {RunnerKind.OLLAMA, RunnerKind.VLLM}


def test_vllm_registered_optimistically_when_unreachable(monkeypatch, fake_ollama):
    # Lenient (default): register even if down, so dispatch surfaces a clear
    # connection error rather than RunnerNotConfigured.
    monkeypatch.setenv("ENCLAVE_VLLM_BASE_URLS", "http://localhost:8000")
    _stub_vllm_health(monkeypatch, reachable=False)
    reg = detect_runners(ollama_service=fake_ollama)
    assert RunnerKind.VLLM in reg.kinds()


def test_strict_raises_on_unreachable_vllm(monkeypatch, fake_ollama):
    monkeypatch.setenv("ENCLAVE_VLLM_BASE_URLS", "http://localhost:8000")
    monkeypatch.setenv("STRICT_RUNNER_DETECTION", "true")
    _stub_vllm_health(monkeypatch, reachable=False)
    with pytest.raises(RuntimeError, match="unreachable"):
        detect_runners(ollama_service=fake_ollama)


def test_first_url_used_for_multiple(monkeypatch, fake_ollama):
    monkeypatch.setenv("ENCLAVE_VLLM_BASE_URLS", "http://a:8000, http://b:8000")
    _stub_vllm_health(monkeypatch, reachable=True)
    reg = detect_runners(ollama_service=fake_ollama)
    assert reg.get(RunnerKind.VLLM).base_url == "http://a:8000/v1"


# ── preferred runner ────────────────────────────────────────────────────────


def test_preferred_runner_recorded(monkeypatch, fake_ollama):
    monkeypatch.setenv("ENCLAVE_VLLM_BASE_URLS", "http://localhost:8000")
    monkeypatch.setenv("ENCLAVE_PREFERRED_RUNNER", "vllm")
    _stub_vllm_health(monkeypatch, reachable=True)
    reg = detect_runners(ollama_service=fake_ollama)
    assert reg.preferred_runner == RunnerKind.VLLM


def test_preferred_runner_ignored_when_not_registered(monkeypatch, fake_ollama):
    # Prefer vllm but it's not configured → preference dropped, no crash.
    monkeypatch.setenv("ENCLAVE_PREFERRED_RUNNER", "vllm")
    reg = detect_runners(ollama_service=fake_ollama)
    assert reg.preferred_runner is None


def test_invalid_preferred_runner_ignored(monkeypatch, fake_ollama):
    monkeypatch.setenv("ENCLAVE_PREFERRED_RUNNER", "rocketship")
    reg = detect_runners(ollama_service=fake_ollama)
    assert reg.preferred_runner is None
