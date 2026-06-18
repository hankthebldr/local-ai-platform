# Run Event Substrate + Dynamic Plan — Design

- **Status:** Approved (design); implementation plan pending
- **Date:** 2026-06-18
- **Release track:** 1.3.0 (Runs view reflects the full pipeline end-to-end)
- **Scope:** L1 (event substrate) + L2-observable (first-class, revisable plan)
- **Inspiration:** OpenWork / OpenCode — dynamic in-workspace planning, a live `/event` SSE stream, and task chaining. This spec absorbs those *patterns* natively rather than wrapping the external tool.

## 1. Motivation

Enclave's workflow engine is a **statically-compiled DAG**: the step set is fixed at compile time, runs are observed by **polling** `GET /runs/{id}` (checkpoint-to-disk after each step), and the agent's "plan" is **implicit** — buried in orchestrator lead-agent directives (`{"spawn": ...}`) and Ralph's playbook. There is no live event stream and no first-class plan object.

OpenCode (the engine under OpenWork) does the opposite: a stateful **session** maintains a **live todo/plan** (`GET /session/:id/todo`, `todo.updated`), and everything is observable through a single **`/event` SSE stream** (`session.status`, `message.part.updated`, `permission.asked`, `question.asked`, `server.connected`, 30s heartbeats).

This design grafts those artifacts onto Enclave as a **native run-event substrate** with a **dynamic, observable plan** projected over it.

### Guiding realization

Do **not** build this as an "OpenWork connector." Build a native event + plan substrate where **OpenCode is just one future producer of events**. A later `kind: opencode` step becomes a thin translator from OpenCode's `/event` stream into Enclave's `RunEventBus` — same UI, same plan surface, same gates, regardless of whether work ran in Enclave's own engine or an OpenCode session. The substrate *is* the integration; OpenCode is the first guest.

### Layering (3 subsystems; this spec is L1 + L2-observable)

```
  L3   Reactive multi-run chaining (sub-runs)        ← deferred (consumes events)
  L2   First-class dynamic Plan / Todo (revisable)   ← THIS SPEC (observable variant)
  L1   EventBus + SSE run stream  (KEYSTONE)         ← THIS SPEC (everything rides this)
```

**Explicitly out of scope (deferred):**
- **L2-executable** — a planner that injects *new steps* into the live DAG mid-run. Today's scheduler, I/O validation, and checkpointing assume a fixed step set; this is a separate, more invasive spec.
- **L3** — cross-run reactive chaining / sub-runs.
- **`kind: opencode`** — driving a real OpenCode session as an event producer. Falls out cheaply on top of this substrate later.

## 2. Approach (chosen: A — event log is source of truth)

The engine emits a structured, append-only **event log per run** (`events.jsonl`, monotonic `seq`). The `RunEventBus` is a thin in-process fan-out *tee* of that log. SSE = **replay-from-log + tail-live** with `Last-Event-ID` resume. The **Plan is a projection**: the current plan is always "the last `plan.updated` event in the log," so it can never silently drift from execution reality, and reconnect reconstructs it for free.

Rejected alternatives:
- **B — Plan as mutable run state, bus broadcasts diffs.** Simpler, one artifact, but weaker reconnect (snapshot+tail can gap), plan/events can drift, and the future OpenCode producer needs a bespoke "mutate the plan" adapter instead of just emitting events.
- **C — extend hooks + finer polling.** Minimal surface, but declines the brief: polling latency, not the live-stream model.

Approach A is marginally more design now but makes L2-executable, L3, and the OpenCode producer all "just more events on the same bus," and it matches Enclave's existing append-only durability patterns (Ralph journal, `output_logger.jsonl`).

## 3. Architecture

```
                          publish(event)         ┌─ events.jsonl  (append-only, monotonic seq → durable truth)
  workflow_engine ──┐                             │
  orchestrator      ├──►  RunEventBus  ────────────┤
  ralph             │     (in-proc async)          └─ live asyncio.Queue per subscriber ──► SSE endpoint ──► UI
  tool/token hooks ─┘            ▲                                                              (EventSource)
                                 │ build()                                                       replay+tail
                          run_plan.PlanBuilder ──emits──► plan.updated (full WorkflowPlan snapshot)
```

New units, each single-purpose:

- **`RunEventBus`** (`api/services/run_event_bus.py`) — in-process async pub/sub.
  - `publish(event)` → assign `seq`, append to `data/workflows/{run_id}/events.jsonl`, fan out to live queues.
  - `subscribe(run_id, since)` → async generator: replay the log from `since`, then tail the live queue.
  - Singleton, constructed in `main.py` lifespan, injected into the engine + router (matches existing service-wiring convention).
- **`PlanBuilder`** (`api/services/run_plan.py`) — turns execution into `WorkflowPlan` snapshots, emitted as `plan.updated`. Also reconstructs the current plan from the log (= last `plan.updated` snapshot ≤ `seq`).
- **SSE endpoint** (`api/routers/workflows.py`) — `GET /api/workflows/runs/{run_id}/stream`, media type `text/event-stream`, honors `Last-Event-ID` header and `?since=` query.

### Seam decision: hooks stay synchronous/mutational; the bus is async/observational

`hook_bus` fires at 6 fixed lifecycle stages to *transform* prompts/outputs — the wrong tool for a live firehose. The engine emits to the bus **directly** at execution boundaries. The two tool-invoker builtin hooks (`plugin_tool_invoker`, `mcp_tool_invoker`) additionally publish `tool.called`. **No change to the existing hook contract** — this substrate is purely additive.

## 4. Event taxonomy (v1)

Envelope: `{ seq, run_id, ts, type, step_id?, data }`. Core types (mirroring OpenCode's `session.status` / `todo.updated` / `permission.asked`):

| type | `data` | emitted by |
|---|---|---|
| `stream.hello` | `{last_seq, replaying}` | SSE on connect (first frame) |
| `run.status` | `{status, reason?}` (queued→running→completed/failed/paused/cancelled) | engine |
| `step.started` | `{step_id, kind, title, attempt}` | engine scheduler |
| `step.completed` | `{step_id, status, duration_ms, tokens?, model_used?, error?}` | engine |
| `plan.updated` | `{revision, plan}` (full snapshot) | PlanBuilder |
| `gate.pending` | `{gate_id, step_id, kind: approval\|question, prompt, options?}` | engine (from `GatePending`) |
| `gate.resolved` | `{gate_id, response, remembered?}` | gate-resolve handler |
| `tool.called` | `{step_id, tool, server?, args_digest, status}` | tool-invoker hooks |
| `token.delta` | `{step_id, delta, cumulative}` (**coalesced**, ≤ ~every 250ms) | LLM stream |
| `log` | `{level, message}` | anywhere (operator breadcrumbs) |
| `stream.resync` | `{since}` | SSE on subscriber-queue overflow |
| `stream.end` | `{}` | SSE when a terminal run's log is fully replayed |

Heartbeat is an SSE comment (`:hb`) every 25s — **not** a logged event.

**Decision:** `plan.updated` carries a full snapshot (trivial reconstruction). Diff-based plan events are a noted future optimization.

## 5. Plan model (L2-observable)

```python
WorkflowPlan: { goal: str, revision: int, items: List[PlanItem] }

PlanItem: {
  id: str,                # DAG-derived items use step_id
  title: str,
  status: pending | in_progress | done | skipped | failed | blocked,
  origin: dag | orchestrator | ralph | external,   # provenance
  step_ref: str | None,
  parent_id: str | None,  # nesting: orchestrator workers, loop iterations
  detail: str | None,
  updated_seq: int,
}
```

`WorkflowRun` gains `plan: WorkflowPlan | None`, snapshotted into the existing `run.json` for convenience (the **log remains source of truth**).

### Plan sources — observable, NOT executable

Execution still uses today's primitives; we do **not** inject steps into the live DAG (that is the deferred L2-executable work).

1. **Baseline (every run):** at compile, project top-level `AgentStep`s → `PlanItem`s (`origin: dag`). Composite `parallel`/`loop` become parent items; children appear as branches/iterations actually run.
2. **Orchestrator enrichment:** when the lead agent emits a `{"spawn": worker}` directive, `orchestrator.py` adds a child item (`origin: orchestrator`). **This is the dynamic-planning payoff** — the implicit directive becomes a visible, live plan node.
3. **Ralph enrichment:** each iteration updates items reflecting plan→execute→verify→reflect; playbook lessons annotate `detail`.

## 6. Data flow

1. `run_workflow_async` → create run, open event log, emit `run.status: running`, build baseline Plan, emit `plan.updated rev 1`.
2. Each scheduler tick → `step.started` → executor runs → hooks emit `tool.called` / `token.delta` → on gate, emit `gate.pending` and suspend (today's `GatePending` path, unchanged) → `step.completed`.
3. Orchestrator / Ralph call `PlanBuilder` → `plan.updated rev N`.
4. Finish → `run.status: completed|failed` → final checkpoint (unchanged).
5. SSE client connects anytime → `stream.hello` → replay log from `since` → tail live → reconnect resumes via `Last-Event-ID`. Late subscribers to a finished run replay the whole story from the log, then receive `stream.end`.

## 7. Error handling

- **Event-log write failure** → log + set a degraded flag, **never crash the run** (observability is non-load-bearing).
- **Slow/dead subscriber** → bounded per-subscriber queue; on overflow, drop its tail and send `stream.resync` (client reconnects with `since`). The publisher never blocks.
- **Reconnect** → `since` > `last_seq` starts at current; missing log (legacy run) → 404 or synthetic replay derived from the checkpoint.
- **Run terminal at connect time** → replay full log, then `stream.end`, then close.
- **Auth** (when `ENABLE_API_AUTH=true`) applies to the stream endpoint identically to other routes.
- **Backward compat** → polling `GET /runs/{id}` stays; SSE is purely additive. UI keeps polling as a fallback and adds the live stream rather than removing polling.

## 8. Testing

- **Unit** — bus publish/subscribe/replay/resume; queue overflow → `stream.resync`; log durability (write → reopen → replay). PlanBuilder: baseline from a sample compiled DAG; orchestrator-spawn → child item; Ralph iteration → items; plan reconstructable from the log.
- **Integration** — run a small workflow async, attach SSE mid-run, assert monotonic `seq` + ordering + terminal `run.status`; reconnect with `since` → no gaps/dupes; gate flow (`gate.pending` → resolve via existing endpoint → `gate.resolved` → resume).
- **UI (Playwright, matching existing `tests/` ui patterns)** — Runs view renders live plan + step timeline from the stream.
- **Regression** — polling path and all existing workflow tests unchanged.

## 9. File inventory

**New**
- `api/models/run_event.py` — `RunEvent` envelope + event-type constants.
- `api/services/run_event_bus.py` — bus (log + fan-out + subscribe/replay).
- `api/services/run_plan.py` — `PlanBuilder` + reconstruct-from-log.
- `WorkflowPlan` / `PlanItem` models (in `workflow_models.py` or a new `run_plan_models.py`).
- Tests mirroring the existing `tests/` layout (unit + integration + ui).

**Modified**
- `api/services/workflow_engine.py` — inject bus; `_emit()` helper; emit at run/step/gate boundaries; build baseline Plan; emit `plan.updated`.
- `api/services/engine_executors/orchestrator.py` — emit plan enrichment on worker spawn.
- `api/services/engine_executors/ralph.py` — emit plan enrichment per iteration.
- The two tool-invoker builtin hooks (`api/hooks/builtins/plugin_tool_invoker.py`, `mcp_tool_invoker.py`) — publish `tool.called`.
- `api/routers/workflows.py` — `GET /runs/{id}/stream` SSE endpoint.
- `api/main.py` — instantiate `RunEventBus` in lifespan; wire into engine + router.
- `api/models/workflow_models.py` — add `WorkflowRun.plan`; persist in checkpoint.
- `api/static/index.html` — Runs view consumes `EventSource`; renders live plan + step timeline + gate prompts.
- `CHANGELOG.md` — `[Unreleased]` entry.

## 10. Forward compatibility

This substrate is designed so the deferred work is additive, not a rewrite:
- **L2-executable** — a planner emits new `plan.updated` items with `origin: external` *and* corresponding step-injection events; the engine grows a controlled mid-run DAG-expansion path.
- **L3** — sub-runs publish to the same bus under a parent `run_id`; chaining triggers subscribe to `run.status` events.
- **`kind: opencode`** — an executor that drives `opencode serve` and translates its `/event` stream (`session.status`, `todo.updated`, `permission.asked`) into Enclave events 1:1.
- **Fleet (1.4.x)** — the in-process bus can be backed by a broker (e.g. Redis) for cross-host run observation without changing producers or the SSE contract.
