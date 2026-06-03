#!/usr/bin/env python3
"""Tests for Documents router"""

import os
import pytest
import importlib
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

pytestmark = pytest.mark.rag
import io


class _FakeEmbedding:
    def __init__(self, dim=4):
        self._dim = dim

    def embed(self, texts):
        return [[0.1] * self._dim for _ in texts]

    def embed_query(self, text):
        return [0.1] * self._dim

    def get_backend(self):
        return "fake"

    def get_model(self):
        return "fake-model"

    def get_dimension(self):
        return self._dim

    def describe(self):
        return {"backend": "fake", "model": "fake-model", "dimension": self._dim}


@pytest.fixture(scope="module")
def client():
    tmpdir = tempfile.mkdtemp()
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"

    # Pre-inject a fake embedding service by monkeypatching the module
    import api.services.embedding_service as emb_mod

    original = emb_mod.EmbeddingService

    class PatchedEmbedding(_FakeEmbedding):
        def __init__(self, *args, **kwargs):
            super().__init__()

    emb_mod.EmbeddingService = PatchedEmbedding

    # Force data_dir to tmpdir
    os.environ["RAG_DATA_DIR"] = tmpdir
    import api.services.document_service as doc_mod

    _orig_init = doc_mod.DocumentService.__init__

    def patched_init(self, embedding_service, data_dir="data/rag", **kw):
        _orig_init(self, embedding_service, data_dir=tmpdir, **kw)

    doc_mod.DocumentService.__init__ = patched_init

    import api.middleware

    importlib.reload(api.middleware)
    import api.routers.documents

    importlib.reload(api.routers.documents)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    yield TestClient(app)

    emb_mod.EmbeddingService = original
    doc_mod.DocumentService.__init__ = _orig_init
    shutil.rmtree(tmpdir)


class TestDocumentsRouter:
    def test_list_empty(self, client):
        resp = client.get("/api/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_upload_and_list(self, client):
        content = b"Hello world document content."
        files = {"file": ("test.txt", io.BytesIO(content), "text/plain")}
        resp = client.post("/api/documents", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.txt"

        resp = client.get("/api/documents")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_upload_unsupported_extension(self, client):
        files = {"file": ("bad.xyz", io.BytesIO(b"x"), "application/octet-stream")}
        resp = client.post("/api/documents", files=files)
        assert resp.status_code == 400

    def test_get_nonexistent(self, client):
        resp = client.get("/api/documents/doc_nonexistent")
        assert resp.status_code == 404

    def test_stats(self, client):
        resp = client.get("/api/documents/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_documents" in data
        assert "embedding" in data

    def test_search(self, client):
        content = b"Some content about sandboxes."
        files = {"file": ("sb.txt", io.BytesIO(content), "text/plain")}
        client.post("/api/documents", files=files)
        resp = client.post(
            "/api/documents/search", json={"query": "sandbox", "top_k": 3}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data


class TestChatRagIntegration:
    def test_chat_accepts_rag_flag(self, client):
        # Upload a doc first
        import io

        files = {
            "file": (
                "facts.txt",
                io.BytesIO(b"The capital of France is Paris."),
                "text/plain",
            )
        }
        client.post("/api/documents", files=files)

        # Mock Ollama chat call

        mock_ollama = MagicMock()
        mock_ollama.status_code = 200
        mock_ollama.json.return_value = {
            "message": {"role": "assistant", "content": "Paris."},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        # chat.py binds `_rag_service` at import time (`from .documents import
        # rag_service as _rag_service`). The module fixture reloads `documents`
        # with a fake-backed rag_service but not `chat`, so chat._rag_service can
        # be a stale real (Ollama-bound) service depending on suite collection
        # order. Pin it to the fresh fake-backed one for this test (auto-reverts).
        import api.routers.chat as chat_mod
        import api.routers.documents as doc_mod

        with (
            patch.object(chat_mod, "_rag_service", doc_mod.rag_service),
            patch(
                "api.services.ollama_service.requests.post", return_value=mock_ollama
            ),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [
                        {"role": "user", "content": "What is the capital of France?"}
                    ],
                    "rag": True,
                    "rag_top_k": 3,
                    "tools": False,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # rag_sources should be present when retrieval found results
            assert "rag_sources" in data or data.get("rag_sources") == []
