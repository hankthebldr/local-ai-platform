#!/usr/bin/env python3
"""
Workflow Index Router — catalogue, import, export.

This is the high-level entry point for the Composer's "Workflow Index"
view. It complements /api/workflows (which deals with single workflow
CRUD and execution) by surfacing categorisation and portable bundle
operations.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ..services.workflow_index import get_workflow_index

router = APIRouter(prefix="/api/workflow-index", tags=["workflow-index"])


@router.get("")
async def list_index():
    """Return all workflows grouped by inferred category."""
    return get_workflow_index().build_index()


@router.get("/categories")
async def list_categories():
    """Return distinct categories with workflow counts."""
    index = get_workflow_index().build_index()
    return {"categories": index["categories"]}


@router.get("/{workflow_id}/export")
async def export_bundle(workflow_id: str):
    """Build a portable bundle for the named workflow."""
    try:
        return get_workflow_index().export_bundle(workflow_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="workflow not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import")
async def import_bundle(body: Dict[str, Any], overwrite: bool = False):
    """Install a workflow bundle (workflow + referenced agents)."""
    try:
        return get_workflow_index().import_bundle(body, overwrite=overwrite)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"workflow '{exc}' already exists; pass ?overwrite=true to replace",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
