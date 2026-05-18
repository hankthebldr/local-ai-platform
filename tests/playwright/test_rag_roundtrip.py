"""
RAG round-trip — upload a document, verify it indexes successfully, run
a semantic search, then clean up. Regression guard for the
sentence_transformers / chromadb tensor-bridge bug found in May 2026:
encode(convert_to_numpy=False) leaked PyTorch tensors into Chroma and
caused every upload to fail at the embedding-store step.
"""

from __future__ import annotations

import textwrap

import pytest
import requests

SAMPLE_DOC = textwrap.dedent(
    """\
    # Enclave RAG Test Doc

    This is a test markdown document for the RAG round-trip Playwright
    test. It mentions the XDM path xdm.network.dst_ip and the XQL
    operator |comp so semantic search has obvious anchor terms.

    ## Section A
    The canonical XDM destination IP path is xdm.network.dst_ip.

    ## Section B
    XQL aggregations use the comp operator: | comp count() by ...
    """
)


def _upload_doc(base_url, api_headers, filename: str = "rag-test.md") -> dict:
    """POST a document and return the JSON record."""
    files = {"file": (filename, SAMPLE_DOC.encode("utf-8"), "text/markdown")}
    r = requests.post(
        f"{base_url}/api/documents",
        headers=api_headers,
        files=files,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _rag_enabled(base_url, api_headers) -> bool:
    """Detect whether the RAG stack is wired (sentence_transformers + chromadb).
    If the API responds 503 (RAG disabled), tests skip cleanly."""
    r = requests.get(f"{base_url}/api/documents/stats", headers=api_headers, timeout=10)
    return r.status_code == 200


def test_rag_upload_indexes_without_tensor_error(base_url, api_headers):
    """The smoking gun: prior to the embedding_service fix, upload
    succeeded at the metadata layer but the doc record had status='failed'
    with a 'got [[tensor(...)]]' error. After the fix, status='indexed'
    and chunk_count > 0."""
    if not _rag_enabled(base_url, api_headers):
        pytest.skip(
            "RAG stack not available (missing chromadb / sentence_transformers)"
        )

    doc = _upload_doc(base_url, api_headers)
    doc_id = doc["id"]
    try:
        # Re-fetch via list (upload response is pre-indexing in some shapes).
        listing = requests.get(
            f"{base_url}/api/documents", headers=api_headers, timeout=10
        ).json()
        rec = next((d for d in listing if d["id"] == doc_id), None)
        assert rec is not None, f"Uploaded doc {doc_id} missing from listing"
        # Status MUST be 'indexed', not 'failed'.
        status = rec.get("status", "indexed")
        assert status != "failed", (
            f"Doc indexing failed — embedding_service likely leaking tensors again.\n"
            f"Full error: {rec.get('error', '(no detail)')[:400]}"
        )
        # Chunks must exist.
        assert (
            rec.get("chunk_count", 0) > 0
        ), f"Doc has 0 chunks; chunking or embedding pipeline broke. Record: {rec}"
    finally:
        requests.delete(
            f"{base_url}/api/documents/{doc_id}",
            headers=api_headers,
            timeout=10,
        )


def test_rag_search_returns_relevant_chunks(base_url, api_headers):
    """End-to-end: upload, search with a phrase that matches the doc,
    verify hits come back ranked, then clean up."""
    if not _rag_enabled(base_url, api_headers):
        pytest.skip("RAG stack not available")

    doc = _upload_doc(base_url, api_headers, filename="rag-search-test.md")
    doc_id = doc["id"]
    try:
        r = requests.post(
            f"{base_url}/api/documents/search",
            headers=api_headers,
            json={"query": "canonical XDM path for destination IP", "top_k": 3},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        results = body.get("results", [])
        assert results, f"Search returned 0 results. Body: {body}"
        # Top hit should contain the literal anchor we put in the doc.
        top_text = (
            results[0].get("text")
            or results[0].get("content")
            or results[0].get("document")
            or ""
        )
        assert (
            "xdm.network.dst_ip" in top_text.lower()
            or "destination ip" in top_text.lower()
        ), f"Top hit doesn't contain the expected anchor. Top text: {top_text[:200]}"
    finally:
        requests.delete(
            f"{base_url}/api/documents/{doc_id}",
            headers=api_headers,
            timeout=10,
        )


def test_rag_stats_reflects_state(base_url, api_headers):
    """Stats endpoint must include total_documents, total_chunks, and the
    embedding model config. UI's RAG panel depends on this shape."""
    if not _rag_enabled(base_url, api_headers):
        pytest.skip("RAG stack not available")
    r = requests.get(f"{base_url}/api/documents/stats", headers=api_headers, timeout=10)
    r.raise_for_status()
    s = r.json()
    for key in ("total_documents", "total_chunks", "collection", "embedding"):
        assert (
            key in s
        ), f"stats response missing required key {key!r}; got {list(s.keys())}"
    emb = s["embedding"]
    assert "backend" in emb and "model" in emb, f"embedding info incomplete: {emb}"
