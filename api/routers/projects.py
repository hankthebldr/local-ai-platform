#!/usr/bin/env python3
"""
Projects Router — CRUD + bundle operations for project records.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..middleware import require_master_key
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
# under data/projects/<id>/tasks.jsonl. Five additive columns:
#   backlog · todo · doing · review · done
# The legacy todo/doing/done trio is untouched; backlog+review are additive
# (no column↔status remap — judge-rejected). Task metadata is dict-merged on
# replay, so new fields (due_date/start_date/estimate/priority/milestone) cost
# no schema migration. AI plan-ops land in this SAME log stamped
# origin:"agent" + state:"proposed"; normal replay skips proposed events and
# reject markers, so an unaccepted proposal is invisible to the board.

import json as _json
import os as _os
import re as _re
import uuid as _uuid
from datetime import datetime as _dt
from pathlib import Path as _Path

_DATA_DIR = _Path(_os.getenv("DATA_PROJECTS_DIR", "data/projects"))

# Additive column enum — legacy todo/doing/done kept; backlog/review new.
COLUMNS = ("backlog", "todo", "doing", "review", "done")
PRIORITIES = ("p0", "p1", "p2", "p3")
# Fields an agent/operator may set on a task beyond the core kanban set.
_EXTRA_FIELDS = {"due_date", "start_date", "estimate", "priority", "milestone"}
_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Cap on pending (unaccepted) proposals per project — groundwork for U12.
MAX_PENDING_PROPOSALS = 50


def _tasks_path(project_id: str) -> _Path:
    safe = "".join(c for c in project_id if c.isalnum() or c in "-_.")
    if not safe or safe != project_id:
        raise HTTPException(status_code=400, detail="invalid project id")
    p = _DATA_DIR / safe
    p.mkdir(parents=True, exist_ok=True)
    return p / "tasks.jsonl"


def _iter_events(project_id: str):
    """Yield parsed task events in append order (torn-line tolerant)."""
    p = _tasks_path(project_id)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield _json.loads(line)
        except _json.JSONDecodeError:
            continue


def _new_proposal_id() -> str:
    return f"prop_{int(_dt.utcnow().timestamp() * 1000):x}_{_uuid.uuid4().hex[:6]}"


def _read_tasks(
    project_id: str, *, history: bool = False, include_proposed: bool = False
) -> list[dict]:
    """Replay the task log into the current task view.

    - Events stamped ``state=="proposed"`` (AI plan-ops awaiting accept) are
      skipped unless ``include_proposed`` — an accepted proposal re-appends the
      effective event without that flag, so it materialises normally.
    - ``op=="reject"`` markers are skipped (they only annul a proposal id).
    - ``history=True`` accumulates a per-task ``history:[{ts, column}]`` trail
      from the already-persisted per-event ``ts`` (zero new writes) — feeds the
      Timeline markers + drawer status trail.
    """
    tasks: dict[str, dict] = {}
    hist: dict[str, list] = {}
    for evt in _iter_events(project_id):
        op = evt.get("op")
        if op == "reject":
            continue
        if evt.get("state") == "proposed" and not include_proposed:
            continue
        tid = evt.get("id")
        if not tid:
            continue
        if op == "del":
            tasks.pop(tid, None)
            hist.pop(tid, None)
            continue
        current = tasks.get(tid, {})
        current.update(evt)
        current.pop("op", None)
        tasks[tid] = current
        if history and evt.get("column"):
            hist.setdefault(tid, []).append(
                {"ts": evt.get("ts"), "column": evt.get("column")}
            )
    if history:
        for tid, t in tasks.items():
            t["history"] = hist.get(tid, [])
    out = list(tasks.values())
    out.sort(key=lambda t: t.get("position", 0))
    return out


def _pending_proposal_count(project_id: str) -> int:
    """Count proposal ids that were proposed but never accepted/rejected —
    groundwork for the U12 50-per-project cap (409)."""
    proposed: set[str] = set()
    resolved: set[str] = set()
    for evt in _iter_events(project_id):
        pid = evt.get("proposal_id")
        if not pid:
            continue
        if evt.get("state") == "proposed":
            proposed.add(pid)
        elif evt.get("op") == "reject" or evt.get("approved_at"):
            resolved.add(pid)
    return len(proposed - resolved)


def _append_event(project_id: str, evt: dict) -> None:
    p = _tasks_path(project_id)
    evt["ts"] = _dt.utcnow().isoformat() + "Z"
    with p.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(evt, default=str) + "\n")


def _coerce_extra_fields(body: Dict[str, Any], patch: dict) -> None:
    """Validate + copy the whitelisted extra task fields into ``patch``.

    due_date/start_date accept an ISO ``YYYY-MM-DD`` string (or ``""``/None to
    clear); estimate is a display-only number ≤16; priority is p0–p3; milestone
    is a ≤80-char string. ``origin`` is server-set and never taken from input.
    """
    for key in ("due_date", "start_date"):
        if key in body:
            val = body.get(key)
            if val in (None, ""):
                patch[key] = None
            elif isinstance(val, str) and _DATE_RE.match(val):
                patch[key] = val
            else:
                raise HTTPException(
                    status_code=400, detail=f"{key} must be an ISO date (YYYY-MM-DD)"
                )
    if "estimate" in body:
        val = body.get("estimate")
        if val in (None, ""):
            patch["estimate"] = None
        else:
            try:
                num = float(val)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="estimate must be a number")
            if num < 0 or num > 16:
                raise HTTPException(status_code=400, detail="estimate must be 0..16")
            patch["estimate"] = int(num) if num == int(num) else num
    if "priority" in body:
        val = body.get("priority")
        if val in (None, ""):
            patch["priority"] = None
        elif val in PRIORITIES:
            patch["priority"] = val
        else:
            raise HTTPException(
                status_code=400, detail="priority must be p0|p1|p2|p3"
            )
    if "milestone" in body:
        val = body.get("milestone")
        patch["milestone"] = (str(val).strip()[:80] or None) if val else None


@router.get("/{project_id}/tasks")
async def list_tasks(project_id: str, history: int = 0):
    return _read_tasks(project_id, history=bool(history))


@router.post("/{project_id}/tasks")
async def create_task(project_id: str, body: Dict[str, Any]):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    column = body.get("column") or "todo"
    if column not in COLUMNS:
        raise HTTPException(
            status_code=400, detail="column must be " + "|".join(COLUMNS)
        )
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
        # origin is server-set and NOT PATCHable — operator creates are
        # "operator"; AI plan-ops (U12) append their own with origin:"agent".
        "origin": "operator",
        "created_at": _dt.utcnow().isoformat() + "Z",
    }
    _coerce_extra_fields(body, evt)
    _append_event(project_id, evt)
    return evt


@router.patch("/{project_id}/tasks/{task_id}")
async def update_task(project_id: str, task_id: str, body: Dict[str, Any]):
    allowed = {"title", "description", "column", "position", "labels", "assignee"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if "column" in patch and patch["column"] not in COLUMNS:
        raise HTTPException(
            status_code=400, detail="column must be " + "|".join(COLUMNS)
        )
    _coerce_extra_fields(body, patch)
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


# ── Project-side run refs ──────────────────────────────────────────────────
# data/projects/<id>/runs.jsonl records runs launched from this project. The
# frozen engine is untouched; the UI labels these refs best-effort with live
# status from GET /api/workflows/runs/{run_id}. seed convention (adopted now,
# reconciler deferred): every project-initiated run passes
#   seed:{project_id, task_id?}
# into run-async, so a run can be traced back to its project + task.


def _runs_path(project_id: str) -> _Path:
    safe = "".join(c for c in project_id if c.isalnum() or c in "-_.")
    if not safe or safe != project_id:
        raise HTTPException(status_code=400, detail="invalid project id")
    p = _DATA_DIR / safe
    p.mkdir(parents=True, exist_ok=True)
    return p / "runs.jsonl"


def _read_runs(project_id: str) -> list[dict]:
    p = _runs_path(project_id)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(_json.loads(line))
        except _json.JSONDecodeError:
            continue
    return out


@router.get("/{project_id}/runs")
async def list_project_runs(project_id: str):
    return _read_runs(project_id)


@router.post("/{project_id}/runs", dependencies=[Depends(require_master_key)])
async def add_project_run(project_id: str, body: Dict[str, Any]):
    run_id = (body.get("run_id") or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    ref = {
        "run_id": run_id[:120],
        "workflow_id": (body.get("workflow_id") or "").strip()[:120] or None,
        "label": (body.get("label") or "").strip()[:200] or None,
        "task_id": (body.get("task_id") or "").strip()[:120] or None,
        "origin": (body.get("origin") or "operator").strip()[:40] or "operator",
        "ts": _dt.utcnow().isoformat() + "Z",
    }
    p = _runs_path(project_id)
    with p.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(ref, default=str) + "\n")
    return ref


# ── Docs context workspace bind (C3) ───────────────────────────────────────


@router.post(
    "/{project_id}/context-workspace",
    dependencies=[Depends(require_master_key)],
)
async def bind_context_workspace(project_id: str, body: Dict[str, Any] | None = None):
    root = (body or {}).get("root") if isinstance(body, dict) else None
    try:
        return get_project_service().bind_context_workspace(project_id, root=root)
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
