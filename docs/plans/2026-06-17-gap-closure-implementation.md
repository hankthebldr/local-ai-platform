# Gap-closure implementation plan (2026-06-17)

Closes the gaps from `docs/research/2026-06-17-flow-gap-audit.md` (88 gaps; 2
critical, 18 high, 37 medium, 31 low). Build the critical + high closeable
gaps + the cheap doc fixes; **document** the deliberate later-cuts rather than
build them now (the audit said so). Each phase is verified live on `:8001`
(the container bind-mounts `api/`) + tests, and committed.

> **Delivered (2026-06-17).** Phases 1–5 shipped on `feat/chat-led-composer`.
> New backend tests: `tests/test_provenance.py` (13),
> `tests/test_conversation_persistence.py` (10); full suite `1731 passed, 1
> skipped`. Two scoping corrections found during build, documented inline
> below: (a) `composer/assist` + `MCPService.invoke_tool(scope=)` + the ralph
> hard-cap safety rails were **already wired** in the engine — Phase 4/5 surface
> them rather than build them; (b) composite step-kind **authoring on the flat
> canvas** is deferred — the engine's container validators (parallel needs ≥2
> `branches` + a separate `gather` with matching outputs and no prompt, etc.)
> can't be satisfied from a single flat node, so a half-correct emitter would
> 422 on every save. Phase 5 therefore ships composite-run **rendering** (the
> honest reading of "UI renderers") + the run-observability + ralph-signal work;
> canvas authoring of composites stays in the YAML editor, tracked as follow-up.

## Phase 1 — Quick critical + doc sweep (low risk, high value)
- **`runner` field on `MODEL_REGISTRY`** — add `runner: "ollama"|"vllm"` to every model in `models/download.py`; surface it in `/api/inventory/catalog` + `MODELS.md`; confirm `model_resolver` can read it. *(critical-2)*
- **Doc refresh** — CLAUDE.md release line (1.1.1→1.2.0-candidate framing, API-key UI no longer "pending"); CHANGELOG loop-namespacing + PR-#97 consistency + a tracked console-v2 `[Unreleased]` backlog subsection; archive-note the stale `GAP_ANALYSIS.md` (2025-01) + `ENTERPRISE_DEPLOYMENT_GAPS.md` (2025-12). *(doc-hygiene cluster)*

## Phase 2 — Provenance + citation rail (the #1 gap, critical-1)
- `ProvenanceEdge` model (`api/models/context_models.py`) + a file-backed `provenance_store.py` (per `docs/plans/2026-05-16-provenance-edge-spec.md`).
- Emit edges at the key sites: skill injection (`PluginService.get_skills`), tool/MCP invoke, RAG chunk retrieval, and per-response.
- `GET /api/provenance/response/{id}` (+ list).
- **Citation rail** under chat messages in `index.html` — chips for the skills/chunks/tools that shaped a response.
- Feed edges into `graph_service.build_graph` so the context graph shows real chunk→step→response lineage.

## Phase 3 — Server-side persistence (high)
- **Conversations**: `conversation_store.py` + `GET/POST /api/conversations`; wire the `Threads` module to persist on snapshot/restore (currently in-memory).
- **Agent tuning**: `GET/POST /api/feedback/agent-tuning`; load on init, persist on vote (currently localStorage-only) — makes the cross-workflow promise real.

## Phase 4 — Composer ↔ capabilities (high)
- **Node `tools[]`/`skills[]` chips** in the node config panel (`index.html`) — view/add/remove.
- **Composer-assist**: wire `POST /api/workflows/composer/assist` (→ `archetypes.suggest_companions`) + a "Suggested companions" panel on node select.
- **Tool validation**: `agent_service._validate_tools()` cross-checks agent tools against the live plugin/MCP registry before save.
- **Ollama-down fallback**: health poll → banner + disable Promote/Pin when the daemon is unreachable.

## Phase 5 — Composite step-kind UI + run observability (high + medium)
- Kind-aware renderers in the run/composer DAG: `parallel` (fan-out box), `loop` (cycle), `orchestrator`, `ralph` (inner DAG) — they currently render as plain nodes.
- **Ralph safety signals** in the Runs view: write-mode/branch/halt indicators.
- Surface orchestrator spawns, per-step pre-warm decision, loop iterations, sandbox tier+approval, durable-memory stores in the run inspector.
- Honor `MCPService.invoke_tool(scope=…)` (step/region) instead of always workflow-scoped.

## Phase 6 — Admin/settings mediums (as budget allows)
- Error-reporting opt-in **UI surface**; persist the audit log; persistent deployment-config storage; RAG token-budget/truncation warning.

## Deliberate defers (document, do NOT build now)
Per the audit: **fleet / `HostRegistration`** (1.4.x), **license entitlement** (keep operator-local placeholder, documented), **RBAC / role management** (2.x), and the large net-new landing-page features (resume cards, Quick-Actions grid, Projects tab, Integrate tab, `enclave doctor`, watched folders, privacy panel) — these are roadmap items, not gap-closure. CLAUDE.md will state them as out-of-scope-for-now.

## Verification + delivery
Each phase: live Playwright smoke on `:8001` (0 JS errors) + `pytest tests/` green + a focused test, committed. Final: open PR `feat/chat-led-composer → master`.
