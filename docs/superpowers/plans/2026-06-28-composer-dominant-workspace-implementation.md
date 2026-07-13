# Composer-Dominant Dynamic Workspace — Implementation Plan

**Status:** Ready for execution · **Date:** 2026-07-06 · **Owner:** front-end
**Design:** [2026-06-28-composer-dominant-workspace-design.md](../specs/2026-06-28-composer-dominant-workspace-design.md)
**Depends on:** parity harness (`tests/parity/`, `scripts/capture_parity_goldens.py`, shipped in `73b4493`)
**Related:** [run-event substrate](../specs/2026-06-18-run-event-substrate-and-dynamic-plan-design.md) · [autonomous orchestration](../specs/2026-06-29-autonomous-orchestration-design.md) (Subsystem C — surfaced by Stage 2's Runs view, not built here)

---

## 1. What this plan adds to the spec

The design is complete on *intent* (module tree, sequencing, parity gate, 9 behavioral
tests, error handling, risks). It **defers four things to this plan**, resolved in §3:
the multi-turn `test-step` decision, the concrete file↔namespace grouping, the
boot-ordering audit, and the phase decomposition with acceptance gates.

Everything here honors the operator's **phase-gated rule**: do not start phase N+1 until
phase N's Gate is signed off. The one hard internal boundary — the **parity gate** — sits
between Stage 1 (modularize, provable no-op) and Stage 2 (the workspace UX).

## 2. Verified baseline (as of `integration/master-plus-k3s` @ this commit)

| Fact | Value | Source |
|---|---|---|
| `index.html` size | **25,362 lines** (spec said 21k; it grew with the console-v2 backlog) | `wc -l` |
| `<style>` block | lines ~36–5679 (~5,600 lines) | spec §ES-modularization |
| `<script>` block | one block, ~7,672–21,270 | spec |
| IIFE namespaces (`window.X = (function`) | **26** | grep |
| Other namespaces (df* families, `RunsTab`, `WorkflowIndex`, `AgentGen`, `Projects`, `RunLens`, `Threads`, `Pins`, `Compare`, `InstallWizard`, `AssetPeek`, `ResearchFlow`, `ComposerSplit`, `ScaffoldModal`, `WorkflowBuilder`, `DfSeedSchema`) | ~15 more → **~41 total** | parity drift + grep |
| Inline `on*=` handlers | **196** symbols, **57** must-bridge (golden `_meta`) | golden |
| `data-action` sites | ~160 already migrated | spec |
| Parity harness | present; **`test_no_handler_drift` RED** — golden missing 17 symbols added post-capture | `pytest tests/parity` |
| Runtime health | 0 console errors, no horizontal overflow @ 1440/1024/768 | live audit |
| Design-system adherence | on-brand (warm-charcoal, teal, mono caps) | live audit |

**Implication:** the shell is clean and shippable but is the *pre-rework* IA. The spec's
target surfaces (`renderRightPane`, `selection.kind`, `enclave.ws.*` session store,
"Promote to step") are at **0 occurrences**; every surface the spec retires
(`_composerEngagedNodeId` ×12, `#step-engage-badge` ×5, `ComposerWorkstream` ×18,
`agent-chat-dock` ×15) is still live. This is a from-zero build, correctly staged.

## 3. Deferred-decision resolutions

### D1 — Multi-turn `test-step` (spec §Chat send, flagged seam)
**Decision: (a) — add an optional `messages[]` field to `POST /api/workflows/test-step`.**
Rationale: requirement 3 ("each node has its own history") is a *conversation* guarantee,
not just a config one; single-shot node chat violates it visibly the moment an operator
sends a second message. The change is **additive + stateless** (absent `messages[]` →
today's single-`user_message` behavior), so it stays inside Approach A (no server session
state) and needs one router edit + one model field. Ship it in **Phase 7** alongside the
unified send, behind a client that only populates `messages[]` for node threads with >1
turn. Fallback if the router change slips review: node chat ships single-shot for v1 and
this reduces to a one-line client TODO — but the default is (a).

### D2 — File ↔ namespace grouping (spec left "exact grouping" to plan)
Concrete map (domains are fixed by the spec; this pins the members):

| Module | Namespaces / functions relocated |
|---|---|
| `core/dom.js` | `esc` (497 sites — the import floor), `renderMarkdown`, `renderMarkdownBasic` |
| `core/net.js` | `Net` |
| `core/ui.js` | `Toast`, `Confirm`, `EmptyState`, `ErrorPanel`, `Skeleton` |
| `core/theme.js` | `Theme` |
| `core/shortcuts.js` | `Shortcuts` |
| `core/heartbeat.js` | `Heartbeat` |
| `core/state.js` **(new)** | `dfEditor`, `dfNodeData`, `dfNextId`, `graphConfig`, `graphData`, `graphSim`, `chatHistory`, `_chatModels`, `_connExpand`, `DfSeedSchema` + **new** `Workspace` session store |
| `shell/boot.js` **(new)** | ordered `boot()` — see D3 |
| `shell/nav.js` **(new)** | top-bar nav; retires `switchTab`'s onclick-string fallback (`:7817`) |
| `shell/router.js` | hash routing `#/<dest>` |
| `shell/actions.js` | `Actions` (162 sites) |
| `shell/legacy-bridge.js` **(new)** | the 57 must-bridge `window.*` re-exposures |
| `workspace/*` | absorbs/retires `ComposerWorkstream`, `ComposerSplit`, `BootSequence`, `ScaffoldModal`, `Pins`, step-engage; new `workspace.js`, `left-rail.js`, `canvas.js` (df* fns), `step-info.js`, `right-pane.js`, `chat-thread.js` (`ChatRating`), `seed-promote.js` |
| `library/*` | `WorkflowIndex`+`Kanban`, `AgentGen`, `CatalogPage`+`CatalogModelsShare`, `SkillsPanel`+`SkillsBuilder`+`SkillsDiscoverShare`, `PluginsPanel`+`ExtDiscover`, `MCPPanel`, `InstallWizard`, `Compare`, `AssetPeek` |
| `runs/*` | `RunsTab` (+ private `_editor`, never exported), `RunLens`, `WorkflowMemory`, `ResearchArtifacts`, `ResearchFlow` |
| `admin/*` | `AdminMenu`, `AdminAuth`, `ApiKeysPanel`, `CloudPanel`, `ExportsPanel` |

Open item for Phase 2: `Threads`, `AgentTuning`, `WorkflowBuilder`, `onChatModelChanged`,
`composerSeedAgent`, `composerStopRun`, `composerTestStepInChat` — assign at extraction
time (Threads→workspace, AgentTuning→workspace/chat-thread, WorkflowBuilder→library).

### D3 — Boot ordering (spec risk §Boot ordering)
Modules are implicitly deferred, so **every parse-time side effect must move into an
explicit `boot()`**. Phase 1 audit enumerates them; the ordered sequence is:
`Theme.apply()` (already inline head — stays) → vendor-global assertion (Drawflow/d3/dagre/
js-yaml present) → `state.init()` (hydrate session + localStorage) → `Actions.register()` →
`Heartbeat.start()` + clock `setInterval` → `Shortcuts.bind()` → `nav/router.init()` (resolve
initial hash) → `workspace.mount(selection)` → per-destination lazy init on first nav.
The ~13 `DOMContentLoaded` handlers + free-floating `Actions.click/.change/.input`
registration blocks collapse into this one call from `main.js`.

## 4. Phases

> Each phase: **scope → acceptance → Gate**. Commit at phase boundaries (named files,
> per the commit policy). Parity/UI tests run against a live `:8001` server with
> `RATE_LIMIT_RPM=0` (learned this session — the limiter false-fails fast e2e suites).

### Phase 0 — Re-baseline the parity goldens *(blocker; no `index.html` moves)*
- **Scope:** the golden drifted (17 symbols added by the console-v2 backlog, 0 removed).
  Run `python scripts/capture_parity_goldens.py`, review the diff is *only* the 17 known
  adds, commit refreshed `tests/parity/golden/{inline_handlers,window_globals}.json`.
  Add the runtime superset + zero-console Playwright parity test the spec calls for (if
  not already present) pointing at the served page.
- **Acceptance:** `pytest tests/parity` fully green; goldens captured from the *current*
  pre-split monolith (only a trustworthy golden is captured pre-split).
- **Gate:** parity green on the untouched monolith. ✅ = safe to start moving code.

### Phase 1 — CSS extraction *(lowest risk)*
- **Scope:** `<style>` (~5,600 lines) → `css/app.css` **verbatim**; `<link rel=stylesheet>`
  in `<head>`. Head theme-bootstrap stays inline classic (must run before paint).
- **Acceptance:** visual diff at 1440/1024/768 identical (screenshot compare vs Phase 0
  baseline); `tests/ui/` 160/160 green; 0 console errors; no overflow.
- **Gate:** pixel-parity + `tests/ui` green.

### Phase 2 — JS module extraction (Stage 1 core) *(large, mechanical, low design risk)*
- **Scope:** relocate the `<script>` block into `js/**` per the D2 map, one **domain at a
  time** (core → shell → library → runs → admin → workspace-legacy). Each namespace gets
  `export` + a `window`-bridge entry in `legacy-bridge.js`. Switch to
  `<script type="module" src="/static/js/main.js">`. Vendored libs stay classic `defer`.
  Honor the risk carve-outs: `dfEditor` in `core/state`, RunsTab's `_editor` **private**;
  audit the 5 shadowed `esc()` before swapping to `core/dom.esc` (leave `renderMarkdown`'s
  own); characterization-snapshot `esc()` output first.
- **Acceptance:** after **each** domain move — parity harness green (superset ⊇ golden,
  every inline `on*=` resolves, 0 console errors); `tests/ui` + non-slow `tests/playwright`
  green. Review each domain's diff independently.
- **Gate:** all domains moved; full parity + e2e green on the modular base.

### Phase 3 — Boot sequence + `main.js` *(closes Stage 1)*
- **Scope:** implement D3's ordered `boot()`; delete the ~13 `DOMContentLoaded` handlers
  and parse-time registration blocks; `main.js` calls `boot()` after imports resolve.
- **Acceptance:** page boots clean; every domain initializes; vendor globals resolve
  before `boot()`; parity Playwright test (superset + zero-console) green.

### 🚦 PARITY GATE (Stage 1 → Stage 2) — *provable no-op*
`Object.keys(window)` ⊇ golden (fail only on *removed* keys) · every inline handler
resolves · 0 console-error boot · `tests/ui` + non-slow `tests/playwright` unchanged.
**Do not begin Phase 4 until this is signed off in chat.**

### Phase 4 — Session/state model
- **Scope:** `core/state.js` `Workspace = { workflowId, projectId, selection, threads }`;
  `ChatThread` model; `localStorage['enclave.ws.'+workflowId]` persist/hydrate; stale-key
  pruning; graceful degradation (localStorage throw → in-memory + one-time Toast).
- **Acceptance:** unit-style Playwright: write threads → reload → restored; stale
  `threads[nodeId]` pruned when node absent; `'seed'` retained; localStorage throw doesn't
  block send. (Spec tests 4, 7.)
- **Gate:** persistence + degradation tests green; no UI wired yet (state is headless).

### Phase 5 — 3-region workspace shell + `renderRightPane(selection)`
- **Scope:** `workspace.js` (left rail / dominant center / right pane); `right-pane.js`
  dispatcher over `selection.kind` (`node|seed|palette|none`); `left-rail.js` (projects
  locator + palette, relocated); `step-info.js` (structural config below canvas; `model`/
  `systemPrompt` read-only mirror). Empty state for `none`.
- **Acceptance:** default selection = `node` if graph non-empty else `seed`; palette
  Agent/Plugin/MCP **click** → `kind:'palette'` config. Design non-negotiables hold
  (teal-leads/emerald-structures/ember≤5%, calm motion, mono labels).
- **Gate:** all four `selection.kind` states render correctly; visual review vs
  `ui_kits/console/` prototype.

### Phase 6 — Selection ↔ chat binding + retire step-engage
- **Scope:** Drawflow `nodeSelected`→`kind:'node'`; blank-click→`kind:'seed'`. Right pane
  swaps to that node's thread. **Delete** `composerEnterStepEngage`/`ExitStepEngage`,
  `window._composerEngagedNodeId`, `#step-engage-badge`. Node thread → `test-step`.
- **Acceptance:** spec tests 1 (A then B → history isolation) + 5 (engage globals gone;
  node select still routes to `test-step`).
- **Gate:** selection-drives-chat proven; removed symbols absent from bundle.

### Phase 7 — Seed → Promote + unified chat send *(includes D1)*
- **Scope:** `seed-promote.js`; one `sendMessage(threadKey)` (seed → `/api/agents/{persona}/
  chat` or `/v1/chat/completions`; node → `test-step`). **Add optional `messages[]` to
  `test-step`** (router + model field, additive). Promote: create node, re-key
  `threads['seed']`→`threads[newId]`, select it, fresh empty seed. Empty-graph promote =
  DAG start; promote-with-selection = append downstream with edge.
- **Acceptance:** spec tests 2 (promote preserves N messages, empties seed, selects node)
  + 3 (promote into existing graph appends with edge); multi-turn node chat sends
  accumulated `messages[]`; single-shot still works when field absent.
- **Gate:** Promote + unified send + multi-turn test-step green.

### Phase 8 — Top-bar nav (retire the 3-menu tier)
- **Scope:** `shell/nav.js` → Composer · Runs · Library ▾ · Admin ▾. Non-Composer
  destinations reuse `.tab-content` swap + hash routing. Ensure every `.tab-btn` carries
  `data-tab`, then delete `switchTab`'s onclick-string fallback (`:7817`).
- **Acceptance:** spec test 6 (all four reachable; `#/runs` etc. deep-link resolve). Fix
  the drifted admin-subnav + `#tab-dashboard`-hidden e2e tests here (they assert the old IA).
- **Gate:** nav + deep-links green; the 3 IA-drift e2e tests updated + passing.

### Phase 9 — Retire remaining old surfaces
- **Scope:** delete `agent-chat-dock`, `composer-workstream` + `ComposerWorkstream.switch`,
  `#df-config-popup`. Active-Run + History move under **Runs**. Shrink `legacy-bridge.js`
  by the now-dead symbols.
- **Acceptance:** dead surfaces gone from markup + JS; parity handler set re-baselined
  (intentional removals → rerun capture); full e2e green.
- **Gate:** no orphaned handlers; bundle free of retired symbols.

### Phase 10 — Behavioral suite + Runs legibility (Subsystem C seam)
- **Scope:** land all 9 spec behavioral tests as durable coverage; ensure `runs/` surfaces
  autonomous-run legibility (per-agent lanes, budget burn-down, dry-streak, vault-write
  log, resume state) so Subsystem C is legible when it lands.
- **Acceptance:** 9/9 spec tests green; `tests/ui` + full `tests/playwright` green
  (`RATE_LIMIT_RPM=0`); the session's 14 known test-drift failures resolved or superseded.
- **Gate:** full green suite; visual + a11y review; design-critique pass.

## 5. Risks & mitigations
Carried from spec §Risks (import cycles → shared state only in `core/state`; boot ordering
→ D3 audit; two Drawflow instances → `_editor` stays private; `esc()` shadowing → audit +
snapshot; caching → `no-store` on `index.html`, cache-bust modules if k3s serves stale).
**Added:** (a) golden drift is *already present* — Phase 0 is a hard blocker, not a
formality; (b) the file grew 25k not 21k → Phase 2 domain moves are larger; budget review
per-domain; (c) e2e limiter false-fails — always run with `RATE_LIMIT_RPM=0`.

## 6. Rollback
Every phase is a named commit on a feature branch (`feat/composer-workspace`, cut from
`integration/master-plus-k3s`). Stage 1 is a provable no-op → revert to the monolith is a
single `git revert` range. Stage 2 phases are independently revertable; the parity gate
commit is the clean fallback point. `index.html` is served `no-store`, so no CDN cache to
purge on rollback.

## 7. Out of scope (deferred — do not build)
Server-side thread persistence (Approach B → 1.4.x fleet-awareness) · LLM-authored DAG
generation · *completing* the `data-action` migration (bridge + shrink only) · per-domain
CSS splitting (`app.css` ships whole) · a JS build/bundler (native ESM suffices).

## 8. Sequencing note
Stage 1 (Phases 0–3 + gate) is mechanical and low-design-risk — the bulk of the diff, the
least judgment. Stage 2 (Phases 4–10) is where design risk lives, on a parity-verified
base. The operator's "single deep phase" directive means these ship as one coordinated
effort; the internal gate keeps it safe. Recommend chat sign-off at: Phase 0, the parity
gate, and Phase 10.
