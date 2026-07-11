// library/mcp.js — MCP catalog panel, the SECOND LibraryShell adapter
// (LB0-U1; originally the phase-2 U4 carve). Migration is endpoint-and-
// action-identical: every endpoint (/api/mcp/servers*, /api/mcp/discover*),
// action id (mcp.select/test/discover/toggle/edit/remove/mkt-install/
// mkt-close), container id (#mcp-list/#mcp-detail/#mcp-detail-label) and the
// register/edit modal + marketplace overlay stay alive. Rows keep `.mcp-row`
// with `.lib-row` added alongside. auth 'optional' — same merged-headers
// posture as before, NOT a hard gate (test_top_level_promoted_tabs_not_locked
// pins that this tab never renders the admin-lock).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { LibraryWizard } from './wizard.js';
import { TestPane } from './test-pane.js';

export const MCPPanel = (function () {
  let _servers = [];
  // Marketplace catalog entries from the last browseMarketplace() fetch —
  // install buttons reference them by data-idx instead of serializing the
  // whole entry object into an onclick attribute.
  let _catalogItems = [];

  function _headers() { return LibraryShell.headers('mcp'); }
  function _selected() { return (LibraryShell.state('mcp') || {}).selected; }
  function _server(id) { return _servers.find(x => x.id === id) || null; }

  // ── LibraryShell adapter ────────────────────────────────────────────
  const adapter = LibraryShell.register({
    kind: 'mcp',
    tabId: 'admin-mcp',
    countBadgeId: 'mcp-count',
    listElId: 'mcp-list',
    detailElId: 'mcp-detail',
    labelElId: 'mcp-detail-label',
    auth: 'optional',
    selectAction: 'mcp.select',       // legacy row action id kept alive
    emptyText: 'No MCP servers registered. Click "+ Register" to add one.',
    emptyDetailLabel: '// SELECT A SERVER',
    emptyDetailText: 'Select a server from the left to inspect its tools, test the handshake, or invoke a tool.',
    title: 'MCP Servers',

    async load() {
      const r = await LibraryShell.fetch('mcp', '/api/mcp/servers');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _servers = r.data || [];
    },

    list() {
      return _servers.map(s => ({
        id: s.id,
        title: s.name || s.id,
        meta: `${s.transport} · ${s.enabled ? 'enabled' : 'disabled'} · ${s.tools_count || 0} tools`,
        group: '',                            // flat list, as before
        provenance: s.provenance,             // 'oob' (catalog) | 'user' (manual) — LB0-U3
        blocks: ['tools'],                    // MCP servers feed the tools building block
        tags: s.tags || [],
        icon: 'mcp',                          // canonical mcp glyph, purple tone
        dot: { cls: `mcp-row-dot ${s.tools_count > 0 ? 'up' : 'unknown'}`,
               title: s.tools_count > 0 ? 'tools cached' : 'no tools cached' },
      }));
    },

    detail(id) {
      return { sections: { overview: () => _overviewHtml(id) } };
    },

    // Test subnav slot (LB1-U2) — the pre-shell tool tester moves into the
    // shell's Test tab as the mcp-tool TestPane: pick a cached tool, fill
    // the JSON-Schema-driven form, invoke statelessly (retries:0).
    testPane(id) {
      return (mountEl) => TestPane.mount('mcp-tool', id, mountEl, { server: _server(id) });
    },

    actions(id) {
      const s = _server(id);
      if (!s) return [];
      return [
        { action: 'mcp.test', label: 'Test handshake', verb: 'test' },
        { action: 'mcp.discover', label: 'Discover tools', verb: 'test' },
        { action: 'mcp.toggle', label: s.enabled ? 'Disable' : 'Enable', verb: 'edit',
          data: { enabled: String(!s.enabled) } },
        { action: 'mcp.edit', label: 'Edit', verb: 'edit' },
        { action: 'mcp.remove', label: 'Delete', verb: 'delete', danger: true },
      ];
    },
  });

  function _overviewHtml(id) {
    const s = _server(id);
    if (!s) return '<div class="model-empty">Server not found.</div>';
    const envStr = Object.entries(s.env || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—';
    return `
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
      <div id="mcp-detail-tools" style="margin-top:14px">
        <div class="panel-label" style="margin-bottom:6px">Tools (${(s.tools || []).length})</div>
        <div class="mcp-tools-list">
          ${(s.tools || []).map(t => `<div class="mcp-tool">
            <div class="mcp-tool-name">${esc(t.name)}</div>
            <div class="mcp-tool-desc">${esc(t.description || '')}</div>
          </div>`).join('') || '<div style="color:var(--text-muted);font-size:0.66rem">No tools cached. Click "Discover tools" to query the server.</div>'}
        </div>
      </div>`;
  }

  // ── Panel API (signature-identical to the pre-shell module) ─────────
  function load() { return LibraryShell.reload('mcp'); }
  function refresh() { load(); }
  function render() { LibraryShell.renderSidebar('mcp'); }
  function renderDetail() { LibraryShell.renderDetail('mcp'); }
  function select(id) { LibraryShell.select('mcp', id); }

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
      select(id);
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
      LibraryShell.select('mcp', null);
      await load();
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
    const s = _server(id);
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

  async function _submitCatalogInstall(entry, env, btn) {
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
      return { ok: true };
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
      return { ok: false, detail: e.message };
    }
  }

  async function _installFromCatalog(entry, btn) {
    const envReq = entry.env_required || [];
    if (!envReq.length) {
      // No secrets to collect — one-click register as before.
      const res = await _submitCatalogInstall(entry, {}, btn);
      if (!res.ok) Toast.danger('Install failed', res.detail);
      return;
    }
    // Secrets ride the LibraryWizard Secrets step (LB1-U2 — window.prompt()
    // retired): password inputs, never prefilled, never echoed, masked in
    // the confirm summary. Endpoint + payload byte-identical.
    LibraryWizard.open({
      title: `Install ${entry.name || entry.id}`,
      steps: {
        secrets: {
          fields: envReq.map(e => ({
            key: e.key, label: e.key, hint: e.hint || '', placeholder: e.hint || '',
          })),
        },
      },
      submitLabel: 'Install',
      onSubmit: async (state) => {
        const env = {};
        envReq.forEach(e => {
          const v = (state.secrets[e.key] || '').trim();
          if (v) env[e.key] = v;
        });
        return _submitCatalogInstall(entry, env, btn);
      },
    });
  }

  // Refresh when the panel becomes visible.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-mcp') load();
  });

  // Delegated actions — legacy ids kept alive as aliases over the
  // shell-driven flows; marketplace install resolves its catalog entry from
  // _catalogItems by data-idx (registered inside the module for state
  // access). data-enabled is a "true"/"false" string by dataset contract.
  Actions.click({
    // Toolbar — migrated off inline onclick to data-action delegation
    // (MS-4). The window.MCPPanel global stays exported for parity.
    'mcp.create':   () => showCreate(),
    'mcp.browse':   () => browseMarketplace(),
    'mcp.refresh':  () => refresh(),
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
           browseMarketplace, _installFromCatalog, adapter };
})();
