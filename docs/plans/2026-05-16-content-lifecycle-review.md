# Content Lifecycle Review — Skills, Context, Research, Projects, MCPs

**Date:** 2026-05-16
**Builds on:** `2026-05-16-ux-stories.md` (moments) — this doc covers the management
lifecycle *behind* each moment.

## Mental model

Every kind of "content" on the platform has the same five-stage lifecycle:

```
   1            2            3            4            5
Author/      Curate       Activate      Use         Retire/
Acquire      (review,     (scope,      (invoke,    Audit
             link, tag)   enable)       cite)       (archive,
                                                    review)
```

Today the platform implements stage 1 well for most content (everything has CRUD)
and stage 4 partially (things get used). Stages 2/3/5 are mostly missing across the
board. **The opportunity is to ship the same lifecycle affordances across every
content type, once.**

The platform already has two `Inventory`-style surfaces:

| Content | Surface | Status |
|---------|---------|--------|
| Models  | `/api/inventory` + Inventory tab | shipped |
| Workflows | `/api/workflow-index` + Workflow Index tab | shipped (with bundle import/export) |
| Skills | — | none |
| MCPs | `/api/mcp` (CRUD only) | partial |
| Documents/RAG | `/api/documents` + Documents tab | partial (no curation/audit) |
| Knowledge graph | `/api/graph` + memory tab | partial |
| Projects | `/api/projects` (CRUD only) | API-only, no UI |

The five content types the user named — skills, context, research, projects, MCPs —
plus the existing model + workflow inventories should converge on **one repeated
lifecycle pattern**.

---

## 1. Skills

Today: markdown in `plugins/<id>/skills/*.md`, declared in `plugin.yaml`, matched
by keyword trigger via `plugin_service.get_skills()`. The Enclave Code work adds 9
skills with `triggers: ["*"]`.

### Lifecycle table

| Stage | Today | Gap | User story |
|-------|-------|-----|-----------|
| Author | edit markdown on disk | no in-app authoring; no preview of resulting system prompt | "I write a skill in the dashboard and see the rendered system prompt update live as I edit." |
| Curate | none | no skill lint, no conflict detection between skills | "When I add a new skill, Enclave warns me if it contradicts an existing one." |
| Activate | static per-plugin | no per-project / per-profile scoping | "I enable the 'code-review-strict' skill only in my work projects, not personal ones." |
| Use | injected silently | no observability — user doesn't know which skills fired | "Below the agent response: 'shaped by 3 skills (click to inspect)'." |
| Retire | delete file | no version history, no soft delete, no rollback | "Roll back the skill I edited yesterday." |

### Where to add UX

- **Skill Library tab** mirroring Inventory/Workflow Index. Browse, edit,
  diff-view changes, enable/disable per project.
- **Skill inspector** in the chat transcript: hovering a response highlights which
  skill text shaped it. Re-uses the citations pattern from §6.
- **Lint pass** on save: run a small "are these instructions consistent?" check
  against all active skills before persisting. Catches the contradictions the
  M1 skills risk doc already calls out.

---

## 2. Context (documents, RAG, knowledge graph, memory)

Today: `DocumentService` handles parse → chunk → embed → store; Chroma stores
vectors; `RAGService` retrieves; `MemoryService` persists session summaries +
pinned facts; `graph_service` extracts entities. Stage 1 is solid; stages 2 and 5
are mostly absent.

### Lifecycle table

| Stage | Today | Gap | User story |
|-------|-------|-----|-----------|
| Acquire | manual upload, file-by-file | no folder-watch, no source connectors (Obsidian, Notion, repo, mail) | "Point Enclave at my Obsidian vault. It indexes incrementally and stays in sync." |
| Curate | none | no PII scan on ingestion; no chunk-level mute; no manual graph editing | "Mark this chunk as noise — never retrieve it." + "Edit the wrong relation the extractor inferred." |
| Activate | global to all conversations | no per-project corpus scoping; no per-conversation filter | "This conversation should only see my work docs, not personal notes." |
| Use | retrieved → injected → no breadcrumb | no inline citations in answers; no jump-to-source | "Every answer cites the chunks used. Clicking opens the file at the line." |
| Retire | delete document | no staleness signal; no re-embed orchestration on model change; no audit | "Show me docs not cited in 90 days. Bulk-archive." + "Embedding model upgrade triggers a guided re-index." |

### Where to add UX

- **Citation rail** on every chat response: the chunks used, the docs they came
  from, the confidence score. This is the single most-impactful addition because
  it converts RAG from "trust me" to "see for yourself."
- **Watched folders** in the Documents tab. A folder picker that becomes a live
  source. Polled via filesystem watchers (already cross-platform via `watchdog`).
- **Knowledge graph editor** in the Memory tab: a small UI to confirm/correct
  extracted relations. Even read-only "look at the graph" is a big win today;
  edit is M2.
- **Re-embed orchestrator**: when the user changes the embedding model, kick off
  a background job, show progress, fall back gracefully on Chroma's existing
  `EmbeddingBackendMismatch` exception.
- **Doc Audit panel**: a `/inventory/documents/audit` endpoint that surfaces docs
  never cited, docs with low retrieval scores, docs with stale embeddings.

---

## 3. Research

Today: `POST /api/research/deep-dive` orchestrates decompose → search → synthesize
into one server response. The dashboard has a Research tab with `.research-layout`
CSS, steps with `.active/.done` states. **The flow runs once and the artifact
evaporates** — there's no project, no save, no continuation.

### Lifecycle table

| Stage | Today | Gap | User story |
|-------|-------|-----|-----------|
| Start | single-shot question | no goal framing; can't title or scope the research | "Start a research project with a goal: 'Understand how XSIAM correlation rules work.' All my queries roll up to it." |
| Decompose | LLM picks sub-questions silently | no user steering; can't edit, prune, or add sub-questions before running | "Show me the decomposition. Let me edit or add sub-questions before searching." |
| Gather | one-shot per sub-question | no pinning of intermediate findings; can't pause/resume; no dedup across sources | "Mid-stream I can pin 'this finding is important'; I can come back tomorrow and continue." |
| Synthesize | one-shot LLM merge | no per-claim provenance; one paragraph wins or loses as a whole | "Every claim in the synthesis links to the source that supported it (chunk, web page, chat turn)." |
| Preserve | result text in browser | not saved; no export; can't feed back into RAG | "Save my research as a note. Optionally add it to my RAG corpus so future questions can use it." |

### Where to add UX

- **Research Projects** as first-class objects (separate from Projects-the-bundle).
  Title, goal, sub-questions, gathered findings, synthesis, sources.
- **Step-by-step research** instead of one server-side orchestration: the user
  watches decomposition, edits, kicks off gathering, decides when to synthesize.
  Reuses the existing workflow engine — research is just a workflow with a special
  surface.
- **Source provenance** as a first-class data model: every finding has a typed
  source (rag_chunk, web_page, chat_turn, mcp_call). Every claim in the synthesis
  points back to ≥1 source.
- **Export targets**: Markdown, Obsidian vault, "add to my RAG" (the synthesis
  becomes a curated doc that future research can build on).

This is a place where the multi-agent workflow engine genuinely outshines a single-
agent chatbot. We should lean into it.

---

## 4. Projects

Today: `ProjectService` does CRUD on YAML bundles grouping workflows + agents +
MCPs + plugins + models + documents + sessions. The API exists. There is **no
dashboard surface** — the tab list is missing a Projects tab.

### Lifecycle table

| Stage | Today | Gap | User story |
|-------|-------|-----|-----------|
| Create | POST /api/projects | no UI; no templates | "Start a 'Code Review' project from a template — workflows/agents/RAG pre-wired." |
| Configure | manual bundle edits | no recommendations; no preflight | "Project doctor: 'You bound the xsiam-analyst agent but no XSIAM-capable model is installed.'" |
| Activate | implicit (no UI) | no quick-switch; no per-project chat history | "Cmd-K to switch project. My open chats follow the project." |
| Use | bound services act through it | no cross-project search; no project-scoped audit | "I learned something about Cortex two months ago in a different project — find it." |
| Retire | delete YAML | no archive; no export-to-share | "Archive this project. Or export it as a zip a teammate can import." |

### Where to add UX

- **Projects tab** as the dashboard's organizing primitive — sit it next to the
  current logo. The current "global mode" stays available as the "Default" project.
- **Project templates**: 4–6 curated starters that bundle agents/workflows/MCPs.
  "Code Review", "Security Analyst" (the XSIAM stuff already shipped), "Personal
  Knowledge Base", "API Sandbox", "Research Workspace".
- **Project doctor** — a preflight that validates: all roles have a model
  installed, all referenced MCPs are healthy, all RAG corpora are indexed with
  the project's embedding model. Same shape as the `enclave doctor` from yesterday.
- **Per-project everything**: chat history, RAG scope, MCP enablement, skill
  enablement. Today most of these are global; per-project scoping converts
  Enclave from "an LLM tool" into "a workspace for a body of work."
- **Bundle export/import** already exists on the API. Surface it as
  "Share this project" with a single .enclave-pack file (zip).

---

## 5. MCPs

Today: `MCPService` persists registrations (stdio or HTTP), runs short-lived
JSON-RPC sessions per request, exposes tools to the workflow engine and chat
runtime. There is a `/api/mcp` router. The audit found no marketplace, no health
monitoring, no per-project scoping.

### Lifecycle table

| Stage | Today | Gap | User story |
|-------|-------|-----|-----------|
| Discover | user types config manually | no catalog; user has to know the MCP exists | "Browse a curated MCP catalog. One-click install." |
| Verify | initialize handshake on first call | no recurring health monitoring; no version pinning | "MCP panel shows live: git-mcp ✓, github-mcp ✗ (last error 5m ago)." |
| Configure | global env + headers | no per-project scoping | "GitHub MCP is enabled only in my work-repo project, not personal." |
| Use | called per workflow step | no per-tool usage telemetry; no failure attribution | "Usage table: 'github.search_issues called 47 times, 3 failures, all timeout.'" |
| Update / Retire | manual edit | no version pin, no upgrade prompt | "Notify me when context7 has a new release; show me the changelog." |

### Where to add UX

- **MCP Catalog** tab mirroring Inventory/Workflow Index. Same UX shell —
  description, version, source URL, install button, enabled/disabled toggle.
- **Health rail** on every MCP card: last successful call, last error, latency p95.
  Recurring background pings (every 5 min for stdio, 60s for HTTP).
- **Per-project enablement matrix**: Project × MCP grid in the Project settings.
- **Tool usage analytics**: tools-called-per-MCP, latency, failure rate. Same
  data model as the per-skill firing rail from §1.
- **Pin / unpin**: explicit version pinning, with an "upgrade available" badge.

---

## Cross-cutting patterns

The lifecycle review above keeps hitting the same five infrastructure pieces.
Build these once, reuse across all five content types:

### A. Citation graph

Every "use" of any content (skill firing, chunk retrieval, MCP tool call, agent
invocation, doc citation) emits a typed provenance record:

```python
class ProvenanceEdge:
    response_id: str        # the chat/workflow turn that consumed this
    source_type: Literal["skill", "chunk", "mcp_tool", "agent", "doc"]
    source_id: str
    contribution: Optional[float]  # 0..1 relevance score where available
    excerpt: Optional[str]         # the span that mattered
```

This single data model powers: citations on chat responses, "which skills fired"
inspector, MCP usage analytics, research synthesis with per-claim sources, doc
audit ("never cited"), workflow run replays. **Highest leverage infrastructure
investment in this doc.**

### B. Per-project scoping

Every content type gets a `scope: project_id | "global"` field. The current
"everything is global" model becomes "everything has a default of 'global,' opt
into project scope." Migration is additive.

### C. Versioning + soft delete

Every content type gets:
- `version_history: list[Snapshot]` (last N revisions, capped, on local disk)
- `archived_at: Optional[datetime]` (soft delete; UI hides but engine can still
  cite from old runs)

This unlocks "rollback that skill", "restore that deleted doc", and the audit
trail Enterprise users will eventually want.

### D. Catalog / Inventory pattern

Five new tabs, all the same shell:

```
[Inventory: Models] [Workflow Index] [Skills] [MCPs] [Plugins]
```

Each has: list view, detail view, install/import, enable/disable toggle,
health/usage rail, link to author docs. One React (or vanilla) shell component
parametrized over the content kind. ~1 week of engineering pays off across all
five tabs.

### E. Curation cadence

A monthly background sweep that surfaces:
- Docs not cited in 90 days → "Archive these?"
- Skills never fired → "Disable these?"
- MCPs with >50% failure rate → "Health check failed; review?"
- Projects unopened in 60 days → "Archive these?"

Surfaces as a small "Tidy up" banner in the dashboard. One opt-in click triggers
the recommended action. Privacy-friendly — all local, no telemetry leaving the
box.

---

## Unified mental model

A **Project** is the top-level container. It contains: Skills (which behavior
shapes the agent), Context (what the agent knows: RAG, graph, memory), MCPs
(what the agent can do externally), Workflows + Agents (how it composes
multi-step work), and Research artifacts (curated outputs of prior work).

Each content type has the same five-stage lifecycle. Each stage exposes the
same UX shape (CRUD + curate + scope + observe + retire). The platform's job is
to host the lifecycle consistently — and to make every "Use" event leave a
provenance trail that powers citations, audits, and curation.

```
┌── Project ──────────────────────────────────────────────┐
│                                                          │
│   [Skills]    [Context]    [Research]    [MCPs]          │
│       \           |             /            /            │
│        \──── Workflows + Agents ────────────/             │
│                       ↓                                   │
│                  ProvenanceEdge                           │
│                       ↓                                   │
│              Citations · Audit · Curation                 │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

---

## Priority

| Priority | Investment | Why |
|----------|-----------|-----|
| **P0** — foundation | (A) ProvenanceEdge data model + emission from chat/workflow/MCP/skill paths | Unblocks citations, audits, inspector, curation. ~1 week. |
| **P0** — UX | Citation rail on chat responses; "Skills that fired" inspector | First visible payoff of (A). Builds user trust in local LLMs by showing the work. ~3 days. |
| **P1** | (D) shared Inventory/Catalog shell + Skills tab + MCP tab + Projects tab | Three big UX wins from one component. ~1 week. |
| **P1** | Watched folders (Context acquire) + doc audit panel | Closes the "drop folder, stay in sync" story everyone expects. ~1 week. |
| **P1** | Project templates (Code Review, Security Analyst, Knowledge Base) + project doctor | Activation moment for new users. ~3 days. |
| **P2** | Research-as-workflow refactor with editable decomposition + provenance | Makes research a signature feature. ~2 weeks. |
| **P2** | (B) per-project scoping rollout across content types | Migration is additive; do it once foundation is settled. ~1 week. |
| **P3** | (C) versioning + soft delete for all content types | Enterprise-grade hygiene. Defer until P0–P2 are shipped. |
| **P3** | (E) monthly curation sweep | Low frequency, low urgency, high delight. |

**The single most-impactful thing in this doc is (A) — the ProvenanceEdge model.**
Everything else compounds on it. If we ship nothing else from this review, ship
that.

## What we are explicitly not doing

- **Generic CMS.** This is not "build a Notion clone in the dashboard." Every
  surface above is a thin lifecycle exposure for content the engine already
  manages.
- **Replacing the workflow engine for research.** Research becomes a *workflow
  flavor* with a special UI; the engine is unchanged.
- **Multi-user content sharing.** Stays out of scope until the Teams direction
  from the brainstorm is picked up.
- **Auto-curation by AI.** The curation cadence (E) *surfaces* candidates; the
  user clicks. We don't auto-delete anything.
