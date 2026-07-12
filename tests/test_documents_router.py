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


def _mock_ollama_response(content="ok"):
    """A MagicMock standing in for requests.post() to Ollama's /api/chat."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 10,
        "eval_count": 5,
    }
    return m


class _SentinelRag:
    """A RAG service returning a uniquely identifiable result.

    Used to prove the chat path invoked *this* instance — resolved live from
    api.routers.documents at request time — rather than a value the chat
    module captured at import time. If chat.py still did
    `from .documents import rag_service as _rag_service`, swapping
    documents.rag_service for this sentinel would NOT be observed and
    `.searched` would stay False.
    """

    def __init__(self, tag):
        self.tag = tag
        self.searched = False

    def search(self, query, top_k=5):
        self.searched = True
        return {
            "query": query,
            "total": 1,
            "results": [{"id": f"sentinel-{self.tag}", "text": query, "score": 1.0}],
        }

    def format_context(self, results):
        return f"[SENTINEL {self.tag}] context"


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
        from unittest.mock import patch, MagicMock

        mock_ollama = MagicMock()
        mock_ollama.status_code = 200
        mock_ollama.json.return_value = {
            "message": {"role": "assistant", "content": "Paris."},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch(
            "api.services.ollama_service.requests.post", return_value=mock_ollama
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

    def test_chat_rag_uses_live_rag_service(self, client):
        """Regression: the chat RAG path must resolve documents.rag_service at
        call time, not capture it at import time.

        Reassigning documents.rag_service (as a module reload or a runtime
        re-init does) must be observed by chat.py. The previous
        `from .documents import rag_service as _rag_service` captured the
        import-time instance and went stale — an order-dependent failure that
        had to be worked around in the test rather than fixed at the source.
        """
        import api.routers.documents as docs_mod

        sentinel = _SentinelRag("rag1")
        original = docs_mod.rag_service
        docs_mod.rag_service = sentinel  # simulate re-init AFTER chat imported
        try:
            with patch(
                "api.services.ollama_service.requests.post",
                return_value=_mock_ollama_response("Paris."),
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "test-model",
                        "messages": [{"role": "user", "content": "capital of France?"}],
                        "rag": True,
                        "rag_top_k": 3,
                        "tools": False,
                    },
                )

            assert resp.status_code == 200
            # The live (sentinel) service must have handled retrieval. If chat
            # held a stale binding, sentinel.search is never called.
            assert (
                sentinel.searched is True
            ), "chat used a stale rag_service, not the live documents.rag_service"
            data = resp.json()
            assert data["rag_sources"] == [
                {"id": "sentinel-rag1", "text": "capital of France?", "score": 1.0}
            ]
        finally:
            docs_mod.rag_service = original

    def test_chat_uses_live_context_and_profile_singletons(self, client):
        """Consistency: context_store and profile_service share the same
        stale-binding class as rag_service and must also be resolved live.
        """
        import api.routers.context as ctx_mod
        import api.routers.profiles as prof_mod

        ctx_spy = MagicMock(wraps=ctx_mod.context_store)
        prof_spy = MagicMock(wraps=prof_mod.profile_service)
        orig_ctx, orig_prof = ctx_mod.context_store, prof_mod.profile_service
        ctx_mod.context_store = ctx_spy
        prof_mod.profile_service = prof_spy
        try:
            with patch(
                "api.services.ollama_service.requests.post",
                return_value=_mock_ollama_response(),
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "test-model",
                        "messages": [{"role": "user", "content": "hi"}],
                        "tools": False,
                    },
                )

            assert resp.status_code == 200
            assert ctx_spy.get.called, "chat used a stale context_store"
            assert prof_spy.resolve.called, "chat used a stale profile_service"
        finally:
            ctx_mod.context_store = orig_ctx
            prof_mod.profile_service = orig_prof


class TestLazyRagHeal:
    """U13: _ensure_rag() lazily re-initializes the pipeline when the embedding
    backend was absent at import time but comes up mid-session — no restart."""

    def test_ensure_rag_returns_live_without_reinit(self, monkeypatch):
        import api.routers.documents as docs

        sentinel = object()
        monkeypatch.setattr(docs, "rag_service", sentinel)

        def boom():
            raise AssertionError("must not re-init when already live")

        monkeypatch.setattr(docs, "_init_rag_pipeline", boom)
        assert docs._ensure_rag() is sentinel

    def test_ensure_rag_heals_after_backend_returns(self, monkeypatch):
        import api.routers.documents as docs

        # Simulate a backend-absent boot: all three singletons are None.
        monkeypatch.setattr(docs, "rag_service", None)
        monkeypatch.setattr(docs, "document_service", None)
        monkeypatch.setattr(docs, "_embedding_service", None)
        monkeypatch.setattr(docs, "_rag_last_attempt", 0.0)

        calls = {"n": 0}
        healed_rag = object()
        healed_doc = object()
        emb = MagicMock()
        emb.get_backend.return_value = "fake"

        def fake_init():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("embedding backend down")
            return emb, healed_doc, healed_rag

        monkeypatch.setattr(docs, "_init_rag_pipeline", fake_init)

        # First attempt: backend still down → None, globals untouched.
        assert docs._ensure_rag() is None
        assert docs.rag_service is None
        assert calls["n"] == 1

        # Within the throttle window → NO second construction attempt.
        assert docs._ensure_rag() is None
        assert calls["n"] == 1

        # Throttle elapses (force last-attempt far in the past) and the backend
        # is now up → heals AND rebinds the module globals importers read.
        monkeypatch.setattr(docs, "_rag_last_attempt", 0.0)
        result = docs._ensure_rag()
        assert result is healed_rag
        assert docs.rag_service is healed_rag
        assert docs.document_service is healed_doc
        assert docs._embedding_service is emb
        assert calls["n"] == 2
