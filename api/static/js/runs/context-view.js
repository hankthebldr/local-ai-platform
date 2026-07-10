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

export const ContextView = (function () {
  let _loaded = false;   // per-pane load flag — independent of researchLoaded

  function init() {
    _mountGraph();
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

  // Delegation-only wiring (no inline handlers on S4 markup). Actions is
  // the shared singleton from shell/actions.js — safe at module-eval time.
  Actions.click({
    'context.refresh': () => refreshSessions(),
    'context.cleanup': () => cleanup(),
    'context.inspect': el => inspect(el.dataset.cid),
    'context.close':   el => closeSession(el.dataset.cid),
  });

  return { init, refreshSessions };
})();
