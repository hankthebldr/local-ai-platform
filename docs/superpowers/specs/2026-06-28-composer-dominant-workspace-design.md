# Composer-Dominant Dynamic Workspace — Design

**Status:** Draft · **Date:** 2026-06-28 · **Surface:** `api/static/index.html` (in-place)
**Supersedes:** the current Composer tab layout (canvas + `agent-chat-dock` + sliding `composer-workstream`) and the flat top tab-bar + Admin dropdown nav.

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

## Out of scope / deferred

- Server-side thread persistence (Approach B) — revisit with fleet-awareness (1.4.x).
- LLM-authored DAG generation.
- ES-module split of `index.html` (operator chose in-place; the deferred 1.x module fan-out is unaffected by this work).
