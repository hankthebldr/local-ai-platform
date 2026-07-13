"""Schedules router — CRUD + dashboard over the local scheduler.

Route-ordering discipline (F15/C6): literal paths register BEFORE parameterized
ones — ``GET /summary`` above ``GET /{schedule_id}`` — otherwise ``/summary``
would resolve as a schedule id and 404. A route-resolution test asserts this.

Reads are scope-authed via the SCOPE_MAP entry ``"/api/schedules": "workflows"``
(middleware.py). Writes are all ``Depends(require_master_key)`` — a no-op when
ENABLE_API_AUTH is off, the master gate otherwise. The scheduler is local-only;
this router never performs network I/O.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..exceptions import WorkflowValidationError
from ..middleware import require_master_key
from ..services.schedule_service import (
    ScheduleCreate,
    get_schedule_service,
    read_journal,
)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


# ── Literal routes FIRST (F15) ───────────────────────────────────────────────


@router.get("/summary")
async def get_summary() -> Dict[str, Any]:
    """Dashboard payload: enabled count, 24h dispatched/skipped/failed, repeated-
    overlap flags, next-5 upcoming. Registered before /{schedule_id} so it never
    resolves as an id lookup."""
    return get_schedule_service().summary()


@router.get("")
async def list_schedules() -> Dict[str, Any]:
    svc = get_schedule_service()
    return {"schedules": [svc.to_row(s) for s in svc.all()]}


@router.post("")
async def create_schedule(
    body: ScheduleCreate, _: None = Depends(require_master_key)
) -> Dict[str, Any]:
    svc = get_schedule_service()
    async with svc._lock:
        try:
            sched = svc.create(body)
        except WorkflowValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return svc.to_row(sched)


@router.get("/{schedule_id}")
async def get_schedule(schedule_id: str) -> Dict[str, Any]:
    svc = get_schedule_service()
    sched = svc.get(schedule_id)
    if sched is None:
        raise HTTPException(
            status_code=404, detail=f"schedule '{schedule_id}' not found"
        )
    row = svc.to_row(sched)
    row["history"] = read_journal(limit=10, schedule_id=schedule_id)
    return row


@router.get("/{schedule_id}/history")
async def get_schedule_history(schedule_id: str, limit: int = 50) -> Dict[str, Any]:
    svc = get_schedule_service()
    if svc.get(schedule_id) is None:
        raise HTTPException(
            status_code=404, detail=f"schedule '{schedule_id}' not found"
        )
    return {
        "history": read_journal(limit=max(1, min(limit, 500)), schedule_id=schedule_id)
    }


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: str, body: ScheduleCreate, _: None = Depends(require_master_key)
) -> Dict[str, Any]:
    svc = get_schedule_service()
    async with svc._lock:
        if svc.get(schedule_id) is None:
            raise HTTPException(
                status_code=404, detail=f"schedule '{schedule_id}' not found"
            )
        try:
            sched = svc.update(schedule_id, body)
        except WorkflowValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
    return svc.to_row(sched)


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str, _: None = Depends(require_master_key)
) -> Dict[str, Any]:
    svc = get_schedule_service()
    async with svc._lock:
        if svc.get(schedule_id) is None:
            raise HTTPException(
                status_code=404, detail=f"schedule '{schedule_id}' not found"
            )
        svc.delete(schedule_id)
    return {"deleted": schedule_id}


@router.post("/{schedule_id}/enable")
async def enable_schedule(
    schedule_id: str, _: None = Depends(require_master_key)
) -> Dict[str, Any]:
    return _set_enabled(schedule_id, True)


@router.post("/{schedule_id}/disable")
async def disable_schedule(
    schedule_id: str, _: None = Depends(require_master_key)
) -> Dict[str, Any]:
    return _set_enabled(schedule_id, False)


def _set_enabled(schedule_id: str, enabled: bool) -> Dict[str, Any]:
    svc = get_schedule_service()
    if svc.get(schedule_id) is None:
        raise HTTPException(
            status_code=404, detail=f"schedule '{schedule_id}' not found"
        )
    return svc.to_row(svc.set_enabled(schedule_id, enabled))


@router.post("/{schedule_id}/run-now")
async def run_now(
    schedule_id: str, _: None = Depends(require_master_key)
) -> Dict[str, Any]:
    """Immediate prepare+dispatch. Does NOT shift the cadence clock and does NOT
    count toward auto-disable."""
    svc = get_schedule_service()
    sched = svc.get(schedule_id)
    if sched is None:
        raise HTTPException(
            status_code=404, detail=f"schedule '{schedule_id}' not found"
        )
    run_id = await svc.dispatch_now(sched, trigger="run-now")
    if run_id is None:
        raise HTTPException(
            status_code=422, detail="run-now dispatch failed (see journal)"
        )
    return {"run_id": run_id, "poll_url": f"/api/workflows/runs/{run_id}"}
