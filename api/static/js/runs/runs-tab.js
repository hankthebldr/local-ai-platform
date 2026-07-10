// runs/runs-tab.js — Runs tab: live plan, history, run DAG viz (phase-2 U5 carve).
// _editor (its own Drawflow instance) stays PRIVATE — closure-local, never exported.
const { Drawflow, dagre } = window;
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const RunsTab = (function () {
  let _rows = [];
  let _activeFilter = 'all';
  let _selectedId = null;
  let _editor = null;          // separate drawflow instance for this tab
  let _idMap = {};             // logical step id → drawflow node id
  let _pollHandle = null;
  let _currentRun = null;      // last fetched run (for cascade / context analysis)
  let _currentSteps = [];      // step list used for the rendered DAG
  let _drawerCopyTexts = [];   // bottom-drawer Copy payloads, keyed by data-idx
  let _sseSource = null;       // active EventSource for run stream (or null)
  const _expandedSteps = new Set();  // step_ids the user clicked to expand
  const _expandedOutputs = new Set();  // "stepId::key" of fully-expanded outputs

  function init() {
    // Defer the drawflow editor init until the first run is actually
    // selected — initializing now (while the tab content is still
    // hidden) gives drawflow a 0×0 container, which breaks layout
    // until the next window resize. The lazy path in _renderRunGraph
    // already calls _initEditor() before each render.
    //
    // load() runs immediately but uses requestAnimationFrame so the
    // browser has a chance to lay out the now-visible tab before the
    // fetch updates the rows container (avoids the "Loading…"
    // placeholder being immediately replaced by an empty grid that
    // hasn't had its scroll height resolved yet).
    requestAnimationFrame(() => load());
  }

  async function load(retry) {
    const box = document.getElementById('runs-tab-rows');
    if (!box) return;
    // Surface loading explicitly so the "Loading…" placeholder can't
    // linger if a previous render flushed it.
    box.innerHTML = '<div class="model-empty">Loading runs…</div>';
    try {
      // Net.call (not getJson): the 401 branch below needs the status code.
      // retries:0 so Net's backoff doesn't delay the 401 auth-bootstrap retry.
      const r = await Net.call('/api/workflows/runs?limit=40', { retries: 0 });
      if (r.status === 401) {
        // Auth hadn't initialized when the tab first opened. Retry
        // once after a beat — the global fetch wrapper will inject
        // the Bearer header now that Auth has bootstrapped.
        if (!retry) {
          await new Promise(res => setTimeout(res, 600));
          return load(true);
        }
        box.innerHTML = `<div class="model-empty" style="color:var(--red)">Not signed in — visit Admin to enter your license key.</div>`;
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = r.data;
      _rows = Array.isArray(data) ? data : (data.runs || []);
      const chip = document.getElementById('runs-tab-count');
      if (chip) chip.textContent = _rows.length ? `(${_rows.length})` : '';
      render();
    } catch (e) {
      box.innerHTML =
        `<div class="model-empty" style="color:var(--red)">Failed to load runs: ${esc(e.message)}.
          <br><br><button class="action-btn xs" data-action="runs.load">Retry</button></div>`;
    }
  }

  function setFilter(f) {
    _activeFilter = f;
    document.querySelectorAll('.runs-tab-filter').forEach(b => {
      b.classList.toggle('active', b.dataset.filter === f);
    });
    render();
  }

  function render() {
    const box = document.getElementById('runs-tab-rows');
    if (!box) return;
    const q = (document.getElementById('runs-tab-search') || {}).value || '';
    const ql = q.toLowerCase();
    const filtered = _rows.filter(r => {
      const s = (r.status || '').toLowerCase();
      if (_activeFilter === 'running'   && !['running', 'queued'].includes(s)) return false;
      if (_activeFilter === 'completed' && s !== 'completed') return false;
      if (_activeFilter === 'failed'    && !['failed', 'error'].includes(s)) return false;
      if (!ql) return true;
      const hay = [r.workflow_id, r.run_id, r.status].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(ql);
    });
    if (!filtered.length) {
      box.innerHTML = '<div class="model-empty">No runs match.</div>';
      return;
    }
    box.innerHTML = filtered.map(r => {
      const s = (r.status || 'unknown').toLowerCase();
      const ts = r.started_at || r.created_at || '';
      const sel = r.run_id === _selectedId ? ' selected' : '';
      return `<button type="button" class="btn-unstyled runs-tab-row${sel}" style="width:100%" data-run-id="${esc(r.run_id)}"
                   aria-pressed="${r.run_id === _selectedId}"
                   data-action="runs.select">
        <span class="runs-tab-row-title">${esc(r.workflow_id || '?')}</span>
        <span class="runs-tab-row-status ${esc(s)}">${esc(s)}</span>
        <span class="runs-tab-row-meta">${esc((r.run_id || '').slice(0, 12))} · ${esc(ts)}</span>
      </button>`;
    }).join('');
  }

  async function select(runId) {
    _selectedId = runId;
    render();
    // Deep-link: a selected run is shareable + reload-safe. Only when
    // the Runs tab owns the hash (select can fire from cross-tab jumps).
    try {
      if ((location.hash || '').indexOf('#/runs') === 0) {
        history.replaceState(null, '', '#/runs/' + encodeURIComponent(runId));
      }
    } catch (_) {}
    // Detail head + buttons.
    const meta = document.getElementById('runs-tab-detail-meta');
    if (meta) meta.textContent = `Loading ${runId.slice(0, 12)}…`;
    document.getElementById('runs-tab-graph-empty').setAttribute('hidden', '');
    // Stop any prior poller and SSE stream.
    if (_pollHandle) { clearInterval(_pollHandle); _pollHandle = null; }
    _unsubscribeSSE();
    // Hide the live plan panel until a plan.updated SSE frame arrives.
    const _livePlanPanel = document.getElementById('runs-tab-live-plan');
    if (_livePlanPanel) _livePlanPanel.hidden = true;
    // Fetch the run + the workflow definition so we can lay out the DAG.
    try {
      const run = await Net.getJson(`/api/workflows/runs/${encodeURIComponent(runId)}`);
      const wfId = run.workflow_id;
      let defn = null;
      if (wfId) {
        try {
          // silent + retries:0 — 404 for private workflows is expected if
          // the overlay doesn't carry the YAML; must not toast or retry.
          const dr = await Net.call(`/api/workflows/${encodeURIComponent(wfId)}`, { silent: true, retries: 0 });
          if (dr.ok) defn = dr.data;
        } catch (_) { /* fall through */ }
      }
      // Pass the run into the graph builder so it can reconstruct
      // the scaffold from step_results when the workflow definition
      // is missing or stale. Cache the run so other helpers
      // (cascade detection, context trace) can read it without a
      // round-trip.
      _currentRun = run;
      _renderRunGraph(defn, run);
      _applyStatus(run);
      _renderSteps(run);
      _renderContextTrace(run);
      _toggleActionButtons(run);
      // Live stream (SSE) + poll while running. SSE is additive — polling
      // keeps going as a fallback if the stream errors or isn't supported.
      if (['running', 'queued'].includes((run.status || '').toLowerCase())) {
        _subscribeSSE(runId);
        _pollHandle = setInterval(async () => {
          try {
            // silent + retries:0 — poll loop: no toast spam, and Net's
            // backoff must not stack with the 1.5s interval timer.
            const r2 = await Net.call(`/api/workflows/runs/${encodeURIComponent(runId)}`, { silent: true, retries: 0 });
            if (!r2.ok) return;
            const run2 = r2.data;
            _currentRun = run2;
            _applyStatus(run2);
            _renderSteps(run2);
            _renderContextTrace(run2);
            _toggleActionButtons(run2);
            if (['completed', 'failed', 'canceled', 'error'].includes((run2.status || '').toLowerCase())) {
              clearInterval(_pollHandle); _pollHandle = null;
              // Refresh the list so the row shows the new status.
              load();
            }
          } catch (_) { /* keep trying */ }
        }, 1500);
      }
    } catch (e) {
      const meta2 = document.getElementById('runs-tab-detail-meta');
      if (meta2) meta2.textContent = `Error: ${e.message}`;
      // Re-show the empty hint so the right pane isn't a void.
      const empty = document.getElementById('runs-tab-graph-empty');
      if (empty) empty.removeAttribute('hidden');
      // Wipe step strip + context to avoid stale data from a prior run.
      const stepsBody = document.getElementById('runs-tab-steps-body');
      if (stepsBody) stepsBody.innerHTML = `<div class="model-empty" style="color:var(--red)">Couldn't load run: ${esc(e.message)}</div>`;
      const ctxBody = document.getElementById('runs-tab-context-body');
      if (ctxBody) ctxBody.innerHTML = '<div class="model-empty">—</div>';
    }
  }

  function _initEditor() {
    const container = document.getElementById('runs-tab-canvas');
    if (!container || typeof Drawflow === 'undefined') return;
    // Defensive: if the container was previously initialized at 0×0
    // (because the tab was hidden), recreating wipes any stale state.
    if (_editor) {
      try { _editor.clear(); } catch (_) {}
    }
    // Drawflow appends its own children to the container; wipe before
    // re-init to avoid duplicated DOM if we re-init.
    container.innerHTML = '';
    _editor = new Drawflow(container);
    _editor.reroute = true;
    _editor.reroute_fix_curvature = true;
    // 'fixed' silently no-ops addConnection in some drawflow builds —
    // keep 'edit' so edges wire, then disable pan/drag via the
    // .readonly-canvas CSS class which routes pointer-events around
    // drawflow's mousedown→pan handler on the wrapper.
    _editor.editor_mode = 'edit';
    _editor.start();
    container.classList.add('readonly-canvas');

    // Click-to-drill: when the operator clicks a node card, find the
    // matching step row in the strip below and scroll it into view
    // + open it. Bound on the container so it survives drawflow's
    // node re-renders during graph updates.
    container.addEventListener('click', (e) => {
      const nodeEl = e.target.closest('.drawflow-node');
      if (!nodeEl) return;
      const m = nodeEl.id.match(/^node-(\d+)$/);
      if (!m) return;
      const dfId = m[1];
      // Resolve dfId → step.id via the _idMap we built at render time.
      const stepId = Object.keys(_idMap).find(k => String(_idMap[k]) === dfId);
      if (!stepId) return;
      // Auto-expand the step's row in the result strip + scroll it
      // into view so the operator sees its error / output immediately.
      _expandedSteps.add(stepId);
      if (_currentRun) _renderSteps(_currentRun);
      // Brief flash on the matching step row so the operator sees
      // where in the strip their click landed.
      setTimeout(() => {
        const row = document.querySelector(
          `#runs-tab-steps-body .ws-run-step[data-step-id="${CSS.escape(stepId)}"]`
        );
        if (row) {
          row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          row.classList.add('flash-highlight');
          setTimeout(() => row.classList.remove('flash-highlight'), 1200);
        }
      }, 30);
    });
  }

  function _renderRunGraph(defn, run) {
    if (!_editor) _initEditor();
    if (!_editor) return;
    // Wipe any previous render.
    try { _editor.clear(); } catch (_) {}
    _idMap = {};

    // Build the step list. If we have a workflow definition use it;
    // otherwise reconstruct the scaffold from the run's step_results
    // (preserves the agent process layout even when the workflow YAML
    // has been deleted, renamed, or changed since the run executed).
    let steps = (defn && Array.isArray(defn.steps) && defn.steps.length)
      ? defn.steps.map(s => ({ ...s }))
      : [];

    // Merge: ensure every step_id from results exists as a step. Adds
    // any "phantom" steps the run actually executed but that aren't
    // in the current definition (e.g. dynamically inserted steps).
    const resultsById = new Map();
    (run && run.step_results || []).forEach(r => {
      if (r && r.step_id) resultsById.set(r.step_id, r);
    });
    const knownIds = new Set(steps.map(s => s.id));
    Array.from(resultsById.keys()).forEach(id => {
      if (!knownIds.has(id)) {
        const r = resultsById.get(id);
        steps.push({
          id, name: id,
          role: r.role || 'general',
          // Marker so we can label "reconstructed" nodes in the UI.
          _reconstructed: true,
        });
      }
    });

    // Determine the depends_on linkage. If the definition supplies it,
    // use it. Otherwise infer a linear chain from the order step_results
    // were appended (which is the engine's execution order).
    const hasDefDeps = (defn && Array.isArray(defn.steps) &&
      defn.steps.some(s => Array.isArray(s.depends_on) ? s.depends_on.length : !!s.depends_on));
    if (!hasDefDeps && run && Array.isArray(run.step_results)) {
      const ordered = run.step_results.map(r => r.step_id).filter(Boolean);
      const byId = new Map(steps.map(s => [s.id, s]));
      for (let i = 1; i < ordered.length; i++) {
        const cur = byId.get(ordered[i]);
        if (cur && !cur.depends_on) cur.depends_on = [ordered[i - 1]];
      }
    }

    // Spawn a node per step using the composer's same dfNodeHtml so the
    // visual is identical. We use logical positions; auto-layout below
    // re-flows via dagre.
    steps.forEach((step, i) => {
      const data = {
        id: step.id, name: step.name || step.id,
        role: step.role || 'general',
        system_prompt: step.system_prompt || '',
        outputs: Array.isArray(step.outputs) ? step.outputs : ['result'],
        output_format: (step.output_parser && step.output_parser.format) || 'raw',
        quality_gates: [], inputs: [],
        is_decision: !!step.is_decision,
        persona: step.persona ||
          (window.AgentIcons ? AgentIcons.resolve({ role: step.role, name: step.name }) : 'general'),
        skills: step.skills || [], tools: step.tools || [],
        _reconstructed: !!step._reconstructed,
      };
      const x = 80 + (i % 4) * 220;
      const y = 60 + Math.floor(i / 4) * 140;
      const numOut = data.outputs.length > 1 && data.is_decision ? data.outputs.length : 1;
      const dfId = _editor.addNode(data.id, 1, numOut, x, y, data.id, {}, dfNodeHtml(data));
      _idMap[data.id] = dfId;
      // Tag the wrapper for reconstructed-step markers in CSS.
      if (data._reconstructed) {
        const el = document.querySelector(`#runs-tab-canvas #node-${dfId}`);
        if (el) el.classList.add('is-reconstructed');
      }
    });
    // Connect via depends_on (definition or inferred linear chain).
    steps.forEach((step) => {
      const tgt = _idMap[step.id];
      if (!tgt) return;
      const deps = Array.isArray(step.depends_on) ? step.depends_on
                 : (step.depends_on ? [step.depends_on] : []);
      deps.forEach(dep => {
        const src = _idMap[dep];
        if (!src) return;
        try { _editor.addConnection(src, tgt, 'output_1', 'input_1'); } catch (_) {}
      });
    });

    // START / END anchor nodes — make the workflow's input (seed) and final
    // deliverable (terminal-step outputs) explicit, bracketing the DAG.
    try {
      const depOf = s => Array.isArray(s.depends_on) ? s.depends_on : (s.depends_on ? [s.depends_on] : []);
      const seedKeys = [...new Set(steps.flatMap(s =>
        (s.inputs || []).filter(i => typeof i === 'string' && i.startsWith('seed.')).map(i => i.slice(5))))];
      const depended = new Set(steps.flatMap(depOf));
      const rootSteps = steps.filter(s => depOf(s).length === 0);
      const terminalSteps = steps.filter(s => !depended.has(s.id));
      const deliverable = [...new Set(terminalSteps.flatMap(s => Array.isArray(s.outputs) ? s.outputs : []))];
      const keyChips = arr => (arr.length ? arr : ['—']).map(k => `<span>${esc(k)}</span>`).join('');

      const startHtml = `<div class="wf-anchor wf-anchor-start"><div class="wf-anchor-label">▶ START</div><div class="wf-anchor-sub">seed input</div><div class="wf-anchor-keys">${keyChips(seedKeys)}</div></div>`;
      const startId = _editor.addNode('__start__', 0, 1, 0, 0, '__start__', {}, startHtml);
      rootSteps.forEach(s => { const t = _idMap[s.id]; if (t) { try { _editor.addConnection(startId, t, 'output_1', 'input_1'); } catch (_) {} } });

      const endHtml = `<div class="wf-anchor wf-anchor-end"><div class="wf-anchor-label">■ END</div><div class="wf-anchor-sub">deliverable</div><div class="wf-anchor-keys">${keyChips(deliverable.length ? deliverable : ['output'])}</div></div>`;
      const endId = _editor.addNode('__end__', 1, 0, 0, 0, '__end__', {}, endHtml);
      terminalSteps.forEach(s => { const src = _idMap[s.id]; if (src) { try { _editor.addConnection(src, endId, 'output_1', 'input_1'); } catch (_) {} } });
    } catch (_) { /* anchors are best-effort decoration */ }
    // Stash the resolved step list for cascade detection.
    _currentSteps = steps;
    // Auto-layout. We reuse the composer's dagre helper but target our
    // separate editor — swap dfEditor pointer temporarily.
    try { _runTabAutoLayout(); } catch (e) { console.warn('runs auto-layout:', e); }
  }

  function _runTabAutoLayout() {
    if (typeof dagre === 'undefined' || !_editor) return;
    const exported = _editor.export();
    const nodes = exported.drawflow.Home.data;
    const ids = Object.keys(nodes);
    if (!ids.length) return;
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 90, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    const NODE_W = 200, NODE_H = 90;
    ids.forEach(id => g.setNode(id, { width: NODE_W, height: NODE_H }));
    ids.forEach(id => {
      Object.keys(nodes[id].outputs || {}).forEach(k => {
        (nodes[id].outputs[k].connections || []).forEach(c => g.setEdge(id, String(c.node)));
      });
    });
    dagre.layout(g);
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    ids.forEach(id => {
      const p = g.node(id); if (!p) return;
      minX = Math.min(minX, p.x - NODE_W/2); minY = Math.min(minY, p.y - NODE_H/2);
      maxX = Math.max(maxX, p.x + NODE_W/2); maxY = Math.max(maxY, p.y + NODE_H/2);
    });
    const canvas = document.getElementById('runs-tab-canvas');
    const rect = canvas ? canvas.getBoundingClientRect() : { width: 1000, height: 600 };
    const bboxW = (maxX - minX) || NODE_W;
    const bboxH = (maxY - minY) || NODE_H;
    const offX = Math.max(40, (rect.width  - bboxW) / 2 - minX);
    const offY = Math.max(40, (rect.height - bboxH) / 2 - minY);
    ids.forEach(id => {
      const p = g.node(id); if (!p) return;
      const left = p.x - NODE_W/2 + offX;
      const top  = p.y - NODE_H/2 + offY;
      try {
        const d = _editor.drawflow.drawflow.Home.data[id];
        if (d) { d.pos_x = left; d.pos_y = top; }
      } catch (_) {}
      const el = document.querySelector(`#runs-tab-canvas #node-${id}`);
      if (el) { el.style.left = left + 'px'; el.style.top = top + 'px'; }
    });
    ids.forEach(id => { try { _editor.updateConnectionNodes(`node-${id}`); } catch (_) {} });

    // Fit-to-screen: zoom the whole precanvas so EVERY node is visible (the
    // run-detail graph should always fit). Measure the ACTUAL rendered node
    // bounds (offset*) — dagre's NODE_H estimate is smaller than the real node
    // cards. Deferred a frame so node cards have reached their final height
    // (their content/fonts grow them taller after addNode).
    requestAnimationFrame(() => { try {
      const cvEl = document.getElementById('runs-tab-canvas');
      const pre = _editor && _editor.precanvas;
      if (cvEl && pre) {
        let bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
        ids.forEach(id => {
          const el = document.querySelector(`#runs-tab-canvas #node-${id}`);
          if (!el) return;
          const x = parseFloat(el.style.left) || 0, y = parseFloat(el.style.top) || 0;
          bx0 = Math.min(bx0, x); by0 = Math.min(by0, y);
          bx1 = Math.max(bx1, x + el.offsetWidth); by1 = Math.max(by1, y + el.offsetHeight);
        });
        const gw = bx1 - bx0, gh = by1 - by0;
        const cw = cvEl.clientWidth, ch = cvEl.clientHeight, pad = 80;
        if (gw > 0 && gh > 0 && cw > 0 && ch > 0) {
          // 0.94 safety factor — connection curves bow ~15-20px beyond the
          // node bounding box, so leave headroom or a sliver clips.
          const z = Math.min(1, ((cw - pad) / gw) * 0.94, ((ch - pad) / gh) * 0.94);
          const cx = (cw - gw * z) / 2 - bx0 * z;
          const cy = (ch - gh * z) / 2 - by0 * z;
          _editor.zoom = z; _editor.zoom_last_value = z;
          _editor.canvas_x = cx; _editor.canvas_y = cy;
          pre.style.transform = 'translate(' + cx + 'px, ' + cy + 'px) scale(' + z + ')';
        }
      }
    } catch (_) { /* fit is best-effort */ } });
  }

  // A run is "zombie" if its status says running/queued but it
  // shipped no progress in over ZOMBIE_MS. Container restarts
  // mid-run leave the persisted status frozen, so we detect this in
  // the UI and surface a banner + an option to force-fail.
  const ZOMBIE_MS = 10 * 60 * 1000;  // 10 minutes without progress
  function _isZombieRun(run) {
    const s = (run.status || '').toLowerCase();
    if (!['running', 'queued'].includes(s)) return false;
    const started = Date.parse(run.started_at || '') || 0;
    if (!started) return false;
    const ageMs = Date.now() - started;
    if (ageMs < ZOMBIE_MS) return false;
    // If at least one step finished recently the run is still alive.
    const results = run.step_results || [];
    if (!results.length) return true;
    // Check the last step's completion timestamp if any.
    const lastDone = results
      .filter(r => r && (r.completed_at || r.started_at))
      .map(r => Date.parse(r.completed_at || r.started_at || '') || 0);
    const newest = lastDone.length ? Math.max(...lastDone) : started;
    return (Date.now() - newest) > ZOMBIE_MS;
  }

  function _applyStatus(run) {
    const results = run.step_results || [];
    const statusMap = new Map();
    results.forEach(r => { if (r && r.step_id) statusMap.set(r.step_id, r.status); });
    const planned = Object.keys(_idMap);
    let completed = 0, current = '';
    const statusLower = (run.status || '').toLowerCase();
    const terminal = ['completed', 'failed', 'error', 'canceled'].includes(statusLower);
    const zombie = _isZombieRun(run);
    planned.forEach(stepId => {
      const dfId = _idMap[stepId];
      const el = document.querySelector(`#runs-tab-canvas #node-${dfId}`);
      if (!el) return;
      el.classList.remove('is-queued','is-running','is-completed','is-failed','is-skipped');
      const st = statusMap.get(stepId);
      if (st === 'completed') { el.classList.add('is-completed'); completed += 1; }
      else if (st === 'running') { el.classList.add('is-running'); current = stepId; }
      else if (st === 'failed' || st === 'error') { el.classList.add('is-failed'); }
      else if (st === 'skipped') { el.classList.add('is-skipped'); }
      else if (!terminal) { el.classList.add('is-queued'); }
    });

    // Stop the live poller for zombie runs — there's nothing to
    // observe and re-fetching the same orphaned payload every 1.5s
    // is just noise.
    if (zombie && _pollHandle) {
      clearInterval(_pollHandle);
      _pollHandle = null;
    }

    // Update the chip. For a healthy running run with 0 steps yet,
    // show an indeterminate bar (stripe animation) so the operator
    // sees motion. For zombies, show a static "stalled" badge.
    const chip = document.getElementById('runs-tab-progress-chip');
    const cur = document.getElementById('runs-tab-current');
    const cnt = document.getElementById('runs-tab-chip-count');
    const bar = document.getElementById('runs-tab-bar');
    const spinner = document.getElementById('runs-tab-spinner');
    if (chip) chip.hidden = false;
    if (chip) chip.classList.toggle('is-zombie', zombie);
    if (cur) {
      if (zombie) cur.textContent = 'stalled — engine likely restarted mid-run';
      else cur.textContent = current || (statusLower === 'queued' ? 'queued' : (run.workflow_id || '—'));
    }
    if (cnt) cnt.textContent = `${completed}/${planned.length || 0}`;
    if (bar) {
      // Indeterminate animation when there's a count of zero in a non-
      // terminal state; concrete % otherwise.
      if (!terminal && !zombie && planned.length && completed === 0) {
        bar.classList.add('is-indeterminate');
        bar.style.width = '100%';
      } else {
        bar.classList.remove('is-indeterminate');
        bar.style.width = `${planned.length ? (completed / planned.length) * 100 : 0}%`;
      }
    }
    if (spinner) {
      spinner.classList.toggle('done', statusLower === 'completed');
      spinner.classList.toggle('failed', ['failed', 'error', 'canceled'].includes(statusLower) || zombie);
    }
    // Detail meta line + data-status attribute (read by Playwright selectors
    // and the SSE run.status handler for test assertions).
    const meta = document.getElementById('runs-tab-detail-meta');
    if (meta) {
      const tag = zombie ? `${run.status || '?'} (stalled)` : (run.status || '?');
      meta.textContent = `${run.workflow_id || '?'} · ${tag} · ${completed}/${planned.length} steps`;
      meta.dataset.status = statusLower;
    }
    // Zombie banner above the steps strip — gives the operator a
    // clear surface to mark the run as failed.
    _renderZombieBanner(run, zombie);
  }

  function _renderZombieBanner(run, zombie) {
    const stepsBody = document.getElementById('runs-tab-steps-body');
    if (!stepsBody) return;
    const existing = document.getElementById('runs-tab-zombie-banner');
    if (existing) existing.remove();
    if (!zombie) return;
    const startedAgo = (() => {
      const t = Date.parse(run.started_at || '') || 0;
      if (!t) return 'unknown time';
      const mins = Math.round((Date.now() - t) / 60000);
      return mins > 60 ? `${Math.round(mins / 60)}h ${mins % 60}m ago` : `${mins}m ago`;
    })();
    const banner = document.createElement('div');
    banner.id = 'runs-tab-zombie-banner';
    banner.className = 'runs-zombie-banner';
    banner.innerHTML = `<span class="zb-icon">!</span>
      <span class="zb-msg">
        This run started <strong>${esc(startedAgo)}</strong> and has shipped no
        progress for over 10 minutes. The engine likely restarted mid-run,
        leaving the run status frozen as <code>${esc(run.status || '')}</code>.
      </span>
      <button class="action-btn xs" data-action="runs.mark-failed">Mark Failed</button>`;
    stepsBody.prepend(banner);
  }

  async function markFailed() {
    if (!_selectedId) return;
    const ok = await Confirm.ask({ title: 'Mark run failed', body: 'Mark this stalled run as failed? This persists status="failed" so the UI stops polling.', okLabel: 'Mark Failed', danger: true });
    if (!ok) return;
    try {
      // The cancel endpoint accepts running/queued and marks them
      // canceled — which is the closest existing signal we have for
      // "this run is dead, stop polling." If the backend grows a
      // dedicated mark-failed verb later, swap the URL.
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(_selectedId)}/cancel`, {}, { retries: 0 });
      if (window.Toast) Toast.info('Run marked', 'Engine cancel sent; refreshing.');
      await load();
      select(_selectedId);
    } catch (e) {
      if (window.Toast) Toast.danger('Could not mark failed', e.message);
    }
  }

  // ── Sandbox / code-exec helpers (Task 18) ────────────────────────

  // Returns an HTML snippet summarising the code-exec result for a step.
  // Rendered inside the expandedBody section when code_exit_code is non-null.
  function _renderSandboxCodePanel(s) {
    if (s.code_exit_code == null) return '';
    const exitOk = s.code_exit_code === 0;
    const exitCls = exitOk ? 'ok' : 'fail';
    const tierChip = s.tier_used
      ? `<span class="scp-chip">${esc(s.tier_used)}</span>`
      : '';
    const exitChip = `<span class="scp-chip ${exitCls}">exit ${s.code_exit_code}</span>`;
    const rssChip = s.peak_rss_mb != null
      ? `<span class="scp-chip dim">${s.peak_rss_mb.toFixed(0)} MB</span>`
      : '';
    const files = Array.isArray(s.files_produced) ? s.files_produced : [];
    const filesChip = `<span class="scp-chip dim">${files.length} file${files.length === 1 ? '' : 's'}</span>`;
    const scopeChip = s.promoted
      ? `<span class="scp-chip ok">promoted</span>`
      : `<span class="scp-chip dim">in-scratch</span>`;
    const approvalChip = s.approval_status
      ? `<span class="scp-chip ${s.approval_status === 'approved' ? 'ok' : (s.approval_status === 'rejected' ? 'fail' : 'dim')}">${esc(s.approval_status)}</span>`
      : '';
    return `<div class="sandbox-code-panel">
      <span class="scp-label">code</span>
      ${tierChip}${exitChip}${rssChip}${filesChip}${scopeChip}${approvalChip}
    </div>`;
  }

  // Renders the approval-gate bar and prepends it to stepsBody.
  // Called from _renderSteps whenever run.status === 'awaiting_approval'
  // and run.pending_gate is present.
  function _renderApprovalGate(run, body) {
    const existing = document.getElementById('runs-tab-approval-gate');
    if (existing) existing.remove();
    if ((run.status || '').toLowerCase() !== 'awaiting_approval') return;
    const gate = run.pending_gate;
    if (!gate) return;
    const files = Array.isArray(gate.files) ? gate.files : [];
    const metaParts = [];
    if (gate.tier)    metaParts.push(`tier ${esc(gate.tier)}`);
    if (gate.network) metaParts.push(`net ${esc(gate.network)}`);
    metaParts.push(`${files.length} file${files.length === 1 ? '' : 's'} out`);
    const questionLine = gate.question
      ? `<div class="agb-question">${esc(gate.question)}</div>`
      : '';
    const el = document.createElement('div');
    el.id = 'runs-tab-approval-gate';
    el.className = 'approval-gate-bar';
    el.innerHTML = `
      <div class="agb-head">
        <span class="agb-icon">?</span>
        <span class="agb-title">AWAITING APPROVAL</span>
        <span class="agb-meta">${metaParts.join(' · ')}</span>
      </div>
      ${questionLine}
      <pre class="agb-code">${esc(gate.proposed_code || '')}</pre>
      <div class="agb-actions">
        <button class="action-btn xs"
                style="color:var(--green);border-color:var(--green)"
                data-action="runs.gate" data-run-id="${esc(run.run_id)}" data-gate-id="${esc(gate.gate_id)}" data-decision="approve">Approve</button>
        <button class="action-btn xs"
                style="color:var(--red);border-color:var(--red)"
                data-action="runs.gate" data-run-id="${esc(run.run_id)}" data-gate-id="${esc(gate.gate_id)}" data-decision="reject">Reject</button>
      </div>`;
    body.prepend(el);
  }

  // POSTs approve/reject to the backend then re-selects the run to refresh.
  async function resolveGate(runId, gateId, action) {
    try {
      // retries:0 — HITL gate decisions must fire exactly once.
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(gateId)}`, { action }, { retries: 0 });
      if (window.Toast) Toast.info(action === 'approve' ? 'Gate approved' : 'Gate rejected',
        `Run ${runId.slice(0, 12)}… will ${action === 'approve' ? 'continue' : 'be halted'}.`);
      select(runId);
    } catch (e) {
      if (window.Toast) Toast.danger('Gate action failed', e.message);
      else console.error('resolveGate failed:', e);
    }
  }

  function _renderSteps(run) {
    const body = document.getElementById('runs-tab-steps-body');
    if (!body) return;
    const results = run.step_results || [];
    // Compute cascade markers. A "root failure" is a step whose
    // status is failed/error. A "starved" step is one that depended
    // on a root failure and either didn't run (no result) or whose
    // workspace input was the failed step's output.
    const cascade = _computeCascade(run);

    // Top-level header — root error line first if any.
    const errorBanner = (run.status || '').toLowerCase() === 'failed' && run.error
      ? `<div class="run-error-banner">
           <span class="run-error-banner-icon">!</span>
           <span class="run-error-banner-text">${esc(run.error)}</span>
         </div>`
      : '';

    if (!results.length) {
      body.innerHTML = errorBanner + '<div class="model-empty">No step results yet.</div>';
      return;
    }

    const rows = results.map(s => {
      const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
      const status = (s.status || '').toLowerCase();
      const cls = status === 'completed' ? 'ok' : (['failed', 'error'].includes(status) ? 'fail' : 'pending');
      const isExpanded = _expandedSteps.has(s.step_id);
      const isRoot = cascade.roots.has(s.step_id);
      const isStarved = cascade.starved.has(s.step_id);
      const retries = s.retries || 0;
      const tokens = (s.token_count || {}).total_tokens || 0;

      // One-line preview of the error, full text revealed in the
      // expanded section.
      const errOneLine = s.error ? esc(String(s.error).split('\n')[0].slice(0, 90)) : '';
      const errFull = s.error ? esc(s.error) : '';

      const badges = [];
      if (isRoot)     badges.push(`<span class="run-step-badge fail">root</span>`);
      if (isStarved)  badges.push(`<span class="run-step-badge starved" title="Downstream step couldn't get its expected context from an upstream failure">starved</span>`);
      if (retries)    badges.push(`<span class="run-step-badge dim">${retries}× retry</span>`);

      const expandedBody = isExpanded ? `
        <div class="run-step-expanded">
          ${s.error ? `<div class="run-step-row-kv error">
            <span class="run-step-row-k">error</span>
            <pre class="run-step-error-text">${errFull}</pre>
          </div>` : ''}
          ${tokens ? `<div class="run-step-row-kv">
            <span class="run-step-row-k">tokens</span>
            <span>${tokens.toLocaleString()}</span>
          </div>` : ''}
          ${s.model_used ? `<div class="run-step-row-kv">
            <span class="run-step-row-k">model</span>
            <span>${esc(s.model_used)}</span>
          </div>` : ''}
          ${s.started_at ? `<div class="run-step-row-kv">
            <span class="run-step-row-k">started</span>
            <span>${esc(s.started_at)}</span>
          </div>` : ''}
          ${_renderStepPrompt(s)}
          ${_renderStepOutputs(run, s.step_id)}
          ${_renderSandboxCodePanel(s)}
        </div>` : '';

      return `<div class="ws-run-step ws-run-step-${cls} ${isRoot ? 'is-root-fail' : ''} ${isStarved ? 'is-starved' : ''}"
                   data-step-id="${esc(s.step_id)}">
        <div class="ws-run-step-head" role="button" tabindex="0"
             data-action="runs.step-detail"
             title="Open full step detail">
          <button type="button" class="btn-unstyled run-step-caret" title="Quick inline peek"
                aria-label="Toggle inline details for step ${esc(s.step_id)}" aria-expanded="${isExpanded}"
                data-action="runs.step-expand">${isExpanded ? '▾' : '▸'}</button>
          <span class="ws-run-step-id">${esc(s.step_id)}</span>
          <span class="run-step-kind kind-${esc(s.kind || 'llm')}" title="step kind">${esc(s.kind || 'llm')}</span>
          <span class="ws-run-step-model">${esc(s.model_used || '—')}</span>
          ${badges.join('')}
          <span style="flex:1"></span>
          ${errOneLine ? `<span class="ws-run-step-err-preview">${errOneLine}</span>` : ''}
          <span class="ws-run-step-dur">${dur}</span>
          <span class="ws-run-step-status">${esc(s.status)}</span>
        </div>
        ${expandedBody}
      </div>`;
    }).join('');

    // Cascade summary if there's a root failure.
    let cascadeSummary = '';
    if (cascade.roots.size) {
      const rootList = Array.from(cascade.roots).slice(0, 3).join(', ');
      const starvedList = Array.from(cascade.starved);
      cascadeSummary = `<div class="run-cascade-summary">
        <span class="run-cascade-label">CASCADE</span>
        <span>Root failure${cascade.roots.size > 1 ? 's' : ''}: <code>${esc(rootList)}</code>.</span>
        ${starvedList.length
          ? `<span>Starved downstream: <code>${esc(starvedList.slice(0, 5).join(', '))}</code>${starvedList.length > 5 ? ` +${starvedList.length - 5}` : ''}.</span>`
          : '<span>No downstream steps were starved (run halted at root).</span>'}
      </div>`;
    }

    // START / END entries bracketing the step list — the workflow's explicit
    // entry point (seed) and output (deliverable). Clickable to inspect the
    // ACTUAL values (e.g. the code that was reviewed, the review produced).
    const seed = (run.context && run.context.seed) || {};
    const seedEntries = Object.entries(seed);
    const ws = (run.context && run.context.workspace) || {};
    const terminal = results[results.length - 1];
    const delivEntries = terminal ? Object.entries(ws[terminal.step_id] || {}) : [];
    const previewOf = entries => {
      if (!entries.length) return 'none';
      const v = entries[0][1];
      const s = typeof v === 'string' ? v : JSON.stringify(v);
      return s.replace(/\s+/g, ' ').slice(0, 44) + (s.length > 44 ? '…' : '');
    };
    const anchorRow = (cls, glyph, label, kind, entries) => `
      <button type="button" class="btn-unstyled ws-run-step ws-run-anchor-row ${cls}" style="width:100%" data-action="runs.anchor-detail" data-kind="${kind}" title="Open the full ${kind} (actual values)">
        <span class="run-step-caret">${glyph}</span>
        <span class="ws-run-step-id">${label}</span>
        <span class="ws-anchor-count">${entries.length} field${entries.length === 1 ? '' : 's'}</span>
        <span style="flex:1"></span>
        <span class="ws-anchor-keys-inline">${entries.length ? esc(entries.map(e => e[0]).join(', ')) + ' · ' + esc(previewOf(entries)) : '—'}</span>
      </button>`;
    const startRow = anchorRow('ws-anchor-start-row', '▶', 'START · seed', 'seed', seedEntries);
    const endRow = anchorRow('ws-anchor-end-row', '■', 'END · deliverable', 'deliverable', delivEntries);

    body.innerHTML = errorBanner + cascadeSummary + startRow + rows + endRow;
    // Approval gate bar — rendered above step rows when a human-in-the-loop
    // gate is waiting. Uses prepend so it appears above the error banner too.
    _renderApprovalGate(run, body);
  }

  // Inspect run.context.workspace for the step's outputs. Returns
  // HTML showing what fields the step wrote (so the operator can
  // trace context handoff). Empty when the step has nothing in
  // workspace (e.g. it failed before producing output).
  function _renderStepPrompt(s) {
    // What actually went IN to the model — the rendered system + user prompt
    // captured on the StepResult at execution time. Each is click-to-expand to
    // its full text (reusing the output-viewer styling). LLM steps populate
    // these; non-LLM steps and pre-capture runs leave them null.
    const items = [];
    if (s.rendered_system_prompt) items.push(['system prompt', s.rendered_system_prompt]);
    if (s.rendered_prompt) items.push(['prompt', s.rendered_prompt]);
    if (!items.length) {
      return `<div class="run-step-row-kv">
        <span class="run-step-row-k">input</span>
        <span style="color:var(--text-muted)">prompt not captured (re-run this workflow to record it)</span>
      </div>`;
    }
    const rows = items.map(([label, text]) => {
      const key = '⟦' + label + '⟧';
      const open = _expandedOutputs.has(s.step_id + '::' + key);
      const preview = text.replace(/\s+/g, ' ').slice(0, 60) + (text.length > 60 ? '…' : '');
      return `<div class="run-step-output${open ? ' open' : ''}">
        <button type="button" class="btn-unstyled run-step-output-head" style="width:100%" aria-expanded="${open}" data-action="runs.output-toggle" data-step-id="${esc(s.step_id)}" data-key="${esc(key)}">
          <span class="run-step-caret">${open ? '▾' : '▸'}</span>
          <span class="ctx-field-k">${esc(label)}</span>
          ${open ? '' : `<span class="ctx-field-v">${esc(preview)}</span>`}
          <span style="flex:1"></span>
          <span class="run-step-output-meta">${text.length} chars</span>
        </button>
        ${open ? `<pre class="run-step-output-full">${esc(text)}</pre>` : ''}
      </div>`;
    }).join('');
    return `<div class="run-step-row-kv run-step-outputs-kv">
      <span class="run-step-row-k">input</span>
      <div class="run-step-outputs">${rows}</div>
    </div>`;
  }

  function _renderStepOutputs(run, stepId) {
    const ws = (run && run.context && run.context.workspace) || {};
    const slot = ws[stepId];
    if (!slot) {
      return `<div class="run-step-row-kv">
        <span class="run-step-row-k">workspace</span>
        <span class="run-step-warn">No output written (step did not complete successfully).</span>
      </div>`;
    }
    const keys = Object.keys(slot);
    if (!keys.length) {
      return `<div class="run-step-row-kv">
        <span class="run-step-row-k">workspace</span>
        <span style="color:var(--text-muted)">(empty object)</span>
      </div>`;
    }
    // Each workspace key is click-to-expand: a collapsed row shows a short
    // preview; expanding reveals the COMPLETE produced value (string verbatim,
    // objects/arrays pretty-printed) in a scrollable block, so the operator can
    // actually read what a step output — not just a 50-char teaser.
    const rows = keys.slice(0, 24).map(k => {
      const v = slot[k];
      const isStr = typeof v === 'string';
      const full = isStr ? v : JSON.stringify(v, null, 2);
      const preview = isStr
        ? v.replace(/\s+/g, ' ').slice(0, 60) + (v.length > 60 ? '…' : '')
        : (v === null ? 'null' : Array.isArray(v) ? `array[${v.length}]` : 'object');
      const meta = isStr ? `${v.length} chars`
        : (Array.isArray(v) ? `${v.length} items` : (v === null ? '' : 'object'));
      const open = _expandedOutputs.has(stepId + '::' + k);
      return `<div class="run-step-output${open ? ' open' : ''}">
        <button type="button" class="btn-unstyled run-step-output-head" style="width:100%" aria-expanded="${open}" data-action="runs.output-toggle" data-step-id="${esc(stepId)}" data-key="${esc(k)}">
          <span class="run-step-caret">${open ? '▾' : '▸'}</span>
          <span class="ctx-field-k">${esc(k)}</span>
          ${open ? '' : `<span class="ctx-field-v">${esc(String(preview))}</span>`}
          <span style="flex:1"></span>
          <span class="run-step-output-meta">${esc(meta)}</span>
        </button>
        ${open ? `<pre class="run-step-output-full">${esc(full)}</pre>` : ''}
      </div>`;
    }).join('');
    return `<div class="run-step-row-kv run-step-outputs-kv">
      <span class="run-step-row-k">output</span>
      <div class="run-step-outputs">${rows}${keys.length > 24 ? `<span class="ctx-field-more">+${keys.length - 24} more</span>` : ''}</div>
    </div>`;
  }

  // Cascade detection — given a run, identify the root failure(s) and
  // the downstream "starved" steps. Approach:
  //   1. Walk step_results in order. Any failed/error step is a root.
  //   2. Any step in _currentSteps that comes AFTER a root in the DAG
  //      (via depends_on transitively) AND either didn't run OR ran
  //      but couldn't find its expected input in workspace, is starved.
  function _computeCascade(run) {
    const roots = new Set();
    const starved = new Set();
    const resultsById = new Map();
    (run.step_results || []).forEach(r => {
      if (!r || !r.step_id) return;
      resultsById.set(r.step_id, r);
      if (['failed', 'error'].includes((r.status || '').toLowerCase())) roots.add(r.step_id);
    });
    if (!roots.size) return { roots, starved };

    // Reachability: iterative BFS from each root through reverse
    // depends_on edges. Iterative + visited set is safe even if the
    // depends_on graph has a cycle (shouldn't, but defensive).
    const reverseEdges = new Map();  // from id → Set<children>
    _currentSteps.forEach(s => {
      const deps = Array.isArray(s.depends_on) ? s.depends_on
                 : (s.depends_on ? [s.depends_on] : []);
      deps.forEach(dep => {
        if (!reverseEdges.has(dep)) reverseEdges.set(dep, new Set());
        reverseEdges.get(dep).add(s.id);
      });
    });
    function descendants(rootId) {
      const out = new Set();
      const queue = Array.from(reverseEdges.get(rootId) || []);
      while (queue.length) {
        const cur = queue.shift();
        if (out.has(cur)) continue;
        out.add(cur);
        (reverseEdges.get(cur) || []).forEach(c => { if (!out.has(c)) queue.push(c); });
      }
      return out;
    }
    roots.forEach(r => {
      descendants(r).forEach(d => {
        const result = resultsById.get(d);
        // A starved step is one that either didn't run at all OR
        // failed because its input wasn't available. We mark both —
        // the run-step row's badge surfaces it.
        if (!result || ['failed', 'error', 'skipped'].includes((result.status || '').toLowerCase())) {
          starved.add(d);
        }
      });
    });
    return { roots, starved };
  }

  function toggleStepExpand(stepId) {
    if (_expandedSteps.has(stepId)) _expandedSteps.delete(stepId);
    else _expandedSteps.add(stepId);
    if (_currentRun) _renderSteps(_currentRun);
  }

  function toggleStepOutput(stepId, key) {
    const id = stepId + '::' + key;
    if (_expandedOutputs.has(id)) _expandedOutputs.delete(id);
    else _expandedOutputs.add(id);
    if (_currentRun) _renderSteps(_currentRun);
  }

  // ── Step-detail popup + troubleshooting pivots ───────────────────────────
  let _detailStepId = null;

  function _detailStep() {
    return _currentRun
      ? (_currentRun.step_results || []).find(x => x.step_id === _detailStepId)
      : null;
  }

  function _stepWorkspace(s) {
    return (((_currentRun || {}).context || {}).workspace || {})[s.step_id] || {};
  }

  function _stepContextText(s) {
    const ws = _stepWorkspace(s);
    const out = Object.values(ws)
      .map(v => (typeof v === 'string' ? v : JSON.stringify(v, null, 2)))
      .join('\n\n');
    return out || s.rendered_prompt || '';
  }

  // The agentic record: what the platform decided and invoked for this
  // step — model + arch placement, the timing anatomy (load vs prompt-eval
  // vs eval), token economics, memory-pressure delta, and every skill /
  // MCP call / plugin tool that fired. This is the context-tuning view:
  // see WHY a step behaved the way it did, then tune.
  // Composite kinds keep their children in the run workspace (loop/ralph →
  // `iterations`, parallel → `branches`), not as nested StepResults. Read that
  // structure back so the run detail can summarize a fan-out / loop / ralph
  // step instead of showing it as one opaque box.
  const _COMPOSITE_KINDS = { parallel: 1, loop: 1, ralph: 1, orchestrator: 1 };
  function _compositeSummary(s) {
    if (!s || !_COMPOSITE_KINDS[s.kind]) return '';
    const ws = _stepWorkspace(s) || {};
    const parts = [];
    const iters = ws.iterations || ws.iteration_results;
    if (iters != null) {
      const n = Array.isArray(iters) ? iters.length : Object.keys(iters).length;
      parts.push(`${n} iteration${n === 1 ? '' : 's'}`);
    }
    const branches = ws.branches || ws.branch_results;
    if (branches != null) {
      const n = Array.isArray(branches) ? branches.length : Object.keys(branches).length;
      parts.push(`${n} branch${n === 1 ? '' : 'es'}`);
    }
    const workers = ws.workers || ws.worker_results;
    if (workers != null) {
      const n = Array.isArray(workers) ? workers.length : Object.keys(workers).length;
      parts.push(`${n} worker${n === 1 ? '' : 's'}`);
    }
    // Ralph / loop halt signals, when the executor recorded them.
    const halt = ws.halt_reason || (ws.halt && ws.halt.reason);
    if (halt) parts.push(`halt: ${halt}`);
    if (ws.consecutive_failures) parts.push(`${ws.consecutive_failures} consecutive fails`);
    if (ws.goal_reached != null) parts.push(ws.goal_reached ? 'goal reached' : 'goal not reached');
    if (!parts.length) return '';
    const tone = s.kind === 'ralph' ? 'var(--amber)' : 'var(--accent)';
    return `<div class="run-decision-chips" style="margin-top:4px"><span class="run-decision-chip" style="border-color:${tone};color:${tone}">▦ ${esc(s.kind)} · ${esc(parts.join(' · '))}</span></div>`;
  }

  function _renderStepDecisions(s) {
    const tk = s.token_count || {};
    const kv = [];
    if (s.kind && s.kind !== 'llm') kv.push(['kind', s.kind]);
    kv.push(['model', s.model_used || '—']);
    if (s.arch_name) kv.push(['arch', s.arch_name]);
    if (tk.prompt_tokens != null) kv.push(['tokens', `${tk.prompt_tokens} in · ${tk.completion_tokens || 0} out`]);
    if (s.duration_seconds != null && tk.completion_tokens) {
      kv.push(['throughput', `${Math.round(tk.completion_tokens / Math.max(0.1, s.duration_seconds))} tok/s`]);
    }
    if (s.keep_alive_used != null) kv.push(['keep-alive', String(s.keep_alive_used)]);
    if (s.retries) kv.push(['retries', `${s.retries}×`]);
    if (s.extension_overhead_ms) kv.push(['ext overhead', `${Math.round(s.extension_overhead_ms)}ms`]);
    const pb = s.pressure_before, pa = s.pressure_after;
    if (pb && pa && pb.level) kv.push(['pressure', `${pb.level} → ${pa.level}`]);
    const kvHtml = kv.map(([k, v]) => `<span class="k">${esc(k)}</span><span class="v">${esc(String(v))}</span>`).join('');

    // Timing anatomy — proportional bar: where the wall-clock actually went.
    let timing = '';
    const load = s.load_duration_ms || 0, pe = s.prompt_eval_duration_ms || 0, ev = s.eval_duration_ms || 0;
    const total = load + pe + ev;
    if (total > 0) {
      const pct = x => Math.max(1, Math.round(100 * x / total));
      timing = `<div class="run-timing-bar">
          <i class="seg-load" style="width:${pct(load)}%" title="model load ${Math.round(load)}ms"></i>
          <i class="seg-prompt" style="width:${pct(pe)}%" title="prompt eval ${Math.round(pe)}ms"></i>
          <i class="seg-eval" style="width:${pct(ev)}%" title="generation ${Math.round(ev)}ms"></i>
        </div>
        <div class="run-timing-legend">
          <span><i class="seg-load" style="background:var(--warn-dim)"></i>load ${(load / 1000).toFixed(1)}s</span>
          <span><i style="background:var(--info-dim)"></i>prompt eval ${(pe / 1000).toFixed(1)}s</span>
          <span><i style="background:var(--accent-dim)"></i>generation ${(ev / 1000).toFixed(1)}s</span>
        </div>`;
    }

    // Invocation chips — the decisions: which skills auto-activated, which
    // MCP servers were called, which plugin tools ran.
    const chips = [];
    (s.skills_activated || []).forEach(x => chips.push(`<span class="run-decision-chip skill" title="skill auto-activated">⚡ ${esc(typeof x === 'string' ? x : x.name || JSON.stringify(x))}</span>`));
    (s.mcp_calls || []).forEach(x => chips.push(`<span class="run-decision-chip mcp" title="MCP call">⇄ ${esc(typeof x === 'string' ? x : (x.server || x.tool || JSON.stringify(x).slice(0, 40)))}</span>`));
    (s.plugin_tools_called || []).forEach(x => chips.push(`<span class="run-decision-chip tool" title="plugin tool">⚙ ${esc(typeof x === 'string' ? x : x.name || JSON.stringify(x).slice(0, 40))}</span>`));
    const chipsHtml = chips.length
      ? `<div class="run-decision-chips">${chips.join('')}</div>`
      : '<div class="run-decision-chips"><span class="run-decision-chip none">no skills / MCP / tools invoked — pure LLM turn</span></div>';

    return `<div class="run-decisions">
      <div class="run-decisions-kv">${kvHtml}</div>
      ${timing}${chipsHtml}${_compositeSummary(s)}
    </div>`;
  }

  function _renderStepDetailFull(s) {
    // Everything fully expanded (no click-to-expand) for the popup: the
    // prompt that ran + every output the step wrote, as scrollable blocks.
    const blocks = [];
    if (s.rendered_system_prompt) blocks.push(['system prompt', s.rendered_system_prompt]);
    if (s.rendered_prompt) blocks.push(['prompt', s.rendered_prompt]);
    const ws = _stepWorkspace(s);
    Object.keys(ws).forEach(k => {
      const v = ws[k];
      blocks.push(['output · ' + k, typeof v === 'string' ? v : JSON.stringify(v, null, 2)]);
    });
    const body = blocks.map(([label, text]) => `
      <div class="run-step-output open" style="margin-bottom:8px">
        <div class="run-step-output-head" style="cursor:default">
          <span class="ctx-field-k">${esc(label)}</span><span style="flex:1"></span>
          <span class="run-step-output-meta">${String(text).length} chars</span>
        </div>
        <pre class="run-step-output-full" style="max-height:280px">${esc(String(text))}</pre>
      </div>`).join('');
    return body || '<div class="model-empty">No prompt or output captured for this step.</div>';
  }

  function openStepDetail(stepId) {
    if (!_currentRun) return;
    _detailStepId = stepId;
    const s = _detailStep();
    if (!s) return;
    const tokens = (s.token_count || {}).total_tokens || 0;
    const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
    const title = document.getElementById('runs-step-modal-title');
    const sub = document.getElementById('runs-step-modal-sub');
    const body = document.getElementById('runs-step-modal-body');
    if (title) title.textContent = s.step_id;
    if (sub) sub.textContent = `${s.kind || 'llm'} · ${esc(s.model_used || '—')} · ${esc(s.status || '')} · ${dur}` +
      (tokens ? ` · ${tokens.toLocaleString()} tok` : '') + (s.retries ? ` · ${s.retries}× retry` : '');
    if (body) {
      body.innerHTML =
        (s.error ? `<div class="run-step-row-kv error"><span class="run-step-row-k">error</span><pre class="run-step-error-text">${esc(s.error)}</pre></div>` : '') +
        _renderStepDecisions(s) +
        _renderStepDetailFull(s);
    }
    const modal = document.getElementById('runs-step-modal');
    if (modal) modal.hidden = false;
  }

  function closeStepDetail() {
    const m = document.getElementById('runs-step-modal');
    if (m) m.hidden = true;
    _detailStepId = null;
  }

  // Inspect the workflow's actual entry-point (seed) or output (deliverable)
  // VALUES — e.g. the code that was reviewed, the review that was produced.
  function openAnchorDetail(kind) {
    if (!_currentRun) return;
    const ctx = _currentRun.context || {};
    let title, sub, entries, accent;
    if (kind === 'seed') {
      title = '▶ START · Seed Input';
      sub = 'The entry-point data this run executed on';
      entries = Object.entries(ctx.seed || {});
      accent = 'var(--accent)';
    } else {
      title = '■ END · Deliverable';
      sub = 'The final output this run produced';
      const results = _currentRun.step_results || [];
      const terminal = results[results.length - 1];
      const ws = ctx.workspace || {};
      entries = terminal ? Object.entries(ws[terminal.step_id] || {}) : [];
      accent = 'var(--cyan)';
    }
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:min(720px,94vw);max-height:88vh;overflow-y:auto;border-radius:6px;';
    const blocks = entries.length
      ? entries.map(([k, v]) => {
          const text = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
          return `<div class="run-step-output open" style="margin-bottom:8px">
            <div class="run-step-output-head" style="cursor:default"><span class="ctx-field-k">${esc(k)}</span><span style="flex:1"></span><span class="run-step-output-meta">${String(text).length} chars</span></div>
            <pre class="run-step-output-full">${esc(String(text))}</pre>
          </div>`;
        }).join('')
      : `<div class="model-empty">No ${esc(kind)} data captured on this run.</div>`;
    inner.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <div style="font-family:var(--mono);font-weight:600;font-size:0.92rem;flex:1;color:${accent}">${esc(title)}</div>
        <button class="action-btn xs ghost" data-action="runs.modal-close">×</button>
      </div>
      <div style="font-size:0.66rem;color:var(--text-muted);margin-bottom:12px">${esc(sub)}</div>
      ${blocks}`;
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
  }

  function pivotResearch() {
    const s = _detailStep(); if (!s) return;
    const ctx = _stepContextText(s);
    closeStepDetail();
    switchTab('research');
    setTimeout(() => {
      const inp = document.getElementById('research-topic');
      if (inp) {
        inp.value = `Research and verify the output of workflow step "${s.step_id}":\n\n${ctx}`.slice(0, 2000);
        inp.focus();
      }
    }, 300);
  }

  function pivotContextGraph() {
    closeStepDetail();
    // S4 graph fork (I10/D13): run/provenance nodes render in the Context
    // tab's OWN #context-graph-svg — Research keeps #graph-svg for the
    // knowledge view — so a run step's "Context Graph" pivot lands on
    // Context, diverging from pivotResearch. switchTab's ladder calls
    // ContextView.init(), which loads/renders the run graph; we just
    // bring the panel into view once it has had a beat to mount.
    switchTab('context');
    setTimeout(() => {
      const g = document.querySelector('#tab-context .graph-panel')
        || document.getElementById('context-graph-svg');
      if (g && g.scrollIntoView) {
        try { g.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) {}
      }
    }, 250);
  }

  function pivotNewAgent() {
    const s = _detailStep(); if (!s) return;
    closeStepDetail();
    if (typeof showCreateAgentModal !== 'function') return;
    showCreateAgentModal();
    // Seed the new agent from this step: its system prompt becomes the agent's,
    // and the description notes the provenance.
    setTimeout(() => {
      const name = document.getElementById('am-name');
      const desc = document.getElementById('am-desc');
      const prompt = document.getElementById('am-prompt');
      if (name && !name.value) name.value = `Agent from ${s.step_id}`;
      if (desc && !desc.value) desc.value = `Seeded from run ${(_currentRun.run_id || '').slice(0, 8)} · step "${s.step_id}"`;
      if (prompt && s.rendered_system_prompt && !prompt.value.trim()) prompt.value = s.rendered_system_prompt;
    }, 300);
  }

  function copyStepContext() {
    const s = _detailStep(); if (!s) return;
    const payload = {
      run_id: _currentRun.run_id,
      step_id: s.step_id,
      model: s.model_used,
      system_prompt: s.rendered_system_prompt,
      prompt: s.rendered_prompt,
      output: _stepWorkspace(s),
    };
    try { navigator.clipboard.writeText(JSON.stringify(payload, null, 2)); } catch (_) {}
  }

  // ── SSE live-stream subscriber ────────────────────────────────────────────
  // Opens an EventSource against the run's /stream endpoint and handles
  // named event types. On onerror the source is closed and polling continues
  // as before (polling was already started by select() before this fires).
  // Call _unsubscribeSSE() when navigating away from the detail view.

  function _unsubscribeSSE() {
    if (_sseSource) {
      try { _sseSource.close(); } catch (_) {}
      _sseSource = null;
    }
    const badge = document.getElementById('rtp-sse-badge');
    if (badge) badge.hidden = true;
  }

  function _renderLivePlan(items) {
    const panel = document.getElementById('runs-tab-live-plan');
    const body  = document.getElementById('runs-tab-plan-body');
    if (!panel || !body) return;
    panel.hidden = false;
    if (!items || !items.length) {
      body.innerHTML = '<div class="model-empty">No plan items yet.</div>';
      return;
    }
    body.innerHTML = items.map(item => {
      const s = (item.status || 'pending').toLowerCase();
      return `<div class="rtp-plan-item" data-testid="plan-item" data-plan-id="${esc(item.id || '')}">
        <span class="rtp-plan-status ${esc(s)}">${esc(s)}</span>
        <span class="rtp-plan-title">${esc(item.title || item.id || '?')}</span>
        ${item.origin ? `<span class="rtp-plan-origin">${esc(item.origin)}</span>` : ''}
      </div>`;
    }).join('');
  }

  function _subscribeSSE(runId) {
    _unsubscribeSSE();
    if (typeof EventSource === 'undefined') return; // SSE not supported
    const src = new EventSource('/api/workflows/runs/' + encodeURIComponent(runId) + '/stream');
    _sseSource = src;

    // Show SSE badge once connected.
    src.addEventListener('stream.hello', () => {
      const badge = document.getElementById('rtp-sse-badge');
      if (badge) badge.hidden = false;
    });

    // Run-level status update — mirror into the data-status attribute.
    src.addEventListener('run.status', e => {
      try {
        const frame = JSON.parse(e.data);
        const status = (frame.data && frame.data.status) || '';
        const meta = document.getElementById('runs-tab-detail-meta');
        if (meta && status) meta.dataset.status = status.toLowerCase();
        // If the run just reached a terminal state, close the stream
        // and let the poller do one final refresh.
        if (['completed', 'failed', 'canceled', 'error'].includes(status.toLowerCase())) {
          _unsubscribeSSE();
          load();
        }
      } catch (_) {}
    });

    // Step started — upsert a synthetic result so the strip shows "running".
    src.addEventListener('step.started', e => {
      try {
        const frame = JSON.parse(e.data);
        const stepId = frame.step_id || (frame.data && frame.data.step_id);
        if (_currentRun && stepId) {
          const results = _currentRun.step_results || [];
          const existing = results.find(r => r.step_id === stepId);
          if (existing) { existing.status = 'running'; }
          else { results.push({ step_id: stepId, status: 'running' }); _currentRun.step_results = results; }
          _renderSteps(_currentRun);
          _applyStatus(_currentRun);
        }
      } catch (_) {}
    });

    // Step completed — upsert result with final status + duration.
    src.addEventListener('step.completed', e => {
      try {
        const frame = JSON.parse(e.data);
        const stepId = frame.step_id || (frame.data && frame.data.step_id);
        const stepData = frame.data || {};
        if (_currentRun && stepId) {
          const results = _currentRun.step_results || [];
          const existing = results.find(r => r.step_id === stepId);
          const status = stepData.status || 'completed';
          if (existing) {
            existing.status = status;
            if (stepData.duration_ms != null) existing.duration_ms = stepData.duration_ms;
          } else {
            results.push({ step_id: stepId, status, duration_ms: stepData.duration_ms });
            _currentRun.step_results = results;
          }
          _renderSteps(_currentRun);
          _applyStatus(_currentRun);
        }
      } catch (_) {}
    });

    // Plan updated — re-render the live plan panel.
    src.addEventListener('plan.updated', e => {
      try {
        const frame = JSON.parse(e.data);
        const plan = frame.data && frame.data.plan;
        if (plan && Array.isArray(plan.items)) {
          _renderLivePlan(plan.items);
        }
      } catch (_) {}
    });

    // Gate pending — surface the approval bar (re-use existing machinery
    // by patching _currentRun with a synthetic pending_gate and calling
    // _renderSteps, which already calls _renderApprovalGate).
    src.addEventListener('gate.pending', e => {
      try {
        const frame = JSON.parse(e.data);
        const gateData = frame.data || {};
        if (_currentRun) {
          _currentRun.status = 'awaiting_approval';
          _currentRun.pending_gate = {
            gate_id:  gateData.gate_id || '',
            step_id:  gateData.step_id || frame.step_id || '',
            question: gateData.prompt  || '',
          };
          _renderSteps(_currentRun);
          _toggleActionButtons(_currentRun);
          if (window.Toast) Toast.info('Gate pending', gateData.prompt || 'Approval required');
        }
      } catch (_) {}
    });

    // Gate resolved — clear synthetic gate state.
    src.addEventListener('gate.resolved', e => {
      try {
        if (_currentRun) {
          delete _currentRun.pending_gate;
          // status will be corrected by the next run.status or poll tick
          _renderSteps(_currentRun);
        }
      } catch (_) {}
    });

    // Stream end — clean up; polling keeps going until terminal status.
    src.addEventListener('stream.end', () => {
      _unsubscribeSSE();
    });

    // On any SSE error fall back to polling (already running) and close.
    src.onerror = () => {
      _unsubscribeSSE();
      // Polling was already started by select() before SSE was opened,
      // so no action needed — the interval keeps running.
    };
  }

  function _toggleActionButtons(run) {
    const s = (run.status || '').toLowerCase();
    const isLive = ['running', 'queued'].includes(s);
    const isFailed = ['failed', 'error'].includes(s);
    const isTerminal = ['completed', 'canceled', 'failed', 'error'].includes(s);
    _setBtn('runs-tab-pause-btn',  isLive);     // shown but disabled — placeholder
    _setBtn('runs-tab-resume-btn', isFailed);
    _setBtn('runs-tab-cancel-btn', isLive);
    _setBtn('runs-tab-rerun-btn',  isTerminal && !!run.workflow_id);
    _setBtn('runs-tab-detail-btn', true);
  }
  function _setBtn(id, show) {
    const b = document.getElementById(id);
    if (b) b.hidden = !show;
  }

  async function resumeCurrent() {
    if (!_selectedId) return;
    try {
      // retries:0 — resume re-executes steps; must fire exactly once.
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(_selectedId)}/resume`, {}, { retries: 0 });
      if (window.Toast) Toast.info('Resuming run', 'Picking up at the first un-completed step.');
      select(_selectedId);
    } catch (e) {
      if (window.Toast) Toast.danger('Resume failed', e.message);
    }
  }
  async function cancelCurrent() {
    if (!_selectedId) return;
    const ok = await Confirm.ask({ title: 'Stop run', body: 'Stop this run? The in-flight LLM call will complete first; no further steps will execute.', okLabel: 'Stop Run', danger: true });
    if (!ok) return;
    try {
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(_selectedId)}/cancel`, {}, { retries: 0 });
      if (window.Toast) Toast.info('Stop requested', 'Engine will halt at the next step boundary.');
    } catch (e) {
      if (window.Toast) Toast.danger('Stop failed', e.message);
    }
  }
  function pauseCurrent() {
    // Engine doesn't yet support cooperative pause (see SIDE_FINDS).
    if (window.Toast) Toast.info('Pause not yet supported',
      'Engine-side pause is on the SIDE_FINDS list — use Stop for now.');
  }
  async function rerunCurrent() {
    if (!_selectedId || !_currentRun) return;
    const wfId = _currentRun.workflow_id;
    const seed = (_currentRun.context && _currentRun.context.seed) || {};
    if (!wfId) {
      if (window.Toast) Toast.danger('Re-run failed', 'No workflow_id on this run.');
      return;
    }
    const ok = await Confirm.ask({ title: 'Re-run workflow', body: `Re-run ${wfId} with the same seed?`, okLabel: 'Re-run' });
    if (!ok) return;
    try {
      // Prefer the async endpoint so the runs tab can immediately
      // start polling without blocking on a possibly-long sync run.
      // retries:0 on BOTH endpoints — a Net retry stacked on the manual
      // sync-fallback could kick off the same workflow run multiple times.
      const r = await Net.call('/api/workflows/run-async', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workflow_id: wfId, seed }),
        },
      });
      if (!r.ok) {
        // Fall back to the sync endpoint for older engines.
        const r2 = await Net.call('/api/workflows/run', {
          retries: 0,
          init: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow_id: wfId, seed }),
          },
        });
        if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
        if (window.Toast) Toast.success('Re-run started (sync)', wfId);
        load();
        return;
      }
      const out = r.data;
      if (window.Toast) Toast.success('Re-run started', `${wfId} · ${(out.run_id || '').slice(0, 12)}…`);
      // Refresh list + auto-select the new run.
      await load();
      if (out.run_id) select(out.run_id);
    } catch (e) {
      if (window.Toast) Toast.danger('Re-run failed', e.message);
    }
  }
  function toggleBottomDrawer() {
    const drawer = document.getElementById('runs-tab-bottom-drawer');
    if (!drawer) return;
    const open = drawer.classList.toggle('open');
    if (open) _renderBottomDrawer(_currentRun);
  }

  // Context-trace panel — shows the run.context.workspace as a
  // producer/consumer map so the operator can see exactly which step
  // wrote which key, and which downstream step couldn't read it.
  // Bottom drawer — fuller drilldown content. Shows seed JSON, the
  // full step list (with system prompts when available from the
  // workflow definition), and the workspace bag in raw form. Heavy
  // content, hence drawer-not-default.
  function _renderBottomDrawer(run) {
    const body = document.getElementById('runs-tab-bottom-drawer-body');
    if (!body) return;
    if (!run) {
      body.innerHTML = '<div class="model-empty">No run selected.</div>';
      return;
    }
    const seed = (run.context && run.context.seed) || {};
    const workspace = (run.context && run.context.workspace) || {};
    const shared = (run.context && run.context.shared) || {};
    // Copy payloads live in module state keyed by data-idx — the raw JSON
    // can be huge and JSON.stringify-into-onclick was attribute-hostile.
    _drawerCopyTexts = [];
    function _jsonPre(label, obj) {
      const txt = JSON.stringify(obj, null, 2);
      const lines = txt.split('\n').length;
      const truncated = lines > 80
        ? txt.split('\n').slice(0, 80).join('\n') + `\n… (${lines - 80} more lines)`
        : txt;
      const copyIdx = _drawerCopyTexts.push(txt) - 1;
      return `<div class="rdd-block">
        <div class="rdd-block-head">
          <span class="rdd-block-label">${esc(label)}</span>
          <button class="action-btn xs ghost"
                  data-action="runs.copy-json" data-idx="${copyIdx}"
                  title="Copy raw JSON to clipboard">Copy</button>
        </div>
        <pre class="rdd-block-pre">${esc(truncated)}</pre>
      </div>`;
    }
    // Step roster — name + status + (if available) system_prompt
    // sourced from _currentSteps which carries the resolved scaffold.
    const stepRoster = (_currentSteps || []).map(s => {
      const result = (run.step_results || []).find(r => r.step_id === s.id);
      const status = (result && result.status) || 'pending';
      const cls = status === 'completed' ? 'ok' : (['failed','error'].includes(status) ? 'fail' : 'pending');
      return `<div class="rdd-step rdd-step-${cls}">
        <span class="rdd-step-id">${esc(s.id)}</span>
        <span class="rdd-step-role">${esc(s.role || '')}</span>
        <span class="rdd-step-status">${esc(status)}</span>
        ${s.system_prompt
          ? `<details class="rdd-step-prompt"><summary>system prompt</summary><pre>${esc(s.system_prompt.slice(0, 1200))}${s.system_prompt.length > 1200 ? '\n…' : ''}</pre></details>`
          : ''}
      </div>`;
    }).join('');

    body.innerHTML = `
      <div class="rdd-cols">
        <div class="rdd-col rdd-col-roster">
          <div class="rdd-block-head"><span class="rdd-block-label">Step roster (${(_currentSteps || []).length})</span></div>
          <div class="rdd-roster">${stepRoster || '<div class="model-empty">No steps.</div>'}</div>
        </div>
        <div class="rdd-col rdd-col-state">
          ${_jsonPre('seed', seed)}
          ${_jsonPre('workspace', workspace)}
          ${Object.keys(shared).length ? _jsonPre('shared', shared) : ''}
        </div>
      </div>
    `;
  }

  function _renderContextTrace(run) {
    const box = document.getElementById('runs-tab-context-body');
    if (!box) return;
    const ws = (run && run.context && run.context.workspace) || {};
    const seed = (run && run.context && run.context.seed) || {};
    const stepIds = Object.keys(ws);
    if (!stepIds.length && !Object.keys(seed).length) {
      box.innerHTML = '<div class="model-empty">No workspace context recorded for this run.</div>';
      return;
    }

    // Producers — every step_id in workspace, with the keys it wrote.
    const producerRows = stepIds.map(stepId => {
      const keys = Object.keys(ws[stepId] || {});
      const result = (run.step_results || []).find(r => r.step_id === stepId);
      const status = (result && result.status) || 'unknown';
      const cls = status === 'completed' ? 'ok' : (['failed', 'error'].includes(status) ? 'fail' : 'pending');
      return `<div class="ctx-row ctx-row-${cls}">
        <span class="ctx-row-step">${esc(stepId)}</span>
        <span class="ctx-row-arrow">→</span>
        <span class="ctx-row-keys">${keys.length
          ? keys.map(k => `<span class="ctx-key-chip">${esc(k)}</span>`).join('')
          : '<span style="color:var(--text-muted)">no output</span>'}</span>
      </div>`;
    }).join('');

    const seedKeys = Object.keys(seed);
    const seedBlock = seedKeys.length ? `<div class="ctx-row ctx-row-ok">
      <span class="ctx-row-step ctx-row-seed">seed</span>
      <span class="ctx-row-arrow">→</span>
      <span class="ctx-row-keys">${seedKeys.map(k => `<span class="ctx-key-chip">${esc(k)}</span>`).join('')}</span>
    </div>` : '';

    box.innerHTML = `<div class="ctx-section-head">Producers (steps → workspace keys)</div>
      ${seedBlock}${producerRows || '<div class="model-empty">No producers yet.</div>'}`;
  }

  // Zoom controls — operate against this tab's own drawflow editor
  // (NOT window.dfEditor, which is the composer's separate instance).
  // Used by the floating zoom toolbar over the runs canvas.
  function zoomIn()    { if (_editor) try { _editor.zoom_in();    } catch (_) {} }
  function zoomOut()   { if (_editor) try { _editor.zoom_out();   } catch (_) {} }
  function zoomReset() {
    if (_editor) try { _editor.zoom_reset(); } catch (_) {}
    // Re-center the bbox after the zoom reset — same auto-layout the
    // initial render uses, so the DAG snaps back to fit the viewport.
    try { _runTabAutoLayout(); } catch (_) {}
  }

  // Registered inside the module for _drawerCopyTexts access — the rest
  // of the runs.* actions live in the block after the module.
  Actions.click({
    'runs.copy-json': el => {
      const t = _drawerCopyTexts[Number(el.dataset.idx)];
      if (t != null) navigator.clipboard.writeText(t);
    }
  });

  return { init, load, render, setFilter, select,
    resumeCurrent, cancelCurrent, pauseCurrent, rerunCurrent,
    toggleStepExpand, toggleStepOutput, toggleBottomDrawer, markFailed,
    openStepDetail, closeStepDetail, openAnchorDetail, pivotResearch, pivotContextGraph,
    pivotNewAgent, copyStepContext,
    zoomIn, zoomOut, zoomReset,
    resolveGate };
})();
