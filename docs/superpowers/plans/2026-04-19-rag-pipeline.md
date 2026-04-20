# Phase 4: RAG Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users chat with their documents — upload → parse → chunk → embed → retrieve → inject into chat, via a UI toggle and an LLM-callable tool.

**Architecture:** Three layered services. `EmbeddingService` binds to one backend (Ollama first, sentence-transformers fallback) at init time. `DocumentService` owns the doc lifecycle and a ChromaDB collection tagged with the embedding backend's identity. `RAGService` is a thin retrieval wrapper. Dual integration: `rag: true` flag on chat requests triggers auto-retrieval, and a built-in `rag/search` plugin tool exposes retrieval to the LLM.

**Tech Stack:** Python 3.9, FastAPI, ChromaDB 0.4.22, LangChain 0.1.4 (`RecursiveCharacterTextSplitter`), sentence-transformers 2.2.2, pypdf (new)

**Spec:** `docs/superpowers/specs/2026-04-19-rag-pipeline-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `api/services/embedding_service.py` | Backend-bound embedding provider (Ollama or sentence-transformers) + exceptions |
| `api/services/chunker.py` | Wrapper around LangChain RecursiveCharacterTextSplitter |
| `api/services/document_service.py` | Upload, parse (txt/md/pdf), chunk, embed, store in ChromaDB |
| `api/services/rag_service.py` | Retrieval + context formatting |
| `api/routers/documents.py` | REST endpoints for docs + exports `rag_service` for the plugin tool |
| `plugins/rag/plugin.yaml` | Built-in RAG plugin manifest |
| `plugins/rag/tools/search.py` | `rag__search` agent-callable retrieval tool |
| `plugins/rag/tools/__init__.py` | Empty init for import |
| `tests/test_embedding_service.py` | Backend selection, binding, mismatch |
| `tests/test_chunker.py` | Chunk sizing + overlap |
| `tests/test_document_service.py` | Upload, parse, delete, reindex |
| `tests/test_rag_service.py` | Search + format_context |
| `tests/test_documents_router.py` | HTTP-level router tests |

### Modified Files
| File | Change |
|------|--------|
| `api/main.py:18,99-109` | Register documents router |
| `api/routers/chat.py:39-49,52+` | Add `rag`/`rag_top_k` fields, run auto-retrieval when enabled, profile gate |
| `api/static/index.html` | New Documents tab |
| `.env.example` | Embedding + RAG config |
| `setup/requirements.txt` | Add `pypdf` |
| `data/profiles/default.yaml` | Add `rag` section |
| `data/profiles/research.yaml` | Add `rag` section |
| `data/profiles/unrestricted.yaml` | Add `rag` section |

---

## Task 1: Chunker

**Files:**
- Create: `api/services/chunker.py`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_chunker.py`:

```python
#!/usr/bin/env python3
"""Tests for Chunker — LangChain RecursiveCharacterTextSplitter wrapper"""

import pytest


class TestChunker:
    def test_split_returns_list_of_strings(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=100, chunk_overlap=10)
        chunks = c.split("hello world")
        assert isinstance(chunks, list)
        assert all(isinstance(x, str) for x in chunks)

    def test_short_text_is_single_chunk(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=1000, chunk_overlap=50)
        chunks = c.split("Short text.")
        assert len(chunks) == 1
        assert chunks[0] == "Short text."

    def test_long_text_is_split(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=50, chunk_overlap=0)
        text = "Paragraph one.\n\n" + ("Sentence. " * 30)
        chunks = c.split(text)
        assert len(chunks) > 1

    def test_empty_text_returns_empty_list(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=100, chunk_overlap=10)
        assert c.split("") == []

    def test_chunks_respect_boundaries(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=80, chunk_overlap=10)
        text = "First paragraph about cats.\n\nSecond paragraph about dogs.\n\nThird paragraph about birds."
        chunks = c.split(text)
        # Each chunk should be under (chunk_size + overlap) characters
        for ch in chunks:
            assert len(ch) <= 120
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_chunker.py -v`
Expected: FAIL — `api.services.chunker` does not exist

- [ ] **Step 3: Create `api/services/chunker.py`**

```python
#!/usr/bin/env python3
"""
Chunker — Thin wrapper around LangChain's RecursiveCharacterTextSplitter
"""

from __future__ import annotations

from typing import Optional


class Chunker:
    """Splits text into overlapping chunks using recursive character splitting."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split(self, text: str) -> list:
        """Return a list of chunk strings. Empty text → empty list."""
        if not text or not text.strip():
            return []
        return self._splitter.split_text(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_chunker.py -v`
Expected: All 5 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/chunker.py tests/test_chunker.py
git commit -m "feat: add Chunker wrapper around LangChain RecursiveCharacterTextSplitter"
```

---

## Task 2: EmbeddingService

**Files:**
- Create: `api/services/embedding_service.py`
- Test: `tests/test_embedding_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_embedding_service.py`:

```python
#!/usr/bin/env python3
"""Tests for EmbeddingService — backend selection and binding"""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestBackendSelection:
    def test_ollama_bound_when_probe_succeeds(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, ollama_model="nomic-embed-text")
            assert svc.get_backend() == "ollama"
            assert svc.get_model() == "nomic-embed-text"
            assert svc.get_dimension() == 3

    def test_explicit_backend_ollama(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.0] * 768}

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="test-model")
            assert svc.get_backend() == "ollama"
            assert svc.get_dimension() == 768

    def test_both_fail_raises(self):
        from api.services.embedding_service import EmbeddingService, EmbeddingBackendUnavailable
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        with patch("api.services.embedding_service.requests.post", side_effect=Exception("conn refused")):
            with patch("api.services.embedding_service.EmbeddingService._load_sentence_transformer", side_effect=Exception("st fail")):
                with pytest.raises(EmbeddingBackendUnavailable):
                    EmbeddingService(ollama, backend="auto")


class TestEmbedding:
    def test_embed_returns_one_vector_per_input(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.5, 0.5, 0.5]}

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="m")
            vecs = svc.embed(["a", "b", "c"])
            assert len(vecs) == 3
            assert all(len(v) == 3 for v in vecs)

    def test_embed_query_returns_single_vector(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.1, 0.2]}

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="m")
            v = svc.embed_query("hello")
            assert v == [0.1, 0.2]


class TestDescribe:
    def test_describe_returns_dict(self):
        from api.services.embedding_service import EmbeddingService
        from api.services.ollama_service import OllamaService

        ollama = OllamaService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.0] * 768}

        with patch("api.services.embedding_service.requests.post", return_value=mock_resp):
            svc = EmbeddingService(ollama, backend="ollama", ollama_model="nomic-embed-text")
            d = svc.describe()
            assert d["backend"] == "ollama"
            assert d["model"] == "nomic-embed-text"
            assert d["dimension"] == 768
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_embedding_service.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create `api/services/embedding_service.py`**

```python
#!/usr/bin/env python3
"""
EmbeddingService — Backend-bound text-to-vector provider

Binds to ONE backend at init time (Ollama or sentence-transformers).
Once bound, stays with that backend for its lifetime to prevent
dimension/semantic mismatches in ChromaDB collections.
"""

from __future__ import annotations

import os
from typing import List, Optional

import requests

from ..logging_config import logger
from .ollama_service import OllamaService


class EmbeddingBackendUnavailable(Exception):
    """Raised when no embedding backend can be initialized."""


class EmbeddingBackendMismatch(Exception):
    """Raised when a ChromaDB collection's embedding metadata doesn't match the active service."""


class EmbeddingService:
    """Text-to-vector conversion with backend binding."""

    def __init__(
        self,
        ollama_service: OllamaService,
        ollama_model: Optional[str] = None,
        st_model: Optional[str] = None,
        backend: Optional[str] = None,
    ):
        self._ollama = ollama_service
        self._ollama_model = ollama_model or os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self._st_model = st_model or os.getenv("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2")
        self._backend_choice = backend or os.getenv("EMBEDDING_BACKEND", "auto")

        self._backend: Optional[str] = None
        self._model: Optional[str] = None
        self._dimension: Optional[int] = None
        self._st_instance = None

        self._select_backend()

    # ── Backend Selection ─────────────────────────────────────────────

    def _select_backend(self) -> None:
        if self._backend_choice == "ollama":
            self._bind_ollama(raise_on_fail=True)
        elif self._backend_choice == "sentence_transformers":
            self._bind_sentence_transformers(raise_on_fail=True)
        else:  # auto
            if not self._bind_ollama(raise_on_fail=False):
                if not self._bind_sentence_transformers(raise_on_fail=False):
                    raise EmbeddingBackendUnavailable(
                        f"No embedding backend available. Tried Ollama model '{self._ollama_model}' "
                        f"and sentence-transformers model '{self._st_model}'."
                    )

    def _bind_ollama(self, raise_on_fail: bool) -> bool:
        """Probe the Ollama embeddings endpoint; bind if it responds."""
        try:
            resp = requests.post(
                f"{self._ollama.host}/api/embeddings",
                json={"model": self._ollama_model, "prompt": "probe"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding")
            if not embedding or not isinstance(embedding, list):
                raise ValueError("Ollama returned empty or invalid embedding")
            self._backend = "ollama"
            self._model = self._ollama_model
            self._dimension = len(embedding)
            logger.info(f"Embedding backend: Ollama ({self._ollama_model}, dim={self._dimension})")
            return True
        except Exception as e:
            logger.warning(f"Ollama embeddings probe failed: {e}")
            if raise_on_fail:
                raise EmbeddingBackendUnavailable(f"Ollama embedding backend failed: {e}") from e
            return False

    def _bind_sentence_transformers(self, raise_on_fail: bool) -> bool:
        try:
            self._load_sentence_transformer()
            # Probe to get dimension
            vec = self._st_instance.encode(["probe"], convert_to_numpy=False)[0]
            self._backend = "sentence_transformers"
            self._model = self._st_model
            self._dimension = len(vec)
            logger.info(
                f"Embedding backend: sentence-transformers ({self._st_model}, dim={self._dimension})"
            )
            return True
        except Exception as e:
            logger.warning(f"sentence-transformers load failed: {e}")
            if raise_on_fail:
                raise EmbeddingBackendUnavailable(
                    f"sentence-transformers backend failed: {e}"
                ) from e
            return False

    def _load_sentence_transformer(self) -> None:
        """Import and instantiate sentence-transformers. Isolated for test patching."""
        from sentence_transformers import SentenceTransformer
        self._st_instance = SentenceTransformer(self._st_model)

    # ── Embedding API ─────────────────────────────────────────────────

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self._backend == "ollama":
            return [self._embed_one_ollama(t) for t in texts]
        return [list(v) for v in self._st_instance.encode(texts, convert_to_numpy=False)]

    def _embed_one_ollama(self, text: str) -> List[float]:
        resp = requests.post(
            f"{self._ollama.host}/api/embeddings",
            json={"model": self._ollama_model, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        embedding = resp.json().get("embedding")
        if not embedding:
            raise RuntimeError(f"Ollama returned empty embedding for text: {text[:60]}...")
        return embedding

    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]

    # ── Metadata ──────────────────────────────────────────────────────

    def get_backend(self) -> str:
        return self._backend or "unknown"

    def get_model(self) -> str:
        return self._model or "unknown"

    def get_dimension(self) -> int:
        return self._dimension or 0

    def describe(self) -> dict:
        return {
            "backend": self.get_backend(),
            "model": self.get_model(),
            "dimension": self.get_dimension(),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_embedding_service.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/embedding_service.py tests/test_embedding_service.py
git commit -m "feat: add EmbeddingService with backend binding (Ollama or sentence-transformers)"
```

---

## Task 3: Add pypdf dependency + PDF parsing helper

**Files:**
- Modify: `setup/requirements.txt`

- [ ] **Step 1: Add pypdf to requirements.txt**

Append to `setup/requirements.txt`:

```
# RAG
pypdf==4.3.1
```

- [ ] **Step 2: Install it in the dev venv**

Run: `source ../../../venv/bin/activate && pip install pypdf==4.3.1`
Expected: Successfully installed pypdf-4.3.1

- [ ] **Step 3: Commit**

```bash
git add setup/requirements.txt
git commit -m "chore: add pypdf dependency for RAG PDF parsing"
```

---

## Task 4: DocumentService (upload, parse, chunk, store)

**Files:**
- Create: `api/services/document_service.py`
- Test: `tests/test_document_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_document_service.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create `api/services/document_service.py`**

```python
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
from .embedding_service import EmbeddingService, EmbeddingBackendMismatch

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

        cs = chunk_size if chunk_size is not None else int(os.getenv("RAG_CHUNK_SIZE", "512"))
        co = chunk_overlap if chunk_overlap is not None else int(os.getenv("RAG_CHUNK_OVERLAP", "50"))
        self._chunker = Chunker(chunk_size=cs, chunk_overlap=co)

        self._client = None
        self._collection = None
        self._init_chroma()

    # ── ChromaDB wiring ───────────────────────────────────────────────

    def _init_chroma(self) -> None:
        import chromadb
        self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
        desc = self._embed.describe()
        try:
            existing = self._client.get_collection(name=COLLECTION_NAME)
            if existing.metadata != desc:
                raise EmbeddingBackendMismatch(
                    f"Collection '{COLLECTION_NAME}' was created with {existing.metadata}, "
                    f"but EmbeddingService reports {desc}. Restore original backend or "
                    f"delete {self._chroma_dir} to re-ingest."
                )
            self._collection = existing
        except Exception as e:
            if isinstance(e, EmbeddingBackendMismatch):
                raise
            # Collection doesn't exist yet
            self._collection = self._client.create_collection(
                name=COLLECTION_NAME,
                metadata=desc,
            )
            logger.info(f"Created ChromaDB collection '{COLLECTION_NAME}' with metadata {desc}")

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
                    ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_document_service.py -v`
Expected: All 10 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/document_service.py tests/test_document_service.py
git commit -m "feat: add DocumentService with upload, parse, chunk, embed, store"
```

---

## Task 5: RAGService (retrieval + context formatting)

**Files:**
- Create: `api/services/rag_service.py`
- Test: `tests/test_rag_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rag_service.py`:

```python
#!/usr/bin/env python3
"""Tests for RAGService — retrieval and context formatting"""

import pytest
import tempfile
import shutil


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
        assert len(formatted) <= 300  # header + one chunk is plausible
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_rag_service.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create `api/services/rag_service.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_rag_service.py -v`
Expected: All 7 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/rag_service.py tests/test_rag_service.py
git commit -m "feat: add RAGService for retrieval and context formatting"
```

---

## Task 6: Documents router + main registration

**Files:**
- Create: `api/routers/documents.py`
- Modify: `api/main.py`
- Test: `tests/test_documents_router.py`

- [ ] **Step 1: Create `api/routers/documents.py`**

```python
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
        raise HTTPException(status_code=404, detail="Document not found or raw file missing")
    return rec
```

- [ ] **Step 2: Register in `api/main.py`**

Read `api/main.py` to see current imports. Update line 18 to add `documents`:

```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, api_keys, plugins, setup, context, memory, profiles, documents
```

After the last `app.include_router(...)` line, add:

```python
app.include_router(documents.router)
```

- [ ] **Step 3: Write router tests**

Create `tests/test_documents_router.py`:

```python
#!/usr/bin/env python3
"""Tests for Documents router"""

import os
import pytest
import importlib
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import io


class _FakeEmbedding:
    def __init__(self, dim=4):
        self._dim = dim

    def embed(self, texts):
        return [[0.1] * self._dim for _ in texts]

    def embed_query(self, text):
        return [0.1] * self._dim

    def get_backend(self): return "fake"
    def get_model(self): return "fake-model"
    def get_dimension(self): return self._dim
    def describe(self): return {"backend": "fake", "model": "fake-model", "dimension": self._dim}


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
        resp = client.post("/api/documents/search", json={"query": "sandbox", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data
```

- [ ] **Step 4: Run tests**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_documents_router.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/documents.py api/main.py tests/test_documents_router.py
git commit -m "feat: add documents router with upload, list, delete, stats, search"
```

---

## Task 7: Chat integration — `rag` flag + profile gate

**Files:**
- Modify: `api/routers/chat.py`
- Test: `tests/test_documents_router.py` (append)

- [ ] **Step 1: Update `api/routers/chat.py`**

Read the file to see current structure. Apply these changes:

**A. Add imports** (after the existing profile/sandbox imports, around line 22):

```python
from .documents import rag_service as _rag_service
```

**B. Extend `ChatCompletionRequest`** — add two fields after `max_tool_iterations`:

```python
    rag: Optional[bool] = Field(False, description="Enable RAG retrieval for this request")
    rag_top_k: Optional[int] = Field(5, description="Number of chunks to retrieve")
```

**C. Add RAG augmentation block** inside `chat_completions`, AFTER the sandbox setup block and AFTER skill injection, but BEFORE the web search block:

```python
    # ── RAG Augmentation ────────────────────────────────────────────
    rag_sources = []
    rag_allowed = True
    if request.rag:
        # Profile gate
        profile_rag = (profile.get("rag") or {}).get("enabled", True)
        if profile_rag is False:
            rag_allowed = False
            logger.info(f"RAG disabled by profile '{profile_id}'")
        elif _rag_service is None:
            rag_allowed = False
            logger.warning("RAG requested but rag_service is unavailable")

    if request.rag and rag_allowed:
        last_user_msg = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_msg = msg["content"]
                break
        if last_user_msg:
            results = _rag_service.search(last_user_msg, top_k=request.rag_top_k)
            if results["total"] > 0:
                messages = [{"role": "system", "content": _rag_service.format_context(results)}] + messages
                rag_sources = results["results"]
                logger.info(f"Injected {results['total']} RAG chunks")
```

**D. Add `rag_sources` to both response dicts** — find the two places where `response["conversation_id"] = conversation_id` is set and add right after each:

```python
        if rag_sources:
            response["rag_sources"] = rag_sources
```

- [ ] **Step 2: Append router test for the integration**

Append to `tests/test_documents_router.py`:

```python
class TestChatRagIntegration:
    def test_chat_accepts_rag_flag(self, client):
        # Upload a doc first
        import io
        files = {"file": ("facts.txt", io.BytesIO(b"The capital of France is Paris."), "text/plain")}
        client.post("/api/documents", files=files)

        # Mock Ollama chat call (the chat endpoint uses the tool executor path
        # which in turn calls ollama via the OllamaService client)
        from unittest.mock import patch, MagicMock
        mock_ollama = MagicMock()
        mock_ollama.status_code = 200
        mock_ollama.json.return_value = {
            "message": {"role": "assistant", "content": "Paris."},
            "prompt_eval_count": 10, "eval_count": 5,
        }

        with patch("api.services.ollama_service.requests.post", return_value=mock_ollama):
            resp = client.post("/v1/chat/completions", json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "rag": True,
                "rag_top_k": 3,
                "tools": False,
            })
            assert resp.status_code == 200
            data = resp.json()
            # rag_sources should be present when retrieval found results
            assert "rag_sources" in data or data.get("rag_sources") == []
```

- [ ] **Step 3: Run all chat + documents tests**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py tests/test_documents_router.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add api/routers/chat.py tests/test_documents_router.py
git commit -m "feat: wire RAG auto-retrieval into chat with profile gating"
```

---

## Task 8: Built-in RAG plugin + profile updates + env example

**Files:**
- Create: `plugins/rag/plugin.yaml`
- Create: `plugins/rag/tools/__init__.py`
- Create: `plugins/rag/tools/search.py`
- Modify: `data/profiles/default.yaml`
- Modify: `data/profiles/research.yaml`
- Modify: `data/profiles/unrestricted.yaml`
- Modify: `.env.example`

- [ ] **Step 1: Create plugin manifest**

Create `plugins/rag/plugin.yaml`:

```yaml
name: "RAG Search"
id: "rag"
version: "1.0.0"
description: "Query indexed documents for relevant context"
author: "local"

tools:
  - id: "search"
    file: "tools/search.py"
    function: "execute"
    description: "Search indexed documents for information relevant to a query. Use when the user asks about specific information that might be in uploaded documents."
    parameters:
      query:
        type: string
        required: true
        description: "Natural-language search query"
      top_k:
        type: integer
        default: 5
        description: "Number of document chunks to retrieve"
```

- [ ] **Step 2: Create the tool module**

Create `plugins/rag/tools/__init__.py`:

```python
```

Create `plugins/rag/tools/search.py`:

```python
"""RAG search tool — agent-callable retrieval over indexed documents."""


def execute(query: str, top_k: int = 5) -> dict:
    """Search indexed documents and return top-k relevant chunks."""
    from api.routers.documents import rag_service
    if rag_service is None:
        return {"error": "RAG pipeline unavailable"}
    return rag_service.search(query=query, top_k=top_k)
```

- [ ] **Step 3: Add `rag` section to each profile**

Read `data/profiles/default.yaml` and append at the end (before any trailing blank line):

```yaml
rag:
  enabled: true
  max_upload_mb: 50
```

Do the same for `data/profiles/research.yaml` — but add `rag` to `allowed_plugins`:

Find the `allowed_plugins` list in `research.yaml` and add `"rag"` to it. Then append:

```yaml
rag:
  enabled: true
  max_upload_mb: 50
```

For `data/profiles/unrestricted.yaml`, append:

```yaml
rag:
  enabled: true
  max_upload_mb: 100
```

- [ ] **Step 4: Add env config**

Append to `.env.example`:

```
# RAG / Embeddings (Phase 4)
EMBEDDING_BACKEND=auto
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
SENTENCE_TRANSFORMER_MODEL=all-MiniLM-L6-v2
RAG_CHUNK_SIZE=512
RAG_CHUNK_OVERLAP=50
```

- [ ] **Step 5: Run the full test suite**

Run: `source ../../../venv/bin/activate && python -m pytest tests/ --tb=short -k "not integration" 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add plugins/rag/ data/profiles/ .env.example
git commit -m "feat: add RAG plugin (rag__search tool) and profile integration"
```

---

## Task 9: Documents tab in dashboard + final DMG verification

**Files:**
- Modify: `api/static/index.html`

- [ ] **Step 1: Add Documents tab button**

Read `api/static/index.html`. Find the tab bar (`<button class="tab-btn" ...>` elements). After the last tab button (likely Memory), add:

```html
<button class="tab-btn" data-tab="documents" onclick="switchTab('documents')">
  <span>Documents</span>
</button>
```

- [ ] **Step 2: Add Documents tab content**

Find the last `<div class="tab-content" ...>` block. After it (still inside the main container), add:

```html
<!-- ── DOCUMENTS TAB ───────────────────────────────────────────── -->
<div class="tab-content" id="tab-documents" style="display:none">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    <!-- Upload + List -->
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:16px;">
      <h3 style="color:var(--cyan);margin-bottom:12px;font-size:0.9rem;">Documents</h3>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <input type="file" id="doc-file-input" accept=".txt,.md,.pdf" style="flex:1;color:var(--text);font-family:var(--mono);font-size:0.8rem;">
        <button onclick="uploadDocument()" style="background:var(--cyan);color:#000;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-weight:600;font-size:0.8rem;">Upload</button>
      </div>
      <div id="doc-upload-status" style="font-size:0.75rem;color:var(--text-dim);margin-bottom:8px;"></div>
      <div id="documents-list" style="max-height:400px;overflow-y:auto;"></div>
    </div>
    <!-- Search Preview -->
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:16px;">
      <h3 style="color:var(--cyan);margin-bottom:12px;font-size:0.9rem;">Search Preview</h3>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <input type="text" id="doc-search-input" placeholder="Try a query..." style="flex:1;background:var(--bg-panel);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:4px;font-family:var(--mono);font-size:0.8rem;" onkeydown="if(event.key==='Enter')searchDocuments()">
        <button onclick="searchDocuments()" style="background:var(--cyan);color:#000;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-weight:600;font-size:0.8rem;">Search</button>
      </div>
      <div id="doc-search-results" style="max-height:400px;overflow-y:auto;"></div>
    </div>
  </div>
  <!-- Stats -->
  <div style="display:flex;gap:16px;margin-top:16px;">
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:12px;flex:1;text-align:center;">
      <div style="font-size:1.4rem;font-weight:600;color:var(--cyan);" id="doc-stat-count">0</div>
      <div style="font-size:0.75rem;color:var(--text-dim);">Documents</div>
    </div>
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:12px;flex:1;text-align:center;">
      <div style="font-size:1.4rem;font-weight:600;color:var(--cyan);" id="doc-stat-chunks">0</div>
      <div style="font-size:0.75rem;color:var(--text-dim);">Chunks</div>
    </div>
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:12px;flex:1;text-align:center;">
      <div style="font-size:0.85rem;font-weight:600;color:var(--cyan);" id="doc-stat-backend">—</div>
      <div style="font-size:0.75rem;color:var(--text-dim);">Embedding Backend</div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add JavaScript for the tab**

Find the `switchTab` function and add:

```javascript
if (tab === 'documents') loadDocumentsTab();
```

Near the other loaders (e.g., after `loadProfiles`), append these functions. Use the existing `esc()` helper:

```javascript
async function loadDocumentsTab() {
  loadDocumentsList();
  loadDocStats();
}

async function loadDocumentsList() {
  try {
    const r = await fetch('/api/documents');
    const docs = await r.json();
    const el = document.getElementById('documents-list');
    if (!docs.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No documents yet. Upload above.</div>';
      return;
    }
    el.innerHTML = docs.map(d => {
      const sizeKb = ((d.size_bytes||0)/1024).toFixed(1);
      const statusColor = d.status === 'indexed' ? 'var(--cyan)' : (d.status === 'failed' ? 'var(--red)' : 'var(--text-dim)');
      return `
        <div style="padding:10px;border-bottom:1px solid var(--border);">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-size:0.85rem;color:var(--text);max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(d.filename)}</div>
            <div>
              <button onclick="reindexDocument('${d.id}')" style="background:none;border:none;color:var(--cyan);cursor:pointer;font-size:0.75rem;margin-right:8px;">reindex</button>
              <button onclick="deleteDocument('${d.id}')" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.75rem;">delete</button>
            </div>
          </div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">
            <span style="color:${statusColor};">${esc(d.status)}</span>
            · ${sizeKb} KB · ${d.chunk_count||0} chunks
          </div>
        </div>
      `;
    }).join('');
  } catch(e) { console.error('Failed to load documents:', e); }
}

async function loadDocStats() {
  try {
    const r = await fetch('/api/documents/stats');
    if (!r.ok) return;
    const s = await r.json();
    document.getElementById('doc-stat-count').textContent = s.total_documents || 0;
    document.getElementById('doc-stat-chunks').textContent = s.total_chunks || 0;
    const emb = s.embedding || {};
    document.getElementById('doc-stat-backend').textContent = `${emb.backend || '—'} (${emb.model || '—'})`;
  } catch(e) {}
}

async function uploadDocument() {
  const input = document.getElementById('doc-file-input');
  const status = document.getElementById('doc-upload-status');
  if (!input.files.length) { status.textContent = 'Pick a file first.'; return; }
  const file = input.files[0];
  const form = new FormData();
  form.append('file', file);
  status.textContent = `Uploading ${file.name}...`;
  try {
    const r = await fetch('/api/documents', { method: 'POST', body: form });
    const data = await r.json();
    if (!r.ok) { status.textContent = `Error: ${data.detail || 'upload failed'}`; return; }
    status.textContent = `Indexed: ${data.filename} (${data.chunk_count} chunks)`;
    input.value = '';
    loadDocumentsList();
    loadDocStats();
  } catch(e) { status.textContent = `Error: ${e.message}`; }
}

async function deleteDocument(id) {
  await fetch('/api/documents/' + id, { method: 'DELETE' });
  loadDocumentsList();
  loadDocStats();
}

async function reindexDocument(id) {
  const status = document.getElementById('doc-upload-status');
  status.textContent = 'Reindexing...';
  const r = await fetch('/api/documents/' + id + '/reindex', { method: 'POST' });
  const data = await r.json();
  status.textContent = r.ok ? `Reindexed: ${data.filename}` : `Error: ${data.detail || 'reindex failed'}`;
  loadDocumentsList();
  loadDocStats();
}

async function searchDocuments() {
  const input = document.getElementById('doc-search-input');
  const query = input.value.trim();
  const el = document.getElementById('doc-search-results');
  if (!query) { el.innerHTML = ''; return; }
  el.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:8px;">Searching...</div>';
  try {
    const r = await fetch('/api/documents/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ query, top_k: 5 }),
    });
    const data = await r.json();
    if (!data.results || !data.results.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No matches.</div>';
      return;
    }
    el.innerHTML = data.results.map((r, i) => `
      <div style="padding:10px;border-bottom:1px solid var(--border);">
        <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:4px;">
          <span style="color:var(--cyan);">[${i+1}]</span> ${esc(r.filename)} (chunk ${r.chunk_index}, score: ${r.score})
        </div>
        <div style="font-size:0.8rem;color:var(--text);">${esc(r.text).slice(0, 300)}${r.text.length > 300 ? '…' : ''}</div>
      </div>
    `).join('');
  } catch(e) {
    el.innerHTML = `<div style="color:var(--red);font-size:0.8rem;padding:8px;">Error: ${esc(e.message)}</div>`;
  }
}
```

- [ ] **Step 4: Run the full test suite**

Run: `source ../../../venv/bin/activate && python -m pytest tests/ --tb=short -k "not integration" 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 5: Commit dashboard changes**

```bash
git add api/static/index.html
git commit -m "feat: add Documents tab to dashboard with upload, list, search preview"
```

- [ ] **Step 6: Rebuild the DMG to verify packaging**

```bash
bash scripts/build_mac.sh 2>&1 | tail -10
```

Expected: Build completes; DMG is produced at `dist/LocalAIPlatform.dmg` with the Enclave icon.

- [ ] **Step 7: Verify endpoints end-to-end**

```bash
source ../../../venv/bin/activate && python -m api.main &
sleep 3

# Stats (no docs yet)
curl -s http://localhost:8000/api/documents/stats | python -m json.tool

# Upload a test doc
echo "The quick brown fox jumps over the lazy dog." > /tmp/test.txt
curl -s -X POST http://localhost:8000/api/documents -F "file=@/tmp/test.txt" | python -m json.tool

# List and search
curl -s http://localhost:8000/api/documents | python -m json.tool
curl -s -X POST http://localhost:8000/api/documents/search \
  -H "Content-Type: application/json" \
  -d '{"query":"fox","top_k":3}' | python -m json.tool

kill %1 2>/dev/null
```

- [ ] **Step 8: Commit any final fixes**

```bash
git status --short
git add -A && git commit -m "chore: Phase 4 final integration verification" || true
```
