---
title: Enclave Master Roadmap & State-of-the-Effort Audit
date: 2026-07-09
status: master-roadmap
branch: feat/composer-workspace
reconciles:
  - 2026-07-09-composer-workflow-builder-design.md
  - 2026-07-09-unified-object-model-library-alignment.md
  - 2026-07-09-composer-chat-separation-implementation.md
supersedes-direction: three independent proposed plans → one sequenced build
---

# Enclave Master Roadmap & State-of-the-Effort Audit

> **What this is.** The capstone that folds the three committed design docs into
> **one dependency-ordered build plan**, gates it against a code-review of what
> already shipped, and names the single next slice. It is the source of truth
> for sequencing; the three design docs remain the source of truth for *detail*.

---

## 1. Executive summary

The effort has **shipped a working substrate** on `feat/composer-workspace` and
**planned the surfaces** that sit on top of it. Three things are real and
committed: a **fusion runtime** (model registry + durable Workspace + resumable
WorkspaceIndex + LangGraph fusion agents), a **frontend ES-module carve**
(`index.html` monolith split into 37 modules; `main.js` 16,707 → 9,271 lines),
and a **left-rail app-frame** (CSS-only over the frozen `switchTab`/parity
substrate). Three things are designed but unbuilt: the **composer-workflow
builder**, the **unified object model / Library alignment**, and the
**four-surface Composer/Chat/Research/Context separation** — and they *overlap*,
touching the same `main.js` center.

**The shipped code is sound at the unit level but carries one CRITICAL and one
HIGH security defect** in the fusion runtime (an unauthenticated glob
path-traversal that reads files outside the workspace root, and a `delete("")`
that `rmtree`s the whole bound directory). These must be closed before the object
model surfaces Workspaces as a first-class Library object.

**Forward strategy (one line):** adopt the **separation plan as the serial
spine** (Chat extraction → canvas-dominant Composer → Research → Context), run
the **object-model track fully in parallel** on the already-clean `asset-peek.js`
module + net-new backend, gate both with **two off-spine hardening tracks**
(fusion-security, CSS frame/a11y), and **join once at the end** where the
Composer palette becomes the object Library.

**Reconciliation of the three plans:**

| Plan | Role in the master | Resolution |
|---|---|---|
| `composer-chat-separation` | **SPINE** (authoritative direction) | Four surfaces; P0 = Chat extraction. |
| `unified-object-model` | **PARALLEL TRACK** (reuse foundation) | Prompts + AssetPeek registry + reference_index on clean ground; joins at the palette. |
| `composer-workflow-builder` | **FEATURE SOURCE** (demoted) | Its single-surface right-pane selection machine is **KILLED**; `#df-config-popup` **stays floating** (separation A16). Its composite/crystallize/workspace-bench ideas feed later phases. |

---

## 2. State-of-the-effort audit

| Area | Kind | State | Quality | Top gaps |
|---|---|---|---|---|
| **Fusion runtime** (C1 model registry · C2 Workspace · C3 WorkspaceIndex · C4 LangGraph loop) | shipped | Committed + wired (`main.py:316,341`); 25/25 tests pass. Durable named dir binding, resumable worklist, MOC render, runner-aware `/api/models`. | Clean, small, well-documented; meaningful tests (traversal, quota, crash-resume, registry persistence). **But** content-file writes are non-atomic while the index is atomic; no concurrency control (claim race); `requeue_stale` has no age threshold. | **Arbitrary-root bind is not a sandbox** (auth off by default = host-wide file access); `make` overwrites silently (no backup/diff); **the flagship `research_graph` bypasses C2/C3** and writes the vault directly — fusion is half-wired. |
| **Frontend carve** (phase-2 ES-module split) | shipped | Real + committed; 37 modules under `core/library/runs/admin/shell/workspace-legacy/`; `main.js` 16,707 → 9,271. 47 `df*` + ~150 orchestration fns + boot remain. | Two tiers: `core/` + `library/asset-peek.js` are production-grade cohesive modules; **but the carve rerouted the dependency graph through `window`** — boundaries are enforced only by a 258-line hand-maintained `legacy-bridge.js`, not statically. | `df*` canvas subsystem un-carvable without the deferred **state-object rewrite**; the **~150 orchestration fns (chat/composer/graph) are the exact surfaces the separation plan touches**, still monolithic; boot not consolidated; latent broken onclicks (`InstallWizard`/`Compare`) in `asset-peek.js`. |
| **UI frame / nav** (left-rail + app-frame) | shipped | CSS-only overlay on `.tab-nav`; `<body>` grid at ≥960px; only `#main-content` scrolls. Build/Operate/Library + Admin pinned. | Deliberately low-risk (no `switchTab`/DOM/JS change → parity-safe); frame-fit rows + gutter fix tested. **But** magic-number frame math, no a11y tab semantics, untested at planned density. | `min-height: calc(100vh - 190px)` hardcodes chrome height (Admin clips off-screen when it grows); **orphaned `#tab-research` panel** (no rail button); tablist illegally holds non-tab children; Library already 6 flat items; Context is mis-homed (RAG **and** Role-Library double duty). |
| **The three plans** (composer · object-model · separation) | planned | 3 committed `status: proposed` docs; nothing implemented. Each carries an adversarial feasibility review with per-line evidence. | Unusually **code-grounded and honest** — spot-checks confirm the anchors (`setMode` 4 callers + def, `dfNodeData` let-scoped at `main.js:4773`, `#agent-chat-dock@612`). Neither production-ready. | No unified roadmap (this doc); **two P0s race** on the same DOM region; `#df-config-popup` fate answered oppositely; composite serialization (`dfExportYaml` v2) is **homeless**; P-numbering clashes. |
| **Backend engine surface** (31 routers) | mixed | The four planned surfaces map to real endpoints today (workflows/composer/agents/graph/workspaces). **Frozen boundary is verified clean** — engine reachable only via `/api/workflows/run` + `/run-async`. | Sound + consistent; `test-step` takes a step *definition* so unsaved edits flow through unmodified; save is traversal-hardened + Pydantic round-tripped. | **`/api/prompts/*` entirely missing** (only read-only `roles.py`); **`/api/objects/*` façade + `edges` missing**; persona chat is non-streaming; no workflow `DELETE`; **auth asymmetry** (open workflow/agent/composer vs master-key-gated skills/plugins); "Context" naming collision (`/api/context` is *conversation* context, not run observability). |

---

## 3. Code-review findings — quality gate on shipped code

Real defects in committed code, **most-severe first**. Each is assigned an
owning phase so the fix ships inside the work that touches the file (see §4).

| # | Sev | File:line | Category | Defect | Fix | Owner |
|---|---|---|---|---|---|---|
| 1 | **CRITICAL** | `api/services/workspace.py:156` | path-traversal | Caller-controlled `?glob=../..` bypasses `resolve()` in `search()`/`list()`; `GET /workspaces/{n}/search?glob=../../etc/hostname` **returns file contents outside root** (auth off by default). | Apply `resolve()` to every glob result; reject `..`/absolute globs → 400. | **F0** |
| 2 | **HIGH** | `api/services/workspace.py:235` | correctness | `delete("")`/`delete(".")` resolves to root and `shutil.rmtree`s the **entire bound workspace** (vault/repo). | Reject any path that resolves to `self.root`. | **F0** |
| 3 | **MEDIUM** | `api/services/workspace_index.py:135` | race-condition | `next_pending` claim is not atomic across requests; two concurrent `/next` calls (the C4 fan-out, and the 1.3.0 parallel-DAG direction) **double-claim** the same item. | File-lock the read-modify-write claim; add age threshold to `requeue_stale`. | **F0** |
| 4 | **MEDIUM** | `api/static/css/app.css:6467` | responsive-overflow | Rail `min-height: calc(100vh - 190px)` + `body{overflow:hidden}` **clips Admin off-screen** at 125% text scale / wrapped header (budget ~6px). Admin (System/Cloud/Exports/Sign-out) becomes unreachable. | CSS var tied to actual header+footer height. | **UIFRAME** |
| 5 | LOW | `api/services/workspace.py:201` | correctness | `edit(count=-1)` replaces **all** occurrences but reports `-1`; also skips `_check_extension`. | Clamp `count>=0`; run `_check_extension` in `edit()`. | **F0** |
| 6 | LOW | `api/services/workspace_index.py:164` | error-handling | Desynced `order`/`items` (hand-edit / partial write) raises uncaught `KeyError` → HTTP 500 instead of the intended "corrupt index must not brick the loop". | Tolerate desync in `_load()`. | **F0** |
| 7 | LOW | `api/static/css/app.css:6446` | stacking-context | `overflow-y:auto` makes the rail a clip + stacking container; the Admin drop-UP menu can't float over the canvas on short viewports. | Let the menu escape the rail box (fixed/portal) or widen the gutter. | **UIFRAME** |
| 8 | LOW | `api/static/css/app.css:6447` | fragile-selector | Frame grid keyed on `body > .tab-nav/#main-content/.footer` direct-child selectors; silently breaks if the carve wraps them. | Document the coupling at the selector site; robustify. | **UIFRAME** |
| 9 | LOW | `api/static/js/runs/runs-tab.js:1305` | correctness | SSE `step.completed` writes `duration_ms`; every render site reads `duration_seconds` → live step duration shows `?` until the poll corrects it. | Read/normalize `duration_ms` at the render sites. | **S4** |
| 10 | LOW | `api/static/js/shell/actions.js:19` | correctness | Delegation uses capture only for `toggle`, not `focus` — a latent trap in the core primitive (`focus` doesn't bubble → future handler silently no-ops). | `capture: type==='toggle'||'focus'||'blur'`. | **FE3** |
| 11 | LOW | `api/static/js/runs/runs-tab.js:3` (+ `main.js:6`) | eval-fragility | Vendor globals (`Drawflow/dagre/d3/jsyaml`) destructured off `window` at module-eval; correct only while `index.html` keeps them as `defer` classic scripts ahead of the module tag. | Guard or lazy-access at first use. | **FE3** |
| — | (also) | `asset-peek.js` | latent-broken | `InstallWizard.open()` / `Compare.add()` referenced but neither bridged nor defined → `ReferenceError` on click. | Fix opportunistically. | **OM0** |

**Gate rule:** every phase that touches an owning file closes its assigned
defect in the same commit. No shipped defect is carried past the phase that next
edits its file.

---

## 4. The unified master roadmap

Fourteen phases across four tracks. The **spine** is serial because every one of
its phases mutates the monolithic `main.js` + `index.html` (the carve left this
center un-modularized). Three **parallel tracks** run in isolated worktrees and
converge late.

> **Two fixes applied to the winning roadmap** (per the judge's review):
> **(a)** S3 (Research) is **decoupled** from the object-model track — it needs
> the R1 Role-Library fix + governed workspace, not Prompts or `edges`.
> **(b)** FE3 (the big state-object rewrite) **no longer gates S1** — S1's
> subtraction slice runs on the current lexical state; FE3 gates only the deep
> canvas work it truly blocks (CS, OM3).
> **Plus:** the homeless `dfExportYaml` composite serializer is given its own
> gated phase (**CS**); the OM2 mega-bucket is split (IA reorg carved out); the
> auth-asymmetry decision is owned (**OM2**, pending operator sign-off D2).

### 4.1 Phase table

| Phase | Delivers | Depends on | Parallel? | Key files | Regression gate |
|---|---|---|---|---|---|
| **F0** — Fusion-security hardening | Closes CR #1,2,3,5,6; permitted-root allowlist + read-only-default; atomic content writes (tmp+replace). Makes "local sandbox" truthful; unblocks parallel-DAG on the index. | — | **yes** (backend) | `workspace.py`, `workspace_index.py`, `workspaces.py`, `tests/test_workspace*.py` | 25 + new traversal/atomicity/concurrency/root-scope tests; `glob=../` → 400; delete-root rejected; 2 concurrent `/next` → 2 distinct items; parity 14 (backend-only). |
| **UIFRAME** — Frame-fit + tablist a11y | Closes CR #4,7,8; CSS var frame math; hardens rail for ~12-item density; `role=tab`/`aria-selected`/`role=tabpanel`; documents the grid child-selector coupling. | — | **yes** (CSS) | `app.css`, `index.html` | Admin reachable at 12 buttons / 125% scale / <700px height; modal beats z-30 rail; a11y validates; parity 14. |
| **OM0** — AssetPeek kind-registry + Prompts vertical | `EntityMeta` envelope, `object_registry`, `prompt_service`/`prompts.py` (seeded from `roles.py`); `asset-peek.js` flat switch → kind→renderer registry; **re-register model/agent/plugin UNCHANGED** as the zero-regression proof; Prompts library end-to-end. Fixes `asset-peek.js` broken onclicks. | — | **yes** (backend + clean module) | `prompt_service.py`, `prompts.py`, `prompt_models.py`, `entity_meta.py`, `object_registry.py`, `library/asset-peek.js`, `library/object-shell.js`, `library/entity-card.js` | model/agent/plugin peek renders **identically** pre/post; Prompt CRUD + `/render`; parity 14. |
| **OM1** — reference_index + edges + delete-safety | `reference_index.py` (generalized from `_workflows_referencing`) + `GET /api/objects/{kind}/{id}/edges`; used-by chips + 409+dependents delete-guard across Library/Composer. | OM0 | **yes** | `reference_index.py`, `data/registry/graph.json`, `library/asset-peek.js` | `edges` answers used-by for agent+prompt; delete on referenced → 409+dependents; parity 14. |
| **OM2** — Remaining kinds onto shell + `/api/objects` façade + workflow DELETE + auth | Skill/MCP/Workflow/Project/Model through one `ObjectShell`+AssetPeek (retire `#mcp-detail`, `WorkflowIndex.deepDive`, `SkillsDiscover.openDetail`); net-new `DELETE /api/workflows/{id}`; model overlay store; **owns the auth-uniformity change** (require_master_key) pending D2. | OM1 | **yes** | `object_registry.py`, `objects.py`, `workflows.py`, `data/registry/overlay/model`, `library/asset-peek.js` | each kind browses via `ObjectShell` with no bespoke-modal regression; `DELETE` guarded by `edges`; parity 14. |
| **S0** — Chat extraction (proof slice) | Lift `#agent-chat-dock` (612-788) verbatim into new `#tab-chat`; repoint 4 `setMode('canvas')` callers → `switchTab('dashboard')`; neutralize `setMode('chat')`; `ChatView.init()`; one Build-rail button. **Chat JS stays in `main.js` module scope** → lexical `dfNodeData` test-step bridge survives a DOM-only move. No Context/Research/Roles change (reversible). | — | no (spine) | `index.html`, `main.js`, `composer-split.js`, `boot-sequence.js`, `app.css` | agent chat persists across tabs; node-select → test-step → model write-back works; **cold-start**: open Chat before Composer → `#agent-select` populates; parity 14 (**diff the set**); no new window globals. |
| **S1** — Composer completion (canvas-dominant) | Delete ComposerSplit mode buttons/divider; canvas fills freed space. **`#df-config-popup` STAYS floating** (A16); the composer doc's right-pane selection machine is **KILLED, not built**. | S0 | no (spine) | `composer-split.js`, `composer-view.js`, `index.html`, `app.css` | floating node-config still opens/edits/writes back; canvas full-bleed; the 5 composer/agent-chat click-timeout baseline failures don't **mask** a new regression (diff the failing set); parity 14. |
| **S2** — Chat config-header + pivots | Config-header persona/tool/skill/hook/context loader (**reads OM0 object endpoints**); pivots (talk-in-Chat → Promote / jump-to-Composer). | S0 *(reads OM0)* | no (spine; region-disjoint from S1) | `main.js`/`chat-view.js`, `index.html`, `agents.py` | config-header swaps persona/model and chat responds (`model_fallback` banner intact); no new inline `on*=`; parity 14. |
| **S3** — Research promotion + governed workspace + **R1 fix** | Un-hide `#tab-research` + rail button; relocate RAG/roles into it; **migrate `research_graph` off the ad-hoc vault writer onto `workspace_tools`** (governed C2/C3 from F0). **R1 GATE:** statically author Role-Library markup in `#tab-research` and relocate `loadRoles` *before* deleting the relocator. | **S0, F0, UIFRAME** | no (spine) | `index.html`, `main.js`, `~/projects/langgraph-vllm/research_graph.py`, `research_tools.py`, `app.css` | **R1**: Role Library mounts **and** `loadRoles` refreshes post-relocator-deletion; RAG upload/search/query intact; research writes land via `/api/workspaces` (governed); parity 14. |
| **IA** — Context→Operate + front doors | The spine×OM coordination point: Context→Operate 3 sub-panels (Documents/Artifacts/Knowledge-Graph) **after S3 untangles its double duty**; Prompts + Workspaces Library front doors; `#kanban` under Projects. | **S3, OM2** | no (spine) | `index.html`, `library/workspaces.js`, `library/object-shell.js` | Context in Operate with no content lost; Workspaces/Prompts browse via `ObjectShell`; rail density verified vs UIFRAME; parity 14. |
| **S4** — Context pane + graph fork (hardest, NEW UI) | Net-new `#tab-context` run-observability bound to `/api/workflows/runs/*` (SSE `/runs/{id}/stream`) — **NOT `/api/context/*`** (the naming trap). Fork the knowledge graph by node-type (research artifacts vs run instances). Closes CR #9. | **S3, IA, UIFRAME** | no (spine) | `index.html`, `runs/runs-tab.js`, `main.js`, `app.css` | run list/detail/step timings render (fix `duration_ms`); live SSE drives the pane; graph fork routes nodes correctly; parity 14 (diff admin/runs failures). |
| **FE3** — Frontend phase-3 (state-object + orchestration split + boot) | The deferred hard 40%: rewrite reassigned `df*` lexical state (~220 sites) into a state-object accessor so `canvas.js` can extract; split ~150 orchestration fns; consolidate 11 `DOMContentLoaded` into one `boot()`; remove the 7 live-getter window bridges. Closes CR #10,11. **Gates only the deep canvas work — not S1.** | **S1** | no (spine, rewrites center) | `main.js`, `core/state.js`, `shell/legacy-bridge.js`, `composer-view.js`, `runs/runs-tab.js` | parity 14 **per extraction unit** (one domain per parity run); `legacy-bridge.js` symbol count **strictly shrinks**; vendor destructures still resolve; boot order preserved. |
| **CS** — Composite serialization + node multi-turn | The homeless lift, homed: extend `dfExportYaml` to serialize `kind:parallel`/`kind:loop` + v2 `StepPrompt` + a branch flatten-to-test adapter (rides the shipped 1.3.0 composite engine). Adds the additive/optional `test-step messages[]` field (frozen-safe). | **FE3, S1** | no (spine-adjacent) | `composer-view.js`, `main.js`, `workflows.py`, `composer.py`, `tests/` | `dfExportYaml` round-trips `kind:parallel`/`loop` to a runnable `WorkflowDefinition`; existing YAML export unchanged; `test-step` with/without `messages[]` both work; engine untouched; parity 14. |
| **OM3** — Composer palette = ObjectShell (the JOIN) | The single merge point: `loadWorkbenches` becomes the object registry; `renderRightPane` palette chip-mode; ⌘K cross-cuts all kinds (Build↔Library↔Operate); **Promote maps object→engine slot AND writes a graph edge** via `reference_index`. | **S1, FE3, CS, OM1, OM2** | no (the join) | `composer-view.js`, `object-shell.js`, `main.js`, `reference_index.py` | ⌘K filters the registry across kinds; Promote writes a valid engine slot + a graph edge; existing YAML export unchanged; parity 14. |

### 4.2 ASCII dependency graph

```
 ══ PARALLEL WORKTREES (start day 1, isolated) ══         ══ SERIAL SPINE (shared main.js / index.html) ══

 HARDENING                                                 S0   Chat extraction ............ (proof slice)
   F0  fusion-security ─────────────┐                       │
   UIFRAME  frame + a11y ─────────┐ │                       ▼
                                  │ │                       S1   Composer canvas-dominant  ◄── S1 NOT gated by FE3
 OBJECT-MODEL                     │ │                       │        │
   OM0 ─► OM1 ─► OM2              │ │                       ▼        │
   (prompts)(edges)(kinds+DELETE) │ │                      S2   Chat config-header  ◄── reads OM0
      │      │      │             │ │                       │        │
      │      │      │             ▼ ▼                        ▼        │
      │      │      │      ┌────► S3   Research + R1 fix  ◄── needs F0 + UIFRAME
      │      │      │      │       │
      │      │      └──────┼────► IA   Context→Operate IA  ◄── needs OM2
      │      │             │       │
      │      │             │       ▼
      │      │             │      S4   Context pane + graph fork  ◄── needs UIFRAME   [hardest NEW UI]
      │      │             │
      │      │             │      S1 ─► FE3  state-object rewrite ─► CS  composite serialize ─┐
      │      │             │           (gates deep canvas only)                              │
      └──────┴─────────────┴───────────── OM1, OM2 ──────────────────────────────────────►  OM3   the JOIN
                                                                                    (palette = ObjectShell,
                                                                                     Promote writes edges)
```

### 4.3 Critical path

```
   S0 ─► S1 ─► FE3 ─► CS ─► OM3
```

**This is THE critical path** — it carries the biggest work (**FE3**, the
~220-site state rewrite), the biggest unknown (**CS**, `dfExportYaml` v2), and
the terminal **JOIN** (OM3). Two sets of parallel feeds must converge onto it:

- **`OM0 → OM1 → OM2`** must finish before **OM3** — it runs from day 1 in a
  separate worktree, so it lands well inside the spine's shadow.
- **`F0` + `UIFRAME`** must finish before **S3** — both start day 1, backend/CSS
  isolated.

**Second terminal leaf:** `S0 → S3 → IA → S4` produces **Context**, the one
surface *built* not *moved* (real build risk) — it is a leaf (nothing depends on
it) and can trail the OM3 join.

**Scheduling note.** The DAG permits FE3 immediately after S1. Because the whole
spine serializes on `main.js`, we *schedule* S2/S3/IA/S4 before FE3 to
front-load all four operator-visible surfaces and de-risk delivery (surfaces
ship before the risky refactor). See decision **D3**.

---

## 5. Parallelization map

```
┌── SPINE (SERIAL — one worktree, one phase at a time) ─────────────────────────┐
│  S0 → S1 → S2 → S3 → IA → S4 → FE3 → CS → OM3                                  │
│  Reason: every phase edits the monolithic main.js + index.html (+ composer-*). │
│  Two spine phases in parallel = guaranteed merge conflict on the 9,271-line    │
│  main.js and a half-migrated config surface. NOT parallelizable internally.    │
└───────────────────────────────────────────────────────────────────────────────┘

┌── TRACK A · HARDENING (isolated worktree, start day 1) ──┐
│  F0       backend: workspace*.py + tests                 │  gates S3
│  UIFRAME  CSS: app.css block 6411-6520 + aria attrs      │  gates S3, S4
└──────────────────────────────────────────────────────────┘

┌── TRACK B · OBJECT-MODEL (isolated worktree, start day 1) ──┐
│  OM0 → OM1 → OM2                                            │  feeds IA (OM2),
│  backend routers + the CLEAN carved library/asset-peek.js   │  joins at OM3
└─────────────────────────────────────────────────────────────┘
```

**Day-1 concurrency: four phases in flight** — `S0` (spine) + `F0` + `UIFRAME`
+ `OM0`, all touching disjoint files.

**Collision boundary (the honest one).** The parallel tracks are isolated
*except* where OM/UIFRAME phases add a nav `<li>` or an `aria` attr to
`index.html` — the one file the spine also owns. Rule: those edits are
**additive-only, to disjoint `index.html` regions, and rebase onto spine head
before merge**. That convention — not "never touch `index.html`" — is the real
isolation boundary.

**What each track can and cannot share:**

| Track | Owns | Never touches | Convergence |
|---|---|---|---|
| Spine | `main.js`, `index.html` tab-content, `composer-*.js` | `workspace*.py`, `app.css` rail block, `asset-peek.js` internals | — |
| Hardening | `workspace*.py`, `app.css`, `tests/` | `main.js` | F0→S3, UIFRAME→S3/S4 |
| Object-model | `api/models/`, `api/services/`, `api/routers/prompts,objects`, `library/*.js` | `main.js` center | OM2→IA, {OM1,OM2,CS}→OM3 |

---

## 6. The no-loss contract (carried forward)

The **14-known-failing baseline** (`tests/parity` + `tests/ui` + non-slow
`tests/playwright`) is the **only** safety net, and **5 of the 14 are
click-timeouts on the exact composer / agent-chat / admin surfaces the spine
rewires**. Therefore:

1. **Diff the failing-SET membership, not the count.** A new failure — or a
   formerly-failing test that now fails *differently* — is a regression even at
   count = 14. Every spine gate runs the harness before *and* after and diffs
   the set.
2. **DOM-only moves preserve lexical bridges.** S0 moves `#agent-chat-dock`
   markup while chat JS stays in `main.js` module scope, so the `dfNodeData`
   test-step / model-write-back bridge survives for free (verified: `dfNodeData`
   let-scoped at `main.js:4773` with "reference it lexically" comments).
3. **`legacy-bridge.js` stays a strict-shrinking bijection.** No phase adds a
   `window` global (session constraint); new cross-module symbols route through
   `core/state.js` accessors from FE3, not the bridge. FE3 makes the bridge
   **net-negative**. Extract one domain per parity run.
4. **`data-action` delegation only** — no new inline `on*=` handlers anywhere.
5. **OM0 re-registers model/agent/plugin UNCHANGED** as an explicit
   zero-regression proof *before* the Prompt kind lights.
6. **`reference_index` delete-safety** (409 + dependents) so no delete silently
   orphans a reference, across every kind.
7. **R1 Role-Library trap is an enforced GATE at S3** — statically author the
   Role markup in `#tab-research` and relocate `loadRoles` *before* deleting the
   relocator, or both silently drop (parity cannot catch this).
8. **`#df-config-popup` stays floating** — node config is never split between a
   popup and a phantom right pane.
9. **Context binds `/api/workflows/runs/*`, never `/api/context/*`** (the
   conversation-context naming trap).
10. **Frozen engine untouched.** Every authoring/chat/research path resolves via
    `ModelResolver`/`test-step` and never imports `WorkflowEngine` — reachable
    only through `/run` + `/run-async` (verified). `test-step` stays non-engine
    even with the new `messages[]` field.
11. **ONLY-ADD.** Every retired surface (ComposerSplit, `SkillsDiscover.openDetail`,
    `#mcp-detail`, `WorkflowIndex.deepDive`) is replaced by an equal-or-greater
    capability **in the same phase**, never deleted bare.
12. **Code-review defects fold into their owning phase** (§3) — shipped defects
    are closed, not carried.
13. **Re-grep symbols at build time.** Both design docs lean on exact `main.js`
    anchors that have already drifted (979 → 989); FE3 + the carve move
    everything. Resolve by name, never by cited line.

---

## 7. The single next slice

**Build `S0` — Chat extraction — now, and launch `F0` in a parallel backend
worktree in the same breath.**

`S0` is the thesis-aligned spine proof: the **smallest slice that exercises the
hardest edge** (the lexical `dfNodeData` test-step bridge) with the least
surface. It is verified zero-loss, fully reversible (no Context/Research/Roles
change), and delivers the first operator-visible structural win — a real Chat
tab. `F0` runs concurrently because it is backend-isolated **and carries the
single CRITICAL defect in the whole audit** (an unauthenticated host-wide file
read while auth is off by default); it must not wait behind UI work.

> If only one worker is available, **F0 goes first** — a CRITICAL
> unauthenticated arbitrary-file-read in committed code outranks a UI slice.
> With two, do both. They share no files.

**S0 — files to touch**

| File | Change |
|---|---|
| `api/static/index.html` | Lift `#agent-chat-dock` (612-788) verbatim into a new `#tab-chat`; add one Build-rail nav button. |
| `api/static/js/main.js` | Add `ChatView.init()`; repoint `setMode('canvas')` callers at `main.js:3705/8070/8503`. |
| `api/static/js/workspace-legacy/composer-split.js` | Neutralize the `setMode` definition (`:94`); remove mode buttons. |
| `api/static/js/workspace-legacy/boot-sequence.js` | Repoint the 4th `setMode('canvas')` caller (`:291`). |
| `api/static/css/app.css` | Chat-tab layout; drop the divider/mode-button styling. |

**S0 — acceptance check**

- [ ] New `#tab-chat` renders the moved dock; exactly one Build-rail button added.
- [ ] `grep 'setMode(' → 0` live callers; `setMode('chat')` neutralized (the surviving Composer float-toggle can't half-size a departed pane).
- [ ] **Cold-start:** open Chat *before* Composer → `#agent-select` populates (the moved `loadAgentsForSelector` fires).
- [ ] Node-select → `test-step` → model write-back still works (lexical `dfNodeData` bridge intact).
- [ ] Agent chat persists across tab switches.
- [ ] Parity: failing-SET **membership** unchanged vs the 14-baseline (diff, not count).
- [ ] No new `window` globals; `data-action` delegation only; no console errors on boot.

**F0 — concurrent, acceptance check**

- [ ] `resolve()` applied to every glob result in `search()`/`list()`; `?glob=../etc/hostname` → 400, not file content.
- [ ] `delete("")`/`delete(".")` (resolve == root) rejected.
- [ ] Two concurrent `/index/{n}/next` calls return **distinct** items (file-locked claim).
- [ ] `write`/`edit`/`expand` are tmp+replace atomic; `edit(count=-1)` clamped + extension-checked; desynced `order`/`items` tolerated.
- [ ] Root-allowlist + read-only-default policy on `Workspace.create()`.
- [ ] 25 existing + new tests green; parity 14 (backend-only).

---

## 8. Open questions / decisions for the operator

| # | Decision | Recommendation | Why it matters |
|---|---|---|---|
| **D1** | `#df-config-popup`: keep floating vs retire into a right pane? | **Keep floating** (separation A16) → kill the composer doc's right-pane machine. | The two P0s answer this oppositely; building both splits node config across a popup **and** a pane. Sign-off unblocks S1 and formally demotes the composer doc. |
| **D2** | Auth: adopt `require_master_key` across the open workflow/composer/agent routes (object-model §7), or keep the current asymmetry? | Decide before OM2; a unified shell driving all four surfaces will otherwise hit inconsistent 401s. | It is a **behavior change** for currently-open routes — must be deliberate, not silent. Owner is OM2. |
| **D3** | FE3 timing: after S4 (front-load all four surfaces) vs after S1 (clean the center before adding S2/S3/S4 wiring)? | **After S4** — ship every visible surface before the risky refactor; the bridge growth is bounded and FE3 reverses it. | Governs whether the invisible ~220-site slog blocks visible value. The judge's fix only requires FE3 ≠ before S1; the exact slot is yours. |
| **D4** | Workspace root-allowlist (F0): which host roots are permitted? Does read-only-default break the LangGraph indexer/authoring graphs that currently bind RW arbitrary-root? | Define the allowlist (vault? repo? homelab paths?) + run a compat check against `~/projects/langgraph-vllm` before flipping the default. | F0's "sandbox" is only truthful once the roots are named; a wrong default breaks the shipped fusion agents. |
| **D5** | `research_graph` migration (S3): move the flagship research agent off its ad-hoc vault writer onto the governed `workspace_tools`? | **Yes** — it's the only way Research inherits policy/index/MOC/resumability and closes the "fusion is half-wired" gap. | Changes *where and how* research artifacts land; confirm before S3. |
| **D6** | `/api/research/deep-dive` hardening: promote Research (S3) with or without fixing the hardcoded `dolphin3:latest` + web-egress + zero test coverage? | Add minimal coverage in S3 before promoting Research to a first-class tab. | It is the weakest backend path the four surfaces lean on. |
| **D7** | Context sub-panel scope (G3): 3 sub-panels (Documents/Artifacts/Knowledge-Graph) vs run-observability-only? | Confirm scope before S4 — it is the one surface **built not moved** (real build risk). | Sets the size of the hardest phase. |
| **D8** | Project-bar home (G1): where does the project selector live once the Composer is canvas-dominant? | Decide during S1. | Layout dependency for the canvas-dominant Composer. |

---

## Verification (confirmed findings + roadmap check)

> **Independent verification pass — 2026-07-09.** Every §3 finding was re-opened
> at its file+line against the shipped code on `feat/composer-workspace`; the
> CRITICAL was **reproduced live**; the roadmap's dependency ordering, the
> frozen-engine claim, and the "single next slice" were re-derived from source.
> **Verdict: §3 is sound with exactly one false positive to drop; the ordering
> and critical path hold; the next slice should lead with F0's security core,
> not S0.**

### A. Confirmed defect list (verified against source)

**Live reproduction of the CRITICAL** (venv Python **3.12.3**): a `Workspace`
whose root is `/root`, calling `root.glob("../*.md")` returns
`/root/../SECRET.md`; `is_file()`→`True`; `read_text()`→the file's **content**;
`relative_to(root)`→`../SECRET.md` and **does not raise**. `glob=../../../../../../etc/hostname`
returned this host's `/etc/hostname` (`bd790i`). Only the *absolute*-pattern
vector is closed (`glob="/etc/hostname"` → `NotImplementedError`); the `..`
vector is fully open. The entire `resolve()` guard is void for `search()`/`list()`.

| # | Sev | File:line | Verdict | Evidence |
|---|---|---|---|---|
| 1 | **CRITICAL** | `workspace.py:156` | **CONFIRMED (live-reproduced)** | `self.root.glob(glob)` with `glob=../…` reads + returns content outside root; `relative_to(root)` yields `../…` without raising. Same class in `list()`:144. Unauthenticated GET (`workspaces.py:146`,`:134`). |
| 2 | **HIGH** | `workspace.py:235` | **CONFIRMED** | `resolve("")`/`resolve(".")`→`self.root` (92-93); `delete()` then hits `shutil.rmtree(p)` (239) on root → wipes the whole bound dir (vault/repo). |
| 3 | **MEDIUM** | `workspace_index.py:135` | **CONFIRMED** | Router `next_pending` is a **sync `def`** (`workspaces.py:198`, runs in the threadpool); `_index()` builds a fresh, **lock-free** `WorkspaceIndex` per request (`:173`); read-see-`pending`-set-`in_progress`-save races → two `/next` double-claim one item. |
| 4 | **MEDIUM** | `app.css:6467` | **CONFIRMED (conditional trigger)** | `min-height:calc(100vh-190px)` on a `minmax(0,1fr)` grid item (6433) + `body{overflow:hidden}` (6435): when header+footer **>190px** (125% text scale / wrapped 2-row header) the rail box exceeds its track, overflows, and Admin (`margin-top:auto`, 6511) clips off-screen — unreachable. Current budget ≈6px. |
| 5 | LOW | `workspace.py:201` | **CONFIRMED** | `EditBody.count:int=0` unconstrained (`workspaces.py:50`); `count=-1`→`replace(find,replace,-1)` replaces **all**, `min(-1,occ)` reports `replacements:-1`; `edit()` never calls `_check_extension` (unlike `write`/`expand`). |
| 6 | LOW | `workspace_index.py:164` | **CONFIRMED** | `_load()` fills `_order`/`_items` independently (73-75); an id in `order` absent from `items` → `self._items[i]` **KeyError** in `items()`/`next_pending()`; `_guard()` maps only Workspace*/FNF → uncaught **HTTP 500**, defeating the stated "corrupt index must not brick the loop". |
| 7 | LOW | `app.css:6446` | **CONFIRMED (conditional trigger)** | `overflow-y:auto` → clip on **both** axes (`visible`+`auto`→`auto`/`auto`) + `sticky`/`z-index:30` stacking context; the drop-UP `.admin-menu` (6519) is a rail descendant → clipped inside the 208px column, cannot float over the canvas on short (<~700px) viewports. |
| 8 | LOW | `app.css:6447` | **CONFIRMED** | Frame grid keyed on `body>.tab-nav / #main-content / .footer` child combinators (6446-49); a wrapper introduced by the in-flight carve silently unbinds the grid areas → layout reverts to broken stacked flow, no error. Accurate latent-coupling note. |
| 9 | LOW | `runs-tab.js:1305` | **CONFIRMED** | SSE `step.completed` writes `duration_ms` (1305/1307); every render site reads `s.duration_seconds` (685, 1085) → live step duration shows `?` until the 1.5s poll swaps in a full run. Cosmetic/transient. |
| 10 | LOW | `actions.js:19` | **CONFIRMED (latent)** | `capture: type==='toggle'` only; the adjacent comment claims *toggle **and** focus* are capture-handled. A future `Actions.on('focus',…)` would register bubble-phase and silently never fire. No `focus` map exists yet. |
| 11 | LOW | `runs-tab.js:3` (+`main.js:6`) | **CONFIRMED** | Eval-time `const {Drawflow,dagre}=window` / `{Drawflow,d3,dagre,jsyaml}=window`; correct **only** because `index.html` loads them as `defer` classic scripts (11-18) ahead of the `type=module` entry (2423) — ordering verified. Converting any vendor to `module`/`async` silently nulls the captures. |
| — | (also) | `asset-peek.js:103-104` | **FALSE POSITIVE — DROPPED** | The onclicks call `InstallWizard.open()` / `Compare.add()`, which **are defined** as window globals (`main.js:8782` / `main.js:8721`); inline `onclick` resolves bare identifiers against global scope → **no ReferenceError**. Consistent with the carve review's own "all inline `on*=` handlers resolve to real methods". **OM0 needs no such fix.** |

**Net: 11 CONFIRMED (1 CRITICAL, 1 HIGH, 2 MEDIUM, 7 LOW); 1 refuted.** The §3
severity transcription is otherwise faithful to the source review. The `asset-peek`
"(also)" row in §3 and the OM0 "fixes `asset-peek.js` broken onclicks" scope item
should be struck.

### B. Roadmap soundness verdict — **SOUND**

- **Dependency ordering holds.** Critical path `S0 → S1 → FE3 → CS → OM3`
  re-derived from source: S0's anchors are real (`#agent-chat-dock@612`;
  `setMode` def `@composer-split.js:94`; the 4 `('canvas')` callers at
  `main.js:3705/8070/8503` + `boot-sequence.js:291`); S1 then deletes the mode
  UI; FE3 correctly gates only deep canvas (CS, OM3) — **not** S1; CS depends on
  FE3+S1; OM3 (the join) depends on S1+FE3+CS+OM1+OM2. Parallel gates
  (`F0`+`UIFRAME`→S3; `OM0→OM1→OM2`→{IA, OM3}) are file-disjoint and real.
- **Frozen engine verified.** `test-step` (`workflows.py:353`) resolves via
  `ModelResolver` only and **never** touches `WorkflowEngine`; `dfNodeData` is
  `let`-scoped at `main.js:4773` — so S0's **DOM-only** dock move preserves the
  lexical test-step / model-write-back bridge exactly as contract #2 claims.
  **One imprecision to tighten:** contract #10's "engine reachable only via
  `/run` + `/run-async`" is overstated — `chat.py` and `a2a.py` also instantiate
  `WorkflowEngine` via `get_engine()`. This does **not** break the plan (neither
  is a rewired surface; the engine files stay unedited), but the contract should
  read *"the authoring/test-step path never invokes the orchestrator"* rather
  than *"only `/run`+`/run-async` reach it."*
- **Baseline confirmed.** The three fusion test files are green (**25 passed**),
  matching §2's "25/25".
- **Orphan + freeze claims confirmed.** `#tab-research` is present but `hidden`
  with no rail/`switchTab('research')` entry (orphan → S3's un-hide is real
  work); vendor `defer` ordering is as §3 #11 assumes.

### C. Tightened "single next slice"

The roadmap (§7) leads with **S0** and treats **F0** as a concurrent sidecar
(conceding "F0 first if one worker"). **Verification inverts the emphasis: F0's
security core is THE next slice — regardless of worker count.** All three
reasons are evidence-backed:

1. The CRITICAL is **live on this host now** (reproduced reading `/etc/hostname`)
   with auth **off by default** — it outranks any feature slice.
2. F0's security core is **strictly no-loss**: it only *removes* a vuln and adds
   guard tests; it is backend-isolated and cannot regress a surface or the frozen
   engine (parity is UI-only).
3. It is **zero-decision**: the six fixes below need **no** operator sign-off.
   Only the *root-allowlist + read-only-default* half of F0 depends on **D4**
   (which host roots? does read-only break the shipped LangGraph graphs?) — that
   half splits off as a fast-follow.

**THE NEXT SLICE — `F0-core` (no operator input required):**

1. `search()`/`list()` — reject `..`/absolute globs **and** re-`resolve()` every
   glob result back inside root → `?glob=../etc/hostname` returns **400**, not
   content. *(CR #1, CRITICAL)*
2. `delete()` — reject any path that resolves to `self.root` → no whole-workspace
   `rmtree`. *(CR #2, HIGH)*
3. `next_pending()` claim — file-locked read-modify-write on the index JSON → two
   concurrent `/next` return **distinct** items. *(CR #3, MEDIUM)*
4. `edit()` — clamp `count>=0` and call `_check_extension`. *(CR #5)*
5. `WorkspaceIndex._load()` — drop `order` ids absent from `items` so a desync no
   longer 500s. *(CR #6)*
6. `write`/`edit`/`expand` — tmp+replace atomic (parity with the already-atomic
   registry/index writers). *(hardening)*

**Gate:** existing **25** fusion tests stay green **+** new tests
(`glob=../etc/hostname`→400; `delete("")`/`delete(".")`→rejected;
2×concurrent `/next`→2 distinct ids; `count=-1`→clamped+ext-checked; desynced
`order`/`items` tolerated); parity **14** unchanged (backend-only).

**Concurrent (iff a 2nd worker is available):** `S0` — Chat extraction — as the
highest-value **spine** slice; verified zero-loss (the `dfNodeData@4773` lexical
bridge survives the DOM-only dock move) and file-disjoint from F0.
**Fast-follow (blocked on D4):** F0 root-allowlist + read-only-default, after the
operator names the permitted roots and a compat check runs against
`~/projects/langgraph-vllm` (the shipped graphs bind RW arbitrary-root today).
