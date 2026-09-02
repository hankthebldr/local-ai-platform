# Enclave — Next-Wave Roadmap & De-duplicated Backlog

> Authored 2026-07-12. Synthesized from four inputs: the standing deferred backlog
> (composer-agentic-revamp, library-alignment, operate-plane, platform-hardening specs +
> CLAUDE.md roadmap), the stick-verifier defect/backlog findings (RESEARCH RX-1/RX-2,
> DRAFTS DR-1, Library multi-formats, GP-2 security), and the Operate-wave reconciler notes.
> Docs-only. Branch of record: `feat/composer-workspace` (gate GREEN, HEAD `673b0f5`).

Priorities carried from source, with stick-verifier P1 defects elevated. Sizes: **S** localized /
one-surface, **M** multi-file but bounded, **L** cross-cutting / multi-wave.

---

## Continuous-improvement observations (what this wave taught us about the BUILD PROCESS)

These are process learnings, not features — fix the process and several backlog items stop recurring.

1. **`persist-error-as-success` is a recurring, independent anti-pattern (highest-signal finding).**
   Three separate surfaces persist a model-failure *sentinel* as durable success: research `graph-walk`
   (P1 — marks node `done`, writes MOC + RAG-ingests the failure string, so `requeue_stale` can never
   retry it), research `followup`/`compare-node` (P2 — returns 200 with a fake answer, frontend renders
   it as a real turn), and composer `resume-from-failed` (P1 — flips status to `running` *before* the
   load can fail, stranding a zombie run + 500). Same root convention violation, three authors, three
   waves. **Process fix:** a codebase convention/lint — *never* write a failure sentinel to a durable
   store, and *never* return HTTP 200 on a local-model exception. This is the single highest-leverage
   theme (see Recommended Next Workflow).

2. **Line-anchor drift is systematic (+50 to +130 lines since spec authoring).** run-async 490→541,
   list_runs 568→620, workflow-index catch-all 847→1109, dfBuildWorkflowDefinition 9040→9167. Every
   unit had to re-grep at edit time. **Process fix:** treat all spec line numbers as approximate; specs
   should cite symbols/anchors, not line numbers.

3. **"CONSUME-not-fork" shared modules get re-forked when an adjacent wave already shipped them.**
   U14 needed a real re-scope because RX-2 had *already* shipped `context-node-rail.js` as a bespoke
   `shell/` registry, while the spec still modeled it as a *new* LibraryShell adapter under `runs/` —
   a colliding file path. **Process fix:** before building any spec's "new shared module," grep whether
   a just-landed adjacent wave already shipped it; consume the existing API.

4. **Service/module name collisions are real and must be grepped first.** `api/services/scheduler.py`
   (Phase-4 DAG facade) collided with U4's intended `scheduler.py`; the correct name was
   `schedule_service.py`. Grep existing module names before naming a new service.

5. **Adapter uniformity keeps drifting — new Library kinds invent their own format.** Only 4/7 tabs use
   the shell `Installed|Discovered` side-tabs (Models folds into an in-list group, MCP uses a marketplace
   modal, Agents has none). Missing-item guards on `actions()` are inconsistent (mcp/skills/models guard;
   agents/tasks don't → ghost buttons on deleted records). **Process fix:** a blessed LibraryShell adapter
   contract + checklist (discovery surface, `actions()` missing-item guard, clear-selection-on-delete,
   no inline handlers) enforced at review.

6. **`datetime.utcnow()` keeps reappearing in brand-new code** (feedback.py, workflows.py:859,
   agent_service.py:126/149). A drip that a single lint rule would stop.

7. **Test-harness gotchas cost real cycles and masquerade as regressions:**
   - Detached servers (`setsid`/`nohup`/`disown`) are reaped on shell exit in the sandbox (spurious
     exit 144); only the `run_in_background` harness path keeps uvicorn alive across turns.
   - `tests/ui/*` flakes with 5s `ReadTimeout` on `GET /api/setup/local-license` (retries=0) under
     concurrent Playwright contexts against single-worker uvicorn — passes on isolated re-run.
   - e2e self-429s without `RATE_LIMIT_RPM=0`; a 429 storm is a harness artifact, not a failure.
   - Full-suite test pollution: `test_project_tasks_v2::test_read_routes_carry_no_master_gate` and
     `test_run_event_bus` pass isolated, fail combined (module-reload identity checks + asyncio×playwright
     plugin interaction). **Process fix:** codify the RATE_LIMIT_RPM=0 / background-server / isolate-ui
     runbook so later waves don't re-discover it.

8. **Untracked runtime artifacts accrete in the working tree** (data/logs/api.log.*, data/schedules/,
   data/research/, data/config/schedules.json, workflows/dr1-e2e-publish.yaml, a modified
   .claude/settings.json). A `.gitignore` audit is overdue so scheduler/journal/research output never
   risks an accidental commit.

9. **Doc drift trails renames.** The `Workflow Index → Workflows` rename left stale references in
   design/plans docs, nav diagrams, and demo docstrings (which still claim Kanban lives "inside
   Workflows" — it relocated to Projects).

10. **Frozen-engine invariant held across every unit** — no unit touched
    `workflow_engine.py`/`step_executor.py`/`workflow_models.py`; the sanctioned seams stayed put.
    Keep this discipline; it's why the gate stayed GREEN.

---

## Backlog by theme

### Composer

| Title | Why | Size | Pri | Source | Next-wave build sketch |
|---|---|---|---|---|---|
| ✅ **DONE 2026-09-02** — Fix `resume-from-failed` zombie + 500 | Fix&Resume dead-ends with HTTP 500 + state corruption for any *unsaved* composer run — the exact durable-run case DR-1/CH-1 exist for. `FileNotFoundError` (OSError, not ValueError) escapes the catch after status was already flipped to `running`. | M | P1 | DRAFTS DR-1 stick-verify | Catch `OSError`→404; flip+checkpoint `running` only *after* definition confirmed loadable; persist the originating inline definition alongside the run snapshot so `engine.resume()` can rehydrate inline runs. Same fix to `resolve_approval` (identical shape). |
| FE3: carve `df*` globals into a `canvas.js` state-object | The deferred Composer state refactor (~220 call sites); unblocks the index.html module-split and reduces global coupling. | L | P2 | composer-agentic-revamp (Deferred) | Introduce a `CanvasState` object; migrate `df*` reads/writes behind accessors incrementally; land each slice under the parity golden. Pairs with the Platform UI module-split. |
| Sharded research fan-out preset | Cut from the v1 parallel pattern; exactly-1-branch + sharder + `shard_input` semantics for map-style research. | M | P2 | composer-agentic-revamp (Deferred) | Add a pattern preset emitting a single-branch loop with a sharder node + `shard_input` binding; validate against pattern-presets tests. |
| Composer hook authoring | `_dfCleanStep` hooks serializer + inspector attach UI so operators can attach step hooks from the canvas. | M | P2 | library-alignment (Deferred #4) | Add a hooks serializer to the step blob + an inspector "Hooks" section; round-trip through composer serialization tests. |
| First-class "saved workflow id" seam | U8 schedule "unsaved" detection is heuristic (`#df-wf-id` empty OR band `data-state==='unsaved'`); a loaded-unmodified workflow reading `unknown` slips through and relies on the CRUD 422. | S | P2 | Operate U8 note | Expose a canonical saved-id on the composer model; schedule/save gate reads it instead of the DOM band heuristic. |
| `list_drafts` blob-free index | In-Progress tab render is O(total draft bytes) — loads every draft's full ≤2MB blob just to strip it via `_summary()`. | S | P2 | DRAFTS backlog | Store a blob-free summary index (or read summary fields without parsing the whole blob). Also drop the unreachable `.tmp` filter dead code. |
| Composer toolbar overflow (1440px) | The ⏰ Schedule button renders overflowed/not-visibly-clickable at 1440px — a layout smell surfaced by U8's programmatic-click workaround. | S | P3 | Operate U8 note | Give the toolbar a horizontal-scroll or overflow-menu treatment. |

### Research

| Title | Why | Size | Pri | Source | Next-wave build sketch |
|---|---|---|---|---|---|
| ✅ **DONE 2026-09-02** — Fix `graph-walk` persist-error-as-success | On a model/search outage the node is marked `done`, the failure sentinel is written as a durable note + MOC section + RAG-ingested, and `requeue_stale` (only requeues `in_progress`) can NEVER retry it — defeats the advertised resumable/survives-interruption contract. Reproduced live. | M | **P1** | RESEARCH RX-2 stick-verify | Have `compare_node` return an ok/error flag; `graph-walk` calls `set_status(id,'error')` (not `done`) on failure and skips the note/MOC/RAG write; add model-down failure-path coverage to `test_research_rx2.py`. |
| ✅ **DONE 2026-09-02** — Fix `followup`/`compare-node` error persistence | Same anti-pattern, lower blast radius: model exception → 200 with `_Answer unavailable_`, appended as a durable session turn + MOC + ConversationStore mirror; frontend renders it as a legit reading-card turn. | S | P2 | RESEARCH RX-1 stick-verify | Return non-200 (or explicit `ok:false`) on model failure; frontend surfaces a Toast instead of persisting; don't mirror failed turns into ConversationStore. |
| Resolve RAG embedding-dimension rebind | Live RAG disabled: chroma `enclave-docs` is 384-dim (sentence_transformers/all-MiniLM) but EmbeddingService now reports 768-dim (ollama/nomic-embed-text) → `document_service` is None, every research/artifact save reports `rag_ingested:false`, and the Obsidian RAG semantic-recall follow-up path is unverifiable end-to-end. Blocks RX-2 verification and U13 heal. | S | P1 | RX-2 / DRAFTS / U13 notes | `ENCLAVE_EMBEDDING_ALLOW_REBIND=true` or wipe `data/rag/chroma` to re-ingest; add an embedding-dim capability flag so the Research docs panel degrades honestly when no embedding backend is expected. |
| Clear stale worklist locks | Interrupted graph-walks leave `.enclave/index/*.lock` in the store. | S | P2 | RX-2 backlog | TTL / auto-clear on `next_pending`. |
| `_researchSlug` comment + underscore fidelity | Client collapses every non-`[a-z0-9]` run to `-` (drops `_`) but its comment claims it mirrors the server's `_derive_slug` (which preserves `_`/`-`); harmless today, diverges for any future server-derived slug. | S | P2 | RX-2 stick-verify | Align the slug fn or fix the comment. |
| Research-followup `web_search` opt-in surface | Kept OFF for privacy; revisit as an explicit opt-in toggle. | S | P3 | platform-hardening (Deferred) | Add an opt-in web_search affordance in the followup composer, default off. |

### Library

| Title | Why | Size | Pri | Source | Next-wave build sketch |
|---|---|---|---|---|---|
| Agents delete → ghost-button fix | `AgentsPanel.actions()` returns its static verb array with NO missing-item guard, and `deleteAgent` never clears shell selection → four live action buttons on a "Agent not found" ghost record (404/no-op on click). Lone tab leaving actionable dead controls. | S | P2 | Library multi-formats stick-verify | `if(!_agent(id)) return []` in `actions()`; `deleteAgent → LibraryShell.select('agent', null)`. Add the same guard to `tasks.js` defensively. |
| Retire/fold the second Skills discovery surface | MS-4 collapsed the duplicate in-tab *filters* but `#skills-discover-panel` (SkillsDiscover module, own search + category select + view toggle, all inline handlers) still reads the same `/api/skills/discover` → "single discovery surface" holds only within the tab. | M | P2 | library-alignment #7 / stick-verify | Make the shell Discovered side-tab the single browse/install surface, or migrate `#skills-discover-panel` off inline handlers onto delegated `data-action` grammar. |
| Workflows adapter on the Library shell | Completes the A1 kind set (Kanban/workflow-index coexistence). Agents migration (#1) already shipped via MS-5. | M | P1 | library-alignment (Deferred #2) | Register a `workflow` LibraryShell adapter; keep the Kanban board coexisting as a subnav slot. |
| Model pull flow onto LibraryWizard | The one named A5 carve-out never migrated; model pull is still bespoke. | M | P1 | library-alignment (Deferred #18) | Port model-pull into the shared LibraryWizard step flow. |
| Discovery-format convergence decision | 4/7 tabs use side-tabs; Models=in-list group, MCP=marketplace modal, Agents=none. Deliberate per module headers but it *is* the "multiple formats" the review targets. | M | P2 | Library stick-verify backlog | Decide: converge Models/MCP onto side-tabs, or bless the divergence and document it as a contract exception in the adapter checklist. |
| Library dead-code sweep | Dead `skills.side-tab/group/dtab` handler registrations (nothing dispatches them); `_renderActiveChatPill()` defined/exported with zero call sites; stale IA comments claim HF/Skills Discover live under Models but they render under `tab-memory`. Ironic against the dead-control-honesty pass. | S | P2 | Library stick-verify | Remove dead registrations or wire markup; drop/re-invoke the pill; fix the containment comments. |
| Plugin version history / rollback + signed-manifest marketplace | 409-unless-force reinstall; reintroduce the version action verb. Overlaps CLAUDE.md "Plugin marketplace v1 (signed manifests)". | L | P2 | library-alignment #8 / CLAUDE.md | Add a plugin version store + rollback; signed-manifest verification; `409` on reinstall unless `force`; restore the version verb. |
| Generic per-plugin config store | `GET/PUT /api/plugins/{id}/config` for plugin-scoped settings. | M | P2 | library-alignment #6 | Add the endpoint + a plugin config pane; back with the plugin data-dir below. |
| Plugin data-dir persistent state | `PLUGIN_DATA`-style per-plugin persistent state adoption. | M | P2 | library-alignment #14 | Provision a per-plugin data dir + accessor; wire into the config store. |
| Server-side saved test suites + MCP warm-session pooling | Generalize `/api/agents/{id}/evaluate` cases into reusable suites; pool MCP warm sessions if latency demands. | M | P2 | library-alignment #5 | Persist named test-case suites; add an MCP session pool keyed by signature. |
| Multi-file external skill directory install | Rides the LB5 fetcher; the tree endpoint already renders dirs. | M | P2 | library-alignment #7 | Extend the skill installer to walk + install a directory tree via the shared fetcher. |
| Model promote target + registry curation loop | Per-model overrides file (until then `model test.promote` stays disabled); operator tag overrides (`model_tags.json → MODEL_REGISTRY`, manual until then). | M | P2 | library-alignment #10, #13 | Add a per-model overrides file + a curation loop that folds `model_tags.json` into the registry; re-enable promote. |
| AssetPeek kind extensions | Retire bespoke overlays and DOM relocators in favor of AssetPeek kinds. | M | P2 | library-alignment #3 | Register the remaining kinds on AssetPeek; delete the bespoke overlay code. |
| Tasks external digest ingestion | Via the shared prompt/cookbook fetcher. | S | P2 | library-alignment #12 | Wire Tasks digest import onto the shared fetcher. |
| Per-skill enable/disable flag | `plugin.yaml` registration is the only enablement lever in v1. | S | P2 | library-alignment #11 | Add an enable flag + toggle in the skill row. |
| Models "Installed Locally" convergence | Currently a deliberate function split between local-install and catalog views. | S | P3 | platform-hardening (Deferred) | Merge the two model surfaces once the catalog relocation lands. |
| Community marketplace tier | Public/community plugin+skill marketplace. | L | P3 | library-alignment #9 | Later — gated behind signed manifests + version history. |

### Operate

| Title | Why | Size | Pri | Source | Next-wave build sketch |
|---|---|---|---|---|---|
| Cron expressions (croniter) + multi-weekday cadence | v1 is a single weekday/time model; operators will want `Mon+Wed+Fri` / cron. The host-side recurring scheduler service is now delivered by U4. | M | P1 | operate-plane §12 / composer-revamp Deferred | Add `croniter`; extend the schedule model + U8 wizard weekday picker to multi-weekday/cron; surface a "next fire" preview. |
| Resolve 3 truncated operator asks | Blocks correct build of: O1 nav ordering / deepDive wording, O7 context-node pivot set + promote semantics, O5 OpenWork-side (:8787) directory config scope. | S | P1 | operate-plane §10 (Pending operator input) | Run a short operator Q&A to pin the three, then implement. |
| Projects `depends_on` + timeline dependency arrows | Land together (C13) with referential validation so arrows can't dangle. | M | P1 | operate-plane §12 | Add a validated `depends_on` field + render dependency arrows on the timeline. |
| Projects CRUD: delete/rename/reorder/assignee | Gap flagged for Operate U2/U3 scope amendment; overlaps power-user undo/redo/multi-select. | M | P2 | platform-hardening (gap-ledger) | Add the four project ops + bulk/multi-select; wire undo/redo. |
| Projects timeline drag-to-reschedule | v1 is render-only (C16); direct-manipulation `PATCH start/due`. | M | P2 | operate-plane §12 | Add drag handles → PATCH start/due; optimistic render + reconcile. |
| Projects JSONL compaction/snapshotting | Hot projects replay full `tasks.jsonl`/`runs.jsonl` on every GET/apply (O(events)); U12 proposal-churn adds a driver. `runs.jsonl` now joins the list. | M | P2 | operate-plane §12 / U2, U12 notes | Add snapshot + compaction for project/task/run JSONL; enforce the 50-pending-proposal cap (409) in the U12 apply path. |
| Projects: `plans/plan-<date>.md` workspace write | U12 shipped the `runs.jsonl` ref append but deferred the plan-doc write (needs a bound docs workspace). | S | P2 | operate-plane U12 note | On Draft-plan, PUT `plans/plan-<date>.md` via the workspace API when a docs workspace is bound. |
| Projects backend bundle | Run reconciler on the seed convention; bundle export carrying tasks/runs jsonl; LibraryShell adapter for the Docs sub-view; milestone entity store with dates; workspace `mkdir`/per-file-delete endpoints for the Docs editor; context-workspace unbind/deregister route. | L | P2 | operate-plane §12 / U2 note | Ship as a Projects-persistence mini-wave. |
| Artifacts v2 | Workspace files in the unified Outputs inventory; delete/compaction for feedback JSONL + run-artifact retention; rendered-markdown preview; format-validation hooks; per-workflow default format set. artifacts.py is deliberately read-only in v1. | M | P2 | operate-plane §12 / U10, U11 notes | Absorb workspace files into `_all_items`; add delete/compaction + a rendered preview; broaden format-set ref scan to composer-draft workflows. |
| Runs/Scheduler deep hardening | dispatches.jsonl deeper compaction; migrate the Runs list onto LibraryShell; retro-tag the 1,675 historical runs (lets the U9 client drop its duration fallback); engine-persisted `triggered_by` (blocked until a sanctioned model change); operator-tunable degraded/zombie thresholds; backfill of missed fires (cut by policy). | L | P2 | operate-plane §12 / U5, U9 notes | Batch as a Runs-scale mini-wave; keep engine-persisted fields gated on a sanctioned model change. |
| Operator-tunable thresholds | `SCAN_CAP=500`, `ANOMALY_FACTOR=3.0`, `MEDIAN_WINDOW=10`, `_ensure_rag()` 30s throttle are hardcoded constants. | S | P2 | U5, U13 notes | Move to an env/config tunables surface alongside the deferred degraded/zombie thresholds. |
| Context/System 503 UX + cleanups | `ollama_unavailable` 503 UX; RunnerRegistry startup-ordering 503s; delete the context-rail fallback renderer; capability flag for the Research docs panel when no embedding backend is expected. | M | P2 | operate-plane §12 / U14 note | Reuse the U13 lazy-reinit pattern for the two 503 follow-ups; remove fallbacks once the shell contract is guaranteed at eval time. |
| Cross-build seams | `AdminAuth.renderLock` raw-element-id extension (unlocks shell `auth:admin` for rail adapters); `TestPane` `origin:test` request field. | S | P2 | operate-plane §12 / hardening | Extend renderLock to raw ids; add the origin field. |
| `.gitignore` audit for runtime output | Scheduler/journal/research byproducts (data/logs/api.log.*, data/schedules/, data/research/, data/config/schedules.json, workflows/dr1-e2e-publish.yaml) risk accidental commit. | S | P2 | U7, U9, U14 notes | Add ignore entries; confirm no runtime output is tracked. |
| OP1 nav inline-onclick → data-action | Last inline-onclick nav button; requires a golden regen. | S | P3 | operate-plane §12 | Convert to `data-action=switch-tab`; regen `inline_handlers.json`. |

### Platform / Infra

| Title | Why | Size | Pri | Source | Next-wave build sketch |
|---|---|---|---|---|---|
| Ship curated seeds via the COPY'd tree | `mcp_catalog.json`, `skills_catalog.json`, `model_benchmarks.json` are git-tracked but never reach containers — the Dockerfile doesn't `COPY data/`. Every container ships with empty seeds. | S | P1 | library-alignment #16 | Add `COPY data/` (or the seed subset) to the Dockerfile; assert seeds present in a built image. |
| Migrate TTL-on-read fetches → refresh-only | `skills.py:44`, `mcp.py:58`, and HF discovery on `GET /api/inventory/discover` still fetch on read, so the platform-wide no-background-egress posture is false. | M | P1 | library-alignment #15 | Convert TTL-on-read to explicit ⟳ refresh; add a test asserting no egress on GET. |
| ◐ **`/api/research` SCOPE_MAP DONE 2026-09-02**; read-route sweep open — Global read-route auth sweep + `/api/research` SCOPE_MAP | `/api/research/*` has NO SCOPE_MAP entry — every research write+egress endpoint is callable by any valid key when auth is on, even though the parallel `/api/workspaces` is scope-gated and writes the same workspace. Symptom of a broader missing read-route audit. | M | P1 | library-alignment #17 / RX-2 stick-verify | Add `/api/research` to SCOPE_MAP (data-action tier, `workspaces` scope); audit all read routes for correct scope + no master-gate; add missing entries (U4/U10 pattern). |
| Complete the XSS `safeUrl()` sweep | a0e9243 fixed main.js but `discover.js:102`, `prompts.js:609`, `plugins.js:441` still interpolate external-catalog URLs into `href` via `esc()` (escapes `&<>` but NOT quotes and does NOT neutralize scheme) → a marketplace/plugin/prompt-source entry with `javascript:` or a `"`-breakout renders a clickable XSS anchor. | S | P2 | GP-2 stick-verify | Route all three sinks through `safeUrl()` (same as main.js:753/768/3861). Add a pure-JS/node assertion so the sanitizers keep CI coverage without a browser. |
| Tighten loopback-license trust | `_is_local_client` returns True for `ipaddress.is_private`, matching all RFC1918 + CGNAT 100.64.0.0/10 (Tailscale) + link-local → any tailnet/LAN peer can GET the first-run master key, not just the box. | S | P2 | GP-2 stick-verify | Loopback-only by default + explicit `ENCLAVE_TRUST_PRIVATE_NET` opt-in before non-localhost exposure. |
| Agent fork/chat tool-scoping fixes | `_dfAgentToolsToRefs` drops built-in type tools (web_search/workflow/code_exec) on fork ("fork carries tools" is partial); `chat_with_agent` builds the request with ALL installed plugin tools instead of the agent's declared `tools[]` subset. | S | P2 | GP-2 stick-verify | Add a step-kind representation for built-ins (or an operator warning on fork); enforce the agent's tool allowlist when constructing the `/v1` request. |
| `datetime.utcnow()` deprecation sweep + lint | Reappears in new code (feedback.py:113/164/166/239, workflows.py:859, agent_service.py:126/149); emits DeprecationWarning, breaks on removal. | S | P2 | multiple stick-verify | Global `→ datetime.now(timezone.utc)`; add a lint rule to stop the drip. |
| Data substrate v2 | `schema_version` migration + reference-counting/cascade/orphan-detection + backup/restore. The durability floor under Projects/Artifacts/Runs. | L | P1 | platform-hardening (Deferred) | Introduce a schema-version migrator + refcount/GC + backup/restore CLI. |
| 1.4.x Fleet awareness | Mac M4 + MS-01 + BD790i over Tailscale: `HostRegistration` model, target-host selector on Composer, resume-on-other-host, opt-in Wake-on-LAN. | L | P1 | CLAUDE.md roadmap | Add a host registry + target-host selector; route runs to a chosen host; WoL as opt-in. |
| 1.5.x Pluggable inference engines | vLLM + llama.cpp parity with Ollama via the OpenAI-compatible surface; per-host engine choice in the fleet registry. | L | P1 | CLAUDE.md roadmap | Abstract the runner behind the OpenAI-compatible client; per-host engine field on `HostRegistration`. |
| 1.x UI module-split | Fan the ~30k-line index.html out into ES modules (pairs with Composer FE3). | L | P2 | CLAUDE.md roadmap | Extract modules behind the parity golden, one surface at a time. |
| Escape overlay full ModalStack | CP-1 shipped only a cheap guard. | M | P2 | platform-hardening (Deferred) | Real modal stack with focus trap + Escape unwind. |
| Full fuzzy command palette | CP-1 shipped only a minimal filter Cmd-K. | M | P2 | platform-hardening (Deferred) | Fuzzy scorer + action registry + recents. |
| Wholesale inline-handler → data-action migration | Parity-pinned, deferred platform-wide (grandfathered handlers). | L | P2 | platform-hardening (Deferred) | Migrate remaining `on*=` handlers to delegated `data-action`, regen golden per surface. |
| Accessibility cluster | Canvas has no accessible representation; CP-1 only removed a nav-label `aria-hidden` as a down-payment. | L | P2 | platform-hardening (Deferred) / gap-ledger | Add an accessible canvas representation + keyboard nav; ARIA pass across shells. |
| Knowledge-loop bridges | facts↔`$memory`, session-summaries, message-rating, memory similarity. | L | P2 | platform-hardening (Deferred) / gap-ledger | Wire the four bridges into the memory store + Runs telemetry. |
| Distribution: codesign/notarize | `.app` codesign / notarize / reachability / bundle-assets. | M | P2 | platform-hardening (Deferred) / gap-ledger | Signing + notarization pipeline; bundle static assets. |
| Round-trip fidelity | `_from_agent` / Import-YAML / category-tags / `prompt.*` (partially Operate U11 sentinel). | M | P2 | platform-hardening (gap-ledger) | Complete YAML round-trip through the U11 sentinel serializer. |
| Tool-call I/O capture sidecar | `tool_io_capture.py` + `GET /runs/{id}/tool-io` for per-tool arg/body drill-down in Logs. | M | P3 | composer-revamp (Deferred) / hardening | Capture tool I/O to a sidecar file; expose the endpoint; add a Logs drill-down. |
| Atomic-save tmp-collision note | `_dump_agent_yaml_atomic` + `save_workflow` use a fixed `<id>.yaml.tmp` sidecar; two concurrent same-id saves race. Fine for single-operator, flag before multi-writer 2.x. | S | P3 | GP-2 stick-verify | Unique/pid-suffixed tmp name when the single-writer assumption changes. |
| Admin-observability a2a default-drift | Worth pulling into a GP-2-style commit if budget. | S | P2 | platform-hardening (gap-ledger) | Add the a2a default-drift check to the admin-observability panel. |
| License-key surface | Beyond the current placeholder. | M | P2 | CLAUDE.md roadmap | Real license key entry/validation surface (loopback-license tightening is a prerequisite). |
| Workflow YAML editor | Direct YAML editing for workflows. | M | P2 | CLAUDE.md roadmap | In-app YAML editor with validate-on-save against `workflow_models`. |
| AgentTuning runtime injection | Frozen engine — CP-1 shipped an honest toast only. | M | P3 | platform-hardening (Deferred) | Requires a sanctioned engine change; deferred while engine is frozen. |
| Agent TestPane / provenance / re-sync | Frozen engine, Library f/u #2 — WONT-FIX this branch. | M | P3 | platform-hardening (gap-ledger) | Deferred with the frozen-engine invariant. |
| Wikilink resolution in store preview | Render `[[wikilinks]]` in the store preview. | S | P3 | platform-hardening (Deferred) | Resolve wikilinks against the workspace index in preview. |
| Power-user undo/redo/multi-select | Projects bulk = Operate U3/U12. | M | P2 | platform-hardening (gap-ledger) | Shared undo stack + multi-select on Projects/Library. |
| 2.0.0 commercial direction (TBD) | If team SKU — RBAC, audit log, multi-tenant storage, observability stack; if free appliance — deliberate UX/aesthetic refresh. | L | P3 | CLAUDE.md roadmap | Decision-gated; do not start until direction is chosen. |

### Testing / Quality

| Title | Why | Size | Pri | Source | Next-wave build sketch |
|---|---|---|---|---|---|
| 1.3.0 completion: land PR #97 | Arch-aware UI summary so Memory tab + Runs view reflect the full pipeline end-to-end. | M | P1 | CLAUDE.md roadmap | Review + merge #97; verify Memory/Runs render the full pipeline. |
| Remaining gap-closure | Provenance/citation, server-side persistence, composite-step-kind UI (tracked in `docs/plans/2026-06-17-gap-closure-implementation.md`). | M | P1 | CLAUDE.md In-flight | Work the gap-closure plan to done. |
| Stabilize `tests/ui` license-fetch flake | 5s `ReadTimeout` on `/api/setup/local-license` (retries=0) under concurrent Playwright masquerades as a regression. | S | P2 | reconciler / multiple unit notes | Add small retry/backoff to the setup fixture, bump the read timeout, or serialize `tests/ui` from `tests/parity`. |
| Failure-path research tests | A model-down `graph-walk` must leave the item retryable (`error`, not `done`) and must not pollute the MOC/RAG store. Current rx2 tests cover only happy-path counts. | S | P2 | RX-2 stick-verify | Add the model-down case to `test_research_rx2.py`. |
| Fix full-suite test pollution | `test_project_tasks_v2::test_read_routes_carry_no_master_gate` + `test_run_event_bus` pass isolated, fail combined (module-reload identity check + asyncio×playwright interaction). | M | P2 | gate notes | Make the router-identity check reload-robust; serialize the asyncio bus test from the playwright session. |
| U15 baseline/seed reconciliation | `xsiam-detection-engineering` (and the xsiam workflow) aren't registered in the server overlay, so the 14-test e2e baseline conflates env gaps with real failures. | S | P2 | U6, gate notes | Seed the missing workflows into the overlay; re-baseline the e2e set. |
| Codify the e2e/ui runbook | `RATE_LIMIT_RPM=0` for non-slow e2e; `run_in_background` for long-lived uvicorn; isolate `tests/ui` parallelism. Recurring rediscovery. | S | P2 | reconciler notes | Write a `tests/README` runbook section; wire the flags into CI defaults. |

---

## Recommended next dynamic workflow

Two themes carry the most leverage per unit of effort. Run **Theme A first** (P1-dense, data-integrity,
small-to-medium, cross-cutting a single root cause), then **Theme B**.

**A. "Fail-safe persistence & resume" hardening wave (do this first).** ✅ **Shipped 2026-09-02** (all three defects + failure-path tests + the `/api/research` SCOPE_MAP gate; the convention is now in CLAUDE.md → Conventions). The broader read-route auth sweep stays in Theme B.
One root convention — *never persist a model-failure sentinel as durable success; never return HTTP 200
on a local-model exception* — resolves **two P1 defects and one P2** that today silently corrupt durable
state across *both* Composer and Research:
- Research `graph-walk` (P1): stop marking failed nodes `done`; set `error`, skip the note/MOC/RAG write,
  restore the resumable contract.
- Composer `resume-from-failed` (P1): catch `OSError`→404, flip status only after the definition loads,
  persist inline definitions so Fix&Resume actually works for unsaved runs.
- Research `followup`/`compare-node` (P2): non-200 + Toast instead of persisting the error string.
- Plus the paired failure-path tests and the `/api/research` SCOPE_MAP gate.
This is the highest-leverage work because it is P1, cross-surface, shares one fix pattern, is
small-to-medium, and directly protects the durable-run and resumable-research contracts the last four
waves advertised. It also retires the top continuous-improvement finding.

**B. "Hardened-deployment posture closure" platform wave (do this second).**
Five clustered P1/P2 items that currently make the self-hosted-appliance security story *false*:
ship curated seeds via `COPY data/` (empty seeds in every container today), migrate TTL-on-read fetches
to refresh-only (no-background-egress posture), the global read-route auth sweep + `/api/research`
SCOPE_MAP, the completed XSS `safeUrl()` sweep, and loopback-license tightening (a Tailscale peer can
currently grab the master key). These share the auth/egress/packaging surface, are mostly S/M, and close
the gap between the claimed and actual hardened-deployment posture before Fleet-awareness (1.4.x) exposes
Enclave across the tailnet.

---

## Item counts by priority

- **P1:** 16
- **P2:** 53
- **P3:** 11
- **Total:** 80 items across 6 themes (Composer 7, Research 6, Library 17, Operate 15, Platform/Infra 28, Testing/Quality 7).
