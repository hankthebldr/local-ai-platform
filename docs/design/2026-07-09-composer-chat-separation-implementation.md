---
title: Composer / Chat Separation + Context Split — Implementation Plan
date: 2026-07-09
status: proposed
supersedes-direction: chat+canvas unified
surface: api/static/ (index.html shell + js/** modules), engine FROZEN
reuses: 2026-07-09-unified-object-model-library-alignment.md (EntityMeta / ObjectShell / AssetPeek / Promote)
revises: 2026-07-09-composer-workflow-builder-design.md (retires the chat↔canvas selection-machine as a single surface)
---

# Composer / Chat Separation + Context Split — Implementation Plan

> **The pivot.** The prior composer design unified chat + canvas into one
> selection machine (`ComposerSplit` chat/canvas/focus modes). Henry has
> revised that: **chat and canvas are two separate tabs.** This plan makes
> the Composer a pure canvas builder, lifts the chat dock into a
> configurable **Chat** tab, and splits the conflated Context tab into
> **Research** (artifact-building) and **Context** (run observability).
> Nothing is deleted — every current capability is *moved*, and the
> bidirectional couplings become explicit cross-tab bridges. Engine stays
> frozen; all new wiring is `data-action` with no new window globals.

---

## 1. Executive summary & the mental model

Today ENCLAVE crams four surfaces into two tabs. `#tab-dashboard` ("Composer")
stacks a Drawflow canvas, a full chat dock (`#agent-chat-dock`), and a
workstream inside one `.composer-split` CSS grid switched by `ComposerSplit`
chat/canvas/focus modes. `#tab-documents` ("Context") is assembled at runtime
by one relocator ([main.js:4532](../../api/static/js/main.js)) that folds a
knowledge graph, deep-research, RAG documents, and a role library into a single
scroll. The result conflates *building* with *conversing* and *artifact
research* with *run observability*.

This plan separates them into **four clean surfaces**, each with one job:

| Surface | Tab | Section | One-line job |
|---|---|---|---|
| **Composer** | `#tab-dashboard` (id kept) | Build | Canvas-DOMINANT DAG builder — chain agents/MCPs/skills/prompts into an ordered workflow. |
| **Chat** | `#tab-chat` (new) | Build | Configurable **launchpad / persona workbench** — load an agent+tool+skill+hook+context config, prove it live, pivot into an artifact or workflow. |
| **Research** | `#tab-research` (promoted) | Build | Obsidian-node artifact **forge** — RAG, deep-research, doc→agent, role library, the knowledge subgraph, C2/C3 workspace runtime. |
| **Context** | `#tab-context` (new) | Operate | Run-metadata **observability** — the workflow_run/provenance subgraph + session/context store, co-located with Runs. |

### The mental model

```
   BUILD ────────────────────────────────────────────  OPERATE ───────────
   ┌───────────┐   ┌───────────┐   ┌───────────┐        ┌────────┐ ┌────────┐
   │  COMPOSER │   │   CHAT    │   │ RESEARCH  │        │  RUNS  │ │CONTEXT │
   │  canvas   │◄─►│ launchpad │   │  forge    │        │ instance│ │ run-   │
   │  builder  │   │ (persona) │   │(artifacts)│        │  observ │ │ meta   │
   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘        └────┬───┘ └───┬────┘
         │ chain          │ configure     │ craft              │ watch    │ map
         │  the parts     │  & prove      │  the parts         │  a run   │  the run
         └───── the parts flow: Research forges → Library catalogs → ─────┘
                Chat proves → Composer chains → Runs executes → Context maps →
                Capture loops back to Research
```

Three sentences to hold in your head:

1. **Composer is where you *build*.** It is a canvas and nothing else — a DAG of
   proven parts. No chat.
2. **Chat is where you *configure and prove a part*, then jump off.** A config
   header loads a full agent/tool/skill/hook/context; you converse to tune it;
   one gesture crystallizes the conversation into a workflow on the canvas, saves
   the persona as an agent, or files a research artifact. It is the *jumping-off
   point into every other surface*.
3. **Research forges the parts; Context maps the runs.** The old Context tab's
   "conjoined research + observability graph" is split by the node-`type` tag
   `graph_service` already emits — one `/api/graph` build, two filtered views.

The couplings that stitch these together (`step-engage`, model write-back,
`+seed`, `AgentTuning`, `syncCompositionModelsToChatPicker`, Pin→convert,
BootSequence scaffold) are **features, not incidental glue** — they are the
"jumping-off point into supporting workflows" Henry asked for, preserved as
explicit cross-tab bridges (§7).

---

## 2. The completed canvas-DOMINANT Composer (`#tab-dashboard`)

The Composer is *completed*, not rebuilt. Every `df*` capability stays byte-for-byte
([main.js](../../api/static/js/main.js) `dfInitEditor`@4832, `dfAddNodeFromAgent`@4947,
`dfExportYaml`@5803, `composerLoadDefinition`@7924, and the whole family). What
changes is **subtraction**: the chat dock leaves, the `ComposerSplit` mode machine
retires, and the canvas inherits the freed viewport.

### 2.1 Layout after the split

```
COMPOSER  #tab-dashboard (Build) — canvas-DOMINANT, chat removed
┌──────────────────────────────────────────────────────────────────────┐
│ admin drawer ▸ [ID][Name][Role][Category][Desc] · Project ▾ · Save … │  #df-wf-* + #project-select
├───────────┬──────────────────────────────────────────────────────────┤
│ PALETTE   │  ▶START(seed ✎)                              [zoom −/+/⛶] │  DfSeedSchema
│ Roles     │      │                                                     │
│ Agents    │   [analyzer]──▶[retriever]──▶[composer]      ┌──────────┐  │
│ Skills    │        │            │            │           │ Step Cfg │  │  #df-config-popup
│ Plugins   │   (auto-chain · depends_on wiring)   ■END    │ id/role  │  │  (drag/dock/Esc)
│ MCPs      │                                              │ prompt   │  │
│ ─────────  │                                              │ outputs  │  │
│ object    │                                              │ gates    │  │
│ cards →    │                                              │ tools    │  │
│ Peek/Promote│                                             └──────────┘  │
├───────────┴──────────────────────────────────────────────────────────┤
│ WORKSTREAM:  [Step Config] [Active Run] [History]   Run▶  Run▶live  ◼ │  #composer-workstream
└──────────────────────────────────────────────────────────────────────┘
```

The chat pane that used to occupy `.composer-split` grid column 1 is gone; the
canvas panel (`#composer-canvas-panel`@543) expands to fill it. The palette
(left), the floating Step Config popup (`#df-config-popup`@571), the START/END
anchor spine, and the bottom workstream (`#composer-workstream`@796) are exactly
where they are today.

### 2.2 What STAYS (unchanged)

| Capability cluster | Anchors | Note |
|---|---|---|
| Palette workbenches (Roles/Agents/Skills/Plugins/MCPs) | `composerSwitchBench`, `renderAgentsWorkbench`, `loadWorkbenches`; `/api/agents` · `/api/plugins` · `/api/mcp/servers` | Rendered as object cards → AssetPeek/Promote apply (§8). |
| Drawflow canvas: place/drag/connect/select | `dfInitEditor`@4832, `dfNodeHtml`, `dfOnConnectionCreated` | `window.dfEditor` singleton; guarded init. |
| Add nodes: templates (14) + agents (drag/click) | `dfAddNodeFromTemplate`, `dfAddNodeFromAgent`@4947, `composerAddAgentAtCenter`, `dfStepTemplates` | Auto-chain via `dfAutoChain`. |
| Node config: id/name/role/model/prompt/outputs/decision/tools/skills/gates | `dfRenderConfigPanel`, `dfUpdateNodeData`, `dfAddGate`(13 ops), `dfFetchCompanions` (`/api/workflows/composer/assist`) | All `data-action` (`df.node-field`, `df.gate-*`). |
| START/END anchors + seed schema | `dfAddAnchors`, `DfSeedSchema.open` (df-seed-schema.js), `dfSeedSchema` | Round-trips `context.inputs`. |
| Zoom / fullscreen / auto-layout | `dfZoomIn/Out/Reset`, `dfToggleFullscreen`, `dfAutoLayout` (dagre LR) | Fullscreen is class-based (`.is-fullscreen`). |
| Export/Copy YAML · Save · Import YAML · Import/Export Bundle | `dfExportYaml`@5803, `dfSave` (`/api/workflows/save`), `dfDoImport`, `dfImportBundle` (`/api/workflow-index`) | Serializer untouched. |
| New/Clear/Load wizard + metadata toolbar | `WorkflowBuilder.open` (builders.js), `composerNewWorkflow`, `composerLoadDefinition`@7924, `#df-wf-*` | See §4 for the load-vs-append distinction. |
| Run ▶ / Run ▶ live / Stop + live overlay + workstream | `dfRunWorkflow`, `dfRunWorkflowLive` (`/api/workflows/run-async`), `dfApplyRunState`, `ComposerWorkstream` | Hands `run_id` to the workstream poller. |

### 2.3 What COMPLETES it (the subtraction)

| Action | File · anchor | Change |
|---|---|---|
| Retire `ComposerSplit` chat/canvas/focus mode machine | composer-split.js `setMode`@94; `#composer-mode-*`@690-697, `#composer-fmode-*`@471-474 | Delete the six mode buttons + the `mode-canvas`/`mode-focus` sizer. Keep `setSpinePrimed`/`toggleSpine`. Re-express `focus` as `dfToggleFullscreen`. |
| Remove the chat-vs-canvas divider | `#composer-divider`@478; `_wireDrag`/`_applyFrac` (composer-split.js) | `--chat-frac` + `CHAT_FRAC=58`/`CANVAS_FRAC=30` obsolete; `enclave.composer.split` localStorage key retired. |
| Reframe the spine ghost CTA | `ComposerSplit.focusChat` (focuses `#prompt`); spine "Start in chat ↑" | Repoint to `switchTab('chat')` — "Draft in Chat →" (a cross-tab jump, not an in-pane focus). |
| Extract the chat dock | `#agent-chat-dock`@612-794 | Lifts to `#tab-chat` (§3, §4). |
| Confirm the project bar's home | `#project-select`@348, `Projects.*` | **Decision G1** — keep in the Composer admin drawer (default) or re-home under Build. |
| Quarantine the legacy runner | `setWfMode`@4822, `#wf-composer` | **Decision G5** — legacy Catalog runner, separate from Composer/Runs; verify not orphaned (§10). |

`ComposerView.init()` ([composer-view.js](../../api/static/js/workspace-legacy/composer-view.js))
still fires on `switchTab('dashboard')` and still runs `dfInitEditor` + `dfInitPalette`
+ `loadWorkbenches` + `composerSwitchBench('steps')`. **One line moves out:**
`loadAgentsForSelector()` (which populates the chat agent picker) relocates to
`ChatView.init()` (§3.3).

---

## 3. The new Chat tab (`#tab-chat`) — configurable launchpad / persona workbench

**Identity (the winning spine, grafted with the launchpad config-header):** Chat is
a **Persona Workbench** realized as a **configurable launchpad**. You compose a live
*launch config* — agent + model + tools/skills/hooks + system-prompt + context — in
a **Config Header** above the transcript, converse to prove the persona works, then
**pivot in one gesture** into an artifact, a scaffolded workflow on the Composer
canvas, or a research note. It is the jumping-off point; every other surface is a
pivot target.

### 3.1 Layout

```
CHAT  #tab-chat (Build) — CONFIGURABLE LAUNCHPAD / PERSONA WORKBENCH
┌──────────────────────────────────────────────────────────────────────┐
│ CONFIG HEADER (composes the launch state):                             │
│   [Agent ▾] [Model ▾] [Role→sysprompt ▾] [🔧 tools/skills] [⛓ hooks]  │
│   [🌐 web ⚙]  [ context ▾ ]        step-engage: ⟨node #4⟩  + seed      │  #step-engage-badge
│   ┌ system prompt editor ─────────────────────────────────────────┐   │  #system-prompt
│   │ Define persona, tone, constraints. Applied role=system / turn. │   │
│   └────────────────────────────────────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────┤
│ system-impact strip:  API● Ollama●  CPU▓▓  MEM▓▓  [models ▾]           │  #chat-system-strip (IDs verbatim)
├──────────────────────────────────────────────────────────────────────┤
│ #messages                                                              │
│   ▸ you: …                                                             │
│   ▸ assistant: …   [★ rate] [copy] [📌 pin] [→ step]                   │  ChatRating · Pins · ChatCode
│     sources · provenance rail · model·backend chip                     │
├──────────────────────────────────────────────────────────────────────┤
│ [Threads ▾  + New]   #prompt _______________________________  Send    │  Threads · sendMessage
│ PIVOTS ▸ Save as agent  ▸ Send to Composer as a step  ▸ Boot Sequence  │
│         ▸ Pins → workflow  ▸ Send to Research                          │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 The Config Header — "load different agent/tool/skill/hook/context configs"

This is the direct realization of Henry's "highly customizable prompt experience."
It **re-groups existing controls, it does not rebuild them**, then adds net-new
additive mounts for the config kinds that have no picker yet:

| Config slot | Mechanism | Status |
|---|---|---|
| **System prompt** (the customizable prompt) | `#system-prompt`@724, `getSystemPromptMessage`@742, `toggleSystemPrompt`; localStorage `enclave.chat.systemPrompt` | Exists — re-grouped into the header. |
| **Role → prompt** loader | `#sysprompt-role-select`@717, `applyRoleAsSystemPrompt`@769, `populateSystemPromptRoles`; `/api/roles` | Exists — re-grouped. |
| **Agent / persona** | `#agent-select`@703, `onAgentSelectionChanged` → `window._chatAgent`; `/api/agents` | Exists — re-grouped. |
| **Model** | `#model-select`@707, `onChatModelChanged`, `loadModels`@457 (incl. "From composition" optgroup) | Exists — re-grouped. |
| **Web-search tool** | `#search-toggle`, `toggleSearch`; settings `/api/inventory/settings/search` | Exists — re-grouped as a tool toggle. |
| **Tools / skills** attach | **NEW** `data-action` picker over `/api/plugins` + `/api/mcp/servers` (same object surface the palette uses) | Additive — net-new mount. |
| **Hooks** attach | **NEW** `data-action` picker (6-hook lifecycle) | Additive — net-new mount. |
| **Context** attach | **NEW** `data-action` picker over `/api/documents` / project context | Additive — net-new mount. |

The additive pickers reuse the unified object surfaces (§8) — a tool in the Chat
header is the same object a palette bench drags onto a node.

### 3.3 Conversation + `ChatView.init()`

The send/receive loop and everything below the header move **verbatim**
(`sendMessage`@979 → `/v1/chat/completions` raw OR `/api/agents/{id}/chat`
scoped; rich rendering `renderMarkdown`/`renderCitations`/`renderSources`/
`renderProvenanceRail`; `ChatRating` → `/api/feedback/messages`; `Threads` →
`/api/conversations` with 15s autosave; `exportSession` → `/api/exports/save`;
`#chat-system-strip` health poller). A new `ChatView.init()` module (mirroring
`ComposerView.init`) mounts the chat-specific loaders on tab entry:

```
ChatView.init()  ← invoked by  if (name === 'chat') ChatView.init();   // switchTab ladder
  ├─ loadAgentsForSelector()      // moved out of ComposerView.init
  ├─ loadModels()                 // populates #model-select + "From composition"
  ├─ populateSystemPromptRoles()  // role library → sysprompt loader
  └─ Threads.restoreActive()      // rehydrate the current thread
```

### 3.4 Pivots — the jumping-off gestures

| Pivot | Gesture | Mechanism | Target |
|---|---|---|---|
| **Crystallize conversation → workflow** | Boot Sequence "run this with my agents" | `BootSequence.dispatch` → `/api/composer/capture-spec` + `/scaffold` → `composerLoadDefinition` | Composer canvas (rebuild) |
| **Pins → workflow** | pin ≥2 replies, Convert | `Pins.convert` → `composerLoadDefinition` | Composer canvas (rebuild) |
| **Send THIS reply/persona → a step** | "Send to Composer as a step" | **`dfAddNodeFromAgent`@4947 (append)** — *not* `composerLoadDefinition` (which wipes) | Composer canvas (append onto existing DAG) |
| **Save as agent** | freeze the proven persona | `POST /api/agents` | Library/Agents → palette + Chat selector |
| **Send to Research** | file a reply as an artifact | **NEW** → `ResearchArtifacts.captureRaw` → `/api/feedback/artifacts` | Research pane |
| **Node-bound chat** | select a Composer node → converse with it | `composerEnterStepEngage` → `sendMessage` step branch → `/api/workflows/test-step` | Cross-tab (§4.4, §7) |

The **append-vs-rebuild** distinction is load-bearing: "crystallize the whole
conversation" rebuilds the canvas (`composerLoadDefinition`); "send this one part"
appends a single node (`dfAddNodeFromAgent`) so an in-progress DAG is never wiped.

---

## 4. The exact separation seam

### 4.1 DOM move — what leaves `#tab-dashboard`

The chat dock is a self-contained `.panel` sitting as one grid column inside
`.composer-split`. Cut it whole:

```
BEFORE (#tab-dashboard):                    AFTER:
  .composer-split                             #tab-dashboard
    ├─ admin drawer (#df-wf-*, #project-select) ├─ admin drawer (#df-wf-*, #project-select)
    ├─ #composer-fmode-* float toggle    ✗DEL   ├─ #composer-canvas-panel (fills width)
    ├─ #composer-divider                 ✗DEL   └─ #composer-workstream
    ├─ #composer-canvas-panel  ───────┐
    ├─ #agent-chat-dock  ────────┐    │        #tab-chat  (NEW)
    │    ├─ #chat-system-strip   │    │          └─ #agent-chat-dock  ◄── moved verbatim
    │    ├─ #thread-bar          │    │               ├─ CONFIG HEADER (re-grouped controls)
    │    ├─ agent/model/sysprompt│MOVE│               ├─ #chat-system-strip  (IDs verbatim)
    │    ├─ #messages / #prompt   │    │               ├─ #thread-bar
    │    ├─ #step-engage-badge    │    │               ├─ #messages / #prompt
    │    ├─ #pins-meter           │    │               ├─ #step-engage-badge
    │    └─ #nba-container        │    │               ├─ #pins-meter
    └─ #composer-workstream ──────┘────┘               └─ #nba-container
```

**Every element ID moves verbatim.** This is the mechanical no-loss guarantee:
the `#chat-system-strip` poller targets (`#cpu-value`, `#mem-value`, `#cpu-cores`,
`#mem-detail`, `#models-content`, `#cpu-arc`, `#mem-arc`, `#status-content`) keep
resolving; `ChatRating.nextId`/`Pins` msg-ID contracts stay stable so
`Threads.rehydrate()` + pin `syncButtons()` survive; existing inline handlers move
with the markup (the no-new-inline rule bans *new* handlers, not lift-and-shift).

### 4.2 Nav + routing wiring (additive only)

Add two nav buttons with the sanctioned pattern — **no new global, no new inline
handler**:

```html
<!-- in .tab-nav, Build section -->
<button class="tab-btn" data-tab="chat"     data-action="switch-tab">Chat</button>
<button class="tab-btn" data-tab="research" data-action="switch-tab">Research</button>
<!-- Operate section -->
<button class="tab-btn" data-tab="context"  data-action="switch-tab">Context</button>
```

```js
// register ONCE (shell/actions.js consumer) — switchTab already global via legacy-bridge
Actions.click({ 'switch-tab': el => switchTab(el.dataset.tab, el) });
```

They auto-join the WAI-ARIA tablist + Arrow/Home/End nav (the
`DOMContentLoaded` loop over `.tab-nav .tab-btn[data-tab]`@242) and become
hash-deep-linkable (`#/chat`, `#/research`, `#/context`) for free — the router
whitelist checks `getElementById('tab-' + name)`.

Add three additive loader lines to `switchTab` ([main.js:133-216](../../api/static/js/main.js)):

```js
if (name === 'chat')     ChatView.init();          // NEW
if (name === 'research')  initResearch();           // already at :174 — un-hide the panel
if (name === 'context')   ContextView.init();       // NEW (§5)
// documents → research alias (reuse the existing 'discover'→'inventory' remap at :94)
if (name === 'documents') { name = 'research'; }     // top-of-function remap
```

`switchTab`'s unknown-tab guard (`if (!panel) return;`@103) already makes added
tabs regression-safe.

### 4.3 Retire the `ComposerSplit` mode machine (repoint the 4 callers)

`setMode('chat')` has no pane after extraction. The mode buttons + divider are
deleted; the **only load-bearing callers** are the four `setMode('canvas')` sites
that reveal a freshly-built DAG. Centralize the reveal in `composerLoadDefinition`
and drop the rest:

| # | Caller | File · line | Today | After |
|---|---|---|---|---|
| 1 | `openWorkflowInComposer` | main.js:3705 | `switchTab('dashboard')` **then** `setMode('canvas')` | Delete the `setMode` line (redundant — already switches tab). |
| 2 | `composerLoadDefinition` tail | main.js:8070 | `if getMode()==='chat' setMode('canvas')` | Replace with `switchTab('dashboard')` — loading a def reveals the canvas. |
| 3 | `Pins.convert` | main.js:8503 | `composerLoadDefinition(defn)` + `setMode('canvas')` | Drop `setMode`; (2) now handles the reveal. |
| 4 | `BootSequence` confirm | boot-sequence.js:291 | `composerLoadDefinition` + `setMode('canvas')` | Drop `setMode`; (2) handles the reveal. |

`grep -n "setMode(" api/static/js -r` must return **zero** callers after this
(the definition in composer-split.js may stay as a no-op or be deleted).

### 4.4 How `seed → Promote` and `test-step` keep working across tabs

The bidirectional Chat↔Composer couplings read `window._composerEngagedNodeId`,
`window.dfNodeData`, and `dfUpdateNodeData`. **`sendMessage`'s step-engage branch
reads `dfNodeData` lexically (module scope).** Therefore:

> **Constraint:** Chat and Composer stay in the **same module scope** (monolithic
> `main.js`, or a shared bridge module). Full ES-module isolation is *deferred* —
> it would break the lexical `dfNodeData` read and the `dfUpdateNodeData`
> write-back. This satisfies "no new globals" by *reusing* the existing bridge,
> adding none.

The cross-tab round-trip after the split:

```
COMPOSER: click node  ──► dfEditor.nodeSelected
                          └─ composerEnterStepEngage(nid)   sets window._composerEngagedNodeId
                                                            shows #step-engage-badge (now in CHAT)
                          (optional) switchTab('chat')  ──► focus the bound conversation
CHAT:     type + Send  ──► sendMessage() sees _composerEngagedNodeId
                          └─ _sendStepMessage → POST /api/workflows/test-step   (engine-frozen)
CHAT:     change model ──► onChatModelChanged → dfUpdateNodeData(nid,'model',…)  (write-back)
CHAT:     "+ seed"     ──► composerSeedAgent → node.system_prompt += context
CHAT:     rate reply   ──► ChatRating.rate → AgentTuning.record(nid,…) → tunes test-step prompt
COMPOSER: node model   ──► syncCompositionModelsToChatPicker → "From composition" optgroup in CHAT
```

Promote (object → step) and the palette-as-objects surface are the unified
object-model seam (§8): a Research-forged agent, a Chat-proven persona, and a
palette card are one `EntityMeta` family, and `dfAddNodeFromAgent` is the append
path that turns any of them into a canvas step.

---

## 5. Context → Build + the Research vs Context split

### 5.1 The one hard seam: the graph

`#tab-documents` is glued by one relocator ([main.js:4532](../../api/static/js/main.js))
that `insertBefore`s the whole `#tab-research .research-layout` (knowledge graph +
deep-research) atop the RAG surface, then appends the role library. The single D3
`#graph-svg` is fed by one `GET /api/graph` whose nodes **already carry a `type`
tag** mixing research types (session/topic/source/agent) with observability types
(workflow_run/response + grounded_on/used_tool). Henry's "conjoined research +
observability graph is too messy" *is* this node-type mix.

**The split is a node-type FILTER, not a data migration.** `graph_service` already
emits `type`; the UI already has `#graph-link-filter` + legend. One build, two
filtered views.

```
              GET /api/graph  (one build)  +  /api/graph/rebuild
                     │
        ┌────────────┴──────────── node-type filter ───────────┐
        ▼                                                       ▼
  RESEARCH pane (#tab-research, Build)              CONTEXT pane (#tab-context, Operate)
  ● session ● topic ● source ● agent                ▪ workflow_run  ◆ response
  — uses / grounded_on (research edges)             — grounded_on / activated_skill / used_tool
  [rebuild][zoom][cfg][legend]  (chrome dup)        [rebuild][zoom][cfg][legend]  (chrome dup)
```

**Cross-type edges** (e.g. `agent → topic uses`, `response → source grounded_on`)
are assigned **per-edge** to their owning pane so neither view loses its anchors.
`initResearch()`'s `researchLoaded` single-shot guard becomes **per-pane** or the
second mount renders empty.

### 5.2 RESEARCH pane — the artifact forge (moves INTO Build)

Research re-seats under **Build** because crafting agents/mcps/skills/workflow
artifacts is *authoring*, not observability. It is the obsidian-node forge on the
unified asset structure (§8):

| Capability | Anchor | Endpoint |
|---|---|---|
| RAG docs: upload/list/search/stats/reindex/delete | `_uploadDocumentFile`, `loadDocumentsList`@4453, `searchDocuments`, `loadDocumentsTab` | `/api/documents` (+Chroma) |
| Deep research + results + Capture-as-artifact | `runDeepDive`@3160, `renderResearchResults`@3236, `ResearchArtifacts.captureRaw` | `/api/research/deep-dive`, `/api/feedback/artifacts` (keep `rag_ingested` loop) |
| Convert/Paste → Agent | `AgentGen.openFromDocument/openFromText` (library/agents.js) | over `/api/agents` |
| Build agent from research | `ResearchFlow.open`@8960 | agent create + seed chat |
| Role library | `loadRoles`, `#wf-roles-list` (id-promotion trick — preserve) | `/api/roles` |
| Knowledge subgraph (session/topic/source/agent) | `loadGraphData`@2279, `renderGraph`@2586, `#graph-svg` | `/api/graph` (research filter) |
| C2/C3 workspace runtime (make/edit/expand + durable index) | workspaces.py / workspace.py / workspace_index.py + langgraph research/indexer | `/api/workspaces/*` |
| Project artifact attachment | projects.py | `/api/projects/{id}/artifacts/{kind}/{id}` |

### 5.3 CONTEXT pane — run-metadata observability (Operate, tied to Runs)

| Capability | Anchor | Endpoint | Note |
|---|---|---|---|
| Run/provenance subgraph | `graph_service._build_workflow_nodes/_build_provenance_nodes`, provenance.py | `/api/graph` (run filter) | forked from the research graph |
| Session/context store | context.py (ContextStore/SessionManager/tool-calls/close/cleanup) | `/api/context` | **NET-NEW UI** over an existing backend (G3) |
| Context Trace producer graph (step→workspace keys) | `RunsTab._renderContextTrace`, `#runs-tab-context-body` | reads `run.context.*` | stays with Runs; co-located |

`ContextView.init()` (new) mounts the run-filtered graph + a session-store list
over `/api/context`. Because `/api/context` has no current UI, this pane is the one
surface that is *built*, not relocated — it fits the "only adding" constraint but
carries build risk pure lift-and-shift does not.

### 5.4 IA update against the shipped Build/Operate/Library/Admin rail

The shipped rail ([index.html:276-293](../../api/static/index.html)) groups
Composer+Workflow-Index (Build), Projects+Runs (Operate), Agents+Models+Context+
Plugins+Skills+MCP (Library), + the Admin dropdown. The new IA:

```
BEFORE                                   AFTER
─────────────────────────────────       ─────────────────────────────────
Build                                    Build
  · Composer      (dashboard)              · Composer      (dashboard)      ← canvas-only
  · Workflow Index                         · Chat          (chat)   NEW
Operate                                    · Research       (research) PROMOTED  ← from hidden
  · Projects                               · Workflow Index
  · Runs                                  Operate
Library                                    · Runs
  · Agents                                 · Context       (context) NEW  ← run-observability
  · Models   (inventory)                   · Projects
  · Context  (documents)  ✗ moves          Library
  · Plugins                                 · Agents
  · Skills                                  · Models   (inventory)
  · MCP                                     · Plugins · Skills · MCP
Admin ▾ (System / Cloud / Exports)       Admin ▾  (unchanged)
```

The old "Context" (`data-tab=documents`, under Library) is **removed from the nav**;
its RAG/research content moves to Research (Build), and the `documents → research`
remap in `switchTab` catches the ~5 hard-coded `switchTab('documents')` links, the
router whitelist, and the onclick-string fallback matcher (main.js:122). A new
"Context" (`data-tab=context`) appears under **Operate** meaning run-observability.

---

## 6. The consolidated regression-preservation checklist (no-loss contract)

Every current capability → its destination surface → a grep-able or click-able
acceptance check. Destinations: **CMP** Composer · **CHT** Chat · **RSCH** Research ·
**CTX** Context · **RUN** Runs (unchanged) · **XT** cross-tab bridge · **NAV** shell.

### A. Composer / canvas — all STAY (CMP)

| # | Capability | Anchor | Dest | Acceptance |
|---|---|---|---|---|
| A1 | Roles/Steps palette (14 templates) | `dfInitPalette`/`dfAddNodeFromTemplate` | CMP | drag card → node; 14 templates present |
| A2 | Agents palette (drag+click prefill) | `composerAddAgentAtCenter`/`dfAddNodeFromAgent`@4947 | CMP | click card → node w/ role+model+prompt; `_from_agent` set |
| A3 | Skills/Plugins/MCPs attach-onto-node | `renderSkillsWorkbench`/`wireWorkbenchDropHandlers` | CMP | drop on node → `node.skills/tools` grows |
| A4 | Workbench tab switcher | `composerSwitchBench` | CMP | each tab toggles `.workbench-pane hidden` |
| A5 | Canvas place/drag/connect/select | `dfInitEditor`@4832 | CMP | `window.dfEditor` set; connect → edge persists |
| A6 | Auto-chain | `dfAutoChain` | CMP | 2nd drop auto-wires START→…→END |
| A7 | Connections → depends_on | `dfOnConnectionCreated` | CMP | connect → YAML `depends_on` |
| A8 | Config: id/name/role/model | `dfRenderConfigPanel`/`dfUpdateNodeData` | CMP | edit role → node retint |
| A9 | Config: system prompt | `df.node-field system_prompt` | CMP | prompt survives export |
| A10 | Config: outputs + output_format | `dfAddOutput`/`dfFmtDescs` (7) | CMP | output in YAML + `output_parser` |
| A11 | Decision branch labels | `dfUpdateDecisionBranch` | CMP | DECISION pill + branch inputs |
| A12 | Attach/detach tools+skills | `dfAddTool/Skill/Detach*` | CMP | chip on node + panel |
| A13 | Quality gates (13 ops) | `dfAddGate/UpdateGate` | CMP | `[nG]` badge; YAML `quality_gates` |
| A14 | Companion suggestions | `dfFetchCompanions` `/composer/assist` | CMP | assist → suggested chips |
| A15 | Delete node | `dfDeleteNode` | CMP | node gone + `dfNodeData` cleaned |
| A16 | Floating Step Config popup | `#df-config-popup`@571; `enclave.stepConfigPos` | CMP | select → popup; drag persists |
| A17 | START/END anchors + seed schema | `dfAddAnchors`/`DfSeedSchema.open` | CMP | START ✎ → schema; `context.inputs` |
| A18 | Zoom in/out/reset | `dfZoomIn/Out/Reset` | CMP | scale changes |
| A19 | Fullscreen (Esc) | `dfToggleFullscreen`/`.is-fullscreen` | CMP | maximize; Esc exits |
| A20 | Auto-layout (dagre LR) | `dfAutoLayout` | CMP | nodes reflow LR centered |
| A21 | Export/Copy YAML | `dfExportYaml`@5803 | CMP | full YAML; copy → clipboard |
| A22 | Save workflow | `dfSave` `/api/workflows/save` | CMP | toast + refresh |
| A23 | Import YAML | `dfDoImport` | CMP | paste → canvas rebuilt |
| A24 | Import/Export Bundle | `dfImportBundle`/`composerExportBundle` `/api/workflow-index` | CMP | export → `.bundle.json` |
| A25 | New/Clear/Load wizard | `WorkflowBuilder.open`/`composerLoadDefinition`@7924 | CMP+XT | +New modal; Load rebuilds |
| A26 | Metadata toolbar | `#df-wf-*` | CMP | fields feed export/save |
| A27 | Run ▶ / Run ▶ live / Stop | `dfRunWorkflowLive`@... `/run-async`; `composerStopRun` | CMP→RUN | live → overlay + run_id to workstream |
| A28 | Live overlay + progress chip | `dfApplyRunState`/`#df-run-progress` | CMP | nodes tint queued/running/completed |
| A29 | Workstream (StepCfg/ActiveRun/History) | `ComposerWorkstream`/`#composer-workstream` | CMP | run → History tail + toasts |
| A30 | **Project context bar** | `#project-select`@348, `Projects.*` | **CMP (G1)** | `#project-select` renders + `onchange` fires |

### B. Chat dock — MOVE to CHT (couplings → XT)

| # | Capability | Anchor | Dest | Acceptance |
|---|---|---|---|---|
| B1 | Send/receive (raw OR agent) | `sendMessage`@979; `/v1/chat/completions` · `/api/agents/{id}/chat` | CHT | reply renders; both shapes |
| B2 | chatHistory/metadata state | main.js:733-735 | CHT | history grows; export reads it |
| B3 | System-prompt control | `getSystemPromptMessage`@742; `enclave.chat.systemPrompt` | CHT | prepended role=system/turn |
| B4 | Role→prompt loader | `applyRoleAsSystemPrompt`@769; `/api/roles` | CHT | pick role → textarea fills |
| B5 | Agent/persona selector | `onAgentSelectionChanged`→`_chatAgent`; `/api/agents` | CHT | scope note; hits `/agents/{id}/chat` |
| B6 | Model picker (backend-grouped) | `loadModels`@457; `_chatModels/_modelBackends` | CHT | grouped vLLM/Ollama |
| B7 | Web-search toggle | `toggleSearch`; `web_search:true` | CHT | badge + flag in body |
| B8 | Search-settings panel | `loadSearchSettings`; `/api/inventory/settings/search` | CHT | save persists |
| B9 | Thread switcher | `Threads`; `/api/conversations`; 15s autosave | CHT | +New; switch restores html+pins+ratings |
| B10 | Session export (MD) | `exportSession`@1175; `/api/exports/save` | CHT | .md download + server save |
| B11 | Per-message rate/copy | `ChatRating`; `/api/feedback/messages`; `enclave.chatRatings.v1` | CHT (XT→I8) | rate → POST; rehydrate on restore |
| B12 | Rich rendering | `renderMarkdown/Citations/Sources/ProvenanceRail` | CHT | md+sources+backend chip |
| B13 | Code-block hand-off | `ChatCode.copy/toStep`@709 | CHT (XT→I3) | copy works; →step → Pins |
| B14 | System-impact strip | `#chat-system-strip`@635; poller IDs | CHT header | **IDs verbatim** — poller keeps writing |
| B15 | Dock collapse/expand | `toggleAgentDock` | CHT | ▾ collapses |
| B16 | Seed system-msg / empty state | `#messages`@731 static msg | CHT | empty state shows seed |

### C. Context/Documents — SPLIT (RAG→RSCH, run-meta→CTX)

| # | Capability | Anchor | Dest | Acceptance |
|---|---|---|---|---|
| C1 | RAG upload (drop+input) | `_uploadDocumentFile`; `/api/documents` | RSCH | drop .md → in list; keyboard-focusable zone |
| C2 | RAG list + reindex/delete/→Agent | `loadDocumentsList`@4453 | RSCH | row actions fire; →Agent opens AgentGen |
| C3 | RAG semantic search | `searchDocuments`; `/api/documents/search` (`/query` alias) | RSCH | query → results; `/query` alias resolves |
| C4 | Doc stats tiles | `loadDocumentsTab`; `/api/documents/stats` | RSCH | count/chunks/backend |
| C5 | Convert doc → Agent | `AgentGen.openFromDocument` | RSCH | grounded agent wizard |
| C6 | Paste → Agent | `AgentGen.openFromText` | RSCH | agent wizard |
| C7 | Deep research | `runDeepDive`@3160; `/api/research/deep-dive` | RSCH | topic + depth 1-5 → report |
| C8 | Results + Capture-artifact + library | `renderResearchResults`@3236; `ResearchArtifacts`; `/api/feedback/artifacts` | RSCH | capture saved; `rag_ingested` cross-link (I11) |
| C9 | Build agent from research | `ResearchFlow.open`@8960 | RSCH | wizard → agent + seed chat |
| C10 | Knowledge subgraph (research nodes) | `loadGraphData`@2279; `#graph-svg` | RSCH | research types render; type filter |
| C11 | Run/provenance subgraph | `_build_workflow_nodes/_build_provenance_nodes` | **CTX** | run/response nodes filter into Context |
| C12 | Graph chrome (rebuild/zoom/cfg/legend) | `rebuildGraph`@2292/`graphZoom*`; localStorage | RSCH+CTX (dup) | chrome in both; config persists |
| C13 | Node/session detail peek | `showSessionDetail` | RSCH+CTX (by type) | research→RSCH, run→CTX |
| C14 | Role library | `loadRoles`; `#wf-roles-list` (id-promotion) | RSCH | roles render into VISIBLE mount |
| C15 | Session context store | context.py; `/api/context` | **CTX (NEW UI)** | pane lists active sessions |
| C16 | Workspace runtime C2/C3 | workspaces.py/workspace.py/workspace_index.py; `/api/workspaces/*` | RSCH | make/edit + index next/requeue/render |
| C17 | Project artifact attachment | projects.py; `/api/projects/{id}/artifacts` | RSCH | attach by kind |

### D. Runs & object substrate — STAY (RUN) unless split

| # | Capability | Anchor (runs-tab.js) | Dest | Acceptance |
|---|---|---|---|---|
| D1 | Runs list + filter + search | `load/setFilter/render`; `/api/workflows/runs` | RUN | filter+search narrow |
| D2 | Select + deep-link `#/runs/{id}` | `select`; `replaceState` | RUN | URL updates; reload restores |
| D3 | Run DAG viz (**private `_editor`**) | `_renderRunGraph/_initEditor` | RUN | renders; **never leaks `window.dfEditor`** |
| D4 | Node click → step row flash | `_initEditor` `_idMap` | RUN | click → row flash+scroll |
| D5 | Live status overlay + chip | `_applyStatus` | RUN | nodes tint |
| D6 | Zombie detect + Mark Failed | `_isZombieRun/markFailed` | RUN | 10min stall → banner |
| D7 | Step results strip + cascade | `_renderSteps/_computeCascade` | RUN | expand; cascade badges |
| D8 | START/END anchor rows + modal | `anchorRow/openAnchorDetail` | RUN | seed/deliverable actuals |
| D9 | Per-step prompt + output expand | `_renderStepPrompt/_renderStepOutputs` | RUN | rendered prompt + values |
| D10 | Sandbox code-exec panel | `_renderSandboxCodePanel` | RUN | exec metadata |
| D11 | HITL approval gate | `_renderApprovalGate/resolveGate` | RUN | approve/reject resolves |
| D12 | Step-detail modal | `openStepDetail/_compositeSummary` | RUN | timing/tokens/skill chips |
| D13 | **Step-detail PIVOTS** | `pivotResearch`@1157/`pivotContextGraph`@1174/`pivotNewAgent` | **XT** | re-targeted (I9/I10) |
| D14 | SSE stream + polling fallback | `_subscribeSSE`; `/stream`; `#rtp-sse-badge` | RUN | SSE badge; events tick |
| D15 | Live Plan panel | `_renderLivePlan` | RUN | plan.updated items |
| D16 | Run mgmt toolbar | `resume/cancel/rerun/pause` | RUN | each endpoint hit |
| D17 | Bottom drawer (JSON + Copy) | `_renderBottomDrawer`; `runs.copy-json` | RUN | raw JSON; copy |
| D18 | Context Trace producer graph | `_renderContextTrace`; `#runs-tab-context-body` | **CTX** (with Runs) | step→key handoffs |
| D19 | Read-only canvas zoom | `zoomIn/Out/Reset` | RUN | acts on `_editor` |
| D20 | Run Lens scrubber | `window.RunLens`@8871 | RUN | replays steps; migrate inline onclicks if moved |
| D21 | Workflow Memory panel | `WorkflowMemory`; `/api/workflows/memory/*` | RUN/Operate | browse stores |
| D22 | AssetPeek deep-dive | `AssetPeek.open`@144 (asset-peek.js) | SHARED | opens any tab; `seedChat` |
| D23 | Unified object model | DESIGN-ONLY (net-new) | SHARED (build target) | do not block relocation (§8) |

### E. Nav / routing / shell — STAY; extend only (NAV)

| # | Capability | Anchor | Dest | Acceptance |
|---|---|---|---|---|
| E1 | `switchTab(name,el)` | main.js:89 | +3 loader lines | chat/research/context branches added |
| E2 | Unknown-tab safety + `discover` remap | main.js:94-103 | STAYS | stale hash warns, no throw |
| E3 | ARIA tablist + roving tabindex | main.js:239-269 | STAYS | new buttons inherit a11y |
| E4 | Hash router `#/tab`, `#/runs/{id}` | shell/router.js | STAYS | `#/chat`/`#/research`/`#/context` deep-link |
| E5 | Left-rail + Build/Operate/Library | app.css:6410; index.html:277 | STAYS (relabel) | markup+CSS only |
| E6 | Admin dropdown | `#admin-trigger AdminMenu` | STAYS | unchanged |
| E7 | `data-action` delegation | shell/actions.js | STAYS | new nav uses it |
| E8 | Cross-tab links + count chips | inline `switchTab()` @872,1671,1728 | STAYS (audit) | audit hard-coded `documents`/`dashboard` strings |

### GAPS — must be closed to honor no-loss (tracked in §10)

| G | Item | Anchor | Decision needed |
|---|---|---|---|
| G1 | Project context bar home | `#project-select`@348 | keep in Composer drawer (default) or Build/Library |
| G2 | `#tab-documents` disposition | `data-tab=documents`@290 | remove nav btn; `documents→research` remap; audit ~5 links |
| G3 | Context pane is NET-NEW UI | context.py `/api/context` | build over existing backend |
| G4 | Graph fork edges + per-pane guard | `graph_service`; `researchLoaded` | per-edge ownership; per-pane guard |
| G5 | `setWfMode`/`#wf-composer` legacy runner | main.js:4822 | verify not orphaned or retire |
| G6 | `ComposerSplit` retirement | 4 `setMode('canvas')` callers | repoint all; `focus`→fullscreen |
| G7 | Thread rehydrate msg-ID contract | `Threads`/`ChatRating.nextId`/`Pins` | preserve IDs across move |

---

## 7. Cross-tab interop map

The window-global bus is the transport (existing, load-bearing — **reuse, do not
re-mint**): `_chatAgent · _chatModels · _modelBackends · _composerEngagedNodeId ·
_enclavePins · dfNodeData · dfUpdateNodeData · Pins · OpPath · BootSequence ·
ComposerSplit · AgentTuning · ChatRating · Threads`.

```
                    CHAT  ◄────────────────►  COMPOSER  ────────────►  RUNS
     I1 step-engage (node→chat test-step)     │  I3 pin→step (append)   │ D13 pivots
     I2 model write-back to node              │  I4 boot scaffold        │ I18 live overlay
     I5 +seed → node prompt                   │  I6 comp-models→picker    │ I19 run→workstream
     I7 save-as-agent                          │                          │
     I8 rating→AgentTuning                     │                          │
        └────── RESEARCH ──────────────────────┴──────── CONTEXT ─────────┘
           I11 capture→RAG   I12 agent→palette/chat    I13 run-graph↔Runs
           I14 build→step (Promote/append)              I15 session-store↔Runs
                              I17 AssetPeek (shared, any tab)
                              I16 OpPath/NBA nudge bus (Chat↔Composer)
```

| # | Edge | From → To | Mechanism | Preserve rule |
|---|---|---|---|---|
| I1 | step-engage | CMP node → CHT | `composerEnterStepEngage`→`sendMessage`→`/api/workflows/test-step` | shared module scope; `dfNodeData` lexical read |
| I2 | model write-back | CHT → CMP node | `onChatModelChanged`→`dfUpdateNodeData` | guarded by `_composerEngagedNodeId` |
| I3 | pin → step | CHT → CMP | `Pins.convert`→`composerLoadDefinition` (rebuild) | reveal via `switchTab('dashboard')` |
| I3b | code → step | CHT → CMP | `ChatCode.toStep`→`_enclavePins` | same Pins path |
| I4 | boot scaffold | CHT → CMP | `BootSequence.dispatch`→capture-spec/scaffold→`composerLoadDefinition` | crosses tab boundary now |
| I5 | +seed | CHT → CMP node | `composerSeedAgent` | appends node `system_prompt` |
| I6 | comp-models → picker | CMP → CHT | `syncCompositionModelsToChatPicker` | "From composition" optgroup |
| I7 | save-as-agent | CHT → Library | `POST /api/agents` | flows to palette + selector (I12) |
| I8 | rating → tuning | CHT → CMP node | `ChatRating.rate`→`AgentTuning.record` | appended to test-step prompt |
| I9 | Runs → Research | RUN → RSCH | `pivotResearch`→`#research-topic` | re-target to Research pane |
| I10 | Runs → Context graph | RUN → CTX | `pivotContextGraph` (had `switchTab('graph')` null bug) | re-target to Context run-graph |
| I10b | Runs → New Agent | RUN → modal | `pivotNewAgent`→`showCreateAgentModal` | global preserved |
| I11 | capture → RAG | RSCH → RSCH | `ResearchArtifacts.captureRaw` `rag_ingested` | keep the corpus loop |
| I12 | forged agent → surfaces | RSCH → CMP+CHT | `/api/agents` consumed by `renderAgentsWorkbench` + `#agent-select` | no extra wiring |
| I13 | run-graph → Runs | CTX → RUN | node → `#/runs/{id}` / `RunLens.open` | same observability substrate |
| I14 | build → step | RSCH → CMP | Promote / `dfAddNodeFromAgent` (append) | §8 object model |
| I15 | session-store ↔ run | CTX ↔ RUN | `/api/context` ↔ run metadata | shared model |
| I16 | OpPath/NBA nudges | CHT ↔ CMP | `OpPath.renderNudges` (chatLen vs nodeCount) | **re-plumb cross-tab signal** |
| I17 | AssetPeek | any → any | `AssetPeek.open`; `seedChat` → CHT | generalize kind→renderer (§8) |
| I18 | live overlay | CMP → RUN | `dfRunWorkflowLive`→`dfApplyRunState` | same run in both |
| I19 | run → workstream | CMP → RUN | `ComposerWorkstream.startPolling` | `/api/workflows/runs/{id}` |

### Bridge-integrity checklist (silent-break tripwires)

1. `dfNodeData`/`dfUpdateNodeData` reachable from Chat after split (I1/I2/I5).
2. All `setMode('canvas')` callers repointed to `switchTab('dashboard')` (G6).
3. `#chat-system-strip` poller IDs verbatim (B14).
4. Runs pivots re-targeted (I9/I10, D13).
5. `composerLoadDefinition` (wipe) vs `dfAddNodeFromAgent` (append) chosen per gesture (I3/I4/I14).
6. `rag_ingested` capture→RAG loop intact (I11).
7. Thread `messagesHtml` msg-ID contract stable (G7).
8. `RunsTab._editor` stays private — never `window.dfEditor` (D3).
9. OpPath cross-surface signal re-plumbed across the tab boundary (I16).

---

## 8. How this revises the prompt-first doc + reuses the object model

### 8.1 Revises `2026-07-09-composer-workflow-builder-design.md`

That doc's **spine is `ComposerSplit`**: one thread pivoting between chat/canvas/focus
modes via a selection machine, with `BootSequence` distilling conversation→spec→scaffold
*in place*. This plan retires that premise:

| Prompt-first doc said | This plan says |
|---|---|
| One selection machine wrapped around a DAG; "selection is engagement." | Two tabs. Composer = canvas selection machine; Chat = configurable launchpad. |
| `setMode('chat'\|'canvas'\|'focus')` switches the view. | Mode machine retired; top-level tab nav supersedes it. `focus` → `dfToggleFullscreen`. |
| BootSequence crystallizes conversation → scaffold *in the same surface*. | BootSequence now **crosses a tab boundary**: Chat captures spec, `switchTab('dashboard')` reveals the DAG. |
| Node-bound chat is the one bridge inside the surface. | Node-bound chat is the **primary cross-tab bridge** (I1) — an explicit channel, not an in-pane test harness. |

**Reused as-is:** the `test-step` `messages[]` additive field (still the only backend
change), palette-as-objects, `Promote`, local-sandbox operation, the three on-ramps
(now: talk in Chat, click a palette object in Composer, drag onto the canvas).

### 8.2 Reuses `2026-07-09-unified-object-model-library-alignment.md`

The object model is the **shared substrate all four surfaces speak**:

- **Palette-as-objects (Composer):** `loadWorkbenches` benches render as `ObjectShell`
  chip-mode over `GET /api/objects/{kind}`; `Promote` maps kind→engine slot
  (Prompt→`role_ref`, Agent→`system_prompt`, Skill/Plugin/MCP→`ToolRef`, Model→`model`).
- **Config Header (Chat):** the tool/skill/hook/context pickers (§3.2) are the *same*
  object surfaces — a tool in the header is the object a bench drags onto a node.
- **Research forge:** artifacts (research-artifacts.js) + roles + doc→agent outputs are
  built on the **same `EntityMeta` envelope**, so "refine in Research → drop into a
  workflow" is one object family end-to-end.
- **Generalized AssetPeek (I17):** one kind→renderer deep-dive invocable from any tab;
  `seedChat` is the terminal action that routes back to Chat.

`EntityMeta`/`ObjectShell`/`EntityCard`/`reference_index`/generalized `AssetPeek` are
**net-new (design-only today)** — a *build target*, not code to move. Relocation (P0-P4)
does **not** block on them (P5).

---

## 9. Phased plan (parity-preserving · engine-frozen · data-action-only)

Every phase is shippable, holds the **14-failure baseline** (tests/parity + tests/ui +
non-slow tests/playwright), touches no engine code, and adds no window globals. Start
with the smallest slice that proves separation with **zero loss**.

```
P0 ─ Chat extraction (PROOF)      ▓▓ smallest · exercises the hardest edges
P1 ─ Composer completion          ▓▓ canvas fills freed space
P2 ─ Config Header + pivots       ▓▓ the launchpad identity
P3 ─ Research promotion           ▓▓▓ un-hide + relocate RAG/research/roles
P4 ─ Context pane + graph fork    ▓▓▓▓ NEW UI + node-type filter (hardest)
P5 ─ Object-model alignment       ▓▓ roadmap · Promote/EntityMeta/AssetPeek
```

### P0 — Chat extraction (the proof slice)

The minimum that proves the whole thesis with zero loss. Relocation + 4 call-site
repoints; nothing else.

| Step | Change | File |
|---|---|---|
| 1 | Create `#tab-chat`; move `#agent-chat-dock`@612-794 into it **verbatim** (IDs + inline handlers intact) | index.html |
| 2 | Add Chat nav button `data-tab=chat data-action=switch-tab` + register `Actions.click({'switch-tab':…})` once | index.html, actions consumer |
| 3 | Add `ChatView.init()` (loadAgentsForSelector + loadModels + populateSystemPromptRoles + Threads restore); drop `loadAgentsForSelector` from `ComposerView.init` | new js/workspace-legacy/chat-view.js; composer-view.js |
| 4 | Add `if(name==='chat') ChatView.init();` to switchTab ladder | main.js:133+ |
| 5 | Delete `#composer-mode-*`/`#composer-fmode-*` buttons + `#composer-divider`; centralize reveal in `composerLoadDefinition` (`switchTab('dashboard')`); drop `setMode` at main.js:3705/8503 + boot-sequence.js:291 | index.html, main.js, boot-sequence.js |
| 6 | Repoint spine ghost CTA "Start in chat ↑" → `switchTab('chat')` | index.html/composer-split.js |
| 7 | Keep `main.js` monolithic (shared scope) — no module isolation | — |

**Gate P0:** baseline stays 14. Manual: (a) Chat standalone — send, threads
rehydrate, rating, export, model/agent/sysprompt all work; (b) select a Composer
node → type in Chat → hits `/api/workflows/test-step`; (c) Pins.convert + BootSequence
scaffold reveal a DAG on the now-separate canvas; (d) `syncCompositionModelsToChatPicker`
feeds the picker; (e) `#chat-system-strip` poller still writes; (f)
`grep -n "setMode(" api/static/js -r` → 0 callers.

### P1 — Composer completion (canvas-dominant)

| Step | Change |
|---|---|
| 1 | Collapse `.composer-split` grid to canvas-first single column; canvas fills the freed width |
| 2 | Decide + wire G1 (project bar home); ensure `#project-select` renders + `onchange` fires |
| 3 | Re-express `focus` mode via `dfToggleFullscreen`; remove `--chat-frac`/`enclave.composer.split` |
| 4 | Audit + quarantine `setWfMode`/`#wf-composer` (G5) |

**Gate P1:** baseline 14; A1-A30 all pass; canvas is permanently dominant; project bar works.

### P2 — Config Header / launchpad + pivots

| Step | Change |
|---|---|
| 1 | Re-group existing controls into a Config Header above `#messages` (agent/model/role→sysprompt/web-search) |
| 2 | Add net-new `data-action` pickers: tools/skills, hooks, context (over `/api/plugins`, `/api/mcp/servers`, `/api/documents`) |
| 3 | Add pivots: "Save as agent" (`/api/agents`), "Send to Composer as a step" (`dfAddNodeFromAgent` **append**), "Send to Research" (`/api/feedback/artifacts`) |

**Gate P2:** baseline 14; B1-B16 pass; header composes launch state; append-pivot does
**not** wipe an in-progress canvas.

### P3 — Research promotion

| Step | Change |
|---|---|
| 1 | Un-hide `#tab-research`; add Research nav button (Build) |
| 2 | **Delete the documents relocator** (main.js:4532); keep RAG/deep-research/role-library mounted in `#tab-research` |
| 3 | Add `documents → research` remap at top of `switchTab` (reuse the `discover` pattern); remove the Context/documents nav button |
| 4 | Wire C2/C3 workspace runtime surface into Research |
| 5 | Preserve `#wf-roles-list` id-promotion trick (roles render into the visible mount) |

**Gate P3:** baseline 14; C1-C10, C14, C16-C17 pass in Research; `switchTab('documents')`
links redirect; role library visible.

### P4 — Context pane + graph fork (hardest)

| Step | Change |
|---|---|
| 1 | Build `#tab-context` + `ContextView.init()` over `/api/context` (NEW UI); add Context nav button (Operate) |
| 2 | Fork `/api/graph` by node `type` — research subgraph in Research, run/provenance in Context |
| 3 | Make `researchLoaded` guard **per-pane**; duplicate graph chrome per pane; assign cross-type edges per-edge (G4) |
| 4 | Re-target Runs step-detail pivots: `pivotResearch`→Research topic, `pivotContextGraph`→Context graph, `pivotNewAgent`→modal (D13/I9/I10) |
| 5 | Co-locate the Context Trace producer graph (D18) with the Context pane |

**Gate P4:** baseline 14; both graphs render independently (no blank second pane); Runs
pivots land correctly; `/api/context` sessions list; cross-type edges preserved.

### P5 — Object-model alignment (roadmap)

Generalize `AssetPeek` to a kind→renderer registry, palette-as-objects over
`GET /api/objects/{kind}`, `Promote` object→step, Research artifacts on `EntityMeta`.
**Gate P5:** Promote from Research → Composer node; AssetPeek from any tab; palette chips
are objects.

### Per-phase parity gate (all phases)

```
□ tests/parity + tests/ui + non-slow tests/playwright → still 14 failures (no 15th)
□ no new window global (grep the diff)          □ no new inline on*= handler
□ no api/services/workflow_engine.py|step_executor.py touch
□ id-stability: chat-strip poller IDs · runs-tab-* · #graph-svg · #tab-research .graph-panel · peek-*
□ hard-coded switchTab('documents')/('dashboard') string audit → no dead-ends
```

---

## 10. Open questions for the operator

1. **G1 — Project context bar home.** Keep `#project-select` in the Composer admin
   drawer (default — it scopes Composer saves), or re-home it under Build/Library as a
   global project switcher shared by Chat + Research? A shared switcher is more
   interop-friendly but is a bigger move.
2. **G5 — `setWfMode`/`#wf-composer` legacy runner.** This older workflow-runner surface
   (main.js:4822, on the Catalog/Workflows page) shares `dfInitEditor` with the Composer
   and is distinct from both Composer and Runs. Retire it, or keep it quarantined? It is
   not referenced by the new IA — confirm it can be removed without breaking a Catalog
   deep-link.
3. **I10 — `pivotContextGraph` target.** After the graph fork, does a Runs step's
   "Context Graph" pivot land in the **Context** run/provenance graph (design intent:
   run nodes live in Context) or the **Research** knowledge graph? The plan assumes
   Context; confirm.
4. **Chat tab default state.** On first entry with no agent selected, does Chat open on
   the last-used persona config, a blank "raw model" config, or a chooser? (Affects
   `ChatView.init` default.)
5. **`documents` alias lifetime.** Keep the `documents → research` remap permanently
   (belt-and-suspenders for old bookmarks), or only through one release then remove?
6. **Naming.** The Operate-side "Context" label now means run-observability, not the old
   docs+graph "Context." Acceptable, or rename (e.g. "Trace" / "Observability") to avoid
   confusion with the old meaning?

---

## Feasibility & no-loss review (verified)

> Adversarial pass against the real code (index.html, main.js, composer-split.js,
> composer-view.js, runs-tab.js, research-artifacts.js, context.py, documents.py,
> shell/actions.js). Every line anchor below was opened and confirmed. **Verdict:
> the plan is sound and preserves all Composer/Chat/Runs capability; the separation
> seam physically works; the engine is untouched. One real capability-loss trap
> exists — Role Library — and it hides inside two innocuous-looking P3 steps.**

### A. Confirmed-preserved (evidence)

| Claim in plan | Verified against real code | Status |
|---|---|---|
| Cross-tab bridge survives the split (seed→node, test-step, model write-back) | `dfNodeData` is `let`-scoped at **main.js:4773**; `sendMessage`'s step-engage branch reads it **lexically** at **main.js:990-991** with the literal comment *"dfNodeData is module-scoped — reference it lexically, not via window."* `_sendStepMessage`@838 POSTs `/api/workflows/test-step`@860; `composerSeedAgent`@963 & `onChatModelChanged`@946 also read `dfNodeData` lexically. **None of this JS moves** — only the `#agent-chat-dock` DOM relocates — so the bridge is preserved for free. | ✅ CORRECT — this is the plan's central bet and it holds. |
| Chat dock is a self-contained subtree that lifts whole | `#agent-chat-dock`@612 → closes @788. Children in range: `#thread-bar`@626, `#chat-system-strip`@635, `#messages`@731, `#step-engage-badge`@762, `#nba-container`@772, `#pins-meter`@773, `#prompt`@784, `#send-btn`@786. | ✅ CORRECT. |
| Poller IDs stay resolvable after the move (B14) | All 8 targets (`cpu-value`,`mem-value`,`cpu-cores`,`mem-detail`,`models-content`,`cpu-arc`,`mem-arc`,`status-content`) appear **exactly once** in index.html. Verbatim move keeps them unique. | ✅ CORRECT. |
| The 4 `setMode('canvas')` callers (§4.3) | Exactly four, at the exact lines claimed: **main.js:3705** (`openWorkflowInComposer`, already `switchTab('dashboard')` first → `setMode` redundant), **main.js:8070** (`composerLoadDefinition` tail, `getMode()==='chat'` guard), **main.js:8503** (`Pins.convert`), **boot-sequence.js:291**. `grep setMode(` returns only these + the def@composer-split.js:94. | ✅ CORRECT, all 4 accounted for. |
| append (`dfAddNodeFromAgent`) vs rebuild (`composerLoadDefinition`) | `composerLoadDefinition`@7924 → `composerNewWorkflow`@7881 wipes `dfNodeData={};dfNextId=0`@7893 **and** calls `composerExitStepEngage()`@7892 (drops the stale engaged pointer — critical, else next chat msg re-routes to a recycled node id). `dfAddNodeFromAgent`@4947 is additive. The load-bearing distinction is real. | ✅ CORRECT. |
| Nav/a11y/routing is additive-only | ARIA tablist loop **main.js:242** iterates `.tab-nav .tab-btn[data-tab]` on DOMContentLoaded → new static buttons inherit role/aria/arrow-nav for free. `Actions` delegation router exists (**shell/actions.js:5**, `closest('[data-action]')`). Unknown-tab guard `if(!panel)return;`@103. `discover→inventory` top-remap@94 is the exact reusable pattern for `documents→research`. `ComposerView` is a real ES import (**main.js:41**) called at :133 — **`ChatView` mirrors it via one more `import`, which is NOT a window global.** | ✅ CORRECT — "no new global / no new inline" is achievable as written. |
| Context split is real, not hand-waved | `context.py` is **5 endpoints, zero UI** (`GET /api/context`, `/{id}`, `/{id}/tool-calls`, `POST /{id}/close`, `/cleanup`) → the Context pane genuinely is *new UI over an existing backend* (G3, honestly flagged). `research-artifacts.js`: `captureRaw`@14 → `/api/feedback/artifacts`@25; `rag_ingested` loop real @41. `documents.py`: `/query`→`/search` alias real @84. `#graph-svg` @index.html:1574 inside `#tab-research .graph-panel`@1544; `runs-tab.js:1177` hard-refs `#tab-research .graph-panel` (id must stay). | ✅ CORRECT. |
| `pivotContextGraph` "graph bug" framing | **Already fixed in-tree**: `pivotContextGraph`@runs-tab.js:1167 routes to `switchTab('research')`@1174 with a comment documenting the old `switchTab('graph')` null-throw. Both `pivotResearch`@1153 and `pivotContextGraph` currently land on the *same* research graph → after the fork they must diverge (D13/I9/I10). Plan states this correctly. | ✅ CORRECT (bug is past-tense, as the plan implies). |
| Engine frozen | Every path routes through routers only: `/api/workflows/{test-step,save,run-async,runs}`, `/api/graph`, `/api/context`, `/api/documents`, `/api/feedback/artifacts`, `/api/conversations`. **No reference to `workflow_engine.py` / `step_executor.py` anywhere in the plan or the touched surfaces.** | ✅ CORRECT. |

### B. At-risk / would-drop capability + fixes

| # | Risk | Evidence | Fix (fold into the phase) |
|---|---|---|---|
| **R1 — Role Library (C14) silently lost in P3** ⚠️ **the one real no-loss break** | The Role Library panel is **built by the relocator P3 deletes**: the `#wf-roles-list-ctx→wf-roles-list` id-promotion *and the panel's DOM construction* both live inside the `DOMContentLoaded` relocator at **main.js:4640-4673** (same listener as :4532, shares `ctxTab`). Separately, the only per-visit `loadRoles()` call is gated behind **`if (name==='documents')`@main.js:179** — and P3's proposed top-of-function `documents→research` remap makes that branch **unreachable**, while the `research` branch (`initResearch()`@174) **does not call `loadRoles`** (confirmed: `initResearch`@2222 calls `loadGraphData/populateResModelSelect`, never `loadRoles`). So P3 as written removes both the *mount* and the *refresh*. | P3 must (a) **statically author the Role-Library markup inside `#tab-research`** (don't rely on the deleted relocator to build it), and (b) **move `loadRoles()` into the `research` branch or into `initResearch()`** so it fires on every Research visit. Add to Gate P3: *"Role Library renders AND refreshes on Research entry; `#wf-roles-list` resolves to the visible mount."* |
| R2 — "Delete the relocator" understates the RAG move | The relocator moves `.research-layout` **into** `#tab-documents`; deleting it leaves `#tab-research` holding graph+deep-research but leaves the **static RAG doc surface stranded in `#tab-documents`** (drop-zone/list/search/stats are static markup in `#tab-documents`, not in `.research-layout`). | P3 step 2 is really *"reverse the relocator's direction"*: re-home the RAG doc markup + role library **into `#tab-research`**, then delete the relocator. State it as a markup move, not a deletion. |
| R3 — `researchLoaded` single-shot blocks a second graph mount (G4) | `initResearch`@2227 early-returns if `researchLoaded`; the flag is module-global and `loadGraphData` targets the single `#graph-svg`. Two panes rendering two filtered views will starve the second. | Plan already flags G4; make it explicit that Context uses its **own** loader (`ContextView.init`), not `initResearch`, and that the run-filtered graph needs its **own SVG id** (not `#graph-svg`, which `runs-tab.js:1177` pins to Research). |
| R4 — stale copy after split | `research-artifacts.js:41` renders `"· also indexed in Context"` on `rag_ingested`; post-split RAG lives in **Research**, so the string misleads. `#composer-mode-*`@690-697 sit **inside** the moved dock — they ride into `#tab-chat` and must be deleted *there*, and the `#composer-fmode-*`@471-474 (outside the dock, stay in Composer) still call the retired `setMode('chat')`. | Copy fix (Research not Context). Sequencing note: P0 step 5 deletes the mode buttons in **both** locations (one now in `#tab-chat`, one in Composer); neutralize `setMode('chat')` so the surviving float toggle can't half-size a departed pane. |

*Nothing in **P0** drops a capability* — R1-R4 are all Context-split (P3/P4). The chat/canvas/focus view-switch that "disappears" is intentional (superseded by tabs); `focus` survives independently via `dfToggleFullscreen`/`#canvas-fullscreen-btn`, so it is not a loss.

### C. Doc inaccuracies (cosmetic — fix for clarity, not load-bearing)

- §2.1 / §4.1 diagrams show `#composer-canvas-panel` and `#agent-chat-dock` as sibling grid *columns* and the admin drawer *inside* `.composer-split`. Reality: the admin `<details>` **closes @461, before `.composer-split` opens @467**; the canvas panel is nested inside `.composer-grid`@501, and `.composer-split` grid-places three children (`.composer-grid` | `#agent-chat-dock` | `#composer-workstream`) per the comment @464-466. The "lift the dock whole" conclusion is unaffected, but P1's "canvas fills the freed width" is a change to **`.composer-grid`**, not `.composer-split`.

### D. Engine / parity assessment

- **Engine: untouched — confirmed.** No plan step references `workflow_engine.py` or `step_executor.py`; node-bound chat already ships today via `/api/workflows/test-step` (`_sendStepMessage`@838). The prior doc's `test-step messages[]` additive field is **not required** for separation and is correctly scoped out of P0-P4.
- **Globals: none added.** The window bus is reused (`_composerEngagedNodeId`, `dfNodeData`, `dfUpdateNodeData`, `ComposerSplit`, `Pins`, `OpPath`, …). `ChatView`/`ContextView` are ES-module exports imported into main.js exactly like `ComposerView`@41 — module bindings, not `window.*`.
- **Inline handlers: compliant.** New nav uses `data-action="switch-tab"`; the moved dock carries **existing** inline handlers (lift-and-shift is explicitly allowed by the rule).
- **Parity gate: the "14-failure baseline" is inherited, not re-measured here.** Run `tests/parity + tests/ui + non-slow tests/playwright` before/after each phase. Add the id-stability greps (poller IDs, `runs-tab-*`, `#graph-svg`, `#tab-research .graph-panel`) — these are the selectors Playwright pins to.

### E. Tightened FIRST PR (P0 — proves separation, zero loss)

P0 is the right proof slice (it exercises the hardest edge — the lexical `dfNodeData` bridge — with the least surface). Two tightenings: (1) neutralize `setMode('chat')` so the *surviving* Composer float-toggle can't half-size a departed pane, and (2) add a **cold-start** acceptance (the moved `loadAgentsForSelector` must populate `#agent-select` when Chat is opened *before* Composer).

**Files touched (P0):** `api/static/index.html` · `api/static/js/main.js` · `api/static/js/workspace-legacy/composer-view.js` · `api/static/js/workspace-legacy/composer-split.js` · `api/static/js/workspace-legacy/boot-sequence.js` · new `api/static/js/workspace-legacy/chat-view.js`.

**DOM moves:**
1. New `<div class="tab-content" id="tab-chat">`; move `#agent-chat-dock` (index.html **612-788**) into it **verbatim** — IDs + inline handlers intact.
2. Nav: add `<button class="tab-btn" data-tab="chat" data-action="switch-tab">Chat</button>` in the Build section; register `Actions.click({'switch-tab': el => switchTab(el.dataset.tab, el)})` **once**.
3. Delete `#composer-fmode-*`@471-474 (Composer) **and** `#composer-mode-*`@690-697 (now inside `#tab-chat`) + `#composer-divider`@478. Make `ComposerSplit.setMode` a safe no-op (or delete) — keep `setSpinePrimed`/`toggleSpine` (used by `ComposerView.updateCanvasEmptyState`@36).

**JS moves:**
4. `import { ChatView } from './workspace-legacy/chat-view.js';` (mirror `ComposerView`@41). `ChatView.init()` = `loadAgentsForSelector()` + `loadModels()` + `populateSystemPromptRoles()` + `Threads.restoreActive()`. Remove `loadAgentsForSelector()` from `ComposerView.init` (composer-view.js:21).
5. `switchTab` ladder: add `if (name === 'chat') ChatView.init();`.
6. Reveal-centralization: at `composerLoadDefinition` tail (main.js:**8070**) replace the `getMode()==='chat'` block with `switchTab('dashboard')`; **drop** the trailing `setMode('canvas')` at main.js:**3705**, **8503**, boot-sequence.js:**291**.
7. Repoint spine CTA `onclick="document.getElementById('prompt').focus()"` (index.html:**496**) → `switchTab('chat')`.
8. Keep main.js monolithic — move **no** chat JS out of it (this is what keeps the `dfNodeData` bridge intact).

**Acceptance / regression gate (P0):**
```
□ tests/parity + tests/ui + non-slow tests/playwright → still 14 (no 15th)
□ grep -n "setMode(" api/static/js -r  → 0 CALLERS (def may remain as no-op)
□ grep the diff → no new window.* global · no new inline on*= (nav uses data-action)
□ no api/services/workflow_engine.py | step_executor.py in the diff
□ Chat standalone: send (raw + agent), threads rehydrate, rate, export, model/agent/sysprompt
□ COLD START: open Chat FIRST (before Composer) → #agent-select is populated   ← new
□ Cross-tab bridge: select a Composer node → switchTab('chat') → type → POST /api/workflows/test-step
□ Reveal: Pins.convert AND BootSequence scaffold each land a DAG on the (now separate) canvas
□ syncCompositionModelsToChatPicker still feeds the "From composition" optgroup
□ #chat-system-strip poller still writes all 8 IDs (verbatim, unique)
□ spine CTA "Start in chat" → switches to the Chat tab (not a dead focus())
```

P0 carries **no Context/Research/Roles changes** — R1-R4 are deferred to P3/P4, so the proof slice stays clean and reversible.
