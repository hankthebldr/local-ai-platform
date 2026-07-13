"""Local scheduler — the ONE surface that persists and dispatches time-based
workflow runs. Zero egress, single-worker, in-process on the app event loop.

Naming: ``api/services/scheduler.py`` is TAKEN (the Phase-4 DAG feasibility
facade), so the time-based scheduler lives here as ``schedule_service`` and its
routes hang off ``/api/schedules``.

Design guarantees (each maps to a spec hardening item):

  * UTC everywhere (F7). The engine persists ``datetime.utcnow()`` throughout;
    cadence math, ``at "HH:MM"``, next-fire and all bookkeeping are UTC. The
    wizard/rail render local time alongside a "stored as UTC" note. No local-time
    math runs server-side, so DST cannot double- or zero-fire.
  * Double-fire hardening (F6). ``last_dispatched_at`` is persisted atomically
    (tmp+replace, lock-held) BEFORE the run is handed to the executor, in the
    same critical section that appends the ``dispatched`` journal line. A restart
    mid-dispatch re-reads the journal tail (boot reconcile) and never re-fires a
    window it already dispatched.
  * Overlap guard with zombie takeover (F17). A prior dispatch counts as running
    only while its run.json is running|queued AND its newest timestamp is within
    ``SCHEDULER_ZOMBIE_MINUTES``. Past that a stuck run is taken over (journaled),
    so a wedged run can never stall a schedule forever while it "appears enabled".
  * Bounded journal (F8). ``data/schedules/dispatches.jsonl`` records TRANSITIONS
    ONLY (dispatched / error / one skipped_missed per missed window / overlap
    episodes) with size-capped rotation (5 MB → .1, single backup). Reads are a
    torn-line-tolerant reverse tail (ralph journal pattern).
  * Executor isolation (F14). Blocking ``engine.run`` goes through a module-owned
    ``ThreadPoolExecutor`` (``_SCHED_POOL``), never the loop's default pool, so it
    cannot starve other ``to_thread`` users.
  * Single-worker guard (F16). Best-effort O_EXCL lockfile; a second process's
    loop no-ops (CRUD still works everywhere, only the loop is exclusive). Assumes
    a single uvicorn worker — ``--workers>1`` would otherwise run one loop each.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import time
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..exceptions import WorkflowValidationError
from ..logging_config import logger
from ..services.workspace import get_workspace_registry

# ── Config knobs (env-overridable) ──────────────────────────────────────────
SCHEDULER_TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "30"))
SCHEDULER_MAX_CONCURRENT = int(os.getenv("SCHEDULER_MAX_CONCURRENT", "2"))
SCHEDULER_ZOMBIE_MINUTES = int(os.getenv("SCHEDULER_ZOMBIE_MINUTES", "120"))
_JOURNAL_MAX_BYTES = 5 * 1024 * 1024  # 5 MB → rotate to .1 (single backup)
_MIN_INTERVAL_SECONDS = 300

_DATA_ROOT = Path(os.getenv("SCHEDULE_DATA_DIR", "./data"))
_CONFIG_PATH = _DATA_ROOT / "config" / "schedules.json"
_SCHED_DIR = _DATA_ROOT / "schedules"
_JOURNAL_PATH = _SCHED_DIR / "dispatches.jsonl"
_LOCK_PATH = _SCHED_DIR / "scheduler.lock"

# Monday=0 … Sunday=6 — matches datetime.weekday(). The named enum (F7) keeps
# Python's Monday=0 and JS's Sunday=0 integer conventions from leaking across
# the wizard boundary; the wire form is always a lowercase weekday string.
_WEEKDAY_NUM = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_SCHED_ID_RE = __import__("re").compile(r"^sched_[a-z0-9_]{1,64}$")


class Weekday(str, Enum):
    mon = "mon"
    tue = "tue"
    wed = "wed"
    thu = "thu"
    fri = "fri"
    sat = "sat"
    sun = "sun"


class Cadence(BaseModel):
    kind: str  # interval | daily | weekly
    every_seconds: Optional[int] = None
    at: Optional[str] = None  # "HH:MM" UTC (daily/weekly)
    weekday: Optional[Weekday] = None  # weekly

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        if v not in ("interval", "daily", "weekly"):
            raise ValueError("cadence.kind must be interval|daily|weekly")
        return v

    @model_validator(mode="after")
    def _shape(self) -> "Cadence":
        if self.kind == "interval":
            if not self.every_seconds or self.every_seconds < _MIN_INTERVAL_SECONDS:
                raise ValueError(
                    f"interval cadence requires every_seconds >= {_MIN_INTERVAL_SECONDS}"
                )
        else:  # daily | weekly
            if not self.at or not _valid_hhmm(self.at):
                raise ValueError(f"{self.kind} cadence requires at 'HH:MM' (UTC)")
            if self.kind == "weekly" and self.weekday is None:
                raise ValueError("weekly cadence requires a named weekday")
        return self

    def period_seconds(self) -> int:
        if self.kind == "interval":
            return int(self.every_seconds or _MIN_INTERVAL_SECONDS)
        return 86400 if self.kind == "daily" else 604800

    def human(self) -> str:
        if self.kind == "interval":
            return f"every {int(self.every_seconds or 0) // 60} min"
        if self.kind == "daily":
            return f"daily at {self.at} UTC"
        return (
            f"weekly on {self.weekday.value if self.weekday else '?'} at {self.at} UTC"
        )


def _valid_hhmm(s: str) -> bool:
    try:
        hh, mm = s.split(":")
        return 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except (ValueError, AttributeError):
        return False


class ScheduleDefinition(BaseModel):
    """Persisted schedule. Local to this service — NOT workflow_models.py."""

    id: str
    name: str
    category: str = "Task"  # free text; datalist Research/Report/Maintenance/Task
    enabled: bool = True
    workflow_id: str
    seed: Dict[str, Any] = Field(default_factory=dict)
    workspace: Optional[str] = None  # C4 — the schedule↔directory binding
    cadence: Cadence
    max_consecutive_failures: int = 5

    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_dispatched_at: Optional[str] = None
    last_run_id: Optional[str] = None
    last_status: Optional[str] = None
    consecutive_failures: int = 0

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not _SCHED_ID_RE.match(v):
            raise ValueError("schedule id must match ^sched_[a-z0-9_]{1,64}$")
        return v


class ScheduleCreate(BaseModel):
    """Router create/update body (no server-set bookkeeping fields)."""

    name: str
    category: str = "Task"
    enabled: bool = True
    workflow_id: str
    seed: Dict[str, Any] = Field(default_factory=dict)
    workspace: Optional[str] = None
    cadence: Cadence
    max_consecutive_failures: int = 5


def _new_schedule_id() -> str:
    # sched_<ms-hex>_<uuid4[:6]> — collision-proof per the task-id lesson.
    return f"sched_{format(int(time.time() * 1000), 'x')}_{_uuid.uuid4().hex[:6]}"


# ── Cadence math (pure, UTC) ─────────────────────────────────────────────────


def _next_after(sched: ScheduleDefinition, after: datetime) -> datetime:
    c = sched.cadence
    if c.kind == "interval":
        return after + timedelta(seconds=int(c.every_seconds or _MIN_INTERVAL_SECONDS))
    hh, mm = (int(x) for x in (c.at or "00:00").split(":"))
    cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if c.kind == "daily":
        if cand <= after:
            cand += timedelta(days=1)
        return cand
    # weekly
    target = _WEEKDAY_NUM[c.weekday.value] if c.weekday else 0
    days_ahead = (target - cand.weekday()) % 7
    cand += timedelta(days=days_ahead)
    if cand <= after:
        cand += timedelta(days=7)
    return cand


def next_fire_at(sched: ScheduleDefinition, now: Optional[datetime] = None) -> datetime:
    """UTC datetime of the next fire, computed from last_dispatched_at (or
    created_at for a never-fired schedule). Never backfills."""
    ref = sched.last_dispatched_at or sched.created_at
    try:
        after = datetime.fromisoformat(ref)
    except (ValueError, TypeError):
        after = now or datetime.utcnow()
    return _next_after(sched, after)


def is_due(sched: ScheduleDefinition, now: datetime) -> bool:
    return next_fire_at(sched, now) <= now


# ── Journal (transitions only, torn-line-tolerant, size-capped) ──────────────


def _rotate_journal_if_needed() -> None:
    try:
        if (
            _JOURNAL_PATH.exists()
            and _JOURNAL_PATH.stat().st_size >= _JOURNAL_MAX_BYTES
        ):
            backup = _JOURNAL_PATH.with_suffix(".jsonl.1")
            os.replace(_JOURNAL_PATH, backup)  # single backup; older discarded
    except OSError as exc:
        logger.warning(f"dispatch journal rotation failed: {exc}")


def append_journal(event: str, record: Dict[str, Any]) -> None:
    """Append one transition line. Best-effort; a write failure logs only."""
    line = {"ts": datetime.utcnow().isoformat(), "event": event, **record}
    try:
        _SCHED_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_journal_if_needed()
        with open(_JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except OSError as exc:
        logger.warning(f"dispatch journal append failed: {exc}")


def _read_journal_lines(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))  # skip a torn final line
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        logger.warning(f"dispatch journal read failed for {path}: {exc}")
    return out


def read_journal(
    limit: int = 50, schedule_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Bounded reverse tail of the current journal, reaching into .1 when the
    current file underruns. Newest first."""
    records = _read_journal_lines(_JOURNAL_PATH)
    if len(records) < limit:
        backup = _JOURNAL_PATH.with_suffix(".jsonl.1")
        records = _read_journal_lines(backup) + records
    records.reverse()
    if schedule_id:
        records = [r for r in records if r.get("schedule_id") == schedule_id]
    return records[:limit]


# ── Run-state introspection (overlap / zombie / completion) ──────────────────


def _run_json_path(run_id: str) -> Path:
    from ..services.workflow_engine import DATA_DIR

    return Path(DATA_DIR) / run_id / "run.json"


def _read_run(run_id: str) -> Optional[Dict[str, Any]]:
    p = _run_json_path(run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _run_newest_ts(run: Dict[str, Any]) -> Optional[datetime]:
    for key in ("completed_at", "started_at"):
        v = run.get(key)
        if v:
            try:
                return datetime.fromisoformat(str(v).replace("Z", ""))
            except ValueError:
                continue
    return None


def run_activity(run_id: str, now: datetime) -> str:
    """Classify a prior dispatch's run for the overlap guard.

    Returns one of: 'running' (active, hold overlap), 'zombie' (running|queued
    but stale past the zombie window — take it over), 'done' (terminal/vanished).
    """
    run = _read_run(run_id)
    if run is None:
        return "done"
    status = str(run.get("status", "")).lower()
    if status not in ("running", "queued"):
        return "done"
    newest = _run_newest_ts(run)
    if newest is None:
        return "running"
    if now - newest > timedelta(minutes=SCHEDULER_ZOMBIE_MINUTES):
        return "zombie"
    return "running"


# ── Service ──────────────────────────────────────────────────────────────────


class ScheduleService:
    """Owns the schedule store, the dispatch journal, and the tick loop.

    A single ``asyncio.Lock`` serializes router mutations against the loop. The
    thread pool runs blocking ``engine.run`` off the event loop.
    """

    def __init__(self) -> None:
        self._schedules: Dict[str, ScheduleDefinition] = {}
        self._lock = asyncio.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=SCHEDULER_MAX_CONCURRENT, thread_name_prefix="sched"
        )
        self._inflight: Dict[str, str] = {}  # sched_id -> run_id currently running
        self._overlap_open: Dict[str, int] = {}  # sched_id -> ticks skipped so far
        self._degraded: Dict[str, int] = {}  # sched_id -> repeated-overlap count
        self._engine = None
        self._owns_loop = False
        self._loop_task: Optional[asyncio.Task] = None
        self._load()

    # ── engine (lazy; local import avoids router cycle) ──
    def _get_engine(self):
        if self._engine is None:
            from ..services.run_dispatch import build_engine

            self._engine = build_engine()
        return self._engine

    # ── persistence ──
    def _load(self) -> None:
        if not _CONFIG_PATH.exists():
            return
        try:
            raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"schedules.json load failed: {exc}")
            return
        for item in raw.get("schedules", []):
            try:
                s = ScheduleDefinition(**item)
                self._schedules[s.id] = s
            except Exception as exc:  # noqa: BLE001 — skip corrupt entries
                logger.warning(f"skipping invalid schedule record: {exc}")

    def _save(self) -> None:
        """Atomic tmp+replace of the whole store."""
        payload = {
            "schedules": [s.model_dump(mode="json") for s in self._schedules.values()]
        }
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _CONFIG_PATH.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            os.replace(tmp, _CONFIG_PATH)
        except OSError as exc:
            logger.warning(f"schedules.json save failed: {exc}")

    # ── CRUD (called under the asyncio lock by the router) ──
    def _validate_refs(self, body: ScheduleCreate) -> None:
        """422-worthy checks: workflow resolvable + validates, workspace known."""
        engine = self._get_engine()
        yaml_path = engine.resolve_workflow_path(body.workflow_id, WORKFLOWS_DIR)
        if not yaml_path:
            raise WorkflowValidationError(
                f"workflow '{body.workflow_id}' not found in public or private overlay"
            )
        defn = engine.load(yaml_path)
        engine.validate(defn, seed_keys=list(body.seed.keys()) if body.seed else None)
        if body.workspace is not None:
            names = {m.name for m in get_workspace_registry().list()}
            if body.workspace not in names:
                raise WorkflowValidationError(
                    f"workspace '{body.workspace}' is not a registered workspace"
                )

    def create(self, body: ScheduleCreate) -> ScheduleDefinition:
        self._validate_refs(body)
        sched = ScheduleDefinition(id=_new_schedule_id(), **body.model_dump())
        self._schedules[sched.id] = sched
        self._save()
        return sched

    def update(self, schedule_id: str, body: ScheduleCreate) -> ScheduleDefinition:
        existing = self._schedules[schedule_id]
        self._validate_refs(body)
        merged = existing.model_copy(
            update={
                **body.model_dump(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        # A cadence or workflow change resets the failure counter (fresh start).
        if (
            body.cadence.model_dump() != existing.cadence.model_dump()
            or body.workflow_id != existing.workflow_id
        ):
            merged.consecutive_failures = 0
        self._schedules[schedule_id] = merged
        self._save()
        return merged

    def delete(self, schedule_id: str) -> None:
        # History JSONL is retained on purpose — audit trail.
        del self._schedules[schedule_id]
        self._save()

    def set_enabled(self, schedule_id: str, enabled: bool) -> ScheduleDefinition:
        s = self._schedules[schedule_id]
        s.enabled = enabled
        s.updated_at = datetime.utcnow().isoformat()
        if enabled:
            s.consecutive_failures = 0
        self._save()
        return s

    def get(self, schedule_id: str) -> Optional[ScheduleDefinition]:
        return self._schedules.get(schedule_id)

    def all(self) -> List[ScheduleDefinition]:
        return list(self._schedules.values())

    # ── dispatch mechanics ──
    def _seed_with_workspace(self, sched: ScheduleDefinition) -> Dict[str, Any]:
        """Inject seed.workspace + seed.workspace_root at dispatch time (C4 /
        C2 convention). Raises WorkflowValidationError if the workspace vanished
        after the schedule was created."""
        seed = dict(sched.seed or {})
        if sched.workspace:
            reg = get_workspace_registry()
            names = {m.name for m in reg.list()}
            if sched.workspace not in names:
                raise WorkflowValidationError("workspace_missing")
            ws = reg.get(sched.workspace)
            seed["workspace"] = sched.workspace
            seed["workspace_root"] = str(ws.root)
        return seed

    def _apply_completion(self, sched: ScheduleDefinition, run_status: str) -> bool:
        """Pure bookkeeping: fold a terminal run status into the schedule.
        Returns True if this completion tripped the auto-disable cap."""
        sched.last_status = run_status
        if (
            run_status in ("failed", "error", "canceled")
            or run_status == "__vanished__"
        ):
            sched.consecutive_failures += 1
        else:
            sched.consecutive_failures = 0
        auto_disabled = False
        if (
            sched.consecutive_failures >= sched.max_consecutive_failures
            and sched.enabled
        ):
            sched.enabled = False
            auto_disabled = True
        return auto_disabled

    async def dispatch_now(
        self, sched: ScheduleDefinition, trigger: str = "scheduled"
    ) -> Optional[str]:
        """Prepare + hand off one run for this schedule. Returns run_id (None on
        a prepare failure that was journaled). The critical section that persists
        ``last_dispatched_at`` and journals ``dispatched`` runs BEFORE the engine
        is handed to the pool (F6). ``trigger='run-now'`` does NOT shift the
        cadence clock and does NOT count toward auto-disable."""
        from ..services.run_dispatch import (
            RunPrepareError,
            WorkflowNotFound,
            dispatch_blocking,
            prepare_run,
        )

        try:
            seed = self._seed_with_workspace(sched)
            origin = {
                "origin": "scheduled",
                "schedule_id": sched.id,
                "schedule_category": sched.category,
                "trigger": trigger,
            }
            defn, run_id = prepare_run(
                workflow_id=sched.workflow_id,
                seed=seed,
                origin=origin,
                engine=self._get_engine(),
            )
        except (WorkflowValidationError, WorkflowNotFound, RunPrepareError) as exc:
            async with self._lock:
                append_journal(
                    "error",
                    {"schedule_id": sched.id, "trigger": trigger, "detail": str(exc)},
                )
                sched.consecutive_failures += 1
                if (
                    sched.consecutive_failures >= sched.max_consecutive_failures
                    and sched.enabled
                ):
                    sched.enabled = False
                    append_journal(
                        "auto_disabled",
                        {"schedule_id": sched.id, "reason": "consecutive_failures"},
                    )
                sched.last_status = "error"
                self._save()
            return None

        # Critical section (F6): persist last_dispatched_at + journal dispatched
        # BEFORE the engine is handed to the executor.
        async with self._lock:
            now_iso = datetime.utcnow().isoformat()
            if trigger != "run-now":
                sched.last_dispatched_at = now_iso
            sched.last_run_id = run_id
            self._save()
            append_journal(
                "dispatched",
                {
                    "schedule_id": sched.id,
                    "run_id": run_id,
                    "trigger": trigger,
                    "category": sched.category,
                },
            )
        self._inflight[sched.id] = run_id

        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(
            self._pool,
            functools.partial(
                dispatch_blocking, defn, seed, run_id, self._get_engine()
            ),
        )
        fut.add_done_callback(
            lambda f, sid=sched.id, rid=run_id, tr=trigger: asyncio.ensure_future(
                self._finalize(sid, rid, tr)
            )
        )
        return run_id

    async def _finalize(self, schedule_id: str, run_id: str, trigger: str) -> None:
        """Completion bookkeeping — read terminal run.json, fold status in."""
        run = _read_run(run_id)
        status = str(run.get("status", "completed")).lower() if run else "__vanished__"
        async with self._lock:
            self._inflight.pop(schedule_id, None)
            sched = self._schedules.get(schedule_id)
            if sched is None:
                return
            if trigger == "run-now":
                # run-now doesn't count toward auto-disable; record status only.
                sched.last_status = status if status != "__vanished__" else "unknown"
                self._save()
                return
            auto_disabled = self._apply_completion(sched, status)
            if status in ("failed", "error", "canceled", "__vanished__"):
                append_journal(
                    "error",
                    {"schedule_id": schedule_id, "run_id": run_id, "status": status},
                )
            if auto_disabled:
                append_journal(
                    "auto_disabled",
                    {"schedule_id": schedule_id, "reason": "consecutive_failures"},
                )
            self._save()

    async def _maybe_dispatch(self, sched: ScheduleDefinition, now: datetime) -> None:
        """Overlap-guarded dispatch for one due schedule."""
        run_id = self._inflight.get(sched.id)
        if run_id:
            activity = run_activity(run_id, now)
            if activity == "running":
                # Overlap episode: journal the START once, then just count ticks.
                if sched.id not in self._overlap_open:
                    self._overlap_open[sched.id] = 0
                    append_journal(
                        "skipped_overlap_start",
                        {"schedule_id": sched.id, "run_id": run_id},
                    )
                self._overlap_open[sched.id] += 1
                return
            if activity == "zombie":
                # Zombie takeover (F17): treat as not-running, surface degraded.
                append_journal(
                    "overlap_takeover", {"schedule_id": sched.id, "run_id": run_id}
                )
                self._degraded[sched.id] = self._degraded.get(sched.id, 0) + 1
                self._inflight.pop(sched.id, None)
            # activity == 'done' (or took over) — clear any open overlap episode.
            if sched.id in self._overlap_open:
                ticks = self._overlap_open.pop(sched.id)
                append_journal(
                    "skipped_overlap_end",
                    {"schedule_id": sched.id, "ticks_skipped": ticks},
                )

        # Skip-not-backfill (F6): if more than one full period elapsed since the
        # scheduled fire, journal ONE skipped_missed and still fire just once.
        nf = next_fire_at(sched, now)
        if (now - nf).total_seconds() > sched.cadence.period_seconds():
            append_journal(
                "skipped_missed",
                {
                    "schedule_id": sched.id,
                    "missed_since": nf.isoformat(),
                },
            )
        await self.dispatch_now(sched, trigger="scheduled")

    async def tick(self, now: Optional[datetime] = None) -> None:
        """One scheduler tick: dispatch every enabled, due, non-overlapping
        schedule. Missed windows are skipped, never backfilled."""
        now = now or datetime.utcnow()
        async with self._lock:
            due = [s for s in self._schedules.values() if s.enabled and is_due(s, now)]
        for sched in due:
            try:
                await self._maybe_dispatch(sched, now)
            except (
                Exception
            ) as exc:  # noqa: BLE001 — one bad schedule can't kill the loop
                logger.warning(f"schedule {sched.id} dispatch failed: {exc}")

    # ── boot reconcile (double-fire safety across restart) ──
    def boot_reconcile(self) -> None:
        """Before the first tick, re-check the journal tail: any ``dispatched``
        entry without a terminal run.json is re-examined — still running →
        adopted as in-flight (overlap accounting); vanished/failed → counted as a
        failure. A restart mid-dispatch therefore never re-fires the same window."""
        now = datetime.utcnow()
        seen: set = set()
        for rec in read_journal(limit=200):
            if rec.get("event") != "dispatched":
                continue
            sid = rec.get("schedule_id")
            rid = rec.get("run_id")
            if not sid or not rid or sid in seen:
                continue
            seen.add(sid)  # only the most-recent dispatch per schedule matters
            sched = self._schedules.get(sid)
            if sched is None:
                continue
            run = _read_run(rid)
            status = str(run.get("status", "")).lower() if run else "__vanished__"
            if status in ("running", "queued") and run_activity(rid, now) != "zombie":
                self._inflight[sid] = rid  # adopt as in-flight
            elif status in ("failed", "error", "canceled", "__vanished__"):
                if sched.last_run_id == rid and sched.last_status not in (
                    "failed",
                    "error",
                    "canceled",
                ):
                    self._apply_completion(sched, status)
        self._save()

    # ── single-worker lockfile (F16) ──
    def acquire_lock(self) -> bool:
        """Best-effort O_EXCL lockfile. Returns True when this process owns the
        loop. A stale lock owned by a dead pid is reclaimed."""
        _SCHED_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "boot_ts": datetime.utcnow().isoformat()}
        )
        try:
            fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            self._owns_loop = True
            return True
        except FileExistsError:
            if self._reclaim_stale_lock():
                return self.acquire_lock()
            logger.warning(
                "scheduler lockfile held by another process — this worker's "
                "dispatch loop is disabled (CRUD routes still work). Run a single "
                "uvicorn worker for scheduling."
            )
            return False
        except OSError as exc:
            logger.warning(f"scheduler lock acquire failed: {exc}")
            return False

    def _reclaim_stale_lock(self) -> bool:
        try:
            info = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
            pid = int(info.get("pid", -1))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return False
        if pid == os.getpid():
            self._owns_loop = True
            return False  # already ours; caller shouldn't retry-create
        if not _pid_alive(pid):
            try:
                os.replace(str(_LOCK_PATH), str(_LOCK_PATH) + ".stale")
                os.remove(str(_LOCK_PATH) + ".stale")
            except OSError:
                pass
            return True
        return False

    def release_lock(self) -> None:
        if self._owns_loop:
            try:
                _LOCK_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            self._owns_loop = False

    # ── dashboard summary (F15 — /summary payload) ──
    def summary(self) -> Dict[str, Any]:
        now = datetime.utcnow()
        window = now - timedelta(hours=24)
        dispatched = skipped = failed = 0
        overlap_flags: Dict[str, int] = {}
        for rec in read_journal(limit=500):
            try:
                ts = datetime.fromisoformat(str(rec.get("ts", "")))
            except ValueError:
                continue
            if ts < window:
                continue
            ev = rec.get("event")
            if ev == "dispatched":
                dispatched += 1
            elif ev in ("skipped_missed", "skipped_overlap_start"):
                skipped += 1
            elif ev in ("error", "auto_disabled"):
                failed += 1
            if ev == "overlap_takeover":
                sid = rec.get("schedule_id", "")
                overlap_flags[sid] = overlap_flags.get(sid, 0) + 1
        enabled = [s for s in self._schedules.values() if s.enabled]
        upcoming = sorted(
            (
                {
                    "id": s.id,
                    "name": s.name,
                    "next_fire_at": next_fire_at(s, now).isoformat(),
                }
                for s in enabled
            ),
            key=lambda r: r["next_fire_at"],
        )[:5]
        return {
            "enabled_count": len(enabled),
            "total_count": len(self._schedules),
            "dispatched_24h": dispatched,
            "skipped_24h": skipped,
            "failed_24h": failed,
            "repeated_overlap": overlap_flags,
            "upcoming": upcoming,
        }

    def to_row(
        self, sched: ScheduleDefinition, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        now = now or datetime.utcnow()
        d = sched.model_dump(mode="json")
        d["next_fire_at"] = next_fire_at(sched, now).isoformat()
        d["cadence_human"] = sched.cadence.human()
        d["repeated_overlap"] = self._degraded.get(sched.id, 0)
        return d

    async def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.release_lock()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


WORKFLOWS_DIR = os.getenv("WORKFLOWS_DIR", "./workflows")

_service: Optional[ScheduleService] = None


def get_schedule_service() -> ScheduleService:
    """Process-wide ScheduleService singleton."""
    global _service
    if _service is None:
        _service = ScheduleService()
    return _service


async def run_dispatch_loop(service: Optional[ScheduleService] = None) -> None:
    """The dispatch loop coroutine — started in lifespan(), cancelled at teardown.

    Single-worker: acquires the lockfile first; a second process no-ops. Wrapped
    so an induced error never blocks boot (the caller runs it as a background task
    and logs on failure)."""
    service = service or get_schedule_service()
    if not service.acquire_lock():
        return
    try:
        service.boot_reconcile()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"scheduler boot reconcile failed: {exc}")
    logger.info(
        "  ⏰ Scheduler:    active (tick=%ss, pool=%s, zombie=%smin)",
        SCHEDULER_TICK_SECONDS,
        SCHEDULER_MAX_CONCURRENT,
        SCHEDULER_ZOMBIE_MINUTES,
    )
    try:
        while True:
            try:
                await service.tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"scheduler tick failed: {exc}")
            await asyncio.sleep(SCHEDULER_TICK_SECONDS)
    except asyncio.CancelledError:
        raise
    finally:
        service.release_lock()
