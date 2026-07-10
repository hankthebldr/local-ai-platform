# Composer agentic revamp — design

**Date:** 2026-07-10 · **Branch:** `feat/composer-workspace` · **Status:** approved (operator, in-chat)
**Provenance:** 15-agent design workflow (7 dimension readers → 5 cluster designers → synthesis → 2 adversarial critics). Blocker + major critiques folded in below.

## Overview

Page-by-page revamp of Build > Composer into an agentic-pattern-led node workflow builder. Strictly additive, four hard constraints:

1. **Engine frozen** — `api/services/workflow_engine.py`, `step_executor.py`, `api/models/workflow_models.py` are read-only. The closed 8-kind Literal `llm|parallel|loop|a2a|orchestrator|consolidate|ralph|code` is the only vocabulary the canvas may emit. (Note: `workflow_compiler.py` named in older docs does not exist; `WorkflowDefinition(**data)` *is* the compiler, engine `validate()` is the wiring pass.)
2. **In-place on current df\*** — no `df* → canvas.js` state-object carve (FE3 stays deferred).
3. **No new inline `on*=` handlers, no new window globals** — all new wiring via `Actions` data-action delegation (`js/shell/actions.js`), registered in main.js's grouped blocks. Legacy inline handlers stay as pre-existing debt.
4. **Parity preserved** — `tests/parity`, `tests/ui`, non-slow e2e at the 14-failure baseline. No existing single-click contract, tab, endpoint, or exported symbol changes.

Line anchors cited below are approximate (drift ±30 lines); verify at edit time.

## Conceptual model: Agent vs Task vs Pattern vs Seed

- **AGENT = model + tools + context** — *who* does the work. Existing Agents bench (`/api/agents`). Asks #3, #6.
- **TASK = agentic instructions/hooks/strategy** — *how* the agent behaves and processes the particular output. The bench currently mislabeled "Roles" (`data-bench="steps"`). Relabel button text only; bench key `steps` stays. `dfStepTemplates.role` values (reasoning/coding/fast) are LLM-routing classes, NOT the Task concept — do not conflate. Asks #3, #7. ("Hooks" here = the instruction blocks that architect behavior — engine grounding is `system_prompt`/`prompt`/`role`; the inspector labels them "instructions".)
- **PATTERN = deployment topology** — *in what shape* the work executes. New 6th "Patterns" bench. SIMPLE pattern = one node emitting one engine kind. COMPLEX pattern = scaffolds a pre-wired, editable sub-DAG. Asks #4, #11.
- **SEED = the editable starting node** — holds the user query + seed schema; feeds `seed.<key>` into step one. Not an engine step: compiles to `context.inputs` + run-time seed payload. Asks #2, #8.

**Composition rule (how the axes combine on one node):** a Pattern drop scaffolds topology with *placeholder personas*; dropping a Task onto a node (or sub-step leaf) fills its instruction; the node config panel always shows both its Task (instruction) and its Pattern/kind. Worked example: drop **Research fan-out** → index→3 subagents→gather appear wired → drop the **Analyst** task onto each subagent leaf → double-click **seed** → type the query → **Run**.

## Pattern → engine-kind mapping (closed set, valid-by-construction)

Every preset must round-trip `WorkflowDefinition(**data)` in tests — the frozen model is the validator, not a bespoke one.

| Pattern card | Type | Kind | Invariants to honor |
|---|---|---|---|
| LLM step | SIMPLE | `llm` | exactly one of `system_prompt`/`prompt`; `outputs:['text']` |
| Orchestrator (dynamic) | SIMPLE | `orchestrator` | ships with **1 valid pre-filled worker** (validator requires ≥1); every worker input must be `seed.*` |
| Remote agent | SIMPLE | `a2a` | `agent_card_url`+`skill`; no model/role/prompt |
| Consolidate (learn) | SIMPLE | `consolidate` | `consolidate:{target,target_name,system_prompt}` |
| Code sandbox | SIMPLE | `code` | `code:{language,source:'inline',code}`; id must not contain `/ \ ..` |
| Ralph loop | COMPLEX | `ralph` | body = plan→execute→verify→consolidate; `ralph:{journal_path,halt}`; every parent output produced by some body step. Budget-preset toggle covers "long-running automation" (same kind — one card, two presets, no duplicate card) |
| Research fan-out | COMPLEX | `parallel` | index(llm) → parallel ≥2 branches → gather; **gather.outputs set-equals parent.outputs**. Sharded variant **cut from v1** (requires exactly-1-branch + `sharder` + `shard_input` semantics; documented follow-up) |
| TDD loop | COMPLEX | `loop` | body = write→test(`code`)→critic; `until:{type:'gate',gate}`; **last body step must produce every loop output** — scaffold makes the critic the last step and carry the loop outputs |

Cross-field exclusivity: a `parallel/loop/ralph/orchestrator/a2a/consolidate` node never carries `system_prompt`/`prompt`. The composite serializer keys emission off `data.kind`.

## Per-area design

### BU1 — Task reframe + bench labels
Button text "Roles"→"Task" (`index.html` ~518); hint updates (Task bench: "Drag a Task onto the canvas…"; Agents bench hint names "model, tools, and context"). `data-bench="steps"`, `#bench-steps`, `composerSwitchBench('steps')` untouched. Register `Actions.click({'bench.switch'})` for the new Patterns tab wiring (BU4); legacy 5 inline tab onclicks stay.

### BU2 — Composer centering + canvas fit
`.composer-split { max-width:1440px; margin-inline:auto; }` centers rail+canvas on wide monitors (ask #1). The previously-theorized min-height "source-order trap" was **disproven by the critic** (among `!important` rules, specificity 0,2,0 at ~:5232 already beats 0,1,0 at ~:5481 inside the split): re-derive any canvas-fit defect empirically in the live DOM before editing; if the panel sits outside `.composer-split` in some mode, scope the `:5481` floor to that context. Do not add a third `!important` layer.

### BU3 — Editable seed node + unified double-click config
- `dfAddSeedNode(x,y)` mirrors `dfAddNodeFromTemplate`: `data={id:'seed',name:'Seed',is_seed:true,query:'',seed_schema:[{key,description}],outputs:[keys],inputs:[]}`; `dfEditor.addNode('__seed__',0,1,…)`; register in `dfNodeData`. Exactly one seed; auto-spawn idempotently on empty-canvas compose mode.
- `dfAddAnchors` skips the decorative `__start__` ghost when a real seed exists. `DfSeedSchema` remains a synced mirror (Library round-trip), superseded as the editing surface.
- **Unified dblclick-to-edit for ALL nodes:** node bodies get `data-action="composer.edit-node"`; `Actions.on('dblclick',…)` resolves id via `closest('.drawflow-node')` → `dfRenderConfigPanel` + `openStepConfigPopup`. Single-click `nodeSelected` behavior unchanged (parity).
- `dfRenderConfigPanel` branches `if(data.is_seed) return dfRenderSeedConfig(nodeId)` (query textarea + key/description rows) → both `#df-config-panel` and popup body.
- **Serialization:** `dfExportYaml` skips seed nodes in the step loop; `seed_schema` → `context.inputs`; a connection from seed serializes as `seed.<key>` inputs on the target step, never `depends_on:[seed]`. Seed values become the run payload read by `dfRunWorkflowLive`; the `#wf-seed` textarea path stays working as fallback.

### BU4 — Patterns bench + scaffolds + composite serializer (keystone)
6th tab `data-bench="patterns"` (data-action wired) + `#bench-patterns`/`#patterns-palette`. `dfPatternTemplates` (single source of truth, near `dfStepTemplates`) renders cards with a SIMPLE/COMPLEX badge via `dfInitPatterns()`. Cards reuse `benchDrag` with MIME `application/df-pattern`. Canvas drop handler gains a `df-pattern` branch → `dfAddPatternFromTemplate` (SIMPLE: one node stamping `dfNodeData[id].kind` + config block) / `dfScaffoldPattern` (COMPLEX: wired sub-DAG via `dfAddNodeFromTemplate`, placeholder personas per the composition rule). Nodes carry `data.pattern` + `data.complexity`. **This unit owns the `dfNodeData → WorkflowDefinition` composite serializer** (kind-keyed emission, exclusivity, output-contract invariants, orchestrator worker inputs default `seed.*`). Tests round-trip every preset through `WorkflowDefinition(**dict)` (venv pytest, non-engine test file).

### BU5 — Sidebar ↔ bottom polymorphic inspector
Bottom Step Config pane becomes selection-source-driven (asks #5, #6, #7). `ComposerWorkstream` gains `inspectAgent/inspectCapability/inspectTemplate` + `_renderInspector({title,kind,html})` → writes read-only HTML into `#df-config-panel` only (never auto-opens the popup), stamps `#ws-step-meta` with `data-inspect-kind`. Triggers are hover/focus (+click for cap cards), never fighting click-to-add/drag: Agents → model+tools+context; Task templates → instructions + the kind they compile to; skills/plugins/MCP → capability detail. **Data passing fix (critic):** the hover handlers live in main.js where `_benchAgents`/`_benchCaps` caches live, and *pass the resolved object* to `ComposerWorkstream.inspect*(obj)` — no new cross-module state, no globals. Debounced mouseover.

### BU6 — Logs workstream tab
4th tab (ask #9): `.workstream-tab[data-ws="logs"]` wired via `data-action="ws.switch"` (existing 3 tabs keep their inline onclicks); `#ws-pane-logs`; `panes[]` + `switchTab` branch + `_refreshLogs()` in `composer-workstream.js`. Data source: `GET /api/workflows/runs/{run_id}` (per-step I/O lives in run.json; the SSE stream carries no prompt/output text). Per StepResult render: **input** = `rendered_system_prompt`/`rendered_prompt` (click-to-expand; "prompt not captured" fallback), **output** = `run.context.workspace[step_id]`, **strategy strip** = `mcp_calls`/`plugin_tools_called`/`skills_activated` (name·duration·status, labeled metadata-only). Expanders via `Actions.click('wslogs.output-toggle')`. Existing 1200 ms poller re-renders when active. Tool-call arg/body drill-down **out of v1** (never persisted); optional sidecar (`tool_io_capture.py` + `GET /runs/{id}/tool-io`) documented, not built.

### BU7 — Segmented progress bar + run signals
`dfApplyRunState` (sole sanctioned `#df-run-progress` writer) paints a segmented linear bar — one segment per step: green (completed) / red (failed) / pulse (running) / amber (skipped/deferred) (ask #10). Logs pane header gains an actionable signal line: `N green · red (step X: <error>) · issue (step Y: seed.foo unresolved)`; each chip is `data-action="logs.focus-step"` → focuses the offending step's config, **and seed-sourced issues route to the seed node's config** (critic fix), closing the edit-seed→run→watch→refine loop. Ralph/loop non-convergence surfaces via `max_iterations`/`goal_gate` events.

### BU8a — Loop safety rails
`dfRenderConfigPanel` renders a "Safety rails" section for `kind:ralph`/`kind:loop` nodes: `halt_file`, the four `RalphHalt` budget caps, `goal_gate`/`until.gate` (client-side validation against the `evaluate_gate` grammar in `engine_executors/loop.py`). Pre-filled from BU4 presets; edits via `Actions.change/input('composer.ralph-rail-edit')` → `dfNodeData`. Copy must not overpromise: `halt_file` has no HTTP brake; the live stop is `POST /runs/{run_id}/cancel`. Ask #11.

### BU8b — Loop wrap (Schedule cut from v1)
Toolbar affordance `composer.loop-wrap`: wraps the current workflow in a real, runnable ralph/loop scaffold (compiles, runs today). **Schedule (recurring cron) is cut from v1** — no host-side scheduler backend exists, and a descriptor nothing executes is a half-baked control. Follow-up: minimal scheduler service + router (non-engine). Ask #10 goal, operator-approved cut.

### BU8c — Feasibility signal band
`#composer-signal-band` fetches `GET /api/workflows/{id}/schedule-preview` and paints green (no issues/notes) / red (`feasibility_issues`) / issue (`notes`: deadlock/all-deferred) / **unknown**. Tri-state fix (critic): "unknown" is computed **locally from `dfNodeData` est_size_gb presence** (the preview payload cannot distinguish all-sizes-absent from genuinely-green) — never fake-green. Requires a saved `workflow_id`.

### BU8d — Guidance: tooltips + starter suggestions
Ask #12, all three affordances: (a) hover **tooltips** on pattern cards (title/desc from `dfPatternTemplates`); (b) a **"suggest a starter workflow"** affordance instantiating a full pre-built best-practice starter (Ralph / TDD / Research — reuses BU4 scaffolds end-to-end incl. seed + tasks); (c) a dismissible **best-practice** card (`dfWorkflowTips`: "give ralph a goal_gate", "cap max_iterations", "gather.outputs must equal parent outputs").

## Change inventory

- `api/static/index.html` — bench labels/hints; Patterns tab + pane; Logs tab + pane; signal band; loop-wrap toolbar button; guidance card.
- `api/static/js/main.js` — seed node fns, dblclick action, `dfPatternTemplates`/`dfInitPatterns`/`dfAddPatternFromTemplate`/`dfScaffoldPattern`, composite serializer, `dfExportYaml` seed guard, `df-pattern` drop branch, segmented bar in `dfApplyRunState`, safety rails in `dfRenderConfigPanel`, inspector hover handlers, signal/guidance handlers. All module-scoped; Actions registrations grouped.
- `api/static/js/workspace-legacy/composer-workstream.js` — `panes[]` + Logs branch + `_refreshLogs`; `inspect*` + `_renderInspector`.
- `api/static/js/workspace-legacy/df-seed-schema.js` — stays as synced mirror.
- `api/static/css/app.css` — centering; `.df-pattern-badge`; segmented-bar; signal-band states. 4th workstream tab inherits existing styling.
- Backend — none in v1 (Logs reads existing run.json; sidecar + scheduler are named follow-ups).

## data-action inventory (zero new globals)

`bench.switch` · `bench.drag` (reused, new MIME `application/df-pattern`) · `bench.inspect-template` · `bench.add-agent` (reused +hover/focus) · `composer.edit-node` (dblclick) · `composer.seed-add-key`/`seed-remove-key`/`seed-save` · `ws.switch` · `wslogs.output-toggle` · `logs.focus-step` · `composer.loop-wrap` · `composer.ralph-rail-edit` · `composer.best-practice` · `composer.suggest-starter`.

## Verification per unit

Fast loop after every unit: `pytest tests/parity tests/ui tests/playwright/test_parity_runtime.py` (~5 s). Serializer presets: dedicated pytest round-tripping `WorkflowDefinition(**data)`. Full non-slow e2e once at the end: failure set ⊆ the known 14-failure baseline, no new names. New e2e coverage: seed dblclick-edit, pattern drop→scaffold, Logs tab render, inspector coupling.

## Deferred (named follow-ups, not half-baked stubs)

- FE3 df\*→canvas.js state-object carve (~220 sites).
- Sharded research fan-out preset (exactly-1-branch + sharder + shard_input semantics).
- Tool-call I/O sidecar (`tool_io_capture.py` + `GET /runs/{id}/tool-io`).
- Host-side recurring scheduler (service + router) to un-cut the Schedule affordance.
