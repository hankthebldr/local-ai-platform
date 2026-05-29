#!/usr/bin/env python3
"""
Plugins Router — List, install, and invoke plugin tools.

Discovery walks two layers (Phase 1.2): the read-only system layer that ships
with the app/image and the writable user layer under the deployment's
user_storage_root. ``PLUGINS_DIR`` overrides the system layer (used by tests);
otherwise both layers are resolved from the active Deployment.
"""

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..middleware import require_master_key
from ..services.plugin_service import PluginService

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _build_service() -> PluginService:
    """Construct a PluginService over (system, user) layers.

    PLUGINS_DIR pins the system layer when set; the user layer always comes
    from the active deployment so installs land somewhere writable. If the
    deployment singleton isn't installed yet, PluginService falls back to its
    own auto-resolution.
    """
    system_override = os.getenv("PLUGINS_DIR")
    user_dir = None
    try:
        from ..services.deployment import _get_current as _get_dep

        d = _get_dep()
        user_dir = d.user_storage_root / "plugins"
        system_dir = (
            Path(system_override)
            if system_override
            else (d.system_storage_root / "plugins")
        )
    except Exception:
        system_dir = Path(system_override) if system_override else None

    if system_dir is None and user_dir is None:
        return PluginService()
    return PluginService(system_dir=system_dir, user_dir=user_dir)


plugin_service = _build_service()
plugin_service.scan_plugins()


@router.get("", dependencies=[Depends(require_master_key)])
async def list_plugins():
    """List all discovered plugins (each carries origin: system|user)."""
    return plugin_service.list_plugins()


@router.post("/install", dependencies=[Depends(require_master_key)])
async def install_plugin(plugin: UploadFile = File(...)):
    """Install a plugin tarball into the writable user layer."""
    suffix = "".join(Path(plugin.filename or "plugin.tar.gz").suffixes) or ".tar.gz"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            shutil.copyfileobj(plugin.file, fh)
            tmp = Path(fh.name)
        installed = plugin_service.install_plugin(tmp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp and tmp.exists():
            tmp.unlink()
    return {"installed": installed["id"], "plugin": installed}


@router.get("/{plugin_id}", dependencies=[Depends(require_master_key)])
async def get_plugin(plugin_id: str):
    """Get plugin details."""
    plugin = plugin_service.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@router.delete("/{plugin_id}", dependencies=[Depends(require_master_key)])
async def uninstall_plugin(plugin_id: str):
    """Remove a user-layer plugin. System-layer plugins are protected (403)."""
    try:
        plugin_service.uninstall_plugin(plugin_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Plugin not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"deleted": plugin_id}


@router.post("/{plugin_id}/tools/{tool_id}", dependencies=[Depends(require_master_key)])
async def invoke_tool(plugin_id: str, tool_id: str, params: dict):
    """Invoke a plugin tool."""
    try:
        result = plugin_service.call_tool(plugin_id, tool_id, params)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result
