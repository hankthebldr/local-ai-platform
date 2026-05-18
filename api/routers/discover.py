#!/usr/bin/env python3
"""
Discover Router — external ingestion endpoints.

Mounts at ``/api/discover`` and exposes the agentic_discovery service
to the UI. Surfaces the unified MCP-compatible feed of installable
items from upstream registries (MCP Registry, Smithery, GitHub
.prompt.yaml, Composio, etc).

Endpoints
  GET  /api/discover/sources           — provider metadata only
  GET  /api/discover/all                — every feed with items
  GET  /api/discover/{source}           — one feed
  POST /api/discover/{source}/refresh   — bypass cache + re-fetch
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..middleware import require_master_key
from ..services import agentic_discovery as ad

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("/sources", dependencies=[Depends(require_master_key)])
async def list_sources():
    """List every registered discovery provider (no item fetch)."""
    return {"providers": ad.list_providers()}


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
