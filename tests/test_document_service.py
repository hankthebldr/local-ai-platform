#!/usr/bin/env python3
"""Tests for DocumentService — lifecycle and ChromaDB integration"""

import os
import pytest
import tempfile
import shutil
from unittest.mock import MagicMock, patch


class _FakeEmbedding:
    """Deterministic fake for EmbeddingService — no network or model."""
    def __init__(self, dim=4):
        self._dim = dim

    def embed(self, texts):
        return [[float(i) / 10] * self._dim for i, _ in enumerate(texts)]

    def embed_query(self, text):
        return [0.5] * self._dim

    def get_backend(self):
        return "fake"

    def get_model(self):
        return "fake-model"

    def get_dimension(self):
        return self._dim

    def describe(self):
        return {"backend": "fake", "model": "fake-model", "dimension": self._dim}


@pytest.fixture
def tmp_rag_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def doc_svc(tmp_rag_dir):
    from api.services.document_service import DocumentService
    svc = DocumentService(embedding_service=_FakeEmbedding(), data_dir=tmp_rag_dir)
    yield svc


class TestUpload:
    def test_upload_txt_creates_record(self, doc_svc):
        result = doc_svc.upload("notes.txt", b"Hello world. This is a test document.")
        assert result["id"].startswith("doc_")
        assert result["filename"] == "notes.txt"
        assert result["status"] == "indexed"
        assert result["chunk_count"] >= 1

    def test_upload_md_parsed(self, doc_svc):
        content = b"# Title\n\nParagraph one.\n\nParagraph two."
        result = doc_svc.upload("readme.md", content)
        assert result["status"] == "indexed"
        assert result["chunk_count"] >= 1

    def test_unsupported_extension_rejected(self, doc_svc):
        from api.services.document_service import UnsupportedFormat
        with pytest.raises(UnsupportedFormat):
            doc_svc.upload("binary.zip", b"\x00\x01\x02")


class TestListAndGet:
    def test_list_empty(self, doc_svc):
        assert doc_svc.list_documents() == []

    def test_list_after_upload(self, doc_svc):
        doc_svc.upload("a.txt", b"content a")
        doc_svc.upload("b.txt", b"content b")
        docs = doc_svc.list_documents()
        assert len(docs) == 2
        names = sorted([d["filename"] for d in docs])
        assert names == ["a.txt", "b.txt"]

    def test_get_document(self, doc_svc):
        rec = doc_svc.upload("a.txt", b"content a")
        fetched = doc_svc.get_document(rec["id"])
        assert fetched["id"] == rec["id"]
        assert fetched["filename"] == "a.txt"

    def test_get_missing_returns_none(self, doc_svc):
        assert doc_svc.get_document("doc_nonexistent") is None


class TestDelete:
    def test_delete_removes_record(self, doc_svc):
        rec = doc_svc.upload("a.txt", b"content")
        assert doc_svc.delete_document(rec["id"]) is True
        assert doc_svc.get_document(rec["id"]) is None
        assert doc_svc.list_documents() == []

    def test_delete_missing_returns_false(self, doc_svc):
        assert doc_svc.delete_document("doc_nonexistent") is False


class TestStats:
    def test_stats_empty(self, doc_svc):
        s = doc_svc.stats()
        assert s["total_documents"] == 0
        assert s["total_chunks"] == 0
        assert s["embedding"]["backend"] == "fake"

    def test_stats_populated(self, doc_svc):
        doc_svc.upload("a.txt", b"Content for document a." * 5)
        s = doc_svc.stats()
        assert s["total_documents"] == 1
        assert s["total_chunks"] >= 1
