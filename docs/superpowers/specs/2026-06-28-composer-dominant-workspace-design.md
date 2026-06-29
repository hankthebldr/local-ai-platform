# Composer-Dominant Dynamic Workspace — Design

**Status:** Draft · **Date:** 2026-06-28 · **Surface:** `api/static/` — `index.html` shell + extracted `css/app.css` + `js/**` ES modules
**Supersedes:** the current Composer tab layout (canvas + `agent-chat-dock` + sliding `composer-workstream`), the flat top tab-bar + Admin dropdown nav, **and the 21k-line single-file `index.html`** (this rework also stages the deferred ES-module fan-out).

## Problem

The Composer tab crams three surfaces into one viewport — the Drawflow **canvas** (center), a global **agent chat dock** (bottom), and a **workstream** with three sliding sub-panels (Step Config / Active Run / History). The layout has no clear primary surface, and the chat↔workflow relationship is **one-directional and modal**:

- The only bridge is **step-engage** ([index.html:8400](../../../api/static/index.html)): clicking a node sets `window._composerEngagedNodeId`, which makes the *single global chat box* a test harness for that one step. There is one chat, shared across all nodes.
- There is **no reverse flow** — chat cannot seed or create a workflow.
- The "3-menu tier" nav (flat tab list + Admin dropdown) and the sliding workstream panes feel dated and fragile.

The entry point dictates a fixed layout; the workspace is not "dynamic to the starting point."

## Goal

One **composer-dominant** workspace where chat and workflow are two views of the same object, and the layout reshapes based on selection rather than on how you entered.

Hard requirements (from the operator):
1. Composer is the **dominant** center surface; project locator + step info sit with it.
2. The **right pane is dynamic and context-bound to the current selection.**
3. **Changing the selected node changes the chat experience** — each node has its own history, model, and options. And vice versa.
4. From the rail you can pick a **persona + model**, chat, and **seed that chat as the start of the workflow** ("Promote").
5. The right pane can also **pivot** to agent / plugin / MCP configuration.
6. **Remove** the 3-menu tier and the sliding-pane workstream; replace with a robust, modern, dynamic workspace.

Non-goals (YAGNI): no LLM-authored DAG generation (conversion is deterministic Promote only); no server-side chat persistence (client-only for now); no change to the workflow engine, run semantics, or YAML schema.

## Core abstraction: the Session

Chat and workflow stop being separate features. **A node *is* a chat thread that occupies a position in a DAG.** "Promote" is therefore a state transition (bind an existing thread to a new node id), not a data migration. Because the right pane is a **pure function of `selection`**, "dynamic to the starting point" falls out for free — sidebar-chat-first and composer-seed-first are two initial values of one state, not two code paths.

### Client state model (Approach A — client session store)

```
Workspace = {
  workflowId,                  // current workflow (graph persists server-side, as today)
  projectId,
  selection: {                 // the single source of truth for the right pane
    kind: 'node' | 'seed' | 'palette' | 'none',
    nodeId?,                   // kind === 'node'
    paletteRef?,               // kind === 'palette' → { type:'agent'|'plugin'|'mcp', id }
  },
  threads: {                   // keyed by nodeId, plus the reserved 'seed' key
    [threadKey]: ChatThread,
  },
}

ChatThread = {
  key,                         // nodeId | 'seed'
  model,                       // model this thread/node talks to
  systemPrompt,
  persona?,                    // agent id, if seeded/bound to a persona
  options: { webSearch, tools, ... },
  messages: [ { role, content, ts, meta } ],
}
```

- **Node graph** (`dfNodeData`, the DAG) persists server-side via the existing `dfSave()` → `dfExportYaml()` → `POST /api/workflows/{id}`. Unchanged.
- **Threads** persist **client-side only**: `localStorage['enclave.ws.' + workflowId]` → `{ selection, threads }`. Per-browser, survives reload. This matches the already-stateless `test-step` endpoint and leaves a clean seam to promote to server persistence when fleet-awareness (1.4.x) lands.
- `NodeData` remains the single source of truth for a node's `model` / `systemPrompt`; the bound `ChatThread` mirrors them and writes back on edit so the canvas node and the chat never drift.

## Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR  Enclave · Composer · Runs · Library ▾ · Admin ▾    Project ▾ [Save][Run▶]│
├───────────────┬────────────────────────────────────────┬───────────────────────┤
│ LEFT RAIL     │  CENTER — COMPOSER (dominant)           │ RIGHT — DYNAMIC PANE  │
│               │                                          │ f(selection)          │
│ ▸ Projects    │  ┌────────────────────────────────────┐ │                       │
│   locator     │  │  CANVAS (Drawflow DAG)             │ │ node  → that node's   │
│               │  │   [seed]→[step]→[step]             │ │         chat thread + │
│ ▸ Palette     │  │                                    │ │         model/prompt/ │
│   Roles       │  └────────────────────────────────────┘ │         options       │
│   Agents      │  ┌────────────────────────────────────┐ │ seed  → persona+model │
│   Skills      │  │  STEP INFO (below)                 │ │         picker + chat │
│   Plugins     │  │  structural config of selected     │ │         + [Promote]   │
│   MCPs        │  │  step: name, deps, parser, gates,  │ │ palette→ agent/plugin/│
│               │  │  last run status                   │ │         mcp config    │
│               │  └────────────────────────────────────┘ │ none  → empty state   │
└───────────────┴────────────────────────────────────────┴───────────────────────┘
```

### Navigation (replaces the 3-menu tier)

The flat tab list + Admin dropdown collapse into a top bar with four destinations:

- **Composer** — the 3-region workspace above (default / home).
- **Runs** — run monitoring + DAG viz (today's `tab-runs`, absorbs the workstream's Active-Run + History panes).
- **Library ▾** — catalogs: Workflows, Agents, Models, Skills, Plugins, MCP (today's `workflow-index`, `inventory`, `admin-plugins`, `admin-skills`, `admin-mcp`, agents).
- **Admin ▾** — System, Exports, Cloud, Keys (today's admin menu items).

Non-Composer destinations render as full-width views that replace the 3-region workspace, reusing the existing `.tab-content` swap mechanism and hash routing (`#/<dest>`). **Same elements, reorganized chrome** — no catalog/admin/runs content is rewritten in this work.

## Region behaviors

### Left rail
- **Projects locator**: select/switch the active project (today's `composer-project-bar`).
- **Palette**: the existing workbenches (Roles, Agents, Skills, Plugins, MCPs, [index.html:5920](../../../api/static/index.html)). Drag a role/agent onto the canvas to add a node. **Click** (without drag) a palette Agent/Plugin/MCP → `selection = { kind:'palette', paletteRef }` → right pane shows its config.

### Center — Composer (dominant)
- **Canvas**: the Drawflow DAG, unchanged in mechanics (`dfInitEditor`, `dfAddAgentAtCenter`, `dfAddNodeFromTemplate`). Node selection drives `selection`.
- **Step info (below)**: structural authoring for the selected node — name, dependencies/edges, output parser, quality gates, last-run status. Binds to `NodeData`. This replaces the floating `#df-config-popup` and the workstream's "Step Config" pane. `model` + `systemPrompt` appear here **read-only mirrored** (their editable home is the right pane, where you see chat feedback immediately).

### Right — Dynamic pane = `renderRightPane(selection)`
A single pane whose content is a pure function of `selection.kind`:

| `kind` | Content |
|---|---|
| `node` | The node's `ChatThread`: message history, composer input, and the editable `model` / `systemPrompt` / `options` for that node. Sending tests the step (see Chat send). |
| `seed` | Persona picker + model picker + a `ChatThread` keyed `'seed'` + a **Promote to step** button. |
| `palette` | The focused agent/plugin/MCP config editor (existing workbench editors, relocated). |
| `none` | Empty state: "Pick a persona to start a seed, or select a step on the canvas." |

Default selection on entering Composer: `node` if the workflow has nodes (select the first/last-edited), else `seed`.

## Key flows

### Selection ↔ chat binding (requirement 3)
- Drawflow `nodeSelected` → `selection = { kind:'node', nodeId }` → `renderRightPane`. The right pane swaps to that node's thread.
- Drawflow `nodeUnselected` / canvas blank-click → `selection = { kind:'seed' }` (or `none` if a seed is mid-flight you don't want to clobber — see error handling).
- This **retires** `composerEnterStepEngage` / `composerExitStepEngage` / `window._composerEngagedNodeId` / the `#step-engage-badge`. Selection *is* engagement.

### Seed → Promote (requirements 1, 4)
1. `selection.kind === 'seed'`; user picks persona + model, chats. Messages accumulate in `threads['seed']`.
2. User clicks **Promote to step**.
3. Create a node (`dfAddAgentAtCenter` for a persona, else `dfAddNodeFromTemplate`) carrying the seed's `persona` / `model` / `systemPrompt`.
4. **Re-key** `threads['seed']` → `threads[newNodeId]` (history preserved).
5. `selection = { kind:'node', nodeId:newNodeId }`; canvas selects it; right pane now shows it as the node's chat.
6. A fresh empty `threads['seed']` is ready for the next seed.

If the workflow is empty, the promoted node is the **start** of the DAG. If a node is already selected when promoting, the new node is appended downstream of it (edge from selected → new), so a seed can extend an existing graph.

### Chat send (unified)
One `sendMessage(threadKey)` for both seed and node threads:
- Builds the request from the thread's `systemPrompt` + `messages`.
- **Seed thread** → `/api/agents/{persona}/chat` if a persona is set, else `/v1/chat/completions` (existing paths).
- **Node thread** → `/api/workflows/test-step` (existing) with the node's step definition.
- Appends the response to the thread; persists to localStorage.

> **Flagged seam:** today `_sendStepMessage` posts only a single `user_message` ([index.html:8337](../../../api/static/index.html)), so a node chat would be single-shot, not multi-turn. To honor "each node has its own history" in conversation, the client should send the accumulated thread as `messages[]`. This is an **additive, stateless** request-shape change to `test-step` (optional `messages[]` field; absent → current single-shot behavior). It does not introduce server-side session state, so it stays within Approach A. The implementation plan must either (a) add the optional field, or (b) ship node chat as single-shot for v1 and defer multi-turn. **Decision deferred to the plan**; default recommendation is (a).

## What gets removed

- The flat tab-nav list + Admin dropdown ([index.html:5745](../../../api/static/index.html)) → new top-bar nav.
- `composer-workstream` and its `ComposerWorkstream.switch()` sliding panes ([index.html:6170](../../../api/static/index.html)) → Step Config becomes "step info below"; Active Run + History move under **Runs**.
- `agent-chat-dock` as a separate global chat ([index.html:6026](../../../api/static/index.html)) → chat lives in the right pane, bound to selection.
- `#step-engage-badge`, `composerEnterStepEngage`, `composerExitStepEngage`, `window._composerEngagedNodeId`.
- `#df-config-popup` floating popup → step info region.

## ES modularization (staged with this rework)

This rework is the vehicle for beginning the deferred `index.html` → ES-module fan-out. The file is already ~35 self-contained IIFE namespaces (`window.X = (function(){…})()`), so each becomes a module by adding an `export` — the work is mostly **mechanical relocation, not rewriting**. The new workspace code is authored as modules from birth.

### Mechanism: native ES modules, no build step

There is **no JS build tooling** in the repo, and FastAPI already serves `/static` via `StaticFiles`. So we use **native ES modules** — `<script type="module" src="/static/js/main.js">` with URL-path imports. No bundler, no transpile, no new build step.

- The single `<script>` block (lines 7672–21270) is replaced by the `js/` module graph below, entered via `main.js`.
- The `<style>` block (lines 36–5679) is extracted verbatim to `css/app.css` and linked with `<link rel="stylesheet">` — near-zero risk, removes ~5,600 lines from `index.html`.
- Vendored libs (d3, dagre, drawflow, js-yaml) **stay classic** `<script defer>` and expose their globals; modules consume `window.Drawflow` / `window.d3` etc. as today. Classic-defer scripts execute before the module script, so the globals are ready.
- The head theme-bootstrap script (lines 19–35) **stays inline classic** (it must run synchronously before paint to avoid theme flash).

### Module tree

```
api/static/
  index.html            shell only: head, body skeleton, <link app.css>, <script type=module main.js>
  css/app.css           extracted <style>
  js/
    main.js             entry: boot sequence, mount shell + workspace, init router
    core/
      net.js            Net
      ui.js             Toast · Confirm · EmptyState · ErrorPanel · Skeleton
      theme.js          Theme
      shortcuts.js      Shortcuts
      heartbeat.js      Heartbeat
      state.js          NEW — Workspace state object + localStorage persistence
    shell/
      nav.js            NEW top-bar nav (Composer/Runs/Library/Admin); retires switchTab's tab list
      router.js         hash routing (#/<dest>)
      actions.js        Actions — the data-action delegation dispatcher
      legacy-bridge.js  window.fn = fn exposures for remaining inline handlers (see below)
    workspace/
      workspace.js      orchestrator: 3 regions + selection
      left-rail.js      Projects locator + palette
      canvas.js         Drawflow DAG (df* functions)
      step-info.js      center "step info below"; retires df-config-popup + Step Config pane
      right-pane.js     renderRightPane(selection) dispatcher
      chat-thread.js    ChatThread model + unified send + ChatRating
      seed-promote.js   seed → Promote flow
    library/
      workflow-index.js WorkflowIndex · Kanban
      agents.js         AgentGen
      models.js         CatalogPage · CatalogModelsShare
      skills.js         SkillsPanel · SkillsBuilder · SkillsDiscover
      plugins.js        PluginsPanel · ExtDiscover
      mcp.js            MCPPanel
    runs/
      runs.js           RunsTab
      workflow-memory.js WorkflowMemory
      research-artifacts.js ResearchArtifacts
    admin/
      menu.js · auth.js · api-keys.js · cloud.js · exports.js
```

(Exact file-to-namespace grouping is a plan-time detail; the domains above are fixed. `ComposerView` / `ComposerWorkstream` are absorbed/retired into `workspace/`.)

### Inline handlers — the window-bridge

~207 inline `on*=` handlers remain in the HTML (`onclick="dfExportYaml()"`, etc.). Under module scope a top-level `function foo(){}` is **not** global, so these break the moment the script becomes a module. Strategy:

- **New workspace code uses `data-action` delegation only** — zero new inline handlers, zero new window globals.
- **Untouched legacy regions keep their inline handlers working** via an explicit bridge: each module that owns a still-referenced function re-exposes it (`window.dfExportYaml = dfExportYaml`), and all such exposures are **centralized in `shell/legacy-bridge.js`** so they are easy to find and delete.
- `legacy-bridge.js` is a **shrinking list**: as the `data-action` migration (already 160 attributes in) retires each inline handler, its window exposure is removed. The bridge documents exactly how much legacy coupling remains.

### Sequencing — modularize first, then redesign

The two bodies of work (module fan-out, workspace redesign) are deliberately **ordered, not interleaved**, and become **two implementation plans**:

**Phase 1 — Behavior-preserving modularization.** Move the existing code into the module tree with **no UX change**. CSS → `app.css`; the `<script>` block → `js/**` (every namespace relocated + `export`ed + `window`-bridged); switch to `<script type="module">`; stand up `main.js` boot. Success criterion: **the app behaves identically and the full existing test suite stays green.** This is provably a no-op refactor — the safest possible first step, and it gives the redesign a clean modular surface to build on.

**Phase 2 — Composer-dominant workspace.** On the now-modular codebase, build `workspace/` + the new `shell/nav.js`, retire the old surfaces (`agent-chat-dock`, `composer-workstream`, step-engage, `df-config-popup`), and wire the Session model + Promote. New code is `data-action`-only.

Phase 1 carries the bulk of the mechanical risk but no design risk; Phase 2 carries the design risk on a stable base. Each phase ships and is verifiable on its own.

### Risks specific to modularization

- **Import cycles** — namespaces cross-reference each other and shared globals (`window._chatAgent`, etc.). Mitigation: shared mutable state lives only in `core/state.js` (imported, never circular); legacy cross-refs go through the `window`-bridge until migrated.
- **Boot ordering** — module execution is deferred. Any code that today runs at classic-script parse time must move into `main.js`'s explicit boot sequence. Audit for parse-time side effects during Phase 1.
- **Caching** — `index.html` is already served `no-store`; module files are normal `/static` assets. Add cache-busting (query string or content hash in import URLs) if stale modules become a problem in the k3s dev container.
- **Bigger diff, mostly mechanical** — Phase 1's relocation is large but low-logic-risk; review per-domain file moves independently.

## Error handling

- **localStorage unavailable / quota**: threads degrade to in-memory only; surface a one-time `Toast` warning; never block chatting.
- **Stale thread keys**: on load, prune `threads[nodeId]` whose `nodeId` is absent from the saved graph (node deleted in another session). Keep `'seed'`.
- **Node deleted while selected**: its thread is dropped; `selection` falls back to `seed`.
- **Promote with empty seed thread**: allowed (creates a configured-but-unused step); no error.
- **Unsaved seed on navigation away from Composer**: seed thread is retained in localStorage; returning restores it.
- **Concurrent edits to model/systemPrompt** from step-info mirror vs right pane: right pane is the writer; step-info is read-only mirror, so no conflict.

## Testing

UI tests live under `tests/ui/` (see existing 46-file suite). Cover:
1. **Selection → right pane**: selecting node A then node B renders A's then B's thread (history isolation).
2. **Seed → Promote**: seed chat with N messages, Promote, assert a node exists, `threads[newId]` has the N messages, `threads['seed']` is empty, canvas selection = new node.
3. **Promote into existing graph**: with node selected, Promote appends downstream with an edge.
4. **Persistence**: write threads, reload, assert restored from localStorage; assert stale-key pruning.
5. **Removal regressions**: `window._composerEngagedNodeId` and `#step-engage-badge` are gone; node selection still routes chat to `test-step`.
6. **Nav**: Composer/Runs/Library/Admin reachable; hash deep-links (`#/runs`, etc.) still resolve.
7. **Graceful degradation**: localStorage throwing does not break send.
8. **Module load**: page boots with the module graph — no console errors, every domain (`library/*`, `runs/*`, `admin/*`) initializes, vendor globals (Drawflow/d3) resolve before `main.js` boot.
9. **Legacy-bridge integrity**: every inline `on*=` handler still present in the HTML resolves to a defined `window.*` function (a smoke test that walks the DOM for `on*` attributes and asserts each referenced symbol exists) — guards against an extraction dropping a global.

## Out of scope / deferred

- Server-side thread persistence (Approach B) — revisit with fleet-awareness (1.4.x).
- LLM-authored DAG generation.
- **Completing** the `data-action` migration (retiring all 207 inline handlers) — this rework bridges them via `window` and shrinks the list; finishing it is a follow-on so `legacy-bridge.js` reaches empty.
- **Component-level CSS splitting** — `app.css` ships as one extracted file; breaking it into per-domain stylesheets is a later refinement.
- A JS **build/bundler** step — native ESM is sufficient at current scale; revisit only if module count or load latency demands it.
