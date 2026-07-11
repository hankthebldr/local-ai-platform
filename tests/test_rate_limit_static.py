#!/usr/bin/env python3
"""Rate limiter must exempt /static/ so a cold SPA boot (the ~60-file ES-module
fan-out from one IP) cannot self-429 the app. Regression for the ships-broken
bug where RateLimitMiddleware checked PUBLIC_PATHS but not PUBLIC_PREFIXES."""

import time

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from api.middleware import RateLimitMiddleware


def _app(rpm: int) -> TestClient:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[
        Route("/static/{path:path}", ok),
        Route("/api/thing", ok),
    ])
    app.add_middleware(RateLimitMiddleware, rpm=rpm)
    return TestClient(app)


def test_static_burst_never_429s():
    client = _app(rpm=5)
    # Far exceed the budget with static assets — every one must pass.
    codes = [client.get(f"/static/js/mod{i}.js").status_code for i in range(40)]
    assert set(codes) == {200}, f"static assets were throttled: {sorted(set(codes))}"


def test_api_still_rate_limited():
    client = _app(rpm=5)
    codes = [client.get("/api/thing").status_code for _ in range(12)]
    assert 429 in codes, "API routes must still be rate-limited"
    assert codes[:5] == [200] * 5, "first rpm requests should pass"


def test_static_does_not_consume_api_budget():
    client = _app(rpm=5)
    for i in range(40):
        assert client.get(f"/static/x{i}.js").status_code == 200
    # Budget untouched by the static burst — API calls still get their full rpm.
    assert [client.get("/api/thing").status_code for _ in range(5)] == [200] * 5


def test_rpm_zero_disables():
    client = _app(rpm=0)
    assert all(client.get("/api/thing").status_code == 200 for _ in range(30))
