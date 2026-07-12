#!/usr/bin/env python3
"""Local scheduler tests (Operate U4).

Covers the hardening items the spec names explicitly:
  * cadence validation + UTC next-fire math (F7)
  * journal rotation + torn-line-tolerant reverse tail (F8)
  * overlap guard with zombie takeover (F17)
  * double-fire hardening across a restart (F6)
  * auto-disable at the consecutive-failure cap
  * boot reconcile counts vanished dispatches as failures
  * router: /summary route resolution (F15), CRUD validation (422)
  * run-async byte-identical contract for BOTH branches + origin.json sidecar
"""

from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timedelta

import pytest

import api.services.schedule_service as ss
from api.exceptions import WorkflowValidationError
from api.services.schedule_service import (
    Cadence,
    ScheduleCreate,
    ScheduleDefinition,
    ScheduleService,
    is_due,
    next_fire_at,
)

# ── isolation ────────────────────────────────────────────────────────────────


@pytest.fixture
def sched_paths(tmp_path, monkeypatch):
    """Redirect all schedule_service on-disk paths into a tmp dir and reset the
    module singleton so no test touches real data/."""
    monkeypatch.setattr(ss, "_DATA_ROOT", tmp_path)
    monkeypatch.setattr(ss, "_CONFIG_PATH", tmp_path / "config" / "schedules.json")
    monkeypatch.setattr(ss, "_SCHED_DIR", tmp_path / "schedules")
    monkeypatch.setattr(
        ss, "_JOURNAL_PATH", tmp_path / "schedules" / "dispatches.jsonl"
    )
    monkeypatch.setattr(ss, "_LOCK_PATH", tmp_path / "schedules" / "scheduler.lock")
    monkeypatch.setattr(ss, "_service", None)
    return tmp_path


def _sched(**over) -> ScheduleDefinition:
    base = dict(
        id="sched_abc_000001",
        name="nightly",
        workflow_id="wf-x",
        cadence=Cadence(kind="interval", every_seconds=3600),
    )
    base.update(over)
    return ScheduleDefinition(**base)


# ── cadence validation + UTC math (F7) ───────────────────────────────────────


def test_cadence_interval_floor():
    with pytest.raises(Exception):
        Cadence(kind="interval", every_seconds=60)  # below the 300s floor
    assert Cadence(kind="interval", every_seconds=300).period_seconds() == 300


def test_cadence_daily_and_weekly_shape():
    with pytest.raises(Exception):
        Cadence(kind="daily")  # missing at
    with pytest.raises(Exception):
        Cadence(kind="weekly", at="09:00")  # missing weekday
    ok = Cadence(kind="weekly", at="09:00", weekday="mon")
    assert ok.period_seconds() == 604800
    assert "mon" in ok.human()


def test_next_fire_interval_utc():
    s = _sched(
        cadence=Cadence(kind="interval", every_seconds=3600),
        created_at="2026-07-08T00:00:00",
        last_dispatched_at="2026-07-08T10:00:00",
    )
    nf = next_fire_at(s, datetime(2026, 7, 8, 10, 30))
    assert nf == datetime(2026, 7, 8, 11, 0, 0)


def test_next_fire_daily_rolls_forward():
    s = _sched(
        cadence=Cadence(kind="daily", at="09:00"),
        last_dispatched_at="2026-07-08T09:00:00",
    )
    nf = next_fire_at(s, datetime(2026, 7, 8, 12, 0))
    assert nf == datetime(2026, 7, 9, 9, 0, 0)


def test_next_fire_weekly_hits_named_day():
    # 2026-07-08 is a Wednesday; next Monday is 2026-07-13.
    s = _sched(
        cadence=Cadence(kind="weekly", at="06:00", weekday="mon"),
        last_dispatched_at="2026-07-06T06:00:00",
    )
    nf = next_fire_at(s, datetime(2026, 7, 8, 12, 0))
    assert nf.weekday() == 0  # Monday
    assert nf == datetime(2026, 7, 13, 6, 0, 0)


def test_is_due_interval():
    s = _sched(
        cadence=Cadence(kind="interval", every_seconds=300),
        last_dispatched_at="2026-07-08T10:00:00",
    )
    assert is_due(s, datetime(2026, 7, 8, 10, 6)) is True
    assert is_due(s, datetime(2026, 7, 8, 10, 3)) is False


# ── journal rotation + torn tail (F8) ────────────────────────────────────────


def test_journal_rotation_and_reverse_tail(sched_paths, monkeypatch):
    monkeypatch.setattr(ss, "_JOURNAL_MAX_BYTES", 2048)  # tiny cap to force rotation
    for i in range(400):
        ss.append_journal("dispatched", {"schedule_id": "sched_r_1", "run_id": f"r{i}"})
    assert ss._JOURNAL_PATH.exists()
    assert ss._JOURNAL_PATH.with_suffix(".jsonl.1").exists()  # rotated backup
    recent = ss.read_journal(limit=5)
    assert recent[0]["run_id"] == "r399"  # newest first
    # single-backup rotation: the tail reaches into .1 (more than the current
    # file alone) but older-than-.1 data is intentionally discarded (< 400).
    current_only = len(ss._read_journal_lines(ss._JOURNAL_PATH))
    spanning = ss.read_journal(limit=400, schedule_id="sched_r_1")
    assert current_only < len(spanning) < 400


def test_journal_torn_final_line_tolerated(sched_paths):
    ss.append_journal("dispatched", {"schedule_id": "sched_t", "run_id": "r0"})
    with open(ss._JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write('{"event": "dispatched", "run_id": "TORN')  # no newline, invalid
    recs = ss.read_journal(limit=10)
    assert len(recs) == 1 and recs[0]["run_id"] == "r0"


# ── overlap / zombie (F17) ───────────────────────────────────────────────────


def test_run_activity_classification(sched_paths, monkeypatch):
    now = datetime(2026, 7, 8, 12, 0)
    runs = {
        "fresh": {"status": "running", "started_at": "2026-07-08T11:59:00"},
        "stale": {"status": "running", "started_at": "2026-07-08T08:00:00"},
        "done": {"status": "completed", "started_at": "2026-07-08T11:00:00"},
    }
    monkeypatch.setattr(ss, "_read_run", lambda rid: runs.get(rid))
    assert ss.run_activity("fresh", now) == "running"
    assert ss.run_activity("stale", now) == "zombie"  # > 120min stale
    assert ss.run_activity("done", now) == "done"
    assert ss.run_activity("missing", now) == "done"  # vanished


@pytest.mark.asyncio
async def test_overlap_then_zombie_takeover(sched_paths, monkeypatch):
    svc = ScheduleService()
    s = _sched(cadence=Cadence(kind="interval", every_seconds=300))
    svc._schedules[s.id] = s
    svc._inflight[s.id] = "run-1"
    now = datetime(2026, 7, 8, 12, 0)

    # first: prior run is genuinely running → overlap episode, no dispatch
    monkeypatch.setattr(ss, "run_activity", lambda rid, n: "running")
    dispatched = []
    monkeypatch.setattr(
        svc,
        "dispatch_now",
        lambda sched, trigger="scheduled": _noop_dispatch(dispatched, sched),
    )
    await svc._maybe_dispatch(s, now)
    assert dispatched == []  # held by overlap
    events = [r["event"] for r in ss.read_journal(limit=20)]
    assert "skipped_overlap_start" in events

    # then: the same run goes stale → takeover, degraded surfaced, dispatch proceeds
    monkeypatch.setattr(ss, "run_activity", lambda rid, n: "zombie")
    await svc._maybe_dispatch(s, now)
    assert svc._degraded.get(s.id, 0) == 1
    assert dispatched == [s.id]
    events = [r["event"] for r in ss.read_journal(limit=20)]
    assert "overlap_takeover" in events


async def _noop_dispatch(sink, sched):
    sink.append(sched.id)
    return "new-run"


# ── auto-disable + completion bookkeeping ────────────────────────────────────


def test_apply_completion_failure_cap_auto_disables():
    s = _sched(max_consecutive_failures=3, consecutive_failures=2, enabled=True)
    assert s.consecutive_failures == 2
    disabled = ScheduleService._apply_completion(
        ScheduleService.__new__(ScheduleService), s, "failed"
    )
    assert s.consecutive_failures == 3
    assert disabled is True and s.enabled is False


def test_apply_completion_success_resets():
    s = _sched(consecutive_failures=2, enabled=True)
    svc = ScheduleService.__new__(ScheduleService)
    assert svc._apply_completion(s, "completed") is False
    assert s.consecutive_failures == 0
    assert s.last_status == "completed"


# ── double-fire hardening across restart (F6) ────────────────────────────────


@pytest.mark.asyncio
async def test_double_fire_hardened_across_restart(sched_paths, monkeypatch):
    # A schedule that just dispatched must NOT re-fire on a fresh service load
    # within the same period. dispatch persists last_dispatched_at BEFORE handoff.
    svc = ScheduleService()
    s = _sched(cadence=Cadence(kind="interval", every_seconds=3600))
    svc._schedules[s.id] = s
    svc._save()

    # stub the engine/run_dispatch layer so no real run happens
    monkeypatch.setattr(
        "api.services.run_dispatch.prepare_run",
        lambda **kw: (object(), "run-xyz"),
    )
    monkeypatch.setattr(
        "api.services.run_dispatch.dispatch_blocking",
        lambda *a, **k: None,
    )
    now = datetime.utcnow()
    monkeypatch.setattr(ss, "datetime", _FixedDatetime(now))
    run_id = await svc.dispatch_now(s, trigger="scheduled")
    assert run_id == "run-xyz"
    assert s.last_dispatched_at is not None

    # simulate a process restart: brand-new service reads the persisted store
    monkeypatch.setattr(ss, "_service", None)
    svc2 = ScheduleService()
    reloaded = svc2.get(s.id)
    assert reloaded is not None and reloaded.last_dispatched_at == s.last_dispatched_at
    # within the 1h period the reloaded schedule is not due → no re-fire
    assert is_due(reloaded, now + timedelta(seconds=60)) is False


class _FixedDatetime:
    """A datetime shim whose utcnow() is pinned, other members pass through."""

    def __init__(self, fixed):
        self._fixed = fixed

    def utcnow(self):
        return self._fixed

    def __getattr__(self, name):
        return getattr(datetime, name)


# ── boot reconcile ───────────────────────────────────────────────────────────


def test_boot_reconcile_counts_vanished_as_failure(sched_paths, monkeypatch):
    svc = ScheduleService()
    s = _sched(last_run_id="run-gone", last_status="queued", consecutive_failures=0)
    svc._schedules[s.id] = s
    ss.append_journal("dispatched", {"schedule_id": s.id, "run_id": "run-gone"})
    monkeypatch.setattr(ss, "_read_run", lambda rid: None)  # run.json vanished
    svc.boot_reconcile()
    assert svc.get(s.id).consecutive_failures == 1


def test_boot_reconcile_adopts_running_inflight(sched_paths, monkeypatch):
    svc = ScheduleService()
    s = _sched(last_run_id="run-live", last_status="running")
    svc._schedules[s.id] = s
    ss.append_journal("dispatched", {"schedule_id": s.id, "run_id": "run-live"})
    monkeypatch.setattr(
        ss,
        "_read_run",
        lambda rid: {"status": "running", "started_at": datetime.utcnow().isoformat()},
    )
    monkeypatch.setattr(ss, "run_activity", lambda rid, n: "running")
    svc.boot_reconcile()
    assert svc._inflight.get(s.id) == "run-live"


# ── router: summary route order + CRUD validation ────────────────────────────


@pytest.fixture
def client(sched_paths):
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from fastapi.testclient import TestClient

    return TestClient(api.main.app)


def test_summary_route_resolves_before_id(client):
    # /summary must return the dashboard shape, NOT a 404 from the id handler.
    r = client.get("/api/schedules/summary")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "enabled_count",
        "dispatched_24h",
        "skipped_24h",
        "failed_24h",
        "upcoming",
    ):
        assert key in body


def test_scope_map_has_schedules_entry():
    import api.middleware as mw

    importlib.reload(mw)
    assert mw.SCOPE_MAP.get("/api/schedules") == "workflows"


def test_create_rejects_unknown_workflow(client, monkeypatch):
    # engine.resolve_workflow_path returns None for a bogus id → 422.
    body = {
        "name": "bad",
        "workflow_id": "does-not-exist-xyz",
        "cadence": {"kind": "interval", "every_seconds": 600},
    }
    r = client.post("/api/schedules", json=body)
    assert r.status_code == 422


def test_create_rejects_unknown_workspace(sched_paths, monkeypatch):
    svc = ScheduleService()

    class _FakeEngine:
        def resolve_workflow_path(self, wid, d):
            return "/tmp/x.yaml"

        def load(self, p):
            return object()

        def validate(self, defn, seed_keys=None):
            return None

    svc._engine = _FakeEngine()
    body = ScheduleCreate(
        name="ws",
        workflow_id="wf-x",
        workspace="no-such-ws",
        cadence=Cadence(kind="interval", every_seconds=600),
    )
    with pytest.raises(WorkflowValidationError):
        svc.create(body)


def test_crud_roundtrip(client, monkeypatch):
    # patch the singleton's ref-validation so we don't need a real workflow
    svc = ss.get_schedule_service()
    monkeypatch.setattr(svc, "_validate_refs", lambda body: None)
    body = {
        "name": "roundtrip",
        "workflow_id": "wf-x",
        "cadence": {"kind": "daily", "at": "09:00"},
    }
    created = client.post("/api/schedules", json=body).json()
    sid = created["id"]
    assert sid.startswith("sched_")
    assert created["next_fire_at"] and created["cadence_human"] == "daily at 09:00 UTC"

    listed = client.get("/api/schedules").json()["schedules"]
    assert any(s["id"] == sid for s in listed)

    got = client.get(f"/api/schedules/{sid}").json()
    assert got["id"] == sid and "history" in got

    disabled = client.post(f"/api/schedules/{sid}/disable").json()
    assert disabled["enabled"] is False
    enabled = client.post(f"/api/schedules/{sid}/enable").json()
    assert enabled["enabled"] is True

    assert client.delete(f"/api/schedules/{sid}").status_code == 200
    assert client.get(f"/api/schedules/{sid}").status_code == 404


# ── run-async byte-identical contract + origin sidecar (both branches) ───────


@pytest.fixture
def wf_client(monkeypatch, tmp_path):
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    # isolate the run root so origin.json lands in tmp
    import api.services.workflow_engine as we

    monkeypatch.setattr(we, "DATA_DIR", str(tmp_path / "workflows"))
    import api.main

    importlib.reload(api.main)
    from fastapi.testclient import TestClient

    # never run the real engine in the background task
    monkeypatch.setattr(
        "api.services.run_dispatch.dispatch_blocking", lambda *a, **k: None
    )
    return TestClient(api.main.app), tmp_path


_VALID_WF = {
    "id": "test-sched-wf",
    "name": "Test Sched WF",
    "defaults": {"role": "general", "retries": 0, "retry_delay": 0},
    "steps": [
        {
            "id": "s1",
            "name": "Step 1",
            "role": "fast",
            "system_prompt": "Analyze.",
            "inputs": ["seed.task"],
            "outputs": ["result"],
        }
    ],
}


def test_run_async_definition_branch_contract(wf_client):
    client, tmp_path = wf_client
    r = client.post(
        "/api/workflows/run-async",
        json={"definition": _VALID_WF, "seed": {"task": "hi"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"run_id", "workflow_id", "status", "poll_url"}
    assert body["status"] == "queued"
    assert body["workflow_id"] == "test-sched-wf"
    assert body["poll_url"] == f"/api/workflows/runs/{body['run_id']}"
    # the one new observable: origin.json sidecar
    origin = json.loads(
        (tmp_path / "workflows" / body["run_id"] / "origin.json").read_text()
    )
    assert origin["origin"] == "manual"
    assert origin["workflow_id"] == "test-sched-wf"


def test_run_async_neither_branch_400(wf_client):
    client, _ = wf_client
    r = client.post("/api/workflows/run-async", json={"seed": {}})
    assert r.status_code == 400


def test_run_async_bad_workflow_id_404(wf_client):
    client, _ = wf_client
    r = client.post("/api/workflows/run-async", json={"workflow_id": "nope-xyz-123"})
    assert r.status_code == 404
