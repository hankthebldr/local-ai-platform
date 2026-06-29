# Enclave — full user-flow + doc gap audit (2026-06-17)

> Cross-module review of the real end-to-end user journeys vs the planning /
> design / backlog docs. 7 parallel auditors (6 module flows + 1 docs sweep);
> 88 gaps surfaced (2 critical, 18 high, 37 medium, 31 low). This is the
> prioritized synthesis — what we missed and what to close. Source run:
> workflow `wf_66ec5cca-eed`.

## The headline: provenance/citation is the #1 gap

It surfaced **independently in four modules** (critical in Context/RAG, high in
chat-composer, skills, and the knowledge graph). The `ProvenanceEdge` spec
(`docs/plans/2026-05-16-provenance-edge-spec.md`, 8 emission sites + a citation
rail) was deferred from Phase 2 of the chat-led plan and **never built**:
- No `ProvenanceEdge` model, no provenance table, no `api/routers/provenance.py` (`grep` is empty).
- Chat responses have **no citation rail** — local-model answers are unauditable (the credibility lever the product leans on).
- Skills/tools/RAG-chunks inject into prompts but **emit no provenance** → the context graph (`graph_service.build_graph`) shows "sessions I ran," not real chunk→step→response→workflow lineage.
- Deep-research cites raw web URLs only, not internal provenance.

**Closing it is the highest-leverage work**: `ProvenanceEdge` schema + emission at the tool/skill/chunk/response sites + a citation rail under chat messages + feed the edges into the context graph. Start with tool_executor + skill injection + `response/{id}`.

## Critical (2)

1. **`MODEL_REGISTRY` has no `runner` field** (`models/download.py`) — the GPU runner abstraction (`model_resolver.py:85-100`) and vLLM dispatch are wired, but **zero of 19 models declare `runner: ollama|vllm`**, so per-model GPU routing can't actually dispatch. Add the field + `attach_model_registry`.
2. **Provenance Edge infrastructure absent** — see headline above.

## High (18) — by theme

**Persistence (state that silently evaporates):**
- Conversation history is **session-only** (`Threads` module is in-memory; ux-stories P1 "conversation persistence" not built). Lost on reload.
- Agent **tuning is localStorage-only** (`AgentTuning`) — the `/api/feedback/messages` POST is best-effort, no server store, so tuning doesn't persist cross-machine or truly "carry across workflows" as intended.

**Composite step kinds have engine + YAML but no UI:**
- No kind-aware renderers for `parallel` (fan-out box), `loop` (cycle), `orchestrator`, `ralph` (deferred to 1.4.0 in CHANGELOG row 16) — they render as plain nodes.
- `ralph` ships with no UI for write-mode promotion / halt signals / branch isolation (safety-critical for an autonomous loop).
- Orchestrator dynamic-worker spawn decisions are invisible in the run inspector.

**Composer node ↔ capabilities:**
- Canvas node config **does not expose `tools[]` / `skills[]`** chips — you can't see/edit a step's tools or skills on the canvas.
- The composer-assist endpoint (`archetypes.suggest_companions`) is **not wired to any UI** ("Suggested companions" panel missing) and untested e2e.

**Validation / safety:**
- Agent tools are saved with **no validation** that the referenced plugin/MCP tool exists in the registry (`agent_service` has no `_validate_tools`).

**Resilience:**
- **No Ollama-down fallback** in the Composer (ux-stories Story 6.1 P0): no banner / "Start Ollama" / disabled Promote+Pin when the daemon is unreachable.

**Deferred-but-undocumented:**
- **Fleet / `HostRegistration`** (CLAUDE.md 1.4.x) not built — intentional, but the doc reads like it might exist.
- **License-key** is a hardcoded placeholder (`setup.py`) with no activation/entitlement path — decide: perpetual operator-local, or define a real protocol.

## Documentation hygiene (a cluster of its own)

- `docs/GAP_ANALYSIS.md` (dated **2025-01-10, v0.1.0**) and `docs/ENTERPRISE_DEPLOYMENT_GAPS.md` (**2025-12-09, "~15% ready"**) are badly stale — they predate ~everything shipped. Refresh or archive.
- `CLAUDE.md` "Release track" still says **Current shipped 1.1.1 / Cortex** while the branch is the 1.2.0 candidate; lists the **API-key UI as pending though it shipped**.
- `CHANGELOG.md`: loop iteration-namespacing is **inconsistently marked** (row "10/25" vs "all six step kinds implemented 1–15"); **PR #97 pre-warm UI marked "draft" but appears shipped** (calm-analytics band is live); the **console-v2 backlog isn't in a tracked `[Unreleased]` section**.
- Lingering "Cortex" naming in `docs/design/project/components/*.prompt.md`.

## Medium (37) — observability + UX friction (top items)

- **Runs inspector is shallow for the new engine:** orchestrator spawns, per-step pre-warm decision (which model/GPU), loop iterations (`workspace.{loop}.iterations.{n}`), sandbox tier + approval gate, and durable-memory stores (playbooks/semantic/episodic) are **not browsable** despite the engine persisting them.
- **MCP scope is a no-op:** `MCPService.invoke_tool(scope=…)` always runs workflow-scoped; step/region scope has no effect (`mcp_runner_pool` exists but isn't honored).
- **Composer friction:** plan-card spec edits need an explicit "recompile" (no live preview); node-config edits don't live-update the canvas node; no fullscreen prompt editor; unsaved canvas edits aren't persisted.
- **Admin/settings thin:** error-reporting opt-in **UI not exposed**; audit log **in-memory only**; settings/permissions UI incomplete (no RBAC surface); no persistent deployment-config storage.
- **RAG:** no token-budget/truncation warnings on context injection; document reindex doesn't re-embed with a changed `EmbeddingService` backend (ONNX↔sentence-transformers rebind untested in CI).

## Planned-but-never-built backlog (from ux-stories / ui-flows / console-v2)

Citation rail · conversation-persistence sidebar · response receipts (tokens/time/"≈ $X on GPT-4") · resume cards · Quick-Actions (workflows-as-apps grid, `user_facing=true`) · Projects browse tab · Integrate tab ("switch from OpenAI" snippet) · `enclave doctor` panel + CLI · watched folders + doc audit · privacy panel (provenance/retention/cost toggles) · Skill Lab detail modal + per-project scope · console-v2 backlog (thread rail polish, operator's-path ladder, install wizard for skills/plugins, full Run lens).

## Recommended close order

1. **Provenance + citation rail** (unlocks credibility + the real context graph; spec already exists) — biggest leverage.
2. **`runner` field on `MODEL_REGISTRY`** (small, unblocks the GPU dispatch that's already wired) — quick critical win.
3. **Server-side persistence** for conversations + agent tuning (stops silent data loss; makes tuning's cross-workflow promise real).
4. **Composite-step-kind UI renderers + ralph safety signals** (the engine shipped; the UI didn't).
5. **Node tools/skills editing + composer-assist panel + tool validation** (closes the composer↔capabilities loop).
6. **Ollama-down fallback** (P0 resilience, small).
7. **Doc refresh sweep** — CLAUDE.md release line, CHANGELOG inconsistencies, archive/refresh the two stale gap docs, console-v2 backlog into `[Unreleased]`.

Fleet (1.4.x), license entitlement, and RBAC/audit-persistence are deliberate later-cut items — document them as such rather than build now.
