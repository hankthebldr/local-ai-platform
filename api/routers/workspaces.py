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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..logging_config import logger
from ..middleware import require_master_key
from ..services.workspace import (
    WorkspaceError,
    WorkspacePolicy,
    WorkspaceQuotaExceeded,
    WorkspaceViolation,
    get_workspace_registry,
)
from ..services.workspace_index import INDEX_SUBDIR, WorkspaceIndex, _slug

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# Operate U10 hardening: workspaces mutate the local filesystem (create/delete a
# binding, write/edit/expand a file, drive an index worklist). Those are the
# **real** write surface — gate them all on the master key (a no-op when
# ENABLE_API_AUTH is off, the master gate otherwise). Reads (list/get/files/
# search/index inspection) stay open. The prefix keeps its existing SCOPE_MAP
# 'workspaces' scope for base auth; this is the additive write gate on top.
_MASTER = [Depends(require_master_key)]


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


class AddItemsBody(BaseModel):
    items: List[dict]


class StatusBody(BaseModel):
    status: str
    artifact: Optional[str] = None
    note: Optional[str] = None


class RenderBody(BaseModel):
    path: Optional[str] = None


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
@router.post("", dependencies=_MASTER)
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


@router.delete("/{name}", dependencies=_MASTER)
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


@router.put("/{name}/file", dependencies=_MASTER)
def write_file(name: str, body: WriteBody):
    """make — create or overwrite a file."""
    ws = _ws(name)
    return _guard(lambda: ws.write(body.path, body.content))


@router.post("/{name}/edit", dependencies=_MASTER)
def edit_file(name: str, body: EditBody):
    """edit — literal find/replace."""
    ws = _ws(name)
    return _guard(lambda: ws.edit(body.path, body.find, body.replace, body.count))


@router.post("/{name}/expand", dependencies=_MASTER)
def expand_file(name: str, body: ExpandBody):
    """expand — append, or insert under a markdown heading."""
    ws = _ws(name)
    return _guard(lambda: ws.expand(body.path, body.content, body.heading))


# ── durable index / worklist (C3) ───
def _index(name: str, index: str) -> WorkspaceIndex:
    return WorkspaceIndex(_ws(name), index)


def _item_payload(idx: WorkspaceIndex) -> dict:
    return {
        "name": idx.name,
        "counts": idx.counts(),
        "complete": idx.is_complete(),
        "items": [it.model_dump() for it in idx.items()],
    }


@router.get("/{name}/indexes")
def list_indexes(name: str):
    """List every durable worklist index bound to this workspace (U10).

    Reads the ``.enclave/index/*.json`` state files and returns each index's
    name + counts + completion — the Artifacts tab Workspaces pane renders these
    with Requeue-stale / Render-MOC buttons. Read-only; the index files live
    inside the workspace root (containment enforced by WorkspaceIndex)."""
    ws = _ws(name)
    idx_dir = (ws.root / INDEX_SUBDIR).resolve()
    out = []
    if idx_dir.is_dir():
        try:
            idx_dir.relative_to(ws.root)
        except ValueError:  # pragma: no cover — defensive
            raise HTTPException(status_code=400, detail="index dir escapes workspace")
        for f in sorted(idx_dir.glob("*.json")):
            idx = WorkspaceIndex(ws, f.stem)
            out.append(
                {
                    "name": idx.name,
                    "slug": _slug(f.stem),
                    "counts": idx.counts(),
                    "complete": idx.is_complete(),
                }
            )
    return {"indexes": out}


@router.get("/{name}/index/{index}")
def get_index(name: str, index: str):
    return _guard(lambda: _item_payload(_index(name, index)))


@router.post("/{name}/index/{index}/items", dependencies=_MASTER)
def add_index_items(name: str, index: str, body: AddItemsBody):
    idx = _index(name, index)
    return _guard(lambda: {**idx.add_items(body.items), "counts": idx.counts()})


@router.post("/{name}/index/{index}/next", dependencies=_MASTER)
def next_pending(name: str, index: str, requeue_stale: bool = False):
    """Claim the next pending item (marks it in_progress). Pass
    requeue_stale=true at loop start to first reclaim interrupted items."""
    idx = _index(name, index)

    def run():
        if requeue_stale:
            idx.requeue_stale()
        nxt = idx.next_pending(claim=True)
        return {"item": nxt.model_dump() if nxt else None, "counts": idx.counts()}

    return _guard(run)


@router.post("/{name}/index/{index}/requeue", dependencies=_MASTER)
def requeue_stale(name: str, index: str):
    """Reclaim interrupted (in_progress) items back to pending — resume prep.
    Does NOT claim a new item (unlike /next)."""
    idx = _index(name, index)

    def run():
        n = idx.requeue_stale()
        return {"requeued": n, "counts": idx.counts()}

    return _guard(run)


@router.post("/{name}/index/{index}/items/{item_id}/status", dependencies=_MASTER)
def set_index_status(name: str, index: str, item_id: str, body: StatusBody):
    idx = _index(name, index)
    return _guard(
        lambda: idx.set_status(item_id, body.status, body.artifact, body.note).model_dump()
    )


@router.post("/{name}/index/{index}/render", dependencies=_MASTER)
def render_index(name: str, index: str, body: RenderBody):
    idx = _index(name, index)
    return _guard(lambda: {"rendered": idx.render_markdown(body.path)})
