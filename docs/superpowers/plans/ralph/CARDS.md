# Ralph CARDS — one per phase

Each card is the variable half of a loop; pair it with [HARNESS.md](./HARNESS.md).
`CAP` = iteration hard cap · `type/scope` = commit prefix. Run Stage 1 (Phase 0→3),
**stop at the parity gate for human sign-off**, then Stage 2 (Phase 4→10).

---

## Stage 1 — modularize (provable no-op, gated by the parity harness)

### phase-0 — re-baseline the goldens · CAP=6 · type/scope=test(parity)
GOAL: parity harness green on the UNTOUCHED monolith; goldens captured pre-split.
UNITS:
- [ ] Run `python scripts/capture_parity_goldens.py`; confirm the golden diff is ONLY these 17 adds, 0 removals: AssetPeek, Compare, ComposerSplit, DfSeedSchema, InstallWizard, Pins, ResearchFlow, RunLens, ScaffoldModal, Threads, WorkflowBuilder, composerSeedAgent, composerStopRun, composerTestStepInChat, loadStatus, onChatModelChanged, openWorkflowInComposer. Anything else changed → HALT.
- [ ] Commit refreshed `tests/parity/golden/{inline_handlers,window_globals}.json`.
- [ ] Ensure a runtime parity Playwright test exists (`Object.keys(window)` ⊇ golden + zero console errors on boot) against the served page; add it if missing.
VERIFY: `pytest tests/parity -q` (+ the runtime parity test with server up)
GATE: `pytest tests/parity -q` fully green with ZERO changes to `api/static/index.html`.

### phase-1 — extract CSS · CAP=6 · type/scope=refactor(ui)
GOAL: `<style>` → `api/static/css/app.css` VERBATIM, linked; zero visual/behavior change.
UNITS:
- [ ] Capture baseline screenshots @1440/1024/768 into scratchpad (reference set).
- [ ] Move the `<style>` block (~lines 36–5679) verbatim into `api/static/css/app.css`.
- [ ] Add `<link rel="stylesheet" href="/static/css/app.css">` in `<head>`; KEEP the head theme-bootstrap script inline classic (must run before paint — no flash).
- [ ] Screenshot-compare @3 widths vs baseline; assert visually identical.
VERIFY: `pytest tests/ui -q` + screenshot diff clean + 0 console errors + no x-overflow.
GATE: pixel-parity @3 widths AND `pytest tests/ui -q` green.

### phase-2 — extract JS to ES modules · CAP=20 · type/scope=refactor(js)
GOAL: relocate the `<script>` block into `js/**` per the plan's D2 map — ONE DOMAIN per iteration — each namespace `export`ed and re-exposed via `shell/legacy-bridge.js`; then flip `index.html` to `<script type="module" src="/static/js/main.js">`. Vendored libs (Drawflow, d3, dagre, js-yaml) stay classic `<script defer>`.
UNITS (one per iteration, in order — DAG-safe, import floor first):
- [ ] core/ — dom(esc/renderMarkdown), net(Net), ui(Toast/Confirm/EmptyState/ErrorPanel/Skeleton), theme, shortcuts, heartbeat, state(dfEditor/dfNodeData/dfNextId/graphConfig/graphData/graphSim/chatHistory/_chatModels/_connExpand/DfSeedSchema). Snapshot each of the 5 shadowed esc() (ApiKeys/Plugins/Skills/Cloud/Exports) before swapping to core/dom.esc; leave renderMarkdown's private esc ALONE.
- [ ] shell/ — actions(Actions, 162 sites), router(hash), legacy-bridge(the 57 must-bridge).
- [ ] library/ — workflow-index(+Kanban), agents(AgentGen), models(CatalogPage+CatalogModelsShare), skills, plugins, mcp, install-wizard, compare, asset-peek.
- [ ] runs/ — runs(RunsTab), run-lens, workflow-memory, research-artifacts, research-flow. Keep RunsTab's private `_editor` Drawflow instance PRIVATE — never export it.
- [ ] admin/ — menu, auth, api-keys, cloud, exports.
- [ ] workspace-legacy/ — df* → canvas.js; relocate ComposerWorkstream/ComposerSplit/BootSequence/ScaffoldModal/Pins/Threads/AgentTuning as-is (retirement is Stage 2).
- [ ] Flip `index.html` to the module entry; delete the extracted `<script>` body.
VERIFY (after EACH domain): `pytest tests/parity -q && pytest tests/ui -q && ENCLAVE_PLAYWRIGHT_BASE_URL=http://localhost:8001 pytest tests/playwright -m "not slow" -q`
GATE: every domain [x]; full parity + tests/ui + non-slow e2e green on the modular base.

### phase-3 — ordered boot() · CAP=6 · type/scope=refactor(js)
GOAL: replace parse-time side effects with a single ordered `boot()` called from `main.js`.
UNITS:
- [ ] Audit + list every parse-time side effect into the ledger (~13 DOMContentLoaded handlers, setInterval(updateClock), free-floating Actions.click/.change/.input blocks).
- [ ] Implement `shell/boot.js` in this order: Theme(inline, stays) → assert vendor globals → state.init() → Actions.register() → Heartbeat.start()+clock → Shortcuts.bind() → router.init()(resolve initial hash) → workspace.mount(selection) → lazy per-destination init.
- [ ] Delete the old parse-time handlers; `main.js` calls `boot()` after imports resolve.
VERIFY: runtime parity Playwright (superset + zero-console) + every domain initializes + vendor globals resolve BEFORE boot().
GATE: clean module boot, parity green.

---

## 🚦 PARITY GATE — human sign-off (NOT a loop)
`Object.keys(window)` ⊇ golden (fail only on removed keys) · every inline `on*=` resolves ·
0 console-error boot · `tests/ui` + non-slow `tests/playwright` unchanged from the Phase-0
baseline. **Stop and get sign-off before Stage 2.**

---

## Stage 2 — the workspace UX (on the parity-verified base)

### phase-4 — Session/state model (headless) · CAP=8 · type/scope=feat(workspace)
GOAL: `core/state.js` session store — no UI wired yet.
UNITS:
- [ ] `Workspace = { workflowId, projectId, selection:{kind,nodeId?,paletteRef?}, threads }`.
- [ ] `ChatThread = { key, model, systemPrompt, persona?, options, messages[] }`.
- [ ] Persist/hydrate `localStorage['enclave.ws.'+workflowId]`.
- [ ] Stale-key pruning on load: drop `threads[nodeId]` whose node is absent; KEEP `'seed'`.
- [ ] Graceful degradation: localStorage throw → in-memory + one-time Toast; never block send.
VERIFY: new Playwright tests — write→reload→restore; prune; degrade (spec tests 4 & 7).
GATE: state persistence + degradation tests green.

### phase-5 — 3-region shell + renderRightPane(selection) · CAP=10 · type/scope=feat(workspace)
GOAL: the dominant-composer layout; right pane is a pure `f(selection.kind)`.
UNITS:
- [ ] `workspace.js`: left rail | dominant center Composer | right pane.
- [ ] `right-pane.js` dispatcher: node | seed | palette | none (none = empty-state copy from spec).
- [ ] `left-rail.js`: projects locator + palette (relocated); palette Agent/Plugin/MCP CLICK (no drag) → `selection={kind:'palette',paletteRef}` → its config editor.
- [ ] `step-info.js`: structural config below canvas (name, deps, parser, gates, last-run); model/systemPrompt shown READ-ONLY mirror (editable home is the right pane).
- [ ] Default selection on entering Composer: node if graph non-empty else seed.
VERIFY: all four kinds render; design non-negotiables hold (dark hero, teal leads / emerald structures / ember ≤5%, calm motion, mono caps labels); compare vs enclave-design `ui_kits/console`.
GATE: four-state render correct + visual review.

### phase-6 — selection↔chat binding, retire step-engage · CAP=8 · type/scope=feat(workspace)
GOAL: selection IS engagement.
UNITS:
- [ ] Drawflow `nodeSelected` → kind:'node'; blank-click → kind:'seed'. Right pane swaps thread.
- [ ] DELETE `composerEnterStepEngage`/`composerExitStepEngage`/`window._composerEngagedNodeId`/`#step-engage-badge` (and their legacy-bridge entries).
- [ ] Node thread sends route to `/api/workflows/test-step`.
VERIFY: spec test 1 (select A then B → isolated histories) + spec test 5 (engage globals gone; node select still routes to test-step).
GATE: selection-drives-chat proven; removed symbols absent from the bundle.

### phase-7 — seed→Promote + unified send (decision D1) · CAP=10 · type/scope=feat(workspace)
GOAL: one send path for both thread kinds; Promote binds a seed thread to a new node.
UNITS:
- [ ] `sendMessage(threadKey)`: seed → `/api/agents/{persona}/chat` (persona set) else `/v1/chat/completions`; node → `/api/workflows/test-step`.
- [ ] BACKEND (the ONLY allowed engine-adjacent edit): add optional `messages[]` to `POST /api/workflows/test-step` (router + Pydantic field, ADDITIVE — absent = today's single-shot). Client sends accumulated `messages[]` for node threads with >1 turn.
- [ ] Promote: create node (dfAddAgentAtCenter for persona else dfAddNodeFromTemplate) carrying seed persona/model/systemPrompt; re-key `threads['seed']`→`threads[newId]`; select it; fresh empty seed. Empty graph → node is DAG start; node already selected → append downstream +edge.
VERIFY: spec tests 2 & 3 + multi-turn test-step + single-shot fallback (field absent).
GATE: Promote + unified send + multi-turn test-step green.

### phase-8 — top-bar nav, retire the 3-menu tier · CAP=8 · type/scope=feat(nav)
GOAL: Composer · Runs · Library ▾ · Admin ▾ replace the flat tab list + Admin dropdown.
UNITS:
- [ ] `shell/nav.js` four destinations; non-Composer views reuse `.tab-content` swap + `#/<dest>` hash.
- [ ] Ensure EVERY `.tab-btn` carries `data-tab`; then delete `switchTab`'s onclick-string fallback (~index.html:7817 pre-split → shell/nav.js post-split).
- [ ] Update the 3 IA-drift e2e tests to the new IA (admin subnav rename; `#tab-dashboard` no longer the default-visible boot target — see session triage).
VERIFY: spec test 6 (all four reachable; `#/runs` etc. deep-link) + the 3 updated e2e tests.
GATE: nav + deep-links green; IA-drift e2e tests pass.

### phase-9 — retire the remaining old surfaces · CAP=6 · type/scope=refactor(workspace)
GOAL: delete the dead pre-rework chrome; shrink the bridge.
UNITS:
- [ ] Remove `agent-chat-dock`, `composer-workstream` + `ComposerWorkstream.switch`, `#df-config-popup`.
- [ ] Move Active-Run + History under Runs.
- [ ] Remove the now-dead symbols from `shell/legacy-bridge.js`; rerun `python scripts/capture_parity_goldens.py` (INTENTIONAL removals) + commit goldens.
VERIFY: dead surfaces absent from markup + JS; `pytest tests/parity -q` green; full e2e green.
GATE: no orphaned handlers; retired symbols absent from the bundle.

### phase-10 — behavioral suite + Runs legibility · CAP=10 · type/scope=test(e2e)
GOAL: durable coverage + make deep autonomous runs legible (Subsystem C seam).
UNITS:
- [ ] Land all 9 spec behavioral tests as committed coverage.
- [ ] `runs/` surfaces autonomous-run legibility: per-agent lanes, budget burn-down, dry-streak, vault-write log, resume state.
- [ ] Resolve/supersede the session's 14 known test-drifts: re-point the 10 `xsiam-detection-engineering` refs to a live catalog id (`xsiam-data-model-rules`); fix the thread-switcher isolation (clear `data/conversations` or don't assume a fresh counter).
VERIFY: 9/9 spec tests + `pytest tests/ui -q` + full `tests/playwright` (RATE_LIMIT_RPM=0) green.
GATE: full green suite + a11y + design-critique pass.
