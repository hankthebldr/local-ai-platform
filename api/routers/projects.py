#!/usr/bin/env python3
"""
Projects Router — CRUD + bundle operations for project records.
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ..models.project_models import ProjectCreate, ProjectUpdate
from ..services.project_service import get_project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def list_projects():
    return get_project_service().list_projects()


@router.post("")
async def create_project(body: ProjectCreate):
    try:
        return get_project_service().create_project(body)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"project '{exc}' already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{project_id}")
async def get_project(project_id: str):
    try:
        result = get_project_service().get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="project not found")
    return result


@router.patch("/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    try:
        return get_project_service().update_project(project_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    try:
        removed = get_project_service().delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not removed:
        raise HTTPException(status_code=404, detail="project not found")
    return {"removed": True, "project_id": project_id}


@router.post("/{project_id}/artifacts/{kind}/{artifact_id}")
async def add_artifact(project_id: str, kind: str, artifact_id: str):
    try:
        return get_project_service().add_artifact(project_id, kind, artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{project_id}/artifacts/{kind}/{artifact_id}")
async def remove_artifact(project_id: str, kind: str, artifact_id: str):
    try:
        return get_project_service().remove_artifact(project_id, kind, artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{project_id}/export")
async def export_bundle(project_id: str):
    try:
        return get_project_service().export_bundle(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Kanban task management ────────────────────────────────────────────────
# Lightweight task tracker scoped to a project. Tasks live as a JSONL file
# under data/projects/<id>/tasks.jsonl. Three columns: todo · doing · done.

import json as _json
import os as _os
import uuid as _uuid
from datetime import datetime as _dt
from pathlib import Path as _Path

_DATA_DIR = _Path(_os.getenv("DATA_PROJECTS_DIR", "data/projects"))


def _tasks_path(project_id: str) -> _Path:
    safe = "".join(c for c in project_id if c.isalnum() or c in "-_.")
    if not safe or safe != project_id:
        raise HTTPException(status_code=400, detail="invalid project id")
    p = _DATA_DIR / safe
    p.mkdir(parents=True, exist_ok=True)
    return p / "tasks.jsonl"


def _read_tasks(project_id: str) -> list[dict]:
    p = _tasks_path(project_id)
    if not p.exists():
        return []
    tasks: dict[str, dict] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        tid = evt.get("id")
        if not tid:
            continue
        op = evt.get("op")
        if op == "del":
            tasks.pop(tid, None)
        else:
            current = tasks.get(tid, {})
            current.update(evt)
            current.pop("op", None)
            tasks[tid] = current
    out = list(tasks.values())
    out.sort(key=lambda t: t.get("position", 0))
    return out


def _append_event(project_id: str, evt: dict) -> None:
    p = _tasks_path(project_id)
    evt["ts"] = _dt.utcnow().isoformat() + "Z"
    with p.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(evt, default=str) + "\n")


@router.get("/{project_id}/tasks")
async def list_tasks(project_id: str):
    return _read_tasks(project_id)


@router.post("/{project_id}/tasks")
async def create_task(project_id: str, body: Dict[str, Any]):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    column = body.get("column") or "todo"
    if column not in ("todo", "doing", "done"):
        raise HTTPException(status_code=400, detail="column must be todo|doing|done")
    # Millisecond timestamps alone collide when tasks are created in rapid
    # succession (same-ms ids merge during JSONL replay) — suffix a random
    # nibble run so every create yields a distinct task id.
    tid = f"task_{int(_dt.utcnow().timestamp() * 1000):x}_{_uuid.uuid4().hex[:6]}"
    evt = {
        "id": tid,
        "title": title[:240],
        "description": (body.get("description") or "")[:4000],
        "column": column,
        "position": int(body.get("position") or _dt.utcnow().timestamp()),
        "labels": list(body.get("labels") or [])[:8],
        "assignee": (body.get("assignee") or "").strip()[:80] or None,
        "created_at": _dt.utcnow().isoformat() + "Z",
    }
    _append_event(project_id, evt)
    return evt


@router.patch("/{project_id}/tasks/{task_id}")
async def update_task(project_id: str, task_id: str, body: Dict[str, Any]):
    allowed = {"title", "description", "column", "position", "labels", "assignee"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if "column" in patch and patch["column"] not in ("todo", "doing", "done"):
        raise HTTPException(status_code=400, detail="column must be todo|doing|done")
    patch["id"] = task_id
    _append_event(project_id, patch)
    # Return the current resolved view of the task so the SPA doesn't need
    # to re-fetch the whole list after every move.
    for t in _read_tasks(project_id):
        if t.get("id") == task_id:
            return t
    raise HTTPException(status_code=404, detail="task not found")


@router.delete("/{project_id}/tasks/{task_id}")
async def delete_task(project_id: str, task_id: str):
    _append_event(project_id, {"id": task_id, "op": "del"})
    return {"removed": True, "id": task_id}


@router.post("/import")
async def import_bundle(body: Dict[str, Any], overwrite: bool = False):
    try:
        return get_project_service().import_bundle(body, overwrite=overwrite)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"project '{exc}' already exists; pass ?overwrite=true to replace",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
