# Phase 4: RAG Pipeline

**Date**: 2026-04-19
**Status**: Approved
**Goal**: Let users chat with their documents. Upload → parse → chunk → embed → retrieve → inject into chat, via a UI toggle and an LLM-callable tool.

## Overview

Three-layer service architecture plugged into the existing chat + plugin pipeline:

1. **EmbeddingService** — backend-bound text-to-vector conversion (Ollama or sentence-transformers)
2. **DocumentService** — document lifecycle (upload, parse, chunk, store in ChromaDB)
3. **RAGService** — retrieval + context formatting

Two user-facing integration points:
- `rag: true` flag on chat requests (user-controlled, auto-retrieval)
- `rag__search` built-in plugin tool (LLM-controlled, on-demand retrieval)

Plus a **Documents tab** in the dashboard for upload and management.

---

## 1. EmbeddingService

### Backend Binding (not fallback)

At service init, pick one backend and stay with it. Switching backends mid-life would produce dimension mismatches and semantic-space mismatches that silently corrupt retrieval.

**Selection order** (when `EMBEDDING_BACKEND=auto`):

1. Probe Ollama — test `OLLAMA_EMBEDDING_MODEL` via `/api/embeddings` with a one-word string
2. If it succeeds → bind to Ollama, cache dimension
3. Otherwise → load sentence-transformers with `SENTENCE_TRANSFORMER_MODEL`, bind to it
4. If both fail → raise `EmbeddingBackendUnavailable` at init time

Explicit values (`ollama`, `sentence_transformers`) skip the probe.

### Collection Binding

When `DocumentService` creates a ChromaDB collection, it stores `embedding_service.describe()` as collection metadata. On query, the service compares the stored metadata to the active backend. On mismatch it raises `EmbeddingBackendMismatch` with clear remediation steps (re-index or restore original backend).

### Interface — `api/services/embedding_service.py`

| Method | Description |
|--------|-------------|
| `__init__(ollama_service, ollama_model=None, st_model=None, backend=None)` | Select and bind backend |
| `embed(texts: list) → list` | Batch embed, return one vector per input |
| `embed_query(text: str) → list` | Single-text convenience |
| `get_backend() → str` | `"ollama"` or `"sentence_transformers"` |
| `get_model() → str` | Actual model name used |
| `get_dimension() → int` | Vector dimension |
| `describe() → dict` | `{"backend", "model", "dimension"}` |

### Exceptions

```python
class EmbeddingBackendUnavailable(Exception):
    """Raised when no embedding backend can be initialized."""

class EmbeddingBackendMismatch(Exception):
    """Raised when a collection's metadata doesn't match the current service."""
```

### Config

```
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
SENTENCE_TRANSFORMER_MODEL=all-MiniLM-L6-v2
EMBEDDING_BACKEND=auto   # auto | ollama | sentence_transformers
```

### Cold-Start Note

Sentence-transformers downloads its model (~90MB for MiniLM) on first use. The setup wizard gains a checkbox: **"Pre-download embedding fallback model"** (default off).

### Batching

- Ollama: `/api/embeddings` takes one text at a time — the service loops. Acceptable for typical ingestion; a progress callback option is provided for large doc uploads.
- sentence-transformers: native batching. Default batch size 32.

---

## 2. DocumentService

### Responsibility
Own the document lifecycle. Upload → parse → chunk → embed → store. Hand retrieval off to `RAGService`.

### Storage Layout

```
data/rag/
├── documents/
│   ├── {doc_id}.yaml              # per-doc metadata
│   └── raw/{doc_id}/<filename>    # original file preserved for re-indexing
└── chroma/                        # ChromaDB persistent directory
```

Single shared ChromaDB collection (`enclave-docs`) by default. Per-conversation or per-project collections can layer on later.

### Document Record — `data/rag/documents/{doc_id}.yaml`

```yaml
id: "doc_a1b2c3"
filename: "whitepaper.pdf"
mime_type: "application/pdf"
size_bytes: 1048576
uploaded_at: "2026-04-20T10:30:00Z"
collection: "enclave-docs"
chunk_count: 42
chunking:
  strategy: "recursive"
  chunk_size: 512
  chunk_overlap: 50
embedding:
  backend: "ollama"
  model: "nomic-embed-text"
  dimension: 768
status: "indexed"   # indexed | failed | processing
error: null         # populated when status == failed
```

### Parsing

- `.txt` / `.md` — `Path.read_text(encoding="utf-8")` with `latin-1` fallback
- `.pdf` — `pypdf` (lightweight, pure-Python, stable)

Each parser returns plain text. Format-aware chunking is out of scope.

### Chunking

`api/services/chunker.py` wraps LangChain's `RecursiveCharacterTextSplitter`:

```python
class Chunker:
    def __init__(self, chunk_size=512, chunk_overlap=50):
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split(self, text: str) -> list:
        return self._splitter.split_text(text)
```

Configurable via `.env`:
```
RAG_CHUNK_SIZE=512
RAG_CHUNK_OVERLAP=50
```

### Interface — `api/services/document_service.py`

| Method | Description |
|--------|-------------|
| `__init__(embedding_service, data_dir="data/rag")` | Open Chroma client; verify collection matches backend |
| `upload(filename, content: bytes) → dict` | Save raw, parse, chunk, embed, store. Returns doc record |
| `list_documents() → list` | All indexed docs with metadata |
| `get_document(doc_id) → dict` | Full doc record |
| `delete_document(doc_id) → bool` | Remove from Chroma, delete raw file and YAML |
| `reindex(doc_id) → dict` | Re-parse + re-chunk + re-embed |
| `stats() → dict` | Total docs, chunks, storage size, backend info |

### ChromaDB Integration

```python
collection = client.get_or_create_collection(
    name="enclave-docs",
    metadata=embedding_service.describe(),
)
```

Each chunk stored with:
- **id**: `{doc_id}::chunk_{idx}`
- **embedding**: from EmbeddingService
- **document**: chunk text
- **metadata**: `{"doc_id", "filename", "chunk_index", "chunk_total"}`

### Collection-Backend Mismatch Handling

On init, the service reads the collection's stored metadata. If it differs from `embedding_service.describe()`:
- Log a clear error listing both sides
- Raise `EmbeddingBackendMismatch` at startup, so the app refuses to serve stale retrievals

The operator must either restore the original backend (via `EMBEDDING_BACKEND=ollama` etc.) or delete `data/rag/chroma/` to re-ingest from `data/rag/documents/raw/`.

### Error Handling

- Parse failure → record `status: failed`, `error: "..."`, keep the doc record for inspection
- Embedding mid-ingest failure → roll back chunks already inserted, mark doc failed
- Delete failure on Chroma → log and continue (metadata removal is source of truth)
- Unsupported extension → reject at upload time with 400

### Router — `api/routers/documents.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents` | GET | List indexed docs |
| `/api/documents` | POST | Upload (multipart form) |
| `/api/documents/{id}` | GET | Doc detail |
| `/api/documents/{id}` | DELETE | Remove |
| `/api/documents/{id}/reindex` | POST | Re-chunk and re-embed |
| `/api/documents/stats` | GET | Counts and sizes |
| `/api/documents/search` | POST | Retrieval preview (wraps RAGService.search) |

---

## 3. RAGService + Integration

### RAGService — `api/services/rag_service.py`

Thin retrieval layer. Depends on `DocumentService` for the collection + `EmbeddingService` for query embedding.

| Method | Description |
|--------|-------------|
| `__init__(embedding_service, document_service)` | Wire deps |
| `search(query, top_k=5, min_score=None) → dict` | Top-k chunks + metadata |
| `format_context(results, max_chars=4000) → str` | System-ready formatted string with numbered sources |

### Search Result Format

```python
{
    "query": "how does sandboxing work",
    "results": [
        {
            "doc_id": "doc_a1b2c3",
            "filename": "whitepaper.pdf",
            "chunk_index": 7,
            "text": "The sandbox enforces a filesystem boundary by...",
            "score": 0.87,
        }
    ],
    "total": 1,
}
```

### Context Format

`format_context()` produces an injection-ready system message:

```
Retrieved context from documents:

[1] whitepaper.pdf (chunk 7, score: 0.87)
The sandbox enforces a filesystem boundary by...

[2] notes.md (chunk 3, score: 0.82)
Profile resolution priority is header → key → env...

Use these excerpts when answering. Cite sources as [1], [2], etc.
```

Truncates at `max_chars` boundary — never mid-chunk.

### Chat Router Integration

Add to `ChatCompletionRequest`:

```python
    rag: Optional[bool] = Field(False, description="Enable RAG retrieval for this request")
    rag_top_k: Optional[int] = Field(5, description="Number of chunks to retrieve")
```

In `chat_completions`, after memory injection + skill injection, before tool executor call:

```python
rag_sources = []
if request.rag and _profile_allows_rag(profile):
    last_user_msg = _last_user_message(messages)
    if last_user_msg:
        results = _rag_service.search(last_user_msg, top_k=request.rag_top_k)
        if results["total"] > 0:
            messages = [{"role": "system", "content": _rag_service.format_context(results)}] + messages
            rag_sources = results["results"]
```

Attach `rag_sources` to response dict alongside `sources` (web search) — same pattern.

### Built-in `rag__search` Plugin Tool

```
plugins/rag/
├── plugin.yaml
└── tools/
    └── search.py
```

**`plugins/rag/plugin.yaml`:**

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
    description: "Search indexed documents for information relevant to a query"
    parameters:
      query:
        type: string
        required: true
      top_k:
        type: integer
        default: 5
```

**`plugins/rag/tools/search.py`:**

```python
def execute(query: str, top_k: int = 5) -> dict:
    """Agent-callable: query the doc index and return top chunks."""
    from api.routers.documents import rag_service
    return rag_service.search(query, top_k=top_k)
```

The plugin imports the pre-initialized `rag_service` instance exported by the documents router (same pattern as `plugin_service` in the plugins router).

### Profile Integration

Each profile YAML gains a `rag` section:

```yaml
rag:
  enabled: true
  max_upload_mb: 50
```

Enforcement points:
- `chat_completions` — checks `profile.rag.enabled` before running RAG auto-retrieval
- `documents` router — checks `profile.rag.enabled` on upload/reindex; returns 403 if false
- `rag__search` tool — filtered out of LLM tool list by existing `filter_tools()` if the `rag` plugin isn't in `allowed_plugins`

Built-in profile defaults:
- `default` — `rag.enabled: true`
- `research` — `rag.enabled: true`, but `allowed_plugins` includes `rag` explicitly (so tool is allowed)
- `unrestricted` — `rag.enabled: true`

### Documents Tab in Dashboard

A new **Documents** tab in the existing tab bar (next to Memory):

**Upload Panel** — drag-drop zone + "Select File" button. Shows progress bar during chunking/embedding (via polling `/api/documents/{id}` for status changes).

**Document List** — table: filename, size, chunk count, uploaded_at, status, delete button, reindex button.

**Stats Row** — total docs, total chunks, storage size, embedding backend + model + dimension (from `/api/documents/stats`).

**Search Preview** — text input that calls `POST /api/documents/search` and displays top-5 chunks with filename + score + snippet. Lets users verify ingestion quality without opening a chat.

---

## Files to Create/Modify

### New

| File | Responsibility |
|------|---------------|
| `api/services/embedding_service.py` | Backend-bound embedding provider |
| `api/services/chunker.py` | Chunker wrapper around LangChain splitter |
| `api/services/document_service.py` | Doc lifecycle + ChromaDB collection management |
| `api/services/rag_service.py` | Retrieval + context formatting |
| `api/routers/documents.py` | REST endpoints for doc management + retrieval preview |
| `plugins/rag/plugin.yaml` | Built-in RAG plugin manifest |
| `plugins/rag/tools/search.py` | `rag__search` tool — agent-callable retrieval |
| `tests/test_embedding_service.py` | Backend selection, binding, mismatch detection |
| `tests/test_chunker.py` | Chunking behavior |
| `tests/test_document_service.py` | Upload, parse, chunk, store, delete, reindex |
| `tests/test_rag_service.py` | Search + format_context |
| `tests/test_documents_router.py` | HTTP-level endpoint tests |

### Modified

| File | Change |
|------|--------|
| `api/main.py` | Register documents router |
| `api/routers/chat.py` | Add `rag`/`rag_top_k`, call rag_service when enabled; wire profile check |
| `api/static/index.html` | Documents tab |
| `.env.example` | Embedding + RAG config |
| `data/profiles/*.yaml` | Add `rag` section to each built-in profile |

---

## Dependencies

**Already installed:**
- `chromadb==0.4.22`
- `langchain==0.1.4` (for `RecursiveCharacterTextSplitter`)
- `sentence-transformers==2.2.2`

**New:**
- `pypdf` (append to `setup/requirements.txt`)

---

## Out of Scope

- Per-conversation / per-project collections (single shared collection for Phase 4)
- Format-aware chunking (all formats use recursive splitter)
- `.docx`, `.html`, `.epub`, `.csv` parsers
- Semantic re-ranking (retrieve top-k and inject, no rerank step)
- Query rewriting / HyDE
- Automatic re-indexing on chunker config change (manual `reindex` endpoint only)
- Streaming RAG responses (auto-retrieval happens once before the LLM call)
- Citation enforcement (the prompt asks for citations; no automatic validation)
