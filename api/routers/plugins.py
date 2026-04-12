#!/usr/bin/env python3
"""
Plugins Router — List plugins and invoke tools
"""

import os
from fastapi import APIRouter, HTTPException

from ..services.plugin_service import PluginService

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_plugins_dir = os.getenv("PLUGINS_DIR", "plugins")
_service = PluginService(plugins_dir=_plugins_dir)
_service.scan_plugins()


@router.get("")
async def list_plugins():
    """List all discovered plugins"""
    return _service.list_plugins()


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str):
    """Get plugin details"""
    plugins = _service.list_plugins()
    for p in plugins:
        if p["id"] == plugin_id:
            return p
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/{plugin_id}/tools/{tool_id}")
async def invoke_tool(plugin_id: str, tool_id: str, params: dict):
    """Invoke a plugin tool"""
    try:
        result = _service.call_tool(plugin_id, tool_id, params)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result
