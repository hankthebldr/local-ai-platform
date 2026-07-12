#!/usr/bin/env python3
"""
API Middleware — Authentication and Rate Limiting
"""

import hmac
import os
import time
from collections import defaultdict
from typing import Callable, Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────

API_KEY = os.getenv("API_KEY", "")
ENABLE_API_AUTH = os.getenv("ENABLE_API_AUTH", "false").lower() == "true"
MASTER_API_KEY = os.getenv("MASTER_API_KEY", "")
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "60"))  # requests per minute


# ── Paths that skip authentication ─────────────────────────────────────────

PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/setup.html",
    "/favicon.ico",
    # A2A discovery — the Agent Card is intentionally public per spec.
    # The JSON-RPC method endpoint at /a2a is still scope-gated below.
    "/.well-known/agent.json",
    # Local-license auto-delivery — the SPA fetches this on first boot so
    # the operator doesn't have to copy-paste the first-run key. The route
    # itself enforces a localhost-only client check before returning the
    # key. Placeholder for the future paid-license activation flow.
    "/api/setup/local-license",
}

# Prefixes that skip authentication (assets the dashboard needs before the
# user can possibly enter an API key — vendor CSS/JS, favicon, fonts).
PUBLIC_PREFIXES = ("/static/",)


# ── Scope enforcement ──────────────────────────────────────────────────────
# Maps URL path prefixes to the scope a key must hold to access them.
# Paths not listed here are unrestricted beyond base authentication.
SCOPE_MAP = {
    "/v1/chat/": "chat",
    "/v1/completions": "completions",
    "/v1/models": "models",
    "/api/documents": "documents",
    # GP-2 (P0-13 corrected): chat-session markdown exports are a data-action
    # write surface (save/list/read/zip/delete). Gate the whole /api/exports
    # prefix on an `exports` scope — parity with /api/documents. A scoped SPA
    # key can save exports; an unscoped key is 403'd. NOT require_master_key:
    # that runs before scope resolution and would 401 a legitimately
    # exports-scoped key, making this entry dead config.
    "/api/exports": "exports",
    "/api/memory": "memory",
    "/api/context": "context",
    "/api/profiles": "profiles",
    "/api/plugins": "plugins",
    "/api/workflows": "workflows",
    # DR-1: composer draft store (opaque canvas snapshots) is a data-action
    # write surface. Gate the whole /api/composer prefix on the `workflows`
    # scope (parity with /api/workflows) — a draft is a pre-publish workflow,
    # so a key that can author workflows can author drafts. Master key + the
    # auth-off dev path bypass this before scope resolution.
    "/api/composer": "workflows",
    # RX-2: the shared `research` workspace (saved sources/notes + MOCs) is a
    # data-action write surface. Gate the whole /api/workspaces prefix on a
    # `workspaces` scope (parity with /api/documents) so a scoped SPA key can
    # write notes but an unscoped key is 403'd. Operate U11 also writes here.
    "/api/workspaces": "workspaces",
    # Operate U4: the local scheduler read surface (list/detail/history/summary)
    # serves the same run-provenance bytes as /api/workflows. Gate reads on the
    # `workflows` scope (data-action tier, parity with /api/workflows) — writes
    # are separately require_master_key'd in the router. NOT master here: that
    # runs before scope resolution and would 401 a legitimately workflows-scoped
    # SPA key reading the Schedules rail.
    "/api/schedules": "workflows",
    "/api/keys": "keys",  # master key bypasses this before scope check
    "/a2a": "a2a",  # A2A JSON-RPC dispatch
}


def _required_scope(path: str) -> Optional[str]:
    """Return the scope needed for the given request path, or None if unrestricted."""
    for prefix, scope in SCOPE_MAP.items():
        if path.startswith(prefix):
            return scope
    return None


# ── API Key Authentication Middleware ──────────────────────────────────────


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    Validates API key from Authorization header or query parameter.

    Supports:
      - Authorization: Bearer <key>
      - ?api_key=<key>  (query param, for testing convenience)

    Skips auth for public paths (health, docs, root).
    Disabled only when ENABLE_API_AUTH=false (dev mode). Auth defaults to
    on; the keystore is auto-provisioned with a first-run master key on a
    fresh boot — see api/services/api_key_service.bootstrap_first_run_key.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        # Default-on: only skip when ENABLE_API_AUTH is explicitly "false".
        if os.getenv("ENABLE_API_AUTH", "true").lower() != "true":
            return await call_next(request)

        # Skip public paths (exact match + prefix allowlist for static assets)
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Extract key from header or query param
        auth_header = request.headers.get("Authorization", "")
        query_key = request.query_params.get("api_key", "")

        provided_key = ""
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:]
        elif query_key:
            provided_key = query_key

        if not provided_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "API key required. Provide via 'Authorization: Bearer <key>' header.",
                        "type": "authentication_error",
                        "code": "missing_api_key",
                    }
                },
            )

        # Accept master key (constant-time comparison)
        master_key = os.getenv("MASTER_API_KEY", "")
        if master_key and hmac.compare_digest(provided_key, master_key):
            return await call_next(request)

        # Accept legacy single key (backward compat)
        if API_KEY and hmac.compare_digest(provided_key, API_KEY):
            return await call_next(request)

        # Try multi-key validation
        from api.services.api_key_service import APIKeyService

        svc = APIKeyService()
        meta = svc.validate_key(provided_key)
        if meta:
            # ── Scope enforcement ──────────────────────────────────────
            required = _required_scope(request.url.path)
            scopes = meta.get("scopes") or []
            if required and required not in scopes:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "message": (
                                f"API key '{meta['name']}' lacks the '{required}' scope "
                                f"required for {request.url.path}."
                            ),
                            "type": "authorization_error",
                            "code": "insufficient_scope",
                        }
                    },
                )
            request.state.api_key_meta = meta
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key.",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )


# ── Rate Limiting Middleware ───────────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory sliding-window rate limiter keyed by client IP.

    Configurable via RATE_LIMIT_RPM env var (default: 60 req/min).
    Set RATE_LIMIT_RPM=0 to disable.
    """

    def __init__(self, app, rpm: int = RATE_LIMIT_RPM):
        super().__init__(app)
        self.rpm = rpm
        self.window = 60.0  # 1-minute window
        self._requests: dict = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable):
        if self.rpm <= 0:
            return await call_next(request)

        # Skip rate limiting on public paths and static assets — a cold SPA
        # boot fetches the whole ES-module fan-out (~60 files) from one IP,
        # which would otherwise blow the 60-rpm budget and self-429 the app's
        # own API calls. Mirrors the AuthMiddleware exemption (see dispatch above).
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window

        # Prune old entries
        self._requests[client_ip] = [t for t in self._requests[client_ip] if t > cutoff]

        if len(self._requests[client_ip]) >= self.rpm:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": f"Rate limit exceeded. Max {self.rpm} requests per minute.",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(self.rpm),
                    "X-RateLimit-Remaining": "0",
                },
            )

        self._requests[client_ip].append(now)

        response = await call_next(request)
        remaining = max(0, self.rpm - len(self._requests[client_ip]))
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def require_master_key(request: Request) -> None:
    """Validate that the request carries a master-tier API key.

    When global auth is disabled (ENABLE_API_AUTH=false), this is a no-op —
    the operator has chosen to run the service without authentication, so
    the admin gate is also lifted for consistency.

    When global auth is enabled, a key qualifies as "master-tier" when EITHER:
      - it matches the legacy MASTER_API_KEY env var (single-key mode), OR
      - it exists in the keystore with the "keys" scope (covers the
        auto-provisioned first-run-master and any operator-issued keys
        granted that scope explicitly).

    Raises HTTPException(401) if neither path succeeds.
    Use as a FastAPI dependency:

        @router.get("", dependencies=[Depends(require_master_key)])
    """
    # Global auth disabled → no admin gate either.
    if os.getenv("ENABLE_API_AUTH", "true").lower() != "true":
        return

    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Master API key required")

    # Path 1: legacy env-var match.
    env_master = os.getenv("MASTER_API_KEY", "")
    if env_master and hmac.compare_digest(token, env_master):
        return

    # Path 2: keystore match with the "keys" scope.
    from api.services.api_key_service import APIKeyService

    meta = APIKeyService().validate_key(token)
    if meta and "keys" in meta.get("scopes", []):
        return

    raise HTTPException(status_code=401, detail="Master API key required")
