#!/usr/bin/env python3
"""
RAGService — Retrieval + context formatting

Thin wrapper that embeds queries, searches the DocumentService's
ChromaDB collection, and formats results for LLM injection.
"""

from __future__ import annotations

from typing import Optional

from ..logging_config import logger
from .document_service import DocumentService
from .embedding_service import EmbeddingService


class RAGService:
    """Retrieval + formatting on top of DocumentService."""

    def __init__(self, embedding_service: EmbeddingService, document_service: DocumentService):
        self._embed = embedding_service
        self._docs = document_service

    # ── Search ────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5, min_score: Optional[float] = None) -> dict:
        collection = self._docs.get_collection()
        query_vec = self._embed.embed_query(query)

        try:
            raw = collection.query(
                query_embeddings=[query_vec],
                n_results=top_k,
            )
        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            return {"query": query, "results": [], "total": 0}

        results = []
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        for text, meta, dist in zip(docs, metas, distances):
            # Chroma returns distance; convert to a similarity score in [0, 1]
            score = 1.0 / (1.0 + float(dist))
            if min_score is not None and score < min_score:
                continue
            results.append({
                "doc_id": meta.get("doc_id", ""),
                "filename": meta.get("filename", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "text": text,
                "score": round(score, 4),
            })

        return {"query": query, "results": results, "total": len(results)}

    # ── Context formatting ───────────────────────────────────────────

    def format_context(self, search_output: dict, max_chars: int = 4000) -> str:
        results = search_output.get("results") or []
        if not results:
            return ""

        header = "Retrieved context from documents:\n\n"
        lines = [header]
        used = len(header)
        for i, r in enumerate(results, start=1):
            block = (
                f"[{i}] {r['filename']} (chunk {r['chunk_index']}, score: {r['score']})\n"
                f"{r['text']}\n\n"
            )
            if used + len(block) > max_chars:
                break
            lines.append(block)
            used += len(block)

        lines.append("Use these excerpts when answering. Cite sources as [1], [2], etc.")
        return "".join(lines)
