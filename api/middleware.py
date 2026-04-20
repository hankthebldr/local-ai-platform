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

PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


# ── Scope enforcement ──────────────────────────────────────────────────────
# Maps URL path prefixes to the scope that a key must hold to access them.
# Requests to paths not listed here are unrestricted (beyond base auth).
SCOPE_MAP = {
    "/v1/chat/": "chat",
    "/v1/completions": "completions",
    "/v1/models": "models",
    "/api/documents": "documents",
    "/api/memory": "memory",
    "/api/context": "context",
    "/api/profiles": "profiles",
    "/api/plugins": "plugins",
    "/api/workflows": "workflows",
    "/api/keys": "keys",  # master key bypasses this before scope check
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
    Disabled entirely when ENABLE_API_AUTH=false or API_KEY is empty.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip if auth is disabled (read at request time for testability)
        if os.getenv("ENABLE_API_AUTH", "false").lower() != "true":
            return await call_next(request)

        # Skip public paths
        if request.url.path in PUBLIC_PATHS:
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
            # ── Scope enforcement ──────────────────────────────────
            required = _required_scope(request.url.path)
            scopes = meta.get("scopes") or []
            if required and required not in scopes:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "message": (
                                f"API key '{meta['name']}' lacks the '{required}' scope "
                                f"required for {request.url.path}. Key scopes: {scopes}."
                            ),
                            "type": "authorization_error",
                            "code": "insufficient_scope",
                        }
                    },
                )

            # Store metadata for downstream use
            request.state.api_key_meta = meta

            # Execute request
            response = await call_next(request)

            # ── Usage tracking ─────────────────────────────────────
            # Best-effort: tokens aren't always available in middleware.
            # We always increment total_requests via tokens_used=0;
            # token-specific tracking is the responsibility of the
            # endpoint if it wants to attach an X-Tokens-Used response header.
            try:
                tokens_used = int(response.headers.get("X-Tokens-Used", "0") or "0")
            except (ValueError, TypeError):
                tokens_used = 0
            try:
                svc.update_usage(meta["id"], tokens_used=tokens_used)
            except Exception:
                # Never let usage tracking break the response
                pass

            return response

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

        # Skip rate limiting on public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window

        # Prune old entries
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > cutoff
        ]

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
