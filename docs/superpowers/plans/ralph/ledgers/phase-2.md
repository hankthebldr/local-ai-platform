# phase-2 ledger — extract JS to ES modules

Card: CARDS.md → `## phase-2` · Harness: HARNESS.md · type/scope=refactor(js) · CAP=20
GOAL: relocate the `<script>` block into `js/**` per the plan's D2 map — ONE DOMAIN per
iteration — each namespace `export`ed and re-exposed via `shell/legacy-bridge.js`; then flip
`index.html` to `<script type="module" src="/static/js/main.js">`. Vendored libs (Drawflow,
d3, dagre, js-yaml) stay classic `<script defer>`.

consec_fail: 0

## Units — FLIP-FIRST, CARVE-AFTER (operator sign-off 2026-07-07; supersedes the original order — see resolved HALT in Notes)
- [x] U1 flip — monolith `<script>` body (index.html 2420–18154) VERBATIM → `js/main.js` (`type="module"` entry); replace inline body with `<script type="module" src="/static/js/main.js">`; create `shell/legacy-bridge.js` re-exposing ALL 63 must-bridge as `window.*`; relocate/import the 7 component `<script id=...>` blocks (journey/pins/threads/library/runlens/components/flow5). Vendored libs stay classic `defer`. End state: whole app = one module graph, every inline `on*=` resolves.
- [ ] U2 core/ — carve OUT of main.js: dom(esc/renderMarkdown/renderMarkdownBasic), net(Net), ui(Toast/Confirm/EmptyState/ErrorPanel/Skeleton), theme, shortcuts, heartbeat, state(dfEditor/dfNodeData/dfNextId/graphConfig/graphData/graphSim/chatHistory/_chatModels/_connExpand/DfSeedSchema). Snapshot the 5 shadowed esc() (ApiKeys/Plugins/Skills/Cloud/Exports) before swapping to core/dom.esc; leave renderMarkdown's private esc ALONE.
  - U2 done incrementally, one module per commit (safer than one 7-module commit). Progress:
  - [x] core/dom.js — esc (497-site floor) + renderMarkdown (private esc left as-is) + renderMarkdownBasic; imported into main.js, esc/renderMarkdownBasic re-export the imports, window.renderMarkdown set early; 5 shadowed esc left untouched. VERIFY: parity 4 / ui 160 / non-slow e2e **14 failed 163 passed = baseline exactly (0 new)**.
  - [x] core/net.js — Net IIFE → core/net.js, imported + `window.Net = Net`. Fast VERIFY: parity 4 / ui 160 / runtime-parity boot 1 = 165 passed (clean boot, window superset intact).
  - [ ] core/ui.js · [ ] core/theme.js · [ ] core/shortcuts.js · [ ] core/heartbeat.js · [ ] core/state.js (df*/graph* are reassigned lexicals — needs a state-object accessor or stays via bridge; assess at that module).
- [ ] U3 shell/ — carve actions(Actions, 162 sites), router(hash); extend legacy-bridge as symbols move.
- [ ] U4 library/ — workflow-index(+Kanban), agents(AgentGen), models(CatalogPage+CatalogModelsShare), skills, plugins, mcp, install-wizard, compare, asset-peek.
- [ ] U5 runs/ — runs(RunsTab), run-lens, workflow-memory, research-artifacts, research-flow. Keep RunsTab's private `_editor` Drawflow instance PRIVATE — never export it.
- [ ] U6 admin/ — menu, auth, api-keys, cloud, exports.
- [ ] U7 workspace-legacy/ — df* → canvas.js; relocate ComposerWorkstream/ComposerSplit/BootSequence/ScaffoldModal/Pins/Threads/AgentTuning as-is (retirement is Stage 2).
- [ ] U8 finalize — main.js remainder = imports + wiring only; confirm extracted `<script>` body fully gone from index.html; D2 tree complete.

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
- U1 (iter 2, flip): monolith `<script>` (index.html 2420–18154) + the 7 component `<script id=enclave-*-js>` blocks concatenated VERBATIM into `js/main.js` as one `type="module"`; vendored libs (Drawflow/d3/dagre/jsyaml) aliased into module scope (`const {…}=window`). index.html 18955→2474 lines; entry `<script type="module" src="/static/js/shell/legacy-bridge.js">`. `shell/legacy-bridge.js` imports main.js and re-exposes the surface on window.
  - **Bridge = 245 symbols** (not the card's "63"): the module strips the 175 classic auto-global `function`s from window too, so the floor is all 313 golden lexicals → 238 plain `window.X = app.X` (greppable for the static must-bridge test) + **7 live-getter state vars** (chatHistory/_agentHistory/dfEditor/dfNodeData/dfNextId/graphData/graphSim — reassigned `let`/`const`; `Object.defineProperty(get:()=>app.X)` so window tracks reassignment = classic global-lexical semantics). graphConfig/_connExpand/_chatModels already `window.`-props (survive).
  - **1 code fix:** removed a byte-identical duplicate `function _renderResearchInFlight` (index.html 5447-5461 ≡ 5463-5477) — harmless under classic hoisting, a module dup-decl SyntaxError. Behaviour-neutral. Preflight: `node --check` on both files; 0 `with`/top-level-`this`/octal/implicit-global hazards.
  - **Test-harness updates (refactor fallout, not behaviour):** `tests/ui/conftest.py` now appends the served `js/**` corpus (wrapped in `<script>`, main.js has 0 literal `</script>`) to `index_html_text` so JS-behaviour assertions resolve; `index_soup` stays DOM-only. 6 `test_*` re-anchored off the now-removed `<script id=enclave-*-js>` wrappers onto the moved code (the `window.X` assertions already prove module presence).
  - **VERIFY:** `pytest tests/parity`=4 passed; `tests/ui`=160 passed; runtime parity (⊇314 window floor + 0 console errors on boot)=passed; non-slow e2e=**14 failed / 163 passed**, and **all 14 failures are baseline-proven PRE-EXISTING** (ran each on the untouched pre-U1 monolith — identical failures): 8 `xsiam-detection-engineering` 404 + 1 thread-switcher counter (`Thread 268`) = the known data-drift; 5 `Page.click/wait` timeouts (composer-workstream demo, full-product demo, admin×2, agent-chat-persists). The 9 real U1 regressions (chatHistory×7, dfEditor, _agentHistory `page.evaluate` ReferenceErrors) were FIXED by the live-getter bridge. **U1 introduces ZERO new failures.**
- **BASELINE for U2–U8:** the pre-split monolith already fails these 14 non-slow e2e tests (session's known drifts; phase-10 fixes them). "e2e green" for the carve units = failure set ⊆ these 14, no NEW names. Full list: e2e_u1_postfix.txt in job tmp.
- HALT RESOLVED (2026-07-07, operator approved flip-first): units above rewritten to flip-first/carve-after; CARDS.md ## phase-2 updated to match. Loop RESUMES on the new U1. Original proof retained below for the record.
- [was] HALT: plan drift — the card's unit ORDER (extract domains U1–U6 → flip U7; legacy-bridge at U2) is not mechanically realizable with the card's own "parity green after EACH domain". Proof (all verified iter 1, server up):
  - Monolith `<script>` = index.html **2420–18154** (one classic script). `esc(` appears **710×**; the plan pins esc at 497 import sites. `core/` symbols are referenced pervasively.
  - **U1 is RED both ways.** (a) Remove `core/` from the classic monolith but DON'T flip index.html to a module loader (flip is U7) → 710+ call-sites hit undefined `esc/Net/Toast/...` → console-error storm, e2e RED. (b) Keep the functions in the monolith (dead-copy the modules) → `api/static/js/` now exists → `tests/parity::test_post_split_symbols_are_window_bridged` UN-SKIPS (skipif `not JS_DIR.is_dir()`) and requires **all 63** must-bridge as `window.X=` in the corpus; **0** are bridged today → parity RED.
  - Root cause: an ES module can't run without the module entry, and the classic monolith can't lose symbols it still calls. So the flip to `<script type="module">` and all 63 `legacy-bridge.js` window-bridges must land at the FIRST domain iteration — the REVERSE of the card's U7/U2 placement.
  - Guardrail (Facts above + HARNESS): "do NOT improvise a reorder" → HALTED for operator sign-off.
- RECOMMENDED resolution (needs Henry's OK — changes the card's unit order): adopt **flip-first, carve-after**:
  - New U1 = "flip + bridge": move the monolith body (2420–18154) verbatim into `js/main.js` as the module entry (temp remainder), add `<script type="module" src="/static/js/main.js">`, create `js/shell/legacy-bridge.js` bridging all 63 must-bridge `window.*`, keep vendored libs classic `defer`. VERIFY green here = the whole app runs as one module with parity intact.
  - Then U2..Un = carve one domain per iteration OUT of `js/main.js` into `core/ → shell/ → library/ → runs/ → admin/ → workspace-legacy/`, each `export` + bridge, VERIFY per domain.
  - Final U = remainder in `main.js` is empty → the "delete the extracted <script> body" clause is satisfied.
  - Boot-ordering cleanup (parse-time side effects → `boot()`) stays deferred to phase-3 per D3, as written.
- consec_fail: 0 (this is a design/ordering HALT, not a build failure). Loop re-feeds cheaply until `/cancel-ralph` or max-iterations; do NOT emit the promise.
