// library/plugins.js — Plugins library panel on the LibraryShell (LB5-U1).
//
// #tab-admin-plugins keeps its skeleton; the panel adopts the shell with
// adapter auth 'admin' (AdminAuth hard gate preserved — every backend read is
// master-key gated). Sidebar: Installed (layer chip origin:system|user +
// version badge — metadata, not an action) | Discovered (the persisted
// claude-marketplaces plugin digest: pointer-only records with license,
// component counts and diff badges). Selection rides data-id — the old
// title-text `.includes()` matching is retired. Discovered reads NEVER fetch
// (the provider feed is digest-backed); network runs only behind the visible
// ⟳ Digest button → POST /api/discover/claude-marketplaces/refresh.
//
// Plugin-vs-MCP split (the Claude Code strategy): the detail header carries a
// LOCAL CAPABILITY BUNDLE kind banner — plugins add LOCAL functionality
// (filesystem, local tools, skills, hooks) executed in-process; MCP
// EXTENDS/INTEGRATES external functionality. "External integration? → MCP"
// cross-links via LibraryShell.open — cross-link, never merged.
//
// LB1-U2 heritage kept intact: ToolFormKit re-exports (renderToolForm/
// _collectParams/_renderHistory names + tool-form-*/tool-param-*/
// tool-tester-run-*/tool-result-*/tool-history-* DOM ids) and the plugin-tool
// TestPane live mount (#plugin-test-pane) render inside the Overview section
// so the worked example (Plugins > websearch) keeps working unchanged. The
// old inline-onclick AssetPeek button is replaced on newly rendered rows by a
// delegated `plugins.peek` action (no inline handlers).
//
// Management plane (LB5-U2): user-layer plugins get a Files detail tab (async
// section renderer) over GET /api/plugins/{id}/files + GET/PUT .../files/{path}
// — system plugins are read-only image content (403 server-side, tab hidden
// here). Saves are atomic and version-bumped server-side (plugin.yaml is the
// source of truth); the PUT response {version, reload_required} raises a
// Reload badge whose button fires the existing POST /api/plugins/reload
// (in-process rescan — chat + tester pick the edit up next call). Delete
// stays Confirm-gated.
import { esc, renderMarkdown } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { AssetPeek } from './asset-peek.js';
import { LibraryShell } from './shell.js';
import { LibraryWizard } from './wizard.js';
import { TestPane, ToolFormKit } from './test-pane.js';

export const PluginsPanel = (function () {
  let _plugins = [];      // GET /api/plugins summaries (layer-annotated)
  let _digest = null;     // last GET /api/discover/claude-marketplaces read
  let _forgeSeed = null;  // staged seed for the LB5-U3 creation wizard
  // Plugin ids edited since the last reload — drives the Reload badge
  // (server truth is the PUT response's reload_required flag).
  const _reloadNeeded = new Set();

  const DISC_PREFIX = 'disc::';

  function _headers() { return LibraryShell.headers('plugin'); }
  function _selected() { return (LibraryShell.state('plugin') || {}).selected; }
  function _pluginRec(id) { return _plugins.find(p => p.id === id) || null; }
  function _isDisc(id) { return !!id && id.indexOf(DISC_PREFIX) === 0; }
  function _discRecord(id) {
    const rid = (id || '').slice(DISC_PREFIX.length);
    return ((_digest && _digest.items) || []).find(r => r.id === rid) || null;
  }
  function _oneLine(text, max) {
    const t = String(text || '').replace(/\s+/g, ' ').trim();
    const cap = max || 96;
    return t.length > cap ? t.slice(0, cap - 1) + '…' : t;
  }

  // The Claude Code plugin-vs-MCP separation, stated on every detail.
  function _kindBanner() {
    return `
      <div class="plugin-kind-banner" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;
           border:1px solid var(--border);border-left:2px solid var(--accent);
           padding:6px 10px;margin-bottom:10px;font-size:0.62rem;letter-spacing:0.06em">
        <span style="font-family:var(--mono);color:var(--accent);text-transform:uppercase">Local capability bundle</span>
        <span style="color:var(--text-muted)">runs in-process — filesystem, local tools, skills, hooks</span>
        <button type="button" class="btn-unstyled" data-action="plugins.goto-mcp"
          style="margin-left:auto;color:var(--accent);font-size:0.62rem;cursor:pointer"
          title="MCP servers EXTEND/INTEGRATE external functionality — separate surface, cross-linked">
          External integration? → MCP</button>
      </div>`;
  }

  function _kvGrid(rows) {
    return `<div style="display:grid;grid-template-columns:110px 1fr;gap:6px 12px;font-size:0.72rem;margin-bottom:10px">
      ${rows.map(([k, v]) => `<div style="color:var(--text-muted)">${esc(k)}</div><div>${v}</div>`).join('')}
    </div>`;
  }

  // ── LibraryShell adapter ────────────────────────────────────────────
  const adapter = LibraryShell.register({
    kind: 'plugin',
    tabId: 'admin-plugins',
    lockPanelId: 'admin-plugins',
    countBadgeId: 'plugins-count',
    listElId: 'plugins-list',
    detailElId: 'plugin-detail',
    labelElId: 'plugin-detail-label',
    auth: 'admin',                    // AdminAuth hard gate preserved
    selectAction: 'plugins.select',   // legacy row action id kept alive
    rowClass: 'plugin-card',          // legacy row class kept alive (only-add)
    emptyText: 'No plugins found in plugins/ directory.',
    emptyDiscoveredText: 'No digest yet — hit ⟳ Digest to fetch the pinned Claude marketplaces.',
    emptyDetailLabel: '// SELECT A PLUGIN',
    emptyDetailText: 'Select a plugin from the left to see its skills and tools.',
    title: 'Plugins',

    async load() {
      const r = await LibraryShell.fetch('plugin', '/api/plugins');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _plugins = Array.isArray(r.data) ? r.data : [];
      // Discovered digest — a READ of the persisted plugin digest (the
      // claude-marketplaces provider feed is digest-backed; this never
      // triggers network ingestion). Fail-soft: a dead read leaves the
      // Installed experience untouched.
      try {
        const d = await LibraryShell.fetch('plugin', '/api/discover/claude-marketplaces');
        if (d.ok && d.data && Array.isArray(d.data.items)) _digest = d.data;
      } catch (_) { /* digest stays as-was */ }
    },

    // Installed — layer chip (origin: system|user) + version badge ride the
    // LB0 row contract; selection is data-id (title matching retired).
    list() {
      return _plugins.map(p => {
        const badges = p.version ? [{ label: `v${p.version}`, cls: 'plugin-version-badge' }] : [];
        if (_reloadNeeded.has(p.id)) badges.push({ label: 'reload', cls: 'plugin-reload-badge' });
        return {
          id: p.id,
          title: p.name || p.id,
          meta: `${(p.skills || []).length} skill${(p.skills || []).length === 1 ? '' : 's'} · ${(p.tools || []).length} tool${(p.tools || []).length === 1 ? '' : 's'}`,
          group: '',
          provenance: (p.layer || p.origin) === 'user' ? 'user' : 'oob',
          blocks: ['tools', 'context'],
          tags: [],
          icon: 'plugin',
          chips: [{ label: p.layer || p.origin || 'system', cls: 'plugin-layer-chip' }],
          badges: badges,
          dot: { cls: p.error ? 'err' : 'up', title: p.error || 'registered' },
        };
      });
    },

    // Discovered — pointer-only records from the persisted digest, grouped
    // per marketplace repo, license + added/changed diff badges.
    discovered() {
      const items = (_digest && _digest.items) || [];
      return items.map(r => {
        const md = r.metadata || {};
        const badges = [{ label: md.license || 'unknown', cls: 'plugin-license-badge' }];
        if (md.diff === 'added') badges.push({ label: 'new', cls: 'lib-diff-new' });
        else if (md.diff === 'changed') badges.push({ label: 'updated', cls: 'lib-diff-update' });
        return {
          id: DISC_PREFIX + r.id,
          title: r.name || r.id,
          meta: _oneLine(r.description),
          group: md.repo || '',
          tags: ((md.manifest_entry || {}).keywords || []).filter(t => typeof t === 'string'),
          icon: 'plugin',
          chips: md.category ? [{ label: String(md.category) }] : [],
          badges,
        };
      });
    },

    // Legacy AssetPeek deep-dive, re-wired: delegated action on newly
    // rendered rows (the old inline onclick is retired).
    renderRowExtras(item) {
      if (_isDisc(item.id)) return null;
      const b = document.createElement('span');
      b.className = 'agent-tile-action';
      b.dataset.action = 'plugins.peek';
      b.dataset.id = item.id;
      b.title = 'Deep dive — tools, skills, identity';
      b.textContent = '⌕';
      return b;
    },

    detail(id) {
      if (_isDisc(id)) {
        return { sections: { overview: (el) => _renderDiscOverview(el, id) } };
      }
      const p = _pluginRec(id);
      const sections = { overview: (el) => _renderOverview(el, id) };
      // Files tab: user layer only — system plugins are read-only image
      // content (the backend 403s them; no tab beats a dead tab).
      if (p && (p.layer || p.origin) === 'user') {
        sections.files = (el) => _renderFiles(el, id);
      }
      return { sections };
    },

    actions(id) {
      if (!_isDisc(id)) {
        const p = _pluginRec(id);
        const isUser = !!p && (p.layer || p.origin) === 'user';
        const dirty = _reloadNeeded.has(id);
        return [
          { action: 'plugins.reload', verb: 'install', accent: dirty,
            label: dirty ? 'Reload required' : 'Reload plugins' },
          { action: 'plugins.delete', verb: 'delete', label: 'Delete',
            enabled: isUser,
            reason: isUser ? undefined : 'system-layer plugin — read-only image content' },
        ];
      }
      const rec = _discRecord(id);
      const nSkills = rec ? ((rec.install || {}).skills || []).length : 0;
      return [
        { action: 'plugins.view-manifest', label: 'View manifest', verb: 'test' },
        { action: 'plugins.import-skills', verb: 'install', accent: true,
          label: `Import skills${nSkills ? ` (${nSkills})` : ''}`,
          enabled: nSkills > 0,
          reason: nSkills ? undefined : 'no SKILL.md pointers in this record' },
        { action: 'plugins.seed-wizard', label: 'Seed wizard', verb: 'edit' },
      ];
    },
  });

  // ── Installed detail (Overview) ─────────────────────────────────────
  // Full payload per selection; skills/tools accordions + the plugin-tool
  // TestPane mount render here so the pre-shell worked example survives.
  async function _renderOverview(el, id) {
    const r = await LibraryShell.fetch('plugin', `/api/plugins/${encodeURIComponent(id)}`);
    if (!r.ok) {
      el.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed to load plugin (HTTP ${r.status})</div>`;
      return;
    }
    const p = r.data || {};
    const skillsHtml = (p.skills || []).map(s => `
      <details class="skill-accordion">
        <summary>
          <span style="flex:1">${esc(s.id)}</span>
          ${s.inject ? `<span class="inject-badge">${esc(s.inject)}</span>` : ''}
        </summary>
        <div class="body">${renderMarkdown(s.body || '*(no body)*')}</div>
      </details>
    `).join('');
    const toolsHtml = (p.tools || []).map(t => renderToolAccordion(p.id, t)).join('');

    el.innerHTML = `
      ${_kindBanner()}
      <div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:8px">
        <code>${esc(p.path || '')}</code> · ${esc(p.author || 'unknown author')}
        · v${esc(p.version || '?')} · <span class="lib-badge">${esc(p.layer || p.origin || 'system')}</span>
      </div>
      <div style="font-size:0.78rem;color:var(--text);margin-bottom:8px">
        ${esc(p.description || '')}
      </div>
      ${(p.skills || []).length ? `<div class="plugin-section-h">Skills</div>${skillsHtml}` : ''}
      ${(p.tools || []).length ? `<div class="plugin-section-h">Tools</div>${toolsHtml}` : ''}
      ${(p.tools || []).length ? '<div class="plugin-section-h">Test</div><div id="plugin-test-pane"></div>' : ''}
    `;
    // plugin-tool TestPane live mount (LB1-U2) — the layered harness (L0
    // saved settings / L1 skills / L3 schema form).
    const paneHost = el.querySelector('#plugin-test-pane');
    if (paneHost) TestPane.mount('plugin-tool', p.id, paneHost, { plugin: p });
  }

  // ── Files tab — management plane over the LB5-U2 file routes ────────
  // User layer only; async section renderer (invoked on first activation).
  async function _renderFiles(el, id) {
    const r = await LibraryShell.fetch('plugin', `/api/plugins/${encodeURIComponent(id)}/files`);
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Files failed: ${esc(detail)}</div>`;
      return;
    }
    const d = r.data || {};
    const files = d.files || [];
    const badge = _reloadNeeded.has(id)
      ? ' <span class="lib-badge plugin-reload-badge">reload required</span>' : '';
    el.innerHTML = `
      <div class="skills-tree-meta" style="margin:0 0 6px;display:block">
        ${files.length} file${files.length === 1 ? '' : 's'} · user layer ·
        v${esc(d.version || '?')}${badge} — saves are atomic; plugin.yaml version
        auto-bumps on the first save per reload cycle</div>
      <div class="skills-tree">${files.map(f => `
        <button type="button" class="btn-unstyled skills-tree-file" data-action="plugins.file-open"
          data-plugin="${esc(id)}" data-path="${esc(f.path)}">
          ${esc(f.path)} <span class="skills-tree-meta">${esc(String(f.size || 0))}b</span>
        </button>`).join('')}
      </div>
      <div id="plugin-file-editor" class="plugin-file-editor" hidden></div>`;
  }

  async function openFile(pluginId, path) {
    const box = document.getElementById('plugin-file-editor');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = '<div class="model-empty">Loading…</div>';
    const url = `/api/plugins/${encodeURIComponent(pluginId)}/files/` +
      String(path).split('/').map(encodeURIComponent).join('/');
    const r = await LibraryShell.fetch('plugin', url);
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      box.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(detail)}</div>`;
      return;
    }
    const d = r.data || {};
    box.innerHTML = `
      <div class="skills-tree-meta" style="margin:8px 0 2px;display:block">
        <code>${esc(d.path || path)}</code> · ${esc(String(d.size || 0))}b</div>
      <textarea id="plugin-file-body" rows="14" spellcheck="false"
        aria-label="File body">${esc(d.body || '')}</textarea>
      <div style="display:flex;justify-content:flex-end;gap:6px;margin-top:6px">
        <button type="button" class="action-btn accent" data-action="plugins.file-save"
          data-plugin="${esc(pluginId)}" data-path="${esc(d.path || path)}">Save</button>
      </div>`;
  }

  async function saveFile(pluginId, path) {
    const ta = document.getElementById('plugin-file-body');
    if (!ta) return;
    const url = `/api/plugins/${encodeURIComponent(pluginId)}/files/` +
      String(path).split('/').map(encodeURIComponent).join('/');
    // retries:0 — a save is a write; never double-fire.
    const r = await LibraryShell.fetch('plugin', url, {
      retries: 0,
      init: {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: ta.value }),
      },
    });
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      Toast.danger('Save failed', detail);
      return;
    }
    const d = r.data || {};
    if (d.reload_required) _reloadNeeded.add(pluginId);
    Toast.success(`Saved — v${d.version || '?'}`, 'Reload to activate the change.');
    // Reload badge on the actions row + sidebar row (editor stays open).
    LibraryShell.renderActions('plugin');
    LibraryShell.renderRows('plugin');
  }

  // Reload — existing POST /api/plugins/reload (in-process rescan; chat and
  // the tool tester read the same live singleton). Toast carries the counts;
  // the current plugin is re-selected so the detail reflects the rescan.
  async function reloadPlugins() {
    const cur = _selected();
    const r = await LibraryShell.fetch('plugin', '/api/plugins/reload', {
      retries: 0,
      init: { method: 'POST' },
    });
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      Toast.danger('Reload failed', detail);
      return;
    }
    _reloadNeeded.clear();
    const d = r.data || {};
    Toast.success('Plugins reloaded',
      `${d.plugins ?? '?'} plugins · ${d.skills ?? '?'} skills · ${d.tools ?? '?'} tools`);
    await load();
    if (cur && !_isDisc(cur)) select(cur);
  }

  // Delete — Confirm-gated (kept); user layer only (backend 403s system).
  async function deletePlugin(id) {
    const ok = await Confirm.ask({
      title: 'Delete plugin',
      body: `Delete user-layer plugin "${id}"? Its files under plugins/${id}/ are removed. This cannot be undone.`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    const r = await LibraryShell.fetch('plugin', `/api/plugins/${encodeURIComponent(id)}`, {
      retries: 0,
      init: { method: 'DELETE' },
    });
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      Toast.danger('Delete failed', detail);
      return;
    }
    _reloadNeeded.delete(id);
    const st = LibraryShell.state('plugin');
    if (st && st.selected === id) st.selected = null;
    Toast.success('Plugin deleted', id);
    await load();
  }

  // ── Discovered detail (Overview) ────────────────────────────────────
  function _renderDiscOverview(el, id) {
    const rec = _discRecord(id);
    if (!rec) {
      el.innerHTML = '<div class="model-empty">Not in the current digest — hit ⟳ Digest to refresh.</div>';
      return;
    }
    const md = rec.metadata || {};
    const comps = md.components || {};
    const compsLine = Object.entries(comps).filter(([, n]) => n)
      .map(([k, n]) => `${n} ${k}`).join(' · ') || '—';
    const licensed = String(md.license || 'unknown').toLowerCase();
    const licenseHtml = `<span class="lib-badge">${esc(md.license || 'unknown')}</span>` +
      (['mit', 'apache-2.0', 'bsd-2-clause', 'bsd-3-clause', '0bsd', 'isc',
        'mpl-2.0', 'cc0-1.0', 'cc-by-4.0', 'unlicense'].indexOf(licensed) === -1
        ? ' <span style="color:var(--amber);font-size:0.62rem">non-permissive / unknown — review before importing anything</span>'
        : '');
    const stale = md.fetched_at
      ? new Date(md.fetched_at * 1000).toLocaleString()
      : 'never';
    const diffHtml = md.diff === 'added' ? ' <span class="lib-badge lib-diff-new">new</span>'
      : md.diff === 'changed' ? ' <span class="lib-badge lib-diff-update">updated</span>' : '';
    el.innerHTML = `
      ${_kindBanner()}
      ${_kvGrid([
        ['Record', `<code>${esc(rec.id)}</code>`],
        ['Marketplace', `<code>${esc(md.repo || '?')}</code> @ <code>${esc(String(md.ref || '').slice(0, 12))}</code>`],
        ['Category', esc(md.category || '—')],
        ['Version', `${esc(rec.version || 'unknown')} <span class="lib-badge">${esc(md.version_resolution || 'unknown')}</span>`],
        ['License', licenseHtml],
        ['Components', esc(compsLine)],
        ['Digest', `fetched ${esc(stale)}${diffHtml}`],
        ['Description', esc(rec.description || '(none)')],
      ])}
      <div style="font-size:0.62rem;color:var(--text-muted)">
        Pointer-only record — nothing is installed until you import. Auto-conversion
        of Claude Code plugins into Enclave plugins is deliberately out of scope (v1);
        SKILL.md pointers bridge through the native skills importer.
      </div>
      <div id="plugin-manifest-view" style="margin-top:10px" hidden></div>`;
  }

  function viewManifest(id) {
    const rec = _discRecord(id || _selected());
    const view = document.getElementById('plugin-manifest-view');
    if (!rec || !view) return;
    if (!view.hidden) { view.hidden = true; return; }
    const md = rec.metadata || {};
    view.hidden = false;
    view.innerHTML = `
      <div class="skills-tree-meta" style="margin-bottom:4px">
        manifest entry · <a href="${esc(rec.url || '#')}" target="_blank" rel="noopener"
          style="color:var(--accent)">${esc(md.path || 'view upstream')}</a></div>
      <pre class="md-code" style="font-size:0.66rem;max-height:280px;overflow:auto">${esc(JSON.stringify(md.manifest_entry || {}, null, 2))}</pre>`;
  }

  // Import skills — license surfaced FIRST, then each SKILL.md pointer
  // bridges through the existing POST /api/skills/import into an installed
  // target plugin picked in the wizard.
  function importSkills(id) {
    const rec = _discRecord(id || _selected());
    if (!rec) return;
    const skills = (rec.install || {}).skills || [];
    if (!skills.length) { Toast.info('No skills', 'This record carries no SKILL.md pointers.'); return; }
    const lic = (rec.metadata || {}).license || 'unknown';
    const targets = _plugins.map(p => p.id);
    LibraryWizard.open({
      title: `Import skills — ${rec.name || rec.id}`,
      steps: {
        configure: (body) => {
          body.innerHTML = `
            <div class="admin-modal-sub" style="margin-bottom:8px">
              License: <span class="lib-badge">${esc(lic)}</span> — review the upstream
              terms before importing; the skill bodies are fetched verbatim.</div>
            <label class="admin-modal-label" for="plugins-import-target">Target plugin</label>
            <select id="plugins-import-target" data-wiz-key="plugin_id">
              ${targets.map(t => `<option value="${esc(t)}"${t === 'user-skills' ? ' selected' : ''}>${esc(t)}</option>`).join('')}
            </select>
            <div class="admin-modal-sub" style="margin-top:8px">
              ${skills.length} SKILL.md pointer${skills.length === 1 ? '' : 's'}:
              ${skills.map(s => `<code>${esc(s.name || s.path)}</code>`).join(' · ')}</div>`;
        },
      },
      validate: (step, state) =>
        (step !== 'confirm' || (state.values.plugin_id || '').trim()) ? true : 'pick a target plugin',
      submitLabel: 'Import',
      onSubmit: async (state) => {
        const target = (state.values.plugin_id || '').trim();
        let done = 0; const errors = [];
        for (const s of skills) {
          try {
            // retries:0 — import writes files + registration; never double-fire.
            const r = await Net.call('/api/skills/import', {
              retries: 0,
              init: {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ..._headers() },
                body: JSON.stringify({ url: s.skill_md_url, plugin_id: target }),
              },
            });
            if (r.ok) done += 1;
            else errors.push(`${s.name || s.path}: ${(r.data && r.data.detail) || `HTTP ${r.status}`}`);
          } catch (e) { errors.push(`${s.name || s.path}: ${e.message}`); }
        }
        await load();
        if (done && !errors.length) return { ok: true, message: `${done} skill(s) imported into ${target}.` };
        if (done) return { ok: true, message: `${done} imported, ${errors.length} failed — ${errors[0]}` };
        return { ok: false, detail: errors[0] || 'import failed' };
      },
    });
  }

  // Seed wizard — stages a digest record (name + description pre-filled) as
  // the seed for the plugin-creation wizard; the forge flow itself lands in
  // LB5-U3 and consumes the staged seed.
  function seedWizard(id) {
    const rec = _discRecord(id || _selected());
    if (!rec) return;
    LibraryWizard.open({
      title: 'Seed plugin wizard',
      steps: {
        configure: (body) => {
          body.innerHTML = `
            <label class="admin-modal-label" for="plugins-seed-name">Plugin name</label>
            <input id="plugins-seed-name" data-wiz-key="name" value="${esc(rec.name || '')}">
            <label class="admin-modal-label" for="plugins-seed-desc" style="margin-top:8px">Description</label>
            <textarea id="plugins-seed-desc" data-wiz-key="description" rows="4"
              style="width:100%">${esc(rec.description || '')}</textarea>
            <div class="admin-modal-sub" style="margin-top:8px">
              Stages this record as the seed for the local-model plugin forge —
              the creation wizard pre-fills from it.</div>`;
        },
      },
      submitLabel: 'Stage seed',
      onSubmit: async (state) => {
        _forgeSeed = {
          name: (state.values.name || rec.name || '').trim(),
          description: (state.values.description || rec.description || '').trim(),
          source_record: rec.id,
        };
        return { ok: true, message: 'Seed staged for the plugin forge.' };
      },
    });
  }

  function forgeSeed() { return _forgeSeed; }   // consumed by LB5-U3

  // Visible ⟳ Digest — the ONLY code path that triggers marketplace network
  // ingestion (operator-triggered POST, master-key gated, retries:0).
  async function refreshDigest() {
    Toast.info('Refreshing plugin digest…');
    try {
      const r = await Net.call('/api/discover/claude-marketplaces/refresh', {
        retries: 0,
        init: { method: 'POST', headers: _headers() },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.warn('Digest refresh degraded', detail);
      }
    } catch (e) { Toast.warn('Digest refresh degraded', e.message); }
    await load();
    const st = LibraryShell.state('plugin');
    if (st) { st.side = 'discovered'; st.chromeBuilt = false; }
    LibraryShell.renderSidebar('plugin');
    Toast.success('Plugin digest refreshed');
  }

  // ── Tool accordions + tester (LB1-U2 surface, unchanged) ────────────

  // Per-tool last-5 invocations kept in memory for this panel session.
  const _runHistory = new Map(); // key: `${pluginId}:${toolId}` → array of {ts, ms, status, body}

  function renderToolAccordion(pluginId, tool) {
    const key = `${pluginId}:${tool.id}`;
    return `
      <details class="tool-accordion">
        <summary>
          <span style="flex:1">${esc(tool.id)}</span>
          <span style="color:var(--text-muted);font-size:0.66rem">${esc(tool.description || '')}</span>
        </summary>
        <div class="body">
          <form id="tool-form-${esc(key)}" data-action="plugins.run-tool" data-plugin-id="${esc(pluginId)}" data-tool-id="${esc(tool.id)}">
            ${renderToolForm(tool)}
            <div style="display:flex;justify-content:flex-end;margin-top:10px">
              <button type="submit" id="tool-tester-run-${esc(key)}"
                class="admin-modal-btn primary" style="padding:6px 18px">Run</button>
            </div>
          </form>
          <div id="tool-result-${esc(key)}" style="margin-top:10px"></div>
          <div id="tool-history-${esc(key)}" style="margin-top:10px"></div>
        </div>
      </details>
    `;
  }

  // Extracted to ToolFormKit (test-pane.js) — same names, same behavior,
  // default idPrefix 'tool-param-' keeps the tester DOM ids intact.
  function renderToolForm(tool) {
    return ToolFormKit.renderToolForm(tool);
  }

  function _collectParams(tool) {
    return ToolFormKit.collectParams(tool);
  }

  async function runTool(pluginId, toolId) {
    const key = `${pluginId}:${toolId}`;
    const resultBox = document.getElementById('tool-result-' + key);
    const runBtn = document.getElementById('tool-tester-run-' + key);

    // Re-fetch the tool spec to pick up any param schema we cached.
    const detailR = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(pluginId)}`, {}, 'admin-plugins');
    if (!detailR.ok) { resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">Cannot load plugin (HTTP ${detailR.status})</div>`; return; }
    const plugin = await detailR.json();
    const tool = (plugin.tools || []).find(t => t.id === toolId);
    if (!tool) { resultBox.innerHTML = '<div class="admin-modal-error" style="margin:0">Tool not found.</div>'; return; }

    let params;
    try { params = _collectParams(tool); }
    catch (e) { resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`; return; }

    runBtn.disabled = true;
    runBtn.textContent = 'Running…';
    const t0 = performance.now();
    let r, body, status;
    try {
      r = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(pluginId)}/tools/${encodeURIComponent(toolId)}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(params),
      }, 'admin-plugins');
      const ms = Math.round(performance.now() - t0);
      status = r.status;
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        body = await r.json();
        resultBox.innerHTML = `
          <div style="font-size:0.66rem;color:var(--text-dim);margin-bottom:4px">
            ${ms} ms · status ${status}
          </div>
          <pre class="md-code" style="font-size:0.72rem;max-height:280px;overflow:auto">${esc(JSON.stringify(body, null, 2))}</pre>
        `;
      } else {
        body = await r.text();
        resultBox.innerHTML = `
          <div style="font-size:0.66rem;color:var(--text-dim);margin-bottom:4px">${ms} ms · status ${status}</div>
          <pre class="md-code">${esc(body)}</pre>
        `;
      }
      if (!r.ok) {
        resultBox.querySelector('pre').classList.add('error');
      }

      const hist = _runHistory.get(key) || [];
      hist.push({ts: Date.now(), ms, status, summary: typeof body === 'object' ? JSON.stringify(body).slice(0,80) : String(body).slice(0,80)});
      while (hist.length > 5) hist.shift();
      _runHistory.set(key, hist);
      _renderHistory(key);
    } catch (e) {
      resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = 'Run';
    }
  }

  function _renderHistory(key) {
    // Extracted to ToolFormKit.renderHistory — markup unchanged.
    ToolFormKit.renderHistory(
      document.getElementById('tool-history-' + key), _runHistory.get(key) || []);
  }

  // ── Panel API (signature-compatible with the pre-shell module) ──────
  function load() { return LibraryShell.reload('plugin'); }
  function refresh() { load(); }
  function select(id) { LibraryShell.select('plugin', id); }
  function renderDetail() { LibraryShell.renderDetail('plugin'); }

  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-plugins') load();
  });

  // Delegated actions — plugin rows + tool-tester forms re-render per
  // load/select; legacy ids stay alive as aliases over the shell flows.
  Actions.click({
    'plugins.select': el => select(el.dataset.id),
    'plugins.sub-tab': el => {
      const st = LibraryShell.state('plugin');
      if (!st) return;
      st.side = el.dataset.side === 'discovered' ? 'discovered' : 'installed';
      st.chromeBuilt = false;
      LibraryShell.renderSidebar('plugin');
    },
    'plugins.refresh-digest': () => refreshDigest(),
    'plugins.view-manifest': el => viewManifest(el.dataset.id),
    'plugins.import-skills': el => importSkills(el.dataset.id),
    'plugins.seed-wizard': el => seedWizard(el.dataset.id),
    'plugins.goto-mcp': () => LibraryShell.open('mcp'),
    'plugins.peek': el => AssetPeek.open('plugin', el.dataset.id),
    // LB5-U2 management plane
    'plugins.file-open': el => openFile(el.dataset.plugin, el.dataset.path),
    'plugins.file-save': el => saveFile(el.dataset.plugin, el.dataset.path),
    'plugins.reload': () => reloadPlugins(),
    'plugins.delete': el => deletePlugin(el.dataset.id),
  });
  Actions.on('submit', {
    'plugins.run-tool': (el, e) => {
      e.preventDefault();
      runTool(el.dataset.pluginId, el.dataset.toolId);
    }
  });

  return { load, refresh, select, renderDetail, renderToolAccordion,
           runTool, renderToolForm, _collectParams,
           refreshDigest, importSkills, seedWizard, viewManifest, forgeSeed,
           openFile, saveFile, reloadPlugins, deletePlugin,
           adapter };
})();
