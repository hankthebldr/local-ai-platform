#!/usr/bin/env python3
"""
Documents Router — REST endpoints for document management + retrieval preview

Exports `rag_service` and `document_service` as module-level instances
so other modules (including plugins) can share them.
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.ollama_service import OllamaService
from ..services.embedding_service import EmbeddingService
from ..services.document_service import DocumentService, UnsupportedFormat
from ..services.rag_service import RAGService

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Module-level instances so plugins and other routers can import them
_ollama = OllamaService(os.getenv("OLLAMA_HOST", "http://localhost:11434"))

try:
    _embedding_service = EmbeddingService(_ollama)
    document_service = DocumentService(_embedding_service)
    rag_service = RAGService(_embedding_service, document_service)
    logger.info(f"RAG pipeline ready: backend={_embedding_service.get_backend()}")
except Exception as e:
    logger.warning(f"RAG pipeline not initialized: {e}")
    _embedding_service = None
    document_service = None
    rag_service = None


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    top_k: Optional[int] = Field(5, description="Number of chunks to return")


def _require_rag():
    if rag_service is None:
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
