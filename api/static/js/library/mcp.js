// library/mcp.js — MCP catalog panel (phase-2 U4 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const MCPPanel = (function () {
  let _servers = [];
  let _selected = null;
  // Marketplace catalog entries from the last browseMarketplace() fetch —
  // install buttons reference them by data-idx instead of serializing the
  // whole entry object into an onclick attribute.
  let _catalogItems = [];

  function _headers() {
    return (window.AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }

  async function load() {
    const el = document.getElementById('mcp-list');
    if (!el) return;
    el.innerHTML = '<div class="model-empty">Loading…</div>';
    try {
      const r = await Net.call('/api/mcp/servers', { init: { headers: _headers() } });
      if (!r.ok) { el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Load failed (${r.status})</div>`; return; }
      _servers = r.data;
      render();
    } catch (e) {
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function refresh() { load(); }

  function render() {
    const el = document.getElementById('mcp-list');
    if (!el) return;
    if (!_servers.length) {
      el.innerHTML = '<div class="model-empty">No MCP servers registered. Click "+ Register" to add one.</div>';
      return;
    }
    el.innerHTML = _servers.map(s => {
      // Persona icon — every MCP server gets the canonical mcp glyph
      // with purple tone, matching the System-page Discover surface.
      const icon = (window.AgentIcons ? AgentIcons.svg('mcp') : '');
      const tone = (window.AgentIcons ? AgentIcons.tone('mcp') : 'purple');
      return `<button type="button" class="btn-unstyled mcp-row ${_selected === s.id ? 'selected' : ''}" style="width:100%" aria-pressed="${_selected === s.id}" data-action="mcp.select" data-id="${esc(s.id)}">
        <span class="admin-card-icon admin-card-icon-sm tone-${esc(tone)}">${icon}</span>
        <span class="mcp-row-dot ${s.tools_count > 0 ? 'up' : 'unknown'}"></span>
        <div style="flex:1;min-width:0">
          <div class="mcp-row-title">${esc(s.name || s.id)}</div>
          <div class="mcp-row-meta">${esc(s.transport)} · ${s.enabled ? 'enabled' : 'disabled'} · ${s.tools_count || 0} tools</div>
        </div>
      </button>`;
    }).join('');
  }

  function select(id) {
    _selected = id;
    render();
    renderDetail();
  }

  function renderDetail() {
    const el = document.getElementById('mcp-detail');
    const label = document.getElementById('mcp-detail-label');
    if (!el || !label) return;
    const s = _servers.find(x => x.id === _selected);
    if (!s) {
      label.textContent = '// SELECT A SERVER';
      el.innerHTML = 'Select a server from the left.';
      return;
    }
    label.textContent = `// ${s.name || s.id}`;
    const envStr = Object.entries(s.env || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—';
    el.innerHTML = `
      <div style="display:grid;grid-template-columns:120px 1fr;gap:6px;font-size:0.74rem;line-height:1.6">
        <div style="color:var(--text-muted)">ID</div><code style="color:var(--accent)">${esc(s.id)}</code>
        <div style="color:var(--text-muted)">Transport</div><div>${esc(s.transport)}</div>
        ${s.transport === 'stdio' ? `
          <div style="color:var(--text-muted)">Command</div><code style="font-size:0.66rem">${esc(s.command || '')} ${(s.args || []).map(esc).join(' ')}</code>
          <div style="color:var(--text-muted)">Env</div><code style="font-size:0.66rem">${esc(envStr)}</code>
        ` : `
          <div style="color:var(--text-muted)">URL</div><code style="font-size:0.66rem">${esc(s.url || '')}</code>
        `}
        <div style="color:var(--text-muted)">Enabled</div><div>${s.enabled ? '✓' : '✕'}</div>
        <div style="color:var(--text-muted)">Description</div><div>${esc(s.description || '')}</div>
      </div>
      <div style="display:flex;gap:6px;margin-top:14px;flex-wrap:wrap">
        <button class="action-btn" data-action="mcp.test" data-id="${esc(s.id)}">Test handshake</button>
        <button class="action-btn" data-action="mcp.discover" data-id="${esc(s.id)}">Discover tools</button>
        <button class="action-btn" data-action="mcp.toggle" data-id="${esc(s.id)}" data-enabled="${!s.enabled}">${s.enabled ? 'Disable' : 'Enable'}</button>
        <button class="action-btn" data-action="mcp.edit" data-id="${esc(s.id)}">Edit</button>
        <button class="action-btn" data-action="mcp.remove" data-id="${esc(s.id)}" style="color:var(--danger);border-color:var(--danger-dim)">Delete</button>
      </div>
      <div id="mcp-detail-tools" style="margin-top:14px">
        <div class="panel-label" style="margin-bottom:6px">Tools (${(s.tools || []).length})</div>
        <div class="mcp-tools-list">
          ${(s.tools || []).map(t => `<div class="mcp-tool">
            <div class="mcp-tool-name">${esc(t.name)}</div>
            <div class="mcp-tool-desc">${esc(t.description || '')}</div>
          </div>`).join('') || '<div style="color:var(--text-muted);font-size:0.66rem">No tools cached. Click "Discover tools" to query the server.</div>'}
        </div>
      </div>
    `;
  }

  async function test(id) {
    try {
      // Net.call (not postJson): result body is read regardless of status, and
      // postJson would add a '{}' body to a body-less POST. retries:0 — live handshake.
      const r = await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}/test`, { retries: 0, init: { method: 'POST', headers: _headers() } });
      const result = (r.data && typeof r.data === 'object') ? r.data : {};
      if (result.reachable) Toast.success('Server reachable', `${result.tools_count} tool(s) advertised`);
      else Toast.danger('Server unreachable', result.error || 'unknown');
      await load();
    } catch (e) { Toast.danger('Test error', e.message); }
  }

  async function discoverTools(id) {
    try {
      // retries:0 — refresh triggers a live tool-discovery query against the server.
      const r = await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}/tools?refresh=true`, { retries: 0, init: { headers: _headers() } });
      if (!r.ok) { Toast.danger('Discover failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      await load();
      _selected = id; renderDetail();
    } catch (e) { Toast.danger('Discover error', e.message); }
  }

  async function toggleEnabled(id, enabled) {
    try {
      await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}`, {
        retries: 0,
        init: {
          method: 'PATCH', headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ enabled }),
        },
      });
      await load();
    } catch (e) { Toast.danger('Toggle error', e.message); }
  }

  async function remove(id) {
    const ok = await Confirm.ask({ title: 'Delete MCP server', body: `Delete MCP server '${id}'?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    try {
      await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}`, { retries: 0, init: { method: 'DELETE', headers: _headers() } });
      _selected = null;
      await load();
      renderDetail();
    } catch (e) { Toast.danger('Delete error', e.message); }
  }

  // ── Create / Edit modal ─────────────────────────────────────────
  function showCreate() {
    document.getElementById('mcp-edit-title').textContent = 'Register MCP server';
    ['mcp-edit-id','mcp-edit-name','mcp-edit-desc','mcp-edit-command','mcp-edit-args','mcp-edit-env','mcp-edit-url','mcp-edit-headers','mcp-edit-tags']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('mcp-edit-id').disabled = false;
    document.getElementById('mcp-edit-transport').value = 'stdio';
    document.getElementById('mcp-edit-timeout').value = 30;
    _onTransportChange();
    _hideError();
    document.getElementById('mcp-edit-modal').hidden = false;
  }

  function edit(id) {
    const s = _servers.find(x => x.id === id);
    if (!s) return;
    document.getElementById('mcp-edit-title').textContent = `Edit ${s.id}`;
    document.getElementById('mcp-edit-id').value = s.id;
    document.getElementById('mcp-edit-id').disabled = true;
    document.getElementById('mcp-edit-name').value = s.name || '';
    document.getElementById('mcp-edit-desc').value = s.description || '';
    document.getElementById('mcp-edit-transport').value = s.transport;
    document.getElementById('mcp-edit-command').value = s.command || '';
    document.getElementById('mcp-edit-args').value = (s.args || []).join(' ');
    // env / headers are masked on the wire; leave blank so PATCH only sets when user types.
    document.getElementById('mcp-edit-env').value = '';
    document.getElementById('mcp-edit-headers').value = '';
    document.getElementById('mcp-edit-url').value = s.url || '';
    document.getElementById('mcp-edit-timeout').value = s.timeout_seconds || 30;
    document.getElementById('mcp-edit-tags').value = (s.tags || []).join(', ');
    _onTransportChange();
    _hideError();
    document.getElementById('mcp-edit-modal').hidden = false;
  }

  function _onTransportChange() {
    const t = document.getElementById('mcp-edit-transport').value;
    document.getElementById('mcp-edit-stdio-fields').style.display = (t === 'stdio') ? '' : 'none';
    document.getElementById('mcp-edit-http-fields').style.display  = (t === 'stdio') ? 'none' : '';
  }

  function _closeModal() { document.getElementById('mcp-edit-modal').hidden = true; }
  function _hideError()  { const e = document.getElementById('mcp-edit-error'); if (e) { e.hidden = true; e.textContent = ''; } }
  function _showError(m) { const e = document.getElementById('mcp-edit-error'); if (e) { e.textContent = m; e.hidden = false; } }

  function _parseKvLines(text, sep) {
    const out = {};
    (text || '').split(/\r?\n/).forEach(line => {
      const idx = line.indexOf(sep);
      if (idx <= 0) return;
      out[line.slice(0, idx).trim()] = line.slice(idx + sep.length).trim();
    });
    return out;
  }

  async function _submit() {
    _hideError();
    const isEdit = document.getElementById('mcp-edit-id').disabled;
    const id = document.getElementById('mcp-edit-id').value.trim();
    const transport = document.getElementById('mcp-edit-transport').value;
    const body = {
      name: document.getElementById('mcp-edit-name').value.trim(),
      description: document.getElementById('mcp-edit-desc').value.trim(),
      transport,
      timeout_seconds: parseInt(document.getElementById('mcp-edit-timeout').value, 10) || 30,
      tags: document.getElementById('mcp-edit-tags').value.split(',').map(s => s.trim()).filter(Boolean),
    };
    if (transport === 'stdio') {
      body.command = document.getElementById('mcp-edit-command').value.trim();
      body.args = document.getElementById('mcp-edit-args').value.trim().split(/\s+/).filter(Boolean);
      const env = _parseKvLines(document.getElementById('mcp-edit-env').value, '=');
      if (Object.keys(env).length) body.env = env;
    } else {
      body.url = document.getElementById('mcp-edit-url').value.trim();
      const hdrs = _parseKvLines(document.getElementById('mcp-edit-headers').value, ':');
      if (Object.keys(hdrs).length) body.headers = hdrs;
    }

    try {
      let r;
      if (isEdit) {
        r = await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}`, {
          retries: 0,
          init: {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ..._headers() },
            body: JSON.stringify(body),
          },
        });
      } else {
        body.id = id;
        r = await Net.call('/api/mcp/servers', {
          retries: 0,
          init: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ..._headers() },
            body: JSON.stringify(body),
          },
        });
      }
      if (!r.ok) {
        _showError((r.data && r.data.detail) || r.error);
        return;
      }
      _closeModal();
      await load();
      if (id) select(id);
    } catch (e) { _showError(e.message); }
  }

  // ── Marketplace — browse + one-click register a catalog MCP server ──
  async function browseMarketplace() {
    const modal = document.createElement('div');
    modal.className = 'mcp-mkt-overlay';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);width:min(760px,95vw);max-height:90vh;display:flex;flex-direction:column;border-radius:8px;overflow:hidden';
    inner.innerHTML = '<div class="model-empty" style="padding:28px">Loading MCP catalog…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
    try {
      const r = await Net.call('/api/mcp/discover', { init: { headers: _headers() } });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      const d = r.data;
      _catalogItems = d.servers || [];
      const icon = (window.AgentIcons ? AgentIcons.svg('mcp') : '');
      const rows = _catalogItems.map((s, i) => {
        const envReq = (s.env_required || []);
        const reqChip = envReq.length
          ? `<span class="skill-disc-chip available" title="${esc(envReq.map(e => e.key).join(', '))}">needs ${envReq.length} secret${envReq.length === 1 ? '' : 's'}</span>` : '';
        const srcChip = s.marketplace ? '<span class="skill-disc-chip marketplace">remote</span>' : '';
        const action = s.installed
          ? '<span class="skill-disc-chip installed">installed</span>'
          : `<button class="action-btn sm accent" data-action="mcp.mkt-install" data-idx="${i}">Install</button>`;
        return `<div class="gh-skill-row">
          <span class="admin-card-icon admin-card-icon-sm tone-purple" style="flex:0 0 auto">${icon}</span>
          <div class="gh-skill-info">
            <div class="gh-skill-name">${esc(s.name || s.id)} ${srcChip} ${reqChip}</div>
            <div class="gh-skill-desc">${esc(s.description || '')}</div>
            ${s.args_hint ? `<div class="gh-skill-desc" style="color:var(--amber);margin-top:2px">⚙ ${esc(s.args_hint)}</div>` : ''}
          </div>
          <div style="flex:0 0 auto">${action}</div>
        </div>`;
      }).join('');
      inner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;padding:14px 18px;border-bottom:1px solid var(--border)">
          <div style="font-family:var(--mono);font-weight:600;flex:1">MCP Marketplace <span style="color:var(--text-muted);font-weight:400">· ${d.count} server${d.count === 1 ? '' : 's'}</span></div>
          <button class="action-btn xs ghost" data-action="mcp.mkt-close">×</button>
        </div>
        <div style="font-size:0.64rem;color:var(--text-muted);padding:8px 18px 0">Servers run as local processes under your account. Servers needing a path/DSN install with a placeholder — edit the registration afterward. Secrets are collected on install.</div>
        <div class="gh-skills" style="overflow:auto;padding:10px 18px 18px">${rows || '<div class="model-empty">Catalog is empty.</div>'}</div>`;
    } catch (e) {
      inner.innerHTML = `<div class="model-empty" style="color:var(--red);padding:24px">Failed: ${esc(e.message)}</div>`;
    }
  }

  async function _installFromCatalog(entry, btn) {
    // Collect required credentials up front; abort if any are skipped.
    const env = {};
    for (const e of (entry.env_required || [])) {
      const val = prompt(`${entry.name}: enter ${e.key}\n${e.hint || ''}`);
      if (val === null) return;           // operator cancelled
      if (val.trim()) env[e.key] = val.trim();
    }
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      // retries:0 — install registers a server; don't double-register.
      const r = await Net.call(`/api/mcp/discover/${encodeURIComponent(entry.id)}/install`, {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ env }),
        },
      });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      if (btn) { btn.outerHTML = '<span class="skill-disc-chip installed">installed</span>'; }
      if (window.Toast) Toast.success('MCP server registered', `${entry.id} — test the handshake from its detail panel.`);
      await load();
      select(entry.id);
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
      Toast.danger('Install failed', e.message);
    }
  }

  // Refresh when the panel becomes visible.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-mcp') load();
  });

  // Delegated actions — server rows + detail buttons re-render on every
  // select/load; marketplace install resolves its catalog entry from
  // _catalogItems by data-idx (registered inside the module for state
  // access). data-enabled is a "true"/"false" string by dataset contract.
  Actions.click({
    'mcp.select':   el => select(el.dataset.id),
    'mcp.test':     el => test(el.dataset.id),
    'mcp.discover': el => discoverTools(el.dataset.id),
    'mcp.toggle':   el => toggleEnabled(el.dataset.id, el.dataset.enabled === 'true'),
    'mcp.edit':     el => edit(el.dataset.id),
    'mcp.remove':   el => remove(el.dataset.id),
    'mcp.mkt-install': el => {
      const entry = _catalogItems[Number(el.dataset.idx)];
      if (entry) _installFromCatalog(entry, el);
    },
    'mcp.mkt-close': el => { const o = el.closest('.mcp-mkt-overlay'); if (o) o.remove(); }
  });

  return { load, refresh, render, select, test, discoverTools, toggleEnabled, remove,
           showCreate, edit, _onTransportChange, _closeModal, _submit,
           browseMarketplace, _installFromCatalog };
})();
