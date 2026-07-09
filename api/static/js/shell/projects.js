// shell/projects.js — Projects locator (phase-2 U8 straggler; sidebar-relevant).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';

export const Projects = (function () {
  let _projects = [];
  let _active = null;

  async function load() {
    try {
      _projects = await Net.getJson('/api/projects', { silent: true });
      _renderBar();
    } catch (e) { /* offline-tolerant */ }
  }

  function _renderBar() {
    const sel = document.getElementById('project-select');
    if (!sel) return;
    sel.innerHTML = ['<option value="">— no project context —</option>']
      .concat(_projects.map(p => `<option value="${esc(p.id)}">${esc(p.name)} (${(p.counts.workflows||0)+(p.counts.agents||0)+(p.counts.mcp_servers||0)+(p.counts.documents||0)})</option>`))
      .join('');
    if (_active) sel.value = _active;
  }

  function setActive(id) {
    _active = id;
    window._activeProject = id;
    document.getElementById('project-badge').textContent = id || '—';
  }

  // Slugify a free-form name → safe project ID. Server enforces the
  // same alphanum/_/- shape, this is just a convenience so the user
  // doesn't have to type a slug manually.
  function _slugify(s) {
    return (s || '')
      .toLowerCase()
      .trim()
      .replace(/['"]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 64);
  }

  function showCreate() {
    const modal = document.getElementById('project-create-modal');
    if (!modal) return;
    // Reset fields each open so we don't leak previous attempts.
    ['project-create-name','project-create-id','project-create-desc','project-create-category','project-create-tags'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
    document.getElementById('project-create-error').hidden = true;
    // Auto-derive ID from the name as the user types, but only while
    // the ID field is empty / has the previous auto-value.
    const nameEl = document.getElementById('project-create-name');
    const idEl = document.getElementById('project-create-id');
    nameEl.oninput = () => {
      if (!idEl.dataset.userEdited) idEl.value = _slugify(nameEl.value);
    };
    idEl.oninput = () => { idEl.dataset.userEdited = '1'; };
    modal.hidden = false;
    setTimeout(() => nameEl.focus(), 0);
  }

  function _closeCreate() {
    const modal = document.getElementById('project-create-modal');
    if (modal) modal.hidden = true;
  }

  async function _submitCreate() {
    const errBox = document.getElementById('project-create-error');
    const name = document.getElementById('project-create-name').value.trim();
    let id = document.getElementById('project-create-id').value.trim() || _slugify(name);
    const description = document.getElementById('project-create-desc').value.trim();
    const category = document.getElementById('project-create-category').value.trim();
    const tagsRaw = document.getElementById('project-create-tags').value.trim();
    const tags = tagsRaw ? tagsRaw.split(',').map(t => t.trim()).filter(Boolean) : [];

    if (!name) { errBox.hidden = false; errBox.textContent = 'Name is required.'; return; }
    if (!id) { errBox.hidden = false; errBox.textContent = 'ID could not be derived from the name — set one explicitly.'; return; }
    if (!/^[A-Za-z0-9_-]+$/.test(id)) {
      errBox.hidden = false;
      errBox.textContent = "ID can only contain letters, digits, '_' and '-'.";
      return;
    }
    try {
      const body = { id, name };
      if (description) body.description = description;
      if (category) body.category = category;
      if (tags.length) body.tags = tags;
      const r = await Net.call('/api/projects', {
        retries: 0,
        init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      });
      if (!r.ok) {
        const detail = typeof r.data === 'string' ? r.data : (r.data && (r.data.detail || r.data.error)) || r.error || '';
        errBox.hidden = false;
        errBox.textContent = `Create failed: ${detail}`;
        return;
      }
      _closeCreate();
      await load();
      setActive(id);
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = `Create error: ${e.message}`;
    }
  }

  // Legacy alias: any old call site still hitting `Projects.create()`
  // now opens the modal instead of the old prompt() flow.
  async function create() { showCreate(); }

  async function attachCurrentWorkflow() {
    if (!_active) { Toast.warn('Pick a project first.'); return; }
    const wfId = (document.getElementById('df-wf-id') || {}).value;
    if (!wfId) { Toast.warn('Set a workflow ID first.'); return; }
    try {
      const r = await Net.call(`/api/projects/${encodeURIComponent(_active)}/artifacts/workflows/${encodeURIComponent(wfId)}`, { retries: 0, init: { method: 'POST' } });
      if (!r.ok) { Toast.danger('Attach failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      Toast.success(`Workflow '${wfId}' attached`, `project '${_active}'`);
      await load();
    } catch (e) { Toast.danger('Attach error', e.message); }
  }

  async function exportBundle() {
    if (!_active) { Toast.warn('Pick a project first.'); return; }
    try {
      const r = await Net.call(`/api/projects/${encodeURIComponent(_active)}/export`);
      if (!r.ok) { Toast.danger('Export failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      const bundle = r.data;
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${_active}.project.json`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) { Toast.danger('Export error', e.message); }
  }

  function importBundle() {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.json';
    inp.onchange = async () => {
      const file = inp.files && inp.files[0];
      if (!file) return;
      const text = await file.text();
      try {
        const bundle = JSON.parse(text);
        const r = await Net.call('/api/projects/import?overwrite=true', {
          retries: 0,
          init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) },
        });
        if (!r.ok) { Toast.danger('Import failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
        const result = r.data;
        Toast.success(`Imported project '${result.project_id}'`);
        await load();
        setActive(result.project_id);
      } catch (e) { Toast.danger('Import error', e.message); }
    };
    inp.click();
  }

  return {
    load, setActive, create, attachCurrentWorkflow, exportBundle, importBundle,
    showCreate, _closeCreate, _submitCreate,
  };
})();
