---
title: The Enclave Composer — Workflow-Building Surface
date: 2026-07-09
status: proposed
surface: api/static/ (index.html shell + js/** modules), backed by the FROZEN workflow engine
supersedes-detail: extends 2026-06-28-composer-dominant-workspace-design.md with the three on-ramps, the sub-component builders, and the local-sandbox operation model
---

# The Enclave Composer — Workflow-Building Surface

> One authoritative design for the Composer as *the place you build agentic
> workflows*. Spine: **prompt-first** (a workflow is crystallized conversation).
> Grafts: the **live bench** on every object (from *The Bench*), and the
> **selection-driven durable right pane** anchored on the `nodeSelected` seam
> that provably already exists (from *Topology*). Everything is grounded in real
> files; the workflow engine is **frozen** and untouched.

---

## Related: Unified Object Model

This Composer design has a companion: **[ENCLAVE Unified Object Model & Library Alignment](2026-07-09-unified-object-model-library-alignment.md)**. Where this document governs *how you build a workflow* (the selection machine wrapped around the DAG), that one governs *what the pieces are* — a single `EntityMeta` envelope, one `ObjectShell`/`EntityCard`, and a generalized `AssetPeek` deep-dive that make all ten platform kinds (agent · model · prompt · skill · plugin · mcp · workflow · project · context · workspace) one family. The two meet at one seam: **every Library object is a Composer palette object, and Promote is the gesture that turns it into a step.** Concretely, the palette (`loadWorkbenches`) becomes `ObjectShell` in chip-mode over the same `GET /api/objects/{kind}` endpoint, `renderRightPane(selection={kind:'palette'})` shares the object's `DeepDiveSpec` + live bench, and Promote maps each kind to its engine slot (Prompt→`StepPrompt.role_ref`, Agent→node `system_prompt`, Skill/Plugin/MCP→`ToolRef`, Model→step `model`). It ships behind the same frozen-engine / `data-action` / no-new-global constraints and does not alter anything below.

---

## 0. TL;DR

- **Mental model:** *The Composer is one selection machine wrapped around a DAG. Whatever is selected — nothing, a seed conversation, a canvas step, or a palette block — is what the right pane engages, tests, and can crystallize into a step.* Selection **is** engagement.
- **Three on-ramps, one surface:** prompt-first (talk in the seed pane), component-first (click a palette block → live bench), canvas-first (drag onto the canvas). All three converge on the same `Promote` gesture and the same `renderRightPane(selection)`.
- **First slice to build (P0):** *The Right Pane* — relocate the node config (`dfRenderConfigPanel`, already emitted into two mirror mounts) into a durable third region driven by the already-wired `nodeSelected` event, retiring the floating `#df-config-popup`. Near-zero logic, no engine change, and it creates the mount every later selection-kind renders into.
- **The one backend change in the whole plan:** an *additive, optional* `messages[]` field on `POST /api/workflows/test-step` (today it takes a single `user_message`, [workflows.py:347](../../api/routers/workflows.py)). Absent → today's behavior. Nothing else touches the engine.

---

## 1. Executive summary & the one mental model

The Composer today crams three surfaces into one viewport — the Drawflow canvas, a single global chat dock, and a sliding workstream — with exactly one bridge between chat and workflow (`window._composerEngagedNodeId` turns the global chat into a test harness for one node, [main.js:903](../../api/static/js/main.js)). There is no reverse flow: chat cannot create a workflow, the layout is fixed regardless of how you entered, and there is no durable right pane.

This design replaces that with **one composer-dominant, selection-driven workspace**. The load-bearing idea, inherited from the canonical spec and sharpened here:

> **THE MENTAL MODEL — "the Composer is a selection machine wrapped around a DAG."**
> A node *is* a chat thread that occupies a position in the graph. A seed is a chat thread that has *no* position yet. A palette block is a testable object you can audition. The right pane is a **pure function of what is selected**, and **Promote** is a single gesture that gives a thread a position — turning conversation (or a proven block) into a running step. You never switch "modes"; you change what is selected.

Three consequences fall out for free:

1. **"Dynamic to the starting point" is not two code paths.** Prompt-first and canvas-first are two *initial values of one `selection` state*, not two flows. We build one pane machine, not two apps.
2. **The engine stays frozen.** Everything the right pane does routes through endpoints that already exist (`test-step`, `/v1/chat/completions`, `/api/agents/{id}/chat`, `capture-spec`/`scaffold`, `run-async`) plus the workspace/index routes. Promote builds a definition dict and goes through `composerLoadDefinition` / `dfAddNodeFrom*` — never engine internals.
3. **The local sandbox becomes first-class.** A workflow's whole reason to exist here is to *operate on real local files and remember what it processed*. The C2 `Workspace` + C3 `WorkspaceIndex` runtime is bound into steps and rendered as inspectable artifacts, not hidden behind a run log.

### What this document adds over the 2026-06-28 spec

| The spec fixed | This document adds |
|---|---|
| 3-region layout, `selection.kind`, `renderRightPane`, seed→Promote, client thread store, nav | The **three on-ramps** unified into that one machine; the **palette bench** (click a block → live test, not a static form); the **sub-component builders** (agent / step / multi-agent) mapped to real engine kinds; the **local-sandbox operation** model (Workspace+Index bound to steps, research/lookup-before-process, make/edit/expand as first-class artifacts); a **phased, parity-preserving** build order anchored on the most buildable slice. |

---

## 2. The three-region layout, and the left sidebar in full

Composer is the **dominant** center. The layout is always the same three regions — the canvas is never hidden (that honors both hard-requirement #1 "composer is the dominant center surface" and Henry's canvas-native profile). "Prompt-first" is achieved by *what the right pane defaults to on a blank graph*, not by replacing the canvas.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR   enclave · COMPOSER · Runs · Library ▾ · Admin ▾     Project ▾  [Save][Run▶]│
├───────────────┬────────────────────────────────────────────┬───────────────────────┤
│ LEFT RAIL     │  CENTER — COMPOSER (dominant)               │ RIGHT — DYNAMIC PANE   │
│ (region 1)    │                                            │ renderRightPane(sel)   │
│ ⌘K filter…    │  ┌ CANVAS · Drawflow DAG ────────────────┐ │  none → empty state    │
│               │  │  [seed]→[step●]→⟨cross-examine ×3⟩→[out]│ │  seed → persona+model+ │
│ ▾ PROJECTS    │  │            ▲ selected                   │ │         workspace +    │
│ ▾ WORKSPACE   │  └────────────────────────────────────────┘ │         thread +       │
│ ▾ PALETTE     │  ┌ STEP INFO (structural, below canvas) ──┐ │         [Promote]      │
│   Roles       │  │ name · deps · inputs · outputs · gates  │ │  node → thread +       │
│   Agents      │  │ output parser · sandbox bind · last-run │ │         editable model/│
│   Skills      │  │ (model + prompt shown READ-ONLY mirror) │ │         prompt/options │
│   Plugins     │  └────────────────────────────────────────┘ │  palette→ config +     │
│   MCPs        │                                            │         LIVE test bench│
└───────────────┴────────────────────────────────────────────┴───────────────────────┘
        region 1 = LEFT SIDEBAR       region 2 = COMPOSER (canvas + step-info)     region 3
```

Every region is a design-system **`Panel`** — 1px hairline, **corner registration ticks** (`.corner-tr`/`.corner-bl` teal L-marks), a caps-tracked **`.ds-label`** header (`PROJECTS`, `PALETTE`, `COMPOSER`, and the right pane's `f(selection)` label). Warm-charcoal surfaces (`--bg #101413`, `--surface-card #171C1A`), teal (`--accent #2BD4B4`) as the single primary, mono for labels/IDs/data. Zero new tokens — every variable already ships in [app.css](../../api/static/css/app.css).

### Navigation (retires the flat tab list + Admin dropdown)

Top bar, four destinations, hash-routed (`#/<dest>`): **Composer** (this 3-region workspace, home) · **Runs** (run monitoring + DAG viz + the C3 autonomous surfaces) · **Library ▾** (Workflows/Agents/Models/Skills/Plugins/MCP catalogs) · **Admin ▾**. Non-Composer destinations reuse the existing `.tab-content` swap — no catalog/admin content is rewritten.

### Region 1 — the LEFT SIDEBAR (fully specified)

A single `Panel`, `--rail-w 248px`, three collapsible sections under **one** `⌘K`-focusable filter at the very top. That filter is the calm-keeper: it **cross-cuts all three sections at once** — typing `xql` surfaces the *xsiam-analyst* Agent, the *analyse_xql_gate* Skill, and any `xql`-named workflow in one list. One search, not five. (Client-side substring over the already-loaded `loadWorkbenches()` + `Projects` + `/api/workspaces` data — no new endpoint.)

```
┌ region 1 · LEFT SIDEBAR ─────────────────────────┐
│ ⌘K  filter projects · workspaces · palette…       │  ← one cross-cutting filter
│                                                   │
│ ▾ PROJECTS                            [+ New]     │  GET /api/workflows
│   ● xsiam-mdr            ok · 6 steps · 2h ago    │  StatusPip = last-run status
│   · brainstorm-decision idle · 5 steps           │  click → state.workflowId, rehydrate threads
│                                                   │
│ ▾ WORKSPACE                        [+ Bind dir]   │  GET /api/workspaces  (C2)
│   ◈ hr-vault      RO  · 2.4k files      ▤ idx     │  policy badge RO/RW; ▤ = has .enclave/index/*
│   ◈ scratch       RW  · 12 files                  │  click row → selection=palette(workspace)
│     ↳ ambient for new seeds/nodes ✓               │  selecting sets state.workspaceId (ambient)
│                                                   │
│ ▾ PALETTE   [Roles][Agents][Skills][Plugins][MCP] │  the 5 existing workbench-tabs verbatim
│   ⋮⋮ ▸ xsiam-analyst   reasoning  deepseek-r1 ▶   │  RoleChip: kind-tint + icon + mono id + ▶Test
│   ⋮⋮ ▸ web_search      tool                    ▶   │  ⋮⋮ grip = drag; row body = click
│   ⋮⋮ ▸ obsidian        mcp                     ▶   │
└───────────────────────────────────────────────────┘
```

**Section 1 · Projects locator.** Absorbs `.composer-project-bar` ([index.html:345](../../api/static/index.html)) out of the admin drawer. Flat list from `GET /api/workflows`, one `StatusPip` per row (last-run health). Click → set `state.workflowId`, rehydrate `localStorage['enclave.ws.'+workflowId]`. **`+ New`** clears the graph and sets `selection={kind:'seed'}` — it does *not* open a modal wizard; it drops you into the seed pane (see §4).

**Section 2 · Workspace picker (the sandbox handle, C2).** From `GET /api/workspaces`, one `EntityCard`-lite row per binding: name · root basename · **policy badge** (`RO` teal-dim = read-only vault / `RW` teal = writable scratch) · file count from `/stats`. The **selected** workspace sets `state.workspaceId` — the *ambient* sandbox every new seed/node inherits unless overridden. **`+ Bind dir`** posts `POST /api/workspaces` with a small form (name, root path, policy picker, `allowed_extensions`). A tiny worklist glyph (`▤`) appears on any workspace that already has an `.enclave/index/*` so durable progress is visible from the rail. Clicking a workspace row is a *palette selection* (`type:'workspace'`) → the right pane opens the **Workspace Bench** (§6).

**Section 3 · Palette.** The existing five workbenches verbatim (`loadWorkbenches` [main.js:7219], Roles/Agents/Skills/Plugins/MCPs, [index.html:507](../../api/static/index.html)), rendered as **`RoleChip`** atoms (kind-tinted 4px left mark using `--node-*`, Lucide icon, mono title, `⋮⋮` grip, and a `▶ Test` affordance). Mapping to the engine: **Roles** → `StepPrompt.role_ref`; **Agents** → seed a `kind:llm` node's `system_prompt` (`dfAddNodeFromAgent`); **Skills/Plugins/MCPs** → `ToolRef` (`plugin:'<id>.<tool>'` / `mcp:'<server>.<tool>'`).

**Three verbs on every palette entry** — all `data-action` (the `bench.*` dispatcher), zero new inline handlers:

| Verb | Gesture | Effect | Existing seam |
|---|---|---|---|
| **Drag → canvas** | grab `⋮⋮`, drop on canvas | add / equip a node | MIME `application/df-{template,agent,skill,tool,mcp}`; `dfInitEditor` drop + `wireWorkbenchDropHandlers` [main.js:7622] |
| **Drag → right pane (node selected)** | drop on the node's pane | append to that step's `tools[]`/`skills[]` | `dfAddTool`/`dfAddSkill` [main.js:5602/5617] |
| **Click (no drag)** | tap the row body | `selection={kind:'palette',paletteRef:{type,id}}` → right pane = **config + live test bench** | new; `bench.*` action |

**Test-in-place** is the headline of the sidebar and the whole of on-ramp (b): clicking a block gives a *live bench* in the right pane **without touching the canvas**. Agent → mini chat; Skill/Plugin/MCP → one-shot invoke form (params → run → JSON result); Workspace → the FILES/INDEX bench. Every bench footer carries a **`[Promote to step ▸]`** `ActionChip`, so kicking the tires and crystallizing are one continuous gesture through the same Promote machine as the seed ramp. (This is *The Bench*'s generalization grafted onto the spec's static-config pane — a strict improvement: the palette becomes a proving ground, not a form.)

---

## 3. The selection state model & the dynamic right pane

### State (owned by `core/state.js`, the single source of truth)

```
Workspace = {
  workflowId,                 // graph persists SERVER-side (dfSave→dfExportYaml→POST /api/workflows/{id})
  projectId,
  workspaceId,                // ambient C2 binding from the left rail
  selection: {                // the ONLY machine
    kind: 'none' | 'seed' | 'node' | 'palette',
    nodeId?,                  // kind==='node'
    paletteRef?,              // kind==='palette' → { type:'agent'|'plugin'|'mcp'|'workspace', id }
  },
  threads: { [key]: ChatThread },   // client-only, localStorage['enclave.ws.'+workflowId]
}

ChatThread = {
  key,                        // nodeId | 'seed' | 'bench:<type>:<id>'
  model, systemPrompt, persona?,
  workspaceRef?, contextRefs[],     // sandbox binding + grounding files
  tools[], options:{ webSearch, ... },
  messages: [ { role, content, ts, meta } ],
}
```

- **Node graph** = `dfNodeData` (keyed by Drawflow **integer** id; logical step id lives in `dfNodeData[id].id` — the dual-id trap; use `dfFindNodeIdForStep` [main.js:4991] for any re-key). Persists server-side, unchanged.
- **Threads** = client-only, per browser, survive reload. Reserved key `'seed'` is the pre-Promote conversation. `bench:*` keys are palette-audition threads. Stale-key pruning on load (drop `threads[nodeId]` whose node is gone; keep `'seed'`).
- `NodeData` is authoritative for a node's `model`/`systemPrompt`; the bound thread mirrors and writes back via `dfUpdateNodeData` [main.js:5544] so canvas node, step-info, and chat never drift.

### The state machine (Drawflow events *are* the transitions)

```
                    palette chip click
        ┌───────────────────────────────────────────┐
        ▼                                            │
   ┌─────────┐  pick persona / type   ┌────────┐  Promote to step   ┌────────┐
   │  none   │──────────────────────▶ │  seed  │ ─────────────────▶ │  node  │
   │ (empty) │                        │ thread │   re-key thread    │ thread │
   └─────────┘ ◀──────────────────────└────────┘ ◀───────────────── └────────┘
        ▲   blank-click / nodeUnselected   ▲   nodeSelected (canvas)   │
        │                                  └───────────────────────────┘
        └──────────── nodeRemoved while selected ─────────────────────┘

   nodeSelected      → selection={kind:'node', nodeId}
   blank-click       → selection={kind:'seed'}   (or 'none' to protect a mid-flight seed)
   palette click     → selection={kind:'palette', paletteRef}
   Promote           → new node carries thread; re-key threads['seed'|'bench:*']→threads[nodeId]
```

This **retires** `composerEnterStepEngage` / `composerExitStepEngage` / `window._composerEngagedNodeId` / `#step-engage-badge` ([main.js:830–959]). Selecting a node *is* engaging it.

### `renderRightPane(selection)` — a pure function of `selection.kind`

| `kind` | Right-pane content | Send target | Crystallize |
|---|---|---|---|
| **`none`** | Empty state: *"Pick a persona to start a seed, or select a step on the canvas."* (design-system `EmptyState`, blueprint watermark) | — | — |
| **`seed`** | Persona picker (`GET /api/agents`) · model picker (`GET /api/models`) · ambient workspace chip · `ChatThread('seed')` · **`MaturityMeter`** (seed→shape→chain→formalize→operate) | persona → `POST /api/agents/{persona}/chat`; else `POST /v1/chat/completions` | **`[Promote to step]`** (1 node) · **`[Crystallize to DAG ⚡]`** (multi-node, boot-sequence) |
| **`node`** | That node's `ChatThread` + **editable** `model`/`systemPrompt`/`options`/tools (the *writer*) | `POST /api/workflows/test-step` (node's live step def) | node already *is* a step |
| **`palette`** | The block's config **+ a live test bench** (agent→chat; skill/plugin/mcp→invoke form; workspace→FILES/INDEX) | agent → `/v1` or `/api/agents/{id}/chat`; workspace → workspace routes | **`[Promote to step ▸]`** |

Default on entering Composer: `node` if the graph has nodes (select first/last-edited), else `seed`.

### Seed → Promote (conversation becomes behavior)

The crystallization gesture, identical for seed and palette threads:

```
1. selection.kind==='seed'; operator picks persona+model+workspace, chats.
   Messages accumulate in threads['seed']; MaturityMeter lights as it gains
   a persona (shape), tools/context (chain), a passing test (formalize).
2. Click [Promote to step].
3. Mint a node: dfAddAgentAtCenter(persona) [main.js:4908]  (persona set)
                dfAddNodeFromTemplate(...)  [main.js:5132]   (else)
   carrying seed persona / model / systemPrompt / tools / contextRefs.
   → a kind:llm AgentStep (NOT an agent YAML — schemas are separate).
4. RE-KEY threads['seed'] → threads[newNodeId]   (history preserved;
   respect the dual-id split via dfFindNodeIdForStep).
5. selection={kind:'node', nodeId}; canvas selects it; right pane is now the node.
6. A fresh empty threads['seed'] awaits the next seed.

Empty graph  ⇒ promoted node is the DAG start.
Node selected at promote-time ⇒ append downstream with edge selected→new.
```

The re-key *is* the thesis: the same thread that was a chat is now a running step's memory, and every attachment (model, tools, context, workspace) rides along — so the agentic behavior is exactly the seed you built. This reuses the proven shape of `Pins.convert` ([main.js:8508], the closest existing analog: pin replies → build a definition → `composerLoadDefinition` + set canvas mode).

---

## 4. The three entry points, unified into one surface

There is no "blank screen" and no mode switch. The 3-region shell is always mounted; the on-ramps differ only in *what you touch first*, and all three land on the same `Promote`/node model.

```
                         ┌──────────────────────────────────────────┐
   (a) PROMPT-FIRST ────▶│  right pane defaults to  selection:seed   │──┐
       type intent       │  "Describe what you want to build."       │  │
                         └──────────────────────────────────────────┘  │
   (b) COMPONENT-FIRST ─▶  palette CLICK → selection:palette (bench) ───┼──▶  [Promote to step]
       test a block        prove it live in the right pane              │      → node on canvas
                         ┌──────────────────────────────────────────┐  │      → selection:node
   (c) CANVAS-FIRST ────▶│  drag chip onto canvas → node appears     │──┘      (all three converge)
       lay the graph      │  selected → right pane = its node thread  │
                         └──────────────────────────────────────────┘
```

### The blank Composer (how a first-timer is invited in)

The canvas stays visible and dominant (ghost START→END spine, `.composer-spine-dormant` [index.html:487]) with a centered dropzone card, **and** the right pane opens on the **Seed Console** (`renderRightPane({kind:'seed'})`):

```
┌───────────────┬────────────────────────────────────────────┬───────────────────────┐
│ ⌘K filter…    │  CANVAS — empty                             │ SEED CONSOLE (kind:seed)│
│               │  ┌──────────────────────────────────────┐   │ persona:[general ▾]     │
│ ▾ PROJECTS    │  │        ·  START ·································· END  │ model:[qwen3-coder ▾]   │
│   + New       │  │                                        │   │ workspace:[hr-vault RO▾]│
│               │  │   Drop a step here, click a block to   │   ├─────────────────────────┤
│ ▾ WORKSPACE   │  │   test it, or start a seed on the right │   │ "Describe what you want │
│   ◈ hr-vault  │  │                                     →  │   │  to build. I'll shape it│
│   ◈ scratch   │  └──────────────────────────────────────┘   │  into steps."           │
│               │  STEP INFO — (no step selected)             │  › you: crawl 8 vendor  │
│ ▾ PALETTE     │                                            │    pages, one note each,│
│   ⋮⋮ xsiam-an │                                            │    skip ones I have…    │
│   ⋮⋮ web_srch │                                            │ [ type…            ] ↵  │
│   ⋮⋮ obsidian │                                            │ MaturityMeter ●○○○○     │
│               │                                            │ [Promote to step][Crystallize⚡]│
└───────────────┴────────────────────────────────────────────┴───────────────────────┘
```

The invitation names all three ramps in one line of canvas copy. Prompt-first is the *default focus* (cursor in the seed input) without hiding the canvas.

> **Reconciling "composer-dominant" with "prompt-first."** The winning proposal hid the canvas until a node existed — which the judge flagged as in tension with hard-requirement #1 and under-serving a canvas-native operator (Henry). Resolution: the canvas is **always** present and the largest region; prompt-first is expressed by the right pane defaulting to the seed and by the existing chat/canvas/**focus** mode toggle (`ComposerSplit.setMode`, [composer-split.js]) — `focus` widens the right pane for a chat-forward feel, `canvas` widens the graph for a topology-forward feel. Same surface, one selection machine, **no fourth control and no hidden canvas.**

### On-ramp (a) — prompt-first (the hero)

Type intent into the Seed Console → unified `sendMessage('seed')`. When the conversation has shape: **`[Crystallize to DAG ⚡]`** runs Boot-Sequence — `POST /api/composer/capture-spec {messages[]}` → an *editable* spec card (`{goal, inputs[], checks[]}`, shown **before** scaffolding so the operator can correct it) → `POST /api/composer/scaffold` → `{definition}` → `composerLoadDefinition()`. The graph is now non-empty; the seed thread is re-keyed onto the start node. This is the workflow visibly condensing out of the chat. (`[Promote to step]` is the lighter one-node version.)

### On-ramp (b) — component-first

Pull from the palette, **click** a block → live bench in the right pane → prove it → **`[Promote to step]`**. You started from an object you trust, tested it in isolation, and it became the DAG start. Same Promote machine.

### On-ramp (c) — canvas-first (power user, first-class not second-class)

Drag a Role/Agent/Composite chip straight onto the canvas. The node appears selected; the right pane immediately shows its node thread + config. Wire outputs→inputs by dragging Drawflow ports. The seed thread remains available (empty `'seed'` key) via a blank-canvas click.

---

## 5. Sub-component builders

### 5a. BUILD AN AGENT (context + model + tools + memory + persona)

An **agent** is the *shape of a thread*. You build it as the seed/node/bench thread's editable header — you never leave the conversation to assemble one. Fields map 1:1 to `agents/*.yaml` (the [xsiam-analyst.yaml](../../agents/xsiam-analyst.yaml) shape) and to the `kind:llm` `AgentStep` a Promote emits.

```
┌ AGENT BUILDER  (right pane, seed | node | palette:agent) ─────────────┐
│ PERSONA   name · icon · role[reasoning ▾]                             │  → system_prompt + role
│ system_prompt ┌──────────────────────────────────────────────────┐   │  the WRITER of record
│               │ You are an expert Cortex XSIAM data-model … (mono) │   │  (step-info mirrors read-only)
│               └──────────────────────────────────────────────────┘   │
│ MODEL     [deepseek-r1:32b ▾]   temp 0.4   max_tokens 8192            │  ← GET /api/models (vLLM|Ollama)
│ CONTEXT   + Add from workspace…  ▸ workflows/xsiam-data-model.yaml    │  → context[] {type:file,value}
│           (opens GET /api/workspaces/{ws}/files + /search)            │    grounded in the real sandbox
│ TOOLS     web_search ×   obsidian.append ×   + drag Skill/Plugin/MCP  │  → tools[] (ToolRef plugin|mcp)
│           ↳ suggested: mcp:filesystem.read · analyse_xql_gate  [+]    │  ← POST /composer/assist
│ MEMORY    workspace: scratch   index: research-sites                  │  → the C3 index IS durable memory
│ ── test ─────────────────────────────────────────────────────────── │
│ › analyze these firewall logs…      « XDM maps src_ip → xdm.source…   │  live reply
│ [ Save as Agent ]              [ Promote to step ▸ ]                  │  two exits (see below)
└───────────────────────────────────────────────────────────────────────┘
```

- **Persona / system_prompt** → right-pane textarea (writer); mirrored read-only in step-info.
- **Model** → `<select>` from `window._chatModels` (`GET /api/models`, vLLM/Blackwell vs Ollama), writes `dfNodeData[id].model` via `dfUpdateNodeData`.
- **Context** → "Add from workspace" opens the bound workspace file picker (`/files` + `/search`); selected files become `context: [{type:file,value}]`. Context is grounded in the real local sandbox, not abstract RAG.
- **Tools** → drag Skills/Plugins/MCPs from the palette → `ToolRef`; `POST /api/workflows/composer/assist` surfaces "logical companion" chips inline as you set the role.
- **Memory** → a bound `Workspace` + named `WorkspaceIndex` *is* the durable memory — what the agent has processed, survives restarts (see §6).

**Two exits, honestly separate** (agents and steps are different schemas): **`[Save as Agent]`** writes `agents/<id>.yaml` for palette reuse; **`[Promote to step]`** mints a `kind:llm` `AgentStep` (persona → `system_prompt`, `tools[]`→`step.tools[]`) into the DAG. Which one you press decides where the thread lands.

### 5b. BUILD A STEP (logical + technical → a non-deterministic strategy that *is* the step)

A step is authored on **two axes**, split across two regions so structural DAG-wiring and conversational tuning never fight for the same column:

```
   CENTER · STEP INFO (structural / logical)          RIGHT · NODE THREAD (behavioral / technical)
   ─ binds dfNodeData ───────────────────────         ─ the editable writer + live test ──────────
   name            enrich                              model      [qwen3-coder ▾]
   depends_on      [seed]            ← DAG edges       systemPrompt  … (mono, editable)   ✎
   inputs          seed.ioc          ← dotted refs     options    temp · max_tokens · webSearch · tools
   outputs         [enriched]        ← min 1 enforced  ┌ chat ─────────────────────────────────┐
   output_format   json / parser                       │ › test: enrich 8.8.8.8                 │
   quality_gates   enriched != ""    ← validate_output │ « {"enriched": "AS15169 Google…"}      │
   sandbox         scratch / sites / *.md              │ [ send → POST /api/workflows/test-step ]│
   last run        ● ok · 1.2s       ← StatusPip       └────────────────────────────────────────┘
   model/prompt    (read-only MIRROR)                  SEND runs the live step def + accumulated
                                                       thread as messages[] → you converse the
                                                       step until it behaves.
```

"Apply logical + technical → a strategy that *is* the step" is literal: **draw structure in the center, converse the behavior in the right, `test-step` until it's right.** The test loop *is* the design loop. The non-determinism is the point — a `kind:llm` step is a persona+model+tools producing varied output *constrained* by the gates + parser you authored in the center; you author the constraints, not the answer. `dfRenderConfigPanel` [main.js:5250] already emits this whole editable form (Identity/Prompt/Outputs/Tools+Skills/Gates) — it *relocates* from the floating popup into the durable right region with near-zero logic change.

### 5c. MULTI-AGENT STEPS (3 logic agents cross-examining each other)

A multi-agent step is **one canvas node** that owns a branch/gather sub-DAG, mapped to the frozen engine's `kind:parallel` (+ optional `kind:loop` wrapper) — **no engine change**.

**Authoring gesture** (grafted from *The Bench*): shift/⌘-select 2–3 Agent chips in the palette → a rail action bar appears → **`[Compose as parallel step ▸]`**. That mints one composite node (composite tint + `Badge "PARALLEL·3"`). The branches are edited in the **right pane as a tabbed branch list** — deliberately *not* a nested canvas (Drawflow has no native nested-DAG rendering; a tabbed editor is buildable now and the honest MVP; an inline sub-canvas is a later enhancement, see Open Q5).

**Worked example — [`brainstorm-decision.yaml`](../../workflows/brainstorm-decision.yaml) (real, in-repo).** A thesis enters; three specialists interrogate it from different angles; a gather step synthesizes and adjudicates:

```
CANVAS (composite reads as ONE node)          RIGHT PANE (branch tabs of the selected composite)
┌──────┐   ┌───────────────┐   ┌─────────┐    kind: parallel   mode:[multi_model_concurrent ▾]
│ seed │─▶ │ research  ×3 ‖ │─▶ │ analyzer│    failure_policy:[fail_fast ▾]  max_concurrency: 3
│thesis│   │ (parallel)    │   └────┬────┘    ┌ branches ─────────────────────────────────────┐
└──────┘   └───────────────┘        ▼         │ [market] [validation] [user_value]  + drag Agent│
                                 ┌─────────┐   │ ── market (role:general) ─────────────  [test ▶]│
                                 │validator│   │ role_inline: "You are a market analyst. Assess │
                                 └─────────┘   │  the market… be concrete and skeptical."       │
                                  END(decision)│ task: "Analyze the market for: {{seed.thesis}}"│
                                               │ outputs: [market]                              │
                                               └────────────────────────────────────────────────┘
                                               ── gather: synthesize (role:reasoning) ──────────
                                               "Three specialists analyzed market/feasibility/
                                                user-value. Combine into one synthesis: strongest
                                                evidence for, biggest risks, open questions."
                                               inputs: market.market · validation.validation ·
                                                       user_value.user_value → research_synthesis
```

**Cross-examination across rounds** = wrap the parallel debate in `kind:loop`: `body:[the parallel step]`, `until: LoopTermination{type:gate, gate:'critic.approved == True', on_max_iterations:emit_best}`, `max_iterations:N`. Step-info shows an iteration badge + the gate predicate; the critic must populate its `final_summary` output (engine validator). To make branches literally rebut each other, the `gather` prompt is instructed *"for each claim in branch A, find the branch that disputes it."*

**Testing, honestly** (the judge's correctness bar): `test-step` only dry-runs a **single `kind:llm`** call. So each branch has an instant **`[test ▶]`** bench in its tab (real `test-step`), but the **whole composite runs via `POST /api/workflows/run-async`** and is watched in **Runs** (per-agent lanes). The UI never fakes a composite dry-run the frozen engine can't do — *test branch (instant) vs run step (real run)* is an explicit two-button truth.

---

## 6. Local sandbox operation (the C2 Workspace + C3 WorkspaceIndex)

This is the platform's reason to exist here: the workflow **operates on real local files and remembers what it processed**. The composer makes that visible end-to-end, tied directly to [workspace.py](../../api/services/workspace.py) and [workspace_index.py](../../api/services/workspace_index.py).

### Binding a step/agent to a Workspace + Index

- **Left rail** picks the *ambient* workspace (`state.workspaceId`) every new seed/node inherits.
- **Step-info** and the **agent builder** expose a **Sandbox block**: `{ target workspace (defaults to ambient), index name, file glob }` + a checkbox **"Skip items already done (consult index)."** This makes "operate on local files and remember what I processed" a *declared, inspectable* part of the step. A bound node's persona gets `make`/`edit`/`expand`/`read`/`list`/`search` wired as tools — thin HTTP wrappers over the workspace routes, mirroring the proven LangGraph `workspace_tools.py` (reference the pattern; do **not** re-implement).

### The research / lookup-before-process pattern

The canonical loop the composer dramatizes is the proven LangGraph indexer (`indexer_graph.py`): **look up before processing, remember what's done.** A step bound to a `WorkspaceIndex` renders a live worklist and drives:

```
index_next  (POST /index/{name}/next?requeue_stale=true)   ← claim a pending item → in_progress + persist
   │                                                          (crash-safe: the claim is durable)
   ▼  the agent scrapes / reasons
make / expand a note  (PUT /file · POST /expand under a ## heading)   ← the produced artifact
   ▼
set_status done + artifact  (POST /index/{name}/items/{id}/status)    ← never reprocessed
   ▼
loop until  GET /index/{name}.complete == true
```

Because `next_pending` claims (marks `in_progress` and persists *before* returning) and `set_status` is durable, the loop is **crash-resumable** — restart and it skips what's done. `requeue_stale` flips interrupted `in_progress` back to `pending`, so `next_pending` alone drives the whole thing. This is the C3 "agent's memory of what's done" primitive, surfaced as UI.

### make / edit / expand as first-class, inspectable artifacts

File writes are **not** buried in run logs — they are the artifact:

```
┌ WORKSPACE BENCH · selection=palette(workspace:scratch) ───────────────────────┐
│ [ FILES ]  [ INDEX ]                                    policy: RW ●  12 files │
│                                                                               │
│ INDEX: research-sites        done 14 · pending 3 · error 1   [Resume][Render] │  ← GET /index (non-mutating)
│ ┌───────────────────────────────────────────────────────────────────────────┐ │  Resume=POST /requeue
│ │ ● done    Palo Alto XDM ref     → sites/xdm-ref.md                         │ │  Render=POST /render (MOC)
│ │ ◐ in_prog CVE-2026-1337 writeup  (claimed)                                 │ │  artifact = provenance link
│ │ ○ pending Sigma rule cross-map                                            │ │
│ │ ✕ error   vendor blog (timeout)  note: 504                     [requeue]   │ │
│ └───────────────────────────────────────────────────────────────────────────┘ │
│ ── FILES tab ──────────────────────────────────────────────────────────────── │
│ make/edit/expand ▾   path: sites/xdm-ref.md   under ## Findings   [expand]     │  ← PUT/POST routes
│   + sites/xdm-ref.md   (created, 1.2kb)                    [open][diff]        │  make/edit/expand = SEEN
│   ~ sites/okta.md      (edited, 2 replacements)            [open][diff]        │
│ [ Bind this workspace + index to the selected step ]                          │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **INDEX tab** = the durable worklist board from `GET /api/workspaces/{ws}/index/{name}` (counts + item rows). **`[Resume]`** = `POST /requeue` (survives host/API restart — the visible durable-work proof for the 1.4.x fleet story). **`[Claim next]`** = `POST /next`. **`[Render MOC]`** = `POST /render` (Obsidian checkbox + wikilink map = a **run receipt** you open in the vault). Each item's `artifact` field links worklist → produced note (provenance drill-down).
- **FILES tab** = navigator (`/files?glob=`, `/search?q=`) + inline `make`/`edit`/`expand`. After any write the list refreshes and highlights new/edited rows; **`edit()` raising on absent find-text surfaces as a real error toast, never a silent no-op** ([workspace.py:194](../../api/services/workspace.py) raises 400). All paths are workspace-root-relative — the UI never sends host-absolute paths (absolute → 403 `WorkspaceViolation`).

### Worked example — the research/indexer loop rendered in the composer

```
1. Left rail → [+ Bind dir] → root ~/vault, policy RO for reading;  + [+ Bind dir] scratch RW for writing.
2. Seed pane: persona "research-agent", ambient workspace=scratch.
   Chat: "crawl these 8 vendor pages, one note each, skip ones I already have."
3. [Crystallize to DAG] → capture-spec → editable spec → scaffold → a FAN-OUT step
   (kind:parallel, mode:sharded, sharder over the pending index items).
4. Step-info · Sandbox: workspace=scratch, index=research-sites, "Skip already done" ✓.
   Add the 8 URLs → POST /index/research-sites/items  (idempotent by slug).
5. Run ▶ (run-async). Runs view shows per-agent lanes; the right-pane INDEX board
   ticks pending→in_progress→done live; each done item links to sites/<id>.md.
6. Host restarts mid-run. [Resume] → POST /requeue → the 2 interrupted items go back to
   pending; the run picks up clean and never reprocesses the 6 finished notes.
7. [Render MOC] → research-sites.md lands in the vault: a checkbox list + wikilinks = the receipt.
```

Seed threads can also attach `make`/`edit`/`expand` *mid-conversation*, so a persona writes real files into the bound dir while you talk to it — the sandbox is where crystallized conversation actually operates. (Write safety: see Open Q3.)

---

## 7. How this maps to the FROZEN engine, the df* canvas, and the composer DOM

**Nothing in the workflow engine changes.** `workflow_engine.py` / `step_executor.py` / `hook_bus.py` are frozen; we compose only via the HTTP seams and the workflow YAML.

### Send paths (all pre-existing except one additive field)

| Thread | Send target | Status |
|---|---|---|
| seed + persona | `POST /api/agents/{persona}/chat` | exists |
| seed, no persona | `POST /v1/chat/completions` | exists (today's `sendMessage` general branch, [main.js:994]) |
| node | `POST /api/workflows/test-step` | exists ([main.js:860]); **needs additive optional `messages[]`** for multi-turn |
| Crystallize | `POST /api/composer/capture-spec` → `/scaffold` | exists (Boot-Sequence) |
| companions | `POST /api/workflows/composer/assist` | exists ([main.js:5357]) |
| whole/composite run | `POST /api/workflows/run-async` + `GET /runs/{id}` | exists |
| graph persistence | `dfSave`→`dfExportYaml`→`POST /api/workflows/{id}` | exists |
| sandbox | `/api/workspaces/**` (C2) + `/index/**` (C3) | exists |

> **The ONE backend change in the entire plan.** `POST /api/workflows/test-step` today accepts a single `user_message` (`StepTestRequest`, [workflows.py:347], built into `messages` at [workflows.py:376]). To honor "each node has its own history," add an **optional `messages[]`** field: absent → today's single-shot behavior (fully back-compatible); present → the accumulated node thread. It is *additive and stateless* (no server session state), so it stays inside Approach A. This is spec Decision D1 = (a).

### Reused vs new (named seams)

| Concern | REUSE (exists) | NEW (build) |
|---|---|---|
| Canvas DAG | `dfInitEditor`@4832, `dfAddNodeFromAgent`@4947, `dfAddNodeFromTemplate`@5132, `dfUpdateNodeData`@5544, `dfExportYaml`@5803, `dfSave`@5868, `composerLoadDefinition`@7924 | — (unchanged) |
| Node config form | `dfRenderConfigPanel`@5250 (already writes to two mounts) | **repoint** its `#df-config-popup-body` target into a durable `#right-pane`; retire the floating popup |
| Selection → engagement | `dfEditor.on('nodeSelected')`@4839 already fires config render | make `#right-pane` the render target; **retire** `composerEnterStepEngage`/`_composerEngagedNodeId`/`#step-engage-badge`@830–959 |
| Chat send fork | `sendMessage`@979 already forks node→`test-step` vs `/v1` | wrap it as `sendMessage(threadKey)` over the thread store, not `window._composerEngagedNodeId` |
| Seed→Promote | `Pins.convert`@8508, `composerAddAgentAtCenter`@4908, `dfFindNodeIdForStep`@4991 | `seed-promote.js`: re-key `threads['seed']→threads[nodeId]` |
| State | `graphConfig`/`_chatModels`/`dfNodeData` globals | `core/state.js`: `Workspace` store + `localStorage['enclave.ws.'+workflowId]` |
| Left rail | `loadWorkbenches`@7219, `Projects.load`, DnD MIME seams, `wireWorkbenchDropHandlers`@7622 | `left-rail.js`: Workspace picker section + `⌘K` cross-cut filter + palette **click→bench** |
| Right pane | `dfFetchCompanions`@5357 (companion data) | `right-pane.js`: `renderRightPane(selection)` dispatcher + palette/workspace benches |
| Layout | `ComposerSplit` modes + `#composer-divider` | 3-column CSS grid (CSS, not JS); reuse chat/canvas/**focus** toggle — no 4th control |
| Sandbox | all `/api/workspaces/**` + `/index/**` routes | `workspace-bench` UI (FILES/INDEX) + step-info Sandbox block |

### Constraints honored

- No new inline `on*=` handlers, no new `window` globals — new code is `data-action`-only. (When relocating `dfRenderConfigPanel`, its legacy inline `onclick="dfAddTool/dfRemoveTool"` + `onkeydown` in the Tools/Skills block [main.js:5327–5331] are migrated to `data-action` in the same pass, not forward-carried.)
- Two Drawflow instances stay separate: `dfEditor` (composer, in `core/state`) vs RunsTab's private `_editor` (never exported).
- Composite steps are pure YAML builders through `dfExportYaml` — never client-side executors.
- Promote emits a `kind:llm` `AgentStep`, never an agent YAML (schema separation).

---

## 8. Phased implementation plan (P0…P7, each shippable & parity-preserving)

**Precondition (spec Stage 1):** the behavior-preserving modularization must be green on the parity harness (post-split `window` ⊇ golden, every inline handler resolves, zero console errors on boot) before Stage-2 UX lands. P0 below is the **first Stage-2 increment** on that verified base.

| Phase | Ship | Why it's the right increment | Proves |
|---|---|---|---|
| **P0 · The Right Pane** | 3-column CSS grid + `#right-pane`; **repoint** `dfRenderConfigPanel`'s popup mount into it; render off `nodeSelected`; retire `#df-config-popup`; add `nodeUnselected`→empty state | **The single most buildable slice in the field** (judge-verified): the full editable config form already exists and already writes to two mounts; this is near-zero logic, no engine change, no thread store yet. Creates the mount every later kind renders into. | "selection IS engagement" for `kind:node` |
| **P1 · State + Seed + Promote** | `core/state.js` (`selection` + `threads` + localStorage); `renderRightPane({kind:'seed'})` with persona/model/workspace pickers + chat; unified `sendMessage('seed')`; **`[Promote to step]`** re-key | The smallest surface that proves the whole thesis end-to-end: land in conversation, accumulate context in one thread, crystallize into a real node with history preserved. | prompt-first + crystallization |
| **P2 · Palette bench + ⌘K** | palette **click**→`kind:palette` live bench (agent chat / tool invoke); `[Promote]`; one cross-cutting filter | Turns the left rail into a proving ground; gives component-first its on-ramp; the filter keeps a dense rail calm. | component-first + the bench generalization |
| **P3 · Node multi-turn** | additive optional `messages[]` on `test-step` (the one backend change); node thread history | Makes "each node has its own history" real; unlocks node-bound tuning (ratings→per-agent, already prototyped). | per-node conversational authoring |
| **P4 · Workspace ambient + bench** | left-rail Workspace picker + Bind dir; `kind:palette(workspace)` **Workspace Bench** (FILES/INDEX board, Resume/Render, make/edit/expand artifacts) | Brings the C2/C3 sandbox into the surface as an operator-driven, fully-real tool (no engine bridge needed). | local sandbox operation you can SEE |
| **P5 · Step↔sandbox bind + research loop** | step-info Sandbox block {ws, index, glob, skip-done}; make/edit/expand as node tools; live worklist during `run-async` | Makes lookup-before-process a declared step property; renders the proven indexer loop in the composer. | durable, resumable autonomous operation |
| **P6 · Multi-agent composite** | multi-select→`[Compose as parallel step]`; composite node (`kind:parallel`/`loop`); right-pane **branch tabs**; honest test-branch vs run-step | Delivers the 3-agent cross-examination on the real engine kinds with no engine change; tabbed branches sidestep Drawflow's nested-DAG gap. | multi-agent depth |
| **P7 · Crystallize-to-DAG + nav** | `[Crystallize to DAG]` (capture-spec→editable spec card→scaffold, multi-node); top-bar nav (Composer/Runs/Library/Admin) | Completes the prompt-first hero ramp and retires the 3-menu tier. | conversation→whole workflow |

**The named first slice: P0 · The Right Pane.** It proves the model with the least code and the most safety — it establishes the durable right region on a seam (`nodeSelected` → config render) that provably already fires, reuses a form that already exists, touches no frozen engine code, and is verifiable by the existing parity harness. Every later phase is additive on top of a working node→right-pane binding.

---

## 9. Open questions for the operator

Ranked; the top three most affect the build.

1. **`test-step` multi-turn (the one engine-adjacent change).** Adopt the additive optional `messages[]` field now (spec D1 = a, recommended — it's stateless and back-compatible), or ship node chat single-shot for v1 and defer multi-turn? *Everything in P3 hinges on this.*
2. **Blank-Composer default posture.** On an empty graph, default the mode toggle to **canvas** (empty canvas dominant + right-pane seed — canvas-native, honors "composer-dominant") or **focus** (seed-forward, canvas minimized — maximally prompt-first)? This is the one remaining lever on how chat-first the landing feels for a canvas-native operator.
3. **Workspace write safety.** Default new bindings to **read-only** and require an explicit RW opt-in with the resolved root shown? And a **confirm-on-first-write per thread** when a seed/node persona is about to `make`/`edit` in a writable dir? (A persona with file tools can mutate the vault mid-chat — real and irreversible.)
4. **Palette-agent bench fidelity.** Send via `/v1/chat/completions` with the *edited* system_prompt (honors unsaved bench edits, but no real tool execution) or `/api/agents/{id}/chat` (saved config, real tools, ignores unsaved edits)? Default + a toggle, or pick one?
5. **Composite node depth.** Ship the **right-pane tabbed branch editor** first (buildable now), and treat an **inline nested sub-canvas** as a later enhancement? Or invest in the sub-canvas up front?
6. **Save-as-Agent vs Promote-to-step.** Keep them as two explicit buttons (agent YAML for reuse vs `kind:llm` AgentStep in the DAG), confirmed? Or auto-offer "also save as agent" on Promote?
7. **Thread persistence horizon.** Client-only `localStorage` per `workflowId` now, server-side deferred to 1.4.x fleet-awareness — confirm acceptable (a browser/cache change loses seed + node chat history).

---

### Appendix — design-system atoms this reuses (zero new tokens)

`Panel` (corner ticks + `.ds-label`) for each region · `RoleChip` (draggable, kind-tinted) for the palette · `EntityCard` for Projects/Workspace rows · `SeedChip` for the seed header (role/model/ctx) · `MaturityMeter` (seed→shape→chain→formalize→operate) as the literal "selection IS engagement" visual · `ActionChip` for `[Promote]`/next-best-action nudges · `StatusPip` + `ds-pip-pulse` (live status) + `ds-flow-dash` (live edges) · `WorkflowNode` (canvas atom, `--node-*` role tint) · `Badge` for kind tags (`PARALLEL·3`, `loop`) · `FitBar`/`Sparkline`/`TrendStat` for the calm run analytics. Warm-charcoal + teal, mono for the operator's voice, calm motion.

---

## Feasibility review & risks (verified)

> Adversarial pass on 2026-07-09 against the real tree (`api/static/js/main.js` @ 9,271 lines, `api/static/index.html` @ 2,477 lines, `api/routers/workflows.py`, `api/routers/workspaces.py`, `api/services/workspace.py`, `api/services/workspace_index.py`, `api/models/workflow_models.py`, `workflows/brainstorm-decision.yaml`). Every file the design cites was opened. **Verdict: sound and buildable as written.** The doc is unusually well-grounded — *every* `main.js` and `index.html` line citation resolves to the exact symbol claimed, the engine-freeze is genuinely honored, and the local-sandbox mapping is real, not hand-waved. The corrections below are scope-tightenings, not redesigns.

### A. Confirmed feasible (checked against source, not asserted)

- **Engine freeze is real and honored.** `POST /api/workflows/test-step` (`workflows.py:352`) calls `ollama.chat(...)` **directly** (`workflows.py:384`) via `ModelResolver`; it never imports or invokes `WorkflowEngine.run` / `StepExecutor`. The "one backend change" (`messages[]`) lands in `StepTestRequest` (`workflows.py:336`) + the message-build block (`workflows.py:376`) — both in the **router**, not in `workflow_engine.py` / `step_executor.py` / `hook_bus.py`. The freeze is not violated. ✅
- **Local-sandbox operation maps 1:1 to shipped routes — not hand-waved.** Every C2/C3 endpoint the doc leans on exists: `PUT /{ws}/file`, `POST /{ws}/edit`, `POST /{ws}/expand` (`workspaces.py:151/158/165`); `GET /{ws}/index/{name}`, `POST …/items`, `POST …/next?requeue_stale=`, `POST …/requeue`, `POST …/items/{id}/status`, `POST …/render` (`workspaces.py:186–236`). `edit()` **does** raise on absent find-text (`workspace.py:195`, `WorkspaceError` → HTTP 400 at `workspaces.py:83`); absolute/escaping paths raise `WorkspaceViolation` → 403 (`workspace.py:95/100`, `workspaces.py:77`). `next_pending(claim=True)` marks `in_progress` **and persists before returning** (`workspace_index.py:135–147`), so the "crash-resumable claim" narrative in §6 is literally true. This is the **strongest-grounded section** of the design. ✅
- **Multi-agent → `kind:parallel` is verbatim-accurate.** `workflows/brainstorm-decision.yaml` really is `kind: parallel` (`:46`), `mode: multi_model_concurrent` (`:52`), `failure_policy: fail_fast` (`:54`), branches `market`/`validation`/`user_value` each with `role_inline`+`task`+`outputs`, and `gather: synthesize` consuming `market.market`/`validation.validation`/`user_value.user_value` (`:99–114`). `ParallelExecutionConfig` (`workflow_models.py:104–112`) confirms the four modes + `max_concurrency` + `failure_policy`; `LoopTermination` (`:181–183`) confirms `type: gate` / `gate` / `on_max_iterations: emit_best|fail`; `AgentStep` carries `body` + `until` for `kind:loop` (`:484–485`). §5c is faithful to the engine. ✅
- **P0 seam already fires.** `dfInitEditor` wires `nodeSelected` → `dfRenderConfigPanel` (`main.js:4844`), and `dfRenderConfigPanel` already writes the full editable form into **two** mounts (`#df-config-panel` + `#df-config-popup-body`, `main.js:5254–5256`, "Write the same body to both targets" `:5343`). Relocating one mount into a durable `#right-pane` is real and low-risk. ✅
- **Crystallize path is wired.** `POST /api/composer/capture-spec` accepts `messages: List[ChatMessage]` (`composer.py:45`), `POST /scaffold` takes `{goal, inputs, checks}` (`composer.py:57–60`). The seed→spec→scaffold ramp in §4 needs no new endpoint. ✅

### B. Corrections & caveats (concrete)

1. **[Most important] v1 `system_prompt` vs v2 `StepPrompt` impedance is unstated — it bites §5c branch-testing.** `test-step` reads **only** `step.get("system_prompt")` and *requires it non-empty* (`workflows.py:358–363`). But composite **branches** (both in `brainstorm-decision.yaml` and the §5c mock) are authored as **v2 `StepPrompt` = `{role_inline, task, constraints}`** with `system_prompt = None` (`workflow_models.py:40–53`, `AgentStep.prompt` `:430`; the validator at `:603` *forbids* having both). So §5c's "each branch has an instant `[test ▶]` bench (real `test-step`)" **does not work as-is** — the client must first **flatten** `role_inline`+`task`(+`constraints`) into a single `system_prompt`/`user_message` before POSTing. This flatten adapter is small but real, and the doc should name it. (Single flat `kind:llm` canvas nodes are unaffected — `dfNodeData.system_prompt` is v1 and tests cleanly.)
2. **[Most important, P6] "Composite steps are pure YAML builders through `dfExportYaml`" understates P6.** `dfExportYaml` (`main.js:5803–5866`) today emits **only** flat steps: `system_prompt: |` (v1, `:5833`), `inputs`/`outputs`/`depends_on`/`tools`/`skills`/`output_parser`/`quality_gates`. It emits **no `kind:` field**, **no `branches`/`gather`/`config`** (mode/failure_policy), **no `body`/`until`**, and **no v2 `StepPrompt`**. P6 therefore requires a genuine `dfExportYaml` extension to serialize `kind:parallel` (nested branch steps + v2 prompts + `ParallelExecutionConfig`) and `kind:loop` (`body`/`until`). This is the **actual bulk of P6**, larger than the "tabbed branch editor" the phase table foregrounds. It stays client-side (no engine change), so the freeze holds — but estimate P6 as *serializer + tabbed UI + branch-flatten-to-test*, not just UI.
3. **P0 "near-zero logic" is optimistic; reframe as "small & low-risk."** Retiring the floating popup is more than repointing one function: `dfClearConfigPanel` **also** writes both mounts and calls `closeStepConfigPopup()` (`main.js:5902–5913`); the popup drag/dock/reposition/close machinery spans ~`main.js:5410–5535`; and the popup markup (`index.html:571–585`) carries **three inline `onclick=`** handlers (`composerTestStepInChat`, dock, `closeStepConfigPopup`). P0 must delete all of that, not just move a mount. Still a few-days PR — but "retire the popup," not "one-line repoint."
4. **P0 proves the *mechanism*, not the *thesis*.** P0 delivers "selection IS engagement" for `kind:node` (durable right pane on an already-firing seam) — that is de-risking plumbing. The headline claim ("conversation crystallizes into a workflow") is first demonstrated by **P1** (seed→Promote re-key). Set expectations: the smallest slice that *demos the new model* is **P0+P1**; P0 alone is the safe foundation.
5. **§5c "cross-examination across rounds" is feasible but not demonstrated by the cited file.** `brainstorm-decision.yaml` is single-pass (`parallel` → `gather` → `analyzer` → `validator`); it does **not** use `kind:loop`. Wrapping the parallel debate in a loop is *supported* (a `parallel` `AgentStep` is a valid `body[]` element; `LoopTermination` exists) but the doc implies the real file shows it — it shows only the parallel. State the loop wrapper as a proposed extension, and note its `emit_best` path requires the critic to populate `final_summary` (engine validator, per `workflow_models.py`).
6. **`test-step` multi-turn contract needs one explicit rule.** `StepTestRequest.user_message` is currently **required** (`workflows.py:347`, no default). When adding optional `messages[]`, specify the merge precisely: `messages = [{system}] + (req.messages if present else [{"role":"user","content": user_message}])`, and decide whether `user_message` stays required (carry latest turn, append history) or becomes optional. Additive + stateless holds either way; just pin it in the PR so back-compat is provable.

### C. Engine-collision risks

- **P0, P1, P2, P4, P7:** front-end or already-existing endpoints only. **No engine contact.** ✅
- **P3 (`messages[]` on `test-step`):** router-local (`StepTestRequest` + message-build in `workflows.py`). **Does not touch the frozen engine.** Only risk is the back-compat contract in B6 — a review checklist item, not an architectural risk. ✅
- **P5 (step↔sandbox bind, make/edit/expand as tools):** rides the shipped `/api/workspaces/**` routes; the engine executes unchanged. No collision. ✅ (Write-safety is a policy/UX question — Open Q3 — not an engine one.)
- **P6 (composite serialization):** `dfExportYaml` extension is client-side; composites **run** via `POST /api/workflows/run-async`, which executes **existing** `kind:parallel`/`kind:loop` the engine already ships. **No engine change** — provided the emitted YAML validates against `AgentStep`'s kind-shape validators (`workflow_models.py:599–806`), which the branch/gather/body/until fields already model. The only "collision-shaped" trap is B1/B2: emitting v2 prompts and validating them client-side before `run-async` rejects them.
- **Net:** nothing in the plan requires editing `workflow_engine.py` / `step_executor.py` / `hook_bus.py`. The freeze is safe end-to-end. ✅

### D. Tightened definition of the FIRST PR (P0 · The Right Pane)

Front-end-only; **zero backend, zero endpoints added** (the `messages[]` change is deferred to P3).

**Files to touch**
- `api/static/index.html` — add the `#right-pane` region; convert `.composer-split`/`.composer-grid` (`:467`) to a 3-column CSS grid (LEFT rail | CENTER canvas+step-info | RIGHT pane); **delete** the `#df-config-popup` block **and its 3 inline `onclick=`** (`:571–585`).
- `api/static/css/app.css` — the 3-column grid + the three region `Panel`s (corner ticks + `.ds-label` headers). No new tokens.
- `api/static/js/main.js` —
  - `dfRenderConfigPanel` (`:5250`): repoint the `#df-config-popup-body` write → `#right-pane` body; **keep** the `#df-config-panel` (workstream-tab) write for parity; remove the auto-open-popup call (~`:5410`).
  - `dfClearConfigPanel` (`:5902`): repoint clear → `#right-pane`; drop the `closeStepConfigPopup()` call.
  - Remove/neutralize the popup drag/dock/reposition/close handlers (~`:5410–5535`) and any `window.*` popup exports.
  - `nodeUnselected` (in `dfInitEditor`, `:4858/:4864`): render the right-pane **empty state** instead of the popup-close path (a first taste of `renderRightPane({kind:'none'})`).
  - **Migrate the 5 legacy inline handlers in the Tools/Skills block** (`:5327–5331`: `dfRemoveTool`/`dfAddTool`/`dfRemoveSkill`/`dfAddSkill` `onclick`/`onkeydown`) to `data-action` **in this pass** — retiring the popup is the moment to stop forward-carrying them (repo rule: no new inline handlers).

**Endpoints to add:** none.

**Acceptance check**
- Parity harness green: post-change `window` ⊇ golden; **every** inline handler resolves; **0** console errors on boot.
- Select a node → its full editable config (Identity/Prompt/Outputs/Tools+Skills/Gates) renders in the durable `#right-pane`; edits still flow through `dfUpdateNodeData` (`:5544`) and repaint the canvas node card.
- Blank-canvas click / `nodeUnselected` → right-pane empty state.
- `grep -n "df-config-popup" api/static/{index.html,js/main.js}` → **no** live references remain (markup + handlers gone); the workstream `#df-config-panel` tab still mirrors (parity preserved).
- `grep -nE "onclick=|onkeydown=" ` over the relocated config block → **zero** (all migrated to `data-action`).

### E. Single most important correction

**Name the v1↔v2 prompt-shape boundary explicitly, and re-scope P6 around it.** Everything the operator *tests* (`test-step`) and everything the current canvas *serializes* (`dfExportYaml`) speaks **v1 flat `system_prompt`**, but every **composite branch** the design showcases (§5c, `brainstorm-decision.yaml`) is **v2 `StepPrompt{role_inline, task}`**. Two concrete consequences the doc must absorb: (1) branch `[test ▶]` needs a client-side **flatten adapter** (v2 → `system_prompt`/`user_message`) before it can hit `test-step`; (2) P6's real work is **extending `dfExportYaml`** to emit `kind:parallel`/`kind:loop` + v2 prompts, not the tabbed UI. Neither breaks the frozen engine — but left unstated, they are exactly where a P6 build would stall. Fold this boundary into §5c and the P6 row, and the plan is clean to execute.
