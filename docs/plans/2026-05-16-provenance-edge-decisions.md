# ProvenanceEdge — Decisions

**Date:** 2026-05-16
**Resolves the open questions at the end of:** `2026-05-16-provenance-edge-spec.md`

This doc closes the five open questions and four decisions from the spec so M1
can start. Each section: decision, reasoning, implementation note, anything new
the decision surfaces.

---

## Q1. Streamed responses

**Decision: assign `response_id` at request entry, before any service runs.**

The OpenAI Chat Completions wire format already includes a stable `id` field on
every `chat.completion.chunk` event — clients expect a single id across the
stream. We need that same id internally so RAG search, skill injection, and tool
calls all emit edges keyed on it before the first token streams.

**Implementation:**

1. In `api/routers/chat.py` and `completions.py`, mint the `response_id` at the
   top of the handler (`chatcmpl-` + hex8), before any engine call.
2. Pass it explicitly into:
   - `ToolExecutor.execute(..., response_id=...)`
   - `RAGService.search(..., response_id=...)`
   - `PluginService.get_skills(..., response_id=...)`
   - `WorkflowEngine.run(..., response_id=...)`
3. Each call site emits with the supplied id; if it's `None` (legacy callers),
   skip emission silently.

Risk: a small contract change to ~6 service methods. All additive (default
`response_id=None`), so existing internal callers don't break. The OpenAI
compatibility surface is unaffected — clients already see one id.

**Surfaced:** verify the dashboard chat actually goes through `/v1/chat/completions`
and not a parallel path. If it has its own path, it needs the same plumbing.

---

## Q2. Per-step vs. per-tool-call edges in workflows

**Decision: flat — every edge points at the final user-visible `response_id`. Add
an optional `metadata.parent_step_id` for future recursive views.**

The citation rail (M1.1 UI) renders flat. The recursive view ("what shaped step
3 of workflow X?") is M2 and benefits from the `parent_step_id` hint but doesn't
need a new edge type.

**What gets emitted in a workflow run:**

```
final response_id = wf_<run_id>

  ├── ProvenanceEdge(source_type=agent_step, source_id="wf::step1", response_id=wf_x)
  │     └── metadata.parent_step_id=None (step1 is a root)
  ├── ProvenanceEdge(source_type=plugin_tool, source_id="code::read", response_id=wf_x)
  │     └── metadata.parent_step_id="step1"
  ├── ProvenanceEdge(source_type=agent_step, source_id="wf::step2", response_id=wf_x)
  │     └── metadata.parent_step_id="step1"  (step2 depends_on step1)
  └── ...
```

**Why flat wins for v1:**
- Citation rail is one SQL: `WHERE response_id = ?`
- Per-tool analytics is one SQL: `GROUP BY source_id`
- Step-tree reconstruction is M2; the data is there when we need it

**Surfaced:** workflows that run as sub-workflows of another workflow will have
nested run IDs. We treat the outermost `response_id` as canonical for now; if
sub-workflow citation views become a need, we extend.

---

## Q3. Dashboard chat vs. OpenAI-compat namespace

**Decision: unify on the OpenAI-compat `chatcmpl-...` format. Refactor any
parallel path to mint ids the same way.**

Same id namespace means:
- External SDK clients can call `/api/provenance/response/{id}` with the id they
  already have from their SSE stream
- The dashboard chat code doesn't need a special id format
- The citation rail works identically regardless of client

**Implementation:** audit `api/static/index.html` chat panel to confirm it calls
`/v1/chat/completions`. If it calls a private endpoint, route it through the
public one (or copy the id-minting code over).

**Surfaced:** this is a small dashboard refactor task — call it out separately
on the M1.0 punch list.

---

## Q4. Setup-wizard copy

**Decision: lead with the user benefit, not the technical term.**

```
[x] Show me what shaped each answer (local-only).  Recommended.
    ⓘ Records which skills, documents, and tools contributed to each
      response, so the dashboard can show citations. All data stays on
      this machine. Clear it any time in Settings → Privacy.
```

Three lines of copy, one tooltip. The word "provenance" appears nowhere in
user-facing text — it's an internal name. The user sees "what shaped each
answer."

**Surfaced:** the same copy pattern applies to the Settings → Privacy panel.
Title: "What shaped each answer (provenance ledger)" with "(provenance ledger)"
as a parenthetical for users who searched for the term. Body uses the
user-centric framing.

---

## Q5. Schema migration tooling

**Decision: ship a 50-LOC migrations runner in M1.0.** Numbered SQL files in
`api/services/migrations/provenance/`. SQLite's `PRAGMA user_version` tracks
applied version. Idempotent. Runs at first `ContextStore.__init__`.

**Shape:**

```
api/services/migrations/provenance/
  ├── 0001_initial.sql         # creates provenance_edges + indexes
  ├── 0002_add_metadata.sql    # future: extra column
  └── runner.py                # ~50 LOC: read user_version, apply in order
```

```python
# runner.py sketch
def migrate(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    files = sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    for f in files:
        version = int(f.stem.split("_")[0])
        if version <= current:
            continue
        conn.executescript(f.read_text())
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
```

Why bother in M1.0: the cost of adding it now is 50 LOC; the cost of adding it
after we've shipped to users and need a schema change is a custom one-off
migration script per release. Pay the small cost up front.

**Surfaced:** the same runner pattern can be reused for any future SQLite-backed
service (Enclave Code's session store, audit logs in the Teams direction). Keep
the helper generic enough that the path-to-migrations is a parameter, not a
constant.

---

## D1. SQLite vs. JSONL

**Decision: SQLite.**

Side-by-side on what actually matters:

| Criterion | SQLite | JSONL |
|-----------|--------|-------|
| 4 read patterns from the spec | Indexed, ms-scale | Full scan or sidecar index |
| Concurrent reads while writing | WAL mode, lock-free | File locks or copy |
| Append performance | ~5K/s with batching | ~10K/s but no query |
| Single-file storage | Yes | Yes |
| Inspect with shell tools | `sqlite3 db .dump` | `tail`/`jq` (slight edge) |
| Retention purge | `DELETE WHERE timestamp < ?` | Rewrite the file |

JSONL's only real advantage is `tail | jq` convenience. SQLite ships with Python
and gives us queries for free. **SQLite.**

**Surfaced:** add an `enclave provenance export` CLI subcommand that dumps to
JSONL for users who want shell-tool inspection. Cheap to build, satisfies the
JSONL convenience use case without giving up SQLite's query power.

---

## D2. Default retention

**Decision: 90 days.**

Disk math: ~200 bytes/edge × 50 edges/response × 100 responses/day = ~1 MB/day.
At 90 days, ~90 MB worst-case. Acceptable for any user who can afford to run a
local LLM.

Why not 30: the Doc Audit feature from the lifecycle review needs ≥90 days of
data to surface "never cited in 90 days." If we default to 30, that feature
ships broken.

Why not forever: a year of heavy use is ~365 MB and gives diminishing returns
beyond ~90 days (an unused doc at 91 days is just as unused at 200 days).

**Config:**
- `PROVENANCE_RETENTION_DAYS=90` default
- `=0` for forever
- `=-1` for disable purge
- User can override in Settings → Privacy → "Keep history for: [30 / 90 / 180 / forever]"

**Surfaced:** the purge job runs on first edge insert of each day. Cheap (an
indexed `DELETE WHERE timestamp < ?`), fires at most once per day.

---

## D3. Citation rail UX

**Decision: as sketched in the spec, with these refinements:**

```
shaped by: 2 skills · 3 chunks · 1 web page · 1 tool call    [details ▾]
```

- **Icon per source type.** A tight glyph (◆ skill, ▣ chunk, ⌖ web, ✦ tool,
  ⌂ memory, ◎ agent step). Cheaper to scan than reading source-type words.
- **Sort order in the expand panel:** by contribution score descending; ties
  broken by source_type alphabetical. Most-relevant first.
- **Empty state:** "No sources tracked for this response." Shouldn't happen
  after M1.0, but a defensive label is one line of code.
- **Truncation:** at >10 edges per type, show top 5 + "5 more" link. The link
  expands inline; doesn't open a new view.
- **Latency:** rendered when the response finishes streaming, not on every
  chunk. One fetch per response.

**Surfaced:** A11y — the expand control needs `aria-expanded` and the rows need
roles. Cheap to do up front, painful to retrofit.

---

## D4. Feature flag

**Decision:**

| Phase | Flag state |
|-------|-----------|
| M1.0 — emission, no UI | No flag. Data collection is invisible to the user. |
| M1.1 — citation rail UI | Behind `ENABLE_PROVENANCE_UI=true`. Default off. Internal dogfood ~2 weeks. |
| Post-dogfood | Default on. Setup-wizard checkbox controls collection (`ENABLE_PROVENANCE`); UI flag goes away. |

Two flags, two stages, clear sunset path. The collection flag (`ENABLE_PROVENANCE`)
is permanent — it's the privacy opt-out. The UI flag (`ENABLE_PROVENANCE_UI`) is
temporary, just for staged rollout.

**Surfaced:** the Settings → Privacy panel needs to differentiate "I collect
this data" (the permanent setting) from "I show it in the UI" (M1.1 only). Once
M1.1 is GA, the panel collapses to one toggle.

---

## Updated M1 plan

The decisions don't move the day count. They sharpen the scope:

| Phase | Days | Now includes |
|-------|------|------|
| **M1.0** | 3 | Data model, SQLite + migrations runner, ContextStore additions, `response_id` plumbing through 6 service methods, emission sites #1–#2, `/response/{id}` endpoint |
| **M1.1** | 2 | Emission site #3 (RAG), citation rail UI (with icons, contribution-sort, 10+ truncation, a11y), dashboard chat path audit + unification |
| **M1.2** | 2 | Emission sites #4–#8, resolver registry, Settings → Privacy panel (with user-centric copy from Q4), purge job |

**Total still ~7 engineer-days.**

---

## New questions that surfaced from these decisions

Honest list — these are not blockers but they're worth tracking:

1. **Dashboard chat path audit (from Q3).** Whoever picks up M1.1 needs to
   confirm the dashboard's chat panel uses `/v1/chat/completions`. If a parallel
   path exists, it's a 1–2 hour fix during M1.1, but it's a fix that should be
   surfaced early so it doesn't sneak up at the end.

2. **Workflow sub-runs (from Q2).** If a workflow `A` triggers workflow `B` as
   a sub-step (via the engine's compose feature, if it has one — needs
   confirmation in `workflow_engine.py`), `B`'s edges currently point at `B`'s
   response_id, not `A`'s. The citation rail on `A` won't show `B`'s edges.
   Fix: when running as a sub-workflow, accept a `parent_response_id` and emit
   against the outer id. M2 problem; not urgent for M1.

3. **Resolver registry shape (from M1.2).** Each `source_type` needs a resolver
   function that turns a `source_id` into `{label, link, preview}`. Should this
   live as a dict in `provenance_router.py` or as a method on each service? My
   bias: dict in the router, because the router owns the read path. Each
   service stays unaware of provenance. Worth flagging during M1.2 review.

4. **`enclave provenance export` CLI subcommand (from D1).** Mentioned as a
   surfaced item — adds JSONL export for shell-tool inspection. Should we ship
   this in M1 or defer? **Defer to M2.** Nice-to-have; not blocking.

5. **A11y testing for the citation rail (from D3).** Mentioned ARIA roles.
   Should we add automated a11y assertions to the M1.1 frontend tests, or trust
   the manual pass? **Add a single `aria-expanded` assertion** to the existing
   dashboard test suite; full a11y testing is out of scope for this feature.

## Ready to ship

With these decisions, M1 has:
- No remaining design ambiguity
- A clear daily breakdown (3 / 2 / 2)
- A clear flag strategy
- A clear privacy story for setup wizard, settings panel, and copy
- A migrations path for future schema changes
- Five known follow-on items, all M2 or later

**Recommend:** queue M1.0 for the next sprint, with the M1.1 + M1.2 phases
following back-to-back so the citation rail ships within the same ~2-week window
as the foundation.
