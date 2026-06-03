#!/usr/bin/env python3
"""Tests for EmbeddingService — backend selection and binding"""

import pytest
from unittest.mock import patch, MagicMock


class TestBackendSelection:
    def test_ollama_bound_when_probe_succeeds(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}

        with patch(
            "api.services.embedding_service.requests.post", return_value=mock_resp
        ):
            svc = EmbeddingService(ollama, ollama_model="nomic-embed-text")
            assert svc.get_backend() == "ollama"
            assert svc.get_model() == "nomic-embed-text"
            assert svc.get_dimension() == 3

    def test_explicit_backend_ollama(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.0] * 768}

        with patch(
            "api.services.embedding_service.requests.post", return_value=mock_resp
        ):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="test-model")
            assert svc.get_backend() == "ollama"
            assert svc.get_dimension() == 768

    def test_both_fail_raises(self):
        from api.services.embedding_service import (
            EmbeddingService,
            EmbeddingBackendUnavailable,
        )
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        with patch(
            "api.services.embedding_service.requests.post",
            side_effect=Exception("conn refused"),
        ):
            with patch(
                "api.services.embedding_service.EmbeddingService._load_sentence_transformer",
                side_effect=Exception("st fail"),
            ):
                with pytest.raises(EmbeddingBackendUnavailable):
                    EmbeddingService(ollama, backend="auto")


class TestEmbedding:
    def test_embed_returns_one_vector_per_input(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.5, 0.5, 0.5]}

        with patch(
            "api.services.embedding_service.requests.post", return_value=mock_resp
        ):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="m")
            vecs = svc.embed(["a", "b", "c"])
            assert len(vecs) == 3
            assert all(len(v) == 3 for v in vecs)

    def test_embed_query_returns_single_vector(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.1, 0.2]}

        with patch(
            "api.services.embedding_service.requests.post", return_value=mock_resp
        ):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="m")
            v = svc.embed_query("hello")
            assert v == [0.1, 0.2]


class TestDescribe:
    def test_describe_returns_dict(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.0] * 768}

        with patch(
            "api.services.embedding_service.requests.post", return_value=mock_resp
        ):
            svc = EmbeddingService(
                ollama, backend="ollama", ollama_model="nomic-embed-text"
            )
            d = svc.describe()
            assert d["backend"] == "ollama"
            assert d["model"] == "nomic-embed-text"
            assert d["dimension"] == 768


# ── Task 1.1: rebind-compatibility helpers ────────────────────────────────────

from api.services.embedding_service import normalized_family, collection_compatible


def test_normalized_family_strips_qualifiers():
    assert normalized_family("all-MiniLM-L6-v2") == "all-minilm-l6-v2"
    assert (
        normalized_family("sentence-transformers/all-MiniLM-L6-v2")
        == "all-minilm-l6-v2"
    )
    assert normalized_family("nomic-embed-text:latest") == "nomic-embed-text"


def test_collection_compatible_exact_match():
    meta = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(meta, dict(meta))
    assert ok is True and warning is None


def test_collection_compatible_strict_default_refuses_backend_switch():
    existing = {
        "backend": "sentence_transformers",
        "model": "all-MiniLM-L6-v2",
        "dimension": 384,
    }
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(existing, active)
    assert ok is False


def test_collection_compatible_lenient_allows_same_family(monkeypatch):
    monkeypatch.setenv("ENCLAVE_EMBEDDING_ALLOW_REBIND", "true")
    existing = {
        "backend": "sentence_transformers",
        "model": "all-MiniLM-L6-v2",
        "dimension": 384,
    }
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(existing, active)
    assert ok is True
    assert warning and "quality" in warning.lower()


def test_collection_compatible_lenient_still_refuses_dimension_change(monkeypatch):
    monkeypatch.setenv("ENCLAVE_EMBEDDING_ALLOW_REBIND", "true")
    existing = {"backend": "ollama", "model": "nomic-embed-text", "dimension": 768}
    active = {"backend": "onnx", "model": "all-MiniLM-L6-v2", "dimension": 384}
    ok, warning = collection_compatible(existing, active)
    assert ok is False


# ── Task 1.2: ONNX backend arm ────────────────────────────────────────────────

from api.services.embedding_service import EmbeddingService


def _service_with_stubbed_onnx(monkeypatch, ollama_up=False):
    """Build an EmbeddingService in auto mode with Ollama down and ONNX stubbed."""
    fake_encoder = MagicMock()
    fake_encoder.encode.return_value = [[0.1] * 384]
    fake_encoder.active_providers = ["CPUExecutionProvider"]

    monkeypatch.setattr(
        EmbeddingService,
        "_load_onnx_encoder",
        lambda self: setattr(self, "_onnx_instance", fake_encoder),
    )
    ollama = MagicMock()
    ollama.host = "http://127.0.0.1:11434"
    svc = EmbeddingService.__new__(EmbeddingService)  # bypass __init__ probing
    return svc, fake_encoder, ollama


def test_bind_onnx_sets_backend_and_dimension(monkeypatch):
    svc, fake_encoder, ollama = _service_with_stubbed_onnx(monkeypatch)
    svc._ollama = ollama
    svc._onnx_model = "all-MiniLM-L6-v2"
    svc._onnx_instance = None
    ok = svc._bind_onnx(raise_on_fail=True)
    assert ok is True
    assert svc.get_backend() == "onnx"
    assert svc.get_dimension() == 384
    assert svc.embed(["x"]) == [[0.1] * 384]


def test_runtime_info_includes_providers(monkeypatch):
    svc, fake_encoder, ollama = _service_with_stubbed_onnx(monkeypatch)
    svc._ollama = ollama
    svc._onnx_model = "all-MiniLM-L6-v2"
    svc._onnx_instance = None
    svc._bind_onnx(raise_on_fail=True)
    info = svc.runtime_info()
    assert info["providers"] == ["CPUExecutionProvider"]
    assert "providers" not in svc.describe()
