#!/usr/bin/env python3
"""
Plugins Router — List plugins and invoke tools
"""

import os
from fastapi import APIRouter, Depends, HTTPException

from ..middleware import require_master_key
from ..services.plugin_service import PluginService

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_plugins_dir = os.getenv("PLUGINS_DIR", "plugins")
plugin_service = PluginService(plugins_dir=_plugins_dir)
plugin_service.scan_plugins()


@router.get("", dependencies=[Depends(require_master_key)])
async def list_plugins():
    """List all discovered plugins"""
    return plugin_service.list_plugins()


@router.get("/{plugin_id}", dependencies=[Depends(require_master_key)])
async def get_plugin(plugin_id: str):
    """Get plugin details"""
    plugins = plugin_service.list_plugins()
    for p in plugins:
        if p["id"] == plugin_id:
            return p
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/{plugin_id}/tools/{tool_id}", dependencies=[Depends(require_master_key)])
async def invoke_tool(plugin_id: str, tool_id: str, params: dict):
    """Invoke a plugin tool"""
    try:
        result = plugin_service.call_tool(plugin_id, tool_id, params)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result
