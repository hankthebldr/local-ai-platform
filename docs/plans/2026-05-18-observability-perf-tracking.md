# Observability & Performance Tracking — Design Proposal

> **Status:** draft · 2026-05-18 · author: live-demo prep · target: 1.2.x
>
> **Audience:** Henry; teammates contributing to Enclave's workflow + agent layer.
>
> **Goal:** answer "why is my workflow slow / why did this agent step fail" in
> seconds, not via `docker logs | grep` archaeology, while keeping the existing
> "no telemetry, no cloud, all data local" stance from `CLAUDE.md`.

---

## 1. What we're solving

Today the operator's debug path for a slow workflow is:

```
1. Observed: a step took 8 minutes.
2. Open `docker logs local-ai-api` and grep for the model name.
3. Cross-reference run-id with `/app/data/workflows/<run-id>/run.json`.
4. Read the JSON, find the step, check duration_seconds.
5. Guess whether the bottleneck was prefill, generation, or post-parse.
```

No tool answers "which step took the longest." No tool surfaces token-per-second
trends per model. There's no per-agent cost-of-grounding measurement (the
4k-token prefill problem we hit in the live demo would have been visible 10
runs ago if we'd been tracking).

This proposal adds three layers, **without changing the existing engine API**:

1. **Structured trace events** emitted by the engine + Ollama service.
2. **Per-run trace storage** under `data/traces/<run-id>.ndjson`.
3. **Trace explorer UI** on the Runs tab (new sub-tab).

The data never leaves the box. Operators can `tar czf traces.tgz data/traces/`
and ship a single archive for a remote teammate to inspect.

---

## 2. Architecture

```
                                                                             
   ┌──────────────────────────────────────────────────────┐                  
   │                    Trace Producer                    │                  
   │                                                      │                  
   │  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │                  
   │  │  Engine    │  │  Step      │  │  OllamaService │  │                  
   │  │  Hook Bus  │  │  Executor  │  │                │  │                  
   │  └─────┬──────┘  └─────┬──────┘  └────────┬───────┘  │                  
   │        │               │                  │          │                  
   │        └───────────────┼──────────────────┘          │                  
   │                        ▼                             │                  
   │              ┌────────────────────┐                  │                  
   │              │   trace.emit(...)  │                  │                  
   │              └─────────┬──────────┘                  │                  
   └─────────────────────────┼─────────────────────────────┘                  
                            ▼                                                
            ┌────────────────────────────────┐                               
            │   data/traces/<run-id>.ndjson  │     ← append-only             
            │   data/traces/agents.ndjson    │     ← cross-run agent stats   
            │   data/traces/ollama.ndjson    │     ← cross-run model stats   
            └─────────────────┬──────────────┘                               
                              ▼                                              
                  ┌────────────────────────┐                                 
                  │   /api/traces routes   │                                 
                  └────────────┬───────────┘                                 
                               ▼                                             
                  ┌────────────────────────┐                                 
                  │   Runs tab → Trace pane │                                
                  │   - flame chart         │                                
                  │   - per-step duration   │                                
                  │   - prefill vs gen      │                                
                  │   - tokens/sec series   │                                
                  └────────────────────────┘                                 
```

---

## 3. Trace event schema (NDJSON)

One JSON object per line. Append-only. Never rewritten.

```jsonc
{
  "ts": "2026-05-18T19:23:11.482Z",
  "run_id": "f404bf20-...",
  "workflow_id": "xsiam-detection-engineering",
  "kind": "step.start" | "step.end" | "ollama.request" | "ollama.response"
        | "hook.before" | "hook.after" | "parser.parse" | "gate.check"
        | "context.read" | "context.write",
  "step_id": "enrich_context",
  "agent_id": "xql-data-model-engineer",   // when the step is agent-backed
  "model": "qwen2.5-coder:1.5b",
  "duration_ms": 410620,                    // step.end / ollama.response only
  "tokens": {                               // ollama.response only
    "prompt": 4096,
    "completion": 87,
    "tokens_per_sec_gen": 7.2,              // derived: completion / gen_time_ms * 1000
    "first_token_ms": 380000                // time-to-first-token (prefill cost)
  },
  "error": null | { "type": "...", "msg": "..." },
  "attrs": { /* free-form, kind-specific */ }
}
```

**Why NDJSON, not SQLite/Parquet:** append-only is the simplest crash-safe
format. `tail -f data/traces/<run-id>.ndjson | jq` works without any tooling.
Cross-run aggregations are O(n) line scans — fine for the operator's local
trace volume (~10MB/month under heavy use).

---

## 4. Producer integration (where the calls land)

Three injection points, each one-line in the existing code:

| Site | File | Hook |
|---|---|---|
| Step lifecycle | `api/services/step_executor.py` | `trace.emit("step.start", ...)` at start of `_execute_step`, `step.end` at return |
| Ollama call | `api/services/ollama_service.py` | `trace.emit("ollama.request", ...)` before `requests.post`, `ollama.response` after, with `first_token_ms` from a streaming-mode probe |
| Hook bus | `api/services/hook_bus.py` | `trace.emit("hook.before"/"after", ...)` wraps every fired hook |
| Output parser | `api/services/output_parsers.py` | `trace.emit("parser.parse", ...)` around format decoding |
| Quality gate | `api/services/quality_gates.py` | `trace.emit("gate.check", ...)` per gate |
| Context r/w | `WorkflowContext.set_workspace / get_workspace` | `context.read/write` only when tracing is on |

The `trace` module is a singleton lazily initialized via `get_tracer()` so
existing services don't grow constructor arguments. Each call adds **~50µs**
(append a dict to a queue, background writer flushes every 100ms).

---

## 5. Trace storage

```
data/traces/
  ├── runs/
  │   └── <run-id>.ndjson         # the full trace for one run
  ├── aggregates/
  │   ├── by_agent.ndjson         # one entry per (agent, day) tuple
  │   ├── by_model.ndjson         # one entry per (model, day) tuple
  │   └── by_workflow.ndjson      # one entry per (workflow_id, day) tuple
  └── current/
      └── live.ndjson             # streaming buffer for the UI tail
```

A `traces-rollup` daemon runs every 5 min and folds the previous interval's
per-run events into the aggregates. Aggregates are bounded — 90 day rolling
window (configurable via env var).

**Retention defaults:**
- Per-run traces: 30 days, then gzipped to `traces/runs/archive/`
- Aggregates: 1 year
- Override via `TRACE_RETENTION_DAYS` env var

---

## 6. API surface

```
GET  /api/traces/runs/<run-id>            — full NDJSON for one run
GET  /api/traces/runs/<run-id>/summary    — flame-chart-ready JSON
GET  /api/traces/agents/<agent-id>        — last N days of perf for one agent
GET  /api/traces/models/<model>           — same, for a model
GET  /api/traces/workflows/<id>           — same, for a workflow
GET  /api/traces/live                     — SSE stream of trace events
                                             from the live buffer
POST /api/traces/export                   — bundle a tar.gz for support
DELETE /api/traces/runs/<run-id>          — clear one run's trace
DELETE /api/traces                        — clear all traces
```

All routes go through the existing auth middleware. The SSE `/live` endpoint
needs `Accept: text/event-stream`.

---

## 7. UI — Runs tab gets a "Trace" sub-pane

Right side of the runs detail pane, alongside the existing "DAG", "Step
Results", and "Context Trace" panes:

```
┌─Trace──────────────────────────────────────────────────┐
│  ╞═══╡ classify_event       410.6 s  prompt:401 →55t   │
│  ╞═╡ extract_iocs            87.9 s  prompt:118 →12t   │
│  ╞═══════════════════════════════════════╡             │
│       enrich_context        603.0 s (timeout)          │
│       ▼                                                │
│       ▼  prefill: 300.0 s                              │
│       ▼  gen:       0 t                                │
│       ▼  retry 1: 300.0 s                              │
│       ▼  ❌ Read timed out                              │
│                                                        │
│  metrics ─                                             │
│  total wall: 1101.5 s                                  │
│  fastest step: extract_iocs (87.9 s)                   │
│  slowest step: enrich_context (FAILED)                 │
│  tokens/sec range: 4.1 - 7.8                           │
│  prefill cost: 67% of total time                       │
└────────────────────────────────────────────────────────┘
```

The flame chart is a simple `<svg>` with one row per step, length proportional
to `duration_ms`. Failed steps render with the `.is-failed` softened-red.
Click any bar to drill into that step's events.

---

## 8. Implementation phases

**Phase 1 (≈1 day):** producer side
- `api/services/tracing.py` — `Tracer` class, append-only NDJSON writer
- Inject into step_executor, ollama_service, hook_bus
- One env var: `ENCLAVE_TRACE_ENABLED=1` to gate the whole thing

**Phase 2 (≈1 day):** API + storage
- Implement the 7 routes above
- Rollup daemon (asyncio task launched at app boot)

**Phase 3 (≈2 days):** UI
- Trace sub-pane in Runs tab
- SVG flame chart renderer (no D3 needed — direct DOM is fine for ≤50 steps)
- Live tail via EventSource

**Phase 4 (≈1 day):** cross-run analytics
- `/api/traces/agents/...` summary endpoints
- Inventory tab → per-model perf chart

**Total:** ~5 dev days. Phase 1 alone is shippable and immediately useful.

---

## 9. Privacy / safety

- All trace data is local-only. The `tracing.py` module never makes a network
  call. No serialization to cloud endpoints.
- Trace events strip prompt/completion *content* by default — only metadata
  (tokens, duration, model, status). Operators can opt-in to content capture
  via `ENCLAVE_TRACE_CAPTURE_CONTENT=1` for offline debugging; the content is
  stored in `data/traces/runs/<run-id>/content/` (separate from the metadata
  NDJSON) and gitignored.
- `/api/traces/export` redacts secrets (api keys, tokens) before bundling.

---

## 10. Open questions for Henry

- Do we want per-token streaming traces (catches stalls mid-generation) or just
  request/response endpoints? Streaming is ~10x more data but catches "model
  stuck at token 47" patterns.
- Should the Inventory tab grow a "model performance" chart as part of Phase 4,
  or is that a separate feature?
- Trace retention default: 30 days feels generous. Aggressive (7 days) keeps
  the data-volume small but loses month-over-month trends. Your call.
