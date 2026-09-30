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

    def test_app_dir_matches_desktop_wrapper(self):
        """APP_DIR must match desktop/app.py so the Mac app sees the flag."""
        import api.routers.setup as setup_module
        assert setup_module.APP_DIR == os.path.expanduser("~/.enclave")


class TestLocalClientGuard:
    """GP-2 (P0-14): only a client we can PROVE is on the box may fetch the
    first-run master key. A naive '172.'-prefix check wrongly trusted public
    172.x, and a proxied request's peer address is the proxy — both refused."""

    @staticmethod
    def _req(host, headers=None):
        from types import SimpleNamespace

        class _Req:
            def __init__(self, host, headers):
                self.client = SimpleNamespace(host=host) if host is not None else None
                self.headers = headers or {}

        return _Req(host, headers)

    def test_loopback_allowed(self):
        from api.routers.setup import _is_local_client

        assert _is_local_client(self._req("127.0.0.1")) is True
        assert _is_local_client(self._req("::1")) is True
        assert _is_local_client(self._req("localhost")) is True

    def test_docker_bridge_rfc1918_refused_without_the_opt_in(self, monkeypatch):
        """Theme B: RFC1918 used to be trusted outright, and `ip.is_private`
        also spans the 100.64.0.0/10 CGNAT range Tailscale hands out — so any
        LAN or tailnet peer could fetch the master key. Now refused by
        default."""
        from api.routers.setup import _is_local_client

        monkeypatch.delenv("ENCLAVE_TRUST_PRIVATE_NET", raising=False)
        assert _is_local_client(self._req("172.17.0.1")) is False  # docker bridge
        assert _is_local_client(self._req("192.168.1.5")) is False
        assert _is_local_client(self._req("10.0.0.4")) is False
        assert _is_local_client(self._req("100.101.102.103")) is False  # tailnet

    def test_docker_bridge_rfc1918_allowed_with_the_opt_in(self, monkeypatch):
        """The Docker-compose bridge topology still works — it just has to say
        so (docker-compose.yml sets ENCLAVE_TRUST_PRIVATE_NET)."""
        from api.routers.setup import _is_local_client

        monkeypatch.setenv("ENCLAVE_TRUST_PRIVATE_NET", "true")
        assert _is_local_client(self._req("172.17.0.1")) is True  # docker bridge
        assert _is_local_client(self._req("192.168.1.5")) is True
        assert _is_local_client(self._req("10.0.0.4")) is True
        # The opt-in widens to private ranges — never to the public internet.
        assert _is_local_client(self._req("8.8.8.8")) is False

    def test_public_172_refused(self):
        from api.routers.setup import _is_local_client

        # 172.5.x is PUBLIC (only 172.16.0.0/12 is private) — the old prefix
        # check wrongly trusted it.
        assert _is_local_client(self._req("172.5.4.3")) is False
        assert _is_local_client(self._req("172.32.0.1")) is False
        assert _is_local_client(self._req("8.8.8.8")) is False

    def test_forwarding_header_refused_even_from_loopback(self):
        from api.routers.setup import _is_local_client

        for h in ("X-Forwarded-For", "Forwarded", "X-Real-IP"):
            assert (
                _is_local_client(self._req("127.0.0.1", {h: "203.0.113.9"})) is False
            ), h

    def test_no_client_refused(self):
        from api.routers.setup import _is_local_client

        assert _is_local_client(self._req(None)) is False
        assert _is_local_client(self._req("not-an-ip")) is False
