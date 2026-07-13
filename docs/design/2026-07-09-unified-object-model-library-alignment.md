---
title: ENCLAVE Unified Object Model & Library Alignment
date: 2026-07-09
status: proposed
extends: 2026-07-09-composer-workflow-builder-design.md
surface: api/ (routers + services + models) · api/static/js/library/** + index.html · backed by the FROZEN workflow engine
---

# ENCLAVE Unified Object Model & Library Alignment

> One authoritative design for making **every platform object feel like one
> family**. Spine: **registry-first** — a single `ObjectRegistry` owns the
> *contract* (a shared envelope + shared verbs + a per-kind descriptor) while
> every native store (YAML, JSON, Chroma, Ollama, `MODEL_REGISTRY`) stays
> authoritative. Grafts: the **graph-first** interop model (an always-present
> uses / used-by tab computed from extractors that already exist), the
> **greenfield-Prompts-first** build slice (prove the whole contract on a kind
> that can't regress), and the **Library = definitions / Operate = instances**
> IA rule. Everything is grounded in real files; the workflow engine is
> **frozen** and untouched; all new wiring is `data-action` delegation.

This document is the object-model half of the in-flight console work. Its
sibling is the [Composer design](2026-07-09-composer-workflow-builder-design.md):
that doc governs *how you build a workflow* (the selection machine); this doc
governs *what the pieces are* (the object family the palette browses and the
steps compose). They meet at one seam — **every Library object is a Composer
palette object, and Promote is the gesture that turns it into a step.**

---

## 0. TL;DR

- **Mental model:** *Every platform thing is an **EnclaveObject** — one node in one dependency graph, projected from its native store into a shared `EntityMeta` envelope, browsed through one shell, drilled through one deep-dive, and composed onto the canvas through one Promote.* There are ten kinds (`agent · model · prompt · skill · plugin · mcp · workflow · project · context · workspace`); there is **one** of everything else.
- **One backend source of truth for the *contract*:** `api/services/object_registry.py` holds a `KindDescriptor` per kind (schema · crud · discovery · metadata · deepdive · interop). The registry never owns storage — uniformity is a **projection layer, not a migration**.
- **One UI, generated from the registry:** `ObjectShell` (browse+search+discover), `EntityCard` (one card), and a **generalized `AssetPeek`** (kind→renderer registry, six fixed tabs). `GET /api/objects/kinds` hands the frontend every descriptor's UI contract.
- **The proof kind is Prompts.** It is the first object authored purely as *descriptor + service*, seeded from the existing `prompts/roles/` + `prompts/templates/` files and the read-only `/api/roles` router that already ships. Building it forces every seam to exist on a surface where nothing legacy can regress.
- **First slice (P0):** *AssetPeek → kind-registry, then ship Prompts through it.* Re-register `model`/`agent`/`plugin` unchanged (zero-regression proof), then light Prompts end-to-end. Everything after is "one descriptor + one adapter."
- **The only new CRUD verbs the gaps require:** workflow `DELETE` (missing today) and artifact soft-delete. Everything else is an adapter over shipped code.

---

## 1. Executive summary & the one mental model

Today the platform has ten object types and roughly ten of everything else: two-plus card renderers (`.agent-tile`, `.inv-card`, `.plugin-card`, `.cap-card`, flat MCP rows), four bespoke deep-dives (`AssetPeek` for model/agent/plugin, `SkillsDiscover.openDetail`, `mcp.js` `renderDetail`, `WorkflowIndex.deepDive`), three unrelated discovery systems (`discovery_service` HF crawl, `agentic_discovery` provider registry, `inventory` enrichment), and per-kind CRUD scattered across a dozen routers. Agents are fully data-driven and self-describing; models are code-defined; prompts are not objects at all. Nothing shares a metadata envelope, and nothing can answer *"which workflows use this model"* or *"which agents reference this prompt"* uniformly.

This design makes them one family without rewriting them. The load-bearing idea:

> **THE MENTAL MODEL — "every object is an EnclaveObject: a node in one graph, projected into one envelope."**
> A Prompt, a Model, a Workflow, and a Workspace are the *same shape* to the platform — an `EntityMeta` envelope (id, kind, name, provenance, maturity, timestamps, tags) plus a typed `spec` plus computed `edges` (uses / used-by). The native store stays authoritative; the registry **projects** it into the envelope and answers the **same verbs** for it. Browse is one shell parameterized by kind. Drill-down is one pane with six tabs. Create/update/remove/duplicate/export is one route shape. Interop is one directed graph. Composition is one Promote.

Three consequences fall out for free:

1. **Adding a kind is a descriptor, not a project.** A `KindDescriptor` declares schema + crud-adapter + discovery + deep-dive + interop. The shell, the card, the deep-dive, the CRUD routes, and the palette chip all read the descriptor. Prompts is the working proof: authored as descriptor + `prompt_service.py`, it lights up everywhere.
2. **Uniformity is projection, not migration.** `agents/*.yaml` already carries `id/name/description/icon/tags/created_at/updated_at` — it *is* the envelope. The other nine kinds are made to match by a `~40-line` adapter that translates native ↔ envelope. No object's real data moves. This is why it is buildable against the frozen engine and the 30k-line `index.html` incrementally.
3. **The library IS the palette.** `ObjectShell` in "chip mode" over the same `GET /api/objects/{kind}` endpoint is exactly the Composer palette. "Browse in Library" and "audition in palette" become one machine, two skins — the direct seam into the [Composer plan](2026-07-09-composer-workflow-builder-design.md).

### What is common vs what is kind-specific (the whole design in one line)

The **envelope + edges** are 100% common and drive every shared surface (shell, card, and the Overview / Dependencies / Usage / History tabs). The **typed `spec`** is kind-specific and drives exactly one surface each: the deep-dive **Config** tab and the create/edit form. That single split is the entire model.

---

## 2. Canonical object model & platform metadata schema

### 2.1 `EntityMeta` — the shared envelope (promoted from `DiscoveryItem`)

`agentic_discovery.DiscoveryItem` (`api/services/agentic_discovery.py:54`) is already the closest thing to a platform contract — it carries `id/source/kind/name/description/version/url/install/tools/resources/prompts/metadata{author,tags,license,rating,downloads}` and **already enumerates `kind="prompt"`** (`:59`). We promote it into `EntityMeta`, the superset that backs **installed *and* discovered** objects.

```python
# api/models/entity_meta.py  (NEW)
class EntityMeta(BaseModel):
    # ── identity ──
    id: str                 # kind-namespaced, stable: "agent:xsiam-analyst", "prompt:python_developer"
    kind: KindEnum          # agent|model|prompt|skill|plugin|mcp|workflow|project|context|workspace
    name: str
    description: str = ""
    icon: str = "❖"         # AgentIcons glyph  (the shared visual grammar)
    tone: str = "teal"      #   + token tone
    # ── provenance & lifecycle ──
    provenance: Literal["builtin","user","discovered","generated"] = "user"
    maturity:  Literal["seed","shape","chain","formalize","operate"] = "shape"
    version:   str = "1.0.0"
    owner:     str = "local"          # single-operator today; reserved for 2.x RBAC
    created_at: str | None = None     # ISO8601 (stamped/back-filled by the adapter)
    updated_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_uri: str | None = None     # canonical link/path back to the native store
    # ── typed payload + computed edges ──
    spec:  dict = Field(default_factory=dict)   # kind-specific (validated by the descriptor's schema)
    edges: "Edges | None" = None                 # {uses:[Ref], used_by:[Ref]}  — derived, never stored
```

**Namespaced ids (`kind:id`)** are the canonical cross-kind reference form: they make edges unambiguous and make `/api/objects/{kind}/{id}` addressable. A back-compat shim resolves bare ids (`xsiam-analyst`, `MODEL_REGISTRY` keys, `StepPrompt.role_ref` file paths) during migration — see Open Questions.

### 2.2 Common fields (all ten kinds carry these)

| Field | Meaning | Where it lives natively | Surfaced on |
|---|---|---|---|
| `id` | kind-namespaced stable key | native store key/filename | card header, deep-links |
| `kind` | one of ten | the descriptor | card badge, shell filter |
| `name` / `description` | human display | native | card + Overview |
| `icon` / `tone` | `AgentIcons` glyph + token tone | native or descriptor default | card + Overview |
| `provenance` | `builtin \| user \| discovered \| generated` | native or synth by adapter | card source-pip |
| `maturity` | `seed→shape→chain→formalize→operate` | derived from state | card `MaturityMeter` |
| `version` | semver or `"unknown"` | native (plugins) / overlay / default | card + History |
| `owner` | operator id (`local`) | synth | Overview |
| `created_at` / `updated_at` | ISO timestamps | native (agents/projects) / synth from mtime | Overview + History |
| `tags` | free taxonomy | native / overlay | card chips + facets |
| `source_uri` | canonical path/link | native | Overview + Discover install |
| `edges` | `uses[]` / `used_by[]` | **derived** (`reference_index`) | Dependencies + Usage tabs |

`maturity` is the one cross-object status axis (borrowed from the Composer's `MaturityMeter`). A derived **`health` pip** (`ok | error | stale | unreachable`) rides alongside for live kinds (mcp reachability, workflow last-run, model residency).

### 2.3 Kind-specific `spec` (the typed payload each descriptor validates)

| Kind | `spec` payload (unchanged native models) |
|---|---|
| `agent` | `model, role, system_prompt, context[], tools[], starters[], temperature, max_tokens` (`AgentDefinition`) |
| `model` | `runner(ollama\|vllm), source, size, context, speed{host}, family, license, params, installed, fits_ram, benchmarks, role_fit` |
| `prompt` | `prompt_kind(role\|template\|full), body, template_ref, variables[], constraints[], inject, engine(plain\|jinja)` **(NEW)** |
| `skill` | `host_plugin_id, inject(system\|none), triggers[], persona, category` |
| `plugin` | `author, path, origin(system\|user), overrides_system, tools[](schema), skills[]` |
| `mcp` | `transport, command/args/env \| url/headers, timeout, enabled, tools[](live), runner_stats` |
| `workflow` | `schema_version, defaults{}, steps[], references{}, category` (`WorkflowDefinition`) |
| `project` | `category, system_prompt, artifacts{workflows,agents,mcp,plugins,models,documents,chats}` |
| `context` | `doc_kind(document\|artifact\|graph), chunks, backend, rag_ingested, capture_context{}` |
| `workspace` | `root, policy{read_only,allowed_extensions,max_file_size_mb}, index_counts, stats{files,bytes}` |

### 2.4 Metadata storage — three tiers, no data moves

```
TIER 1  NATIVE (authoritative)      agents/*.yaml · workflows/*.yaml · data/projects/*.yaml
        envelope + spec live here    plugin.yaml · mcp servers.json · prompts/{roles,templates}
        where the store can hold it   Chroma · Ollama · MODEL_REGISTRY (code)
                     │  projected by the CrudAdapter (native ↔ EntityMeta)
                     ▼
TIER 2  DERIVED SIDECAR (registry-owned, NEW)     data/registry/
        • usage.jsonl   append-only last-used/use-count  (op-sourced like kanban tasks)
        • graph.json    the uses/used-by edge cache      (rebuilt on write)
        • overlay/model/<id>.json   editable tags/owner/version/notes for CODE-defined
          MODEL_REGISTRY entries → models become annotatable without a code change
                     │
                     ▼
TIER 3  ENRICHMENT PROVIDERS (unchanged)   data/discovery/model_benchmarks.json
        per-kind quality/benchmarks         agentic_discovery feeds · HF discovery_service
```

**Design rule that keeps this honest:** the registry owns the *contract*, never the *storage*. Fields a native store can't hold (model `version`/`owner`, prompt envelope over a flat `.md`) live in a Tier-2 sidecar; the body/native record stays authoritative and the sidecar **lazily heals** on read. `usage.jsonl` is written at the **router boundary** (not inside the frozen engine).

---

## 3. The unified Library shell, Card, and Deep-Dive

### 3.1 `ObjectShell` — one browse+search+discover surface, parameterized by kind

`api/static/js/library/object-shell.js` generalizes every current panel (`agents.js` list, `models.js CatalogPage`, `SkillsDiscover`, `PluginsPanel`, `MCPPanel`) into a single component fed by two endpoints:

```
GET /api/objects/{kind}            → { items:[EntityMeta], facets:{tags,provenance,maturity}, total }
GET /api/objects/{kind}/discover   → { items:[EntityMeta provenance=discovered], feeds:[health] }
```

```
┌ ObjectShell (kind=prompt) ─────────────────────────────────────────────────┐
│ ✦ Prompts  (14)                 [＋ New Prompt]        [ Installed | Discover ]│  ← segmented control
│ 🔍 search…    #role #template   · prov: user·builtin   · maturity ▾   sort ▾  │  ← ⌘K + facet chips
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌── EntityCard ──┐  ┌── EntityCard ──┐  ┌── EntityCard ──┐  ┌── EntityCard ──┐ │
│  │  …             │  │  …             │  │  …             │  │  … [Install]   │ │  ← discoverable
│  └────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘ │    swaps primary action
└──────────────────────────────────────────────────────────────────────────────┘
```

The **segmented `[ Installed | Discover ]` control is the local-vs-marketplace unification** — one pattern for every kind. `Installed` hits `/api/objects/{kind}`; `Discover` hits `/api/objects/{kind}/discover`, which the descriptor's `DiscoveryProvider` fans out to whichever upstream already exists (`mcp_registry`, `skills_marketplace`, HF `discovery_service` normalized into `DiscoveryItem`, or the new `prompts_marketplace`). Kinds with no upstream (`project`, `workspace`, today `agent`/`plugin`) set `discovery: None` and the segment simply hides. This folds the **three fragmented discovery systems behind one grammar without deleting any of them.**

The Composer palette is the *same* `ObjectShell` in **chip mode** (renders `RoleChip` + `▶Test` + `[Promote]` instead of `EntityCard`) reading the *same* endpoint — §5.

### 3.2 `EntityCard` — one card, kind-adaptive metric row

`api/static/js/library/entity-card.js` replaces `.agent-tile` / `.inv-card` / `.plugin-card` / `.cap-card` / MCP rows. Fixed grammar, one variable zone.

```
┌─────────────────────────────────────────┐
│ [icon]  NAME                    ⋮ menu   │  icon+tone · name · overflow(CRUD verbs)
│  kind · ●provenance-pip · v{version}     │  StatusPip colour = maturity; pip glyph = provenance
│  description (2-line clamp)               │
│  ▸ SLOT: kind-adaptive metric row        │  ← the ONLY kind-variable zone
│  #tag #tag · ⇖ used-by N · ⟳ last-used   │  tags + interop count + usage
└─────────────────────────────────────────┘
```

| Kind | metric row | primary action |
|---|---|---|
| agent | model chip · tool/context counts · role `FitBar` | Chat → |
| model | size · ctx · speed `FitBar` · fits-host pip (green/red) | Seed chat / Pull |
| prompt | `prompt_kind` badge(role\|template\|full) · N vars · used-by N | Preview render → |
| skill | host-plugin chip · trigger count · inject badge | Test trigger |
| plugin | skill/tool counts · origin(system\|user) badge | Open |
| mcp | transport · N tools · reachable `StatusPip` | Test handshake |
| workflow | step count · mini-DAG SVG sparkline · category chip | Run ▶ |
| project | artifact-count roll-up (wf/agent/mcp/doc) · task `StatusPip` | Open |
| context | `doc_kind` badge · chunk count · rag-indexed pip | Search → |
| workspace | policy badge(RO/RW) · file count · worklist glyph | Open FILES/INDEX |

The `⇖ used-by N` chip and the source-pip/`MaturityMeter` are present on **every** card regardless of kind — the graph-first signature. Because the metric row is the only variance, **adding Prompts needs zero card code.**

### 3.3 `AssetPeek` — one deep-dive, generalized to a kind→renderer registry

Today `asset-peek.js:144` is a 3-line dispatch:

```js
function open(kind, id) {
  if (kind === 'model')  return openModel(id);   // :145
  if (kind === 'agent')  return openAgent(id);   // :146
  if (kind === 'plugin') return openPlugin(id);  // :147
}
```

Generalize it into a registry while keeping the shared `#asset-peek` slide-over, `_show/_section/_kv/_fitRow`, and the terminal `seedChat()` verbatim:

```js
const RENDERERS = {};                                  // kind → DeepDiveSpec
function register(kind, spec){ RENDERERS[kind] = spec; }
function open(kind, id){ return (RENDERERS[kind] || RENDERERS._missing).render(id); }
```

Every kind supplies a `DeepDiveSpec` returning the **same six tabs**; a kind hides a tab it doesn't populate. Re-registering `model`/`agent`/`plugin` with their existing bodies proves zero regression before any new kind is added. This retires the four bespoke deep-dives (`mcp.js renderDetail`, `SkillsDiscover.openDetail`, `WorkflowIndex.deepDive`, `PluginsPanel.renderDetail`) into `DeepDiveSpec` section builders. (It also fixes the real inline-`onclick` at `asset-peek.js:103` on the way through — migrated to `data-action`.)

```
┌ AssetPeek slide-over ─────────────────────────────────────────┐
│ [icon] NAME · kind · v{ver} · ●provenance · ▰▰▰▱▱ maturity  ✕  │
│── Overview · Config · Dependencies · Usage · History · Actions ─│
│                                                                 │
│   (tab body — built by the kind's DeepDiveSpec section builder) │
│                                                                 │
│ footer:  [ 💬 seedChat ]   [ Promote to step ▸ ]   Edit·Dup·⌫  │  ← terminal action, ALL kinds
└─────────────────────────────────────────────────────────────────┘
```

**Overview / Dependencies / Usage / History are identical code for every kind** (they read the envelope + `edges` + `usage.jsonl`). Only **Config** is bespoke. **Actions** always ends in `seedChat()` — "every deep dive ends in a conversation."

### 3.4 What each tab shows, per kind

| Kind | Overview | **Config** (bespoke) | Dependencies | Usage | History | Actions |
|---|---|---|---|---|---|---|
| **agent** | envelope + starters | model/role/system_prompt/tools/context form | uses: model, prompt, skills, plugins, mcp, context / used-by: steps, projects | last-used, eval pass/fail | version, eval runs | Chat →, Edit, Dup, Export, Promote |
| **model** | envelope + benchmarks/role-fit | specs (read-only) + **unload** + overlay retag | uses: runner, cloud-provider / used-by: agents, steps, workflows | live residency, `_workflows_referencing` | overlay version notes | Seed chat, Pull, Compare, Retag |
| **prompt** | envelope + body preview | body editor + `inject` + vars + **live /render preview** | uses: role/template (full), mcp-source / used-by: agents, steps | render count | edit log (updated_at) | Render, Edit, Dup, Export, Promote(role_ref) |
| **skill** | envelope | **SKILL.md editor** (in-place) + triggers | uses: host plugin / used-by: chats, steps, agents | inject count | version (NEW) | Edit + reload, Uninstall, Promote(tool) |
| **plugin** | envelope + identity(author/path) | tools accordions + **live tool tester** | uses: child skills+tools / used-by: agents, steps, chats, projects | tool invocations | version (native) | Reinstall, Uninstall, Export tarball |
| **mcp** | envelope | transport/env form + **Test handshake** + tools list | uses: advertised prompts+tools / used-by: agents, steps, projects | runner stats (pid, handshake_ms, errors) | health checks | Test, Discover tools, Enable/Disable, Edit, ⌫ |
| **workflow** | envelope + category | **per-step mini-cards** + Steps/Schedule/References/Runs sub-panels | uses: step→{agent,prompt,model,tools,skills} / used-by: projects | last-run `StatusPip`, run history | version, runs | Run ▶, Edit-in-Composer, Export, **DELETE (NEW)** |
| **project** | envelope | **artifact-membership grid** (typed sub-cards) + system_prompt | uses: all artifacts / used-by: scoped chats | task counts, last activity | version | Open, Edit, Export, ⌫ |
| **context** | envelope | chunks + **search preview** \| artifact body \| graph | uses: re-ingested source / used-by: agents, projects | retrieval hits | reindex log | Search, Reindex, ⌫ |
| **workspace** | envelope | **FILES navigator + INDEX worklist board** | uses: produced artifacts / used-by: steps, runs | worklist progress | binding history | Bind-to-step, Render MOC, Forget |

### 3.5 Nested mini-cards answer "keep adding sub-panels for workflow objects"

The **Config** tab renders composite objects recursively with the *same* `EntityCard` in chip mode: a Workflow's Config renders each step as a mini-card whose `uses` (agent, prompt, model, tools) are clickable chip-cards that re-open the peek on that neighbour — a drill-down *tree*, not a new template per level. A Project's Config renders its `ProjectArtifacts` bag as mini-cards grouped by kind. A `full` Prompt renders its role + template as two chip-cards. **One recursive card grammar replaces "add another sub-panel."**

---

## 4. Uniform CRUD user-story template + full per-object matrix

### 4.1 The template (every kind fills the same six blanks)

```
CREATE     "As an operator I create a {kind} by {origin path} → it lands as
            EntityMeta with provenance={p}, maturity=seed, stamped timestamps."
UPDATE     "I update it by {edit surface} → re-stamps updated_at, re-validates spec."
REMOVE     "I remove it by {delete verb} → the registry checks used-by FIRST
            (409 + dependents list unless forced)."
DUPLICATE  "POST /api/objects/{kind}/{id}/duplicate → clones spec, mints new id, provenance=user."
EXPORT     "GET  /api/objects/{kind}/{id}/export → bundle (envelope + spec + inlined deps)."
IMPORT     "POST /api/objects/{kind}/import → validates, bumps version."
```

### 4.2 Uniform routes (the registry mounts these for every kind; kind-specific routers stay for extras)

```
GET/POST   /api/objects/{kind}                 ·  GET/PATCH/DELETE /api/objects/{kind}/{id}
POST       /api/objects/{kind}/{id}/duplicate  ·  GET  /api/objects/{kind}/{id}/export
POST       /api/objects/{kind}/import          ·  GET  /api/objects/{kind}/{id}/edges
POST       /api/objects/{kind}/{id}/{render|test|invoke}   (kind's "audition" verb)
POST       /api/objects/{kind}/discover/{item_id}/install  (discoverable kinds)
```

`/api/objects/*` is the **common denominator**; the native routers (`agents /evaluate`, `mcp /invoke`, `workflows /run`) remain the **specialized** surface. The registry route delegates to the kind's `CrudAdapter`, which binds to the *real* shipped service — nothing about the engine or existing endpoints moves.

**Affordance discipline (grafted from EntityKit):** a kind that cannot fulfil a verb **greys it, never hides it** — uniformity of *affordance* even where backend parity is incomplete (a model catalog `Edit` is greyed with guidance, not absent).

### 4.3 The full per-object CRUD matrix

| Kind | Create | Update | Remove | Manage (dup/export) | Real backend | Discovery |
|---|---|---|---|---|---|---|
| **agent** | modal · doc-generate (`/generate`+`/save`) · YAML | PUT `/api/agents/{id}` | DELETE (used-by guard) | dup=copy YAML · export inlined in wf/project bundle | `agents.py` + `agent_service.py` + `agent_generator.py` | none upstream (segment hidden) |
| **model** | `inventory/pull` · cloud `POST /cloud-providers` · **catalog=code → create 405+guidance** | **overlay retag/owner/notes** · `unload` · cloud PATCH | `inventory/remove` · cloud DELETE · catalog delete greyed | dup greyed (code) · export enrichment · Compare | `inventory.py` + `model_registry.py` + `MODEL_REGISTRY` + `cloud_providers.py` | HF `discovery_service` → `DiscoveryItem` |
| **prompt** *(NEW)* | form · generate-from-agent · install-from-registry | PATCH (rewrite body, re-parse vars) | DELETE (used-by guard closes silent-break) | dup/version/export `.md`/`.jinja` | **`prompt_service.py` + `prompts.py`** (seeds `roles.py`) | **`prompts_marketplace.py`** (kind reserved) |
| **skill** | `SkillsBuilder` · `/discover/{id}/install` · `/import` | GET+PUT `/skills/source/{id}` + `/plugins/reload` | `/discover/{id}/uninstall` (used-by guard) | dup=create-new-id · export SKILL.md · **version NEW** | `skills.py` + `plugin_service.py` | `skills_marketplace` (skills-sh) |
| **plugin** | `POST /plugins/install` (tarball) | reinstall + `/plugins/reload` | DELETE (user layer; system 403) | export=tarball · version native | `plugins.py` + `plugin_service.py` | none (segment hidden) |
| **mcp** | manual `POST /mcp/servers` · catalog `/discover/{id}/install` | PATCH `/mcp/servers/{id}` · toggle | DELETE (used-by guard) | export config (masked) | `mcp.py` + `mcp_service.py` + `mcp_runner_pool.py` | `mcp_registry` (modelcontextprotocol.io) |
| **workflow** | `/workflows/save` · `/workflow-index/import` · scaffold | re-save `overwrite=true` (Edit-in-Composer) | **DELETE (NEW — gap closed)** | dup=save-as · export=`/workflow-index/{id}/export` | `workflows.py` (923L) + `workflow_index.py` + FROZEN engine | register as provider (no external yet) |
| **project** | `POST /projects` (consolidate 2 modals) | PATCH + artifact add/remove | DELETE (present, `projects.py:52`) | export=project-bundle | `projects.py` + `project_service.py` | none (segment hidden) |
| **context** | `POST /documents` (upload) · capture artifact | `/documents/{id}/reindex` | DELETE doc · **artifact soft-delete (NEW)** | export via RAG re-ingest | `documents.py` + `feedback.py` + Chroma | none |
| **workspace** | `POST /workspaces` (bind dir) | `/edit`,`/expand`, index status | DELETE = **forget binding, never deletes files** | export = render MOC | `workspace.py` + `workspace_index.py` + `workspaces.py` | none |

**Only two net-new CRUD verbs** exist in this whole matrix: workflow `DELETE` and artifact soft-delete. Everything else is an adapter over shipped code. Prompts and Projects are the two *reference implementations* of complete uniform CRUD; Models are the honest exception (read-mostly, code-defined catalog).

---

## 5. Interoperability graph & Composer composition

### 5.1 The graph is already implicit — unify the extractors, then invert

Every edge already has a bespoke extractor. Unification = run them all into one edge model and reverse-index for `used_by`.

| Edge (uses →) | Extractor that exists today |
|---|---|
| workflow step → agent/model/role/plugin/mcp/skill | `WorkflowIndexService._extract_references` |
| agent → tools (plugin/mcp) | `AgentService._validate_tools` (via `extension_preflight`) |
| agent → context (file/url/graph/workflow_output/text) | `agent_service._resolve_workflow_output` |
| agent → **prompt** (system_prompt source) | **NEW** — optional `AgentDefinition.prompt_ref` |
| step → prompt | `StepPrompt.role_ref` (`workflow_models.py:43`) |
| step → step (DAG) | `AgentStep.depends_on` |
| project → {workflows,agents,mcp,plugins,models,documents,chats} | `ProjectArtifacts` typed bag |
| model ← workflow (reverse, already!) | `inventory._workflows_referencing(name)` |
| skill → host plugin | `plugin.yaml skills[]` |
| artifact → context (RAG) | `feedback.py:146-158` re-ingest |
| mcp → prompt (advertises) | `DiscoveryItem.prompts[]` |
| agent/step → workspace (memory) | `workspaceRef` |

### 5.2 `reference_index.py` — one edge store, generalized from `_workflows_referencing`

```python
# api/services/reference_index.py  (NEW)  — cached at data/registry/graph.json, rebuilt on write
class Ref(BaseModel): kind: str; id: str; via: str
def build_edges() -> list[Edge]:      # UNION the extractors above (adapters, no new parsing)
    ...
def uses(kind, id)    -> list[Ref]:   # outbound
def used_by(kind, id) -> list[Ref]:   # inverted index — free once uses is built
```

Exposed as `GET /api/objects/{kind}/{id}/edges`, consumed by every deep-dive's **Dependencies** + **Usage** tabs and the card's `⇖ used-by N` chip. This finally answers what the platform *cannot* answer today — *"which projects contain workflow X"*, *"which agents use prompt Y"*, *"which workflows consume model Z"* — all three become one `used_by()` call. It also makes **delete safe**: `DELETE` consults `used_by` and returns `409 + dependents` (closing the "delete a `role_ref` target → silent compose-time break" gap).

### 5.3 The object dependency graph

```
project ──uses──▶ workflow ──uses──▶ step ──uses──▶ agent
   │                 │                 │              ├──▶ model ──▶ runner
   │                 │                 ├──▶ prompt    ├──▶ prompt (role_ref)
   ├──▶ agent        │                 ├──▶ skill     ├──▶ skill ──▶ plugin
   ├──▶ context      │                 ├──▶ plugin    ├──▶ mcp
   ├──▶ model        │                 ├──▶ mcp       ├──▶ context (grounding)
   └──▶ mcp/plugin   └──▶ model        └──▶ workspace └──▶ workspace (memory)

context/artifact ──indexes──▶ RAG      mcp ──advertises──▶ prompt/tool
workspace ──bound-by──▶ step/run       run ──writes──▶ workspace
```

### 5.4 How it powers Composer composition — the seam into the Composer plan

The Composer palette (`loadWorkbenches@7219`) becomes `ObjectShell` in **chip mode** over the same `GET /api/objects/{kind}`, so the [Composer design](2026-07-09-composer-workflow-builder-design.md)'s thesis — *"every library object is a palette object"* — becomes literal, not aspirational. Consequences, all consistent with that doc's frozen-engine constraint:

- **Selection → deep-dive parity.** Clicking a palette object sets `selection={kind:'palette',paletteRef:{type,id}}` (Composer §3); `renderRightPane` shows the *same* `DeepDiveSpec` Config + a **live audition bench** (agent→mini-chat, prompt→`/render`, skill/plugin/mcp→invoke form, workspace→FILES/INDEX) + `[Promote to step ▸]`. The Library deep-dive and the Composer right pane are **one descriptor set**.
- **Promote maps object → engine slot.** Prompt → `StepPrompt.role_ref`; Agent → node `system_prompt` (`dfAddNodeFromAgent@4947`); Skill/Plugin/MCP → `ToolRef` (`dfAddTool@5602`/`dfAddSkill@5617`); Model → step `model`. The seed thread's attachments ride along (Composer §3 re-key). **Building a workflow = assembling objects and letting the graph record the edges.**
- **The graph closes the loop.** A step that references a Prompt appears in that Prompt's **Usage** tab immediately — the deep-dive's Dependencies/Usage tabs and the Composer canvas are *two views of one graph*. `companion-suggest` (`composer/assist`, `dfFetchCompanions@5357`) can rank from used-with statistics.

No engine change at any point: composition still flows through `test-step`, `dfExportYaml`, and workflow YAML.

---

## 6. IA reorg — Build / Operate / Library / Admin

### 6.1 The governing rule (what makes the buckets earn meaning)

The current nav (`index.html:276-322`) has `aria-hidden` section labels but a flat, behaviorally-meaningless grouping. Henry's two asks only make sense if the buckets carry a rule:

| Bucket | Contains | Litmus test |
|---|---|---|
| **Build** | authoring surfaces that *produce* objects | "Do I compose here?" |
| **Operate** | stateful, run-tied, accumulating **instances** | "Does this grow as I run things?" |
| **Library** | stateless, reusable, composable **definitions** — the palette inventory | "Would I drop this into a workflow as a block?" |
| **Admin** | platform / host / secret configuration | "Is this about the machine, not the work?" |

This rule justifies both moves:

- **Context/Research → Operate is correct.** A Context source is *stateful and run-tied*: documents re-chunk/re-embed into Chroma, research artifacts are append-only (`data/feedback/artifacts.jsonl`) and auto-re-ingested (`feedback.py:146-158`), and deep-research shares state with Runs (`window._lastResearch` survives tab switches). It **accumulates**; it is the evidence a run produced, not a block you drop into a DAG.
- **Prompts → Library is correct.** A Prompt (role / template) is the *purest* stateless reusable definition on the platform — opaque, side-effect-free text that many agents and steps reference. It is exactly a palette block, the missing sibling of Agent/Model/Skill/Plugin/MCP.

**Library = a noun you drag into a build. Operate = a live thing that accumulates state.**

### 6.2 Target map

```
BUILD      Composer          data-tab="dashboard"       (the selection machine — Composer plan)
           Workflow Index    data-tab="workflow-index"  (produced DAGs; re-skinned onto EntityCard/AssetPeek)

OPERATE    Projects          data-tab="projects"        (gains a real card grid + deep-dive; Kanban moves HERE)
           Runs              data-tab="runs"
           Context           data-tab="documents"       ← MOVED from Library
             ├ Documents (RAG)  ├ Research artifacts  └ Knowledge graph   (disentangle the conflated tab)
           Workspaces        data-tab="workspaces"      ← NEW front door for the UI-less C2/C3 runtime

LIBRARY    Agents            data-tab="agents"
           Models            data-tab="inventory"
           Prompts           data-tab="prompts"          ← NEW object (slots between Agents and Skills)
           Skills            data-tab="admin-skills"
           Plugins           data-tab="admin-plugins"
           MCP               data-tab="admin-mcp"
           (Context REMOVED from here)

ADMIN ▾    System (Memory/Keys/Runs hub) · Cloud Models · Exports · Catalog
```

Two secondary corrections the reorg carries (both are pre-existing IA debt):

1. **Kanban** (`kanban.js`, currently nested inside `#tab-workflow-index` while operating on Projects) moves under the **Projects** tab in Operate. It is a project concern.
2. **Workspaces** (`api/routers/workspaces.py` — full CRUD, zero UI today) gets a real Operate tab beside Runs (a run *writes into* a workspace). Additive: a new `data-tab="workspaces"` panel + a `library/workspaces.js` that reuses the shared shell.

### 6.3 Sub-panels for workflow objects

Per §3.5, the Workflow deep-dive's **Config** tab hosts the workflow's step sub-panels (Steps / Schedule preview / References / Runs), each itself an `ObjectShell`/`DeepDiveSpec` over the step's composed objects — a workflow becomes a *container of objects* browsable with the same shell **recursively**. This is the structural answer to "keep adding sub-panels for workflow objects": one recursive grammar, not N bespoke panels.

### 6.4 Concrete nav edits (no new inline handlers)

`data-tab` ids stay stable (deep links + `switchTab` muscle memory preserved). The reorder is DOM sibling order within `.tab-nav`, plus two new buttons. The existing nav uses inline `onclick="switchTab('documents', this)"`; the **no-new-inline rule forbids adding new `on*=`**, so the two new buttons use `data-action` delegation:

```html
<!-- NEW — Library group -->
<button class="tab-btn" data-tab="prompts"
        data-action="nav.switch" data-tab-target="prompts">
  Prompts<span class="tab-count" id="prompts-count"></span></button>
<!-- NEW — Operate group -->
<button class="tab-btn" data-tab="workspaces"
        data-action="nav.switch" data-tab-target="workspaces">
  Workspaces<span class="tab-count" id="workspaces-count"></span></button>
```

`nav.switch` is a one-line delegation wrapper over the existing `switchTab()` — no new global, no new inline handler — and becomes the pattern legacy tabs migrate onto later. Add `prompts-count` / `workspaces-count` to the existing tab-count badge family (`wfi-count`, `agents-count`, `inv-count`, `plugins-count`, `skills-count`, `mcp-count`).

---

## 7. The Prompts library object — end to end

Prompts is the **reference implementation** of "add a kind = one descriptor + one service." It is *not* greenfield-from-nothing: a read-only seed already ships.

### 7.1 What already exists (build on it, don't duplicate)

- `api/routers/roles.py` (`prefix="/api/roles"`) — a read-only, path-traversal-safe lister/getter of `prompts/roles/` returning `RoleSummary{id,name,summary,path}` / `Role(+content)`, synthesizing `name` from the filename and `summary` from the first non-empty line (`_summarize`).
- `api/services/prompt_composer.py` — `PromptComposer.compose(role_ref, role_inline, …, template_name="five_part.jinja")` (`:57`) with a containment-checked `_load_role` (`:101`) and a `ComposedPrompt{system,user,params}` output (`:18`). Wired once in `workflow_engine.py:166` and driven from `StepPrompt`.
- On disk: `prompts/roles/{python_developer,qa_engineer,senior_data_architect}.md` + `prompts/templates/{five_part,five_part_prefix_locked}.jinja`.

What's missing: templates as a browsable kind, **write** CRUD, a metadata envelope, a card, an `AssetPeek` deep-dive, discovery, and interop back-references.

### 7.2 Object shape — `PromptConfig(EntityMeta)`

```python
# api/models/prompt_models.py  (NEW)
PromptKind = Literal["role", "template", "full"]
#   role     → prompts/roles/<id>.md        (persona text; the StepPrompt.role_ref target)
#   template → prompts/templates/<id>.jinja (5-part skeleton, Jinja)
#   full     → prompts/composed/<id>.yaml   (a role_ref + template_ref + defaults preset)

class PromptSpec(BaseModel):
    prompt_kind: PromptKind
    body: str                                  # the .md persona OR the .jinja source
    template_ref: str | None = None            # full-kind: which template it renders through
    variables: list[str] = Field(default_factory=list)   # parsed {{ vars }}
    constraints: list[str] = Field(default_factory=list)  # lifts StepPrompt.constraints to standalone
    inject: Literal["system","user","none"] = "system"
    engine: Literal["plain","jinja"] = "plain"

class PromptConfig(EntityMeta):   # envelope + typed body (see §2)
    spec: PromptSpec
```

The envelope is deliberately the field-set agents already carry and `DiscoveryItem` already defines, so the shared card/deep-dive/CRUD apply for free.

### 7.3 Persistence — files stay authoritative

- `role` → `prompts/roles/<id>.md` (body verbatim; envelope in optional YAML front-matter, synthesized from filename when absent — exactly `roles.py:_summarize` behaviour, so hand-authored `.md` files stay first-class).
- `template` → `prompts/templates/<id>.jinja` (body verbatim).
- `full` → `prompts/composed/<id>.yaml` (new subdir).
- Envelope fields a flat file can't hold (`version`, `provenance`, timestamps) live in a `prompts/.meta/<id>.json` Tier-2 sidecar; the **body is authoritative** and the sidecar lazily heals. No new DB. This mirrors `AgentService` exactly (YAML-backed CRUD, id-charset validation, timestamp stamping).

### 7.4 Backend — `prompt_service.py` + `api/routers/prompts.py`

Router shape is a line-for-line mirror of `mcp.py` (the reference CRUD surface), which is why the kind is cheap:

```
GET    /api/prompts                    list PromptConfig summaries (roles ∪ templates ∪ full)
POST   /api/prompts                    create → writes the right dir by spec.prompt_kind
GET    /api/prompts/{id}               full PromptConfig
PATCH  /api/prompts/{id}               update (exclude_unset, re-parse vars, re-stamp updated_at)
DELETE /api/prompts/{id}               remove (+ used-by guard → 409 with dependents)
POST   /api/prompts/{id}/render        PREVIEW — reuse PromptComposer, no new engine code
GET    /api/prompts/discover           catalog + remote (mirrors /api/skills/discover)
POST   /api/prompts/discover/{cid}/install
GET    /api/prompts/{id}/edges         uses / used-by (reference_index)
```

`/render` is the key reuse — it constructs a `PromptComposer(roles_dir, templates_dir)` (same args as `workflow_engine.py:166`) and calls `.compose(role_ref=…, role_inline=body, task=sample, constraints=spec.constraints, template_name=spec.template_ref or "five_part.jinja")`, returning `ComposedPrompt{system,user,params}` for the live Config-tab preview. **Zero engine change; the frozen composer is used as a pure library.** Keep `/api/roles` as a thin back-compat alias delegating to `prompt_service.list(kind="role")` (the Composer "Roles" bench consumes it). All write routes gated by `require_master_key`.

### 7.5 Card, deep-dive, CRUD stories

- **Card:** `EntityCard`, metric row = `prompt_kind` badge + var count + `used-by N`, primary = `Preview render →`. Kind-chip tinted by `prompt_kind` using the existing `--node-*` tokens.
- **Deep-dive:** `DeepDiveSpec` — Overview(body preview) · **Config**(body editor + `inject` + var table + live `/render`) · Dependencies(uses: role/template for `full`, mcp-source; used-by: agents + steps) · Usage(render count) · History(edit log) · Actions(`Render`, `Edit`, `Duplicate`, `Promote → StepPrompt.role_ref`, `seedChat` with this persona as system). **Zero new pane code.**
- **CRUD:** create via form (pick kind + body + tags), or **generate-from-agent** (extract an agent's inline `system_prompt` into a shared Prompt), or import from Discover. Update = PATCH (id immutable). Remove = DELETE guarded by `used_by`. Duplicate/version/export uniform.

### 7.6 Interop (closes the loop the Composer needs)

- **Prompt ← Workflow step:** `StepPrompt.role_ref` (`workflow_models.py:43`) already points at `prompts/roles/<ref>.md`. The Prompt object is now *the thing that reference resolves to* — closing the library↔composer palette loop.
- **Prompt ← Agent:** agents carry `system_prompt` inline today. A new optional `AgentDefinition.prompt_ref` lets an agent *reference* a Prompt instead of duplicating text — one source both agents and steps share; editing the Prompt propagates via `used_by` to every consumer.
- **Prompt ← Discovery:** `agentic_discovery` already reserves `kind="prompt"` (`:59`) and `DiscoveryItem.prompts[]` (`:67`); a new `prompts_marketplace.py` wires `github_prompts`/`x1xhlol`/`claude_code` feeds — no provider-registry change. MCP-advertised prompts surface as Prompt cards sourced from a server.
- **Prompt → Composer palette:** the "Roles" bench becomes a Prompts bench; a Prompt is a Promotable palette block mapping to `StepPrompt.role_ref` on drop.

---

## 8. Platform alignment points

The "one family" feel is four shared substrates. Each half-exists; alignment is **projection, not rewrite.**

### 8.1 Shared model — `EntityMeta` (promote `DiscoveryItem`)

One envelope backs installed *and* discovered objects (§2). Agents already match; Prompts are native to it; Models get missing fields via the Tier-2 overlay JSON; Skills/MCP/Workflow/Project keep their authoritative stores and are projected.

### 8.2 Shared service pattern — YAML/JSON-backed CRUD + timestamp stamping

Every object service follows the `AgentService`/`MCPService` template that `prompt_service.py` copies: id-charset validation, `exclude_unset` PATCH merge, preserve `created_at` / re-stamp `updated_at`, `_public_view`/`_mask` secret discipline (from `mcp_service` — adopted even by low-secret kinds for consistency). Projection over migration: the service owns the contract; the flat files / Chroma / Ollama stay authoritative.

### 8.3 Shared route shape — `/api/objects/{kind}` (+ native routers for extras)

Uniform eight-verb shape (§4.2), registered the same way in `api/main.py` (`app.include_router`, `/api/*` prefix, `require_master_key` on writes). A thin `GET /api/objects/kinds` façade lets the UI enumerate kinds generically; the per-kind routers remain the real implementation.

### 8.4 Shared component set — one shell, one card, one deep-dive

| Concern | Shared component | Replaces |
|---|---|---|
| Browse grid | `ObjectShell` (grid mode) over `/api/objects/{kind}` | `.agent-tile` / `.inv-card` / `.plugin-card` / `.cap-card` / MCP rows (4+ renderers) |
| Card | one `EntityCard` (from `_ds_manifest.json`), tinted by kind | per-kind card templates |
| Palette chip | same `ObjectShell` in **chip mode**, same endpoint | separate `loadWorkbenches` renderers |
| Deep-dive | `AssetPeek` kind→renderer registry, 6-tab grammar | `#mcp-detail`, `SkillsDiscover.openDetail`, `WorkflowIndex.deepDive`, `PluginsPanel.renderDetail` |
| Sub-object drill | nested `EntityCard` chips (§3.5) | ad-hoc sub-panels |
| Chips/actions | `SeedChip`, `ActionChip`, `MaturityMeter`, `StatusPip`, `FitBar` | shadowed `esc()` redefs, inline handlers |

**Interaction discipline that keeps parity:** all wiring is `data-action` delegation (no new `on*=`, no new `window` globals; the two new nav buttons and every card/peek action use `data-action`), and `seedChat()` stays the shared terminal action so "every deep dive ends in a conversation" holds for Prompts too. The generalization pass also **fixes** the existing inline-`onclick` violations (`asset-peek.js:103`, `plugins.js`, `discover.js`) rather than propagating them.

### 8.5 Discovery reconciliation

`registry.discovery(kind)` wraps whichever of `{agentic_discovery provider, discovery_service HF crawl, inventory HF discover}` exists — Models finally flow through a `DiscoveryItem`-shaped adapter, ending the three-system split **without deleting any**. Per-feed health (`DiscoveryFeed.implemented/last_synced/error`) stays visible so a stale feed erodes no trust.

---

## 9. Phased plan (P0..P6) — incremental, parity-preserving, engine-frozen

Each phase ships independently. The order is *cheapest surface that proves the most* first.

### First slice (P0): **AssetPeek → kind-registry, then Prompts end-to-end.**

**Why this slice.** It is the cheapest surface that forces the entire contract into existence with **zero regression risk**. (1) It generalizes the deep-dive (the `asset-peek.js:144` switch → registry) and *proves no regression* by re-registering `model`/`agent`/`plugin` unchanged. (2) It delivers a real Henry ask — the Prompts library — on a kind with **no legacy card, modal, or parity to preserve**. (3) It stands up `EntityMeta`, `ObjectShell`, `EntityCard`, the `/api/objects/{kind}` route shape, and one interop edge (`StepPrompt.role_ref`) as reusable substrate. Everything after is "one descriptor + one adapter."

| Phase | Goal | Key files | Ships when | Independent value |
|---|---|---|---|---|
| **P0** | AssetPeek registry + **Prompts** vertical | `entity_meta.py`, `object_registry.py`, `prompt_models.py`, `prompt_service.py`, `prompts.py`; `asset-peek.js` (registry), `object-shell.js`, `entity-card.js`; new `prompts` nav (`data-action`) | Create a Prompt in the shell → it renders as an `EntityCard` → opens the shared `AssetPeek` (Overview/Config/Deps/Actions) → `/render` previews live | The Prompts library exists; agent/model/plugin peeks unchanged (regression-proof) |
| **P1** | `reference_index.py` + Deps/Usage tabs | `reference_index.py`, `data/registry/graph.json`; Deps/Usage `DeepDiveSpec` sections | `GET /objects/{kind}/{id}/edges` answers used-by for agent+prompt; delete-guard returns 409+dependents | "Which agents use prompt Y" answerable; safe deletes |
| **P2** | IA moves | `index.html` nav reorder; `library/workspaces.js`; move `#kanban-board` under Projects | Context sits in Operate (3 sub-panels); Prompts + Workspaces tabs live | The requested IA; Workspaces gets a front door |
| **P3** | Skill onto the shell + peek (biggest gap) | `object_registry` skill adapter; retire `SkillsDiscover.openDetail`; add `version` | Skills browse via `ObjectShell`, drill via `AssetPeek` | Kills the one object with no AssetPeek path |
| **P4** | MCP + Workflow + Project onto shell/peek | mcp/workflow/project adapters; **workflow `DELETE`**; retire `#mcp-detail`, `WorkflowIndex.deepDive`; Projects card grid | Each browses+drills through the shared components; workflows deletable | Retires 3 bespoke deep-dives; closes the delete gap; Projects become visible |
| **P5** | Model adapter + overlay + discovery reconciliation | model adapter, `data/registry/overlay/model/*`; normalize `discovery_service` → `DiscoveryItem` | Models retaggable; one Discover grammar across kinds | Models become annotatable; discovery unified |
| **P6** | Composer palette = `ObjectShell` chip-mode | `loadWorkbenches` → registry; `renderRightPane` palette bench + Promote | ⌘K cross-cut over all kinds; Promote writes graph edges | Library and Build are one machine |

### 9.1 How this **extends** the Composer plan

This plan is the object-model dependency of the [Composer design](2026-07-09-composer-workflow-builder-design.md), and it is deliberately additive to it:

- **Same constraints.** Engine FROZEN; new capability rides existing HTTP seams (`test-step`, `/render`, `/v1`, `agents/{id}/chat`, `workspaces/**`) + the frozen `PromptComposer`/`workflow_engine`; all wiring is `data-action`; no new `window` globals.
- **P0–P1 are prerequisites for the Composer's palette (Composer §2/§5b).** The Composer plan's palette-as-selection and `renderRightPane(selection={kind:'palette'})` need a per-kind browse + live-bench; `ObjectShell` chip-mode + `DeepDiveSpec` (P0, P6) *are* that.
- **P6 is the join.** The Composer's `loadWorkbenches@7219`, `renderRightPane` palette bench, and `[Promote to step ▸]` consume the envelope + `edges`; the ⌘K cross-cut filters the registry (Build ↔ Library ↔ Operate in one search). Promote maps object → engine slot (§5.4) exactly as the Composer plan's Promote gesture specifies.
- **Non-collision.** The Composer plan's P0 (retire `#df-config-popup` into the durable right pane) and this plan's P0 (retire the AssetPeek switch into a registry) touch adjacent but distinct seams and can proceed in either order; both are net-additive and parity-snapshotted.

---

## 10. Open questions for the operator

1. **Namespaced ids vs bare ids.** Adopt `kind:id` as canonical (clean cross-kind edges + one addressable route) with a resolver shim for bare ids, or keep bare ids and namespace only in the edge graph? The shim touches `StepPrompt.role_ref` file paths, `MODEL_REGISTRY` keys, and `agents.py` — a broad but mechanical surface. **Recommendation: namespaced + shim.**
2. **Model overlay store.** Editable model metadata (tags/owner/version/notes) needs somewhere to live since `MODEL_REGISTRY` is code. The Tier-2 overlay JSON risks becoming a *third* model store a `MODELS.md` sync could clobber. Accept the overlay with an explicit merge discipline (overlay wins for annotation fields, `MODEL_REGISTRY` wins for catalog facts), or defer model-editability to 2.x and grey the affordance?
3. **`agent.prompt_ref` — second persona path.** Letting an agent reference a Prompt instead of inline `system_prompt` is the keystone of the propagation story, but introduces two ways to specify a persona the resolver + edit modal must reconcile. Ship `prompt_ref` in P1, or keep agents inline-only until Prompts prove out?
4. **Usage tap-point.** `usage.jsonl` is written at the router boundary to respect the frozen engine; any run path that bypasses the router (tests/CLI/direct engine) under-counts. Is router-boundary accuracy sufficient for 1.x, or do we need an explicit engine-adjacent event that stays inside the freeze?
5. **Context disentangle depth.** Context → Operate must split the conflated tab into Documents / Artifacts / Knowledge-Graph. Are these **three sub-panels of one tab**, or three peer Operate objects (each its own `kind`)? The matrix models one `context` kind with a `doc_kind` discriminator; peer-kinds is cleaner but adds two descriptors.
6. **Six-tab ceremony.** Fixed six tabs impose structure on simple kinds (a workspace has no History, a context doc no real Dependencies). Hide-empty-tabs keeps it clean — acceptable, or should truly-stateless kinds collapse to a 3-tab variant?
7. **Discovery freshness surfacing.** With three upstreams behind one `Discover` segment (HF crawl TTL vs `mcp-registry` TTL vs inventory cache), how prominent should per-feed staleness be — a quiet pip, or a blocking "N feeds stale" banner?

---

## Appendix — verified file anchors (this session)

| Claim | Anchor |
|---|---|
| AssetPeek dispatch is a 3-line `model\|agent\|plugin` switch | `api/static/js/library/asset-peek.js:144-147` (inline `onclick` at `:103`) |
| Prompt render engine to reuse | `api/services/prompt_composer.py` — `ComposedPrompt` `:18`, `compose(role_ref, role_inline, …, template_name="five_part.jinja")` `:57`, `_load_role` `:101` |
| Prompts library seed (read-only) already ships | `api/routers/roles.py` (`/api/roles`, `RoleSummary`/`Role`, `_summarize`) |
| Step→prompt edge | `api/models/workflow_models.py` — `StepPrompt` `:40`, `role_ref` `:43`, `constraints` `:46`, `AgentStep` `:382` |
| Envelope substrate reserves `kind="prompt"` | `api/services/agentic_discovery.py` — `DiscoveryItem` `:54`, `kind` enum `:59`, `prompts[]` `:67`, `register_provider` `:163` |
| Workflow DELETE gap (present for projects) | `api/routers/workflows.py` (no `@router.delete`) vs `api/routers/projects.py:52` |
| Nav to reorder (inline `onclick`, `aria-hidden` section labels) | `api/static/index.html:276-322` |
| Composer wiring to `prompts/roles` + `prompts/templates` | `api/services/workflow_engine.py:166` |
| On-disk seed corpus | `prompts/roles/{python_developer,qa_engineer,senior_data_architect}.md` · `prompts/templates/{five_part,five_part_prefix_locked}.jinja` |

---

## Feasibility review & risks (verified)

> Adversarial verification pass (2026-07-09, branch `feat/composer-workspace`). Every claim below was checked against the actual source. Verdict: **the spine is sound and buildable — Prompts is a real, low-risk first kind and the frozen engine is genuinely untouched — but the doc's P0 is over-scoped and three specific reuse claims are wrong or oversold as written.** Fix those and the first PR shrinks by half.

### A. Confirmed feasible (with evidence)

1. **Prompts CRUD is a real backend, not hand-wave.** The mirror target is exact: `mcp.py` gates its whole router via `APIRouter(..., dependencies=[Depends(require_master_key)])` (`mcp.py:29-32`) and exposes `GET/POST /servers`, `GET/PATCH/DELETE /servers/{id}`, `/discover`, `/discover/{id}/install` — the shape §7.4 copies. The read-only seed ships and is mounted (`roles.py` → `app.include_router(roles.router)` at `main.py:332`). Seed corpus exists on disk (3 roles, 2 templates). `AgentService`'s id-charset + timestamp-stamp pattern is a valid template. **A role-kind Prompt object is buildable today.**
2. **AssetPeek dispatch → registry is trivial.** `open()` is a literal 3-line switch (`asset-peek.js:144-148`); turning it into a `RENDERERS` map is a few lines. *(But see caveat B3 — the six-tab shell is not.)*
3. **Envelope substrate is real.** `DiscoveryItem` (`agentic_discovery.py:53-68`) carries the fields, already enumerates `kind="prompt"` (`:59`) and `prompts[]` (`:67`). `AgentDefinition` (`agent_models.py:85-99`) already carries `id/name/description/icon/tags/created_at/updated_at`.
4. **The workflow `DELETE` gap is real and correctly scoped.** Zero `@router.delete` across all 923 lines of `workflows.py` (routes stop at `save`/`run`/`runs`/`memory`/`{id}`); `projects.py:52` has `@router.delete("/{project_id}")`. The new verb lives in the *router*, not the frozen engine.
5. **Discovery seam is real.** `discover.py` (`/api/discover/{sources,all,{source},{source}/refresh}`, all `Depends(require_master_key)`) over the `agentic_discovery` provider registry; prompt-kind providers are already *registered* (`stubs.py:100-127`). *(But see B7 — they are stubs.)*
6. **`AgentStep` v1/v2 boundary is enforced** (`workflow_models.py:598-604`: `kind=llm` requires exactly one of `prompt`/`system_prompt`), so Promote→`StepPrompt.role_ref` (v2) and generate-from-agent (extract v1 `system_prompt` string → a role `.md`) are both coherent.

### B. Corrections & caveats (each with file evidence)

1. **`compose()` call in §7.4 will `TypeError` as written.** Real signature (`prompt_composer.py:57-70`) makes `context: str` and `output_schema: dict` **required positional args with no defaults**; the doc's call omits both. Correct call: `compose(role_ref=None, role_inline=body, context="", task=sample, constraints=spec.constraints, output_schema={}, template_name=spec.template_ref or "five_part.jinja")`. Trivial fix, but the reuse only runs with `context` + `output_schema` supplied.
2. **`/render` is not uniform across the three `prompt_kind`s.** `PromptComposer` renders a **role** *through* a named template loaded once from `templates_dir` via `FileSystemLoader` (`prompt_composer.py:43-51`); `_load_role` raises if neither `role_ref` nor `role_inline` is set (`:116-118`). So: **role** kind renders cleanly (`role_inline=body`); **full** kind works only if its template is already on disk; **template** kind (editing an unsaved `.jinja`) has **no render path** and a pure template has no role → raises. → **Scope P0 Prompts to the `role` kind** — which is also the entire seed corpus and the `StepPrompt.role_ref` target. Defer template/full.
3. **"Six fixed tabs … keeping `_show/_section/_kv` verbatim" is internally contradictory.** The `#asset-peek` DOM has only `peek-kind/title/body/actions` — **no tab bar** (`index.html:1474-1486`) — and `_show()` sets a single flat `peek-body.innerHTML` (`asset-peek.js:42-50`). Six tabs = net-new DOM + a tab-switch render loop + a `_show` restructure. You can keep `_show` verbatim **or** add six tabs, not both. Feasible, but it is a **new shell, not a projection** — the biggest hidden cost in P0.
4. **"Fixes the inline-`onclick` at `asset-peek.js:103`" understates ~9× and conflicts with "re-register verbatim".** There are **8** inline `onclick` in `asset-peek.js` (`grep -c onclick= = 8`) plus the backdrop `onclick="AssetPeek.close()"` at `index.html:1474`. Re-registering `model/agent/plugin` "with their existing bodies unchanged" (the zero-regression proof) **preserves all 8**; fixing them means rewriting those bodies. Pick one framing — you cannot claim both zero-regression-verbatim and inline-onclick-cleanup in the same pass.
5. **"Uniform `require_master_key` on writes" is NOT the current state — it is a parity change on six kinds.** Gated today: `mcp.py` (whole router), `skills.py` (10 refs), `plugins.py` (7), `discover.py` (per-route). **Ungated today:** `agents.py`, `workflows.py`, `projects.py`, `documents.py`, `inventory.py`, `context.py`, `roles.py` (all 0 refs). A unified `/api/objects/{kind}` writer that gates uniformly would **add an auth requirement to agent/workflow/project/document/model writes that today succeed without the key** — a behavior change, not a projection. Decide explicitly: mirror each kind's current gating (non-uniform) or accept the tightening. (Repo default is `ENABLE_API_AUTH=false`, so this is latent, not loud — which is exactly why it will surprise.)
6. **"agents/*.yaml IS the envelope" = 7 of 12 fields.** `AgentDefinition` (`agent_models.py:85-99`) has no `provenance/maturity/version/owner/tone/source_uri`. Those five must be **synthesized by the adapter for every kind including agents** — the envelope is a mostly-synthesized overlay (fine), not "already there."
7. **Prompt discovery is stubs, not "feeds to wire."** `github_prompts` / `x1xhlol-prompts` / `claude_code_prompts` are registered in `stubs.py:100-127` with `implemented=False` and **zero items**. Real prompt discovery = writing the GitHub `.prompt.yaml` ingestion. Non-blocking for P0 (ship installed-only, `discovery: None`), but it is *build*, not *wiring*.
8. **"~40-line adapter per kind" is realistic for agents, optimistic for model/workflow/context.** The `model` adapter must join `MODEL_REGISTRY` (code) ∪ Ollama live ∪ `cloud_providers` ∪ `model_benchmarks.json` ∪ the new overlay; the `workflow` adapter projects a 923-line router + `workflows-private/` overlay. Fine as direction; don't hold the line count. Also note `object_registry.py`, `entity_meta.py`, `object-shell.js`, `entity-card.js`, `reference_index.py` are **all net-new** (none exist) — so "adding Prompts needs zero card code" is only true *after* P0 builds EntityCard/ObjectShell; those components are themselves P0 cost.

### C. Engine-collision assessment

**No collision in P0–P1.** Frozen files per `CLAUDE.md` are `workflow_engine.py`, `workflow_compiler.py`, `step_executor.py` — none are touched:
- `/render` instantiates a **standalone** `PromptComposer(roles_dir, templates_dir)` and uses it read-only — exactly the pattern `workflow_engine.py:166` already uses; the frozen module is imported as a pure library, never edited.
- Workflow `DELETE` lives in `workflows.py` (the *router*, 923 L, not frozen) — deleting a YAML file does not touch the engine.
- `usage.jsonl` is written at the **router boundary** by design (§ Open Q4).

Two yellow flags, both correctly deferred outside the freeze: `agent.prompt_ref` changes **`agent_service` resolution** (not the engine) and adds a second persona path the edit modal must reconcile (Open Q3); router-boundary usage counting under-counts direct-engine/CLI/test runs (Open Q4). Non-collision with the Composer plan holds — that plan's P0 touches `#df-config-popup`/`main.js`, this plan's P0 touches `asset-peek.js`; disjoint files.

### D. Tightened FIRST PR (smaller than the doc's P0)

The doc's P0 bundles **five net-new modules + a shared-component build + a regression-risky refactor of the deep-dive used by three shipping kinds + a nav change**. That is not "the smallest thing that proves uniformity." Prove the contract on the one kind that *cannot regress*, through the deep-dive that *already ships*, first. Defer the six-tab generalization and the `model/agent/plugin` re-registration to P0.5.

**Goal:** a new `prompt` kind is created, listed, deep-dived, and live-previewed through the **existing** `AssetPeek._show`, with **byte-identical** model/agent/plugin peeks. No six-tab shell, no `ObjectShell`/`EntityCard`, no engine edit.

**Backend (add):**
- `api/models/prompt_models.py` — `PromptConfig`/`PromptSpec`, **`role` kind only** for this PR.
- `api/services/prompt_service.py` — `.md`-backed CRUD over `prompts/roles/`, mirroring `AgentService`: id-charset validation, timestamps in a `prompts/.meta/<id>.json` sidecar (body stays authoritative), containment check reusing `roles.py:_id_to_path` logic.
- `api/routers/prompts.py` — mirror `mcp.py`: `GET/POST /api/prompts`, `GET/PATCH/DELETE /api/prompts/{id}`, `POST /api/prompts/{id}/render`; register in `main.py`; keep `/api/roles` as a read-only alias. **Match `agents.py` gating (ungated) for parity, or make the tighten-to-master-key call explicitly in the PR description — do not silently diverge from the sibling authoring routers.**

**Endpoints (the only load-bearing one):**
- `POST /api/prompts/{id}/render` → `PromptComposer(root/"prompts"/"roles", root/"prompts"/"templates").compose(role_ref=None, role_inline=spec.body, context="", task="(preview)", constraints=spec.constraints, output_schema={}, template_name="five_part.jinja")` → return `ComposedPrompt.system`. (Note `context=""` + `output_schema={}` — the fix from B1.)

**Frontend (minimal, no new components):**
- One line in `asset-peek.js` `open()`: `if (kind === 'prompt') return openPrompt(id);` — `openPrompt` calls the **existing** `_show('prompt', name, id, body, actions)` with a flat body (`_section('about', bodyPreview)` + a Config `<textarea>` + a Render button hitting `/render`). Reuse `_section/_kv`. No tab bar.
- List prompts with the existing agents-list grid (or a 20-line grid); do **not** build `EntityCard` yet.
- Prompts nav button in the Library group. To honor the no-new-inline rule, ship the single `data-action="nav.switch"` delegation wrapper here (the one net-new delegation); if that slips, an inline `onclick` matching the existing nine is acceptable **only** if flagged for the P2 data-action sweep.

**Acceptance check:**
- `pytest tests/ --ignore=tests/e2e -v` green, plus a new test: `POST /api/prompts` writes `prompts/roles/<id>.md` + sidecar → `GET` lists it → `POST /{id}/render` returns a non-empty `system` containing the body text → `DELETE` removes both files. Add a regression assertion that `AssetPeek.open('model'|'agent'|'plugin')` still routes to the unchanged `openModel/openAgent/openPlugin`.
- Manual: create a role prompt in the UI → it lists → open the peek → **Render** previews the composed system prompt live; open a model peek → visually unchanged.

**Then P0.5 (the doc's original P0):** generalize `AssetPeek` to the six-tab registry, re-register `model/agent/plugin`, build `ObjectShell`/`EntityCard`, and fix the 8 + 1 inline `onclick`s in one deliberate sweep — now with a proven, no-regression kind already riding the shared deep-dive.
