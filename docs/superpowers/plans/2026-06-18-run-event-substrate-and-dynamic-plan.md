# Run Event Substrate + Dynamic Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native run-event substrate (in-process async EventBus + per-run `events.jsonl` + SSE stream) and a first-class, revisable `WorkflowPlan` projected over that stream, so workflow runs are observable live the way OpenCode sessions are.

**Architecture:** A thread-safe, loop-aware module-singleton `RunEventBus` appends structured events to a per-run append-only log and fans them out to async SSE subscribers. The synchronous, threaded engine calls `publish()` (works headless = log-only when no loop is bound); the async SSE endpoint calls `subscribe()` which replays the log then tails live. `WorkflowPlan` is a projection: the current plan is always the last `plan.updated` event in the log, so it can never drift from execution.

**Tech Stack:** Python 3.12/3.13, FastAPI (`StreamingResponse`, `text/event-stream`), Pydantic v2, asyncio + threading bridge (`loop.call_soon_threadsafe`), pytest. Spec: `docs/superpowers/specs/2026-06-18-run-event-substrate-and-dynamic-plan-design.md`.

**Conventions to respect:**
- Always `source venv/bin/activate` first.
- The format hook strips imports unused *at edit time* — add an import and its first usage in the **same** edit (or write the whole file). See `project_format_hook_strips_imports`.
- Stage commits by explicit file path; never `git add -A`.
- Test command (CI parity): `pytest tests/ --ignore=tests/e2e -v`. Unit tests live in `tests/unit/`, integration in `tests/integration/`.

---

## Decisions locked from spec review

1. `plan.updated` carries **full `WorkflowPlan` snapshots** (not diffs) in v1.
2. UI **keeps polling as a fallback** and *adds* the SSE stream.
3. `WorkflowPlan` / `PlanItem` are defined in **`api/models/workflow_models.py`** (same module as `WorkflowRun`, to avoid an import cycle — `WorkflowRun` gains a `plan` field).
4. **Out of scope this plan** (deferred fast-follows): L2-executable (injecting steps into the live DAG), L3 (multi-run chaining), `kind: opencode` producer, and **live `token.delta` streaming** (requires `StepExecutor` stream-loop integration). `token.delta` is *defined* as an event-type constant for forward-compat but **not emitted** here.

---

## File Structure

**New files:**
- `api/models/run_event.py` — `RunEvent` envelope + `EventType` string constants. One responsibility: the wire/log shape of an event.
- `api/services/run_event_bus.py` — `RunEventBus` (log append + seq + async fan-out + replay) + `get_run_event_bus()` singleton accessor + `RUNS_DIR`.
- `api/services/run_plan.py` — `PlanBuilder` (baseline-from-definition, reconstruct-from-log, mutation helpers, `emit_plan`). One responsibility: building/emitting plan snapshots.
- `tests/unit/test_run_event.py`, `tests/unit/test_run_event_bus.py`, `tests/unit/test_run_plan.py`
- `tests/integration/test_run_event_stream.py` (engine + SSE)

**Modified files:**
- `api/models/workflow_models.py` — add `WorkflowPlan`, `PlanItem`; add `WorkflowRun.plan: Optional[WorkflowPlan]`.
- `api/services/workflow_engine.py` — cache bus in `__init__`; emit `run.status` + baseline `plan.updated` at run start; emit terminal `run.status`; bracket `_execute_one_step` with `step.started`/`step.completed`; emit `gate.pending` at the gate.
- `api/services/engine_executors/orchestrator.py` — emit plan enrichment on worker spawn.
- `api/services/engine_executors/ralph.py` — emit plan enrichment per iteration.
- `api/hooks/builtins/plugin_tool_invoker.py`, `api/hooks/builtins/mcp_tool_invoker.py` — emit `tool.called` after invocation.
- `api/routers/workflows.py` — add `GET /api/workflows/runs/{run_id}/stream` SSE endpoint; emit `gate.resolved` in the resolve handler.
- `api/main.py` — `get_run_event_bus().bind_loop(asyncio.get_running_loop())` in lifespan.
- `api/static/index.html` — Runs view consumes `EventSource`; renders live plan + step timeline.
- `CHANGELOG.md` — `[Unreleased]` entry.

---

## Task 1: RunEvent model + EventType constants

**Files:**
- Create: `api/models/run_event.py`
- Test: `tests/unit/test_run_event.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_run_event.py
from api.models.run_event import RunEvent, EventType


def test_run_event_roundtrips_and_has_core_types():
    ev = RunEvent(seq=1, run_id="r1", ts="2026-06-18T00:00:00Z",
                  type=EventType.STEP_STARTED, step_id="s1", data={"kind": "llm"})
    dumped = ev.model_dump(mode="json")
    assert dumped["seq"] == 1
    assert dumped["type"] == "step.started"
    assert dumped["step_id"] == "s1"
    # round-trip from a JSONL line
    assert RunEvent.model_validate(dumped).data["kind"] == "llm"
    # taxonomy present
    assert EventType.RUN_STATUS == "run.status"
    assert EventType.PLAN_UPDATED == "plan.updated"
    assert EventType.GATE_PENDING == "gate.pending"
    assert EventType.TOOL_CALLED == "tool.called"
    assert EventType.STREAM_HELLO == "stream.hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_run_event.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.models.run_event'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/models/run_event.py
"""Run event envelope + taxonomy (v1). One event = one append-only log line."""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType:
    """v1 event-type string constants. Mirrors OpenCode session.status / todo.updated / permission.asked."""
    STREAM_HELLO = "stream.hello"
    STREAM_RESYNC = "stream.resync"
    STREAM_END = "stream.end"
    RUN_STATUS = "run.status"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    PLAN_UPDATED = "plan.updated"
    GATE_PENDING = "gate.pending"
    GATE_RESOLVED = "gate.resolved"
    TOOL_CALLED = "tool.called"
    TOKEN_DELTA = "token.delta"  # defined for forward-compat; not emitted in v1
    LOG = "log"


class RunEvent(BaseModel):
    """A single run event. `seq` is monotonic per run (used as SSE Last-Event-ID)."""
    seq: int
    run_id: str
    ts: str  # ISO-8601 UTC
    type: str
    step_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_run_event.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/models/run_event.py tests/unit/test_run_event.py
git commit -m "feat(events): RunEvent envelope + v1 event taxonomy"
```

---

## Task 2: RunEventBus — publish, seq, log append (headless)

**Files:**
- Create: `api/services/run_event_bus.py`
- Test: `tests/unit/test_run_event_bus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_run_event_bus.py
import api.services.run_event_bus as reb
from api.models.run_event import EventType


def test_publish_appends_monotonic_seq_and_reads_back(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    bus = reb.RunEventBus()
    e1 = bus.publish("run1", EventType.RUN_STATUS, {"status": "running"})
    e2 = bus.publish("run1", EventType.STEP_STARTED, {"kind": "llm"}, step_id="s1")
    assert (e1.seq, e2.seq) == (1, 2)
    assert e1.run_id == "run1" and e1.ts.endswith("Z")

    log = bus.read_log("run1")
    assert [e.type for e in log] == [EventType.RUN_STATUS, EventType.STEP_STARTED]
    assert bus.read_log("run1", since=1)[0].seq == 2  # since is exclusive


def test_singleton_accessor_is_stable():
    assert reb.get_run_event_bus() is reb.get_run_event_bus()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_run_event_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.services.run_event_bus'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/run_event_bus.py
"""In-process run event bus: append-only per-run log + (Task 3) async fan-out.

Source of truth is data/workflows/<run_id>/events.jsonl. publish() is sync and
thread-safe so the synchronous, threaded WorkflowEngine can call it from worker
threads; it works headless (log-only) when no event loop is bound.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.run_event import RunEvent

RUNS_DIR = os.getenv("ENCLAVE_RUNS_DIR", "./data/workflows")


class RunEventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq: Dict[str, int] = {}

    def _log_path(self, run_id: str) -> Path:
        return Path(RUNS_DIR) / run_id / "events.jsonl"

    def _next_seq(self, run_id: str) -> int:
        # caller holds self._lock
        nxt = self._seq.get(run_id)
        if nxt is None:
            # recover from any existing log so seq stays monotonic across restarts
            existing = self.read_log(run_id)
            nxt = existing[-1].seq if existing else 0
        nxt += 1
        self._seq[run_id] = nxt
        return nxt

    def publish(self, run_id: str, type: str, data: Optional[Dict[str, Any]] = None,
                step_id: Optional[str] = None) -> RunEvent:
        with self._lock:
            seq = self._next_seq(run_id)
            event = RunEvent(
                seq=seq, run_id=run_id,
                ts=datetime.utcnow().isoformat() + "Z",
                type=type, step_id=step_id, data=data or {},
            )
            self._append(event)
        return event

    def _append(self, event: RunEvent) -> None:
        path = self._log_path(event.run_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps(event.model_dump(mode="json")) + "\n")
        except OSError:
            # Observability must never crash a run.
            pass

    def read_log(self, run_id: str, since: int = 0) -> List[RunEvent]:
        """Return logged events with seq > `since` (since is exclusive)."""
        path = self._log_path(run_id)
        if not path.exists():
            return []
        out: List[RunEvent] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = RunEvent.model_validate(json.loads(line))
                if ev.seq > since:
                    out.append(ev)
        return out


_BUS: Optional[RunEventBus] = None


def get_run_event_bus() -> RunEventBus:
    global _BUS
    if _BUS is None:
        _BUS = RunEventBus()
    return _BUS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_run_event_bus.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/run_event_bus.py tests/unit/test_run_event_bus.py
git commit -m "feat(events): RunEventBus publish + append-only per-run log"
```

---

## Task 3: RunEventBus — async subscribe (replay + live tail + resync)

**Files:**
- Modify: `api/services/run_event_bus.py`
- Test: `tests/unit/test_run_event_bus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_run_event_bus.py  (append)
import asyncio
import pytest


@pytest.mark.asyncio
async def test_subscribe_replays_then_tails_live(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    bus = reb.RunEventBus()
    bus.bind_loop(asyncio.get_running_loop())
    bus.publish("r", EventType.RUN_STATUS, {"status": "running"})  # pre-existing (replayed)

    received = []
    sub = bus.subscribe("r", since=0)

    async def reader():
        async for ev in sub:
            received.append(ev)
            if len(received) == 3:
                break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.05)
    bus.publish("r", EventType.STEP_STARTED, {"kind": "llm"}, step_id="s1")  # live
    bus.publish("r", EventType.STEP_COMPLETED, {"status": "completed"}, step_id="s1")
    await asyncio.wait_for(task, timeout=2.0)

    assert [e.type for e in received] == [
        EventType.RUN_STATUS, EventType.STEP_STARTED, EventType.STEP_COMPLETED]
    assert [e.seq for e in received] == [1, 2, 3]  # monotonic, no dupes
```

Add to `tests/unit/test_run_event_bus.py` top: `import asyncio`, `import pytest`. (The repo already uses `pytest-asyncio`; confirm `asyncio_mode = auto` or keep the `@pytest.mark.asyncio` marker as written.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_run_event_bus.py::test_subscribe_replays_then_tails_live -v`
Expected: FAIL — `AttributeError: 'RunEventBus' object has no attribute 'bind_loop'`

- [ ] **Step 3: Write minimal implementation**

Add `import asyncio` to the imports. Add to `__init__`:

```python
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subs: Dict[str, List[asyncio.Queue]] = {}
```

Add these methods to `RunEventBus`:

```python
    def bind_loop(self, loop: "asyncio.AbstractEventLoop") -> None:
        """Capture the running event loop so publish() (sync, maybe off-thread) can fan out."""
        self._loop = loop

    def _fanout(self, event: RunEvent) -> None:
        # caller holds self._lock; schedule thread-safe puts onto each subscriber queue
        subs = list(self._subs.get(event.run_id, []))
        if not subs or self._loop is None:
            return

        def _deliver(q: "asyncio.Queue", ev: RunEvent) -> None:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # slow subscriber: signal resync, drop its tail
                try:
                    q.put_nowait(RunEvent(seq=ev.seq, run_id=ev.run_id, ts=ev.ts,
                                          type="stream.resync", data={"since": ev.seq}))
                except asyncio.QueueFull:
                    pass

        for q in subs:
            self._loop.call_soon_threadsafe(_deliver, q, event)

    async def subscribe(self, run_id: str, since: int = 0):
        """Async generator: replay log from `since` (exclusive), then tail live events."""
        q: "asyncio.Queue" = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(run_id, []).append(q)
            replay = self.read_log(run_id, since=since)
        try:
            last = since
            for ev in replay:
                last = ev.seq
                yield ev
            while True:
                ev = await q.get()
                if ev.seq <= last and ev.type != "stream.resync":
                    continue  # de-dupe overlap between replay tail and live head
                last = max(last, ev.seq)
                yield ev
        finally:
            with self._lock:
                lst = self._subs.get(run_id, [])
                if q in lst:
                    lst.remove(q)
```

Wire fan-out into `publish()` — inside the `with self._lock:` block, immediately after `self._append(event)`:

```python
            self._append(event)
            self._fanout(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_run_event_bus.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/run_event_bus.py tests/unit/test_run_event_bus.py
git commit -m "feat(events): async subscribe — replay-from-log + live tail + resync"
```

---

## Task 4: WorkflowPlan / PlanItem models + PlanBuilder

**Files:**
- Modify: `api/models/workflow_models.py` (add `PlanItem`, `WorkflowPlan` near `WorkflowRun`, ~line 1240)
- Create: `api/services/run_plan.py`
- Test: `tests/unit/test_run_plan.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_run_plan.py
from api.models.workflow_models import WorkflowDefinition, WorkflowPlan
from api.services.run_plan import PlanBuilder


def _defn():
    return WorkflowDefinition.model_validate({
        "id": "wf",
        "steps": [
            {"id": "a", "name": "Triage", "outputs": ["x"]},
            {"id": "b", "name": "Report", "outputs": ["y"], "depends_on": ["a"]},
        ],
    })


def test_baseline_projects_top_level_steps():
    plan = PlanBuilder.baseline_from_definition(_defn())
    assert isinstance(plan, WorkflowPlan)
    assert plan.revision == 1
    assert [(i.id, i.title, i.status, i.origin) for i in plan.items] == [
        ("a", "Triage", "pending", "dag"),
        ("b", "Report", "pending", "dag"),
    ]


def test_mutation_helpers_and_child_add():
    plan = PlanBuilder.baseline_from_definition(_defn())
    PlanBuilder.mark_item(plan, "a", "in_progress", updated_seq=5)
    assert next(i for i in plan.items if i.id == "a").status == "in_progress"
    PlanBuilder.add_child(plan, parent_id="a", item_id="a::w1",
                          title="worker-1", origin="orchestrator", updated_seq=6)
    child = next(i for i in plan.items if i.id == "a::w1")
    assert child.parent_id == "a" and child.origin == "orchestrator"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_run_plan.py -v`
Expected: FAIL — `ImportError: cannot import name 'WorkflowPlan'`

- [ ] **Step 3a: Add models to `api/models/workflow_models.py`**

Insert immediately **before** `class WorkflowRun(BaseModel):` (~line 1250). The `Literal`, `List`, `Optional`, `Field`, `BaseModel` imports already exist in this file.

```python
class PlanItem(BaseModel):
    """One node of a run's live plan. Observable projection — not an executable step."""
    id: str
    title: str
    status: Literal["pending", "in_progress", "done", "skipped", "failed", "blocked"] = "pending"
    origin: Literal["dag", "orchestrator", "ralph", "external"] = "dag"
    step_ref: Optional[str] = None
    parent_id: Optional[str] = None
    detail: Optional[str] = None
    updated_seq: int = 0


class WorkflowPlan(BaseModel):
    goal: str = ""
    revision: int = 0
    items: List[PlanItem] = Field(default_factory=list)
```

- [ ] **Step 3b: Add `plan` field to `WorkflowRun`**

In `class WorkflowRun(BaseModel):` (~line 1250), add after `context: WorkflowContext`:

```python
    plan: Optional[WorkflowPlan] = None
```

- [ ] **Step 3c: Create `api/services/run_plan.py`**

```python
# api/services/run_plan.py
"""Build and emit WorkflowPlan snapshots. The plan is a projection over the
event log: the current plan is the last plan.updated event (reconstruct_from_log)."""
from typing import Optional

from ..models.run_event import EventType
from ..models.workflow_models import PlanItem, WorkflowDefinition, WorkflowPlan


class PlanBuilder:
    @staticmethod
    def baseline_from_definition(definition: WorkflowDefinition) -> WorkflowPlan:
        items = [
            PlanItem(id=s.id, title=s.name or s.id, status="pending",
                     origin="dag", step_ref=s.id)
            for s in definition.steps
        ]
        return WorkflowPlan(goal=definition.id, revision=1, items=items)

    @staticmethod
    def mark_item(plan: WorkflowPlan, item_id: str, status: str, updated_seq: int) -> None:
        for item in plan.items:
            if item.id == item_id:
                item.status = status  # type: ignore[assignment]
                item.updated_seq = updated_seq
                return

    @staticmethod
    def add_child(plan: WorkflowPlan, parent_id: str, item_id: str, title: str,
                  origin: str, updated_seq: int, detail: Optional[str] = None) -> None:
        if any(i.id == item_id for i in plan.items):
            return
        plan.items.append(PlanItem(
            id=item_id, title=title, status="in_progress", origin=origin,  # type: ignore[arg-type]
            parent_id=parent_id, detail=detail, updated_seq=updated_seq))

    @staticmethod
    def emit(bus, run_id: str, plan: WorkflowPlan, step_id: Optional[str] = None):
        """Bump revision and publish a full plan.updated snapshot."""
        plan.revision += 1
        return bus.publish(run_id, EventType.PLAN_UPDATED,
                           {"revision": plan.revision, "plan": plan.model_dump(mode="json")},
                           step_id=step_id)

    @staticmethod
    def reconstruct_from_log(bus, run_id: str) -> Optional[WorkflowPlan]:
        last = None
        for ev in bus.read_log(run_id):
            if ev.type == EventType.PLAN_UPDATED:
                last = ev
        if last is None:
            return None
        return WorkflowPlan.model_validate(last.data["plan"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_run_plan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/models/workflow_models.py api/services/run_plan.py tests/unit/test_run_plan.py
git commit -m "feat(plan): WorkflowPlan/PlanItem models + PlanBuilder projection"
```

---

## Task 5: Engine emits run.status + baseline plan + terminal status

**Files:**
- Modify: `api/services/workflow_engine.py` (`__init__` ~line 150; `run()` ~line 585; terminal ~line 1021)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py
import api.services.run_event_bus as reb
from api.models.run_event import EventType
from api.models.workflow_models import WorkflowDefinition
from api.services.workflow_engine import WorkflowEngine
from tests.integration.conftest import FakeOllamaClient


def _wf():
    return WorkflowDefinition.model_validate({
        "id": "evt_wf",
        "steps": [{"id": "a", "name": "Step A", "outputs": ["out"]}],
    })


def test_run_emits_status_and_baseline_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None  # fresh singleton picks up patched RUNS_DIR
    engine = WorkflowEngine(FakeOllamaClient(["done"]))
    run = engine.run(_wf(), seed={})

    bus = reb.get_run_event_bus()
    types = [e.type for e in bus.read_log(run.run_id)]
    assert types[0] == EventType.RUN_STATUS          # running
    assert EventType.PLAN_UPDATED in types           # baseline plan
    assert types[-1] == EventType.RUN_STATUS         # terminal
    statuses = [e.data["status"] for e in bus.read_log(run.run_id)
                if e.type == EventType.RUN_STATUS]
    assert statuses[0] == "running" and statuses[-1] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_run_emits_status_and_baseline_plan -v`
Expected: FAIL — no `run.status` events in the log (assertion error on `types[0]`).

- [ ] **Step 3a: Cache the bus in `__init__`**

In `WorkflowEngine.__init__` (~line 160), add (import + usage in the same edit so the format hook keeps it):

```python
        from .run_event_bus import get_run_event_bus
        self._bus = get_run_event_bus()
```

- [ ] **Step 3b: Emit at run start.** In `run()` (~line 585), right after `self._checkpoint(workflow_run)` (the "Initial checkpoint" line):

```python
        self._bus.publish(workflow_run.run_id, "run.status", {"status": "running"})
        from .run_plan import PlanBuilder
        workflow_run.plan = PlanBuilder.baseline_from_definition(definition)
        self._bus.publish(
            workflow_run.run_id, "plan.updated",
            {"revision": workflow_run.plan.revision,
             "plan": workflow_run.plan.model_dump(mode="json")},
        )
```

- [ ] **Step 3c: Emit terminal status.** After `workflow_run.status = "completed"` (~line 1021):

```python
        self._bus.publish(workflow_run.run_id, "run.status", {"status": "completed"})
```

Find the failure path that sets `workflow_run.status = "failed"` (search `= "failed"` in this file) and add directly after it:

```python
        self._bus.publish(workflow_run.run_id, "run.status",
                          {"status": "failed", "reason": workflow_run.error})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/workflow_engine.py tests/integration/test_run_event_stream.py
git commit -m "feat(events): engine emits run.status + baseline plan.updated"
```

---

## Task 6: Engine emits step.started / step.completed

**Files:**
- Modify: `api/services/workflow_engine.py` (`_execute_one_step` ~lines 1265–1339)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py  (append)
def test_emits_step_started_and_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    engine = WorkflowEngine(FakeOllamaClient(["done"]))
    run = engine.run(_wf(), seed={})
    log = reb.get_run_event_bus().read_log(run.run_id)
    started = [e for e in log if e.type == EventType.STEP_STARTED and e.step_id == "a"]
    completed = [e for e in log if e.type == EventType.STEP_COMPLETED and e.step_id == "a"]
    assert started and completed
    assert completed[0].data["status"] == "completed"
    assert "duration_ms" in completed[0].data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_emits_step_started_and_completed -v`
Expected: FAIL — no `step.started` events.

- [ ] **Step 3: Bracket the dispatch ladder.** In `_execute_one_step` (~line 1265), wrap the existing `if step.kind == ...` dispatch ladder (everything from the first `if step.kind == "parallel":` through the final `llm`-default `return`) inside a nested `def _dispatch() -> StepResult:`, then bracket it. The method becomes:

```python
    def _execute_one_step(self, step, definition, context, workflow_run,
                          resolved_model, prefix_locked=False) -> StepResult:
        """Run a single step end-to-end. Dispatches on `step.kind`."""

        def _dispatch() -> StepResult:
            # ... EXISTING dispatch ladder, unchanged (parallel/loop/a2a/orchestrator/
            #     consolidate/ralph/code/llm-default), indented one level ...
            ...

        self._bus.publish(workflow_run.run_id, "step.started",
                          {"kind": step.kind, "title": getattr(step, "name", step.id)},
                          step_id=step.id)
        result = _dispatch()
        self._bus.publish(workflow_run.run_id, "step.completed", {
            "status": result.status,
            "duration_ms": int((result.duration_seconds or 0) * 1000),
            "model_used": result.model_used,
            "error": result.error,
        }, step_id=step.id)
        return result
```

(Mechanical: indent the existing ladder one level into `_dispatch`, change its `return X` statements to stay as `return` inside `_dispatch`, then add the three statements after it. No logic inside the ladder changes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/workflow_engine.py tests/integration/test_run_event_stream.py
git commit -m "feat(events): emit step.started/step.completed around dispatch"
```

---

## Task 7: Engine emits gate.pending

**Files:**
- Modify: `api/services/workflow_engine.py` (gate path ~lines 986–992)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py  (append)
def test_emits_gate_pending_when_awaiting_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    # A kind=code step at a tier that requires approval pauses the run.
    wf = WorkflowDefinition.model_validate({
        "id": "gate_wf",
        "steps": [{
            "id": "c", "name": "Run code", "kind": "code", "outputs": ["res"],
            "code": {"language": "python", "source": "print('hi')",
                     "network": "none", "approval": "always"},
        }],
    })
    engine = WorkflowEngine(FakeOllamaClient([]))
    run = engine.run(wf, seed={})
    assert run.status == "awaiting_approval"
    gate_evs = [e for e in reb.get_run_event_bus().read_log(run.run_id)
                if e.type == EventType.GATE_PENDING]
    assert gate_evs and gate_evs[0].data["gate_id"]
    assert gate_evs[0].data["step_id"] == "c"
```

> If the exact `code` step schema differs, adapt the YAML to whatever the existing `tests/` use for an approval-gated `kind: code` step (grep `tests/` for `"approval"` / `GatePending`). The assertion on the emitted event is the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_emits_gate_pending_when_awaiting_approval -v`
Expected: FAIL — no `gate.pending` event.

- [ ] **Step 3: Emit at the gate.** At the gate path (~line 986), right after `workflow_run.status = "awaiting_approval"` and `self._checkpoint(workflow_run)`:

```python
        g = workflow_run.pending_gate
        if g is not None:
            self._bus.publish(workflow_run.run_id, "gate.pending", {
                "gate_id": g.gate_id, "step_id": g.step_id, "kind": "approval",
                "prompt": g.question or f"Approve step '{g.step_id}'?",
                "tier": g.tier, "files": g.files, "network": g.network,
            }, step_id=g.step_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/workflow_engine.py tests/integration/test_run_event_stream.py
git commit -m "feat(events): emit gate.pending at HITL approval gate"
```

---

## Task 8: Plan enrichment — orchestrator worker spawn

**Files:**
- Modify: `api/services/engine_executors/orchestrator.py` (spawn site, inside the main loop)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py  (append)
def test_orchestrator_spawn_enriches_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    # Lead emits one spawn directive, then completes. Worker echoes.
    # Build the minimal orchestrator workflow your repo's orchestrator tests use
    # (grep tests/ for kind: orchestrator) and script the FakeOllamaClient so the
    # lead's first turn spawns worker "w1" and the second turn completes.
    ...  # construct `wf` + scripted FakeOllamaClient per existing orchestrator test
    engine = WorkflowEngine(fake)
    run = engine.run(wf, seed={})
    plan = PlanBuilder.reconstruct_from_log(reb.get_run_event_bus(), run.run_id)
    assert any(i.origin == "orchestrator" for i in plan.items)
```

```python
# add import at top of file:
from api.services.run_plan import PlanBuilder
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_orchestrator_spawn_enriches_plan -v`
Expected: FAIL — no plan item with `origin == "orchestrator"`.

- [ ] **Step 3: Emit on spawn.** In `orchestrator.execute(...)`, at the spawn-directive branch (where `directive.spawn` / `worker_id` is resolved, ~line 150), after the worker is identified and before/after dispatch:

```python
            if workflow_run.plan is not None:
                from ..run_plan import PlanBuilder
                PlanBuilder.add_child(
                    workflow_run.plan, parent_id=step.id,
                    item_id=f"{step.id}::{worker_id}",
                    title=f"worker: {worker_id}", origin="orchestrator",
                    updated_seq=0)
                PlanBuilder.emit(engine._bus, workflow_run.run_id,
                                 workflow_run.plan, step_id=step.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/engine_executors/orchestrator.py tests/integration/test_run_event_stream.py
git commit -m "feat(plan): orchestrator worker spawns enrich the live plan"
```

---

## Task 9: Plan enrichment — ralph iterations

**Files:**
- Modify: `api/services/engine_executors/ralph.py` (iteration loop top ~line 100)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py  (append)
def test_ralph_iterations_enrich_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    # Minimal kind=ralph workflow that runs 2 iterations then halts (grep tests/
    # for kind: ralph to mirror the existing halt/goal config + scripted responses).
    ...  # construct `wf` + FakeOllamaClient
    engine = WorkflowEngine(fake)
    run = engine.run(wf, seed={})
    plan = PlanBuilder.reconstruct_from_log(reb.get_run_event_bus(), run.run_id)
    iters = [i for i in plan.items if i.origin == "ralph"]
    assert len(iters) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_ralph_iterations_enrich_plan -v`
Expected: FAIL — fewer than 2 `origin == "ralph"` items.

- [ ] **Step 3: Emit per iteration.** In `ralph.execute(...)`, right after `iteration += 1` (~line 102):

```python
        if workflow_run.plan is not None:
            from ..run_plan import PlanBuilder
            PlanBuilder.add_child(
                workflow_run.plan, parent_id=step.id,
                item_id=f"{step.id}::iter{iteration}",
                title=f"iteration {iteration}", origin="ralph", updated_seq=0)
            PlanBuilder.emit(engine._bus, workflow_run.run_id,
                             workflow_run.plan, step_id=step.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/engine_executors/ralph.py tests/integration/test_run_event_stream.py
git commit -m "feat(plan): ralph iterations enrich the live plan"
```

---

## Task 10: tool.called from tool-invoker hooks

**Files:**
- Modify: `api/hooks/builtins/mcp_tool_invoker.py`, `api/hooks/builtins/plugin_tool_invoker.py`
- Test: `tests/unit/test_tool_called_event.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tool_called_event.py
import api.services.run_event_bus as reb
from api.models.run_event import EventType


def test_emit_tool_called_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    from api.hooks.builtins.mcp_tool_invoker import _emit_tool_called
    _emit_tool_called(run_id="r", step_id="s", tool="search",
                      server="srv", status="ok")
    evs = [e for e in reb.get_run_event_bus().read_log("r")
           if e.type == EventType.TOOL_CALLED]
    assert evs and evs[0].data["tool"] == "search" and evs[0].data["server"] == "srv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_called_event.py -v`
Expected: FAIL — `ImportError: cannot import name '_emit_tool_called'`

- [ ] **Step 3: Add the helper + call it.** In `api/hooks/builtins/mcp_tool_invoker.py`, add a shared helper (import + usage in one edit):

```python
def _emit_tool_called(run_id, step_id, tool, server=None, status="ok"):
    from ...services.run_event_bus import get_run_event_bus
    from ...models.run_event import EventType
    get_run_event_bus().publish(run_id, EventType.TOOL_CALLED,
                                {"tool": tool, "server": server, "status": status},
                                step_id=step_id)
```

Then at the insertion point (after `result = await mcp_service.invoke_tool(...)` returns, ~line 150):

```python
        try:
            _emit_tool_called(
                run_id=ctx.workflow.run_id, step_id=ctx.step.id,
                tool=self.tool_name, server=self.server_id,
                status="ok" if result is not None else "error")
        except Exception:
            pass  # never let observability break a tool call
```

Repeat the same `_emit_tool_called` helper + call in `api/hooks/builtins/plugin_tool_invoker.py` after its `svc.invoke_tool(...)` returns (use `server=self.server_id`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tool_called_event.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/hooks/builtins/mcp_tool_invoker.py api/hooks/builtins/plugin_tool_invoker.py tests/unit/test_tool_called_event.py
git commit -m "feat(events): tool-invoker hooks emit tool.called"
```

---

## Task 11: SSE endpoint + lifespan loop binding

**Files:**
- Modify: `api/routers/workflows.py` (new endpoint near `get_run` ~line 552; imports ~line 27)
- Modify: `api/main.py` (lifespan ~line 90)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py  (append)
from fastapi.testclient import TestClient


def test_sse_endpoint_replays_run_events(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    engine = WorkflowEngine(FakeOllamaClient(["done"]))
    run = engine.run(_wf(), seed={})  # completed run; log on disk

    from api.main import app
    with TestClient(app) as client:
        with client.stream("GET", f"/api/workflows/runs/{run.run_id}/stream") as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            body = ""
            for chunk in r.iter_text():
                body += chunk
                if "run.status" in body and "completed" in body:
                    break
    assert "event: run.status" in body
    assert "event: plan.updated" in body
    assert "event: stream.end" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_sse_endpoint_replays_run_events -v`
Expected: FAIL — 404 (endpoint not defined).

- [ ] **Step 3a: Add the SSE endpoint.** In `api/routers/workflows.py`, ensure imports (add in one edit with usage): `import asyncio`, `import json`, and `from fastapi import Request`, `from fastapi.responses import StreamingResponse`. After `get_run` (~line 568):

```python
@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, since: int = 0):
    """Live SSE stream of a run's events. Honors Last-Event-ID / ?since= for resume."""
    from ..services.run_event_bus import get_run_event_bus
    bus = get_run_event_bus()

    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdigit():
        since = int(last_event_id)

    async def _gen():
        # hello frame
        existing = bus.read_log(run_id, since=since)
        last_seq = existing[-1].seq if existing else since
        yield f"event: stream.hello\ndata: {json.dumps({'last_seq': last_seq})}\n\n"

        terminal = {"completed", "failed", "canceled"}
        async for ev in bus.subscribe(run_id, since=since):
            payload = json.dumps(ev.model_dump(mode="json"))
            yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {payload}\n\n"
            if ev.type == "run.status" and ev.data.get("status") in terminal:
                # drain any trailing logged events, then close
                yield "event: stream.end\ndata: {}\n\n"
                return

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
```

> Note: for an already-terminal run, `subscribe` replays the logged events (including the terminal `run.status`), so `_gen` emits `stream.end` and returns without hanging.

- [ ] **Step 3b: Bind the loop in lifespan.** In `api/main.py` `lifespan` (~line 90), add (import + usage one edit):

```python
    import asyncio
    from .services.run_event_bus import get_run_event_bus
    get_run_event_bus().bind_loop(asyncio.get_running_loop())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add api/routers/workflows.py api/main.py tests/integration/test_run_event_stream.py
git commit -m "feat(events): SSE GET /runs/{id}/stream (replay+tail, Last-Event-ID) + loop binding"
```

---

## Task 12: gate.resolved on the resolve handler

**Files:**
- Modify: `api/routers/workflows.py` (find the existing gate-resolve/approve endpoint — grep `approve` / `gate` / `resume` in this file)
- Test: `tests/integration/test_run_event_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_run_event_stream.py  (append)
def test_gate_resolution_emits_event(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    # Reuse the gate workflow from Task 7 to produce an awaiting_approval run,
    # then POST the existing approve/resolve endpoint and assert gate.resolved.
    ...  # build gated run via engine.run(...)
    from api.main import app
    with TestClient(app) as client:
        # adapt path/body to the repo's real resolve endpoint:
        client.post(f"/api/workflows/runs/{run.run_id}/gate",
                    json={"gate_id": gate_id, "decision": "approved"})
    evs = [e for e in reb.get_run_event_bus().read_log(run.run_id)
           if e.type == EventType.GATE_RESOLVED]
    assert evs and evs[0].data["response"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_run_event_stream.py::test_gate_resolution_emits_event -v`
Expected: FAIL — no `gate.resolved` event.

- [ ] **Step 3: Emit on resolve.** In the resolve handler, after the decision is recorded (and before/after `engine.resume(...)`):

```python
    from ..services.run_event_bus import get_run_event_bus
    get_run_event_bus().publish(run_id, "gate.resolved",
                                {"gate_id": gate_id, "response": decision},
                                step_id=step_id)
```

(Use the handler's actual variable names for `decision`/`gate_id`/`step_id`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_run_event_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/workflows.py tests/integration/test_run_event_stream.py
git commit -m "feat(events): emit gate.resolved on operator decision"
```

---

## Task 13: Live Runs view (UI)

**Files:**
- Modify: `api/static/index.html` (Runs view; it already has `#/runs/<run_id>` deep links + a `Net` fetch layer)
- Test: `tests/playwright/test_runs_live_stream.py` (mirror existing playwright tests)

- [ ] **Step 1: Write the failing test**

```python
# tests/playwright/test_runs_live_stream.py
# Mirror the existing playwright harness (grep tests/playwright for the page fixture
# + base URL). Drive a run, open #/runs/<run_id>, assert the live plan + a step row.
def test_runs_view_renders_live_plan(page, base_url, started_run_id):
    page.goto(f"{base_url}/#/runs/{started_run_id}")
    page.wait_for_selector("[data-testid='run-plan']")
    assert page.locator("[data-testid='plan-item']").count() >= 1
    page.wait_for_selector("[data-testid='run-status'][data-status='completed']",
                           timeout=15000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/playwright/test_runs_live_stream.py -v`
Expected: FAIL — selectors not found.

- [ ] **Step 3: Add the EventSource subscriber + render.** In the Runs-view module of `index.html`, when a run detail opens, attach an `EventSource` and render plan + timeline. Keep polling as the fallback (do not remove it). Sketch:

```javascript
function subscribeRun(runId) {
  const es = new EventSource(`/api/workflows/runs/${runId}/stream`);
  const plan = { items: [] };
  es.addEventListener('plan.updated', (e) => {
    const { plan: p } = JSON.parse(e.data).data;
    renderPlan(p);                       // into [data-testid='run-plan']
  });
  es.addEventListener('step.started', (e) => upsertStepRow(JSON.parse(e.data)));
  es.addEventListener('step.completed', (e) => upsertStepRow(JSON.parse(e.data)));
  es.addEventListener('gate.pending', (e) => showGatePrompt(JSON.parse(e.data)));
  es.addEventListener('run.status', (e) => {
    const { status } = JSON.parse(e.data).data;
    setRunStatus(status);                // [data-testid='run-status'][data-status]
  });
  es.addEventListener('stream.end', () => es.close());
  es.onerror = () => { es.close(); startPolling(runId); }; // graceful fallback
}
```

Add the DOM scaffolding with the `data-testid` hooks (`run-plan`, `plan-item`, `run-status`) used by the test, following the existing Runs-view markup/`data-action` conventions.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/playwright/test_runs_live_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/static/index.html tests/playwright/test_runs_live_stream.py
git commit -m "feat(ui): Runs view streams live plan + step timeline via EventSource"
```

---

## Task 14: CHANGELOG + full-suite gate

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add `[Unreleased]` entry**

```markdown
### Added
- **Run event substrate** — in-process `RunEventBus`, per-run append-only `events.jsonl`,
  and `GET /api/workflows/runs/{run_id}/stream` (SSE, `Last-Event-ID` resume). Runs are
  now observable live; polling remains as a fallback.
- **First-class run plan** — `WorkflowPlan`/`PlanItem` projected over the event stream
  (`plan.updated` snapshots), seeded from the compiled DAG and enriched live by
  orchestrator worker spawns and Ralph iterations.
```

- [ ] **Step 2: Run the full suite**

Run: `pytest tests/ --ignore=tests/e2e -v`
Expected: PASS (new + existing). Investigate any regression before proceeding.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): run event substrate + dynamic plan (1.3.0)"
```

---

## Self-Review

**Spec coverage:**
- L1 EventBus + log → Tasks 2–3. ✅
- SSE `/runs/{id}/stream` + `Last-Event-ID` resume → Task 11. ✅
- Event taxonomy (run.status/step.*/plan.updated/gate.*/tool.called; token.delta defined-not-wired) → Tasks 1, 5–12. ✅ (token.delta deferred, stated in Decisions.)
- `WorkflowPlan`/`PlanItem` + `WorkflowRun.plan` + baseline/enrichment → Tasks 4, 8, 9. ✅
- Hooks stay additive (tool.called via helper, never crashes) → Task 10. ✅
- Per-run `events.jsonl` alongside `run.json`; degraded-not-fatal on write failure → Task 2 (`_append` swallows `OSError`). ✅
- UI live + polling fallback → Task 13. ✅
- Reconnect/resume + de-dupe + overflow→resync → Task 3 (`subscribe`), Task 11 (Last-Event-ID). ✅

**Placeholder scan:** Tasks 8, 9, 12, 13 contain `...` where the engineer must mirror an *existing* repo test fixture (orchestrator/ralph/gate workflows, playwright harness) — these are explicitly flagged with grep pointers, not hidden TODOs; the emitted-event assertion is the fixed contract in each. All production code steps contain complete code.

**Type consistency:** `RunEvent(seq, run_id, ts, type, step_id, data)`, `EventType.*` constants, `RunEventBus.publish/subscribe/read_log/bind_loop/_fanout`, `PlanBuilder.baseline_from_definition/mark_item/add_child/emit/reconstruct_from_log`, `WorkflowPlan(goal, revision, items)`, `PlanItem(id, title, status, origin, step_ref, parent_id, detail, updated_seq)`, `self._bus` on the engine — all consistent across tasks.

---

## Execution Handoff

See the bottom of this conversation for the chosen execution mode (subagent-driven vs. inline).
