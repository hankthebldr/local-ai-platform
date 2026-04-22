#!/usr/bin/env python3
"""Tests for RAGService — retrieval and context formatting"""

import pytest
import tempfile
import shutil

pytestmark = pytest.mark.rag


class _FakeEmbedding:
    def __init__(self, dim=4):
        self._dim = dim

    def embed(self, texts):
        return [[0.1, 0.2, 0.3, 0.4]] * len(texts)

    def embed_query(self, text):
        return [0.1, 0.2, 0.3, 0.4]

    def get_backend(self): return "fake"
    def get_model(self): return "fake-model"
    def get_dimension(self): return self._dim
    def describe(self): return {"backend": "fake", "model": "fake-model", "dimension": self._dim}


@pytest.fixture
def populated_rag():
    from api.services.document_service import DocumentService
    from api.services.rag_service import RAGService

    tmpdir = tempfile.mkdtemp()
    embed = _FakeEmbedding()
    doc_svc = DocumentService(embedding_service=embed, data_dir=tmpdir)
    doc_svc.upload("a.txt", b"The quick brown fox jumps over the lazy dog.")
    doc_svc.upload("b.txt", b"Python is a high-level programming language.")
    rag = RAGService(embedding_service=embed, document_service=doc_svc)
    yield rag, doc_svc
    shutil.rmtree(tmpdir)


class TestSearch:
    def test_search_returns_results_dict(self, populated_rag):
        rag, _ = populated_rag
        out = rag.search("fox", top_k=3)
        assert "query" in out
        assert "results" in out
        assert "total" in out
        assert out["query"] == "fox"

    def test_search_empty_collection(self):
        import tempfile
        from api.services.document_service import DocumentService
        from api.services.rag_service import RAGService
        tmpdir = tempfile.mkdtemp()
        try:
            embed = _FakeEmbedding()
            doc_svc = DocumentService(embedding_service=embed, data_dir=tmpdir)
            rag = RAGService(embedding_service=embed, document_service=doc_svc)
            out = rag.search("anything", top_k=5)
            assert out["total"] == 0
            assert out["results"] == []
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_search_result_shape(self, populated_rag):
        rag, _ = populated_rag
        out = rag.search("anything", top_k=2)
        if out["results"]:
            r = out["results"][0]
            assert "doc_id" in r
            assert "filename" in r
            assert "chunk_index" in r
            assert "text" in r
            assert "score" in r


class TestFormatContext:
    def test_format_context_produces_string(self, populated_rag):
        rag, _ = populated_rag
        out = rag.search("anything", top_k=2)
        formatted = rag.format_context(out)
        assert isinstance(formatted, str)
        assert "Retrieved context" in formatted

    def test_format_context_empty(self, populated_rag):
        rag, _ = populated_rag
        formatted = rag.format_context({"query": "x", "results": [], "total": 0})
        assert formatted == ""

    def test_format_context_numbered(self, populated_rag):
        rag, _ = populated_rag
        out = rag.search("anything", top_k=2)
        formatted = rag.format_context(out)
        if out["total"] > 0:
            assert "[1]" in formatted

    def test_format_context_respects_max_chars(self, populated_rag):
        rag, _ = populated_rag
        out = rag.search("anything", top_k=5)
        formatted = rag.format_context(out, max_chars=100)
        assert len(formatted) <= 300
