// runs/schedules-view.js — Schedules rail + scheduled-run wizard (Operate U8).
//
// The Runs tab's left rail gains a Runs|Schedules segmented toggle. Schedules
// mode mounts a LibraryShell adapter (kind:'schedule', auth:'optional' — the
// renderLock rule forbids 'admin' inside #tab-runs, which would wipe the host
// tab). Reads ride the scope-authed GET routes; writes carry explicit
// AdminAuth headers and, on a 401, render a SCOPED lock row inside the rail
// detail pane — never AdminAuth.renderLock, which replaces the whole tab.
//
// The wizard is the first live LibraryWizard consumer: Workflow → Configure →
// Confirm (secrets skipped). Seed fields derive from the selected workflow's
// `seed.*` step inputs (F13 — there is no `expects` field); a validated JSON
// textarea is the zero-declared fallback. Submit rides the wizard's sanctioned
// post() with AdminAuth.authHeaders() (F24). Times are UTC on the wire; the UI
// shows the operator's local time alongside an explicit "stored as UTC" note.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from '../library/shell.js';
import { LibraryWizard } from '../library/wizard.js';

export const SchedulesView = (function () {
  const KIND = 'schedule';
  const SHELL_HOST = 'schedules-shell';
  const CATEGORIES = ['Research', 'Report', 'Maintenance', 'Task'];
  const WEEKDAYS = [
    ['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'],
    ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday'],
  ];

  let _rows = [];                       // GET /api/schedules → to_row[]
  const _detailCache = Object.create(null);   // id → detail promise (row + history)
  const _defCache = Object.create(null);      // workflow_id → full definition promise
  let _mounted = false;
  let _railMode = 'runs';
  let _editId = null;                   // wizard PUT target (null ⇒ create/POST)

  // ── Time helpers (UTC wire → local display) ─────────────────────────────
  // datetime.utcnow().isoformat() carries no offset — parse it as UTC.
  function _asUtc(iso) {
    if (!iso) return null;
    const s = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z';
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  function _localWhen(iso) {
    const d = _asUtc(iso);
    if (!d) return '—';
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  // Local time-of-day for a UTC "HH:MM" cadence anchor.
  function _localHHMM(hhmm) {
    if (!hhmm || !/^\d{1,2}:\d{2}$/.test(hhmm)) return '';
    const [hh, mm] = hhmm.split(':').map(Number);
    const now = new Date();
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hh, mm));
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  // Human cadence line: UTC form + the operator's local equivalent (F7).
  function _cadenceLine(cad) {
    if (!cad) return '—';
    if (cad.kind === 'interval') {
      const mins = Math.round((cad.every_seconds || 0) / 60);
      return `every ${mins} min · stored as UTC`;
    }
    const local = _localHHMM(cad.at);
    const localNote = local ? ` (${local} your time)` : '';
    if (cad.kind === 'daily') return `daily at ${esc(cad.at || '')} UTC${localNote}`;
    return `weekly on ${esc(cad.weekday || '?')} at ${esc(cad.at || '')} UTC${localNote}`;
  }

  // ── Data access ─────────────────────────────────────────────────────────
  async function _loadList() {
    const r = await LibraryShell.fetch(KIND, '/api/schedules');
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _rows = (r.data && r.data.schedules) || [];
    // A reload invalidates cached details (status/history moved on).
    for (const k of Object.keys(_detailCache)) delete _detailCache[k];
  }
  function _fetchDetail(id) {
    if (_detailCache[id]) return _detailCache[id];
    _detailCache[id] = (async () => {
      const r = await LibraryShell.fetch(KIND, `/api/schedules/${encodeURIComponent(id)}`);
      if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
      return r.data;
    })();
    return _detailCache[id];
  }
  function _fetchDef(workflowId) {
    if (_defCache[workflowId]) return _defCache[workflowId];
    _defCache[workflowId] = Net.getJson('/api/workflows/' + encodeURIComponent(workflowId))
      .catch(() => null);
    return _defCache[workflowId];
  }
  function _row(id) { return _rows.find(r => r.id === id) || null; }

  // Seed keys: declared context.inputs ∪ step inputs with the `seed.` prefix
  // (the shared derivation WorkflowIndex/RunsTab already use — F13).
  function _deriveSeedKeys(def) {
    if (!def) return [];
    const declared = (((def.context && def.context.inputs) || [])
      .map(x => (typeof x === 'string' ? x : (x && x.key))).filter(Boolean));
    const inferred = (def.steps || []).flatMap(s => (s.inputs || [])
      .filter(i => typeof i === 'string' && i.startsWith('seed.')).map(i => i.slice(5)));
    return [...new Set([...declared, ...inferred])];
  }

  // ── Scoped write-401 lock row (never a tab wipe) ────────────────────────
  function _detailEl() { return document.getElementById('lib-schedule-detail'); }
  function _renderLockRow(msg) {
    const host = _detailEl();
    if (!host) { Toast.warn('Sign in required', msg || 'Master key required for this action.'); return; }
    if (host.querySelector('.sched-lock-row')) return;
    const row = document.createElement('div');
    row.className = 'sched-lock-row';
    // No data-panel: admin.sign-in with an empty panel reloads on success
    // instead of renderLock-wiping #tab-runs.
    row.innerHTML = `<span class="sched-lock-icon" aria-hidden="true">🔒</span>
      <span class="sched-lock-msg">${esc(msg || 'Master key required to modify schedules.')}</span>
      <button type="button" class="action-btn xs" data-action="admin.sign-in">Sign in</button>`;
    host.insertBefore(row, host.firstChild);
  }
  function _authHeaders() {
    return (window.AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }

  // ── Write verbs ─────────────────────────────────────────────────────────
  async function _write(url, method) {
    return Net.call(url, {
      retries: 0,
      init: { method, headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()) },
    });
  }
  async function _delete(id) {
    const ok = await Confirm.ask({
      title: 'Delete schedule', body: `Delete schedule "${id}"? Dispatch history is retained.`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    const r = await _write(`/api/schedules/${encodeURIComponent(id)}`, 'DELETE');
    if (r.ok) { await LibraryShell.reload(KIND); Toast.success('Deleted', `Schedule "${id}" removed.`); return; }
    if (r.status === 401) return _renderLockRow('Sign in as admin to delete schedules.');
    Toast.danger('Delete failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }
  async function _toggleEnabled(id) {
    const row = _row(id);
    if (!row) return;
    const verb = row.enabled ? 'disable' : 'enable';
    const r = await _write(`/api/schedules/${encodeURIComponent(id)}/${verb}`, 'POST');
    if (r.ok) { await LibraryShell.reload(KIND); LibraryShell.select(KIND, id); return; }
    if (r.status === 401) return _renderLockRow('Sign in as admin to enable or disable schedules.');
    Toast.danger('Toggle failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }
  async function _runNow(id) {
    const r = await _write(`/api/schedules/${encodeURIComponent(id)}/run-now`, 'POST');
    if (r.ok && r.data && r.data.run_id) { _pivotRun(r.data.run_id); return; }
    if (r.status === 401) return _renderLockRow('Sign in as admin to trigger a run.');
    Toast.danger('Run failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }

  // ── Cross-surface pivots ────────────────────────────────────────────────
  function _pivotRun(runId) {
    if (!runId) return;
    setRailMode('runs');
    try { if (typeof window.switchTab === 'function') window.switchTab('runs'); } catch (_) {}
    try { if (window.RunsTab && RunsTab.select) RunsTab.select(runId); } catch (_) {}
    try { location.hash = '#/runs/' + runId; } catch (_) {}
  }

  // ── LibraryShell adapter ────────────────────────────────────────────────
  const adapter = {
    kind: KIND,
    title: 'Schedules',
    tabId: 'tab-runs',
    auth: 'optional',           // NEVER 'admin' — renderLock would wipe #tab-runs
    emptyText: 'No schedules yet. Use + Schedule to create one.',
    emptyDetailText: 'Select a schedule to see its cadence, dispatch history, and controls.',
    emptyDetailLabel: '// SCHEDULE',
    load: _loadList,
    list() {
      return _rows.map(s => {
        const chips = [];
        if (s.workspace) chips.push({ label: `▢ ${s.workspace}`, cls: 'sched-ws-chip' });
        if (s.repeated_overlap) chips.push({ label: `overlap×${s.repeated_overlap}`, cls: 'sched-warn-chip' });
        const next = _localWhen(s.next_fire_at);
        return {
          id: s.id,
          title: s.name || s.id,
          meta: `${s.cadence_human || _cadenceLine(s.cadence)} · next ${next}`,
          group: s.category || 'Task',
          status: s.last_status || '',
          chips,
          dot: {
            cls: s.enabled ? 'ok' : 'off',
            title: s.enabled ? 'enabled' : 'disabled',
          },
        };
      });
    },
    detail(id) {
      return {
        sections: {
          overview: (el) => _renderOverview(el, id),
          relations: (el) => _renderRelations(el, id),
          test: (el) => _renderTest(el, id),
        },
      };
    },
    sectionLabels: { relations: 'History', test: 'Run' },
    actions(id) {
      const row = _row(id);
      const enabled = row && row.enabled;
      return [
        { verb: 'test', label: 'Run now', action: 'sched.run-now', accent: true, data: { schedId: id } },
        { verb: 'edit', label: 'Edit', action: 'sched.edit', data: { schedId: id } },
        { verb: 'edit', label: enabled ? 'Disable' : 'Enable', action: 'sched.toggle', data: { schedId: id } },
        { verb: 'delete', label: 'Delete', action: 'sched.delete', danger: true, data: { schedId: id } },
      ];
    },
    onSelect(id) { _fetchDetail(id); },
  };
  LibraryShell.register(adapter);

  // ── Detail sections ─────────────────────────────────────────────────────
  async function _renderOverview(el, id) {
    let d;
    try { d = await _fetchDetail(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    const seedKeys = Object.keys(d.seed || {});
    const seedPreview = seedKeys.length
      ? seedKeys.map(k => `<code>${esc(k)}</code>=${esc(String(d.seed[k]))}`).join('  ')
      : '<span style="color:var(--text-muted)">(none)</span>';
    el.innerHTML = `
      <div class="sched-ov">
        <div class="sched-ov-toggle">
          <span class="lib-dot ${d.enabled ? 'ok' : 'off'}"></span>
          <span>${d.enabled ? 'Enabled' : 'Disabled'}</span>
          <button type="button" class="action-btn xs" data-action="sched.toggle" data-sched-id="${esc(id)}">
            ${d.enabled ? 'Disable' : 'Enable'}</button>
        </div>
        <div class="sched-kv"><span>Cadence</span><span>${_cadenceLine(d.cadence)}</span></div>
        <div class="sched-kv"><span>Category</span><span>${esc(d.category || 'Task')}</span></div>
        <div class="sched-kv"><span>Workflow</span>
          <span><button type="button" class="btn-unstyled sched-wf-link" data-action="sched.open-workflow"
            data-workflow-id="${esc(d.workflow_id)}">${esc(d.workflow_id)}</button></span></div>
        <div class="sched-kv"><span>Workspace</span><span>${d.workspace ? esc(d.workspace) : '<span style="color:var(--text-muted)">(unbound)</span>'}</span></div>
        <div class="sched-kv"><span>Next fire</span><span>${_localWhen(d.next_fire_at)} <span style="color:var(--text-muted)">(stored as UTC)</span></span></div>
        <div class="sched-kv"><span>Last run</span><span>${d.last_status ? esc(d.last_status) : '—'}${d.last_dispatched_at ? ` · ${_localWhen(d.last_dispatched_at)}` : ''}</span></div>
        <div class="sched-kv"><span>Failures</span><span>${d.consecutive_failures || 0} / ${d.max_consecutive_failures || 5}${d.repeated_overlap ? ` · overlap×${d.repeated_overlap} (degraded)` : ''}</span></div>
        <div class="sched-kv"><span>Seed</span><span class="sched-seed">${seedPreview}</span></div>
      </div>`;
  }

  const _EVENT_LABEL = {
    dispatched: 'Dispatched', error: 'Error', skipped_missed: 'Skipped (missed window)',
    skipped_overlap_start: 'Overlap started', skipped_overlap_end: 'Overlap cleared',
    overlap_takeover: 'Zombie takeover', auto_disabled: 'Auto-disabled',
  };
  async function _renderRelations(el, id) {
    let d;
    try { d = await _fetchDetail(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    const hist = (d.history || []).slice(0, 20);
    if (!hist.length) { el.innerHTML = '<div class="model-empty">No dispatch history yet.</div>'; return; }
    el.innerHTML = `<div class="sched-hist">${hist.map(h => {
      const label = _EVENT_LABEL[h.event] || h.event;
      const when = _localWhen(h.ts);
      const runId = h.run_id;
      const inner = `<span class="sched-hist-ev ev-${esc(h.event)}">${esc(label)}</span>
        <span class="sched-hist-when">${when}</span>
        ${h.trigger ? `<span class="sched-hist-trig">${esc(h.trigger)}</span>` : ''}
        ${runId ? `<code class="sched-hist-run">${esc(runId)}</code>` : ''}`;
      // dispatched rows pivot to the run they launched.
      return runId && h.event === 'dispatched'
        ? `<button type="button" class="btn-unstyled sched-hist-row pivot" data-action="sched.pivot-run" data-run-id="${esc(runId)}">${inner}</button>`
        : `<div class="sched-hist-row">${inner}</div>`;
    }).join('')}</div>`;
  }
  function _renderTest(el, id) {
    el.innerHTML = `<div class="sched-test">
      <p style="color:var(--text-muted);font-size:0.72rem">Trigger this schedule immediately. A run-now dispatch does not shift the cadence clock and does not count toward auto-disable.</p>
      <button type="button" class="action-btn accent" data-action="sched.run-now" data-sched-id="${esc(id)}">Run now ▶</button>
    </div>`;
  }

  // ── Rail mount + mode toggle ────────────────────────────────────────────
  function mount() {
    if (_mounted) { LibraryShell.reload(KIND); return; }
    _mounted = true;
    LibraryShell.mount(KIND, SHELL_HOST);
  }
  function setRailMode(mode) {
    _railMode = mode === 'schedules' ? 'schedules' : 'runs';
    const runsWrap = document.getElementById('runs-mode-runs');
    const schedWrap = document.getElementById('runs-mode-schedules');
    const newBtn = document.getElementById('runs-schedule-new');
    if (runsWrap) runsWrap.hidden = _railMode !== 'runs';
    if (schedWrap) schedWrap.hidden = _railMode !== 'schedules';
    if (newBtn) newBtn.hidden = _railMode !== 'schedules';
    document.querySelectorAll('.runs-rail-mode').forEach(b => {
      const on = b.dataset.mode === _railMode;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    if (_railMode === 'schedules') mount();
  }

  // ── Wizard ──────────────────────────────────────────────────────────────
  // Source step: workflow radio list from /api/workflow-index.
  function _renderSourceStep(bodyEl, state) {
    bodyEl.innerHTML = '<div class="model-empty">Loading workflows…</div>';
    Net.getJson('/api/workflow-index').then(data => {
      const wfs = (data && data.workflows) || [];
      // A prefilled-but-unlisted workflow (e.g. just saved in the Composer)
      // still gets a row so it can be preselected.
      const sel = state.values.workflow_id;
      if (sel && !wfs.some(w => w.id === sel)) wfs.unshift({ id: sel, name: sel, category: '' });
      // A single hidden input carries workflow_id into state.values — the
      // wizard's _collect reads EVERY [data-wiz-key], so per-radio keys would
      // let the last radio win. The radios drive this hidden input on change.
      bodyEl.innerHTML = `
        <div class="admin-modal-sub">Choose the workflow this schedule runs.</div>
        <input type="hidden" id="sched-wf-id" data-wiz-key="workflow_id" value="${esc(sel || '')}">
        <div class="sched-wf-list">${wfs.map(w => `
          <label class="sched-wf-opt">
            <input type="radio" name="sched-wf" value="${esc(w.id)}" data-action="sched.wiz-pick-wf"
              data-wf-id="${esc(w.id)}" ${sel === w.id ? 'checked' : ''}>
            <span class="sched-wf-name">${esc(w.name || w.id)}</span>
            <span class="sched-wf-id">${esc(w.id)}</span>
          </label>`).join('') || '<div class="model-empty">No workflows available.</div>'}
        </div>`;
    }).catch(e => { bodyEl.innerHTML = `<div class="model-empty">Couldn't load workflows: ${esc(e.message)}</div>`; });
  }

  function _cadenceVisibility(kind) {
    const body = document.getElementById('lib-wizard-body');
    if (!body) return;
    const show = (cls, on) => body.querySelectorAll(cls).forEach(el => { el.hidden = !on; });
    show('.sched-cad-interval', kind === 'interval');
    show('.sched-cad-clock', kind === 'daily' || kind === 'weekly');
    show('.sched-cad-weekday', kind === 'weekly');
  }

  // Configure step: name, category, workspace, seed fields, cadence block.
  function _renderConfigStep(bodyEl, state) {
    const v = state.values;
    const kind = v.cadence_kind || 'daily';
    bodyEl.innerHTML = `
      <label class="admin-modal-label" for="sched-name">Name</label>
      <input id="sched-name" class="chat-input" data-wiz-key="name" value="${esc(v.name || '')}" placeholder="Nightly research digest" autocomplete="off">

      <label class="admin-modal-label" for="sched-category">Category</label>
      <input id="sched-category" class="chat-input" data-wiz-key="category" list="sched-cat-list" value="${esc(v.category || 'Task')}" autocomplete="off">
      <datalist id="sched-cat-list">${CATEGORIES.map(c => `<option value="${esc(c)}">`).join('')}</datalist>

      <label class="admin-modal-label" for="sched-workspace">Workspace <span style="color:var(--text-muted);font-weight:400">(optional)</span></label>
      <select id="sched-workspace" class="chat-input" data-wiz-key="workspace">
        <option value="">(none)</option>
      </select>

      <div class="sched-seed-fields" id="sched-seed-fields">
        <div class="model-empty">Loading seed inputs…</div>
      </div>

      <label class="admin-modal-label">Cadence <span style="color:var(--text-muted);font-weight:400">— times stored as UTC</span></label>
      <select id="sched-cadence-kind" class="chat-input" data-wiz-key="cadence_kind" data-action="sched.wiz-cadence-kind">
        <option value="interval" ${kind === 'interval' ? 'selected' : ''}>Interval</option>
        <option value="daily" ${kind === 'daily' ? 'selected' : ''}>Daily</option>
        <option value="weekly" ${kind === 'weekly' ? 'selected' : ''}>Weekly</option>
      </select>
      <div class="sched-cad-interval" ${kind === 'interval' ? '' : 'hidden'}>
        <label class="admin-modal-label" for="sched-every">Every (minutes, ≥5)</label>
        <input id="sched-every" type="number" min="5" step="1" class="chat-input" data-wiz-key="every_minutes" value="${esc(v.every_minutes || '60')}">
      </div>
      <div class="sched-cad-clock" ${kind === 'daily' || kind === 'weekly' ? '' : 'hidden'}>
        <label class="admin-modal-label" for="sched-at">At (HH:MM UTC)</label>
        <input id="sched-at" type="time" class="chat-input" data-wiz-key="at" value="${esc(v.at || '09:00')}">
        <div class="admin-modal-sub" id="sched-at-local"></div>
      </div>
      <div class="sched-cad-weekday" ${kind === 'weekly' ? '' : 'hidden'}>
        <label class="admin-modal-label" for="sched-weekday">Weekday</label>
        <select id="sched-weekday" class="chat-input" data-wiz-key="weekday">
          ${WEEKDAYS.map(([val, lbl]) => `<option value="${val}" ${v.weekday === val ? 'selected' : ''}>${lbl}</option>`).join('')}
        </select>
      </div>`;

    // Populate the workspace selector (optional; silent on failure).
    Net.getJson('/api/workspaces').then(data => {
      const sel = document.getElementById('sched-workspace');
      if (!sel) return;
      (data && data.workspaces || []).forEach(ws => {
        const opt = document.createElement('option');
        opt.value = ws.name; opt.textContent = ws.name;
        if (v.workspace === ws.name) opt.selected = true;
        sel.appendChild(opt);
      });
    }).catch(() => {});

    // Derive + render seed fields for the chosen workflow.
    _renderSeedFields(v.workflow_id, v);
    _updateLocalNote();
  }

  function _renderSeedFields(workflowId, v) {
    const host = document.getElementById('sched-seed-fields');
    if (!host) return;
    if (!workflowId) { host.innerHTML = ''; return; }
    _fetchDef(workflowId).then(def => {
      const keys = _deriveSeedKeys(def);
      if (keys.length) {
        host.innerHTML = `<label class="admin-modal-label">Seed inputs</label>` + keys.map(k => `
          <div class="sched-seed-row">
            <label class="admin-modal-sub" for="sched-seed-${esc(k)}">${esc(k)}</label>
            <input id="sched-seed-${esc(k)}" class="chat-input" data-wiz-key="seed.${esc(k)}"
              value="${esc(v['seed.' + k] || '')}" placeholder="value for seed.${esc(k)}" autocomplete="off">
          </div>`).join('');
      } else {
        // Zero-declared fallback — a validated JSON textarea (F13).
        host.innerHTML = `<label class="admin-modal-label">Seed (JSON) — this workflow declares no seed keys</label>
          <textarea class="chat-input" data-wiz-key="seed_json" spellcheck="false"
            style="min-height:80px;resize:vertical">${esc(v.seed_json || '{}')}</textarea>`;
      }
    });
  }

  function _updateLocalNote() {
    const at = document.getElementById('sched-at');
    const note = document.getElementById('sched-at-local');
    if (!at || !note) return;
    const local = _localHHMM(at.value);
    note.textContent = local ? `≈ ${local} your local time` : '';
  }

  function _confirmStep(bodyEl, state) {
    const v = state.values;
    const cad = _buildCadence(v);
    const seed = _buildSeed(v);
    const seedStr = Object.keys(seed).length
      ? Object.entries(seed).map(([k, val]) => `${esc(k)}=${esc(String(val))}`).join(', ')
      : '(none)';
    bodyEl.innerHTML = `
      <div class="admin-modal-sub">Review, then ${_editId ? 'update' : 'create'} the schedule.</div>
      <div class="sched-confirm">
        <div><span>Name</span><span>${esc(v.name || '')}</span></div>
        <div><span>Workflow</span><span>${esc(v.workflow_id || '')}</span></div>
        <div><span>Category</span><span>${esc(v.category || 'Task')}</span></div>
        <div><span>Workspace</span><span>${v.workspace ? esc(v.workspace) : '(unbound)'}</span></div>
        <div><span>Cadence</span><span>${_cadenceLine(cad)}</span></div>
        <div><span>Seed</span><span>${seedStr}</span></div>
      </div>
      <div id="lib-wizard-result" style="margin-top:10px"></div>`;
  }

  function _buildCadence(v) {
    const kind = v.cadence_kind || 'daily';
    if (kind === 'interval') {
      return { kind: 'interval', every_seconds: Math.max(300, Math.round(Number(v.every_minutes || 5) * 60)) };
    }
    const cad = { kind, at: v.at || '' };
    if (kind === 'weekly') cad.weekday = v.weekday || 'mon';
    return cad;
  }
  function _buildSeed(v) {
    const seed = {};
    Object.keys(v).forEach(k => {
      if (k.startsWith('seed.')) {
        const val = v[k];
        if (val != null && String(val).trim() !== '') seed[k.slice(5)] = val;
      }
    });
    if (v.seed_json != null && String(v.seed_json).trim() !== '') {
      try {
        const parsed = JSON.parse(v.seed_json);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) Object.assign(seed, parsed);
      } catch (_) { /* validated in flow.validate */ }
    }
    return seed;
  }

  function _validate(stepId, state) {
    const v = state.values;
    if (stepId === 'source') {
      if (!v.workflow_id) return 'Pick a workflow to schedule.';
      return true;
    }
    if (stepId === 'configure') {
      if (!v.name || !v.name.trim()) return 'Give the schedule a name.';
      const kind = v.cadence_kind || 'daily';
      if (kind === 'interval') {
        if (!(Number(v.every_minutes) >= 5)) return 'Interval must be at least 5 minutes.';
      } else {
        if (!/^\d{1,2}:\d{2}$/.test(v.at || '')) return 'Enter a valid time (HH:MM).';
        if (kind === 'weekly' && !v.weekday) return 'Pick a weekday.';
      }
      if (v.seed_json != null && String(v.seed_json).trim() !== '') {
        try {
          const p = JSON.parse(v.seed_json);
          if (!p || typeof p !== 'object' || Array.isArray(p)) return 'Seed JSON must be a JSON object.';
        } catch (_) { return 'Seed JSON is not valid JSON.'; }
      }
      return true;
    }
    return true;
  }

  async function _onSubmit(state, { post }) {
    const v = state.values;
    const body = {
      name: (v.name || '').trim(),
      category: (v.category || 'Task').trim() || 'Task',
      enabled: true,
      workflow_id: v.workflow_id,
      seed: _buildSeed(v),
      workspace: v.workspace || null,
      cadence: _buildCadence(v),
    };
    let r;
    if (_editId) {
      r = await Net.call(`/api/schedules/${encodeURIComponent(_editId)}`, {
        retries: 0,
        init: {
          method: 'PUT',
          headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()),
          body: JSON.stringify(body),
        },
      });
    } else {
      r = await post('/api/schedules', body, _authHeaders());
    }
    if (r.ok) {
      const newId = (r.data && r.data.id) || _editId;
      await LibraryShell.reload(KIND);
      if (newId) LibraryShell.select(KIND, newId);
      return { ok: true, message: _editId ? 'Schedule updated.' : 'Schedule created.' };
    }
    if (r.status === 401) return { ok: false, detail: 'Sign in as admin to save schedules.' };
    const d = r.data;
    return { ok: false, detail: (d && (d.detail || d.message)) || r.error || 'Save failed.' };
  }

  // prefill: {workflow_id?}, {workspace?}, or a full schedule row (edit).
  function openScheduleWizard(prefill) {
    prefill = prefill || {};
    _editId = (prefill.id && /^sched_/.test(prefill.id)) ? prefill.id : null;
    const values = {};
    if (prefill.workflow_id) values.workflow_id = prefill.workflow_id;
    if (prefill.workspace) values.workspace = prefill.workspace;
    if (prefill.name) values.name = prefill.name;
    if (prefill.category) values.category = prefill.category;
    if (prefill.cadence) {
      const c = prefill.cadence;
      values.cadence_kind = c.kind;
      if (c.kind === 'interval') values.every_minutes = String(Math.round((c.every_seconds || 300) / 60));
      if (c.at) values.at = c.at;
      if (c.weekday) values.weekday = c.weekday;
    }
    if (prefill.seed && typeof prefill.seed === 'object') {
      Object.entries(prefill.seed).forEach(([k, val]) => { values['seed.' + k] = val; });
    }
    LibraryWizard.open({
      title: _editId ? 'Edit schedule' : 'Schedule a workflow',
      submitLabel: _editId ? 'Update schedule' : 'Create schedule',
      state: { values },
      steps: {
        source: _renderSourceStep,
        configure: _renderConfigStep,
        confirm: _confirmStep,
      },
      validate: _validate,
      onSubmit: _onSubmit,
    });
  }

  // ── Delegated actions ───────────────────────────────────────────────────
  Actions.click({
    'runs.rail-mode': el => setRailMode(el.dataset.mode),
    'runs.schedule-new': () => openScheduleWizard(),
    'sched.run-now': el => _runNow(el.dataset.schedId || el.dataset.id),
    'sched.edit': el => { const row = _row(el.dataset.schedId || el.dataset.id); if (row) openScheduleWizard(row); },
    'sched.toggle': el => _toggleEnabled(el.dataset.schedId || el.dataset.id),
    'sched.delete': el => _delete(el.dataset.schedId || el.dataset.id),
    'sched.pivot-run': el => _pivotRun(el.dataset.runId),
    'sched.open-workflow': el => {
      const wid = el.dataset.workflowId;
      if (wid && window.WorkflowIndex && WorkflowIndex.deepDive) { try { WorkflowIndex.deepDive(wid); } catch (_) {} }
    },
  });
  Actions.change({
    'sched.wiz-cadence-kind': el => { _cadenceVisibility(el.value); },
    'sched.wiz-pick-wf': el => {
      const hidden = document.getElementById('sched-wf-id');
      if (hidden) hidden.value = el.dataset.wfId || el.value || '';
    },
  });
  // Live local-time note as the operator types the UTC time.
  document.addEventListener('input', e => {
    if (e.target && e.target.id === 'sched-at') _updateLocalNote();
  });

  return { adapter, mount, setRailMode, openScheduleWizard, railMode: () => _railMode };
})();
