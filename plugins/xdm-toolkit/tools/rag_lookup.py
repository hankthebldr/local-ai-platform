"""
rag_lookup — retrieve chunks from the Phase 2 `xql_corpus` Chroma
collection by free-text query and optional metadata filters.

Operates directly against the project ChromaDB so workflows do not
need RAGService extended for multi-collection access (see plan
Phase 4 minor extension note). Embeds the query via the same
EmbeddingService the ingest script used, so embedding-backend
compatibility holds across writes and reads.

Tool contract:
    Input:
      query: str            — free-text query (required)
      top_k: int            — 1..20, default 5
      filters: dict         — optional metadata equality filters, e.g.
                              {"pack_name": "aws_guardduty"} or
                              {"category": "pack", "pack_role": "datamodel"}
    Output:
      {
        "query": str,
        "collection": str,
        "matches": [{text, score, source_path, pack_name?, category,
                     chunk_index, ...}],
        "total_chunks": int,
      }

If the collection or embedding backend is unavailable, returns
`{"matches": [], "error": "..."}` rather than raising — callers can
treat it as a soft miss and fall back to the static `packs_index.md`
context.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

# Repo root: plugins/xdm-toolkit/tools/<this file> -> ../../../
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHROMA_DIR = _REPO_ROOT / "data" / "rag" / "chroma"

DEFAULT_COLLECTION = "xql_corpus"


def _ensure_repo_on_path() -> None:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))


@lru_cache(maxsize=1)
def _embedding_service():
    _ensure_repo_on_path()
    from api.services.embedding_service import EmbeddingService
    from api.services.ollama_service import OllamaService
    return EmbeddingService(ollama_service=OllamaService())


@lru_cache(maxsize=1)
def _collection():
    if not _CHROMA_DIR.is_dir():
        return None
    try:
        import chromadb
    except ImportError:
        return None
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    try:
        return client.get_collection(name=DEFAULT_COLLECTION)
    except Exception:
        return None


def _build_where(filters: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Translate a flat {field: value} dict to Chroma's $eq filter shape."""
    if not filters:
        return None
    if len(filters) == 1:
        (field, value), = filters.items()
        return {field: {"$eq": value}}
    return {"$and": [{field: {"$eq": value}} for field, value in filters.items()]}


def execute(
    query: str = "",
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
    **_unused,
) -> Dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        return {
            "query": query,
            "collection": DEFAULT_COLLECTION,
            "matches": [],
            "total_chunks": 0,
            "error": "empty query",
        }
    k = max(1, min(int(top_k or 5), 20))

    coll = _collection()
    if coll is None:
        return {
            "query": query,
            "collection": DEFAULT_COLLECTION,
            "matches": [],
            "total_chunks": 0,
            "error": (
                f"collection '{DEFAULT_COLLECTION}' not found at {_CHROMA_DIR}. "
                "Run `python scripts/ingest_xql_corpus.py` to build it."
            ),
        }

    try:
        embed = _embedding_service()
        vec = embed.embed_query(query.strip())
    except Exception as exc:
        return {
            "query": query,
            "collection": DEFAULT_COLLECTION,
            "matches": [],
            "total_chunks": coll.count(),
            "error": f"embedding backend unavailable: {exc}",
        }

    where = _build_where(filters)
    try:
        raw = coll.query(
            query_embeddings=[vec],
            n_results=k,
            where=where,
        )
    except Exception as exc:
        return {
            "query": query,
            "collection": DEFAULT_COLLECTION,
            "matches": [],
            "total_chunks": coll.count(),
            "error": f"chroma query failed: {exc}",
        }

    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    matches: List[Dict[str, Any]] = []
    for text, meta, dist in zip(docs, metas, distances):
        score = round(1.0 / (1.0 + float(dist)), 4)
        meta = dict(meta or {})
        matches.append({
            "text": text,
            "score": score,
            "source_path": meta.pop("source_path", ""),
            "chunk_index": meta.pop("chunk_index", 0),
            "category": meta.pop("category", "other"),
            **meta,  # surface remaining metadata (pack_name, pack_role, doc_name, etc.)
        })

    return {
        "query": query,
        "collection": DEFAULT_COLLECTION,
        "matches": matches,
        "total_chunks": coll.count(),
    }
