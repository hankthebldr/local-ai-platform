// library/plugins.js — Plugins catalog panel (phase-2 U4 carve).
import { esc, renderMarkdown } from '../core/dom.js';
import { Actions } from '../shell/actions.js';
import { AssetPeek } from './asset-peek.js';

export const PluginsPanel = (function () {
  let _selectedId = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

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
    `;
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

  function renderToolForm(tool) {
    const params = tool.parameters || {};
    if (typeof params !== 'object' || Array.isArray(params)) {
      return '<div style="color:var(--text-muted);font-size:0.7rem">No parameter schema declared.</div>';
    }
    return Object.entries(params).map(([name, spec]) => {
      const required = spec && spec.required === true;
      const type = (spec && spec.type) || 'string';
      const def = spec && spec.default;
      const id = `tool-param-${name}`;
      const label = `<label class="admin-modal-label">${esc(name)}${required ? ' *' : ''}
        <span style="color:var(--text-muted);font-size:0.62rem">(${esc(type)})</span></label>`;
      let input;
      if (type === 'boolean') {
        input = `<input type="checkbox" id="${id}" ${def === true ? 'checked' : ''}>`;
      } else if (type === 'integer' || type === 'number') {
        input = `<input type="number" id="${id}" value="${esc(def ?? '')}" ${type === 'integer' ? 'step="1"' : ''}>`;
      } else if (Array.isArray(spec.enum)) {
        input = `<select id="${id}">${spec.enum.map(o =>
          `<option value="${esc(o)}" ${o === def ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      } else if (type === 'array' || type === 'object') {
        input = `<textarea id="${id}" rows="3" placeholder="JSON or one item per line"></textarea>`;
      } else {
        input = `<input type="text" id="${id}" value="${esc(def ?? '')}">`;
      }
      return label + input;
    }).join('');
  }

  function _collectParams(tool) {
    const out = {};
    const params = tool.parameters || {};
    for (const [name, spec] of Object.entries(params)) {
      const el = document.getElementById('tool-param-' + name);
      if (!el) continue;
      const type = (spec && spec.type) || 'string';
      let v;
      if (type === 'boolean') v = el.checked;
      else if (type === 'integer') v = el.value === '' ? null : parseInt(el.value, 10);
      else if (type === 'number') v = el.value === '' ? null : parseFloat(el.value);
      else if (type === 'array' || type === 'object') {
        const raw = el.value.trim();
        if (!raw) { v = type === 'array' ? [] : {}; }
        else if (raw[0] === '[' || raw[0] === '{') {
          try { v = JSON.parse(raw); } catch (e) { throw new Error(`${name}: invalid JSON`); }
        } else {
          v = raw.split(/\n/).map(s => s.trim()).filter(Boolean);
        }
      } else {
        v = el.value;
      }
      if (spec && spec.required && (v === null || v === undefined || v === '')) {
        throw new Error(`${name} is required`);
      }
      if (v !== null && v !== undefined && v !== '') out[name] = v;
    }
    return out;
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
    const host = document.getElementById('tool-history-' + key);
    if (!host) return;
    const hist = _runHistory.get(key) || [];
    if (!hist.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div style="font-size:0.62rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-top:8px">Last invocations</div>
      ${hist.slice().reverse().map(h => `
        <div style="display:flex;gap:10px;font-size:0.66rem;color:var(--text-dim);padding:2px 0">
          <span style="color:var(--text-muted);min-width:130px">${new Date(h.ts).toLocaleTimeString()}</span>
          <span style="color:${h.status >= 200 && h.status < 300 ? 'var(--accent)' : 'var(--danger,#e54b4b)'};min-width:40px">${h.status}</span>
          <span style="min-width:50px">${h.ms} ms</span>
          <span style="opacity:0.85">${esc(h.summary)}…</span>
        </div>
      `).join('')}
    `;
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
