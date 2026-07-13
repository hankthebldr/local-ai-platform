// runs/context-view.js — S4 Context tab (Operate): run/provenance
// observability. NEW UI (G3) over two EXISTING backends:
//   · the run-filtered view of the single /api/graph build — rendered by
//     main.js's renderGraph(data, 'context') into #context-graph-svg
//     (its own SVG id: runs-tab pivots pin #graph-svg to Research);
//   · the /api/context session store (list / inspect / close / cleanup).
// Mirrors ComposerView/ChatView's module shape: main.js imports it, and
// bridged main.js fns (renderGraph, loadGraphData, switchTab, …) resolve
// via the window bridge at call time as bare references. Owns its OWN
// load flag so Research's researchLoaded single-shot guard can never
// starve this pane (R3 fix).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Actions } from '../shell/actions.js';
import { ContextNodeRail } from '../shell/context-node-rail.js';
import { Toast } from '../core/ui.js';

export const ContextView = (function () {
  let _loaded = false;   // per-pane load flag — independent of researchLoaded

  function init() {
    // Paint the graph, then reconcile the node picker off the cached
    // dataset (whether the paint fetched fresh or reused window.graphData).
    _mountGraph().then(refreshNodeList, refreshNodeList);
    // Sessions are live server state — refresh on every visit.
    refreshSessions();
    if (_loaded) return;
    _loaded = true;
  }

  async function _mountGraph() {
    const svg = document.getElementById('context-graph-svg');
    if (!svg) return;
    try {
      if (!window.graphData) {
        // ONE /api/graph build feeds both panes: the shared loader caches
        // window.graphData and repaints every mounted pane.
        if (typeof loadGraphData === 'function') await loadGraphData();
      }
      // First visit paints the pane (and stamps data-rendered so config
      // changes + rebuilds keep it in sync); later visits only repaint if
      // something cleared the stamp.
      if (window.graphData && svg.dataset.rendered !== '1') {
        renderGraph(window.graphData, 'context');
      }
    } catch (e) {
      console.error('Context graph load failed', e);
    }
  }

  // ── /api/context session store (NET-NEW UI over the existing router) ──

  async function refreshSessions() {
    const box = document.getElementById('context-session-list');
    if (!box) return;
    let sessions;
    try {
      sessions = await Net.getJson('/api/context', { silent: true });
    } catch (_) {
      box.innerHTML = '<div class="context-session-empty">Context store unreachable.</div>';
      return;
    }
    const countEl = document.getElementById('context-session-count');
    if (countEl) countEl.textContent = String((sessions || []).length);
    if (!sessions || !sessions.length) {
      box.innerHTML =
        '<div class="context-session-empty">No active conversation contexts. ' +
        'A session appears here while a chat or workflow holds live context ' +
        'and clears on close / cleanup.</div>';
      return;
    }
    box.innerHTML = sessions.map(_sessionRow).join('');
  }

  function _sessionRow(s) {
    const id = s.conversation_id || '?';
    const tools = (s.tool_calls || []).length;
    const skills = (s.skills_injected || []).length;
    return `<div class="context-session-row" data-cid="${esc(id)}">
      <div class="context-session-head">
        <span class="context-session-id" title="${esc(id)}">${esc(id.slice(0, 24))}${id.length > 24 ? '…' : ''}</span>
        <span class="context-session-meta">${esc(s.model || '')}</span>
      </div>
      <div class="context-session-meta">
        ${s.message_count || 0} msg · ${tools} tool call${tools === 1 ? '' : 's'} · ${skills} skill${skills === 1 ? '' : 's'}
        ${s.last_activity ? ` · last ${esc(String(s.last_activity).slice(0, 19))}` : ''}
      </div>
      <div class="context-session-actions">
        <button type="button" class="action-btn xs ghost" data-action="context.inspect" data-cid="${esc(id)}">Tool calls</button>
        <button type="button" class="action-btn xs ghost" data-action="context.close" data-cid="${esc(id)}">Close</button>
      </div>
      <div class="context-session-detail" id="ctx-session-detail-${esc(id)}" hidden></div>
    </div>`;
  }

  async function inspect(cid) {
    const body = document.getElementById(`ctx-session-detail-${cid}`);
    if (!body) return;
    if (!body.hidden) { body.hidden = true; return; }
    body.hidden = false;
    body.innerHTML = '<div class="context-session-empty">loading…</div>';
    try {
      const calls = await Net.getJson(`/api/context/${encodeURIComponent(cid)}/tool-calls`, { silent: true });
      if (!calls || !calls.length) {
        body.innerHTML = '<div class="context-session-empty">No tool calls recorded on this session.</div>';
        return;
      }
      body.innerHTML = calls.map(tc => `<div class="context-tool-call">
        <span class="context-tool-name">${esc(tc.tool_name || '?')}</span>
        <span class="context-session-meta">${tc.duration_ms != null ? `${esc(String(tc.duration_ms))}ms · ` : ''}${esc(String(tc.timestamp || '').slice(0, 19))}</span>
      </div>`).join('');
    } catch (_) {
      body.innerHTML = '<div class="context-session-empty">Session vanished (closed or cleaned up).</div>';
    }
  }

  async function closeSession(cid) {
    try {
      await Net.postJson(`/api/context/${encodeURIComponent(cid)}/close`, {}, { retries: 0 });
    } catch (_) { /* already gone — refresh below reconciles */ }
    refreshSessions();
  }

  async function cleanup() {
    try {
      const r = await Net.postJson('/api/context/cleanup', {}, { retries: 0 });
      if (window.Toast && r) Toast.show(`Closed ${r.closed || 0} stale session${r.closed === 1 ? '' : 's'}`);
    } catch (_) { /* non-fatal */ }
    refreshSessions();
  }

  // ── U14: Context node rail consumer ─────────────────────────────────
  // Registers kind:'context-node' INTO the shared shell rail
  // (shell/context-node-rail.js). The single pane-guard lives ONCE in that
  // module, so a Research-pane node click can never paint this Context rail.
  // This consumer owns only: the #context-node-list picker, and the pivot
  // footer painted into #context-detail-actions (run / promote / provenance).
  // selectNode(d,'context') fills the rest of #context-detail. It NEVER
  // assigns window.graphData (read-only), mirroring the research-node-rail
  // template, and feature-detects every cross-module call.
  const CTX_RAIL_MOUNT = 'context-detail-actions';
  const _CTX_NODE_TYPES = ['workflow_run', 'response'];
  let _railFocusId = null; // id-compare loop guard — re-render only on change

  function _isFullRunId(id) {
    // A dispatchable run id is the full store key; a truncated graph label
    // (…-elided, or too short) is not safe to hand RunsTab.select.
    const s = String(id || '');
    return /^[A-Za-z0-9][\w.:-]{7,}$/.test(s) && s.indexOf('…') === -1;
  }

  function _runIdOf(node) { return String((node && (node.run_id || node.id)) || ''); }
  function _isCtxNode(n) { return !!n && _CTX_NODE_TYPES.indexOf(n.type) !== -1; }

  function _provenanceLine(node) {
    if (!node) return '';
    if (node.type === 'response') {
      const n = node.edge_count || 0;
      return `<div class="context-node-prov">Grounded on ${n} source${n === 1 ? '' : 's'} · provenance chain intact.</div>`;
    }
    if (node.type === 'workflow_run') {
      const bits = [node.workflow_id ? `workflow ${node.workflow_id}` : null, node.status || null]
        .filter(Boolean).join(' · ');
      return bits ? `<div class="context-node-prov">${esc(bits)}</div>` : '';
    }
    return '';
  }

  // The rail render — paints ONLY the pivot footer. Invoked via
  // ContextNodeRail.activate (single pane-guard) for context-pane nodes.
  function _railRender(node, mount) {
    if (!mount) return;
    mount._node = node;
    const runId = _runIdOf(node);
    const full = _isFullRunId(runId);
    const btns = [];
    if (_isCtxNode(node)) {
      btns.push(full
        ? `<button type="button" class="action-btn xs" data-action="graph.open-run" data-run-id="${esc(runId)}" data-focus="${esc(String(node.step_id || ''))}" title="Open this run in the Runs surface">Open run ▸</button>`
        : `<button type="button" class="action-btn xs" data-action="graph.open-run" disabled title="Cached node id is truncated or stale — rebuild the graph to dispatch this run">Open run ▸</button>`);
      btns.push(`<button type="button" class="action-btn xs ghost" data-action="graph.open-runs" title="Open the Runs surface">Open Runs</button>`);
      btns.push(`<button type="button" class="action-btn xs ghost" data-action="graph.promote-research" title="Capture this node's provenance as a Research artifact">Promote ▸</button>`);
    }
    mount.innerHTML = btns.join(' ') + _provenanceLine(node);
  }

  function _nodeToArtifact(node) {
    const title = String((node && (node.label || node.id)) || 'context node');
    const meta = [node && node.workflow_id, node && node.status, node && node.started_at]
      .filter(Boolean).join(' · ');
    const body = String((node && (node.preview || node.description || node.summary)) || meta || title);
    return {
      title: title.slice(0, 120),
      body,
      source: 'context-graph',
      tags: ['provenance', node && node.type].filter(Boolean),
    };
  }

  function _openRun(runId, focus) {
    if (!runId) return;
    // switchTab rides the legacy bridge (window global) — feature-detect it.
    if (typeof window.switchTab === 'function') window.switchTab('runs');
    try {
      if (window.RunsTab && RunsTab.select) {
        RunsTab.select(runId);
        // data-focus (a step id) scrolls the U7 result strip to that step.
        if (focus) {
          setTimeout(() => {
            const sel = (window.CSS && CSS.escape) ? CSS.escape(focus) : focus;
            const row = document.querySelector(`#runs-tab-steps-body .ws-run-step[data-step-id="${sel}"]`);
            if (row && row.scrollIntoView) row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }, 200);
        }
      }
    } catch (_) { /* RunsTab not ready — the tab switch still lands the operator */ }
  }

  function _promoteResearch() {
    const mount = document.getElementById(CTX_RAIL_MOUNT);
    const node = mount && mount._node;
    if (!node) return;
    // captureRaw already POSTs with retries:0 (a promote is a single write).
    if (window.ResearchArtifacts && ResearchArtifacts.captureRaw) {
      ResearchArtifacts.captureRaw(_nodeToArtifact(node));
    } else if (window.Toast) {
      Toast.info('Unavailable', 'The Research capture surface is not loaded.', { ttl: 1800 });
    }
  }

  // ── #context-node-list — the run/response node picker ────────────────
  function _contextNodes() {
    const data = window.graphData; // READ ONLY — never assign
    if (!data || !Array.isArray(data.nodes)) return [];
    return data.nodes.filter(_isCtxNode);
  }

  function _nodeRow(n) {
    const label = String(n.label || n.id || '?');
    const stale = _isFullRunId(_runIdOf(n))
      ? ''
      : 'Cached id may be stale — rebuild the graph before dispatching. ';
    return `<button type="button" class="context-node-row" data-action="graph.node-select"
              data-node-id="${esc(String(n.id))}" data-pane="context"
              title="${esc(stale)}Inspect ${esc(label)}">
      <span class="context-node-dot kind-${esc(String(n.type))}"></span>
      <span class="context-node-label">${esc(label.slice(0, 46))}</span>
      ${n.status ? `<span class="context-node-status">${esc(String(n.status))}</span>` : ''}
    </button>`;
  }

  function _groupHtml(heading, rows) {
    if (!rows.length) return '';
    return `<div class="context-node-group">
      <div class="context-node-group-h">${esc(heading)} <span class="context-node-group-n">${rows.length}</span></div>
      ${rows.map(_nodeRow).join('')}
    </div>`;
  }

  function refreshNodeList() {
    const box = document.getElementById('context-node-list');
    if (!box) return;
    const nodes = _contextNodes();
    const countEl = document.getElementById('context-node-count');
    if (countEl) countEl.textContent = String(nodes.length);
    if (!nodes.length) {
      box.innerHTML = '<div class="context-session-empty">No run or response nodes yet. ' +
        'Run a workflow to populate the run/provenance graph.</div>';
      return;
    }
    box.innerHTML =
      _groupHtml('Runs', nodes.filter(n => n.type === 'workflow_run')) +
      _groupHtml('Responses', nodes.filter(n => n.type === 'response'));
  }

  // Register kind:'context-node' INTO the shared rail. auth:'optional' —
  // inspecting a run node never needs a key; the promote verb rides
  // ResearchArtifacts' own request-time write path.
  ContextNodeRail.register('context-node', {
    pane: 'context',
    mount: CTX_RAIL_MOUNT,
    render(node, mount) {
      const id = _runIdOf(node);
      // id-compare loop guard: skip a redundant repaint of the same node.
      if (id && id === _railFocusId && mount && mount._node === node) return;
      _railFocusId = id;
      _railRender(node, mount);
    },
    auth: 'optional',
  });

  // Keep the picker in lockstep with every context graph repaint (initial
  // load, Rebuild, config toggles) — renderGraph dispatches this on the
  // context pane only; Research repaints never fire it.
  document.addEventListener('graph:context-rendered', refreshNodeList);

  // Delegation-only wiring (no inline handlers on S4 markup). Actions is
  // the shared singleton from shell/actions.js — safe at module-eval time.
  Actions.click({
    'context.refresh': () => refreshSessions(),
    'context.cleanup': () => cleanup(),
    'context.inspect': el => inspect(el.dataset.cid),
    'context.close':   el => closeSession(el.dataset.cid),
    // U14 pivots (graph.open-runs stays owned by main.js).
    'graph.open-run':        el => _openRun(el.dataset.runId, el.dataset.focus),
    'graph.promote-research': () => _promoteResearch(),
  });

  return { init, refreshSessions };
})();
