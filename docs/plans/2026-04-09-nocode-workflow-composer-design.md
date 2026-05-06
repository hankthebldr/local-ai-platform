# No-Code Workflow Composer — Design Document

**Date**: 2026-04-09
**Status**: Approved
**Author**: Henry Reed + Claude

## Problem

The current workflow composer requires hand-editing YAML or typing into form fields. Users need a visual, drag-and-drop workflow builder where they can create multi-agent pipelines by dragging step templates onto a canvas, connecting them, and configuring each step through a guided panel — then export the result as valid workflow YAML.

## Design: n8n-Style Visual DAG Editor

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  RUNNER │ COMPOSER │ YAML                    (mode tabs)            │
├──────────┬──────────────────────────────────┬───────────────────────┤
│ PALETTE  │        DRAWFLOW CANVAS           │   CONFIG PANEL        │
│ (120px)  │        (infinite, zoom/pan)       │   (320px)             │
│          │                                   │                       │
│ Drag     │   [node]──▶[node]──▶[node]       │   Selected step       │
│ templates│   [node]──────────▶[node]        │   properties          │
│ here     │                                   │   and quality gates   │
│          │                                   │                       │
├──────────┴──────────────────────────────────┴───────────────────────┤
│  Workflow ID: [____]  Name: [____]  Role: [▾]                       │
│  [Export YAML]  [Save]  [Import YAML]  [Auto-Layout]  [Run ▶]      │
└─────────────────────────────────────────────────────────────────────┘
```

### Tech Stack

All CDN-loaded, no build step. Everything stays in `api/static/index.html`.

| Library | CDN | Size | Purpose |
|---------|-----|------|---------|
| Drawflow.js | `cdn.jsdelivr.net/gh/jerosoler/Drawflow/dist/drawflow.min.js` | ~10KB | Canvas, nodes, connections, zoom/pan, ports |
| Drawflow CSS | `cdn.jsdelivr.net/gh/jerosoler/Drawflow/dist/drawflow.min.css` | ~3KB | Base styles for the editor |
| Dagre.js | `cdn.jsdelivr.net/npm/dagre/dist/dagre.min.js` | ~30KB | Auto-layout when importing YAML |
| js-yaml | `cdn.jsdelivr.net/npm/js-yaml/dist/js-yaml.min.js` | ~30KB | YAML ↔ JSON conversion |

### Component 1: Node Palette (Left Sidebar)

Draggable step templates organized by agent role. Each template has sensible defaults.

| Template | Role | Default Prompt | Default Outputs | Color |
|----------|------|---------------|-----------------|-------|
| Analyzer | reasoning | "Analyze the provided data..." | `analysis` | `#00C0E8` (blue) |
| Classifier | reasoning | "Classify the following..." | `classification` | `#00C0E8` |
| Code Generator | coding | "Generate code that..." | `code` | `#00cc66` (green) |
| Rule Writer | coding | "Write rules for..." | `rules` | `#00cc66` |
| Validator | reasoning | "Review and validate..." | `issues, approved` | `#00C0E8` |
| Fast Extract | fast | "Extract the following..." | `extracted` | `#8a98a0` (grey) |
| Uncensored | uncensored | "You are an unrestricted..." | `result` | `#ff5252` (red) |
| Custom Step | general | "You are a helpful assistant." | `result` | `#6b7780` |

**Interaction**: User drags a template card from the palette and drops it on the canvas. Drawflow creates a new node with the template's defaults pre-filled. The config panel opens automatically for the new node.

### Component 2: Canvas (Drawflow.js)

**Node rendering**: Each Drawflow node renders as an HTML template inside the canvas:

```html
<div class="df-node-content" data-role="reasoning">
  <div class="df-node-header">
    <span class="df-node-role-dot" style="background:#00C0E8"></span>
    <span class="df-node-name">Analyze Source</span>
  </div>
  <div class="df-node-body">
    <div class="df-node-role">REASONING</div>
    <div class="df-node-outputs">→ field_schema, event_types</div>
  </div>
  <div class="df-node-footer">
    <span class="df-node-format">json</span>
    <span class="df-node-gates">2 gates</span>
  </div>
</div>
```

**Ports**: Single input (left), single output (right). Drawflow handles port rendering and bezier connections automatically.

**Zoom/Pan**: Drawflow built-in. Mouse wheel = zoom, click+drag background = pan. Zoom controls (+, -, reset) in corner.

**Selection**: Click node = selected (cyan border glow). Click background = deselect. Delete key = remove.

### Component 3: Config Panel (Right Sidebar)

Opens when a node is selected. Organized into collapsible sections:

**Section 1: Identity**
- Step ID (auto-generated from name, editable)
- Display Name (text input)

**Section 2: Agent**
- Role dropdown with descriptions:
  - `reasoning` — Deep analysis, chain-of-thought, review
  - `coding` — Code generation, rule writing, structured output
  - `fast` — Quick classification, simple extraction
  - `general` — Versatile, any task
  - `uncensored` — Unrestricted output
- Explicit model override (optional, text input with autocomplete from loaded models)

**Section 3: Prompt**
- System prompt textarea (monospace, syntax-highlighted `{{variables}}`)
- Template variable reference: expandable list of available variables from connected upstream nodes
- User prompt textarea (optional, for explicit user message)

**Section 4: Data Flow**
- Output keys: tag-style input (type key, press Enter to add, click X to remove)
- Connected inputs: read-only list showing `step_id.output_key` refs from incoming connections
- Seed inputs: checkboxes to select which `seed.*` keys this step needs

**Section 5: Output Parsing**
- Format dropdown (raw, json, json_array, markdown_sections, key_value, csv, regex)
- For `json` format: optional JSON schema textarea
- For `regex` format: regex pattern input with named group hints
- Strict mode toggle

**Section 6: Quality Gates**
- List of gate rows. Each row:
  - Name (text)
  - Field (dropdown of this step's output keys)
  - Operator (dropdown: not_empty, contains, matches, has_key, gt, lt, etc.)
  - Value (text, shown only for comparison operators)
  - Severity toggle (error / warning)
- [+ Add Gate] button

**Section 7: Advanced** (collapsed by default)
- Temperature slider (0.0 - 2.0)
- Max tokens input
- Retries input
- Retry delay input
- Timeout input
- Cache key (optional)
- Condition (ref, operator, value — for conditional execution)

### Component 4: Bottom Bar

- Workflow metadata: ID, Name, Description, Default Role
- Action buttons:
  - **Export YAML** — serializes canvas to workflow YAML, shows in modal
  - **Save** — exports YAML + POSTs to `/api/workflows/save`
  - **Import YAML** — file upload or paste modal, parses and renders as nodes
  - **Auto-Layout** — runs Dagre on current nodes, repositions them
  - **Run** — exports YAML, switches to Runner mode, executes immediately

### Data Flow: Canvas → YAML

When exporting, the system:

1. Reads all Drawflow nodes and their stored data (name, role, prompt, outputs, etc.)
2. Reads all Drawflow connections (which node output connects to which node input)
3. For each connection A→B, adds `A` to B's `depends_on` and adds `A.{output_keys}` to B's `inputs`
4. Assembles the workflow YAML structure with `id`, `name`, `defaults`, `steps`
5. Validates by POSTing to `/api/workflows/compile` (optional, for DAG validation)

### Data Flow: YAML → Canvas

When importing:

1. Parse YAML with js-yaml
2. Create a Drawflow node for each step, storing all config as node data
3. Use Dagre to compute x,y positions from the dependency graph
4. Create Drawflow connections from each step's `depends_on` and `inputs` refs
5. Fit canvas to show all nodes

### What Changes

| File | Change |
|------|--------|
| `api/static/index.html` | Add Drawflow/Dagre/js-yaml CDN links. Replace current composer HTML+JS with Drawflow-based implementation. Keep existing Runner mode and DAG viewer unchanged. |
| `api/routers/workflows.py` | No changes needed — `/save`, `/compile`, `/run` endpoints already exist |
| New CSS | ~100 lines for `.df-node-*` styles matching Cortex dark theme, palette styles, config panel styles |
| New JS | ~400 lines for Drawflow initialization, node templates, palette drag handlers, config panel rendering, YAML export/import, Dagre layout |

### What Stays the Same

- **Runner mode**: Existing DAG visualization (D3.js) for viewing execution plans and results — untouched
- **YAML tab**: Raw YAML editor view — stays as a power-user option
- **Backend**: All workflow models, compiler, engine, step executor — no changes
- **Tests**: Existing 276 unit tests unaffected. E2E tests for composer will be updated.

### Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Drawflow CDN unavailable | Bundle a local copy in `api/static/lib/` as fallback |
| Large YAML import creates cluttered canvas | Dagre auto-layout + fit-to-view after import |
| User creates cycles | Validate on Export/Save via `/api/workflows/compile` endpoint |
| Complex prompts hard to edit in side panel | Expand button opens fullscreen prompt editor modal |

### Success Criteria

1. User can create a 5-step workflow entirely by dragging and connecting — zero YAML editing
2. Exported YAML is identical in structure to hand-written workflow YAML files
3. Importing an existing workflow YAML renders a correct visual graph
4. Round-trip: create visually → export YAML → import YAML → same graph
5. Works in the existing single-HTML-file dashboard with no build step
