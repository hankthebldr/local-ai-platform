#!/usr/bin/env python3
"""Tests for EmbeddingService — backend selection and binding"""

import os
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

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
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

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="test-model")
            assert svc.get_backend() == "ollama"
            assert svc.get_dimension() == 768

    def test_both_fail_raises(self):
        from api.services.embedding_service import EmbeddingService, EmbeddingBackendUnavailable
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        with patch("api.services.embedding_service.requests.post", side_effect=Exception("conn refused")):
            with patch("api.services.embedding_service.EmbeddingService._load_sentence_transformer", side_effect=Exception("st fail")):
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

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
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

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
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

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="nomic-embed-text")
            d = svc.describe()
            assert d["backend"] == "ollama"
            assert d["model"] == "nomic-embed-text"
            assert d["dimension"] == 768
