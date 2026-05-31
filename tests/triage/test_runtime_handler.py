from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.exceptions import register_exception_handlers


def _app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_unhandled_returns_500_envelope_and_request_id(monkeypatch):
    monkeypatch.delenv("ENABLE_ERROR_REPORTING", raising=False)
    client = TestClient(_app(), raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["type"] == "internal_error"
    assert body["error"]["request_id"]
    assert "kaboom" not in body["error"]["message"]  # internals not leaked to caller


def test_reporting_skipped_when_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_ERROR_REPORTING", raising=False)
    client = TestClient(_app(), raise_server_exceptions=False)
    with patch("triage.reporting.report") as rep:
        client.get("/boom")
        rep.assert_not_called()


def test_reporting_invoked_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_ERROR_REPORTING", "true")
    monkeypatch.setenv("ERROR_SINK", "webhook")
    monkeypatch.setenv("ERROR_SINK_URL", "https://sink/in")
    client = TestClient(_app(), raise_server_exceptions=False)
    with patch("api.exceptions._dispatch_report") as disp:
        client.get("/boom")
        disp.assert_called_once()
