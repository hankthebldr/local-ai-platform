// admin/cloud.js — cloud providers panel (phase-2 U6 carve). Keeps its local shadowing esc().
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const CloudPanel = (function () {
  let _items = [];
  let _selectedId = null;
  let _editId = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    const list = document.getElementById('cloud-list');
    if (!list) return;
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">Loading…</div>';
    try {
      const r = await Net.call('/api/cloud-providers');
      if (!r.ok) {
        list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
        return;
      }
      _items = r.data;
      _render();
    } catch (e) {
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    }
  }

  function refresh() { load(); }

  function _render() {
    const list = document.getElementById('cloud-list');
    if (!list) return;
    if (!Array.isArray(_items) || _items.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">No cloud providers configured. Click <strong>+ Add Provider</strong> to register one.</div>';
      _renderDetailPlaceholder();
      return;
    }
    list.innerHTML = _items.map(p => `
      <button type="button" class="btn-unstyled plugin-card ${p.id === _selectedId ? 'selected' : ''}"
           style="width:100%" aria-pressed="${p.id === _selectedId}"
           data-action="cloud.select" data-id="${esc(p.id)}">
        <div class="plugin-card-title">
          <span class="plugin-status-pip ${p.enabled ? '' : 'error'}"></span>${esc(p.name || p.id)}
          <span style="color:var(--text-muted);font-size:0.66rem;margin-left:6px">${esc(p.kind || 'custom')}</span>
        </div>
        <div class="plugin-card-meta">
          ${p.api_key_set ? '<span style="color:var(--accent)">⚿ key set</span>' : '<span style="color:var(--warn)">no key</span>'}
          · ${(p.models || []).length} curated model${(p.models || []).length === 1 ? '' : 's'}
        </div>
        <div class="plugin-card-desc"><code style="color:var(--text-muted)">${esc(p.base_url || '')}</code></div>
      </button>
    `).join('');
    if (!_selectedId && _items.length) select(_items[0].id);
  }

  function _renderDetailPlaceholder() {
    const detail = document.getElementById('cloud-detail');
    const label = document.getElementById('cloud-detail-label');
    if (label) label.textContent = '// SELECT A PROVIDER';
    if (detail) detail.innerHTML = 'Select a provider to inspect its config or rotate its API key. Use <strong>+ Add Provider</strong> to register a new one.';
  }

  function select(id) {
    _selectedId = id;
    document.querySelectorAll('#cloud-list .plugin-card').forEach(c => c.classList.remove('selected'));
    const card = document.querySelector(`#cloud-list .plugin-card[data-id="${CSS.escape(id)}"]`);
    if (card) card.classList.add('selected');

    const p = _items.find(x => x.id === id);
    const detail = document.getElementById('cloud-detail');
    const label = document.getElementById('cloud-detail-label');
    if (!p || !detail) return;
    if (label) label.textContent = `// ${esc(p.id.toUpperCase())}`;

    const tagList = (p.tags || []).map(t => `<span class="role-pill">${esc(t)}</span>`).join(' ') || '<span style="color:var(--text-muted)">none</span>';
    const modelList = (p.models || []).map(m => `<code>${esc(m)}</code>`).join(', ') || '<span style="color:var(--text-muted)">(empty — will list from provider /v1/models on first use)</span>';
    detail.innerHTML = `
      <div style="font-size:0.74rem;display:grid;grid-template-columns:120px 1fr;gap:6px 14px;margin-bottom:14px">
        <div style="color:var(--text-muted)">Name</div><div>${esc(p.name)}</div>
        <div style="color:var(--text-muted)">Kind</div><div><code>${esc(p.kind)}</code></div>
        <div style="color:var(--text-muted)">Base URL</div><div><code>${esc(p.base_url)}</code></div>
        <div style="color:var(--text-muted)">API key</div><div>${p.api_key_set ? '<span style="color:var(--accent)">set ✓</span> (re-save with a new value to rotate)' : '<span style="color:var(--warn)">not set</span>'}</div>
        <div style="color:var(--text-muted)">Enabled</div><div>${p.enabled ? '<span style="color:var(--accent)">yes</span>' : '<span style="color:var(--warn)">no</span>'}</div>
        <div style="color:var(--text-muted)">Curated models</div><div>${modelList}</div>
        <div style="color:var(--text-muted)">Tags</div><div>${tagList}</div>
        <div style="color:var(--text-muted)">Description</div><div>${esc(p.description || '(none)')}</div>
      </div>
      <div class="admin-modal-actions" style="justify-content:flex-end">
        <button type="button" class="admin-modal-btn" data-action="cloud.edit" data-id="${esc(p.id)}">Edit</button>
        <button type="button" class="admin-modal-btn" style="color:var(--danger);border-color:var(--danger-dim)" data-action="cloud.delete" data-id="${esc(p.id)}">Delete</button>
      </div>
    `;
  }

  function showCreate() {
    _editId = null;
    _resetModal();
    document.getElementById('cloud-edit-title').textContent = 'Add cloud provider';
    document.getElementById('cloud-edit-modal').hidden = false;
    setTimeout(() => document.getElementById('cloud-edit-id').focus(), 0);
  }

  function showEdit(id) {
    const p = _items.find(x => x.id === id);
    if (!p) return;
    _editId = id;
    _resetModal();
    document.getElementById('cloud-edit-title').textContent = `Edit ${p.id}`;
    document.getElementById('cloud-edit-id').value = p.id;
    document.getElementById('cloud-edit-id').disabled = true; // ID is immutable
    document.getElementById('cloud-edit-name').value = p.name || '';
    document.getElementById('cloud-edit-kind').value = p.kind || 'custom';
    document.getElementById('cloud-edit-base-url').value = p.base_url || '';
    document.getElementById('cloud-edit-desc').value = p.description || '';
    document.getElementById('cloud-edit-models').value = (p.models || []).join(', ');
    document.getElementById('cloud-edit-tags').value = (p.tags || []).join(', ');
    document.getElementById('cloud-edit-enabled').checked = p.enabled !== false;
    document.getElementById('cloud-edit-modal').hidden = false;
    setTimeout(() => document.getElementById('cloud-edit-api-key').focus(), 0);
  }

  function _resetModal() {
    ['cloud-edit-id','cloud-edit-name','cloud-edit-base-url','cloud-edit-api-key',
     'cloud-edit-desc','cloud-edit-models','cloud-edit-tags']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('cloud-edit-id').disabled = false;
    document.getElementById('cloud-edit-kind').value = 'openai';
    document.getElementById('cloud-edit-enabled').checked = true;
    document.getElementById('cloud-edit-error').hidden = true;
  }

  function _closeModal() {
    document.getElementById('cloud-edit-modal').hidden = true;
    _editId = null;
  }

  async function _submit() {
    const errBox = document.getElementById('cloud-edit-error');
    errBox.hidden = true;
    const id = document.getElementById('cloud-edit-id').value.trim();
    const name = document.getElementById('cloud-edit-name').value.trim();
    const kind = document.getElementById('cloud-edit-kind').value;
    const baseUrl = document.getElementById('cloud-edit-base-url').value.trim();
    const apiKey = document.getElementById('cloud-edit-api-key').value;
    const description = document.getElementById('cloud-edit-desc').value.trim();
    const modelsRaw = document.getElementById('cloud-edit-models').value.trim();
    const tagsRaw = document.getElementById('cloud-edit-tags').value.trim();
    const enabled = document.getElementById('cloud-edit-enabled').checked;

    if (!id) { errBox.hidden = false; errBox.textContent = 'ID is required.'; return; }
    if (!name) { errBox.hidden = false; errBox.textContent = 'Display name is required.'; return; }
    if (!baseUrl) { errBox.hidden = false; errBox.textContent = 'Base URL is required.'; return; }
    if (!/^[A-Za-z0-9_-]+$/.test(id)) {
      errBox.hidden = false;
      errBox.textContent = "ID can only contain letters, digits, '_' and '-'.";
      return;
    }

    const body = {
      name, kind, base_url: baseUrl, description, enabled,
      models: modelsRaw ? modelsRaw.split(',').map(s => s.trim()).filter(Boolean) : [],
      tags: tagsRaw ? tagsRaw.split(',').map(s => s.trim()).filter(Boolean) : [],
    };
    if (apiKey) body.api_key = apiKey;

    try {
      let r;
      if (_editId) {
        r = await AdminAuth.fetch(`/api/cloud-providers/${encodeURIComponent(_editId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }, 'admin-cloud');
      } else {
        body.id = id;
        r = await AdminAuth.fetch('/api/cloud-providers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }, 'admin-cloud');
      }
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const j = await r.json(); detail = j.detail || detail; } catch (e) {}
        errBox.hidden = false;
        errBox.textContent = detail;
        return;
      }
      _closeModal();
      _selectedId = id;
      await load();
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = e.message;
    }
  }

  async function del(id) {
    const ok = await Confirm.ask({ title: 'Delete cloud provider', body: `Delete cloud provider '${id}'?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    const r = await AdminAuth.fetch(`/api/cloud-providers/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }, 'admin-cloud');
    if (!r.ok) {
      Toast.danger('Delete failed', `HTTP ${r.status}`);
      return;
    }
    if (_selectedId === id) _selectedId = null;
    await load();
  }

  // Hot-load whenever the Cloud Models admin panel becomes active.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-cloud') load();
  });

  // Delegated actions — provider rows + detail buttons re-render per
  // load/select.
  Actions.click({
    'cloud.select': el => select(el.dataset.id),
    'cloud.edit':   el => showEdit(el.dataset.id),
    'cloud.delete': el => del(el.dataset.id)
  });

  return { load, refresh, select, showCreate, showEdit, del, _closeModal, _submit };
})();
