// library/discover.js — Extension + Skills discovery (phase-2 U8 straggler).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryWizard } from './wizard.js';

// Announce a cross-kind inventory change without coupling this helper module
// to LibraryShell — the shell listens for this event and reloads the named
// kinds' badges/panels. Installing/uninstalling a skill writes into a plugin,
// so both the skill and plugin surfaces are affected.
function _announceInventory(kinds) {
  try {
    document.dispatchEvent(new CustomEvent('enclave:inventory-changed', { detail: { kinds } }));
  } catch (_) { /* non-DOM context (tests) — no-op */ }
}

export const ExtDiscover = (function () {
  async function _toggle(detailsEl) {
    if (!detailsEl.open) return;
    const source = detailsEl.dataset.source;
    if (!source) return;
    const body = document.getElementById('ext-prov-body-' + source);
    if (!body) return;
    // Cache the fetch in-memory per session — re-clicking doesn't
    // re-hit the network unless the operator explicitly refreshes.
    if (body.dataset.loaded === '1') return;
    body.innerHTML = `<div class="model-empty">Fetching…</div>`;
    try {
      const feed = await Net.getJson(`/api/discover/${encodeURIComponent(source)}`);
      body.innerHTML = _renderFeedBody(feed, source);
      body.dataset.loaded = '1';
    } catch (e) {
      body.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
    }
  }

  async function refresh(source) {
    const body = document.getElementById('ext-prov-body-' + source);
    if (!body) return;
    body.innerHTML = `<div class="model-empty">Refreshing…</div>`;
    delete body.dataset.loaded;
    try {
      const feed = await Net.getJson(`/api/discover/${encodeURIComponent(source)}?force=true`);
      body.innerHTML = _renderFeedBody(feed, source);
      body.dataset.loaded = '1';
    } catch (e) {
      body.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
    }
  }

  function _renderFeedBody(feed, source) {
    const head = `<div class="ext-feed-head">
      <span class="ext-feed-count">${feed.count || 0} items</span>
      ${feed.last_synced
        ? `<span class="ext-feed-synced">synced ${new Date(feed.last_synced * 1000).toLocaleTimeString()}</span>`
        : ''}
      <span style="flex:1"></span>
      <button class="action-btn xs ghost" data-action="ext.refresh" data-source="${esc(source)}">⟲ Refresh</button>
    </div>`;
    if (feed.error) {
      return `${head}
        <div class="ext-feed-error">
          <span class="ext-feed-error-icon">!</span>
          <span>${esc(feed.error)}</span>
        </div>`;
    }
    if (!feed.items || !feed.items.length) {
      return `${head}<div class="model-empty">Provider returned no items.</div>`;
    }
    const items = feed.items.slice(0, 50).map(_renderItem).join('');
    // Cap at 50 cards per provider, but say so — silent truncation reads
    // as "that's everything" when it isn't.
    const more = feed.items.length > 50
      ? `<div class="model-empty">Showing 50 of ${feed.items.length} — refine the search to narrow results.</div>`
      : '';
    return `${head}<div class="ext-item-grid">${items}</div>${more}`;
  }

  function _renderItem(it) {
    const kindClass = `ext-item-kind-${esc(it.kind || 'other')}`;
    const toolCount = (it.tools || []).length;
    // Installable skills (e.g. the skills.sh provider) carry a raw SKILL.md
    // URL the native importer accepts. Render an Install action so the
    // External-Sources surface matches the Skills catalog's install
    // affordance instead of being display-only.
    const skillUrl = (it.kind === 'skill' && it.install && it.install.skill_md_url)
      ? it.install.skill_md_url : '';
    const installBtn = skillUrl
      ? `<button class="action-btn xs accent"
                 onclick="ExtDiscover.installSkill('${esc(skillUrl)}','${esc(it.id)}',this)"
                 title="Install this skill into general-skills">+ Install</button>`
      : '';
    // Surface the CLI one-liner (npx skills add …) when present.
    const cmd = (it.install && it.install.command) ? it.install.command : '';
    const cmdChip = cmd
      ? `<code class="ext-item-id" style="opacity:.75" title="CLI install">${esc(cmd)}</code>`
      : '';
    return `<div class="ext-item">
      <div class="ext-item-head">
        <span class="ext-item-kind ${kindClass}">${esc(it.kind || 'item')}</span>
        <span class="ext-item-name">${esc(it.name)}</span>
        <span class="ext-item-version">${esc(it.version || '')}</span>
        <span style="flex:1"></span>
        ${installBtn}
      </div>
      <div class="ext-item-desc">${esc(it.description || '')}</div>
      <div class="ext-item-foot">
        <code class="ext-item-id">${esc(it.id)}</code>
        ${cmdChip}
        ${toolCount ? `<span class="ext-item-toolcount">${toolCount} tools</span>` : ''}
        ${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener" class="ext-item-link">↗</a>` : ''}
      </div>
    </div>`;
  }

  // Install a discovered skill (kind=skill) via the same native importer
  // the Skills catalog uses, then refresh the Skills surfaces so a skill
  // found under External Sources lands in the catalog identically.
  async function installSkill(skillMdUrl, id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const r = await fetch('/api/skills/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: skillMdUrl, plugin_id: 'general-skills', id }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
      // Hot-reload the plugin registry so the skill activates immediately.
      try { await fetch('/api/plugins/reload', { method: 'POST' }); } catch (_) {}
      if (btn) { btn.textContent = '✓ Installed'; btn.classList.remove('accent'); btn.disabled = true; }
      if (window.Toast) Toast.success('Skill installed', `${d.name || id} → general-skills`);
      // Keep the two surfaces consistent: reflect the install in the Skills
      // catalog section, the catalog counts, and the composer workbench.
      if (window.SkillsDiscover && typeof SkillsDiscover.load === 'function') { try { SkillsDiscover.load(true); } catch (_) {} }
      if (typeof loadCatalogPage === 'function') { try { loadCatalogPage(); } catch (_) {} }
      if (typeof loadComposerCatalogs === 'function') { try { loadComposerCatalogs(); } catch (_) {} }
      _announceInventory(['skill', 'plugin']);
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
      if (window.Toast) Toast.error('Install failed: ' + e.message);
      else alert('Install failed: ' + e.message);
    }
  }

  return { _toggle, refresh, installSkill };
})();

export const SkillsDiscover = (function () {
  let _data = null;
  let _loaded = false;
  // View mode — 'list' is the original dense card view, 'icons' is the
  // icon-explorer grid that leads with persona glyphs.
  let _view = 'list';

  async function load(force) {
    if (_loaded && !force) { render(); return; }
    const grid = document.getElementById('skills-discover-grid');
    if (grid) grid.innerHTML = '<div class="model-empty">Loading discoverable skills…</div>';
    try {
      _data = await Net.getJson('/api/skills/discover');
      _loaded = true;
      _populateCats();
      _setMeta(`${_data.count || 0} skills · updated ${_data.updated || '—'}`);
      render();
    } catch (e) {
      _setMeta('failed');
      if (grid) grid.innerHTML = `<div class="model-empty" style="color:var(--red)">Discover failed: ${esc(e.message)}</div>`;
    }
  }

  function _setMeta(text) {
    const m = document.getElementById('skills-discover-meta');
    if (m) m.textContent = text;
  }

  function _populateCats() {
    const sel = document.getElementById('skills-discover-cat');
    if (!sel || !_data) return;
    const cur = sel.value;
    const cats = Array.from(new Set((_data.skills || []).map(s => s.category).filter(Boolean))).sort();
    sel.innerHTML = '<option value="">All categories</option>' +
      cats.map(c => `<option value="${esc(c)}"${cur === c ? ' selected' : ''}>${esc(c)}</option>`).join('');
  }

  function render() {
    const grid = document.getElementById('skills-discover-grid');
    if (!grid || !_data) return;
    const q   = (document.getElementById('skills-discover-search')?.value || '').toLowerCase();
    const cat = (document.getElementById('skills-discover-cat')?.value || '');
    const items = (_data.skills || []).filter(s => {
      if (cat && s.category !== cat) return false;
      if (!q) return true;
      const hay = [s.id, s.name, s.description, ...(s.tags || []), ...(s.triggers || [])]
        .filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
    if (!items.length) {
      grid.innerHTML = '<div class="model-empty">No skills match the filter.</div>';
      return;
    }
    // View-mode router. Both renderers know how to handle the
    // already-filtered item list.
    grid.classList.toggle('view-icons', _view === 'icons');
    grid.innerHTML = _view === 'icons'
      ? _renderIconExplorer(items)
      : items.map(_card).join('');
  }

  function _card(s) {
    // Use the skill's declared persona for the icon block so the
    // visual carries over to wherever the skill ends up installed.
    const persona = s.persona || (window.AgentIcons ? AgentIcons.resolve({ name: s.name, description: s.description }) : 'skill');
    const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'amber');
    const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const triggers = (s.triggers || []).slice(0, 3).map(t => `<span class="cap-card-meta">${esc(t)}</span>`).join(' · ');
    // Source badge — remote marketplace entries are visually distinct.
    const sourceChip = (s.marketplace || s.source === 'remote')
      ? `<span class="skill-disc-chip marketplace" title="From a remote marketplace catalog">marketplace</span>`
      : '';
    const stateChip = sourceChip + (s.installed
      ? `<span class="skill-disc-chip installed" title="Already installed in ${esc((s.installed_in || []).join(', '))}">installed</span>`
      : (s.has_body
          ? `<span class="skill-disc-chip available">install</span>`
          : `<span class="skill-disc-chip bundled" title="Ships pre-installed with the platform">bundled</span>`));
    // Same .action-btn sizing/vocabulary as the Models catalog cards so the
    // install/remove experience reads identically across the product.
    const action = s.installed
      ? `<button class="action-btn sm danger" data-action="sdisc.uninstall">Remove</button>`
      : (s.has_body
          ? `<button class="action-btn sm accent" data-action="sdisc.install">Install</button>`
          : '');
    return `<div class="workbench-item agent-card cap-card skill-disc-card cap-skill" data-skill-id="${esc(s.id)}">
      <button type="button" class="btn-unstyled agent-card-head" title="Open detail" data-action="sdisc.detail">
        <span class="agent-card-icon tone-${esc(tone)}">${iconSvg}</span>
        <div class="agent-card-titleblock">
          <div class="agent-card-title">${esc(s.name)}</div>
          <div class="agent-card-subtitle">${esc(s.description || '')}</div>
        </div>
        ${stateChip}
      </button>
      <div class="cap-card-foot">
        <code class="cap-card-id">${esc(s.id)}</code>
        ${triggers ? `<span class="cap-card-meta">${triggers}</span>` : ''}
      </div>
      ${action ? `<div class="skill-disc-actions">${action}</div>` : ''}
    </div>`;
  }

  // Install → target-plugin choice through the LibraryWizard (LB3-U2 —
  // window.prompt() retired). Endpoint + payload byte-identical to the old
  // flow: POST /api/skills/discover/{id}/install {plugin_id}. Defaults to
  // general-skills since it's the catch-all bundle; operator can override.
  // onDone (optional) lets callers (the Skills library shell) refresh too.
  async function install(skillId, onDone) {
    const plugins = await _availablePlugins();
    const def = plugins.includes('general-skills') ? 'general-skills' : (plugins[0] || 'general-skills');
    LibraryWizard.open({
      title: `Install skill '${skillId}'`,
      submitLabel: 'Install',
      steps: {
        configure: (el, state) => {
          el.innerHTML = `
            <div class="admin-modal-sub">Copies the catalog SKILL.md into the chosen plugin and registers it.</div>
            <label class="admin-modal-label" for="skills-install-plugin">Target plugin</label>
            <input id="skills-install-plugin" type="text" data-wiz-key="plugin_id" autocomplete="off"
              list="skills-install-plugin-options" placeholder="general-skills">
            <datalist id="skills-install-plugin-options">
              ${plugins.map(p => `<option value="${esc(p)}"></option>`).join('')}
            </datalist>`;
          const inp = el.querySelector('#skills-install-plugin');
          if (inp) inp.value = state.values.plugin_id || def;
        },
      },
      validate: (stepId, state) => {
        if (stepId !== 'configure') return true;
        return (state.values.plugin_id || '').trim() ? true : 'Target plugin required';
      },
      onSubmit: async (state) => {
        const target = (state.values.plugin_id || '').trim() || def;
        // retries:0 — install writes skill files; don't double-install.
        const r = await Net.call(`/api/skills/discover/${encodeURIComponent(skillId)}/install`, {
          retries: 0,
          init: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin_id: target }),
          },
        });
        if (!r.ok) {
          const body = typeof r.data === 'string'
            ? r.data : ((r.data && r.data.detail) || r.error || '');
          return { ok: false, detail: body || `HTTP ${r.status}` };
        }
        if (window.Toast) Toast.success('Skill installed', `${skillId} → ${target}`);
        await load(true);
        // Refresh the workbench so the newly installed skill appears in the
        // composer's Skills tab without a full page reload.
        if (typeof loadComposerCatalogs === 'function') loadComposerCatalogs();
        if (onDone) { try { onDone(); } catch (_) {} }
        _announceInventory(['skill', 'plugin']);
        return { ok: true, message: `${skillId} → ${target}` };
      },
    });
  }

  async function uninstall(skillId, pluginId) {
    if (!pluginId) {
      Toast.warn('Could not determine target plugin');
      return;
    }
    const ok = await Confirm.ask({ title: 'Uninstall skill', body: `Uninstall '${skillId}' from '${pluginId}'? This deletes the skill .md and removes the registration.`, okLabel: 'Uninstall', danger: true });
    if (!ok) return;
    const r = await Net.call(`/api/skills/discover/${encodeURIComponent(skillId)}/uninstall?plugin_id=${encodeURIComponent(pluginId)}`, { retries: 0, init: { method: 'DELETE' } });
    if (!r.ok) {
      const body = typeof r.data === 'string' ? r.data : (r.error || '');
      Toast.danger('Uninstall failed', body || `HTTP ${r.status}`);
      return;
    }
    if (window.Toast) Toast.success('Skill uninstalled', `${skillId} ↛ ${pluginId}`);
    await load(true);
    if (typeof loadComposerCatalogs === 'function') loadComposerCatalogs();
    _announceInventory(['skill', 'plugin']);
  }

  async function _availablePlugins() {
    try {
      const data = await Net.getJson('/api/plugins', { silent: true });
      const list = Array.isArray(data) ? data : (data.plugins || []);
      return list.map(p => p.id).filter(Boolean);
    } catch { return []; }
  }

  function setView(v) {
    if (v !== 'list' && v !== 'icons') return;
    _view = v;
    document.querySelectorAll('.skills-disc-view').forEach(b => {
      b.classList.toggle('active', b.dataset.view === v);
    });
    render();
  }

  // Browse every skill in a GitHub repo (skills.sh repos are at
  // skills.sh/<owner>/<repo>) and install any of them. The repo choice rides
  // the LibraryWizard (window.prompt() retired); the listing keeps its
  // existing modal + endpoints (GET /api/skills/github, POST /api/skills/import).
  async function browseGithubRepo(repoArg) {
    if (!repoArg) {
      LibraryWizard.open({
        title: 'Browse a GitHub skills repo',
        submitLabel: 'Browse',
        steps: {
          source: (el, state) => {
            el.innerHTML = `
              <div class="admin-modal-sub">Lists every SKILL.md in the repo; installs go to <code>general-skills</code>.</div>
              <label class="admin-modal-label" for="skills-browse-repo">GitHub repo (owner/repo)</label>
              <input id="skills-browse-repo" type="text" data-wiz-key="repo" autocomplete="off"
                placeholder="anthropics/skills">`;
            const inp = el.querySelector('#skills-browse-repo');
            if (inp) inp.value = state.values.repo || 'anthropics/skills';
          },
        },
        validate: (stepId, state) => {
          if (stepId !== 'source') return true;
          return /^[\w.-]+\/[\w.-]+$/.test((state.values.repo || '').trim())
            ? true : 'Use the owner/repo form';
        },
        onSubmit: async (state) => {
          const repo = (state.values.repo || '').trim();
          // Open the listing modal after the wizard's submit cycle settles —
          // closing the wizard mid-submit would null its flow state.
          setTimeout(() => { LibraryWizard.close(); browseGithubRepo(repo); }, 0);
          return { ok: true, message: `Loading ${repo}…` };
        },
      });
      return;
    }
    const repo = repoArg;
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:min(680px,94vw);max-height:88vh;overflow-y:auto;border-radius:6px;';
    inner.innerHTML = '<div class="model-empty">Loading repo skills…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
    try {
      // getJson's thrown message already prefers the body's detail/error
      // field, matching the old d.detail || HTTP-status throw.
      const d = await Net.getJson('/api/skills/github?repo=' + encodeURIComponent(repo.trim()));
      const rows = (d.skills || []).map(s => `
        <div class="gh-skill-row">
          <div class="gh-skill-info">
            <div class="gh-skill-name">${esc(s.name)}</div>
            <div class="gh-skill-desc">${esc(s.description || s.path || '')}</div>
          </div>
          <button class="action-btn sm accent" data-action="sdisc.gh-install" data-raw-url="${esc(s.raw_url)}" data-skill-id="${esc(s.id)}">Install</button>
        </div>`).join('');
      inner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="font-family:var(--mono);font-weight:600;flex:1">${esc(d.repo)} <span style="color:var(--text-muted);font-weight:400">· ${d.count} skill${d.count === 1 ? '' : 's'}</span></div>
          <button class="action-btn xs ghost" data-action="sdisc.close">×</button>
        </div>
        <div style="font-size:0.64rem;color:var(--text-muted);margin-bottom:10px">Installs go to <code>general-skills</code> and activate immediately.</div>
        <div class="gh-skills">${rows || '<div class="model-empty">No SKILL.md files found in this repo.</div>'}</div>`;
    } catch (e) {
      inner.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
    }
  }

  async function _installGithub(rawUrl, id, btn) {
    btn.disabled = true; btn.textContent = '…';
    try {
      // retries:0 — import writes a skill file; don't double-install.
      await Net.postJson('/api/skills/import', { url: rawUrl, plugin_id: 'general-skills', id }, { retries: 0 });
      try { await Net.postJson('/api/plugins/reload', {}, { retries: 0, silent: true }); } catch (_) {}
      btn.textContent = '✓ Installed'; btn.classList.remove('accent');
      load(true);
      _announceInventory(['skill', 'plugin']);
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Retry';
      if (window.Toast) Toast.danger('Install failed', e.message);
    }
  }

  // Import a SKILL.md from a URL (skills.sh entries are GitHub-backed — grab
  // the SKILL.md's GitHub link). URL + target plugin ride the LibraryWizard
  // (window.prompt() retired); endpoints byte-identical: POST
  // /api/skills/import {url, plugin_id} then POST /api/plugins/reload.
  // onDone (optional) lets the Skills library shell refresh after import.
  async function importFromUrl(onDone) {
    LibraryWizard.open({
      title: 'Import SKILL.md from URL',
      submitLabel: 'Import',
      steps: {
        source: (el, state) => {
          el.innerHTML = `
            <div class="admin-modal-sub">A GitHub raw or blob link — e.g. from a skills.sh skill. Frontmatter is parsed server-side.</div>
            <label class="admin-modal-label" for="skills-import-url">SKILL.md URL</label>
            <input id="skills-import-url" type="text" data-wiz-key="url" autocomplete="off"
              placeholder="https://raw.githubusercontent.com/…/SKILL.md">`;
          const inp = el.querySelector('#skills-import-url');
          if (inp) inp.value = state.values.url || '';
        },
        configure: (el, state) => {
          el.innerHTML = `
            <label class="admin-modal-label" for="skills-import-plugin">Install into plugin</label>
            <input id="skills-import-plugin" type="text" data-wiz-key="plugin_id" autocomplete="off"
              placeholder="general-skills">`;
          const inp = el.querySelector('#skills-import-plugin');
          if (inp) inp.value = state.values.plugin_id || 'general-skills';
        },
      },
      validate: (stepId, state) => {
        if (stepId === 'source' && !(state.values.url || '').trim()) return 'URL required';
        if (stepId === 'configure' && !(state.values.plugin_id || '').trim()) return 'Target plugin required';
        return true;
      },
      onSubmit: async (state) => {
        const url = (state.values.url || '').trim();
        const plugin = (state.values.plugin_id || '').trim() || 'general-skills';
        _setMeta('Importing…');
        try {
          // retries:0 — import writes a skill file; don't double-install.
          const d = await Net.postJson('/api/skills/import', { url, plugin_id: plugin }, { retries: 0 });
          // Hot-reload the plugin registry so the skill activates immediately —
          // no API restart. The chat path reads the same live registry.
          let active = false;
          try { active = (await Net.call('/api/plugins/reload', { retries: 0, silent: true, init: { method: 'POST' } })).ok; } catch (_) {}
          const msg = `Imported "${d.name || d.skill_id}" → ${d.plugin_id}` + (active ? ' — active now.' : ' (reload to activate).');
          Toast.info(msg);
          load(true);
          if (onDone) { try { onDone(); } catch (_) {} }
          _announceInventory(['skill', 'plugin']);
          return { ok: true, message: msg };
        } catch (e) {
          _setMeta('');
          return { ok: false, detail: e.message };
        }
      },
    });
  }

  // Icon-explorer renderer — groups skills by persona (their primary
  // visual axis), with a large icon tile per skill. Each tile carries
  // an install/uninstall affordance.
  function _renderIconExplorer(items) {
    const groups = {};
    items.forEach(s => {
      const persona = s.persona ||
        (window.AgentIcons ? AgentIcons.resolve({ name: s.name, description: s.description }) : 'general');
      (groups[persona] = groups[persona] || []).push(s);
    });
    const order = Object.keys(groups).sort();
    return order.map(p => {
      const tone = (window.AgentIcons ? AgentIcons.tone(p) : 'accent');
      const skillsIn = groups[p].sort((a, b) => a.id.localeCompare(b.id));
      const tiles = skillsIn.map(s => {
        const icon = (window.AgentIcons ? AgentIcons.svg(p) : '');
        const action = s.installed
          ? `<button class="skill-tile-action uninstall" data-action="sdisc.uninstall" title="Uninstall this skill">−</button>`
          : (s.has_body
              ? `<button class="skill-tile-action install" data-action="sdisc.install" title="Install this skill">+</button>`
              : '');
        const stateClass = s.installed ? 'installed' : (s.has_body ? 'available' : 'bundled');
        return `<div class="skill-tile ${stateClass}" data-skill-id="${esc(s.id)}"
                     title="${esc(s.name)} — ${esc(s.description || '')}">
          <span class="skill-tile-icon tone-${esc(tone)}">${icon}</span>
          <span class="skill-tile-label">${esc(s.name)}</span>
          <span class="skill-tile-state">${esc(stateClass)}</span>
          ${action}
        </div>`;
      }).join('');
      return `<div class="skill-icon-group">
        <div class="skill-icon-group-head">
          <span class="skill-icon-group-icon tone-${esc(tone)}">${window.AgentIcons ? AgentIcons.svg(p) : ''}</span>
          <span class="skill-icon-group-name">${esc(p)}</span>
          <span class="skill-icon-group-count">${skillsIn.length}</span>
        </div>
        <div class="skill-icon-tiles">${tiles}</div>
      </div>`;
    }).join('');
  }

  // Deep-dive — expand a skill into its full SKILL.md body. Installed skills
  // open editable (saved in place via PUT /source + a live plugin reload);
  // catalog/remote skills are read-only previews of the body that would land
  // on install. Mirrors the Models/Workflows deep-dive pattern.
  async function openDetail(skillId) {
    const s = (_data?.skills || []).find(x => x.id === skillId);
    if (!s) return;
    const persona = s.persona || (window.AgentIcons ? AgentIcons.resolve({ name: s.name, description: s.description }) : 'skill');
    const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'amber');
    const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const plugin  = (s.installed_in || [])[0] || '';

    const modal = document.createElement('div');
    modal.className = 'skill-detail-overlay';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);width:min(780px,95vw);max-height:90vh;display:flex;flex-direction:column;border-radius:8px;overflow:hidden';
    inner.innerHTML = '<div class="model-empty" style="padding:28px">Loading skill…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);

    // Resolve the body: installed → on-disk editable source; else catalog body.
    let body = '', editable = false, srcPlugin = plugin;
    try {
      if (s.installed && plugin) {
        const r = await Net.call(`/api/skills/source/${encodeURIComponent(skillId)}?plugin_id=${encodeURIComponent(plugin)}`, { silent: true });
        if (r.ok) { const d = r.data; body = d.body || ''; editable = true; srcPlugin = d.plugin_id || plugin; }
      }
      if (!body) {
        const r = await Net.call(`/api/skills/discover/${encodeURIComponent(skillId)}`, { silent: true });
        if (r.ok) { const d = r.data; body = d.skill_md || ''; }
      }
    } catch (_) {}

    const triggers = (s.triggers || []).map(t => `<span class="cap-card-meta">${esc(t)}</span>`).join(' · ');
    const stateLabel = s.installed
      ? `installed${plugin ? ' · ' + esc(plugin) : ''}`
      : (s.marketplace || s.source === 'remote' ? 'marketplace' : (s.has_body ? 'available' : 'bundled'));
    const removeBtn = (s.installed && plugin)
      ? `<button class="action-btn sm danger" data-action="sdisc.overlay-uninstall" data-skill-id="${esc(skillId)}" data-plugin="${esc(plugin)}">Remove</button>` : '';
    const installBtn = (!s.installed && s.has_body)
      ? `<button class="action-btn sm accent" data-action="sdisc.overlay-install" data-skill-id="${esc(skillId)}">Install</button>` : '';
    const editControls = editable
      ? `<button class="action-btn sm" id="skill-edit-toggle" data-action="sdisc.edit-toggle">Edit</button>` : '';

    inner.innerHTML = `
      <div style="display:flex;align-items:flex-start;gap:11px;padding:16px 18px;border-bottom:1px solid var(--border)">
        <span class="agent-card-icon tone-${esc(tone)}" style="flex:0 0 auto">${iconSvg}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:650;font-size:0.96rem">${esc(s.name || skillId)}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px">${esc(s.description || '')}</div>
          <div style="display:flex;gap:8px;align-items:center;margin-top:7px;flex-wrap:wrap">
            <code class="cap-card-id">${esc(skillId)}</code>
            <span class="skill-disc-chip ${s.installed ? 'installed' : (s.has_body ? 'available' : 'bundled')}">${stateLabel}</span>
            ${triggers ? `<span class="cap-card-meta">${triggers}</span>` : ''}
          </div>
        </div>
        <button class="action-btn xs ghost" data-action="sdisc.overlay-close">×</button>
      </div>
      <div style="flex:1;min-height:0;overflow:auto;padding:14px 18px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:0.64rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-muted)">SKILL.md ${editable ? '' : '· read-only'}</span>
          <span id="skill-edit-status" style="font-size:0.64rem;color:var(--text-muted)"></span>
        </div>
        <textarea id="skill-detail-body" readonly spellcheck="false"
          style="width:100%;min-height:340px;font-family:var(--mono);font-size:0.72rem;line-height:1.5;background:var(--bg-deep);color:var(--text);border:1px solid var(--border-strong);border-radius:5px;padding:11px;resize:vertical;box-sizing:border-box">${esc(body || '(no body — this entry ships pre-bundled in the plugin)')}</textarea>
      </div>
      <div style="display:flex;gap:8px;align-items:center;padding:12px 18px;border-top:1px solid var(--border)">
        ${editControls}
        <span id="skill-edit-save-wrap" style="display:none;gap:8px">
          <button class="action-btn sm accent" id="skill-edit-save" data-action="sdisc.edit-save" data-skill-id="${esc(skillId)}" data-plugin="${esc(srcPlugin)}">Save &amp; reload</button>
          <button class="action-btn sm ghost" data-action="sdisc.edit-cancel">Cancel</button>
        </span>
        <span style="flex:1"></span>
        ${installBtn}${removeBtn}
      </div>`;
    SkillsDiscover._detailOrig = body;
  }

  function _toggleEdit() {
    const ta = document.getElementById('skill-detail-body');
    const toggle = document.getElementById('skill-edit-toggle');
    const saveWrap = document.getElementById('skill-edit-save-wrap');
    if (!ta) return;
    ta.readOnly = false;
    ta.focus();
    if (toggle) toggle.style.display = 'none';
    if (saveWrap) saveWrap.style.display = 'inline-flex';
    const st = document.getElementById('skill-edit-status');
    if (st) st.textContent = 'editing — unsaved';
  }

  function _cancelEdit() {
    const ta = document.getElementById('skill-detail-body');
    if (ta && typeof SkillsDiscover._detailOrig === 'string') ta.value = SkillsDiscover._detailOrig;
    if (ta) ta.readOnly = true;
    const toggle = document.getElementById('skill-edit-toggle');
    const saveWrap = document.getElementById('skill-edit-save-wrap');
    if (toggle) toggle.style.display = '';
    if (saveWrap) saveWrap.style.display = 'none';
    const st = document.getElementById('skill-edit-status');
    if (st) st.textContent = '';
  }

  async function _saveEdit(skillId, pluginId) {
    const ta = document.getElementById('skill-detail-body');
    const save = document.getElementById('skill-edit-save');
    const st = document.getElementById('skill-edit-status');
    if (!ta) return;
    const newBody = ta.value;
    if (!newBody.trim()) { if (window.Toast) Toast.danger('Skill body cannot be empty'); return; }
    if (save) { save.disabled = true; save.textContent = 'Saving…'; }
    try {
      // retries:0 — PUT rewrites the skill file; don't double-apply.
      const r = await Net.call(`/api/skills/source/${encodeURIComponent(skillId)}`, {
        retries: 0,
        init: {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plugin_id: pluginId, body: newBody }),
        },
      });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      // Hot-reload so the edited skill activates immediately for chat.
      let active = false;
      try { active = (await Net.call('/api/plugins/reload', { retries: 0, silent: true, init: { method: 'POST' } })).ok; } catch (_) {}
      SkillsDiscover._detailOrig = newBody;
      ta.readOnly = true;
      const toggle = document.getElementById('skill-edit-toggle');
      const saveWrap = document.getElementById('skill-edit-save-wrap');
      if (toggle) toggle.style.display = '';
      if (saveWrap) saveWrap.style.display = 'none';
      if (st) st.textContent = active ? 'saved — active now' : 'saved (reload to activate)';
      if (window.Toast) Toast.success('Skill saved', `${skillId} → ${pluginId}`);
      load(true);
    } catch (e) {
      if (window.Toast) Toast.danger('Save failed', e.message);
      if (st) st.textContent = 'save failed';
    } finally {
      if (save) { save.disabled = false; save.textContent = 'Save & reload'; }
    }
  }

  // Delegated actions — the discover grid re-renders per keystroke, so
  // cards/tiles carry data-action and resolve the skill id via the closest
  // data-skill-id host. The (s.installed_in||[])[0] target-plugin lookup
  // lives here against module state instead of being interpolated into
  // attribute strings. Registered inside the module for _data access.
  const _skillIdOf = el => {
    const host = el.closest('[data-skill-id]');
    return host ? host.dataset.skillId : '';
  };
  const _installedPluginOf = id => {
    const s = ((_data && _data.skills) || []).find(x => x.id === id);
    return (s && (s.installed_in || [])[0]) || '';
  };
  const _overlayOf = el => el.closest('.skill-detail-overlay');
  Actions.click({
    'sdisc.install':    el => install(_skillIdOf(el)),
    'sdisc.uninstall':  el => uninstall(_skillIdOf(el), _installedPluginOf(_skillIdOf(el))),
    'sdisc.detail':     el => openDetail(_skillIdOf(el)),
    'sdisc.gh-install': el => _installGithub(el.dataset.rawUrl, el.dataset.skillId, el),
    'sdisc.close':      el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); },
    'sdisc.overlay-close':     el => { const o = _overlayOf(el); if (o) o.remove(); },
    'sdisc.overlay-install':   el => { install(el.dataset.skillId); const o = _overlayOf(el); if (o) o.remove(); },
    'sdisc.overlay-uninstall': el => { uninstall(el.dataset.skillId, el.dataset.plugin); const o = _overlayOf(el); if (o) o.remove(); },
    'sdisc.edit-toggle': () => _toggleEdit(),
    'sdisc.edit-save':   el => _saveEdit(el.dataset.skillId, el.dataset.plugin),
    'sdisc.edit-cancel': () => _cancelEdit()
  });

  return { load, render, install, uninstall, setView, importFromUrl, browseGithubRepo, _installGithub,
           openDetail, _toggleEdit, _cancelEdit, _saveEdit };
})();
