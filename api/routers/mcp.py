#!/usr/bin/env python3
"""
MCP Router — Register, inspect, and invoke Model Context Protocol servers.

All endpoints require the master API key. MCP servers run arbitrary
local processes (stdio transport) or contact arbitrary URLs (http
transport); operator credentials gate every change.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..middleware import require_master_key
from ..models.mcp_models import (
    MCPServerCreate,
    MCPServerUpdate,
    MCPToolCall,
)
from ..services.mcp_service import get_mcp_service

router = APIRouter(
    prefix="/api/mcp",
    tags=["mcp"],
    dependencies=[Depends(require_master_key)],
)

# ── MCP marketplace (curated catalog + optional remote merge) ───────────────
# A discovery surface analogous to the Skills Lab's: browse well-known MCP
# servers and one-click register them. The curated catalog ships in
# data/discovery/mcp_catalog.json; set ENCLAVE_MCP_CATALOG_URL to merge a
# remote JSON index ({"servers":[...]} or a bare [...] list) alongside it.
_CATALOG_PATH = (
    Path(__file__).parent.parent.parent / "data" / "discovery" / "mcp_catalog.json"
)
_REMOTE_TTL_SECONDS = 600
_remote_cache: Dict[str, Any] = {"ts": 0.0, "url": None, "servers": []}


def _load_catalog() -> Dict[str, Any]:
    try:
        return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"servers": []}
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP catalog read failed: %s", exc)
        return {"servers": []}


def _fetch_remote_catalog(allow_fetch: bool = False) -> List[Dict[str, Any]]:
    """Return the remote MCP catalog. Never raises — degrades to local-only.

    Theme B (no background egress): the TTL used to be evaluated ON READ, so
    opening the MCP marketplace with a stale cache silently egressed to the
    configured catalog. ``allow_fetch=False`` (the default, and every GET) is
    now a pure cache read; only the explicit ⟳ refresh and the install path
    (both operator-initiated POSTs) may touch the network.
    """
    url = os.getenv("ENCLAVE_MCP_CATALOG_URL", "").strip()
    if not url:
        return []
    now = time.time()
    if (
        _remote_cache["url"] == url
        and (now - _remote_cache["ts"]) < _REMOTE_TTL_SECONDS
    ):
        return _remote_cache["servers"]
    if not allow_fetch:
        return _remote_cache["servers"] if _remote_cache["url"] == url else []
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        servers = data.get("servers") if isinstance(data, dict) else data
        servers = [s for s in (servers or []) if isinstance(s, dict) and s.get("id")]
        _remote_cache.update({"ts": now, "url": url, "servers": servers})
        return servers
    except Exception as exc:  # noqa: BLE001
        logger.warning("Remote MCP catalog fetch failed (%s): %s", url, exc)
        return _remote_cache["servers"] if _remote_cache["url"] == url else []


class InstallMcpReq(BaseModel):
    """Register a catalog MCP server, optionally overriding id/name/args and
    supplying required credentials."""

    id: Optional[str] = None
    name: Optional[str] = None
    args: Optional[List[str]] = None
    env: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


@router.get("/discover")
async def discover_mcp() -> Dict[str, Any]:
    """List catalog MCP servers with install state (which catalog ids are
    already registered). Merges any configured remote catalog."""
    cat = _load_catalog()
    servers = list(cat.get("servers") or [])
    seen = {s.get("id") for s in servers}
    remote_count = 0
    for r in _fetch_remote_catalog():
        rid = r.get("id")
        if not rid or rid in seen:
            continue
        rec = dict(r)
        rec["source"] = "remote"
        rec["marketplace"] = True
        servers.append(rec)
        seen.add(rid)
        remote_count += 1

    registered = {s.get("id") for s in get_mcp_service().list_servers()}
    out = []
    for s in servers:
        rec = dict(s)
        rec["installed"] = s.get("id") in registered
        out.append(rec)
    return {
        "schema": cat.get("schema"),
        "version": cat.get("version"),
        "updated": cat.get("updated"),
        "count": len(out),
        "remote_count": remote_count,
        "servers": out,
    }


@router.post("/discover/refresh")
async def refresh_mcp_catalog() -> Dict[str, Any]:
    """Explicit ⟳ — the ONLY way a read of the MCP marketplace reaches the
    network. GET /discover serves the cache (Theme B: no background egress)."""
    url = os.getenv("ENCLAVE_MCP_CATALOG_URL", "").strip()
    if not url:
        return {
            "refreshed": False,
            "reason": "no ENCLAVE_MCP_CATALOG_URL configured",
            "remote_count": 0,
        }
    _remote_cache["ts"] = 0.0  # force past the TTL
    servers = _fetch_remote_catalog(allow_fetch=True)
    return {"refreshed": True, "url": url, "remote_count": len(servers)}


@router.post("/discover/{catalog_id}/install")
async def install_mcp(catalog_id: str, req: InstallMcpReq) -> Dict[str, Any]:
    """Register a catalog MCP server. Builds an MCPServerCreate from the
    catalog entry, applying any id/name/args overrides and supplied env."""
    cat = _load_catalog()
    entry = next(
        (s for s in (cat.get("servers") or []) if s.get("id") == catalog_id),
        None,
    )
    if entry is None:
        # An install is an explicit operator action, so it MAY refresh a
        # cold/stale catalog cache to resolve the entry. Reads never do.
        entry = next(
            (
                s
                for s in _fetch_remote_catalog(allow_fetch=True)
                if s.get("id") == catalog_id
            ),
            None,
        )
    if entry is None:
        raise HTTPException(status_code=404, detail="server not in catalog")

    create = MCPServerCreate(
        id=req.id or entry["id"],
        name=req.name or entry.get("name") or entry["id"],
        description=entry.get("description"),
        transport=entry.get("transport", "stdio"),
        command=entry.get("command"),
        args=req.args if req.args is not None else list(entry.get("args") or []),
        env=req.env or {},
        url=entry.get("url"),
        enabled=req.enabled,
        tags=list(entry.get("tags") or []),
    )
    try:
        registered = get_mcp_service().register(create)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Installed MCP server '%s' from catalog '%s'", create.id, catalog_id)
    return {"installed": True, "server": registered}


@router.get("/servers")
async def list_servers():
    """List all registered MCP servers (secrets masked).

    Each record carries ``provenance`` (LB0-U3), derived from existing state:
    ids present in the shipped local catalog are 'oob' (catalog-installed),
    everything else is 'user' (manually registered). Read-only annotation —
    the local catalog file only, never the remote merge (no egress on GET)."""
    catalog_ids = {s.get("id") for s in (_load_catalog().get("servers") or [])}
    out = []
    for s in get_mcp_service().list_servers():
        rec = dict(s)
        rec["provenance"] = "oob" if rec.get("id") in catalog_ids else "user"
        out.append(rec)
    return out


@router.post("/servers")
async def create_server(body: MCPServerCreate):
    """Register a new MCP server."""
    try:
        return get_mcp_service().register(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/servers/{server_id}")
async def get_server(server_id: str):
    """Return a single server's masked configuration."""
    cfg = get_mcp_service().get_server(server_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="server not found")
    return cfg


@router.patch("/servers/{server_id}")
async def update_server(server_id: str, body: MCPServerUpdate):
    """Patch a server's configuration. Refreshes the tools cache."""
    try:
        return get_mcp_service().update(server_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str):
    """Remove a server registration."""
    removed = get_mcp_service().remove(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail="server not found")
    return {"removed": True, "server_id": server_id}


@router.post("/servers/{server_id}/test")
async def test_server(server_id: str):
    """Perform an MCP initialize+tools/list handshake and return status."""
    try:
        status = get_mcp_service().test_server(server_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    return status.model_dump(mode="json")


@router.get("/servers/{server_id}/tools")
async def list_tools(server_id: str, refresh: bool = False):
    """List tools advertised by a server."""
    try:
        tools = get_mcp_service().list_tools(server_id, force_refresh=refresh)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"discovery failed: {exc}")
    return [t.model_dump(mode="json") for t in tools]


@router.post("/servers/{server_id}/invoke")
async def invoke_tool(server_id: str, body: MCPToolCall):
    """Invoke a tool on the server and return its JSON-RPC result."""
    try:
        return get_mcp_service().invoke_tool(server_id, body.tool, body.arguments)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
