#!/usr/bin/env python3
"""
DocumentService — Document lifecycle + ChromaDB storage

Owns: parse → chunk → embed → store, plus per-doc YAML metadata
and a ChromaDB collection tagged with the embedding backend.
"""

from __future__ import annotations

import io
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger
from .chunker import Chunker
from .embedding_service import (
    EmbeddingBackendMismatch,
    EmbeddingService,
    collection_compatible,
)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
COLLECTION_NAME = "enclave-docs"


class UnsupportedFormat(Exception):
    """Raised when an uploaded file's extension is not supported."""


def _doc_id() -> str:
    return f"doc_{secrets.token_hex(6)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guess_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def _parse_file(filename: str, content: bytes) -> str:
    """Parse a file's bytes into plain text based on extension."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormat(f"Unsupported extension: {ext}")
    if ext in (".txt", ".md"):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1")
    if ext == ".pdf":
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    raise UnsupportedFormat(f"Unhandled extension: {ext}")


class DocumentService:
    """Manages indexed documents and the backing ChromaDB collection."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        data_dir: str = "data/rag",
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        self._embed = embedding_service
        self._dir = Path(data_dir)
        self._docs_dir = self._dir / "documents"
        self._raw_dir = self._docs_dir / "raw"
        self._chroma_dir = self._dir / "chroma"
        self._docs_dir.mkdir(parents=True, exist_ok=True)
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._chroma_dir.mkdir(parents=True, exist_ok=True)

        cs = (
            chunk_size
            if chunk_size is not None
            else int(os.getenv("RAG_CHUNK_SIZE", "512"))
        )
        co = (
            chunk_overlap
            if chunk_overlap is not None
            else int(os.getenv("RAG_CHUNK_OVERLAP", "50"))
        )
        self._chunker = Chunker(chunk_size=cs, chunk_overlap=co)

        self._client = None
        self._collection = None
        self._init_chroma()

    # ── ChromaDB wiring ───────────────────────────────────────────────

    def _init_chroma(self) -> None:
        import chromadb

        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
        desc = self._embed.describe()
        try:
            existing = self._client.get_collection(name=COLLECTION_NAME)
            compatible, warning = collection_compatible(existing.metadata, desc)
            if not compatible:
                raise EmbeddingBackendMismatch(
                    f"Collection '{COLLECTION_NAME}' was created with {existing.metadata}, "
                    f"but EmbeddingService reports {desc}. Restore the original backend, "
                    f"set ENCLAVE_EMBEDDING_ALLOW_REBIND=true to reuse a same-family "
                    f"collection, or delete {self._chroma_dir} to re-ingest."
                )
            if warning:
                logger.warning(warning)
            self._collection = existing
        except Exception as e:
            if isinstance(e, EmbeddingBackendMismatch):
                raise
            self._collection = self._client.create_collection(
                name=COLLECTION_NAME,
                metadata=desc,
            )
            logger.info(
                f"Created ChromaDB collection '{COLLECTION_NAME}' with metadata {desc}"
            )

    # ── Upload ────────────────────────────────────────────────────────

    def upload(self, filename: str, content: bytes) -> dict:
        doc_id = _doc_id()
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise UnsupportedFormat(f"Unsupported extension: {ext}")

        # Save raw file
        raw_dir = self._raw_dir / doc_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / filename).write_bytes(content)

        record = {
            "id": doc_id,
            "filename": filename,
            "mime_type": _guess_mime(filename),
            "size_bytes": len(content),
            "uploaded_at": _now_iso(),
            "collection": COLLECTION_NAME,
            "chunk_count": 0,
            "chunking": {
                "strategy": "recursive",
                "chunk_size": self._chunker.chunk_size,
                "chunk_overlap": self._chunker.chunk_overlap,
            },
            "embedding": self._embed.describe(),
            "status": "processing",
            "error": None,
        }

        try:
            text = _parse_file(filename, content)
            chunks = self._chunker.split(text)
            if chunks:
                embeddings = self._embed.embed(chunks)
                ids = [f"{doc_id}::chunk_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "doc_id": doc_id,
                        "filename": filename,
                        "chunk_index": i,
                        "chunk_total": len(chunks),
                    }
                    for i in range(len(chunks))
                ]
                self._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas,
                )
            record["chunk_count"] = len(chunks)
            record["status"] = "indexed"
        except Exception as e:
            logger.error(f"Failed to index {filename}: {e}")
            record["status"] = "failed"
            record["error"] = str(e)
            # Roll back any partial inserts
            try:
                self._collection.delete(where={"doc_id": doc_id})
            except Exception:
                pass

        self._save_record(record)
        return record

    # ── List / Get / Delete ──────────────────────────────────────────

    def list_documents(self) -> list:
        docs = []
        for p in sorted(self._docs_dir.glob("*.yaml")):
            try:
                docs.append(yaml.safe_load(p.read_text()))
            except yaml.YAMLError as e:
                logger.error(f"Corrupt document record {p}: {e}")
        return docs

    def get_document(self, doc_id: str) -> Optional[dict]:
        p = self._docs_dir / f"{doc_id}.yaml"
        if not p.exists():
            return None
        try:
            return yaml.safe_load(p.read_text())
        except yaml.YAMLError:
            return None

    def delete_document(self, doc_id: str) -> bool:
        p = self._docs_dir / f"{doc_id}.yaml"
        if not p.exists():
            return False
        try:
            self._collection.delete(where={"doc_id": doc_id})
        except Exception as e:
            logger.warning(f"Chroma delete failed for {doc_id}: {e}")
        p.unlink(missing_ok=True)
        raw = self._raw_dir / doc_id
        if raw.exists():
            import shutil as _shutil

            _shutil.rmtree(raw, ignore_errors=True)
        return True

    # ── Reindex ──────────────────────────────────────────────────────

    def reindex(self, doc_id: str) -> Optional[dict]:
        rec = self.get_document(doc_id)
        if rec is None:
            return None
        raw_dir = self._raw_dir / doc_id
        files = list(raw_dir.iterdir()) if raw_dir.exists() else []
        if not files:
            logger.error(f"Cannot reindex {doc_id}: raw file missing")
            return None
        filename = rec["filename"]
        content = (raw_dir / filename).read_bytes()
        # Delete existing chunks
        try:
            self._collection.delete(where={"doc_id": doc_id})
        except Exception:
            pass
        # Re-run pipeline but keep the same doc_id
        try:
            text = _parse_file(filename, content)
            chunks = self._chunker.split(text)
            if chunks:
                embeddings = self._embed.embed(chunks)
                ids = [f"{doc_id}::chunk_{i}" for i in range(len(chunks))]
                metadatas = [
                    {
                        "doc_id": doc_id,
                        "filename": filename,
                        "chunk_index": i,
                        "chunk_total": len(chunks),
                    }
                    for i in range(len(chunks))
                ]
                self._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas,
                )
            rec["chunk_count"] = len(chunks)
            rec["status"] = "indexed"
            rec["error"] = None
            rec["embedding"] = self._embed.describe()
            rec["chunking"] = {
                "strategy": "recursive",
                "chunk_size": self._chunker.chunk_size,
                "chunk_overlap": self._chunker.chunk_overlap,
            }
        except Exception as e:
            rec["status"] = "failed"
            rec["error"] = str(e)
        self._save_record(rec)
        return rec

    # ── Stats ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        docs = self.list_documents()
        total_chunks = sum(d.get("chunk_count", 0) for d in docs)
        total_bytes = sum(d.get("size_bytes", 0) for d in docs)
        return {
            "total_documents": len(docs),
            "total_chunks": total_chunks,
            "total_bytes": total_bytes,
            "collection": COLLECTION_NAME,
            "embedding": self._embed.describe(),
        }

    # ── Collection accessor for RAGService ───────────────────────────

    def get_collection(self):
        return self._collection

    # ── Private ──────────────────────────────────────────────────────

    def _save_record(self, record: dict) -> None:
        path = self._docs_dir / f"{record['id']}.yaml"
        path.write_text(yaml.dump(record, default_flow_style=False))
