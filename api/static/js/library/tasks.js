// library/tasks.js — Task Menu library on the LibraryShell (LB6).
//
// Tasks are agentic step SCHEMAS (persona · role · instructions · outputs ·
// format · prompt/hook refs) — a persisted superset of a Composer
// dfStepTemplates record. This panel manages/discovers/creates/edits them and
// feeds the Composer Task bench.
//
// THE BENCH FEED IS NON-DESTRUCTIVE (blocker F1 resolution). The frozen
// 13-entry `dfStepTemplates` array in main.js is NEVER touched. Library tasks
// live in a module-scoped `dfLibraryTemplates` Map here; main.js appends their
// palette rows under a single "Library" divider AFTER the 13 statics
// (deduped, statics winning), gives them their OWN action id
// `bench.inspect-library-task` + their OWN drag MIME
// `application/df-library-task`, and spawns them via `dfAddNodeFromLibraryTask`
// (the dfAddPatternNode seam). Any failure leaves the palette byte-identical.
//
// No inline on*= handlers, no new window globals — all wiring rides the
// delegated Actions registry; cross-module access is ES-module imports.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { LibraryWizard } from './wizard.js';
import { TestPane } from './test-pane.js';

export const TasksPanel = (function () {
  let _tasks = [];         // GET /api/tasks (operator user layer)
  let _discover = null;    // GET /api/tasks/discover cache (builtins + records)
  let _mounted = false;
  let _editing = null;     // task id currently in in-place edit mode
  let _renderOut = null;   // { id, system, user, warnings } — last render preview

  // Module-scoped Map (spec): palette key → mapped bench record. Populated by
  // fetchComposerTasks(); read by main.js's drop handler + inspector.
  const dfLibraryTemplates = new Map();

  // role → color, mirroring dfRoleColors (main.js is not an ES export). Display
  // only — the mapped record's `color` feeds the inspector, never persistence.
  const ROLE_COLORS = {
    reasoning: '#2BD4B4', coding: '#57C4D2', fast: '#E0A33C',
    general: '#1FB983', uncensored: '#E08A4C',
  };
  const ROLES = ['reasoning', 'coding', 'fast', 'general', 'uncensored'];
  const FORMATS = ['raw', 'json', 'json_array', 'markdown_sections', 'key_value', 'csv', 'text'];
  const DISC = 'disc::';
  const _ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;

  function _headers() { return LibraryShell.headers('task'); }
  function _selected() { return (LibraryShell.state('task') || {}).selected; }
  function _task(id) { return _tasks.find(t => t.id === id) || null; }
  function _isDisc(id) { return !!id && id.indexOf(DISC) === 0; }
  function _discId(id) { return (id || '').slice(DISC.length); }
  function _discRecord(id) {
    if (!_discover) return null;
    const rid = _discId(id);
    return [...(_discover.builtins || []), ...(_discover.records || [])]
      .find(x => x.id === rid) || null;
  }

  // ── Bench mapping (schema → dfStepTemplates-shaped record) ────────────
  function mapSchema(s) {
    const role = s.role || 'general';
    const outputs = (Array.isArray(s.outputs) && s.outputs.length) ? s.outputs.slice() : ['result'];
    return {
      key: s.id,
      name: s.name || s.id,
      role,
      persona: s.persona || role,
      prompt: (s.instructions && s.instructions.system_prompt) || '',
      color: ROLE_COLORS[role] || ROLE_COLORS.general,
      outputs,
      format: s.format || 'raw',
      is_decision: !!s.is_decision,
      num_outputs: s.num_outputs || 1,
      kind: 'llm',
    };
  }
  function libraryTask(key) { return dfLibraryTemplates.get(key) || null; }
  function mapById(id) { const t = _task(id); return t ? mapSchema(t) : null; }

  function _stepData(t) {
    const models = (t.model_fit && t.model_fit.models) || [];
    return {
      id: t.id, name: t.name, role: t.role,
      system_prompt: (t.instructions && t.instructions.system_prompt) || '',
      model: models[0] || '',
    };
  }

  // ── Row builders (LB0 row contract) ──────────────────────────────────
  function _row(t) {
    const role = t.role || 'general';
    const pa = t.pattern_affinity || [];
    const chips = pa.slice(0, 3).map(p => ({ label: p }));
    if (pa.length > 3) chips.push({ label: `+${pa.length - 3}`, cls: 'more' });
    return {
      id: t.id,
      title: t.name || t.id,
      meta: `${role} · ${t.format || 'raw'}`,
      group: role,                          // role-grouped sidebar
      provenance: t.source === 'builtin' ? 'oob' : 'user',
      blocks: ['context'],                  // tasks shape the context building block
      tags: (t.tags || []).concat(pa),
      chips,
      badges: [{ label: role, cls: `lib-badge task-role-${esc(role)}` }],
    };
  }

  function _discRow(rec, group, installed) {
    const role = rec.role || 'general';
    return {
      id: DISC + rec.id,
      title: rec.name || rec.id,
      meta: `${role}${rec.intended_output ? ' · ' + rec.intended_output : ''}`,
      group,
      provenance: rec.source === 'builtin' ? 'oob' : 'user',
      blocks: ['context'],
      tags: (rec.tags || []).concat(rec.pattern_affinity || []),
      chips: (rec.pattern_affinity || []).slice(0, 3).map(p => ({ label: p })),
      badges: installed.has(rec.id) ? [{ label: 'installed', cls: 'lib-badge' }] : [],
    };
  }

  function _discRows() {
    if (!_discover) return [];
    const installed = new Set(_discover.installed || []);
    const rows = [];
    (_discover.builtins || []).forEach(b => rows.push(_discRow(b, 'Curated seeds', installed)));
    (_discover.records || []).forEach(r => rows.push(_discRow(r, 'Remote', installed)));
    return rows;
  }

  // ── LibraryShell adapter ─────────────────────────────────────────────
  const adapter = LibraryShell.register({
    kind: 'task',
    tabId: 'tasks',
    countBadgeId: 'tasks-count',
    auth: 'optional',                 // reads open; writes carry merged AdminAuth headers
    selectAction: 'tasks.select',
    title: 'Tasks',
    emptyText: 'No task schemas yet. Click "+ New task", or install a curated seed from Discovered.',
    emptyDiscoveredText: 'Hit ⟳ Discover, then install a curated or remote task seed.',
    emptyDetailLabel: '// SELECT A TASK',
    emptyDetailText: 'Select a task for its instructions, refs, and a live render preview — or run it in the Test tab.',

    async load() {
      const r = await LibraryShell.fetch('task', '/api/tasks');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _tasks = r.data || [];
    },

    list() { return _tasks.map(_row); },
    discovered() { return _discRows(); },

    detail(id) {
      if (_isDisc(id)) return { sections: { overview: (el) => _discOverview(el, id) } };
      return { sections: { overview: (el) => _overview(el, id) } };
    },

    // Test subnav slot — the LB1 step adapter (POST /api/workflows/test-step,
    // labeled prompt-only: tools/skills/parsers not exercised).
    testPane(id) {
      return (el) => {
        if (_isDisc(id)) {
          el.innerHTML = '<div class="model-empty">Install this task first, then test it.</div>';
          return;
        }
        const t = _task(id);
        if (!t) { el.innerHTML = '<div class="model-empty">Task not found — refresh.</div>'; return; }
        return TestPane.mount('step', t.id, el, { stepData: _stepData(t) });
      };
    },

    actions(id) {
      if (_isDisc(id)) {
        const d = _discRecord(id);
        if (!d) return [];
        const installed = new Set((_discover && _discover.installed) || []);
        return [{
          action: 'tasks.install', label: installed.has(d.id) ? 'Installed' : 'Install',
          verb: 'install', accent: true, enabled: !installed.has(d.id),
          reason: installed.has(d.id) ? 'already in the user layer' : undefined,
          data: { 'disc-id': d.id },
        }];
      }
      if (_editing === id) return [];   // edit mode renders Save/Cancel in the form
      return [
        { action: 'tasks.render', label: 'Render', verb: 'test', accent: true },
        { action: 'tasks.test', label: 'Test', verb: 'test' },
        { action: 'tasks.send-to-composer', label: 'Send to Composer', verb: 'edit' },
        { action: 'tasks.edit', label: 'Edit', verb: 'edit' },
        { action: 'tasks.delete', label: 'Delete', verb: 'delete', danger: true },
      ];
    },
  });

  // ── Detail rendering ──────────────────────────────────────────────────
  function _kv(rows) {
    return `<div style="display:grid;grid-template-columns:120px 1fr;gap:6px 12px;font-size:0.72rem;margin-bottom:10px">
      ${rows.map(([k, v]) => `<div style="color:var(--text-muted)">${esc(k)}</div><div>${v}</div>`).join('')}
    </div>`;
  }
  function _chips(items, cls) {
    return (items || []).map(t => `<span class="${cls || 'lib-chip'}">${esc(t)}</span>`).join(' ')
      || '<span style="color:var(--text-muted)">—</span>';
  }

  function _refLink(kind, id) {
    // Clickable prompt/hook refs jump to the Prompts library detail via
    // LibraryShell.open (the shell prompt id is `kind/id`).
    return `<button type="button" class="action-btn xs" data-action="tasks.open-ref"
      data-ref="${esc(`${kind}/${id}`)}" title="Open ${esc(kind)} '${esc(id)}' in Prompts">↗ ${esc(kind)}: ${esc(id)}</button>`;
  }

  function _overview(el, id) {
    const t = _task(id);
    if (!t) { el.innerHTML = '<div class="model-empty">Task not found — refresh.</div>'; return; }
    if (_editing === id) { _editForm(el, t); return; }
    const refs = t.refs || {};
    const refBits = [];
    if (refs.role_ref) refBits.push(_refLink('role', refs.role_ref));
    if (refs.template_ref) refBits.push(_refLink('template', refs.template_ref));
    (refs.hooks || []).forEach(h => {
      const name = (h && (h.target || h.name)) || null;
      if (name) refBits.push(_refLink('hook', name));
    });
    const preview = (_renderOut && _renderOut.id === id) ? `
      <div class="prompts-render-label" style="margin-top:12px">// RENDER PREVIEW</div>
      ${(_renderOut.warnings || []).length ? `<div class="admin-modal-sub" style="color:var(--amber)">⚠ ${_renderOut.warnings.map(esc).join('; ')}</div>` : ''}
      <pre class="prompts-render-pre" style="white-space:pre-wrap;font-size:0.66rem;background:var(--bg-alt,rgba(0,0,0,0.2));padding:8px;border:1px solid var(--border);overflow:auto;max-height:280px">${esc(_renderOut.system || '')}</pre>` : '';
    el.innerHTML = _kv([
      ['Task id', `<code>${esc(t.id)}</code>`],
      ['Name', esc(t.name || '')],
      ['Role', `<span class="lib-badge task-role-${esc(t.role || 'general')}">${esc(t.role || 'general')}</span>`],
      ['Persona', esc(t.persona || '—')],
      ['Outputs', _chips(t.outputs)],
      ['Format', esc(t.format || 'raw')],
      ['Intended output', esc(t.intended_output || '—')],
      ['Pattern affinity', _chips(t.pattern_affinity)],
      ['Tags', _chips(t.tags)],
      ['Refs', refBits.join(' ') || '<span style="color:var(--text-muted)">none</span>'],
    ]) + `
      <div class="prompts-render-label">// INSTRUCTIONS</div>
      <pre class="prompts-render-pre" style="white-space:pre-wrap;font-size:0.7rem;background:var(--bg-alt,rgba(0,0,0,0.2));padding:8px;border:1px solid var(--border);overflow:auto">${esc((t.instructions && t.instructions.system_prompt) || '')}</pre>
      ${preview}`;
  }

  function _discOverview(el, id) {
    const d = _discRecord(id);
    if (!d) { el.innerHTML = '<div class="model-empty">Not in the current scan — hit ⟳ Discover.</div>'; return; }
    el.innerHTML = _kv([
      ['Id', `<code>${esc(d.id)}</code>`],
      ['Name', esc(d.name || '')],
      ['Role', esc(d.role || 'general')],
      ['Source', esc(d.source || 'remote')],
      ['Intended output', esc(d.intended_output || '—')],
      ['Pattern affinity', _chips(d.pattern_affinity)],
      ['Tags', _chips(d.tags)],
    ]) + `<pre class="prompts-render-pre" style="white-space:pre-wrap;font-size:0.7rem;background:var(--bg-alt,rgba(0,0,0,0.2));padding:8px;border:1px solid var(--border)">${esc((d.instructions && d.instructions.system_prompt) || '')}</pre>
      <div style="font-size:0.6rem;color:var(--text-muted);margin-top:6px">Discovered read — nothing fetches on tab activation; ⟳ Discover is the only egress.</div>`;
  }

  // ── In-place edit form ────────────────────────────────────────────────
  function _formFields(t) {
    t = t || {};
    const instr = t.instructions || {};
    const refs = t.refs || {};
    const sel = (name, opts, cur) =>
      `<select id="tasks-f-${name}" class="model-select" style="width:100%">${
        opts.map(o => `<option value="${esc(o)}" ${o === cur ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
    return `
      <label class="admin-modal-label" for="tasks-f-name">Name</label>
      <input id="tasks-f-name" type="text" value="${esc(t.name || '')}" placeholder="Task name">
      <label class="admin-modal-label" for="tasks-f-role">Role</label>${sel('role', ROLES, t.role || 'general')}
      <label class="admin-modal-label" for="tasks-f-persona">Persona</label>
      <input id="tasks-f-persona" type="text" value="${esc(t.persona || '')}" placeholder="persona (icon key)">
      <label class="admin-modal-label" for="tasks-f-system_prompt">Instructions (system prompt)</label>
      <textarea id="tasks-f-system_prompt" class="prompts-textarea" rows="5">${esc(instr.system_prompt || '')}</textarea>
      <label class="admin-modal-label" for="tasks-f-outputs">Outputs (comma-separated)</label>
      <input id="tasks-f-outputs" type="text" value="${esc((t.outputs || ['result']).join(', '))}" placeholder="result">
      <label class="admin-modal-label" for="tasks-f-format">Format</label>${sel('format', FORMATS, t.format || 'raw')}
      <label class="admin-modal-label" for="tasks-f-intended_output">Intended output</label>
      <input id="tasks-f-intended_output" type="text" value="${esc(t.intended_output || '')}" placeholder="what this task produces">
      <label class="admin-modal-label" for="tasks-f-pattern_affinity">Pattern affinity (comma-separated)</label>
      <input id="tasks-f-pattern_affinity" type="text" value="${esc((t.pattern_affinity || []).join(', '))}" placeholder="llm, loop, …">
      <label class="admin-modal-label" for="tasks-f-tags">Tags (comma-separated)</label>
      <input id="tasks-f-tags" type="text" value="${esc((t.tags || []).join(', '))}" placeholder="analysis, review">
      <label class="admin-modal-label" for="tasks-f-role_ref">Role ref (prompt id, optional)</label>
      <input id="tasks-f-role_ref" type="text" value="${esc(refs.role_ref || '')}" placeholder="role prompt id">
      <label class="admin-modal-label" for="tasks-f-template_ref">Template ref (prompt id, optional)</label>
      <input id="tasks-f-template_ref" type="text" value="${esc(refs.template_ref || '')}" placeholder="template id">`;
  }

  function _collectForm(prefix) {
    const g = n => document.getElementById(`${prefix}-${n}`);
    const csv = n => (g(n) ? g(n).value : '').split(',').map(s => s.trim()).filter(Boolean);
    const outputs = csv('outputs');
    return {
      name: (g('name') ? g('name').value : '').trim(),
      role: g('role') ? g('role').value : 'general',
      persona: (g('persona') ? g('persona').value : '').trim() || null,
      instructions: { system_prompt: g('system_prompt') ? g('system_prompt').value : '', blocks: [] },
      outputs: outputs.length ? outputs : ['result'],
      format: g('format') ? g('format').value : 'raw',
      intended_output: (g('intended_output') ? g('intended_output').value : '').trim() || null,
      pattern_affinity: csv('pattern_affinity'),
      tags: csv('tags'),
      refs: {
        role_ref: (g('role_ref') ? g('role_ref').value : '').trim() || null,
        template_ref: (g('template_ref') ? g('template_ref').value : '').trim() || null,
        hooks: [],
      },
      source: 'user',
    };
  }

  function _editForm(el, t) {
    el.innerHTML = `
      <div class="tasks-edit-form">${_formFields(t)}</div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button class="action-btn accent" data-action="tasks.save" data-id="${esc(t.id)}">Save</button>
        <button class="action-btn" data-action="tasks.cancel-edit">Cancel</button>
      </div>`;
  }

  // ── CRUD flows ────────────────────────────────────────────────────────
  function load() { return LibraryShell.reload('task'); }
  function select(id) { _editing = null; LibraryShell.select('task', id); }

  function edit(id) {
    const target = id || _selected();
    if (!target || _isDisc(target)) return;
    if (target !== _selected()) LibraryShell.select('task', target);
    _editing = target;
    LibraryShell.setSubnav('task', 'overview');
    LibraryShell.renderDetail('task');
  }
  function cancelEdit() { _editing = null; LibraryShell.renderDetail('task'); }

  async function saveEdit(id) {
    const target = id || _editing;
    if (!target) return;
    const body = _collectForm('tasks-f');
    try {
      const r = await Net.call(`/api/tasks/${encodeURIComponent(target)}`, {
        retries: 0,
        init: {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ ...body, id: target }),
        },
      });
      if (!r.ok) { Toast.danger('Save failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      _editing = null;
      Toast.success('Task saved', target);
      await load();
      select(target);
    } catch (e) { Toast.danger('Save failed', e.message); }
  }

  // Wizard-backed create (LB6 named A5 flow).
  function newTask() {
    LibraryWizard.open({
      title: 'New task schema',
      steps: { configure: (body, state) => _wizardForm(body, state) },
      validate: (step, state) => {
        if (step === 'configure') {
          const id = (state.values.id || '').trim();
          if (!_ID_RE.test(id)) return 'id must be alnum/_/- (≤80, alnum start)';
          if (!(state.values.name || '').trim()) return 'name is required';
        }
        return true;
      },
      submitLabel: 'Create',
      onSubmit: (state) => _submitCreate(state),
    });
  }

  function _wizardForm(bodyEl) {
    bodyEl.innerHTML = `
      <label class="admin-modal-label" for="tasks-w-id">Task id</label>
      <input id="tasks-w-id" data-wiz-key="id" type="text" placeholder="e.g. threat_summarizer" autocomplete="off">
      ${_formFieldsWiz()}`;
  }
  function _formFieldsWiz() {
    // Mirror the edit form fields but with data-wiz-key so LibraryWizard
    // collects them into state.values.
    const sel = (name, opts, cur) =>
      `<select data-wiz-key="${name}" class="model-select" style="width:100%">${
        opts.map(o => `<option value="${esc(o)}" ${o === cur ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
    return `
      <label class="admin-modal-label">Name</label>
      <input data-wiz-key="name" type="text" placeholder="Task name">
      <label class="admin-modal-label">Role</label>${sel('role', ROLES, 'general')}
      <label class="admin-modal-label">Persona</label>
      <input data-wiz-key="persona" type="text" placeholder="persona (icon key)">
      <label class="admin-modal-label">Instructions (system prompt)</label>
      <textarea data-wiz-key="system_prompt" class="prompts-textarea" rows="5" placeholder="You are…"></textarea>
      <label class="admin-modal-label">Outputs (comma-separated)</label>
      <input data-wiz-key="outputs" type="text" placeholder="result">
      <label class="admin-modal-label">Format</label>${sel('format', FORMATS, 'raw')}
      <label class="admin-modal-label">Intended output</label>
      <input data-wiz-key="intended_output" type="text" placeholder="what this task produces">
      <label class="admin-modal-label">Pattern affinity (comma-separated)</label>
      <input data-wiz-key="pattern_affinity" type="text" placeholder="llm, loop, …">
      <label class="admin-modal-label">Tags (comma-separated)</label>
      <input data-wiz-key="tags" type="text" placeholder="analysis, review">
      <label class="admin-modal-label">Role ref (prompt id, optional)</label>
      <input data-wiz-key="role_ref" type="text" placeholder="role prompt id">
      <label class="admin-modal-label">Template ref (prompt id, optional)</label>
      <input data-wiz-key="template_ref" type="text" placeholder="template id">`;
  }

  function _schemaFromValues(v) {
    const csv = k => (v[k] || '').split(',').map(s => s.trim()).filter(Boolean);
    const outputs = csv('outputs');
    return {
      id: (v.id || '').trim(),
      name: (v.name || '').trim(),
      persona: (v.persona || '').trim() || null,
      role: v.role || 'general',
      instructions: { system_prompt: v.system_prompt || '', blocks: [] },
      outputs: outputs.length ? outputs : ['result'],
      format: v.format || 'raw',
      intended_output: (v.intended_output || '').trim() || null,
      pattern_affinity: csv('pattern_affinity'),
      tags: csv('tags'),
      refs: {
        role_ref: (v.role_ref || '').trim() || null,
        template_ref: (v.template_ref || '').trim() || null,
        hooks: [],
      },
      source: 'user',
    };
  }

  async function _submitCreate(state) {
    const schema = _schemaFromValues(state.values);
    try {
      const r = await Net.call('/api/tasks', {
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
      return { ok: true, message: `Task '${schema.id}' created.` };
    } catch (e) { return { ok: false, detail: e.message }; }
  }

  async function remove(id) {
    const target = id || _selected();
    if (!target) return;
    const ok = await Confirm.ask({
      title: 'Delete task', body: `Delete task schema "${target}"?`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    try {
      const r = await Net.call(`/api/tasks/${encodeURIComponent(target)}`, {
        retries: 0, init: { method: 'DELETE', headers: _headers() },
      });
      if (!r.ok) { Toast.danger('Delete failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      LibraryShell.select('task', null);
      Toast.success('Task deleted', target);
      await load();
    } catch (e) { Toast.danger('Delete failed', e.message); }
  }

  async function render(id) {
    const target = id || _selected();
    if (!target || _isDisc(target)) return;
    try {
      const r = await Net.call(`/api/tasks/${encodeURIComponent(target)}/render`, {
        retries: 0,
        init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) },
      });
      if (!r.ok) { Toast.danger('Render failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      _renderOut = { id: target, system: r.data.system, user: r.data.user, warnings: r.data.warnings || [] };
      LibraryShell.refreshSection('task', 'overview');
    } catch (e) { Toast.danger('Render failed', e.message); }
  }

  function test(id) {
    const target = id || _selected();
    if (!target || _isDisc(target)) return;
    if (target !== _selected()) select(target);
    LibraryShell.setSubnav('task', 'test');
  }

  // ── Discovery (operator-triggered refresh; reads never fetch) ─────────
  async function loadDiscover() {
    try {
      const r = await Net.call('/api/tasks/discover', { silent: true, retries: 0 });
      if (r.ok) _discover = r.data || null;
    } catch (_) { /* stays null */ }
    LibraryShell.renderSidebar('task');
  }

  async function refreshDiscover() {
    const btn = document.getElementById('tasks-refresh-discover');
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
    try {
      const r = await Net.call('/api/tasks/discover/refresh', {
        retries: 0, init: { method: 'POST', headers: _headers() },
      });
      if (!r.ok) { Toast.danger('Discovery refresh failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      await loadDiscover();
      const n = ((_discover && _discover.records) || []).length;
      Toast.success('Task catalog refreshed', `${n} remote record${n === 1 ? '' : 's'}`);
    } catch (e) {
      Toast.danger('Discovery refresh failed', e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '⟳ Discover'; }
    }
  }

  async function install(discId) {
    if (!discId) return;
    try {
      const r = await Net.call(`/api/tasks/discover/${encodeURIComponent(discId)}/install`, {
        retries: 0,
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({}) },
      });
      if (!r.ok) { Toast.danger('Install failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
      Toast.success('Task installed', discId);
      await load();
      await loadDiscover();
      select(discId);
    } catch (e) { Toast.danger('Install failed', e.message); }
  }

  // ── Composer bench feed ───────────────────────────────────────────────
  // Append library task rows to #df-palette under a single "Library" divider
  // AFTER the 13 statics, deduped by key (statics win). Fail-soft: any error
  // — network, 404 (tasks router absent), empty list — leaves the palette
  // byte-identical to pre-LB6. Idempotent (guards on the divider).
  async function fetchComposerTasks() {
    const palette = document.getElementById('df-palette');
    if (!palette || palette.querySelector('[data-lib-divider]')) return;
    let tasks = [];
    try {
      const r = await Net.call('/api/tasks', { silent: true, retries: 0 });
      if (!r.ok) return;                    // fail-soft — palette untouched
      tasks = r.data || [];
    } catch (_) { return; }
    if (!tasks.length) return;              // nothing to add → identical palette
    const staticKeys = new Set(
      Array.from(palette.querySelectorAll('.df-palette-item[data-template-key]'))
        .map(el => el.dataset.templateKey)
    );
    dfLibraryTemplates.clear();
    const frag = document.createDocumentFragment();
    let any = false;
    tasks.forEach(t => {
      if (!t.id || staticKeys.has(t.id)) return;   // dedupe — statics win
      const rec = mapSchema(t);
      dfLibraryTemplates.set(rec.key, rec);
      frag.appendChild(_paletteRow(rec));
      any = true;
    });
    if (!any) return;                       // all deduped → identical palette
    const divider = document.createElement('div');
    divider.className = 'df-palette-divider';
    divider.setAttribute('data-lib-divider', '1');
    // Self-contained styling (no app.css edit — outside the LB6 file set).
    divider.style.cssText = 'margin:10px 4px 4px;padding-top:8px;border-top:1px solid var(--border);' +
      'font-family:var(--mono);font-size:0.58rem;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-muted)';
    divider.textContent = 'Library';
    palette.appendChild(divider);
    palette.appendChild(frag);
  }

  function _paletteRow(rec) {
    const persona = rec.persona || 'general';
    const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const tone = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');
    const item = document.createElement('div');
    item.className = 'df-palette-item df-library-task';
    item.draggable = true;
    item.dataset.persona = persona;
    // Library rows carry their OWN action id — the static rows'
    // bench.inspect-template handler is untouched.
    item.dataset.action = 'bench.inspect-library-task';
    item.dataset.taskId = rec.key;
    item.innerHTML = `
      <span class="df-palette-icon tone-${esc(tone)}">${iconSvg}</span>
      <span class="df-palette-titleblock">
        <span class="df-palette-label">${esc(rec.name)}</span>
        <span class="df-palette-role">${esc(rec.role)}</span>
      </span>`;
    // Distinct drag MIME so the canvas drop handler routes library tasks to
    // dfAddNodeFromLibraryTask, never the static df-template path.
    item.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('application/df-library-task', rec.key);
      e.dataTransfer.effectAllowed = 'move';
    });
    return item;
  }

  // ── Panel API ─────────────────────────────────────────────────────────
  function activate() {
    if (!_mounted) {
      _mounted = true;
      const p = LibraryShell.mount('task', 'tasks-shell');
      loadDiscover();
      return p;
    }
    loadDiscover();
    return LibraryShell.reload('task');
  }

  // ── Delegated actions ─────────────────────────────────────────────────
  // Every task action carries its OWN id (not the generic lib.action verb
  // dispatcher), so delete rides tasks.delete → remove() with its own Confirm.
  Actions.click({
    'tasks.select': el => select(el.dataset.id),
    'tasks.new': () => newTask(),
    // create-save/create-cancel are the wizard's submit/cancel by another
    // name (the create flow is wizard-backed; these keep the action grammar
    // complete for any inline-create surface).
    'tasks.create-save': () => LibraryWizard.submit(),
    'tasks.create-cancel': () => LibraryWizard.cancel(),
    'tasks.edit': el => edit(el.dataset.id),
    'tasks.save': el => saveEdit(el.dataset.id),
    'tasks.cancel-edit': () => cancelEdit(),
    'tasks.delete': el => remove(el.dataset.id),
    'tasks.render': el => render(el.dataset.id),
    'tasks.test': el => test(el.dataset.id),
    'tasks.open-ref': el => LibraryShell.open('prompt', el.dataset.ref),
    'tasks.discover-refresh': () => refreshDiscover(),
    'tasks.install': el => install(el.dataset.discId),
  });

  return {
    activate, load, select, edit, saveEdit, cancelEdit, newTask, remove,
    render, test, refreshDiscover, install, loadDiscover,
    fetchComposerTasks, libraryTask, mapById, mapSchema, adapter,
  };
})();
