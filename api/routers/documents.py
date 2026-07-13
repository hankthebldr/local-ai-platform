#!/usr/bin/env python3
"""
Documents Router — REST endpoints for document management + retrieval preview

Exports `rag_service` and `document_service` as module-level instances
so other modules (including plugins) can share them.
"""

import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.embedding_service import EmbeddingService
from ..services.document_service import DocumentService, UnsupportedFormat
from ..services.rag_service import RAGService

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Module-level instances so plugins and other routers can import them.
# NOTE (U13 heal): these start as ``None`` when the embedding backend is absent
# at import time. ``_ensure_rag()`` re-binds them in place once the backend
# comes up, so a mid-session stop/start of the embedding backend heals every
# consumer WITHOUT a process restart. Importers must read these through
# ``_ensure_rag()`` (or re-resolve the attribute at call time) — never capture
# the value at import time.
_embedding_service = None
document_service = None
rag_service = None

# Lazy re-init state. Construction is throttled so a persistently-down backend
# can't turn every request into a slow probe (embedding init can touch the
# network / spawn a local model). One attempt per window, single-flighted.
_RAG_REINIT_THROTTLE_SECONDS = 30.0
_rag_init_lock = threading.Lock()
_rag_last_attempt = 0.0


def _init_rag_pipeline():
    """Construct the (embedding, document, rag) singleton trio.

    Raises when the embedding backend is unavailable — the caller decides
    whether that's a fatal boot error or a deferred lazy retry.
    """
    ollama = OllamaService(os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    embedding = EmbeddingService(ollama)
    docsvc = DocumentService(embedding)
    ragsvc = RAGService(embedding, docsvc)
    return embedding, docsvc, ragsvc


def _ensure_rag():
    """Return the live ``RAGService``, lazily (re)initializing if the backend
    was absent before but has since come up. Returns ``None`` while the backend
    stays unavailable.

    Rebinds the module globals on success so every importer that reads
    ``documents.rag_service`` / ``document_service`` — the audited set:
    chat.py, research.py, rag_ingest.py, plugins/rag/tools/search.py — observes
    the healed instances on their next call. Throttled + single-flighted so a
    down backend costs at most one construction attempt per window.
    """
    global _embedding_service, document_service, rag_service, _rag_last_attempt
    if rag_service is not None:
        return rag_service
    now = time.monotonic()
    with _rag_init_lock:
        # Re-check under the lock — another thread may have healed it.
        if rag_service is not None:
            return rag_service
        if now - _rag_last_attempt < _RAG_REINIT_THROTTLE_SECONDS:
            return None
        _rag_last_attempt = now
        try:
            emb, docsvc, ragsvc = _init_rag_pipeline()
        except Exception as e:  # noqa: BLE001 — backend still down; retry later
            logger.warning(f"RAG pipeline re-init deferred (backend down?): {e}")
            return None
        _embedding_service, document_service, rag_service = emb, docsvc, ragsvc
        logger.info(f"RAG pipeline healed: backend={emb.get_backend()}")
        return rag_service


# Eager first attempt at import so a healthy boot logs "ready" and warm callers
# never pay the lazy probe. Failure is non-fatal — _ensure_rag() retries.
try:
    _embedding_service, document_service, rag_service = _init_rag_pipeline()
    logger.info(f"RAG pipeline ready: backend={_embedding_service.get_backend()}")
except Exception as e:
    _rag_last_attempt = time.monotonic()
    logger.warning(f"RAG pipeline not initialized (will retry lazily): {e}")


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    top_k: Optional[int] = Field(5, description="Number of chunks to return")


def _require_rag():
    # Lazily heal before refusing — a backend that came up mid-session recovers
    # here without a process restart.
    if _ensure_rag() is None:
        raise HTTPException(
            status_code=503,
            detail="RAG pipeline unavailable. Check embedding backend configuration.",
        )


@router.get("")
async def list_docs():
    _require_rag()
    return document_service.list_documents()


@router.post("")
async def upload_doc(file: UploadFile = File(...)):
    _require_rag()
    content = await file.read()
    try:
        record = document_service.upload(file.filename, content)
    except UnsupportedFormat as e:
        raise HTTPException(status_code=400, detail=str(e))
    return record


@router.get("/stats")
async def doc_stats():
    _require_rag()
    return document_service.stats()


@router.post("/search")
async def search_docs(body: SearchRequest):
    _require_rag()
    return rag_service.search(query=body.query, top_k=body.top_k)


# Alias: /query → /search. The dashboard and external scripts historically
# tried both spellings; /search is canonical, but /query is a natural-feeling
# verb for retrieval and was returning 405. Keep both routes wired to the
# same handler so external callers don't need to know the canonical name.
@router.post("/query")
async def query_docs(body: SearchRequest):
    return await search_docs(body)


@router.get("/{doc_id}")
async def get_doc(doc_id: str):
    _require_rag()
    doc = document_service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str):
    _require_rag()
    if not document_service.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "id": doc_id}


@router.post("/{doc_id}/reindex")
async def reindex_doc(doc_id: str):
    _require_rag()
    rec = document_service.reindex(doc_id)
    if rec is None:
        raise HTTPException(
            status_code=404, detail="Document not found or raw file missing"
        )
    return rec
