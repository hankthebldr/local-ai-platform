// library/patterns.js — Patterns library on the LibraryShell (PT-1).
//
// Patterns are whole agentic sub-DAG BLUEPRINTS (id · name · complexity ·
// kind · desc · steps [· budget_presets]) — the exact shape the Composer's
// Patterns bench drops. This panel lists/creates/edits/promotes/deletes them
// (backed by /api/patterns: builtin catalog ∪ user layer, user shadows) and
// feeds the Composer bench a "Library" section AFTER the 8 statics.
//
// The 8-entry dfPatternTemplates statics array in main.js is NEVER touched —
// the bench renders the statics from JS; user patterns ride their own
// dfUserPatterns Map + the shared application/df-pattern drop MIME. The
// drill-down "Structure" view reuses the SINGLE shared renderer
// window.dfRenderPatternStructure (also painted by the bench inspector), so
// there is one structure renderer, not two.
//
// No inline on*= handlers, no new window globals — all wiring rides the
// delegated Actions registry; cross-module composer access is the bridged
// window.df* surface (same posture as tasks.js reaching AgentIcons/Toast).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { LibraryWizard } from './wizard.js';

export const PatternsPanel = (function () {
  let _patterns = [];      // GET /api/patterns (builtin ∪ user, user shadows)
  let _mounted = false;
  let _editing = null;     // pattern id currently in JSON-source edit mode

  const COMPLEXITY = ['SIMPLE', 'COMPLEX'];
  const KINDS = ['llm', 'parallel', 'loop', 'a2a', 'orchestrator', 'consolidate', 'ralph', 'code'];
  const _ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;

  function _headers() { return LibraryShell.headers('pattern'); }
  function _selected() { return (LibraryShell.state('pattern') || {}).selected; }
  function _pattern(id) { return _patterns.find(p => p.id === id) || null; }
  function _isBuiltin(id) { const p = _pattern(id); return !!p && p.source === 'builtin'; }
  function _renderStructure(tpl) {
    return (typeof window.dfRenderPatternStructure === 'function')
      ? window.dfRenderPatternStructure(tpl)
      : `<pre class="prompts-render-pre">${esc(JSON.stringify(tpl, null, 2))}</pre>`;
  }

  // ── Row builder (LB0 row contract) ───────────────────────────────────
  function _row(p) {
    const complexity = p.complexity || 'SIMPLE';
    return {
      id: p.id,
      title: p.name || p.id,
      meta: `${p.kind || 'llm'} · ${(p.steps || []).length} step${(p.steps || []).length === 1 ? '' : 's'}`,
      group: complexity,                    // complexity-grouped sidebar
      provenance: p.source === 'builtin' ? 'oob' : 'user',
      tags: (p.tags || []).concat([p.kind || 'llm']),
      chips: (p.tags || []).slice(0, 3).map(t => ({ label: t })),
      badges: [{ label: complexity.toLowerCase(), cls: `df-pattern-badge ${complexity === 'COMPLEX' ? 'complex' : 'simple'}` }],
    };
  }

  // ── LibraryShell adapter ─────────────────────────────────────────────
  const adapter = LibraryShell.register({
    kind: 'pattern',
    tabId: 'patterns',
    countBadgeId: 'patterns-count',
    auth: 'optional',                 // reads open; writes carry AdminAuth headers
    selectAction: 'patterns.select',
    title: 'Patterns',
    emptyText: 'No patterns yet. Click "+ New pattern", or "Save canvas as pattern" from the Composer bench.',
    emptyDetailLabel: '// SELECT A PATTERN',
    emptyDetailText: 'Select a pattern for its structure drill-down and JSON — or send it to the Composer.',
    sectionOrder: ['overview', 'source'],
    sectionLabels: { overview: 'Structure', source: 'JSON' },

    async load() {
      const r = await LibraryShell.fetch('pattern', '/api/patterns');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _patterns = r.data || [];
    },

    list() { return _patterns.map(_row); },

    detail(id) {
      return {
        sections: {
          overview: (el) => _overview(el, id),
          source: (el) => _source(el, id),
        },
      };
    },

    actions(id) {
      const builtin = _isBuiltin(id);
      return [
        { action: 'patterns.send-to-composer', label: 'Send to Composer', verb: 'edit', accent: true },
        { action: 'patterns.edit', label: 'Edit JSON', verb: 'edit' },
        {
          action: 'patterns.promote', label: 'Promote', verb: 'promote',
          enabled: builtin, reason: builtin ? undefined : 'already a user copy',
        },
        {
          action: 'patterns.delete', label: 'Delete', verb: 'delete', danger: true,
          enabled: !builtin, reason: builtin ? 'shipped preset — edit to make a deletable copy' : undefined,
        },
      ];
    },
  });

  // ── Detail rendering ──────────────────────────────────────────────────
  function _overview(el, id) {
    const p = _pattern(id);
    if (!p) { el.innerHTML = '<div class="model-empty">Pattern not found — refresh.</div>'; return; }
    el.innerHTML = _renderStructure(p);
  }

  function _source(el, id) {
    const p = _pattern(id);
    if (!p) { el.innerHTML = '<div class="model-empty">Pattern not found — refresh.</div>'; return; }
    if (_editing === id) { _editForm(el, p); return; }
    const json = JSON.stringify(
      { id: p.id, name: p.name, complexity: p.complexity, kind: p.kind, desc: p.desc, steps: p.steps, budget_presets: p.budget_presets || undefined, tags: p.tags || [] },
      null, 2,
    );
    el.innerHTML = `<pre class="prompts-render-pre" style="white-space:pre;font-size:0.66rem;background:var(--bg-alt,rgba(0,0,0,0.2));padding:8px;border:1px solid var(--border);overflow:auto;max-height:360px">${esc(json)}</pre>`;
  }

  function _editForm(el, p) {
    const json = JSON.stringify(
      { name: p.name, complexity: p.complexity, kind: p.kind, desc: p.desc, steps: p.steps, budget_presets: p.budget_presets || undefined, tags: p.tags || [] },
      null, 2,
    );
    el.innerHTML = `
      <label class="admin-modal-label" for="patterns-f-json">Pattern JSON (name · complexity · kind · desc · steps · tags)</label>
      <textarea id="patterns-f-json" class="prompts-textarea" rows="18" spellcheck="false"
        style="width:100%;font-family:var(--mono);font-size:0.64rem">${esc(json)}</textarea>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="action-btn accent" data-action="patterns.save" data-id="${esc(p.id)}">Save</button>
        <button class="action-btn" data-action="patterns.cancel-edit">Cancel</button>
      </div>
      <div style="font-size:0.58rem;color:var(--text-muted);margin-top:6px">Steps must form a scaffoldable workflow — the server validates before save (422 on an un-scaffoldable DAG).</div>`;
  }

  // ── CRUD flows ────────────────────────────────────────────────────────
  function load() { return LibraryShell.reload('pattern'); }
  function select(id) { _editing = null; LibraryShell.select('pattern', id); }

  function edit(id) {
    const target = id || _selected();
    if (!target) return;
    if (target !== _selected()) LibraryShell.select('pattern', target);
    _editing = target;
    LibraryShell.setSubnav('pattern', 'source');
    LibraryShell.renderDetail('pattern');
  }
  function cancelEdit() { _editing = null; LibraryShell.renderDetail('pattern'); }

  async function saveEdit(id) {
    const target = id || _editing;
    if (!target) return;
    const ta = document.getElementById('patterns-f-json');
    if (!ta) return;
    let body;
    try { body = JSON.parse(ta.value); }
    catch (e) { Toast.danger('Invalid JSON', e.message); return; }
    try {
      const r = await Net.call(`/api/patterns/${encodeURIComponent(target)}`, {
        retries: 0,
        init: {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify(body),
        },
      });
      if (!r.ok) { Toast.danger('Save failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      _editing = null;
      Toast.success('Pattern saved', target);
      await load();
      select(target);
      _refreshBench();
    } catch (e) { Toast.danger('Save failed', e.message); }
  }

  // Wizard-backed create.
  function newPattern() {
    LibraryWizard.open({
      title: 'New pattern',
      steps: { configure: (bodyEl) => _wizardForm(bodyEl) },
      validate: (step, state) => {
        if (step === 'configure') {
          const vid = (state.values.id || '').trim();
          if (!_ID_RE.test(vid)) return 'id must be alnum/_/- (≤80, alnum start)';
          if (!(state.values.name || '').trim()) return 'name is required';
          try { JSON.parse(state.values.steps || '[]'); }
          catch (e) { return 'steps must be valid JSON: ' + e.message; }
        }
        return true;
      },
      submitLabel: 'Create',
      onSubmit: (state) => _submitCreate(state),
    });
  }

  function _wizardForm(bodyEl) {
    const sel = (name, opts, cur) =>
      `<select data-wiz-key="${name}" class="model-select" style="width:100%">${
        opts.map(o => `<option value="${esc(o)}" ${o === cur ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
    const starter = JSON.stringify([{
      id: 'step_1', name: 'Step 1', kind: 'llm', role: 'general',
      system_prompt: 'You are a capable assistant. Complete the task and reply with the result.',
      inputs: ['seed.query'], outputs: ['result'],
    }], null, 2);
    bodyEl.innerHTML = `
      <label class="admin-modal-label" for="patterns-w-id">Pattern id</label>
      <input id="patterns-w-id" data-wiz-key="id" type="text" placeholder="e.g. triage_loop" autocomplete="off">
      <label class="admin-modal-label">Name</label>
      <input data-wiz-key="name" type="text" placeholder="Pattern name">
      <label class="admin-modal-label">Complexity</label>${sel('complexity', COMPLEXITY, 'SIMPLE')}
      <label class="admin-modal-label">Card kind</label>${sel('kind', KINDS, 'llm')}
      <label class="admin-modal-label">Description</label>
      <input data-wiz-key="desc" type="text" placeholder="what this topology does">
      <label class="admin-modal-label">Steps (JSON array of engine steps)</label>
      <textarea data-wiz-key="steps" class="prompts-textarea" rows="10" spellcheck="false"
        style="font-family:var(--mono);font-size:0.62rem">${esc(starter)}</textarea>`;
  }

  async function _submitCreate(state) {
    const v = state.values;
    let steps;
    try { steps = JSON.parse(v.steps || '[]'); }
    catch (e) { return { ok: false, detail: 'steps JSON: ' + e.message }; }
    const schema = {
      id: (v.id || '').trim(),
      name: (v.name || '').trim(),
      complexity: v.complexity || 'SIMPLE',
      kind: v.kind || 'llm',
      desc: (v.desc || '').trim(),
      steps,
      tags: [],
      source: 'user',
    };
    try {
      const r = await Net.call('/api/patterns', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify(schema),
        },
      });
      if (!r.ok) return { ok: false, detail: (r.data && r.data.detail) || r.error || `HTTP ${r.status}` };
      await load();
      select(schema.id);
      _refreshBench();
      return { ok: true, message: `Pattern '${schema.id}' created.` };
    } catch (e) { return { ok: false, detail: e.message }; }
  }

  async function promote(id) {
    const target = id || _selected();
    if (!target) return;
    try {
      const r = await Net.call(`/api/patterns/${encodeURIComponent(target)}/promote`, {
        retries: 0,
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({}) },
      });
      if (!r.ok) { Toast.danger('Promote failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      Toast.success('Pattern promoted', target);
      await load();
      select(target);
      _refreshBench();
    } catch (e) { Toast.danger('Promote failed', e.message); }
  }

  async function remove(id) {
    const target = id || _selected();
    if (!target) return;
    const ok = await Confirm.ask({
      title: 'Delete pattern', body: `Delete pattern "${target}"? A shipped preset reverts to its built-in version.`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    try {
      const r = await Net.call(`/api/patterns/${encodeURIComponent(target)}`, {
        retries: 0, init: { method: 'DELETE', headers: _headers() },
      });
      if (!r.ok) { Toast.danger('Delete failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      LibraryShell.select('pattern', null);
      Toast.success('Pattern deleted', target);
      await load();
      _refreshBench();
    } catch (e) { Toast.danger('Delete failed', e.message); }
  }

  function sendToComposer(id) {
    const target = id || _selected();
    if (!target) return;
    if (typeof window.dfSendPatternToComposer === 'function') window.dfSendPatternToComposer(target);
  }

  // The Composer bench is the statics + the user "Library" rows; force a
  // rebuild so a create/edit/delete/promote reflects immediately (fail-soft).
  function _refreshBench() {
    try { if (typeof window.fetchComposerPatterns === 'function') window.fetchComposerPatterns({ force: true }); } catch (_) {}
  }

  // ── Panel API ─────────────────────────────────────────────────────────
  function activate() {
    if (!_mounted) {
      _mounted = true;
      return LibraryShell.mount('pattern', 'patterns-shell');
    }
    return LibraryShell.reload('pattern');
  }

  // ── Delegated actions ─────────────────────────────────────────────────
  Actions.click({
    'patterns.select': el => select(el.dataset.id),
    'patterns.new': () => newPattern(),
    'patterns.edit': el => edit(el.dataset.id),
    'patterns.save': el => saveEdit(el.dataset.id),
    'patterns.cancel-edit': () => cancelEdit(),
    'patterns.promote': el => promote(el.dataset.id),
    'patterns.delete': el => remove(el.dataset.id),
    'patterns.send-to-composer': el => sendToComposer(el.dataset.id),
  });

  return {
    activate, load, select, edit, saveEdit, cancelEdit, newPattern,
    promote, remove, sendToComposer, adapter,
  };
})();
