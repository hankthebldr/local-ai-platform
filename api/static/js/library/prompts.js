// library/prompts.js — Prompts library panel (roles + templates).
// Full CRUD + live render preview over /api/prompts, mirroring MCPPanel's
// list+detail shape. This is the Library-object promotion of the read-only
// Role Library that lives in Research (loadRoles): here roles AND templates
// are first-class, editable, and renderable through the frozen composer.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const PromptsLibrary = (function () {
  let _items = [];
  let _selected = null;   // "kind/id"
  let _editing = false;

  function _headers() {
    return (window.AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }
  function _key(p) { return `${p.kind}/${p.id}`; }
  function _current() { return _items.find(p => _key(p) === _selected) || null; }

  async function load() {
    const el = document.getElementById('prompts-list');
    if (!el) return;
    el.innerHTML = '<div class="model-empty">Loading…</div>';
    try {
      const r = await Net.call('/api/prompts', { init: { headers: _headers() } });
      if (!r.ok) { el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Load failed (${r.status})</div>`; return; }
      _items = r.data || [];
      _updateCount();
      render();
      if (_selected && _current()) renderDetail(); else _clearDetail();
    } catch (e) {
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }
  function refresh() { load(); }

  function _updateCount() {
    const c = document.getElementById('prompts-count');
    if (c) c.textContent = _items.length ? String(_items.length) : '';
  }

  function render() {
    const el = document.getElementById('prompts-list');
    if (!el) return;
    if (!_items.length) {
      el.innerHTML = '<div class="model-empty">No prompts. Click "+ New" to add a role or template.</div>';
      return;
    }
    // Group roles then templates, each under a small header.
    const groups = [['role', 'Roles'], ['template', 'Templates']];
    el.innerHTML = groups.map(([kind, label]) => {
      const rows = _items.filter(p => p.kind === kind);
      if (!rows.length) return '';
      return `<div class="prompts-group-label">${label}</div>` + rows.map(p => {
        const k = _key(p);
        const vars = (p.variables || []).length ? `${p.variables.length} var${p.variables.length > 1 ? 's' : ''}` : 'no vars';
        return `<button type="button" class="btn-unstyled mcp-row ${_selected === k ? 'selected' : ''}" style="width:100%" aria-pressed="${_selected === k}" data-action="prompts.select" data-key="${esc(k)}">
          <span class="prompts-kind-dot ${esc(kind)}"></span>
          <div style="flex:1;min-width:0">
            <div class="mcp-row-title">${esc(p.name || p.id)}</div>
            <div class="mcp-row-meta">${esc(kind)} · ${esc(vars)}</div>
          </div>
        </button>`;
      }).join('');
    }).join('');
  }

  function select(key) {
    _selected = key;
    _editing = false;
    render();
    // Fetch full body on demand (list only carries summaries).
    const p = _current();
    if (p) _loadDetail(p.kind, p.id);
  }

  async function _loadDetail(kind, id) {
    const el = document.getElementById('prompts-detail');
    if (el) el.innerHTML = '<div class="model-empty">Loading…</div>';
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, { init: { headers: _headers() } });
      if (!r.ok) { if (el) el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Load failed (${r.status})</div>`; return; }
      const p = r.data;
      // Merge fetched body into the cached summary.
      const idx = _items.findIndex(x => _key(x) === _key(p));
      if (idx >= 0) _items[idx] = p;
      renderDetail();
    } catch (e) {
      if (el) el.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function _clearDetail() {
    const label = document.getElementById('prompts-detail-label');
    const el = document.getElementById('prompts-detail');
    if (label) label.textContent = '// SELECT A PROMPT';
    if (el) el.innerHTML = 'Select a role or template on the left to view, edit, or render it.';
  }

  function renderDetail() {
    const label = document.getElementById('prompts-detail-label');
    const el = document.getElementById('prompts-detail');
    if (!el || !label) return;
    const p = _current();
    if (!p) { _clearDetail(); return; }
    label.textContent = `// ${p.name || p.id}`;
    const vars = (p.variables || []).length
      ? p.variables.map(v => `<code class="prompts-var">${esc(v)}</code>`).join(' ')
      : '<span style="color:var(--text-muted)">none</span>';
    if (_editing) {
      el.innerHTML = `
        <div class="prompts-meta">
          <code class="prompts-var">${esc(p.kind)}</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
        </div>
        <textarea id="prompts-edit-body" class="prompts-textarea" spellcheck="false">${esc(p.body || '')}</textarea>
        <div style="margin-top:8px;display:flex;gap:6px">
          <button class="action-btn accent" data-action="prompts.save" data-key="${esc(_key(p))}">Save</button>
          <button class="action-btn" data-action="prompts.cancel">Cancel</button>
        </div>`;
      return;
    }
    el.innerHTML = `
      <div class="prompts-meta">
        <code class="prompts-var">${esc(p.kind)}</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
        &nbsp;·&nbsp; variables: ${vars}
      </div>
      <pre class="prompts-body">${esc(p.body || '')}</pre>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
        <button class="action-btn accent" data-action="prompts.render" data-key="${esc(_key(p))}">▶ Render preview</button>
        <button class="action-btn" data-action="prompts.edit" data-key="${esc(_key(p))}">Edit</button>
        <button class="action-btn" data-action="prompts.remove" data-key="${esc(_key(p))}">Delete</button>
      </div>
      <div id="prompts-render-out" class="prompts-render" hidden></div>`;
  }

  function edit(key) { if (key === _selected) { _editing = true; renderDetail(); } }
  function cancel() { _editing = false; renderDetail(); }

  async function save(key) {
    const p = _current();
    const ta = document.getElementById('prompts-edit-body');
    if (!p || !ta) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}`, {
        init: { method: 'PATCH', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({ body: ta.value }) }
      });
      if (!r.ok) { Toast.show(`Save failed (${r.status})`, 'error'); return; }
      _editing = false;
      Toast.show('Prompt saved', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  async function remove(key) {
    const p = _current();
    if (!p) return;
    const ok = await Confirm.show(`Delete ${p.kind} "${p.id}"? This removes the file on disk.`);
    if (!ok) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}`, {
        init: { method: 'DELETE', headers: _headers() }
      });
      if (!r.ok) { Toast.show(`Delete failed (${r.status})`, 'error'); return; }
      _selected = null;
      Toast.show('Prompt deleted', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  async function renderPreview(key) {
    const p = _current();
    const out = document.getElementById('prompts-render-out');
    if (!p || !out) return;
    out.hidden = false;
    out.innerHTML = '<div class="model-empty">Rendering…</div>';
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}/render`, {
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({ task: 'Draft a concise plan for the given objective.' }) }
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(detail)}</div>`;
        return;
      }
      const d = r.data;
      out.innerHTML = `
        <div class="prompts-render-label">SYSTEM</div>
        <pre class="prompts-body">${esc(d.system || '')}</pre>
        <div class="prompts-render-label">USER</div>
        <pre class="prompts-body">${esc(d.user || '')}</pre>`;
    } catch (e) {
      out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function showCreate() {
    const modal = document.getElementById('prompts-create-modal');
    if (modal) {
      modal.hidden = false;
      const idf = document.getElementById('prompts-create-id');
      if (idf) idf.value = '';
      const bodyf = document.getElementById('prompts-create-body');
      if (bodyf) bodyf.value = '';
    }
  }
  function closeCreate() {
    const modal = document.getElementById('prompts-create-modal');
    if (modal) modal.hidden = true;
  }
  async function submitCreate() {
    const kind = (document.getElementById('prompts-create-kind') || {}).value || 'role';
    const id = (document.getElementById('prompts-create-id') || {}).value || '';
    const body = (document.getElementById('prompts-create-body') || {}).value || '';
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(id)) {
      Toast.show('Invalid id — use alnum, _ or -, max 80 chars', 'error'); return;
    }
    try {
      const r = await Net.call('/api/prompts', {
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({ id, kind, body }) }
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Create failed: ${detail}`, 'error'); return;
      }
      closeCreate();
      _selected = `${kind}/${id}`;
      Toast.show('Prompt created', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  Actions.click({
    'prompts.select': el => select(el.dataset.key),
    'prompts.edit':   el => edit(el.dataset.key),
    'prompts.cancel': () => cancel(),
    'prompts.save':   el => save(el.dataset.key),
    'prompts.remove': el => remove(el.dataset.key),
    'prompts.render': el => renderPreview(el.dataset.key),
    'prompts.new':    () => showCreate(),
    'prompts.refresh': () => refresh(),
    'prompts.create-close': () => closeCreate(),
    'prompts.create-submit': () => submitCreate(),
  });

  return { load, refresh, render, select, edit, cancel, save, remove,
           renderPreview, showCreate, closeCreate, submitCreate };
})();
