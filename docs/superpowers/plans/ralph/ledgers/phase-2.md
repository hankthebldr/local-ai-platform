# phase-2 ledger — extract JS to ES modules

Card: CARDS.md → `## phase-2` · Harness: HARNESS.md · type/scope=refactor(js) · CAP=20
GOAL: relocate the `<script>` block into `js/**` per the plan's D2 map — ONE DOMAIN per
iteration — each namespace `export`ed and re-exposed via `shell/legacy-bridge.js`; then flip
`index.html` to `<script type="module" src="/static/js/main.js">`. Vendored libs (Drawflow,
d3, dagre, js-yaml) stay classic `<script defer>`.

consec_fail: 0

## Units (one domain per iteration, in order — DAG-safe, import floor first)
- [ ] U1 core/ — dom(esc/renderMarkdown), net(Net), ui(Toast/Confirm/EmptyState/ErrorPanel/Skeleton), theme, shortcuts, heartbeat, state(dfEditor/dfNodeData/dfNextId/graphConfig/graphData/graphSim/chatHistory/_chatModels/_connExpand/DfSeedSchema). Snapshot each of the 5 shadowed esc() (ApiKeys/Plugins/Skills/Cloud/Exports) before swapping to core/dom.esc; leave renderMarkdown's private esc ALONE.
- [ ] U2 shell/ — actions(Actions, 162 sites), router(hash), legacy-bridge (the must-bridge set — see Facts: now 63, not the card's 57).
- [ ] U3 library/ — workflow-index(+Kanban), agents(AgentGen), models(CatalogPage+CatalogModelsShare), skills, plugins, mcp, install-wizard, compare, asset-peek.
- [ ] U4 runs/ — runs(RunsTab), run-lens, workflow-memory, research-artifacts, research-flow. Keep RunsTab's private `_editor` Drawflow instance PRIVATE — never export it.
- [ ] U5 admin/ — menu, auth, api-keys, cloud, exports.
- [ ] U6 workspace-legacy/ — df* → canvas.js; relocate ComposerWorkstream/ComposerSplit/BootSequence/ScaffoldModal/Pins/Threads/AgentTuning as-is (retirement is Stage 2).
- [ ] U7 Flip `index.html` to the module entry; delete the extracted `<script>` body.

VERIFY (after EACH domain): `pytest tests/parity -q && pytest tests/ui -q && ENCLAVE_PLAYWRIGHT_BASE_URL=http://localhost:8001 pytest tests/playwright -m "not slow" -q`
GATE: every domain [x]; full parity + tests/ui + non-slow e2e green on the modular base.

## Facts (resolved pre-launch)
- **must_bridge is now 63, not 57.** The phase-0 re-baseline grew the inline-handler golden
  to 98 symbols / 63 `must_bridge` (was 57 before the 17 workspace adds). `legacy-bridge.js`
  MUST expose all 63 — `tests/parity` `test_post_split_symbols_are_window_bridged` un-skips
  the moment `api/static/js/` exists and hard-fails on any un-bridged handler symbol.
  Authoritative list: `tests/parity/golden/inline_handlers.json` → `must_bridge`.
- **Runtime floor:** `tests/parity/golden/window_globals.json` (314 app globals). The Stage-1
  runtime test `tests/playwright/test_parity_runtime.py` asserts `Object.keys(window) ⊇` this
  set + zero-console boot — it tightens automatically once modules exist.
- **Depends on phase-1 GATE PASSED** (CSS already in `app.css`); do not launch until phase-1
  is signed off, or two big `index.html` edits interleave.
- **Precedence:** if extraction surfaces an import cycle the D2 order didn't anticipate →
  `HALT: plan drift — <detail>` and STOP (do NOT improvise a reorder).
- Stage-1 boundary: after phase-2 + phase-3, STOP at the 🚦 PARITY GATE for human sign-off
  before Stage 2.

## Notes
