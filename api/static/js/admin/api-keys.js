// admin/api-keys.js — API keys panel (phase-2 U6 carve). Keeps its local shadowing esc().
import { Toast, Confirm } from '../core/ui.js';

export const ApiKeysPanel = (function () {

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  let _knownScopes = null;     // cached list from /api/keys/scopes
  let _selectedScopes = new Set();
  let _newKeyValue = '';

  async function load() {
    if (!AdminAuth.isSignedIn()) {
      AdminAuth.renderLock('admin-keys');
      return;
    }
    const list = document.getElementById('api-keys-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';

    const r = await AdminAuth.fetch('/api/keys', {}, 'admin-keys');
    if (!r.ok) {
      // 401 already handled by AdminAuth.fetch.
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed to load keys (HTTP ${r.status})</div>`;
      return;
    }
    const keys = await r.json();
    if (!Array.isArray(keys) || keys.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);padding:10px 0">No keys yet. Click "+ New Key" to create one.</div>';
      return;
    }

    // Header + rows.
    list.innerHTML = `
      <table class="api-keys-table" role="table">
        <thead>
          <tr>
            <th>Name</th><th>Key</th><th>Scopes</th>
            <th>RPM</th><th>Last used</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          ${keys.map(rowHtml).join('')}
        </tbody>
      </table>
    `;
  }

  function rowHtml(k) {
    const enabled = k.enabled !== false;
    const last = k.last_used_at
      ? new Date(k.last_used_at).toLocaleString()
      : '<span style="color:var(--text-muted)">never</span>';
    const scopes = (k.scopes || []).map(s =>
      `<span class="scope-chip">${esc(s)}</span>`).join(' ');
    const masked = `${esc(k.prefix || '')}…${esc(k.last_four || '')}`;
    return `
      <tr class="${enabled ? '' : 'key-disabled'}">
        <td>${esc(k.name)}</td>
        <td><code>${masked}</code></td>
        <td>${scopes || '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${k.rate_limit_rpm ?? '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${last}</td>
        <td>${enabled
          ? '<span style="color:var(--accent)">enabled</span>'
          : '<span style="color:var(--text-muted)">revoked</span>'}</td>
        <td class="row-actions">
          ${enabled ? `
            <button class="action-btn small" data-action="keys.rotate" data-key-id="${esc(k.id)}" data-key-name="${esc(k.name)}">Rotate</button>
            <button class="action-btn small danger" data-action="keys.revoke" data-key-id="${esc(k.id)}" data-key-name="${esc(k.name)}">Revoke</button>
          ` : ''}
        </td>
      </tr>
    `;
  }

  function refresh() { load(); }

  async function _ensureScopes() {
    if (_knownScopes) return _knownScopes;
    const r = await AdminAuth.fetch('/api/keys/scopes', {}, 'admin-keys');
    if (!r.ok) throw new Error('failed to load scopes');
    _knownScopes = (await r.json()).scopes || [];
    return _knownScopes;
  }

  async function showCreate() {
    if (!AdminAuth.isSignedIn()) { AdminAuth.renderLock('admin-keys'); return; }
    document.getElementById('create-key-form').hidden = false;
    document.getElementById('create-key-reveal').hidden = true;
    document.getElementById('create-key-error').hidden = true;
    document.getElementById('new-key-name').value = '';
    document.getElementById('new-key-rpm').value = '';
    document.getElementById('new-key-expires').value = '';
    document.getElementById('new-key-confirm-copied').checked = false;
    document.getElementById('create-key-close-btn').disabled = true;

    _selectedScopes = new Set();
    // CP-1a: _ensureScopes() hits the network — a failure used to throw past
    // the modal-open lines below, leaving the operator with a half-reset form
    // that never appears (silent dead control). Surface it instead.
    let scopes;
    try {
      scopes = await _ensureScopes();
    } catch (e) {
      const err = document.getElementById('create-key-error');
      if (err) { err.hidden = false; err.textContent = 'Could not load scopes — check the master key and retry.'; }
      Toast.danger('Scopes unavailable', e.message || String(e));
      document.getElementById('create-key-modal').hidden = false;
      return;
    }
    const picker = document.getElementById('new-key-scopes');
    picker.innerHTML = scopes.map(s =>
      `<button type="button" class="btn-unstyled scope-chip" data-scope="${esc(s)}" aria-pressed="false"
        data-action="keys.scope">${esc(s)}</button>`
    ).join('');

    document.getElementById('create-key-modal').hidden = false;
    setTimeout(() => document.getElementById('new-key-name').focus(), 0);
  }

  function _toggleScope(s, el) {
    if (_selectedScopes.has(s)) {
      _selectedScopes.delete(s);
      el.classList.remove('selected');
    } else {
      _selectedScopes.add(s);
      el.classList.add('selected');
    }
    el.setAttribute('aria-pressed', _selectedScopes.has(s) ? 'true' : 'false');
  }

  async function _submitCreate() {
    const name = document.getElementById('new-key-name').value.trim();
    const rpmRaw = document.getElementById('new-key-rpm').value.trim();
    const expRaw = document.getElementById('new-key-expires').value.trim();
    const errBox = document.getElementById('create-key-error');

    if (!name) { errBox.hidden = false; errBox.textContent = 'Name is required.'; return; }
    if (_selectedScopes.size === 0) {
      errBox.hidden = false; errBox.textContent = 'Pick at least one scope.'; return;
    }

    const body = {
      name,
      scopes: Array.from(_selectedScopes),
      rate_limit_rpm: rpmRaw ? Number(rpmRaw) : null,
      expires_at: expRaw ? expRaw + 'T00:00:00Z' : null,
    };

    const r = await AdminAuth.fetch('/api/keys', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }, 'admin-keys');

    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      errBox.hidden = false;
      errBox.textContent = detail.detail || `Failed (HTTP ${r.status})`;
      return;
    }

    const result = await r.json();
    _newKeyValue = result.key || '';
    document.getElementById('new-key-value').textContent = _newKeyValue;
    document.getElementById('create-key-form').hidden = true;
    document.getElementById('create-key-reveal').hidden = false;
    document.getElementById('copy-confirm').style.display = 'none';
    load(); // refresh the table behind the modal
  }

  function _copyKey() {
    if (!_newKeyValue || !navigator.clipboard) return;
    navigator.clipboard.writeText(_newKeyValue).then(() => {
      const c = document.getElementById('copy-confirm');
      c.style.display = 'block';
      setTimeout(() => { c.style.display = 'none'; }, 1500);
    });
  }

  function _closeCreate() {
    _newKeyValue = '';
    document.getElementById('new-key-value').textContent = '';
    document.getElementById('create-key-modal').hidden = true;
  }

  async function rotate(id, name) {
    const ok = await Confirm.ask({ title: `Rotate key "${name}"?`, body: 'The old key will stop working immediately.', okLabel: 'Rotate', danger: true });
    if (!ok) return;
    const r = await AdminAuth.fetch(`/api/keys/${encodeURIComponent(id)}/rotate`, {
      method: 'POST',
    }, 'admin-keys');
    if (!r.ok) {
      Toast.danger('Rotate failed', `HTTP ${r.status}`);
      return;
    }
    const result = await r.json();
    _newKeyValue = result.key || '';
    document.getElementById('new-key-value').textContent = _newKeyValue;
    document.getElementById('create-key-form').hidden = true;
    document.getElementById('create-key-reveal').hidden = false;
    document.getElementById('new-key-confirm-copied').checked = false;
    document.getElementById('create-key-close-btn').disabled = true;
    document.getElementById('copy-confirm').style.display = 'none';
    document.getElementById('create-key-modal').hidden = false;
    load();
    refreshAudit();
  }

  async function revoke(id, name) {
    const ok = await Confirm.ask({ title: `Revoke key "${name}"?`, body: 'This cannot be undone via the UI.', okLabel: 'Revoke', danger: true });
    if (!ok) return;
    const r = await AdminAuth.fetch(`/api/keys/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }, 'admin-keys');
    if (!r.ok) {
      Toast.danger('Revoke failed', `HTTP ${r.status}`);
      return;
    }
    load();
    refreshAudit();
  }

  async function refreshAudit() {
    const host = document.getElementById('api-keys-audit');
    if (!host) return;
    const r = await AdminAuth.fetch('/api/keys/audit', {}, 'admin-keys');
    if (!r.ok) {
      host.innerHTML = `<div class="admin-modal-error" style="margin:0">Audit unavailable (HTTP ${r.status})</div>`;
      return;
    }
    const events = await r.json();
    if (!Array.isArray(events) || events.length === 0) {
      host.innerHTML = '<div style="color:var(--text-muted)">No admin actions recorded yet.</div>';
      return;
    }
    // Last 20, newest first.
    const recent = events.slice(-20).reverse();
    host.innerHTML = recent.map(e => `
      <div style="display:flex;gap:14px;padding:4px 0;border-bottom:1px dashed var(--border)">
        <span style="color:var(--text-muted);min-width:170px">${esc(new Date(e.ts).toLocaleString())}</span>
        <span style="color:var(--accent);min-width:90px">${esc(e.action)}</span>
        <span style="color:var(--text-dim)">${esc(e.name || '')}</span>
        <span style="color:var(--text-muted);font-family:var(--mono)">${esc(e.key_id)}</span>
      </div>
    `).join('');
  }

  // Auto-load when this admin panel is activated.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-keys') {
      load();
      refreshAudit();
    }
  });

  return { load, refresh, showCreate, rotate, revoke, refreshAudit,
           _toggleScope, _submitCreate, _copyKey, _closeCreate };
})();
