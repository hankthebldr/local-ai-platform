#!/usr/bin/env python3
"""
Workspaces Router — durable named local directories for autonomous workflows.

CRUD over Workspace bindings + the make / edit / expand / read / list / search
file operations that let a workflow (or an operator, or a LangGraph run)
"access a file on the local host to make, edit, expand markdown."

See api/services/workspace.py and C2 of
docs/plans/2026-07-09-fusion-autonomous-local-workspace-feature-request.md.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..logging_config import logger
from ..services.workspace import (
    WorkspaceError,
    WorkspacePolicy,
    WorkspaceQuotaExceeded,
    WorkspaceViolation,
    get_workspace_registry,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ── request bodies ───
class CreateWorkspaceBody(BaseModel):
    name: str
    root: str
    description: Optional[str] = None
    policy: Optional[WorkspacePolicy] = None


class WriteBody(BaseModel):
    path: str
    content: str


class EditBody(BaseModel):
    path: str
    find: str
    replace: str
    count: int = 0


class ExpandBody(BaseModel):
    path: str
    content: str
    heading: Optional[str] = None


def _guard(fn):
    """Map workspace exceptions to clean HTTP codes."""
    try:
        return fn()
    except (WorkspaceViolation,) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except WorkspaceQuotaExceeded as e:
        raise HTTPException(status_code=413, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except WorkspaceError as e:
        # not-found vs conflict both surface as WorkspaceError; 400 is the safe
        # generic. "not found" is refined to 404 by the callers that know.
        raise HTTPException(status_code=400, detail=str(e))


# ── CRUD ───
@router.post("")
def create_workspace(body: CreateWorkspaceBody):
    reg = get_workspace_registry()
    ws = _guard(
        lambda: reg.create(body.name, body.root, body.policy, body.description)
    )
    return {"workspace": ws.meta.model_dump(), "stats": ws.stats()}


@router.get("")
def list_workspaces():
    reg = get_workspace_registry()
    return {"workspaces": [m.model_dump() for m in reg.list()]}


@router.get("/{name}")
def get_workspace(name: str):
    reg = get_workspace_registry()
    try:
        ws = reg.get(name)
    except WorkspaceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"workspace": ws.meta.model_dump(), "stats": ws.stats()}


@router.delete("/{name}")
def delete_workspace(name: str):
    reg = get_workspace_registry()
    try:
        reg.delete(name)
    except WorkspaceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": name}


def _ws(name: str):
    try:
        return get_workspace_registry().get(name)
    except WorkspaceError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── file operations ───
@router.get("/{name}/files")
def list_files(name: str, subdir: str = "", glob: str = "**/*"):
    ws = _ws(name)
    return {"files": _guard(lambda: ws.list(subdir, glob))}


@router.get("/{name}/file")
def read_file(name: str, path: str):
    ws = _ws(name)
    return {"path": path, "content": _guard(lambda: ws.read(path))}


@router.get("/{name}/search")
def search(name: str, q: str, glob: str = "**/*.md"):
    ws = _ws(name)
    return {"query": q, "hits": _guard(lambda: ws.search(q, glob))}


@router.put("/{name}/file")
def write_file(name: str, body: WriteBody):
    """make — create or overwrite a file."""
    ws = _ws(name)
    return _guard(lambda: ws.write(body.path, body.content))


@router.post("/{name}/edit")
def edit_file(name: str, body: EditBody):
    """edit — literal find/replace."""
    ws = _ws(name)
    return _guard(lambda: ws.edit(body.path, body.find, body.replace, body.count))


@router.post("/{name}/expand")
def expand_file(name: str, body: ExpandBody):
    """expand — append, or insert under a markdown heading."""
    ws = _ws(name)
    return _guard(lambda: ws.expand(body.path, body.content, body.heading))
