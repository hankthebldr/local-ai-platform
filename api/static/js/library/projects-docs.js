// library/projects-docs.js — Projects › Docs segment (U3).
//
// A file tree + markdown editor over the project's bound context Workspace
// (proj-<id>). Reuses the existing /api/workspaces routes; writes carry admin
// headers (AdminAuth) so they keep working once the workspace write surface is
// master-key gated (U10). When no workspace is bound yet, offers a
// Bind-context-directory affordance that POSTs /api/projects/{id}/context-
// workspace (master-key) with an optional root (Obsidian vault → 00-Inbox
// re-root is handled server-side).

import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';
import { AdminAuth } from '../admin/auth.js';
import { Kanban } from './kanban.js';

export const ProjectsDocs = (function () {
  let _ws = null;          // bound workspace name, or null
  let _file = null;        // currently open file path
  let _dirty = false;

  function _pid() { return Kanban.activeProject && Kanban.activeProject(); }
  function _wsName(pid) { return ('proj-' + pid).toLowerCase(); }
  function _host() { return document.getElementById('projects-docs-body'); }

  async function render() {
    const host = _host();
    if (!host) return;
    const pid = _pid();
    if (!pid) {
      host.innerHTML = '<div class="model-empty" style="font-size:0.72rem">Pick a project on the Board segment first.</div>';
      return;
    }
    host.innerHTML = '<div class="skeleton skeleton-line long"></div><div class="skeleton skeleton-line short"></div>';
    const name = _wsName(pid);
    // Probe the workspace — 404 means not bound yet.
    const probe = await Net.call('/api/workspaces/' + encodeURIComponent(name), { retries: 0, silent: true, init: { method: 'GET' } });
    if (!probe.ok) {
      _ws = null;
      _renderBind(host);
      return;
    }
    _ws = name;
    await _renderTree(host);
  }

  function _renderBind(host) {
    host.innerHTML = `
      <div class="proj-docs-bind">
        <div class="proj-docs-bind-h">No docs workspace bound</div>
        <p class="proj-docs-bind-sub">Bind a context directory to give this project an Obsidian-style docs
          workspace (index MOC, specs/, plans/, notes/status.md, decisions/log.md). Leave the path blank
          for the local default <code>data/projects/&lt;id&gt;/docs/</code>. A path inside an Obsidian vault is
          re-rooted at <code>00-Inbox/</code>.</p>
        <div class="proj-docs-bind-row">
          <input id="proj-docs-root" type="text" placeholder="/optional/path/or/blank-for-default" autocomplete="off">
          <button class="action-btn" data-action="proj.docs-bind">Bind context directory</button>
        </div>
        <div id="proj-docs-bind-err" class="admin-modal-error" hidden></div>
      </div>`;
  }

  async function bind() {
    const pid = _pid();
    if (!pid) return;
    const errBox = document.getElementById('proj-docs-bind-err');
    const rootEl = document.getElementById('proj-docs-root');
    const root = rootEl ? rootEl.value.trim() : '';
    try {
      const r = await Net.call('/api/projects/' + encodeURIComponent(pid) + '/context-workspace', {
        retries: 0,
        init: {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, AdminAuth.authHeaders()),
          body: JSON.stringify(root ? { root } : {}),
        },
      });
      if (!r.ok) {
        if (r.status === 401) throw new Error('Master key required — sign in as admin (Admin tab) to bind docs.');
        throw new Error(r.error || ('HTTP ' + r.status));
      }
      if (window.Toast) Toast.success('Docs bound', 'Workspace ' + ((r.data && r.data.workspace) || _wsName(pid)));
      await render();
    } catch (e) {
      if (errBox) { errBox.hidden = false; errBox.textContent = String(e); }
      else if (window.Toast) Toast.danger('Bind failed', String(e));
    }
  }

  async function _renderTree(host) {
    let files = [];
    try {
      const data = await Net.getJson('/api/workspaces/' + encodeURIComponent(_ws) + '/files?glob=**/*.md', { silent: true });
      files = (data && data.files) || [];
    } catch (_) { files = []; }
    files.sort();
    const tree = files.length
      ? files.map(f => `<li><button class="proj-docs-file${f === _file ? ' active' : ''}" data-action="proj.docs-open" data-path="${esc(f)}">${esc(f)}</button></li>`).join('')
      : '<li class="proj-hist-empty">No markdown files yet.</li>';
    host.innerHTML = `
      <div class="proj-docs">
        <div class="proj-docs-tree">
          <div class="proj-docs-tree-head">
            <span>${esc(_ws)}</span>
            <button class="action-btn xs ghost" data-action="proj.docs-refresh" title="Refresh">⟲</button>
          </div>
          <ul class="proj-docs-filelist">${tree}</ul>
          <div class="proj-docs-new">
            <input id="proj-docs-newname" type="text" placeholder="notes/new.md" autocomplete="off">
            <button class="action-btn xs" data-action="proj.docs-new">+ New</button>
          </div>
        </div>
        <div class="proj-docs-editor" id="proj-docs-editor">
          <div class="model-empty" style="font-size:0.72rem">Select a file to edit, or create one.</div>
        </div>
      </div>`;
    if (_file && files.includes(_file)) openFile(_file);
  }

  async function openFile(path) {
    if (!_ws || !path) return;
    _file = path;
    document.querySelectorAll('.proj-docs-file').forEach(b => b.classList.toggle('active', b.dataset.path === path));
    const ed = document.getElementById('proj-docs-editor');
    if (!ed) return;
    ed.innerHTML = '<div class="skeleton skeleton-line long"></div>';
    let content = '';
    try {
      const data = await Net.getJson('/api/workspaces/' + encodeURIComponent(_ws) + '/file?path=' + encodeURIComponent(path), { silent: true });
      content = (data && data.content) || '';
    } catch (e) {
      ed.innerHTML = '<div class="admin-modal-error">Couldn’t open ' + esc(path) + ' — ' + esc(String(e)) + '</div>';
      return;
    }
    ed.innerHTML = `
      <div class="proj-docs-editor-head">
        <span class="proj-docs-editor-path">${esc(path)}</span>
        <span style="flex:1"></span>
        <button class="action-btn xs primary" data-action="proj.docs-save">Save</button>
      </div>
      <textarea id="proj-docs-content" class="proj-docs-textarea" spellcheck="false">${esc(content)}</textarea>
      <div id="proj-docs-save-err" class="admin-modal-error" hidden></div>`;
    _dirty = false;
    const ta = document.getElementById('proj-docs-content');
    if (ta) ta.addEventListener('input', () => { _dirty = true; });
  }

  async function save() {
    if (!_ws || !_file) return;
    const ta = document.getElementById('proj-docs-content');
    const errBox = document.getElementById('proj-docs-save-err');
    if (!ta) return;
    try {
      const r = await Net.call('/api/workspaces/' + encodeURIComponent(_ws) + '/file', {
        retries: 0,
        init: {
          method: 'PUT',
          headers: Object.assign({ 'Content-Type': 'application/json' }, AdminAuth.authHeaders()),
          body: JSON.stringify({ path: _file, content: ta.value }),
        },
      });
      if (!r.ok) {
        if (r.status === 401) throw new Error('Master key required — sign in as admin to write docs.');
        throw new Error(r.error || ('HTTP ' + r.status));
      }
      _dirty = false;
      if (window.Toast) Toast.success('Saved', _file);
    } catch (e) {
      if (errBox) { errBox.hidden = false; errBox.textContent = String(e); }
      else if (window.Toast) Toast.danger('Save failed', String(e));
    }
  }

  async function newFile() {
    const nameEl = document.getElementById('proj-docs-newname');
    const rel = nameEl ? nameEl.value.trim() : '';
    if (!rel) { if (window.Toast) Toast.warn('Name required', 'e.g. notes/idea.md'); return; }
    const path = /\.md$/i.test(rel) ? rel : rel + '.md';
    try {
      const r = await Net.call('/api/workspaces/' + encodeURIComponent(_ws) + '/file', {
        retries: 0,
        init: {
          method: 'PUT',
          headers: Object.assign({ 'Content-Type': 'application/json' }, AdminAuth.authHeaders()),
          body: JSON.stringify({ path, content: '# ' + path.replace(/\.md$/i, '') + '\n\n' }),
        },
      });
      if (!r.ok) {
        if (r.status === 401) throw new Error('Master key required — sign in as admin to create docs.');
        throw new Error(r.error || ('HTTP ' + r.status));
      }
      _file = path;
      await _renderTree(_host());
    } catch (e) {
      if (window.Toast) Toast.danger('Create failed', String(e));
    }
  }

  function refresh() { if (_ws) _renderTree(_host()); else render(); }

  return { render, bind, openFile, save, newFile, refresh, isDirty: () => _dirty };
})();
