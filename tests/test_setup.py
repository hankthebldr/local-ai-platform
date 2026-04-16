#!/usr/bin/env python3
"""Tests for the setup wizard endpoints"""

import os
import pytest
import importlib
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def setup_client():
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware
    importlib.reload(api.middleware)
    import api.main
    importlib.reload(api.main)
    from api.main import app
    return TestClient(app)


class TestSetupEndpoints:
    def test_check_ollama_when_running(self, setup_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": []}
        with patch("api.routers.setup.http_requests.get", return_value=mock_resp):
            resp = setup_client.get("/api/setup/check-ollama")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is True

    def test_check_ollama_when_not_running(self, setup_client):
        with patch("api.routers.setup.http_requests.get", side_effect=Exception("refused")):
            resp = setup_client.get("/api/setup/check-ollama")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is False

    def test_complete_setup(self, setup_client):
        import tempfile
        import shutil
        tmpdir = tempfile.mkdtemp()
        with patch("api.routers.setup.APP_DIR", tmpdir):
            resp = setup_client.post("/api/setup/complete")
            assert resp.status_code == 200
            flag = os.path.join(tmpdir, "setup_complete")
            assert os.path.exists(flag)
        shutil.rmtree(tmpdir)

    def test_setup_page_served(self, setup_client):
        resp = setup_client.get("/setup")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
