// library/kanban.js — workflow-index Kanban board (phase-2 U4 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm, ErrorPanel, Skeleton } from '../core/ui.js';

export const Kanban = (function () {
  let _activeProject = null;
  let _modalMode = null;       // 'task' | 'project'
  let _modalColumn = 'todo';
  let _editingTaskId = null;

  function _setEmptyBoard() {
    document.querySelectorAll('.kanban-col-body').forEach(b => {
      b.innerHTML = '<div class="kanban-empty">Drop tasks here — or click + Add task.</div>';
    });
    document.querySelectorAll('.kanban-col-count[data-count]').forEach(c => c.textContent = '0');
  }

  async function _loadProjectsIntoSelect() {
    const sel = document.getElementById('kanban-project-select');
    if (!sel) return;
    try {
      const list = await Net.getJson('/api/projects');
      const projects = Array.isArray(list) ? list : (list.projects || []);
      const current = sel.value;
      sel.innerHTML = '<option value="">— pick a project —</option>' +
        projects.map(p => `<option value="${esc(p.id || p.project_id || '')}">${esc(p.name || p.id || '?')}</option>`).join('');
      if (current && projects.some(p => (p.id || p.project_id) === current)) {
        sel.value = current;
      }
    } catch (e) {
      sel.innerHTML = '<option value="">(failed to load projects)</option>';
    }
  }

  async function setActive(projectId) {
    _activeProject = projectId || null;
    if (!_activeProject) { _setEmptyBoard(); return; }
    await _renderTasks();
  }

  async function refresh() {
    await _loadProjectsIntoSelect();
    if (_activeProject) await _renderTasks();
  }

  async function _renderTasks() {
    if (!_activeProject) return _setEmptyBoard();
    const board = document.getElementById('kanban-board');
    if (!board) return;
    // Skeleton placeholders while we fetch.
    document.querySelectorAll('.kanban-col-body').forEach(b => {
      b.innerHTML = '<div class="skeleton skeleton-line long"></div><div class="skeleton skeleton-line short"></div>';
    });
    try {
      const tasks = await Net.getJson('/api/projects/' + encodeURIComponent(_activeProject) + '/tasks');
      // Additive 5-column enum (U3): backlog·todo·doing·review·done.
      const byCol = { backlog: [], todo: [], doing: [], review: [], done: [] };
      (tasks || []).forEach(t => {
        const col = byCol[t.column] ? t.column : 'todo';
        byCol[col].push(t);
      });
      Object.entries(byCol).forEach(([col, items]) => {
        items.sort((a, b) => (a.position || 0) - (b.position || 0));
        const body = document.querySelector(`.kanban-col[data-column="${col}"] .kanban-col-body`);
        if (!body) return;
        if (!items.length) {
          body.innerHTML = '<div class="kanban-empty">Drop tasks here — or click + Add task.</div>';
        } else {
          body.innerHTML = items.map(t => _renderCard(t)).join('');
        }
        const count = document.querySelector(`.kanban-col[data-column="${col}"] .kanban-col-count`);
        if (count) count.textContent = items.length || '';
      });
    } catch (e) {
      // Render unified error in each column so the operator sees it
      // visually wherever they look, with a Retry button.
      document.querySelectorAll('.kanban-col-body').forEach((b, i) => {
        if (i === 0) {
          ErrorPanel.render(b, {
            title: 'Couldn’t load tasks',
            detail: String(e),
            retry: () => _renderTasks(),
          });
        } else {
          b.innerHTML = '';
        }
      });
      if (window.Toast) Toast.danger('Tasks load failed', String(e));
    }
  }

  // Metadata chips shared by the board card and the drawer header. Only
  // renders chips for fields that carry a value (U2 extra fields:
  // priority / due_date / start_date / estimate / milestone / assignee).
  function chipsHtml(t) {
    const chips = [];
    if (t.priority) chips.push(`<span class="kanban-chip prio prio-${esc(t.priority)}">${esc(t.priority)}</span>`);
    if (t.due_date) chips.push(`<span class="kanban-chip due" title="Due ${esc(t.due_date)}">▸ ${esc(t.due_date)}</span>`);
    else if (t.start_date) chips.push(`<span class="kanban-chip" title="Starts ${esc(t.start_date)}">◃ ${esc(t.start_date)}</span>`);
    if (t.estimate != null && t.estimate !== '') chips.push(`<span class="kanban-chip est" title="Estimate">${esc(String(t.estimate))}pt</span>`);
    if (t.milestone) chips.push(`<span class="kanban-chip ms" title="Milestone">◈ ${esc(String(t.milestone))}</span>`);
    if (t.assignee) chips.push(`<span class="kanban-chip who" title="Assignee">@${esc(t.assignee)}</span>`);
    if (t.origin === 'agent') chips.push(`<span class="kanban-chip agent" title="Proposed by an agent">ai</span>`);
    return chips.length ? `<div class="kanban-card-chips">${chips.join('')}</div>` : '';
  }

  function _renderCard(t) {
    const labels = (t.labels || []).map(l => `<span class="kanban-label">${esc(l)}</span>`).join('');
    const desc = t.description ? `<div class="kanban-card-desc">${esc(t.description.slice(0, 200))}${t.description.length > 200 ? '…' : ''}</div>` : '';
    return `
      <div class="kanban-card" draggable="true"
           data-task-id="${esc(t.id)}"
           data-action="kanban.card">
        <div class="kanban-card-title">${esc(t.title || '')}</div>
        ${desc}
        ${chipsHtml(t)}
        ${labels ? `<div class="kanban-card-labels">${labels}</div>` : ''}
        <div class="kanban-card-actions">
          <button class="kanban-card-btn" title="Edit"
                  data-action="kanban.edit">edit</button>
          <button class="kanban-card-btn danger" title="Delete"
                  data-action="kanban.delete">×</button>
        </div>
      </div>
    `;
  }

  function _dragStart(ev, id) {
    ev.dataTransfer.setData('application/x-enclave-task', id);
    ev.dataTransfer.effectAllowed = 'move';
    ev.target.classList.add('dragging');
  }
  function _dragEnd(ev) {
    ev.target.classList.remove('dragging');
    document.querySelectorAll('.kanban-col-body.drop-target').forEach(b => b.classList.remove('drop-target'));
  }
  async function drop(ev, column) {
    ev.preventDefault();
    document.querySelectorAll('.kanban-col-body.drop-target').forEach(b => b.classList.remove('drop-target'));
    const id = ev.dataTransfer.getData('application/x-enclave-task');
    if (!id || !_activeProject) return;
    try {
      const r = await Net.call('/api/projects/' + encodeURIComponent(_activeProject) + '/tasks/' + encodeURIComponent(id), {
        retries: 0,
        init: {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ column, position: Date.now() }),
        },
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      await _renderTasks();
    } catch (e) {
      if (window.Toast) Toast.danger('Move failed', String(e));
    }
  }

  // ── Modal flows ────────────────────────────────────────────────────
  function _openModal(mode, opts) {
    _modalMode = mode;
    opts = opts || {};
    _modalColumn = opts.column || 'todo';
    _editingTaskId = opts.editingTaskId || null;
    document.getElementById('kanban-modal-title').textContent =
      mode === 'project' ? 'New project' :
      _editingTaskId ? 'Edit task' : 'New task — ' + _modalColumn;
    document.getElementById('kanban-modal-title-input').value = opts.title || '';
    document.getElementById('kanban-modal-desc').value = opts.description || '';
    document.getElementById('kanban-modal-labels').value = (opts.labels || []).join(', ');
    document.getElementById('kanban-modal-error').hidden = true;
    document.getElementById('kanban-modal').hidden = false;
    setTimeout(() => document.getElementById('kanban-modal-title-input').focus(), 0);
  }
  function _cancelModal() {
    document.getElementById('kanban-modal').hidden = true;
    _editingTaskId = null;
    _modalMode = null;
  }

  function showCreateTask(column) {
    if (!_activeProject) {
      if (window.Toast) Toast.warn('Pick a project first', 'Use the dropdown above the board.');
      return;
    }
    _openModal('task', { column: column || 'todo' });
  }

  async function showEditTask(taskId) {
    if (!_activeProject) return;
    try {
      const list = await Net.getJson('/api/projects/' + encodeURIComponent(_activeProject) + '/tasks', { silent: true });
      const t = (list || []).find(x => x.id === taskId);
      if (!t) return;
      _openModal('task', {
        column: t.column,
        editingTaskId: taskId,
        title: t.title,
        description: t.description,
        labels: t.labels || [],
      });
    } catch (_) {}
  }

  function showCreateProject() {
    _openModal('project');
  }

  async function _submitModal() {
    const errBox = document.getElementById('kanban-modal-error');
    const title = document.getElementById('kanban-modal-title-input').value.trim();
    if (!title) {
      errBox.hidden = false;
      errBox.textContent = 'Title is required.';
      return;
    }
    try {
      if (_modalMode === 'project') {
        const desc = document.getElementById('kanban-modal-desc').value.trim();
        const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || ('proj_' + Date.now().toString(36));
        const r = await Net.call('/api/projects', {
          retries: 0,
          init: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: slug, name: title, description: desc }),
          },
        });
        if (!r.ok) {
          const t = typeof r.data === 'string' ? r.data : JSON.stringify(r.data || r.error || '');
          throw new Error('HTTP ' + r.status + ' — ' + String(t).slice(0, 200));
        }
        const rec = r.data;
        _cancelModal();
        await _loadProjectsIntoSelect();
        document.getElementById('kanban-project-select').value = rec.id || slug;
        await setActive(rec.id || slug);
        if (window.Toast) Toast.success('Project created', title);
      } else if (_modalMode === 'task') {
        const desc = document.getElementById('kanban-modal-desc').value.trim();
        const labels = document.getElementById('kanban-modal-labels').value
          .split(',').map(s => s.trim()).filter(Boolean);
        if (_editingTaskId) {
          const r = await Net.call('/api/projects/' + encodeURIComponent(_activeProject) + '/tasks/' + encodeURIComponent(_editingTaskId), {
            retries: 0,
            init: {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title, description: desc, labels }),
            },
          });
          if (!r.ok) throw new Error('HTTP ' + r.status);
        } else {
          const r = await Net.call('/api/projects/' + encodeURIComponent(_activeProject) + '/tasks', {
            retries: 0,
            init: {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title, description: desc, labels, column: _modalColumn }),
            },
          });
          if (!r.ok) throw new Error('HTTP ' + r.status);
        }
        _cancelModal();
        await _renderTasks();
      }
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = String(e);
    }
  }

  async function deleteTask(taskId) {
    if (!_activeProject) return;
    const ok = await Confirm.ask({
      title: 'Delete task?',
      body: 'This removes the task from the board. The event stays in the project log so the action is auditable, but the task won’t come back.',
      okLabel: 'Delete',
      cancelLabel: 'Keep',
      danger: true,
    });
    if (!ok) return;
    const r = await Net.call(
      '/api/projects/' + encodeURIComponent(_activeProject) + '/tasks/' + encodeURIComponent(taskId),
      { retries: 0, init: { method: 'DELETE' }, silent: true }
    );
    if (!r.ok) {
      if (window.Toast) Toast.danger('Delete failed', r.error);
      return;
    }
    await _renderTasks();
  }

  // Auto-init when the Workflow Index tab activates.
  document.addEventListener('DOMContentLoaded', () => {
    refresh();
  });

  return {
    setActive, refresh,
    showCreateTask, showEditTask, showCreateProject, deleteTask, drop,
    _dragStart, _dragEnd, _cancelModal, _submitModal,
    // U3: exposed for the Board/Backlog/Timeline/Docs segments so they can
    // read the active project + reuse the metadata-chip rendering.
    activeProject: () => _activeProject,
    chipsHtml,
  };
})();
