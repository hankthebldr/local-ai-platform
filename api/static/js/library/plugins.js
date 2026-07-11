// library/plugins.js — Plugins catalog panel (phase-2 U4 carve).
//
// LB1-U2: the schema form kit (renderToolForm/_collectParams/_renderHistory)
// moved into library/test-pane.js as ToolFormKit — this module re-exports the
// same names over the kit, so the tool-tester DOM ids (tool-form-*,
// tool-param-*, tool-tester-run-*, tool-result-*, tool-history-*) and the
// public surface stay byte-compatible. The local esc() shadow is deleted
// (the core/dom.js import is the one implementation). The plugin detail also
// gains a Test section — the plugin-tool TestPane live mount (worked
// example: Plugins > websearch).
import { esc, renderMarkdown } from '../core/dom.js';
import { Actions } from '../shell/actions.js';
import { AssetPeek } from './asset-peek.js';
import { TestPane, ToolFormKit } from './test-pane.js';

export const PluginsPanel = (function () {
  let _selectedId = null;

  async function load() {
    if (!AdminAuth.isSignedIn()) {
      AdminAuth.renderLock('admin-plugins');
      return;
    }
    const list = document.getElementById('plugins-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';

    const r = await AdminAuth.fetch('/api/plugins', {}, 'admin-plugins');
    if (!r.ok) {
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
      return;
    }
    const plugins = await r.json();
    if (!Array.isArray(plugins) || plugins.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">No plugins found in plugins/ directory.</div>';
      return;
    }

    list.innerHTML = plugins.map(p => {
      // Use the unified AgentIcons grammar so admin tab plugin cards
      // pick up the same icon-block visual as the composer workbench
      // and the System-page Discover sections.
      const icon = (window.AgentIcons ? AgentIcons.svg('plugin') : '');
      const tone = (window.AgentIcons ? AgentIcons.tone('plugin') : 'green');
      return `<button type="button" class="btn-unstyled plugin-card ${p.id === _selectedId ? 'selected' : ''}"
           style="width:100%" aria-pressed="${p.id === _selectedId}"
           data-action="plugins.select" data-id="${esc(p.id)}">
        <div class="plugin-card-head">
          <span class="admin-card-icon tone-${esc(tone)}">${icon}</span>
          <div class="plugin-card-head-text">
            <div class="plugin-card-title">
              <span class="plugin-status-pip ${p.error ? 'error' : ''}"></span>${esc(p.name || p.id)}
              <span style="color:var(--text-muted);font-size:0.66rem;margin-left:6px">${esc(p.version || '')}</span>
            </div>
            <div class="plugin-card-meta">
              ${(p.skills || []).length} skill${(p.skills || []).length === 1 ? '' : 's'}
              · ${(p.tools || []).length} tool${(p.tools || []).length === 1 ? '' : 's'}
              <button class="agent-tile-action" style="margin-left:6px"
                      onclick="event.stopPropagation();AssetPeek.open('plugin','${esc(p.id)}')"
                      title="Deep dive — tools, skills, identity">⌕</button>
            </div>
          </div>
        </div>
        <div class="plugin-card-desc">${esc(p.description || '')}</div>
      </button>`;
    }).join('');

    // Auto-select first if none selected.
    if (!_selectedId && plugins.length) select(plugins[0].id);
  }

  async function select(id) {
    _selectedId = id;
    document.querySelectorAll('.plugin-card').forEach(c => c.classList.remove('selected'));
    const cards = document.querySelectorAll('.plugin-card');
    const r = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(id)}`, {}, 'admin-plugins');
    if (!r.ok) {
      document.getElementById('plugin-detail').innerHTML =
        `<div class="admin-modal-error" style="margin:0">Failed to load plugin (HTTP ${r.status})</div>`;
      return;
    }
    const p = await r.json();
    renderDetail(p);
    // mark the matching card.
    cards.forEach(c => {
      if (c.querySelector('.plugin-card-title').textContent.includes(p.name || p.id)) {
        c.classList.add('selected');
      }
    });
  }

  function renderDetail(p) {
    document.getElementById('plugin-detail-label').innerHTML =
      `// ${esc((p.name || p.id).toUpperCase())}`;
    const skillsHtml = (p.skills || []).map(s => `
      <details class="skill-accordion">
        <summary>
          <span style="flex:1">${esc(s.id)}</span>
          ${s.inject ? `<span class="inject-badge">${esc(s.inject)}</span>` : ''}
        </summary>
        <div class="body">${renderMarkdown(s.body || '*(no body)*')}</div>
      </details>
    `).join('');

    const toolsHtml = (p.tools || []).map(t => renderToolAccordion(p.id, t)).join('');

    document.getElementById('plugin-detail').innerHTML = `
      <div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:8px">
        <code>${esc(p.path || '')}</code> · ${esc(p.author || 'unknown author')}
      </div>
      <div style="font-size:0.78rem;color:var(--text);margin-bottom:8px">
        ${esc(p.description || '')}
      </div>
      ${(p.skills || []).length ? `<div class="plugin-section-h">Skills</div>${skillsHtml}` : ''}
      ${(p.tools || []).length ? `<div class="plugin-section-h">Tools</div>${toolsHtml}` : ''}
      ${(p.tools || []).length ? '<div class="plugin-section-h">Test</div><div id="plugin-test-pane"></div>' : ''}
    `;
    // plugin-tool TestPane live mount (LB1-U2) — the layered harness (L0
    // saved settings / L1 skills / L3 schema form) alongside the retained
    // per-tool accordions above.
    const paneHost = document.getElementById('plugin-test-pane');
    if (paneHost) TestPane.mount('plugin-tool', p.id, paneHost, { plugin: p });
  }

  // Per-tool last-5 invocations kept in memory for this panel session.
  const _runHistory = new Map(); // key: `${pluginId}:${toolId}` → array of {ts, ms, status, body}

  function renderToolAccordion(pluginId, tool) {
    const key = `${pluginId}:${tool.id}`;
    return `
      <details class="tool-accordion">
        <summary>
          <span style="flex:1">${esc(tool.id)}</span>
          <span style="color:var(--text-muted);font-size:0.66rem">${esc(tool.description || '')}</span>
        </summary>
        <div class="body">
          <form id="tool-form-${esc(key)}" data-action="plugins.run-tool" data-plugin-id="${esc(pluginId)}" data-tool-id="${esc(tool.id)}">
            ${renderToolForm(tool)}
            <div style="display:flex;justify-content:flex-end;margin-top:10px">
              <button type="submit" id="tool-tester-run-${esc(key)}"
                class="admin-modal-btn primary" style="padding:6px 18px">Run</button>
            </div>
          </form>
          <div id="tool-result-${esc(key)}" style="margin-top:10px"></div>
          <div id="tool-history-${esc(key)}" style="margin-top:10px"></div>
        </div>
      </details>
    `;
  }

  // Extracted to ToolFormKit (test-pane.js) — same names, same behavior,
  // default idPrefix 'tool-param-' keeps the tester DOM ids intact.
  function renderToolForm(tool) {
    return ToolFormKit.renderToolForm(tool);
  }

  function _collectParams(tool) {
    return ToolFormKit.collectParams(tool);
  }

  async function runTool(pluginId, toolId) {
    const key = `${pluginId}:${toolId}`;
    const resultBox = document.getElementById('tool-result-' + key);
    const runBtn = document.getElementById('tool-tester-run-' + key);

    // Re-fetch the tool spec to pick up any param schema we cached.
    const detailR = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(pluginId)}`, {}, 'admin-plugins');
    if (!detailR.ok) { resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">Cannot load plugin (HTTP ${detailR.status})</div>`; return; }
    const plugin = await detailR.json();
    const tool = (plugin.tools || []).find(t => t.id === toolId);
    if (!tool) { resultBox.innerHTML = '<div class="admin-modal-error" style="margin:0">Tool not found.</div>'; return; }

    let params;
    try { params = _collectParams(tool); }
    catch (e) { resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`; return; }

    runBtn.disabled = true;
    runBtn.textContent = 'Running…';
    const t0 = performance.now();
    let r, body, status;
    try {
      r = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(pluginId)}/tools/${encodeURIComponent(toolId)}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(params),
      }, 'admin-plugins');
      const ms = Math.round(performance.now() - t0);
      status = r.status;
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        body = await r.json();
        resultBox.innerHTML = `
          <div style="font-size:0.66rem;color:var(--text-dim);margin-bottom:4px">
            ${ms} ms · status ${status}
          </div>
          <pre class="md-code" style="font-size:0.72rem;max-height:280px;overflow:auto">${esc(JSON.stringify(body, null, 2))}</pre>
        `;
      } else {
        body = await r.text();
        resultBox.innerHTML = `
          <div style="font-size:0.66rem;color:var(--text-dim);margin-bottom:4px">${ms} ms · status ${status}</div>
          <pre class="md-code">${esc(body)}</pre>
        `;
      }
      if (!r.ok) {
        resultBox.querySelector('pre').classList.add('error');
      }

      const hist = _runHistory.get(key) || [];
      hist.push({ts: Date.now(), ms, status, summary: typeof body === 'object' ? JSON.stringify(body).slice(0,80) : String(body).slice(0,80)});
      while (hist.length > 5) hist.shift();
      _runHistory.set(key, hist);
      _renderHistory(key);
    } catch (e) {
      resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = 'Run';
    }
  }

  function _renderHistory(key) {
    // Extracted to ToolFormKit.renderHistory — markup unchanged.
    ToolFormKit.renderHistory(
      document.getElementById('tool-history-' + key), _runHistory.get(key) || []);
  }

  function refresh() { load(); }

  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-plugins') load();
  });

  // Delegated actions — plugin rows + tool-tester forms re-render per
  // load/select. The form's submit delegates (submit bubbles) and keeps
  // the old inline preventDefault.
  Actions.click({
    'plugins.select': el => select(el.dataset.id)
  });
  Actions.on('submit', {
    'plugins.run-tool': (el, e) => {
      e.preventDefault();
      runTool(el.dataset.pluginId, el.dataset.toolId);
    }
  });

  return { load, refresh, select, renderDetail, renderToolAccordion,
           runTool, renderToolForm, _collectParams };
})();
