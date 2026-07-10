#!/usr/bin/env python3
"""
Discover Router — external ingestion endpoints.

Mounts at ``/api/discover`` and exposes the agentic_discovery service
to the UI. Surfaces the unified MCP-compatible feed of installable
items from upstream registries (MCP Registry, Smithery, GitHub
.prompt.yaml, Composio, etc).

Endpoints
  GET  /api/discover/sources           — provider metadata only
  GET  /api/discover/config             — operator source config (masked)
  PUT  /api/discover/config             — persist source config (LB0-U2)
  GET  /api/discover/all                — every feed with items
  GET  /api/discover/{source}           — one feed
  POST /api/discover/{source}/refresh   — bypass cache + re-fetch

Route-ordering hazard: ``/config`` MUST stay registered BEFORE the
``/{source}`` catch-all (FastAPI matches in registration order), and
``config`` is a reserved source name in ``agentic_discovery`` so no
provider can ever shadow it.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..middleware import require_master_key
from ..services import agentic_discovery as ad

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("/sources", dependencies=[Depends(require_master_key)])
async def list_sources():
    """List every registered discovery provider (no item fetch)."""
    return {"providers": ad.list_providers()}


# ── Sources config (LB0-U2) — BEFORE the /{source} catch-all ────────


class SourcesConfigUpdate(BaseModel):
    """Partial update — only provided fields are persisted."""

    skill_repos: Optional[List[str]] = None
    plugin_marketplaces: Optional[List[str]] = None
    prompt_digest_sources: Optional[List[str]] = None
    catalog_urls: Optional[Dict[str, str]] = None
    cache_ttls: Optional[Dict[str, float]] = None
    github_token: Optional[str] = None


# owner/repo only — these get spliced into GitHub API/raw URLs, so the
# charset allowlist doubles as a traversal/injection guard. Owner must
# start alphanumeric (GitHub rule — also excludes '.'/'..' owners); repo
# may start with '.' (e.g. '.github') but dot-only segments are rejected
# below so no entry can ever URL-normalize into a different API path.
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[A-Za-z0-9_.-]{1,120}$")
_DOT_SEGMENTS = {".", ".."}
_TTL_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")  # provider ids + 'default'
_CATALOG_KEYS = {"skills", "mcp"}


def _validate_sources_update(update: "SourcesConfigUpdate") -> None:
    for field_name in ("skill_repos", "plugin_marketplaces", "prompt_digest_sources"):
        entries = getattr(update, field_name)
        if entries is None:
            continue
        for entry in entries:
            cleaned = (entry or "").strip()
            if not _REPO_RE.match(cleaned) or any(
                seg in _DOT_SEGMENTS for seg in cleaned.split("/")
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name}: '{entry}' is not a valid owner/repo",
                )
    if update.catalog_urls is not None:
        for key, url in update.catalog_urls.items():
            if key not in _CATALOG_KEYS:
                raise HTTPException(
                    status_code=400, detail=f"catalog_urls: unknown key '{key}'"
                )
            u = (url or "").strip()
            if u and not (u.startswith("https://") or u.startswith("http://")):
                raise HTTPException(
                    status_code=400,
                    detail=f"catalog_urls.{key}: must be an http(s) URL or empty",
                )
    if update.cache_ttls is not None:
        for key, ttl in update.cache_ttls.items():
            if not _TTL_KEY_RE.match(key or ""):
                raise HTTPException(
                    status_code=400, detail=f"cache_ttls: bad source key '{key}'"
                )
            if not math.isfinite(ttl) or ttl < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"cache_ttls.{key}: must be a finite number >= 0",
                )
    if update.github_token is not None:
        tok = update.github_token
        if len(tok) > 200 or any(c in tok for c in "\r\n\t"):
            # Never echo or log the offending value — it may be a secret.
            raise HTTPException(status_code=400, detail="github_token: malformed")


@router.get("/config", dependencies=[Depends(require_master_key)])
async def get_sources_config():
    """Operator source config — token masked, never echoed raw."""
    return ad.masked_sources_config()


@router.put("/config", dependencies=[Depends(require_master_key)])
async def put_sources_config(update: SourcesConfigUpdate):
    """Persist source config to data/config/discovery_sources.json.

    Atomic tmp+replace, chmod 0600. Providers read the file at fetch
    time, so changes govern the next refresh without a restart.
    """
    _validate_sources_update(update)
    return ad.update_sources_config(update.model_dump(exclude_unset=True))


@router.get("/all", dependencies=[Depends(require_master_key)])
async def all_feeds(force: bool = False):
    """Fetch every provider's feed at once."""
    return {"feeds": ad.get_all_feeds(force=force)}


@router.get("/{source}", dependencies=[Depends(require_master_key)])
async def one_feed(source: str, force: bool = False):
    """Fetch one provider's feed."""
    try:
        feed = ad.get_feed(source, force=force)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"unknown discovery provider '{source}'"
        )
    return feed.to_dict()


@router.post("/{source}/refresh", dependencies=[Depends(require_master_key)])
async def refresh(source: str):
    """Bypass cache and re-fetch one provider."""
    try:
        feed = ad.get_feed(source, force=True)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"unknown discovery provider '{source}'"
        )
    return feed.to_dict(with_items=False)
