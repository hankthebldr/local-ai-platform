// library/prompts.js — Prompts library panel (roles + templates), the FIRST
// LibraryShell adapter (LB0-U1). Full CRUD + live render preview over
// /api/prompts. Migration is endpoint-and-action-identical: every endpoint
// call, action id (prompts.select/edit/cancel/save/remove/promote/render/new/
// refresh/create-close/create-submit), container id (#prompts-list/#prompts-detail/
// #prompts-detail-label/#prompts-count) and selector from the pre-shell panel
// stays alive; the shell adds the uniform sidebar/subnav/actions grammar on
// top (`.lib-row` added ALONGSIDE the retained `.mcp-row`).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';

export const PromptsLibrary = (function () {
  let _items = [];
  let _editing = false;

  function _headers() { return LibraryShell.headers('prompt'); }
  function _key(p) { return `${p.kind}/${p.id}`; }
  function _selected() { return (LibraryShell.state('prompt') || {}).selected; }
  function _current() { return _items.find(p => _key(p) === _selected()) || null; }

  // ── LibraryShell adapter ────────────────────────────────────────────
  // auth 'optional': reads are open server-side; AdminAuth headers merge in
  // when present. Deliberately NOT 'admin' — prompts must not be over-gated.
  const adapter = LibraryShell.register({
    kind: 'prompt',
    tabId: 'prompts',
    countBadgeId: 'prompts-count',
    listElId: 'prompts-list',
    detailElId: 'prompts-detail',
    labelElId: 'prompts-detail-label',
    auth: 'optional',
    selectAction: 'prompts.select',   // legacy row action id kept alive
    rowKeyAttr: 'data-key',
    groupClass: 'prompts-group-label',
    emptyText: 'No prompts. Click "+ New" to add a role or template.',
    emptyDetailLabel: '// SELECT A PROMPT',
    emptyDetailText: 'Select a role or template on the left to view, edit, or render it.',
    title: 'Prompts',

    async load() {
      const r = await LibraryShell.fetch('prompt', '/api/prompts');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _items = r.data || [];
    },

    list() {
      // Group roles then templates — same order + labels as the pre-shell panel.
      const groups = [['role', 'Roles'], ['template', 'Templates']];
      const rows = [];
      groups.forEach(([kind, label]) => {
        _items.filter(p => p.kind === kind).forEach(p => {
          const vars = (p.variables || []).length
            ? `${p.variables.length} var${p.variables.length > 1 ? 's' : ''}` : 'no vars';
          rows.push({
            id: _key(p),
            title: p.name || p.id,
            meta: `${kind} · ${vars}`,
            group: label,
            provenance: p.provenance,          // 'oob'|'user' — layer-derived (LB0-U3)
            blocks: ['context'],               // prompts feed the context building block
            tags: p.tags || [],
            dot: { cls: `prompts-kind-dot ${kind}`, title: kind },
          });
        });
      });
      return rows;
    },

    detail(id) {
      return { sections: { overview: (mountEl) => _renderOverview(mountEl) } };
    },

    actions(id) {
      if (_editing) {
        return [
          { action: 'prompts.save', label: 'Save', verb: 'edit', accent: true },
          { action: 'prompts.cancel', label: 'Cancel', verb: 'edit' },
        ];
      }
      const p = _current();
      const isOob = !!p && p.provenance === 'oob';
      return [
        { action: 'prompts.render', label: '▶ Render preview', verb: 'test', accent: true },
        { action: 'prompts.edit', label: 'Edit', verb: 'edit' },
        // Physical promote — copies the shipped file into the user layer.
        // Disabled (never hidden) on user-layer items so the verb row is stable.
        { action: 'prompts.promote', label: 'Promote', verb: 'promote',
          enabled: isOob, reason: isOob ? undefined : 'already user-layer' },
        { action: 'prompts.remove', label: 'Delete', verb: 'delete' },
      ];
    },
  });

  async function _renderOverview(el) {
    const key = _selected();
    if (!key) return;
    const [kind, ...rest] = key.split('/');
    const id = rest.join('/');
    let p = _current();
    // Fetch the full body on demand (list only carries summaries) unless the
    // cache already holds it (post-save reload merges bodies back in).
    if (!p || p.body == null) {
      const r = await LibraryShell.fetch('prompt',
        `/api/prompts/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
      if (!r.ok) { el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Load failed (${r.status})</div>`; return; }
      p = r.data;
      const idx = _items.findIndex(x => _key(x) === _key(p));
      if (idx >= 0) _items[idx] = p; else _items.push(p);
    }
    const vars = (p.variables || []).length
      ? p.variables.map(v => `<code class="prompts-var">${esc(v)}</code>`).join(' ')
      : '<span style="color:var(--text-muted)">none</span>';
    if (_editing) {
      el.innerHTML = `
        <div class="prompts-meta">
          <code class="prompts-var">${esc(p.kind)}</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
        </div>
        <textarea id="prompts-edit-body" class="prompts-textarea" spellcheck="false">${esc(p.body || '')}</textarea>`;
      return;
    }
    el.innerHTML = `
      <div class="prompts-meta">
        <code class="prompts-var">${esc(p.kind)}</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
        &nbsp;·&nbsp; variables: ${vars}
      </div>
      <pre class="prompts-body">${esc(p.body || '')}</pre>
      <div id="prompts-render-out" class="prompts-render" hidden></div>`;
  }

  // ── Panel API (signature-identical to the pre-shell module) ─────────
  function load() { return LibraryShell.reload('prompt'); }
  function refresh() { load(); }
  function render() { LibraryShell.renderSidebar('prompt'); }
  function renderDetail() { LibraryShell.renderDetail('prompt'); }

  function select(key) {
    _editing = false;
    LibraryShell.select('prompt', key);
  }

  function edit(key) {
    if (key === _selected()) { _editing = true; renderDetail(); }
  }
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
    const ok = await Confirm.ask({
      title: 'Delete prompt',
      body: `Delete ${p.kind} "${p.id}"? This removes the file on disk.`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}`, {
        init: { method: 'DELETE', headers: _headers() }
      });
      if (!r.ok) {
        // 403 on pure-oob carries an explanatory detail — surface it.
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Delete failed: ${detail}`, 'error'); return;
      }
      LibraryShell.select('prompt', null);
      Toast.show('Prompt deleted', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  async function promote(key) {
    // Physical promote (LB0-U3): POST copies the oob file into the user
    // layer server-side. Master-key gated; retries:0 — a retry after a
    // slow success would surface a spurious 409.
    const p = _current();
    if (!p) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}/promote`, {
        retries: 0,
        init: { method: 'POST', headers: _headers() }
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Promote failed: ${detail}`, 'error'); return;
      }
      Toast.show('Promoted to user layer', 'success');
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
      Toast.show('Prompt created', 'success');
      await load();
      LibraryShell.select('prompt', `${kind}/${id}`);
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  // Legacy action ids — aliases over the shell-driven flows (migration
  // contract: old ids stay registered and behavior-identical).
  Actions.click({
    'prompts.select': el => select(el.dataset.key),
    'prompts.edit':   el => edit(el.dataset.key),
    'prompts.cancel': () => cancel(),
    'prompts.save':   el => save(el.dataset.key),
    'prompts.remove': el => remove(el.dataset.key),
    'prompts.promote': el => promote(el.dataset.key),
    'prompts.render': el => renderPreview(el.dataset.key),
    'prompts.new':    () => showCreate(),
    'prompts.refresh': () => refresh(),
    'prompts.create-close': () => closeCreate(),
    'prompts.create-submit': () => submitCreate(),
  });

  return { load, refresh, render, select, edit, cancel, save, remove, promote,
           renderPreview, showCreate, closeCreate, submitCreate, adapter };
})();
