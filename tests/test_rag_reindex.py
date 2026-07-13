#!/usr/bin/env python3
"""RAG dimension-change self-heal.

Reproduces the real incident: a Chroma collection built at 384-dim
(sentence-transformers) becomes unusable after the box switches to Ollama
nomic (768-dim). Default behavior hard-fails RAG init (safe, loud). With
ENCLAVE_EMBEDDING_AUTO_REINDEX=true the dead collection is dropped and
rebuilt empty at the active dimension so ingest works again.
"""

import shutil
import tempfile

import pytest

pytestmark = pytest.mark.rag


class _FakeEmbedding:
    def __init__(self, dim):
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


def _make(tmpdir, dim):
    from api.services.document_service import DocumentService

    return DocumentService(embedding_service=_FakeEmbedding(dim), data_dir=tmpdir)


def test_dim_change_hard_fails_by_default(monkeypatch):
    from api.services.embedding_service import EmbeddingBackendMismatch

    monkeypatch.delenv("ENCLAVE_EMBEDDING_AUTO_REINDEX", raising=False)
    tmpdir = tempfile.mkdtemp()
    try:
        # Build a 384-dim collection, then re-open with a 768-dim backend —
        # DocumentService eager-inits Chroma in __init__, so the mismatch
        # surfaces at construction.
        _make(tmpdir, 384).upload("a.txt", b"hello world")
        with pytest.raises(EmbeddingBackendMismatch):
            _make(tmpdir, 768)
    finally:
        shutil.rmtree(tmpdir)


def test_auto_reindex_rebuilds_and_ingest_works(monkeypatch):
    monkeypatch.setenv("ENCLAVE_EMBEDDING_AUTO_REINDEX", "true")
    tmpdir = tempfile.mkdtemp()
    try:
        _make(tmpdir, 384).upload("a.txt", b"stale 384-dim content")
        # New backend at 768 must self-heal instead of raising.
        svc = _make(tmpdir, 768)
        res = svc.upload("b.txt", b"fresh 768-dim content is ingestable")
        assert res.get("error") is None
        # Collection now reports the active dimension, empty of the stale doc.
        svc._init_chroma()
        assert svc._collection.metadata.get("dimension") == 768
    finally:
        shutil.rmtree(tmpdir)


def test_same_dim_reopen_is_untouched(monkeypatch):
    monkeypatch.delenv("ENCLAVE_EMBEDDING_AUTO_REINDEX", raising=False)
    tmpdir = tempfile.mkdtemp()
    try:
        _make(tmpdir, 384).upload("a.txt", b"content")
        svc = _make(tmpdir, 384)
        svc._init_chroma()  # no mismatch, no raise
        assert svc._collection.metadata.get("dimension") == 384
    finally:
        shutil.rmtree(tmpdir)
