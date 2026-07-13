// library/projects-board.js — Projects tab segment controller (U3).
//
// Owns the Board · Backlog · Timeline segments of #tab-projects and the
// per-task drawer. The Kanban board panel (#kanban-panel) is relocated into
// #tab-projects by the main.js DOMContentLoaded relocator; init() re-adopts
// it into the Board segment (#projects-seg-board) so segment switching hides
// it with the rest of the Board view. Docs live in projects-docs.js.
//
// Data source is the SAME per-project task log the board reads
// (/api/projects/{id}/tasks). The drawer requests ?history=1 for the status
// trail and /runs for linked runs. Column enum: backlog·todo·doing·review·done.

import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Kanban } from './kanban.js';
import { ProjectsDocs } from './projects-docs.js';
import { AdminAuth } from '../admin/auth.js';

export const ProjectsBoard = (function () {
  const COLUMNS = ['backlog', 'todo', 'doing', 'review', 'done'];
  const COL_LABEL = { backlog: 'Backlog', todo: 'To do', doing: 'In progress', review: 'Review', done: 'Done' };
  let _segment = 'board';
  let _adopted = false;
  const _selected = new Set();   // backlog bulk-op selection (task ids)

  function _pid() { return Kanban.activeProject && Kanban.activeProject(); }

  // Re-adopt the relocated Kanban panel into the Board segment. Idempotent —
  // the relocator lands #kanban-panel directly under #tab-projects; we move it
  // one level deeper into #projects-seg-board so the segment switcher governs
  // its visibility. Safe to call on every tab activation.
  function init() {
    const seg = document.getElementById('projects-seg-board');
    const panel = document.getElementById('kanban-panel');
    if (seg && panel && panel.parentElement !== seg) {
      const ph = document.getElementById('projects-tab-placeholder');
      if (ph) ph.remove();
      seg.appendChild(panel);
      _adopted = true;
    }
  }

  function activate() {
    init();
    segment(_segment);
  }

  function segment(name) {
    _segment = name || 'board';
    document.querySelectorAll('.proj-seg-btn').forEach(b => {
      const on = b.dataset.segment === _segment;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.proj-seg-panel').forEach(p => {
      const on = p.id === 'projects-seg-' + _segment;
      p.classList.toggle('active', on);
      p.hidden = !on;
    });
    if (_segment === 'backlog') renderBacklog();
    else if (_segment === 'timeline') renderTimeline();
    else if (_segment === 'docs') { try { ProjectsDocs.render(); } catch (_) {} }
  }

  async function _fetchTasks(history) {
    const pid = _pid();
    if (!pid) return null;
    const url = '/api/projects/' + encodeURIComponent(pid) + '/tasks' + (history ? '?history=1' : '');
    return Net.getJson(url, { silent: true });
  }

  // ── Task drawer ────────────────────────────────────────────────────
  async function openDrawer(taskId) {
    const pid = _pid();
    if (!pid || !taskId) return;
    const drawer = document.getElementById('proj-task-drawer');
    const body = document.getElementById('proj-drawer-body');
    if (!drawer || !body) return;
    body.dataset.taskId = taskId;
    body.innerHTML = '<div class="model-empty" style="font-size:0.72rem">Loading task…</div>';
    drawer.hidden = false;
    drawer.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => drawer.classList.add('open'));
    let task = null, runs = [];
    try {
      const tasks = await _fetchTasks(true);
      task = (tasks || []).find(t => t.id === taskId);
    } catch (_) {}
    try {
      const allRuns = await Net.getJson('/api/projects/' + encodeURIComponent(pid) + '/runs', { silent: true });
      runs = (allRuns || []).filter(r => r.task_id === taskId);
    } catch (_) {}
    if (!task) {
      body.innerHTML = '<div class="model-empty" style="font-size:0.72rem">Task not found — it may have been deleted.</div>';
      return;
    }
    document.getElementById('proj-drawer-title').textContent = task.title || 'Task';
    body.innerHTML = _drawerForm(task, runs);
  }

  function _drawerForm(t, runs) {
    const colOpts = COLUMNS.map(c => `<option value="${c}"${t.column === c ? ' selected' : ''}>${COL_LABEL[c]}</option>`).join('');
    const prioOpts = ['', 'p0', 'p1', 'p2', 'p3'].map(p =>
      `<option value="${p}"${(t.priority || '') === p ? ' selected' : ''}>${p || '—'}</option>`).join('');
    const hist = (t.history || []);
    const histHtml = hist.length
      ? hist.map(h => `<li><span class="proj-hist-col">${esc(COL_LABEL[h.column] || h.column || '?')}</span><span class="proj-hist-ts">${esc((h.ts || '').replace('T', ' ').slice(0, 16))}</span></li>`).join('')
      : '<li class="proj-hist-empty">No status transitions recorded yet.</li>';
    const runsHtml = runs.length
      ? runs.map(r => `<li><button class="proj-run-link" data-action="proj.open-run" data-run="${esc(r.run_id)}">${esc(r.label || r.run_id)}</button><span class="proj-hist-ts">${esc((r.ts || '').replace('T', ' ').slice(0, 16))}</span></li>`).join('')
      : '<li class="proj-hist-empty">No runs linked to this task.</li>';
    return `
      <div class="proj-drawer-field">
        <label class="admin-modal-label" for="drw-title">Title</label>
        <input id="drw-title" type="text" value="${esc(t.title || '')}" autocomplete="off">
      </div>
      <div class="proj-drawer-grid">
        <div class="proj-drawer-field">
          <label class="admin-modal-label" for="drw-column">Column</label>
          <select id="drw-column" class="model-select">${colOpts}</select>
        </div>
        <div class="proj-drawer-field">
          <label class="admin-modal-label" for="drw-priority">Priority</label>
          <select id="drw-priority" class="model-select">${prioOpts}</select>
        </div>
        <div class="proj-drawer-field">
          <label class="admin-modal-label" for="drw-start">Start</label>
          <input id="drw-start" type="date" value="${esc(t.start_date || '')}">
        </div>
        <div class="proj-drawer-field">
          <label class="admin-modal-label" for="drw-due">Due</label>
          <input id="drw-due" type="date" value="${esc(t.due_date || '')}">
        </div>
        <div class="proj-drawer-field">
          <label class="admin-modal-label" for="drw-estimate">Estimate (pts)</label>
          <input id="drw-estimate" type="number" min="0" max="16" step="1" value="${t.estimate != null ? esc(String(t.estimate)) : ''}">
        </div>
        <div class="proj-drawer-field">
          <label class="admin-modal-label" for="drw-assignee">Assignee</label>
          <input id="drw-assignee" type="text" value="${esc(t.assignee || '')}" autocomplete="off">
        </div>
      </div>
      <div class="proj-drawer-field">
        <label class="admin-modal-label" for="drw-milestone">Milestone</label>
        <input id="drw-milestone" type="text" value="${esc(t.milestone || '')}" autocomplete="off">
      </div>
      <div class="proj-drawer-field">
        <label class="admin-modal-label" for="drw-labels">Labels <span style="color:var(--text-muted);font-weight:normal">(comma-separated)</span></label>
        <input id="drw-labels" type="text" value="${esc((t.labels || []).join(', '))}" autocomplete="off">
      </div>
      <div class="proj-drawer-field">
        <label class="admin-modal-label" for="drw-desc">Description</label>
        <textarea id="drw-desc" rows="4">${esc(t.description || '')}</textarea>
      </div>
      <div id="drw-error" class="admin-modal-error" hidden></div>
      <div class="proj-drawer-actions">
        <button type="button" class="admin-modal-btn primary" data-action="proj.drawer-save">Save</button>
        <button type="button" class="admin-modal-btn" data-action="proj.drawer-close">Close</button>
      </div>
      <div class="proj-drawer-meta">
        <div class="proj-drawer-section">
          <div class="proj-drawer-section-h">Status history</div>
          <ul class="proj-hist">${histHtml}</ul>
        </div>
        <div class="proj-drawer-section">
          <div class="proj-drawer-section-h">Linked runs</div>
          <ul class="proj-hist">${runsHtml}</ul>
        </div>
        <div class="proj-drawer-section">
          <div class="proj-drawer-section-h">Docs</div>
          <button class="action-btn xs ghost" data-action="proj.open-docs">Open project docs →</button>
        </div>
      </div>
    `;
  }

  async function saveDrawer() {
    const pid = _pid();
    const body = document.getElementById('proj-drawer-body');
    if (!pid || !body || !body.dataset.taskId) return;
    const taskId = body.dataset.taskId;
    const errBox = document.getElementById('drw-error');
    const val = id => { const el = document.getElementById(id); return el ? el.value : ''; };
    const title = val('drw-title').trim();
    if (!title) { if (errBox) { errBox.hidden = false; errBox.textContent = 'Title is required.'; } return; }
    const patch = {
      title,
      column: val('drw-column'),
      priority: val('drw-priority') || null,
      start_date: val('drw-start') || null,
      due_date: val('drw-due') || null,
      estimate: val('drw-estimate') === '' ? null : val('drw-estimate'),
      milestone: val('drw-milestone').trim() || null,
      assignee: val('drw-assignee').trim() || null,
      labels: val('drw-labels').split(',').map(s => s.trim()).filter(Boolean),
      description: val('drw-desc'),
    };
    try {
      const r = await Net.call('/api/projects/' + encodeURIComponent(pid) + '/tasks/' + encodeURIComponent(taskId), {
        retries: 0,
        init: { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) },
      });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      closeDrawer();
      try { await Kanban.refresh(); } catch (_) {}
      if (_segment === 'backlog') renderBacklog();
      else if (_segment === 'timeline') renderTimeline();
      if (window.Toast) Toast.success('Task saved', title);
    } catch (e) {
      if (errBox) { errBox.hidden = false; errBox.textContent = String(e); }
    }
  }

  function closeDrawer() {
    const drawer = document.getElementById('proj-task-drawer');
    if (!drawer) return;
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    setTimeout(() => { drawer.hidden = true; }, 180);
  }

  // ── Backlog grooming table + bulk ops ──────────────────────────────
  async function renderBacklog() {
    const host = document.getElementById('projects-backlog-body');
    const toolbar = document.getElementById('proj-backlog-toolbar');
    if (!host) return;
    const pid = _pid();
    // Refresh AI proposals whenever the Backlog view renders (best-effort).
    try { loadProposals(); } catch (_) {}
    if (!pid) {
      host.innerHTML = '<div class="model-empty" style="font-size:0.72rem">Pick a project on the Board segment first.</div>';
      if (toolbar) toolbar.hidden = true;
      return;
    }
    host.innerHTML = '<div class="skeleton skeleton-line long"></div><div class="skeleton skeleton-line short"></div>';
    let tasks = [];
    try { tasks = await _fetchTasks(false) || []; }
    catch (e) { host.innerHTML = '<div class="admin-modal-error">Couldn’t load tasks — ' + esc(String(e)) + '</div>'; return; }
    _selected.clear();
    if (toolbar) toolbar.hidden = false;
    _syncSelCount();
    if (!tasks.length) {
      host.innerHTML = '<div class="model-empty" style="font-size:0.72rem">No tasks yet. Add tasks on the Board segment.</div>';
      return;
    }
    // Sort: priority (p0 first) then due date then column order.
    const prioRank = { p0: 0, p1: 1, p2: 2, p3: 3 };
    tasks.sort((a, b) => {
      const pa = prioRank[a.priority] != null ? prioRank[a.priority] : 9;
      const pb = prioRank[b.priority] != null ? prioRank[b.priority] : 9;
      if (pa !== pb) return pa - pb;
      const da = a.due_date || '9999-99-99', db = b.due_date || '9999-99-99';
      if (da !== db) return da < db ? -1 : 1;
      return COLUMNS.indexOf(a.column) - COLUMNS.indexOf(b.column);
    });
    const rows = tasks.map(t => `
      <tr data-task-id="${esc(t.id)}">
        <td class="proj-bk-check"><input type="checkbox" data-action="proj.backlog-toggle" data-task-id="${esc(t.id)}"></td>
        <td class="proj-bk-title"><button class="proj-bk-open" data-action="proj.backlog-open" data-task-id="${esc(t.id)}">${esc(t.title || '(untitled)')}</button></td>
        <td>${t.priority ? `<span class="kanban-chip prio prio-${esc(t.priority)}">${esc(t.priority)}</span>` : '<span class="proj-bk-dim">—</span>'}</td>
        <td>${esc(COL_LABEL[t.column] || t.column || '?')}</td>
        <td>${t.due_date ? esc(t.due_date) : '<span class="proj-bk-dim">—</span>'}</td>
        <td>${t.estimate != null && t.estimate !== '' ? esc(String(t.estimate)) + 'pt' : '<span class="proj-bk-dim">—</span>'}</td>
        <td>${t.milestone ? esc(String(t.milestone)) : '<span class="proj-bk-dim">—</span>'}</td>
      </tr>`).join('');
    host.innerHTML = `
      <table class="proj-backlog-table">
        <thead><tr>
          <th class="proj-bk-check"><input type="checkbox" data-action="proj.backlog-toggle-all" title="Select all"></th>
          <th>Task</th><th>Prio</th><th>Column</th><th>Due</th><th>Est</th><th>Milestone</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function backlogToggle(el) {
    const id = el.dataset.taskId;
    if (!id) return;
    if (el.checked) _selected.add(id); else _selected.delete(id);
    _syncSelCount();
  }
  function backlogToggleAll(el) {
    const on = el.checked;
    document.querySelectorAll('#projects-backlog-body input[data-action="proj.backlog-toggle"]').forEach(cb => {
      cb.checked = on;
      if (on) _selected.add(cb.dataset.taskId); else _selected.delete(cb.dataset.taskId);
    });
    _syncSelCount();
  }
  function _syncSelCount() {
    const el = document.getElementById('proj-backlog-sel');
    if (el) el.textContent = _selected.size + ' selected';
  }

  async function _bulkPatch(patch) {
    const pid = _pid();
    if (!pid || !_selected.size) { if (window.Toast) Toast.warn('Nothing selected', 'Tick one or more tasks first.'); return; }
    const ids = Array.from(_selected);
    let ok = 0;
    for (const id of ids) {
      try {
        const r = await Net.call('/api/projects/' + encodeURIComponent(pid) + '/tasks/' + encodeURIComponent(id), {
          retries: 0,
          init: { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) },
        });
        if (r.ok) ok++;
      } catch (_) {}
    }
    if (window.Toast) Toast.success('Bulk update', ok + ' of ' + ids.length + ' updated');
    await renderBacklog();
    try { await Kanban.refresh(); } catch (_) {}
  }
  function backlogBulkMove() {
    const col = (document.getElementById('proj-backlog-bulk-col') || {}).value;
    if (!col) { if (window.Toast) Toast.warn('Pick a column', 'Choose a destination column.'); return; }
    _bulkPatch({ column: col });
  }
  function backlogBulkPrio() {
    const prio = (document.getElementById('proj-backlog-bulk-prio') || {}).value;
    if (!prio) { if (window.Toast) Toast.warn('Pick a priority', 'Choose p0–p3.'); return; }
    _bulkPatch({ priority: prio });
  }
  async function backlogBulkDelete() {
    const pid = _pid();
    if (!pid || !_selected.size) { if (window.Toast) Toast.warn('Nothing selected', 'Tick one or more tasks first.'); return; }
    const ids = Array.from(_selected);
    const ok = await Confirm.ask({
      title: 'Delete ' + ids.length + ' task' + (ids.length === 1 ? '' : 's') + '?',
      body: 'The tasks leave the board. Their events stay in the project log so the action is auditable.',
      okLabel: 'Delete', cancelLabel: 'Keep', danger: true,
    });
    if (!ok) return;
    let done = 0;
    for (const id of ids) {
      try {
        const r = await Net.call('/api/projects/' + encodeURIComponent(pid) + '/tasks/' + encodeURIComponent(id),
          { retries: 0, init: { method: 'DELETE' }, silent: true });
        if (r.ok) done++;
      } catch (_) {}
    }
    if (window.Toast) Toast.success('Deleted', done + ' task' + (done === 1 ? '' : 's') + ' removed');
    await renderBacklog();
    try { await Kanban.refresh(); } catch (_) {}
  }

  // ── Timeline (due-date lanes + Unscheduled) ────────────────────────
  async function renderTimeline() {
    const host = document.getElementById('projects-timeline-body');
    if (!host) return;
    const pid = _pid();
    if (!pid) {
      host.innerHTML = '<div class="model-empty" style="font-size:0.72rem">Pick a project on the Board segment first.</div>';
      return;
    }
    host.innerHTML = '<div class="skeleton skeleton-line long"></div><div class="skeleton skeleton-line short"></div>';
    let tasks = [];
    try { tasks = await _fetchTasks(false) || []; }
    catch (e) { host.innerHTML = '<div class="admin-modal-error">Couldn’t load tasks — ' + esc(String(e)) + '</div>'; return; }
    if (!tasks.length) {
      host.innerHTML = '<div class="model-empty" style="font-size:0.72rem">No tasks yet. Add tasks on the Board segment.</div>';
      return;
    }
    const scheduled = tasks.filter(t => t.due_date).sort((a, b) => a.due_date < b.due_date ? -1 : (a.due_date > b.due_date ? 1 : 0));
    const unscheduled = tasks.filter(t => !t.due_date);
    // Group scheduled by due date.
    const byDate = new Map();
    scheduled.forEach(t => { if (!byDate.has(t.due_date)) byDate.set(t.due_date, []); byDate.get(t.due_date).push(t); });
    const today = new Date().toISOString().slice(0, 10);
    let laneHtml = '';
    for (const [date, items] of byDate) {
      const past = date < today ? ' past' : (date === today ? ' today' : '');
      laneHtml += `<div class="proj-tl-lane${past}">
        <div class="proj-tl-date">${esc(date)}${date === today ? ' · today' : ''}</div>
        <div class="proj-tl-cards">${items.map(_tlCard).join('')}</div>
      </div>`;
    }
    const unschedHtml = `<div class="proj-tl-lane unscheduled">
      <div class="proj-tl-date">Unscheduled <span class="proj-bk-dim">(${unscheduled.length})</span></div>
      <div class="proj-tl-cards">${unscheduled.length ? unscheduled.map(_tlCard).join('') : '<div class="proj-hist-empty">Every task has a due date.</div>'}</div>
    </div>`;
    host.innerHTML = `<div class="proj-timeline">${laneHtml || '<div class="proj-hist-empty">No scheduled tasks.</div>'}${unschedHtml}</div>`;
  }

  function _tlCard(t) {
    return `<button class="proj-tl-card" data-action="proj.backlog-open" data-task-id="${esc(t.id)}">
      <span class="proj-tl-card-title">${esc(t.title || '(untitled)')}</span>
      ${Kanban.chipsHtml ? Kanban.chipsHtml(t) : ''}
      <span class="proj-tl-col">${esc(COL_LABEL[t.column] || t.column || '?')}</span>
    </button>`;
  }

  // ── AI plan-ops + proposals review (U12) ───────────────────────────
  // AI actions dispatch the frozen-engine project-plan workflow, then POST the
  // resulting plan-ops to /plan/apply where they land PROPOSED. Nothing touches
  // the board until the operator accepts a proposal in the review panel.

  function _authHeaders() {
    try { return AdminAuth.authHeaders ? AdminAuth.authHeaders() : {}; }
    catch (_) { return {}; }
  }

  // Poll a run to a terminal status, returning its final run_data (or null).
  async function _pollRun(runId, { tries = 60, delayMs = 1500 } = {}) {
    const terminal = new Set(['completed', 'failed', 'error', 'cancelled', 'awaiting_approval']);
    for (let i = 0; i < tries; i++) {
      let d = null;
      try { d = await Net.getJson('/api/workflows/runs/' + encodeURIComponent(runId), { silent: true }); }
      catch (_) { /* keep polling */ }
      if (d && terminal.has(d.status)) return d;
      await new Promise(r => setTimeout(r, delayMs));
    }
    return null;
  }

  // Pull the plan-ops array out of a completed run's workspace, tolerant of the
  // engine's output-key shapes (workspace.plan, workspace.plan.plan, …).
  function _extractPlan(runData) {
    const ws = (runData && runData.workspace) || {};
    const candidates = [ws.plan, ws.plan && ws.plan.plan, ws.plan && ws.plan.ops];
    for (const c of candidates) {
      if (Array.isArray(c)) return c;
      if (typeof c === 'string') { try { const p = JSON.parse(c); if (Array.isArray(p)) return p; } catch (_) {} }
    }
    return null;
  }

  async function _applyOps(pid, ops, source) {
    const r = await Net.call('/api/projects/' + encodeURIComponent(pid) + '/plan/apply', {
      retries: 0,
      init: {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()),
        body: JSON.stringify({ ops, source }),
      },
    });
    if (!r.ok) {
      Toast.danger('Plan apply failed', typeof r.data === 'string' ? r.data : ('HTTP ' + r.status));
      return null;
    }
    return r.data;
  }

  let _aiBusy = false;
  async function _runPlanFlow(kind) {
    const pid = _pid();
    if (!pid) { Toast.warn('Pick a project first', 'Choose a project on the Board segment.'); return; }
    if (_aiBusy) { Toast.info('AI busy', 'A plan is already running.'); return; }
    const verb = kind === 'groom' ? 'Groom the current backlog' : 'Draft a plan';
    const goal = window.prompt(verb + ' — what is the goal?', kind === 'groom' ? 'Groom and prioritise the backlog.' : '');
    if (goal === null) return;
    _aiBusy = true;
    Toast.info(kind === 'groom' ? 'Grooming backlog…' : 'Drafting plan…', 'Dispatching the local project-plan workflow.');
    try {
      const seed = { project_id: pid, goal: goal || '', docs: '' };
      const r = await Net.call('/api/workflows/run-async', {
        retries: 0,
        init: {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()),
          body: JSON.stringify({ workflow_id: 'project-plan', seed }),
        },
      });
      if (!r.ok) { Toast.danger('Dispatch failed', typeof r.data === 'string' ? r.data : ('HTTP ' + r.status)); return; }
      const runId = r.data && r.data.run_id;
      if (!runId) { Toast.danger('Dispatch failed', 'No run id returned.'); return; }
      const runData = await _pollRun(runId);
      if (!runData || runData.status !== 'completed') {
        Toast.warn('Plan run did not complete', 'Check the Runs tab (' + esc(runId) + ').');
        return;
      }
      let ops = _extractPlan(runData) || [];
      if (kind === 'groom') ops = ops.filter(o => o.op === 'update_task' || o.op === 'set_status' || o.op === 'set_milestone');
      if (!ops.length) { Toast.info('No ops proposed', 'The model returned an empty plan.'); return; }
      const res = await _applyOps(pid, ops, { run_id: runId, agent: kind === 'groom' ? 'groom-backlog' : 'draft-plan' });
      if (!res) return;
      // Best-effort: record the run against the project.
      try {
        await Net.call('/api/projects/' + encodeURIComponent(pid) + '/runs', {
          retries: 0,
          init: {
            method: 'POST',
            headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()),
            body: JSON.stringify({ run_id: runId, workflow_id: 'project-plan', label: (kind === 'groom' ? 'Groom backlog' : 'Draft plan'), origin: 'agent' }),
          }, silent: true,
        });
      } catch (_) {}
      Toast.success('Proposed ' + res.ops_accepted + ' op' + (res.ops_accepted === 1 ? '' : 's'), 'Review under Backlog → proposals.');
      await loadProposals();
    } catch (e) {
      Toast.danger('AI plan error', String(e && e.message || e));
    } finally {
      _aiBusy = false;
    }
  }

  function draftPlan() { return _runPlanFlow('draft'); }
  function groomBacklog() { return _runPlanFlow('groom'); }

  // Status-doc digest via the scribe → workspace expand() (never full rewrite).
  async function updateStatusDoc() {
    const pid = _pid();
    if (!pid) { Toast.warn('Pick a project first'); return; }
    const ws = 'proj-' + pid;
    Toast.info('Updating status doc…', 'Appending a digest under a heading (expand-only).');
    try {
      const r = await Net.call('/api/workspaces/' + encodeURIComponent(ws) + '/expand', {
        retries: 0,
        init: {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()),
          body: JSON.stringify({ file: 'notes/status.md', heading: 'Status', agent: 'project-scribe' }),
        },
      });
      if (!r.ok) {
        Toast.warn('Status update unavailable', r.status === 404 ? 'Bind a docs directory first (Docs segment).' : ('HTTP ' + r.status));
        return;
      }
      Toast.success('Status doc updated', 'See Docs → notes/status.md.');
    } catch (e) { Toast.danger('Status update error', String(e && e.message || e)); }
  }

  async function loadProposals() {
    const host = document.getElementById('proj-proposals');
    const badge = document.getElementById('proj-proposals-badge');
    const pid = _pid();
    if (!host) return;
    if (!pid) { host.hidden = true; host.innerHTML = ''; if (badge) badge.hidden = true; return; }
    let props = [];
    try { props = await Net.getJson('/api/projects/' + encodeURIComponent(pid) + '/proposals', { silent: true }) || []; }
    catch (_) { host.hidden = true; return; }
    if (badge) {
      if (props.length) { badge.textContent = '● ' + props.length; badge.hidden = false; }
      else badge.hidden = true;
    }
    if (!props.length) { host.hidden = true; host.innerHTML = ''; return; }
    host.hidden = false;
    host.innerHTML = '<div class="proj-prop-h">Pending AI proposals <span class="proj-bk-dim">(' + props.length + ')</span></div>'
      + props.map(_proposalCard).join('');
  }

  function _opLine(op) {
    const kind = op.op;
    const before = op.before || {};
    if (kind === 'add_task') {
      return '<b>add</b> “' + esc(op.title || '') + '”' + (op.column ? ' → ' + esc(op.column) : '')
        + (op.priority ? ' · ' + esc(op.priority) : '') + (op.milestone ? ' · ' + esc(op.milestone) : '');
    }
    if (kind === 'set_status') {
      return '<b>move</b> “' + esc(before.title || op.id) + '”: ' + esc(before.column || '?') + ' → ' + esc(op.column || '?');
    }
    if (kind === 'set_milestone') {
      return '<b>milestone</b> “' + esc(before.title || op.id) + '” → ' + esc(op.milestone || '');
    }
    const skip = ['op', 'id', 'before', 'ts', 'origin', 'source', 'created_at', 'position', 'proposal_id', 'state', 'plan_op', 'approved_at'];
    const fields = Object.keys(op).filter(k => !skip.includes(k));
    return '<b>update</b> “' + esc(before.title || op.id) + '”: ' + esc(fields.join(', ') || '(no fields)');
  }

  function _proposalCard(p) {
    const src = (p.source && (p.source.agent || p.source.run_id)) ? esc(p.source.agent || p.source.run_id) : 'agent';
    const ts = (p.ts || '').replace('T', ' ').slice(0, 16);
    return `<div class="proj-prop-card" data-prop="${esc(p.proposal_id)}">
      <div class="proj-prop-head">
        <span class="proj-prop-src">${src}</span>
        <span class="proj-prop-count">${p.ops.length} op${p.ops.length === 1 ? '' : 's'}</span>
        <span class="proj-prop-ts">${esc(ts)}</span>
        <span style="flex:1"></span>
        <button class="action-btn xs primary" data-action="proj.proposal-accept" data-prop="${esc(p.proposal_id)}">Accept</button>
        <button class="action-btn xs danger" data-action="proj.proposal-reject" data-prop="${esc(p.proposal_id)}">Reject</button>
      </div>
      <ul class="proj-prop-ops">${p.ops.map(o => '<li>' + _opLine(o) + '</li>').join('')}</ul>
    </div>`;
  }

  async function _resolveProposal(propId, action) {
    const pid = _pid();
    if (!pid || !propId) return;
    const r = await Net.call('/api/projects/' + encodeURIComponent(pid) + '/proposals/' + encodeURIComponent(propId) + '/' + action, {
      retries: 0, init: { method: 'POST', headers: _authHeaders() },
    });
    if (!r.ok) { Toast.danger(action + ' failed', typeof r.data === 'string' ? r.data : ('HTTP ' + r.status)); return; }
    Toast.success(action === 'accept' ? 'Proposal accepted' : 'Proposal rejected');
    await loadProposals();
    try { await Kanban.refresh(); } catch (_) {}
    if (_segment === 'backlog') await renderBacklog();
  }
  function acceptProposal(propId) { return _resolveProposal(propId, 'accept'); }
  function rejectProposal(propId) { return _resolveProposal(propId, 'reject'); }

  return {
    init, activate, segment,
    openDrawer, saveDrawer, closeDrawer,
    renderBacklog, renderTimeline,
    backlogToggle, backlogToggleAll,
    backlogBulkMove, backlogBulkPrio, backlogBulkDelete,
    // U12 — AI plan-ops + proposals
    draftPlan, groomBacklog, updateStatusDoc,
    loadProposals, acceptProposal, rejectProposal,
    // exposed for tests / cross-module
    _currentSegment: () => _segment,
  };
})();
