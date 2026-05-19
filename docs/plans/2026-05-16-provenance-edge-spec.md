# ProvenanceEdge — Spec

**Status:** Draft
**Date:** 2026-05-16
**Builds on:** `2026-05-16-content-lifecycle-review.md` (P0 foundation piece)
**Owners:** TBD

## TL;DR

A single typed data structure records every contribution to every model response.
Skills that fired, RAG chunks that were retrieved, MCP tools that were called,
agents that ran in a workflow — each emits one `ProvenanceEdge`. Citations,
"which skills fired" inspectors, MCP usage analytics, doc audits, workflow
replay, and the curation cadence all read from the same table. This is one piece
of infrastructure that unlocks ~8 features.

## Goals

1. **One write path, many read paths.** Every "content shaped this response"
   moment in the engine emits the same edge shape. The UI is the only place
   that diverges per content type.
2. **Cheap to write.** ≤1 ms per edge on the hot path. Engine pipelines that
   emit 10–50 edges per response must not see measurable slowdown.
3. **Persistent enough to power citations.** Survives a dashboard refresh.
   Survives a session export. Does not survive a `--reset`.
4. **Privacy preserves the brand.** All data local. No telemetry. User-clearable.
   Retention defaults are short.

## Non-goals (v1)

- Distributed tracing (OpenTelemetry, Jaeger). Local-only.
- Multi-user audit (per-user attribution). Single-user box.
- Replay-to-debug (faithful re-execution from edges). Edges are evidence,
  not transactions.
- Compression or columnar storage. SQLite is plenty for v1.

## Data model

```python
# api/models/context_models.py — add alongside ToolCallRecord

from typing import Literal, Optional

SourceType = Literal[
    "skill",        # plugins/<id>/skills/<name>.md
    "rag_chunk",    # a Chroma chunk
    "mcp_tool",     # plugin_id::tool_id called via MCP
    "plugin_tool",  # local plugin tool (not MCP)
    "agent_step",   # a workflow step
    "doc",          # a whole document (when chunk-level not available)
    "memory_fact",  # a pinned fact from MemoryService
    "web_page",     # a URL fetched during research
    "auto_context", # a section of the auto-injected session context
]

@dataclass
class ProvenanceEdge:
    edge_id: str                        # `pe_<hex8>`
    response_id: str                    # message_id or step run_id consuming this
    conversation_id: str                # for query-by-conversation
    source_type: SourceType
    source_id: str                      # opaque, type-namespaced
    contribution: Optional[float] = None  # 0..1 where available (RAG score, etc.)
    excerpt: Optional[str] = None       # the span that mattered; ≤500 chars
    metadata: dict = field(default_factory=dict)  # source-specific extras
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict: ...
```

**Naming convention for `source_id`:**

| source_type | source_id format | example |
|-------------|------------------|---------|
| `skill` | `<plugin_id>::<skill_id>` | `code::read-before-edit` |
| `rag_chunk` | `<collection>::<chunk_id>` | `enclave-docs::chunk_a1b2c3` |
| `mcp_tool` | `<server_id>::<tool_name>` | `github::search_issues` |
| `plugin_tool` | `<plugin_id>::<tool_id>` | `rag::search` |
| `agent_step` | `<workflow_id>::<step_id>` | `xsiam-data-model-rules::analyze_source` |
| `doc` | `<doc_id>` | `doc_a1b2c3d4` |
| `memory_fact` | `<fact_id>` | `fact_a1b2c3` |
| `web_page` | sha256(url)[:12] | `9f2a1b3c4d5e` |
| `auto_context` | `<section>` | `repo_identity` |

The `source_id` is **opaque**. The UI joins it back to the source via per-type
resolvers (e.g. given `rag_chunk` → call `document_service.get_chunk(id)`).

**Why typed sources, not a single FK?**

A FK to one master content table would force every type into the same schema
and require migrations every time we add a content kind. The typed `source_id`
costs nothing at the storage layer and keeps schemas independent.

## Storage

### v1: SQLite, extending ContextStore

The existing `ContextStore` is in-memory and per-conversation. Two changes:

1. **Add SQLite backing** for provenance edges only (not the whole context —
   keep messages in memory; just persist edges).
2. **Add a `record_edge(...)` method** alongside the existing `record_tool_call`,
   `record_skill`.

```python
# api/services/context_store.py — additions

class ContextStore:
    def __init__(self, db_path: Optional[Path] = None):
        self._contexts: dict = {}
        self._db = ProvenanceDB(db_path or Path("data/provenance.sqlite"))

    def record_edge(self, edge: ProvenanceEdge) -> None:
        """Persist an edge. Hot path — must be cheap."""
        self._db.insert(edge)
        ctx = self._contexts.get(edge.conversation_id)
        if ctx:
            ctx.edges_emitted += 1
```

### SQLite schema

```sql
CREATE TABLE provenance_edges (
    edge_id          TEXT PRIMARY KEY,
    response_id      TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    contribution     REAL,
    excerpt          TEXT,
    metadata_json    TEXT,
    timestamp        TEXT NOT NULL
);

CREATE INDEX idx_by_response       ON provenance_edges(response_id);
CREATE INDEX idx_by_conversation   ON provenance_edges(conversation_id, timestamp);
CREATE INDEX idx_by_source         ON provenance_edges(source_type, source_id);
CREATE INDEX idx_by_type_time      ON provenance_edges(source_type, timestamp);
```

Four indexes cover the four read patterns from the next section. SQLite's WAL
mode + batched inserts gives us 5K+ writes/sec, well above what we'll emit.

### Persistence path

`data/provenance.sqlite` (next to the existing `data/projects/`, `data/memory/`
etc.). Created lazily on first edge. WAL mode for concurrent reads.

### Retention

- **Default:** 30 days of edges, then purged on first write of each day.
- **Configurable:** `PROVENANCE_RETENTION_DAYS` env var. `0` = forever.
- **Manual clear:** `POST /api/provenance/clear` (master-key auth), or dashboard
  Settings → Privacy → "Clear provenance ledger."

## Emission sites

Exact files and methods that need to emit edges. **Eight write sites; each is
a one-line addition** because the call signature is uniform.

| # | Site | When | source_type | Notes |
|---|------|------|-------------|-------|
| 1 | `tool_executor.py:execute` (existing tool_calls loop) | Per tool call already recorded | `plugin_tool` (or `mcp_tool` if the plugin is MCP-backed) | Extend the existing `record_tool_call` to also emit a ProvenanceEdge |
| 2 | `plugin_service.py:get_skills` → caller injects into prompt | When a skill is added to the system prompt | `skill` | Today it just appends a string to `ctx.skills_injected`; add the edge with `excerpt = first 200 chars of skill body` |
| 3 | `rag_service.py:search` | For each result returned to the caller | `rag_chunk` | `contribution = similarity score`, `excerpt = chunk preview` |
| 4 | `mcp_service.py:call_tool` | Per MCP tool invocation | `mcp_tool` | `metadata = { transport, latency_ms }` |
| 5 | `step_executor.py:execute_step` | At step completion | `agent_step` | `contribution = quality_gate_score where available` |
| 6 | `memory_service.py:get_pinned_facts` (callers) | When a fact is injected into prompt | `memory_fact` | |
| 7 | Web fetches in `graph.py:deep-dive` | Per URL fetched | `web_page` | `metadata = { url, title }` |
| 8 | `code_session.py:build_initial_context` (Enclave Code) | Per section assembled | `auto_context` | `source_id = section name` |

**Hot-path budget:** each emission is ~0.3 ms (one INSERT to a WAL'd SQLite,
prepared statement, batched flush every 100 ms). For a workflow run with 50
edges, that's <20 ms total — within budget.

## Query API

A small read-only router `api/routers/provenance.py`. All endpoints local-auth.

| Endpoint | Returns | Used by |
|----------|---------|---------|
| `GET /api/provenance/response/{response_id}` | All edges that shaped a single response, grouped by source_type | Citation rail on a chat message |
| `GET /api/provenance/conversation/{conversation_id}` | All edges in a conversation, paginated | Conversation timeline view |
| `GET /api/provenance/source?type=X&id=Y` | All responses that cited this source | "What has used this doc?" / chunk audit |
| `GET /api/provenance/usage?type=X&window=7d` | Histogram: source_id → call_count, last_used | Skill firing rates, MCP usage, doc citation frequency |
| `GET /api/provenance/audit/docs` | Per-doc: citation_count, last_cited, embed_age | Doc Audit panel from the lifecycle doc |
| `DELETE /api/provenance` | Clear all (admin) | Privacy panel |

Each endpoint resolves `source_id` → human-readable label via a per-type
resolver registry (a small dict mapping `source_type` to a function in the
relevant service).

## UX surfaces (M1 — ship one)

### Citation rail on chat responses

Below every assistant message, a single line:

```
shaped by: 2 skills · 3 chunks · 1 web page · 1 tool call    [details ▾]
```

Click "details" → expand into:

```
┌─ Skills (2) ──────────────────────────────────────┐
│  code::read-before-edit        always-on           │
│  code::diff-driven-edits       always-on           │
├─ Retrieved chunks (3) ────────────────────────────┤
│  87% │ api/services/workflow_engine.py:42-78      │
│  74% │ docs/plans/2026-04-06-multi-agent-…md      │
│  61% │ workflows/xsiam-data-model-rules.yaml       │
├─ Web (1) ──────────────────────────────────────────┤
│       │ github.com/ollama/ollama/blob/main/docs…  │
├─ Tools (1) ────────────────────────────────────────┤
│  340ms │ rag::search("workflow engine DAG")        │
└────────────────────────────────────────────────────┘
```

Each row is clickable: chunk → opens doc at line; web → opens URL; tool →
shows full args + result. Skill name → opens skill markdown viewer.

**Why this UI first:** Citations are the single biggest credibility move for
local LLMs. Frontier-model chatbots get a pass on hallucination because users
expect quality; local models don't, and showing the work flips the frame from
"trust me" to "see for yourself." It also doubles as a debug surface during
development.

### Deferred to M2

- Skill firing-rate dashboard
- MCP usage analytics
- Doc Audit panel ("docs never cited")
- Workflow run replay with edges

All read from the same data; UI work, not engine work.

## Privacy

Hard rules baked into the design:

1. **No telemetry.** ProvenanceEdge never leaves the box. The router has no
   "share" endpoint. Bundle export (`/api/workflow-index/export`) explicitly
   excludes the provenance table.
2. **Excerpts truncated at 500 chars.** Long excerpts would risk leaking secrets
   from RAG chunks; 500 chars is enough for "what was this about?" without
   becoming a copy of the corpus.
3. **Opt-out at install.** Setup wizard checkbox: "Record provenance for
   citations (recommended, local-only)." Default on. Stored as
   `ENABLE_PROVENANCE=true`; if false, `record_edge` becomes a no-op.
4. **One-click clear** in Settings → Privacy.
5. **Retention TTL** as described above.
6. **No PII inference.** Edges store opaque IDs and short excerpts. We never
   try to extract "user names" or "topics" from the data.

## Performance

Budget: emission must add <1 ms per edge, <5% to total response latency for
typical chat (5–10 edges) and <10% for a heavy workflow run (50 edges).

### Strategies

- **WAL mode + prepared INSERT statement.** ~0.2 ms per row.
- **Batch flush every 100 ms** via a single background thread. The engine
  enqueues; the writer drains. Lost on crash → acceptable (this is evidence
  data, not transactions).
- **Bounded queue (1000 edges).** Backpressure: if the writer falls behind,
  the queue drops oldest edges silently and increments a counter. Surface the
  counter on the Privacy panel ("3 edges dropped in the last hour").
- **No fsync per write.** The 100 ms flush is a `COMMIT`, not a `sync`. Fine
  for evidence data.

### Performance tests in M1

- 1K edges in <2 s (steady state).
- Burst: 100 edges in <100 ms with zero drops.
- Read: "edges by response_id" for a 50-edge response in <10 ms.

## Migration / rollout

Edge emission is **additive** — no existing code path needs to change behavior,
only to gain an emission call. Three rollout phases:

### M1.0 — Foundation (3 days)

- Data model + SQLite schema + ContextStore additions.
- Router `provenance.py` with `/response/{id}` only.
- Emission sites #1 (tool_executor) and #2 (skills). These are the two highest-
  signal edges and exercise the write path.

### M1.1 — Citation rail (2 days)

- Emission site #3 (RAG chunks).
- Frontend: the rail UI above. Hook into the existing chat response renderer.
- Ship behind a feature flag `ENABLE_PROVENANCE_UI` so we can A/B.

### M1.2 — Full coverage (2 days)

- Emission sites #4–#8.
- Resolver registry for converting `source_id` → label.
- Privacy panel (clear button, retention setting).

**Total: ~7 engineer-days for the foundation + citation rail.** Subsequent UX
(audit panel, usage analytics) is pure UI work on top.

## Failure modes

| Mode | Detection | Response |
|------|-----------|----------|
| SQLite locked / busy | Insert returns `SQLITE_BUSY` | Retry once with 50 ms backoff; on second failure drop the edge and increment the dropped counter |
| Queue backpressure | Queue size > 1000 | Drop oldest, increment counter, log warning |
| Schema migration on upgrade | Version mismatch detected at startup | Run `ALTER TABLE` from a tiny migration script; on irrecoverable schema drift, rename old DB to `.bak` and start fresh |
| Disk full | Insert returns `SQLITE_FULL` | Disable emission, log a single warning, surface a banner on the dashboard |
| Source ID unresolvable (renamed/deleted) | Resolver returns None | UI shows the raw ID; the edge is still useful for "this was cited even though it's gone now" |

## Open questions

1. **Should we record edges for streamed responses?** Today a streamed response
   has no single message_id at start time. Options: assign the ID up front
   (cheap, mild contract change) or buffer edges in memory and flush on stream
   end (more complex). Recommend: assign up front.
2. **Per-step edges vs. per-tool-call edges in workflows.** A single step makes
   N tool calls. Do we emit one `agent_step` edge + N `plugin_tool` edges, or
   collapse? Recommend: emit both (cheap, two views of the same activity).
3. **Should the dashboard chat use a different `response_id` namespace than the
   OpenAI-compat API?** They flow through different paths today. Recommend:
   unify on the API's response IDs so external clients can fetch provenance for
   their own responses too.
4. **Telemetry vs. privacy in the UI copy.** The setup-wizard checkbox copy
   matters. "Record provenance for citations (recommended, local-only)" vs.
   "Enable provenance tracking." Lean toward the first — it explains the *why*.
5. **Schema migration story.** If we add a `source_type` value, old edges still
   parse — they store the enum as a string. But if we add a *column*, we need
   migration tooling. Should we ship a tiny migrations runner in M1.0? Recommend:
   yes, ~50 LOC; future-proofs the design.

## Decisions needed before kickoff

- [ ] SQLite path vs. JSONL append-only. SQLite wins on query patterns; JSONL
  is dead-simple. **Recommend SQLite.**
- [ ] Default retention: 30 days vs. 90 days vs. forever. **Recommend 30.**
- [ ] Citation rail copy and exact UI. Tied to the dashboard refresh budget.
- [ ] Whether to ship behind a feature flag. **Recommend yes for M1.1, off for
  M1.0 (data collection but no UI exposure yet).**
