#!/usr/bin/env python3
"""
MCP Router — Register, inspect, and invoke Model Context Protocol servers.

All endpoints require the master API key. MCP servers run arbitrary
local processes (stdio transport) or contact arbitrary URLs (http
transport); operator credentials gate every change.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..middleware import require_master_key
from ..models.mcp_models import (
    MCPServerCreate,
    MCPServerUpdate,
    MCPToolCall,
)
from ..services.mcp_service import get_mcp_service

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# Read-only GETs are open for discoverability (composer palette / MCPs
# workbench needs them on the default landing). Mutations + invocations
# still require the master key — declared per-route below.


@router.get("/servers")
async def list_servers():
    """List all registered MCP servers (secrets masked). Public read."""
    return get_mcp_service().list_servers()


@router.post("/servers", dependencies=[Depends(require_master_key)])
async def create_server(body: MCPServerCreate):
    """Register a new MCP server."""
    try:
        return get_mcp_service().register(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/servers/{server_id}")
async def get_server(server_id: str):
    """Return a single server's masked configuration. Public read."""
    cfg = get_mcp_service().get_server(server_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="server not found")
    return cfg


@router.patch("/servers/{server_id}", dependencies=[Depends(require_master_key)])
async def update_server(server_id: str, body: MCPServerUpdate):
    """Patch a server's configuration. Refreshes the tools cache."""
    try:
        return get_mcp_service().update(server_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/servers/{server_id}", dependencies=[Depends(require_master_key)])
async def delete_server(server_id: str):
    """Remove a server registration."""
    removed = get_mcp_service().remove(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail="server not found")
    return {"removed": True, "server_id": server_id}


@router.post("/servers/{server_id}/test", dependencies=[Depends(require_master_key)])
async def test_server(server_id: str):
    """Perform an MCP initialize+tools/list handshake and return status."""
    try:
        status = get_mcp_service().test_server(server_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    return status.model_dump(mode="json")


@router.get("/servers/{server_id}/tools")
async def list_tools(server_id: str, refresh: bool = False):
    """List tools advertised by a server. Public read."""
    try:
        tools = get_mcp_service().list_tools(server_id, force_refresh=refresh)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"discovery failed: {exc}")
    return [t.model_dump(mode="json") for t in tools]


@router.post("/servers/{server_id}/invoke", dependencies=[Depends(require_master_key)])
async def invoke_tool(server_id: str, body: MCPToolCall):
    """Invoke a tool on the server and return its JSON-RPC result."""
    try:
        return get_mcp_service().invoke_tool(server_id, body.tool, body.arguments)
    except KeyError:
        raise HTTPException(status_code=404, detail="server not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
