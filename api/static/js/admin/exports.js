// admin/exports.js — exports panel (phase-2 U6 carve). Keeps its local shadowing esc().
import { renderMarkdown } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const ExportsPanel = (function () {
  let _selected = new Set();
  let _items = [];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    const list = document.getElementById('exports-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';
    // Exports endpoint is not master-key gated today, but we still attach the
    // header for future-proofing (cheap, harmless, consistent with other admin panels).
    const r = await Net.call('/api/exports', { init: { headers: AdminAuth.authHeaders() } });
    if (!r.ok) {
      // CP-1a: exports is base-auth + `exports` scope (P0-13), NOT master-key —
      // a scoped SPA key reads fine, so we deliberately do NOT pre-gate on the
      // admin master key. But a genuine 401/403 (no valid key at all) should
      // show the sign-in lock instead of a raw "Failed (HTTP 401)".
      if ((r.status === 401 || r.status === 403) && window.AdminAuth) {
        AdminAuth.renderLock('admin-exports');
        return;
      }
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
      return;
    }
    const data = r.data;
    _items = data.exports || [];
    if (!_items.length) {
      list.innerHTML = '<div style="color:var(--text-muted);padding:14px 0">No exports yet — use "Export session" from the Chat tab.</div>';
      _refreshBulkBar();
      return;
    }
    list.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;font-size:0.66rem;color:var(--text-dim);margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid var(--border)">
        <input type="checkbox" id="exports-select-all" data-action="exports.select-all">
        <span>Select all</span>
      </div>
      ${_items.map(rowHtml).join('')}
    `;
    _refreshBulkBar();
  }

  function rowHtml(e) {
    const kb = (e.size / 1024).toFixed(1);
    const date = new Date(e.modified * 1000).toLocaleString();
    const checked = _selected.has(e.filename) ? 'checked' : '';
    return `
      <div class="export-row" id="export-row-${esc(e.filename)}" data-filename="${esc(e.filename)}" style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
        <input type="checkbox" data-filename="${esc(e.filename)}" ${checked}
               data-action="exports.toggle" style="margin-top:3px">
        <div style="flex:1;min-width:0">
          <div style="font-size:0.8rem;color:var(--text);font-weight:500">${esc(e.filename)}</div>
          <div style="font-size:0.66rem;color:var(--text-dim);margin-top:2px">${date} · ${kb} KB</div>
          <div style="font-size:0.7rem;color:var(--text-muted);margin-top:3px;white-space:pre-wrap;max-height:48px;overflow:hidden">${esc((e.preview || '').trim())}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;align-self:flex-start">
          <button class="action-btn small" data-action="exports.view">View</button>
          <button class="action-btn small" data-action="exports.download">Download</button>
          <button class="action-btn small danger" data-action="exports.delete">Delete</button>
        </div>
      </div>
    `;
  }

  function _toggle(name, on) {
    if (on) _selected.add(name); else _selected.delete(name);
    _refreshBulkBar();
  }

  function _toggleSelectAll(on) {
    _selected = on ? new Set(_items.map(e => e.filename)) : new Set();
    document.querySelectorAll('#exports-list input[type=checkbox][data-filename]')
      .forEach(c => { c.checked = on; });
    _refreshBulkBar();
  }

  function _refreshBulkBar() {
    const bar = document.getElementById('exports-bulk-bar');
    if (!bar) return;
    const count = _selected.size;
    bar.hidden = count === 0;
    document.getElementById('exports-selected-count').textContent = count;
  }

  async function view(filename) {
    // expectJson:false — body is raw markdown, read it as text from the response.
    const r = await Net.call('/api/exports/' + encodeURIComponent(filename), { expectJson: false, init: { headers: AdminAuth.authHeaders() } });
    if (!r.ok) { Toast.warn('Export not found'); return; }
    const text = await r.response.text();
    document.getElementById('export-view-title').textContent = filename;
    document.getElementById('export-view-body').innerHTML = renderMarkdown(text);
    document.getElementById('export-view-modal').hidden = false;
  }

  function _closeView() {
    document.getElementById('export-view-modal').hidden = true;
  }

  function download(filename) {
    const url = '/api/exports/' + encodeURIComponent(filename);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function deleteOne(filename) {
    const ok = await Confirm.ask({ title: 'Delete export', body: `Delete "${filename}"?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    const r = await Net.call('/api/exports/' + encodeURIComponent(filename), {
      retries: 0,
      init: { method: 'DELETE', headers: AdminAuth.authHeaders() },
    });
    if (!r.ok) { Toast.danger('Delete failed', `HTTP ${r.status}`); return; }
    _selected.delete(filename);
    load();
  }

  function downloadZip() {
    if (_selected.size === 0) return;
    const names = Array.from(_selected).join(',');
    const url = '/api/exports/zip?names=' + encodeURIComponent(names);
    // We can't easily set Authorization on a window navigation, but the
    // exports zip endpoint is not master-key gated. Use anchor click.
    const a = document.createElement('a');
    a.href = url;
    a.download = 'enclave-exports.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function bulkDelete() {
    const count = _selected.size;
    if (count === 0) return;
    const ok = await Confirm.ask({ title: 'Delete exports', body: `Delete ${count} export${count === 1 ? '' : 's'}?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    // Fire deletes in parallel.
    const names = Array.from(_selected);
    const results = await Promise.all(names.map(n =>
      Net.call('/api/exports/' + encodeURIComponent(n), {
        retries: 0,
        init: { method: 'DELETE', headers: AdminAuth.authHeaders() },
      })
    ));
    const failed = names.filter((_, i) => !results[i].ok);
    if (failed.length) Toast.danger('Delete failed', failed.join(', '));
    _selected.clear();
    load();
  }

  function refresh() { load(); }

  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-exports') load();
  });

  // Esc closes the view modal.
  document.addEventListener('keydown', e => {
    const m = document.getElementById('export-view-modal');
    if (m && !m.hidden && e.key === 'Escape') _closeView();
  });

  // Delegated actions — rows re-render on every load(). Row buttons
  // resolve the filename from the row's data-filename; the checkboxes
  // read el.checked directly (change event), same as the old inline
  // this.checked args.
  const _filenameOf = el => {
    const host = el.closest('[data-filename]');
    return host ? host.dataset.filename : '';
  };
  Actions.click({
    'exports.view':     el => view(_filenameOf(el)),
    'exports.download': el => download(_filenameOf(el)),
    'exports.delete':   el => deleteOne(_filenameOf(el))
  });
  Actions.change({
    'exports.toggle':     el => _toggle(el.dataset.filename, el.checked),
    'exports.select-all': el => _toggleSelectAll(el.checked)
  });

  return { load, refresh, view, download, deleteOne, downloadZip, bulkDelete,
           _toggle, _toggleSelectAll, _closeView };
})();
