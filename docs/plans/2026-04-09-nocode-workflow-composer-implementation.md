# No-Code Workflow Composer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the custom D3-based workflow composer with an n8n-style visual editor using Drawflow.js, where users drag step templates from a palette onto a canvas, connect them, configure via a right-side panel, and export valid workflow YAML.

**Architecture:** Drawflow.js handles the interactive canvas (nodes, connections, zoom/pan). A left sidebar provides draggable step templates. A right sidebar shows a config panel when a node is selected. The YAML export reads Drawflow's internal state and serializes to workflow YAML. YAML import uses Dagre.js for auto-layout.

**Tech Stack:** Drawflow.js (CDN), Dagre.js (CDN), js-yaml (CDN), existing Cortex dark theme CSS. All in `api/static/index.html`.

---

### Task 1: Add CDN Dependencies

**Files:**
- Modify: `api/static/index.html:1-10` (head section)

**Step 1: Add Drawflow, Dagre, and js-yaml CDN links**

Add these lines after the D3.js CDN link (line 9):

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/jerosoler/Drawflow@0.0.59/dist/drawflow.min.css">
<script src="https://cdn.jsdelivr.net/gh/jerosoler/Drawflow@0.0.59/dist/drawflow.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js"></script>
```

**Step 2: Verify CDN loads**

Run: Reload the dashboard in the preview, check console for load errors.
Expected: No 404s, `window.Drawflow` and `window.dagre` and `window.jsyaml` are defined.

**Step 3: Commit**

```bash
git add api/static/index.html
git commit -m "chore: add Drawflow, Dagre, js-yaml CDN dependencies"
```

---

### Task 2: Replace Composer CSS

**Files:**
- Modify: `api/static/index.html:1076-1137` (current `.composer-*` CSS block)

**Step 1: Replace the composer CSS block**

Replace the block from `/* ── Workflow Composer */` through `.composer-port.input:hover` with Drawflow-themed CSS:

```css
/* ── Drawflow Composer ─────────────────────────────────────────── */
#drawflow-canvas { width: 100%; height: 100%; min-height: 440px; }
#drawflow-canvas .drawflow { background: var(--bg-deep); background-image: radial-gradient(var(--border) 1px, transparent 1px); background-size: 20px 20px; }
#drawflow-canvas .drawflow .drawflow-node { background: var(--bg); border: 1.5px solid var(--border); border-radius: 6px; min-width: 160px; color: var(--text); font-family: var(--mono); font-size: 0.72rem; }
#drawflow-canvas .drawflow .drawflow-node.selected { border-color: var(--cyan); box-shadow: var(--glow-cyan); }
#drawflow-canvas .drawflow .drawflow-node:hover { border-color: var(--cyan-dim); }
#drawflow-canvas .drawflow .drawflow-node .input, #drawflow-canvas .drawflow .drawflow-node .output { background: var(--border); border: 2px solid var(--text-muted); }
#drawflow-canvas .drawflow .drawflow-node .input:hover, #drawflow-canvas .drawflow .drawflow-node .output:hover { background: var(--cyan); border-color: var(--cyan); }
#drawflow-canvas .drawflow .connection .main-path { stroke: var(--text-muted); stroke-width: 2; }
#drawflow-canvas .drawflow .connection .main-path.selected { stroke: var(--cyan); stroke-width: 3; }

.df-node-content { padding: 0; }
.df-node-header { padding: 6px 10px; background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 0.7rem; }
.df-node-role-bar { width: 3px; height: 100%; position: absolute; left: 0; top: 0; border-radius: 6px 0 0 6px; }
.df-node-body { padding: 6px 10px; font-size: 0.6rem; color: var(--text-dim); }
.df-node-role { text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.54rem; margin-bottom: 2px; }
.df-node-outputs { color: var(--cyan); opacity: 0.7; font-size: 0.56rem; }
.df-node-footer { padding: 4px 10px; border-top: 1px solid var(--border); font-size: 0.52rem; color: var(--text-muted); display: flex; justify-content: space-between; }

/* Palette */
.df-palette { display: flex; flex-direction: column; gap: 4px; padding: 6px; overflow-y: auto; }
.df-palette-item { padding: 8px 10px; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; cursor: grab; font-size: 0.64rem; font-family: var(--mono); display: flex; align-items: center; gap: 6px; transition: border-color 0.2s; }
.df-palette-item:hover { border-color: var(--cyan-dim); }
.df-palette-item:active { cursor: grabbing; }
.df-palette-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.df-palette-label { flex: 1; }
.df-palette-role { font-size: 0.5rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; }

/* Config panel */
.df-config-section { padding: 8px 0; border-bottom: 1px solid var(--border); }
.df-config-section-title { font-size: 0.56rem; color: var(--cyan); text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 6px; font-weight: 600; cursor: pointer; }
.df-config-section-title:hover { color: var(--text); }
.df-config-label { font-size: 0.54rem; color: var(--text-muted); display: block; margin-bottom: 2px; }
.df-config-hint { font-size: 0.5rem; color: var(--text-muted); margin-top: 2px; }
.df-tag { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; background: var(--cyan-ghost); border: 1px solid var(--cyan-dim); font-size: 0.58rem; color: var(--cyan); margin: 2px; border-radius: 2px; }
.df-tag-remove { cursor: pointer; opacity: 0.6; font-size: 0.7rem; }
.df-tag-remove:hover { opacity: 1; color: var(--red); }
.df-gate-row { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 4px; margin-bottom: 4px; font-size: 0.6rem; }
.df-gate-row select, .df-gate-row input { font-size: 0.6rem; padding: 3px 6px; }
```

**Step 2: Verify styling**

Run: Reload dashboard, switch to Workflows → Composer. Verify no visual regressions.

**Step 3: Commit**

```bash
git add api/static/index.html
git commit -m "style: add Drawflow-themed CSS for no-code composer"
```

---

### Task 3: Replace Composer HTML Structure

**Files:**
- Modify: `api/static/index.html:1678-1742` (current `#wf-composer` div)

**Step 1: Replace the composer HTML**

Replace the entire `<div id="wf-composer">` block with:

```html
<div id="wf-composer" style="display:none">
  <div style="display:grid;grid-template-columns:130px 1fr 320px;gap:10px;margin-bottom:12px">
    <!-- LEFT: Node Palette -->
    <div class="panel" style="overflow-y:auto;max-height:500px">
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div class="panel-label">Steps</div>
      <div class="df-palette" id="df-palette"></div>
    </div>
    <!-- CENTER: Drawflow Canvas -->
    <div class="panel" style="min-height:440px;position:relative;padding:0;overflow:hidden">
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div id="drawflow-canvas"></div>
    </div>
    <!-- RIGHT: Config Panel -->
    <div class="panel" style="display:flex;flex-direction:column;overflow-y:auto;max-height:500px">
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div class="panel-label" id="df-config-title">Config</div>
      <div id="df-config-panel" style="flex:1;overflow-y:auto;font-size:0.72rem;color:var(--text-dim);padding:0 2px">
        <div style="padding:30px 0;text-align:center;color:var(--text-muted);font-size:0.64rem">
          Drag a step from the palette onto the canvas to begin. Click a node to configure it.
        </div>
      </div>
    </div>
  </div>
  <!-- Bottom bar: metadata + actions -->
  <div class="panel" style="margin-bottom:12px">
    <span class="corner-tr"></span><span class="corner-bl"></span>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:10px">
      <div><div class="df-config-label">Workflow ID</div><input type="text" id="df-wf-id" class="chat-input" style="font-size:0.68rem;padding:5px 8px" placeholder="my-workflow" /></div>
      <div><div class="df-config-label">Name</div><input type="text" id="df-wf-name" class="chat-input" style="font-size:0.68rem;padding:5px 8px" placeholder="My Workflow" /></div>
      <div><div class="df-config-label">Default Role</div><select id="df-wf-role" class="model-select" style="font-size:0.68rem;padding:3px 6px"><option value="reasoning">reasoning</option><option value="coding">coding</option><option value="fast">fast</option><option value="general" selected>general</option><option value="uncensored">uncensored</option></select></div>
      <div><div class="df-config-label">Description</div><input type="text" id="df-wf-desc" class="chat-input" style="font-size:0.68rem;padding:5px 8px" placeholder="What does this workflow do?" /></div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="action-btn" onclick="dfExportYaml()" style="color:var(--cyan);border-color:var(--cyan-dim)">Export YAML</button>
      <button class="action-btn" onclick="dfSave()" style="color:var(--green);border-color:var(--green-dim)">Save</button>
      <button class="action-btn" onclick="dfImportYaml()">Import YAML</button>
      <button class="action-btn" onclick="dfAutoLayout()">Auto-Layout</button>
      <div style="flex:1"></div>
      <button class="action-btn" onclick="dfRunWorkflow()" style="color:var(--green);border-color:var(--green-dim)">Run ▶</button>
    </div>
  </div>
  <!-- YAML preview (hidden until export) -->
  <div class="panel" id="df-yaml-panel" style="display:none;margin-bottom:12px">
    <span class="corner-tr"></span><span class="corner-bl"></span>
    <div class="panel-label">Generated YAML</div>
    <pre id="df-yaml-output" style="font-size:0.6rem;color:var(--text-dim);max-height:300px;overflow:auto;white-space:pre-wrap"></pre>
    <button class="action-btn" onclick="navigator.clipboard.writeText(document.getElementById('df-yaml-output').textContent)" style="font-size:0.56rem;padding:3px 10px;margin-top:6px">Copy YAML</button>
  </div>
</div>
```

Also update the composer toolbar controls (`#wf-composer-controls`) to match.

**Step 2: Commit**

```bash
git add api/static/index.html
git commit -m "feat: replace composer HTML with Drawflow 3-column layout"
```

---

### Task 4: Implement Drawflow Initialization + Palette

**Files:**
- Modify: `api/static/index.html:3992-4388` (replace existing composer JS)

**Step 1: Replace the entire WORKFLOW COMPOSER JS block**

Replace from `/* WORKFLOW COMPOSER */` through the line before `/* AGENTS TAB */` with the new Drawflow-based implementation. This includes:

- `dfEditor` — the Drawflow instance
- `dfStepTemplates` — palette template definitions
- `setWfMode()` — mode toggle (updated to init Drawflow)
- `dfInitPalette()` — renders draggable palette items
- `dfInitEditor()` — creates Drawflow editor, registers node template
- Node event handlers: `nodeSelected`, `nodeRemoved`, `connectionCreated`
- `dfRenderConfigPanel(nodeId)` — renders the n8n-style right panel
- `dfUpdateNodeData(nodeId, field, value)` — updates node data + re-renders node HTML
- `dfExportYaml()` — serializes Drawflow state → YAML
- `dfImportYaml()` — opens paste modal, parses YAML, creates nodes + connections with Dagre layout
- `dfAutoLayout()` — repositions nodes using Dagre
- `dfSave()` — exports + POSTs to `/api/workflows/save`
- `dfRunWorkflow()` — exports, switches to runner, executes

Key implementation details:

**Drawflow node registration:**
```javascript
const editor = new Drawflow(document.getElementById('drawflow-canvas'));
editor.reroute = true;
editor.start();

// Register a single flexible node type
editor.registerNode('step', stepNodeHtml, {}, {});
```

**Node HTML template function:**
```javascript
function dfNodeHtml(data) {
  const roleColors = { reasoning:'#00C0E8', coding:'#00cc66', fast:'#8a98a0', uncensored:'#ff5252', general:'#6b7780' };
  const color = roleColors[data.role] || '#6b7780';
  const outputs = (data.outputs || ['result']).join(', ');
  const gates = (data.quality_gates || []).length;
  return `
    <div class="df-node-content">
      <div class="df-node-role-bar" style="background:${color}"></div>
      <div class="df-node-header">
        <span style="color:${color}">●</span>
        <span>${data.name || 'New Step'}</span>
      </div>
      <div class="df-node-body">
        <div class="df-node-role" style="color:${color}">${data.role || 'general'}</div>
        <div class="df-node-outputs">→ ${outputs}</div>
      </div>
      <div class="df-node-footer">
        <span>${data.output_format || 'raw'}</span>
        ${gates ? `<span>${gates} gates</span>` : ''}
      </div>
    </div>`;
}
```

**Palette drag-and-drop:**
```javascript
// Each palette item has draggable="true" and ondragstart stores template data
// Canvas has ondrop that creates a new Drawflow node at drop position
```

**Config panel rendering** — same 7 sections as the design doc, using `dfRenderConfigPanel(nodeId)`.

**YAML export** — reads `editor.export()`, iterates nodes, reads connections, builds YAML string.

**YAML import** — parses with `jsyaml.load()`, creates nodes, uses `dagre` for layout, creates connections.

**Step 2: Verify the composer works**

Run: Reload, switch to Composer mode, drag a step, connect two nodes, export YAML.
Expected: Valid YAML output with `steps`, `depends_on`, `inputs`.

**Step 3: Commit**

```bash
git add api/static/index.html
git commit -m "feat: implement Drawflow no-code composer with palette, canvas, config panel"
```

---

### Task 5: Implement YAML Import + Dagre Auto-Layout

**Files:**
- Modify: `api/static/index.html` (within the composer JS block)

**Step 1: Implement `dfImportYaml()`**

Shows a modal with a textarea for pasting YAML. On submit:
1. Parse with `jsyaml.load()`
2. Clear existing Drawflow nodes
3. For each step in the workflow, call `editor.addNode()` with position from Dagre layout
4. For each dependency (from `depends_on` + `inputs`), call `editor.addConnection()`
5. Populate workflow metadata fields (ID, name, description, role)

**Step 2: Implement `dfAutoLayout()`**

Uses Dagre to recompute positions for all existing nodes:
1. Create a dagre graph from current nodes + connections
2. Run `dagre.layout()`
3. Update each node's position via Drawflow API

**Step 3: Test round-trip**

Test: Export a workflow → copy YAML → clear canvas → import the copied YAML.
Expected: Same graph structure, auto-laid-out cleanly.

**Step 4: Commit**

```bash
git add api/static/index.html
git commit -m "feat: add YAML import with Dagre auto-layout for composer"
```

---

### Task 6: Update E2E Tests

**Files:**
- Modify: `tests/test_e2e_dashboard.py` (TestWorkflowComposer class)

**Step 1: Update composer E2E tests**

Replace the existing `TestWorkflowComposer` tests with tests for the new Drawflow-based composer:

```python
class TestWorkflowComposer:
    def test_composer_mode_shows_drawflow(self, page, server_check):
        """Switching to Composer mode shows the Drawflow canvas"""
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        expect(page.locator("#drawflow-canvas")).to_be_visible()
        expect(page.locator("#df-palette")).to_be_visible()

    def test_palette_has_templates(self, page, server_check):
        """Palette shows draggable step templates"""
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        items = page.locator(".df-palette-item")
        assert items.count() >= 6  # At least 6 template types

    def test_export_yaml_produces_valid_output(self, page, server_check):
        """Export YAML button generates workflow YAML"""
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        # Add nodes programmatically for test reliability
        page.evaluate("dfAddNodeFromTemplate('analyzer', 100, 100)")
        page.evaluate("dfAddNodeFromTemplate('code_gen', 350, 100)")
        page.wait_for_timeout(500)
        page.fill("#df-wf-id", "e2e-test")
        page.fill("#df-wf-name", "E2E Test")
        page.click("button:has-text('Export YAML')")
        page.wait_for_timeout(500)
        yaml_output = page.locator("#df-yaml-output")
        expect(yaml_output).to_be_visible()
        expect(yaml_output).to_contain_text("id: e2e-test")
        expect(yaml_output).to_contain_text("steps:")

    def test_save_endpoint(self, page, server_check):
        """POST /api/workflows/save persists workflow"""
        yaml_content = "id: e2e-save-test\\nname: E2E Save\\nversion: '1.0'\\ndefaults:\\n  role: general\\nsteps:\\n  - id: s1\\n    name: Step 1\\n    system_prompt: Do something\\n    outputs:\\n      - result"
        resp = page.request.post(f"{BASE_URL}/api/workflows/save", data={
            "workflow_id": "e2e-save-test", "yaml_content": yaml_content
        })
        assert resp.status == 200
```

**Step 2: Run E2E tests**

Run: `pytest tests/test_e2e_dashboard.py -v -k "TestWorkflowComposer"` (requires server running)
Expected: All composer tests pass.

**Step 3: Commit**

```bash
git add tests/test_e2e_dashboard.py
git commit -m "test: update E2E tests for Drawflow-based composer"
```

---

### Task 7: Final Integration + Push

**Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short -k "not test_api.py and not test_e2e"
```

Expected: 276+ unit tests pass.

**Step 2: Verify preview**

Reload dashboard, test:
- Runner mode: load a workflow, see DAG, inspect nodes
- Composer mode: drag templates from palette, connect nodes, configure in panel, export YAML
- Import an existing workflow YAML, verify auto-layout
- Switch between Runner and Composer without losing state

**Step 3: Push**

```bash
git push
```

**Step 4: Final commit message**

```bash
git add -A
git commit -m "feat: n8n-style no-code workflow composer with Drawflow.js

Complete visual workflow builder:
- Draggable step palette with 8 role-based templates
- Drawflow.js canvas with bezier connections, zoom/pan
- n8n-style right-side config panel with 7 sections
- YAML export/import with Dagre auto-layout
- Quality gate builder, template variable hints
- Round-trip: visual → YAML → visual
- E2E tests for all composer interactions"
```
