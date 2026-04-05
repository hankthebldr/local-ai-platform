#!/usr/bin/env python3
"""
Export Router Tests — Unit tests for session export endpoints

Run:  pytest tests/test_exports.py -v
"""

import os
import pytest
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Test client with auth disabled"""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import importlib
    import api.middleware
    importlib.reload(api.middleware)
    import api.main
    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_exports():
    """Clean up test export files after each test."""
    yield
    from api.routers.exports import EXPORTS_DIR

    for f in EXPORTS_DIR.glob("test-*.md"):
        f.unlink(missing_ok=True)


# ── Unit Tests: Save ──────────────────────────────────────────────────────


class TestSaveExport:
    """Tests for POST /api/exports/save"""

    def test_save_success(self, client):
        md = "# Test Session\n\n## User\nHello\n\n## Assistant\nHi there!\n"
        resp = client.post(
            "/api/exports/save",
            json={"filename": "test-session.md", "content": md},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"
        assert data["filename"] == "test-session.md"
        assert data["size"] == len(md)

    def test_save_sanitizes_filename(self, client):
        resp = client.post(
            "/api/exports/save",
            json={"filename": "../../etc/test-evil.md", "content": "# Bad"},
        )
        assert resp.status_code == 200
        # Should strip path traversal
        assert ".." not in resp.json()["filename"]
        # Clean up
        from api.routers.exports import EXPORTS_DIR
        for f in EXPORTS_DIR.glob("*evil*"):
            f.unlink(missing_ok=True)

    def test_save_adds_md_extension(self, client):
        resp = client.post(
            "/api/exports/save",
            json={"filename": "test-noext", "content": "# Test"},
        )
        assert resp.json()["filename"].endswith(".md")
        # Clean up
        from api.routers.exports import EXPORTS_DIR
        for f in EXPORTS_DIR.glob("test-noext*"):
            f.unlink(missing_ok=True)

    def test_save_missing_content(self, client):
        resp = client.post("/api/exports/save", json={"filename": "test.md"})
        assert resp.status_code == 422

    def test_save_missing_filename(self, client):
        resp = client.post("/api/exports/save", json={"content": "# Test"})
        assert resp.status_code == 422


# ── Unit Tests: List ──────────────────────────────────────────────────────


class TestListExports:
    """Tests for GET /api/exports"""

    def test_list_empty(self, client):
        resp = client.get("/api/exports")
        assert resp.status_code == 200
        data = resp.json()
        assert "exports" in data
        assert "count" in data
        assert isinstance(data["exports"], list)

    def test_list_after_save(self, client):
        client.post(
            "/api/exports/save",
            json={"filename": "test-list.md", "content": "# Listed session\n\nContent here"},
        )
        resp = client.get("/api/exports")
        data = resp.json()
        filenames = [e["filename"] for e in data["exports"]]
        assert "test-list.md" in filenames

    def test_list_has_preview(self, client):
        content = "# Preview Test\n\nThis is the preview content that should appear."
        client.post(
            "/api/exports/save",
            json={"filename": "test-preview.md", "content": content},
        )
        resp = client.get("/api/exports")
        export = next(e for e in resp.json()["exports"] if e["filename"] == "test-preview.md")
        assert "Preview Test" in export["preview"]


# ── Unit Tests: Read ──────────────────────────────────────────────────────


class TestReadExport:
    """Tests for GET /api/exports/{filename}"""

    def test_read_success(self, client):
        content = "# Read Test\n\n## User\nHello world"
        client.post(
            "/api/exports/save",
            json={"filename": "test-read.md", "content": content},
        )
        resp = client.get("/api/exports/test-read.md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "Read Test" in resp.text

    def test_read_not_found(self, client):
        resp = client.get("/api/exports/nonexistent-file.md")
        assert resp.status_code == 200
        assert resp.json()["error"] == "not_found"

    def test_read_sanitizes_path(self, client):
        resp = client.get("/api/exports/../../etc/passwd")
        # FastAPI blocks path traversal with 404, or our sanitizer returns not_found
        assert resp.status_code in (404, 200)
        if resp.status_code == 200:
            assert resp.json().get("error") == "not_found"


# ── Unit Tests: Delete ────────────────────────────────────────────────────


class TestDeleteExport:
    """Tests for DELETE /api/exports/{filename}"""

    def test_delete_success(self, client):
        client.post(
            "/api/exports/save",
            json={"filename": "test-delete.md", "content": "# Delete me"},
        )
        resp = client.delete("/api/exports/test-delete.md")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify it's gone
        read_resp = client.get("/api/exports/test-delete.md")
        assert read_resp.json()["error"] == "not_found"

    def test_delete_not_found(self, client):
        resp = client.delete("/api/exports/nonexistent.md")
        assert resp.json()["status"] == "not_found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
