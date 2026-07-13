#!/usr/bin/env python3
"""
Feedback Router Tests — research-artifact capture (MS-3).

Covers the research-capture 422 regression fix and the real RAG ingest wire-up:
  - a >200-char title and an empty synthesis body both return 200 (was 422)
  - title is clamped <=200 server-side; empty body gets the sentinel
  - rag_ingested is reported truthfully: True when a document service is wired,
    False (but the artifact still persisted) when the RAG backend is down

Run:  ENABLE_API_AUTH=false pytest tests/test_feedback.py -q
"""

import os
import pytest
from fastapi.testclient import TestClient

from api.services import rag_ingest


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Test client with auth + rate limiting disabled and an isolated log dir."""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    os.environ["DATA_FEEDBACK_DIR"] = str(tmp_path_factory.mktemp("feedback"))
    import importlib
    import api.middleware
    importlib.reload(api.middleware)
    import api.routers.feedback
    importlib.reload(api.routers.feedback)
    import api.main
    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


class _FakeDocService:
    """Stand-in for the DocumentService singleton — records uploads."""

    def __init__(self):
        self.uploaded = []

    def upload(self, filename, content):
        self.uploaded.append((filename, content))
        return {"id": "doc_test", "filename": filename}


# ── The 422 regression: long title + empty body must both succeed ──────────


class TestCapture422Fix:
    def test_long_title_returns_200_and_is_clamped(self, client):
        long_title = "Synthesis: " + ("word " * 80)  # ~ 411 chars
        assert len(long_title) > 200
        resp = client.post(
            "/api/feedback/artifacts",
            json={"source": "research", "title": long_title, "body": "real body"},
        )
        assert resp.status_code == 200, resp.text
        rec = resp.json()
        assert len(rec["title"]) <= 200
        assert rec["title"]  # non-empty
        assert rec["id"].startswith("art_")

    def test_empty_body_returns_200_with_sentinel(self, client):
        resp = client.post(
            "/api/feedback/artifacts",
            json={"source": "research", "title": "Angle with no synthesis", "body": ""},
        )
        assert resp.status_code == 200, resp.text
        rec = resp.json()
        assert rec["body"] == "(no synthesis was generated for this angle)"

    def test_missing_body_field_returns_200(self, client):
        # body is optional now — omitting it must not 422.
        resp = client.post(
            "/api/feedback/artifacts",
            json={"source": "research", "title": "No body key at all"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["body"] == "(no synthesis was generated for this angle)"

    def test_whitespace_body_gets_sentinel(self, client):
        resp = client.post(
            "/api/feedback/artifacts",
            json={"source": "research", "title": "Whitespace body", "body": "   \n  "},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["body"] == "(no synthesis was generated for this angle)"

    def test_normal_capture_still_round_trips(self, client):
        resp = client.post(
            "/api/feedback/artifacts",
            json={
                "source": "research",
                "title": "Short title",
                "body": "Full synthesis text.",
                "tags": ["research", "synthesis"],
            },
        )
        assert resp.status_code == 200, resp.text
        rec = resp.json()
        assert rec["title"] == "Short title"
        assert rec["body"] == "Full synthesis text."
        # capture is durable — it lists back
        listed = client.get("/api/feedback/artifacts?limit=10").json()
        assert any(a["id"] == rec["id"] for a in listed)


# ── rag_ingested truthfulness ──────────────────────────────────────────────


class TestRagIngestWiring:
    def test_rag_ingested_true_when_service_wired(self, client, monkeypatch):
        fake = _FakeDocService()
        import api.routers.documents as docs
        monkeypatch.setattr(docs, "document_service", fake, raising=False)
        resp = client.post(
            "/api/feedback/artifacts",
            json={"source": "research", "title": "Indexed artifact", "body": "body text"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["rag_ingested"] is True
        assert len(fake.uploaded) == 1
        fname, content = fake.uploaded[0]
        assert fname.endswith(".md")
        assert b"Indexed artifact" in content

    def test_rag_ingested_false_when_backend_down(self, client, monkeypatch):
        import api.routers.documents as docs
        monkeypatch.setattr(docs, "document_service", None, raising=False)
        resp = client.post(
            "/api/feedback/artifacts",
            json={"source": "research", "title": "Not indexed", "body": "body text"},
        )
        assert resp.status_code == 200, resp.text
        rec = resp.json()
        # Artifact still persisted even though RAG is down …
        assert rec["rag_ingested"] is False
        listed = client.get("/api/feedback/artifacts?limit=20").json()
        assert any(a["id"] == rec["id"] for a in listed)


# ── ingest_markdown unit behavior (graceful, never raises) ─────────────────


class TestIngestMarkdown:
    def test_none_service_returns_false(self, monkeypatch):
        import api.routers.documents as docs
        monkeypatch.setattr(docs, "document_service", None, raising=False)
        assert rag_ingest.ingest_markdown("t", "b") is False

    def test_upload_failure_is_swallowed(self, monkeypatch):
        class Boom:
            def upload(self, *a, **k):
                raise RuntimeError("backend exploded")

        import api.routers.documents as docs
        monkeypatch.setattr(docs, "document_service", Boom(), raising=False)
        # Never raises — returns False.
        assert rag_ingest.ingest_markdown("t", "b") is False

    def test_success_builds_markdown_and_slug(self, monkeypatch):
        fake = _FakeDocService()
        import api.routers.documents as docs
        monkeypatch.setattr(docs, "document_service", fake, raising=False)
        ok = rag_ingest.ingest_markdown(
            "My / weird : title", "content", tags=["a", "b"], doc_id="art_1"
        )
        assert ok is True
        fname, content = fake.uploaded[0]
        assert fname.startswith("art_1-")
        assert fname.endswith(".md")
        assert "/" not in fname and ":" not in fname
        assert b"_tags: a, b_" in content
