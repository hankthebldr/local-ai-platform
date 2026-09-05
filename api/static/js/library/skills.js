// library/skills.js — Skills library panel on the LibraryShell (LB3-U2).
//
// #tab-admin-skills rebuilt on the shell, adapter auth 'admin' — HONEST about
// the backend: every data source this panel reads (/api/plugins,
// /api/skills/discover, /github, /source) is master-key gated server-side, so
// an 'optional' tier claiming per-layer degradation would be indistinguishable
// from a wall. Sidebar: Installed (collapsible per-plugin groups) | Discovered
// (Bundled / Marketplace / Remote from GET /api/skills/discover — a read of
// the persisted/cached catalog, never a fetch trigger). Calm rows via the LB0
// row contract (persona icon, name, one-line description, ≤3 trigger chips
// + `+n`, one source badge); status pip / inject mode / content preview all
// moved into detail. Drill-down: Overview (kv-grid + rendered SKILL.md),
// Files (LB3-U1 tree + file endpoints, per-node async), Relations ("works
// with XYZ"), Examples (frontend-parsed ## Example(s)/## Usage), Test (LB1
// skill adapter — trigger dry-run). Actions preserved: Edit source (PUT +
// plugin reload), Uninstall (Confirm), Seed chat, Install/Import-URL via
// LibraryWizard (endpoints byte-identical, window.prompt() retired in
// discover.js), Browse GitHub repo, New Skill (SkillsBuilder), and Promote
// (skills.promote → POST /api/skills/{id}/promote, Confirm-gated).
//
// No inline handlers, no new window globals (the pre-existing window.SkillsPanel
// bridge in main.js is a static-HTML guard, kept alive). The old local esc()
// shadow is deleted — core/dom.js esc is the one escaper.
import { esc, renderMarkdown } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { TestPane } from './test-pane.js';
import { SkillsDiscover } from './discover.js';
import { flattenSkills, skillKey } from './skills-data.js';

export const SkillsPanel = (function () {
  let _items = [];        // flattened installed skills (skills-data.js shape)
  let _discover = null;   // GET /api/skills/discover payload (fail-soft)
  let _editing = false;

  const DISC_PREFIX = 'disc::';

  function _headers() { return LibraryShell.headers('skill'); }
  function _selected() { return (LibraryShell.state('skill') || {}).selected; }
  function _item(id) {
    return _items.find(x => skillKey(x.plugin_id, x.skill_id) === id) || null;
  }
  function _isDisc(id) { return !!id && id.indexOf(DISC_PREFIX) === 0; }
  function _discRecord(id) {
    const sid = (id || '').slice(DISC_PREFIX.length);
    return ((_discover && _discover.skills) || []).find(s => s.id === sid) || null;
  }
  function _persona(it) {
    return it.persona ||
      (window.AgentIcons
        ? AgentIcons.resolve({ name: it.name, description: it.description })
        : 'skill');
  }
  function _oneLine(text, max) {
    const t = String(text || '').replace(/\s+/g, ' ').trim();
    const cap = max || 96;
    return t.length > cap ? t.slice(0, cap - 1) + '…' : t;
  }
  function _keywords(triggers) {
    return (triggers || [])
      .map(t => (t && t.keyword) || (t && t.manual ? 'manual' : ''))
      .filter(Boolean);
  }
  function _triggerChips(triggers) {
    const kws = _keywords(triggers);
    const chips = kws.slice(0, 3).map(k => ({ label: k }));
    if (kws.length > 3) chips.push({ label: `+${kws.length - 3}`, cls: 'more' });
    return chips;
  }

  // ── LibraryShell adapter ────────────────────────────────────────────
  const adapter = LibraryShell.register({
    kind: 'skill',
    tabId: 'admin-skills',
    lockPanelId: 'admin-skills',
    countBadgeId: 'skills-count',
    listElId: 'skills-list',
    detailElId: 'skill-detail',
    labelElId: 'skill-detail-label',
    auth: 'admin',                    // honest tier — backend fully gated (F12)
    selectAction: 'skills.select',    // legacy row action id kept alive
    emptyText: 'No skills installed. Add one under plugins/<plugin>/skills/.',
    emptyDiscoveredText: 'Nothing discovered — hit ⟳ Discover to re-read the catalogs.',
    emptyDetailLabel: '// SELECT A SKILL',
    emptyDetailText: 'Select a skill on the left to read its body, files, relations, and examples — or dry-run its triggers in the Test tab.',
    title: 'Skills',

    async load() {
      const r = await LibraryShell.fetch('skill', '/api/plugins');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _items = flattenSkills(Array.isArray(r.data) ? r.data : []);
      // Discovered tab data — fail-soft: a dead catalog read leaves the
      // Installed experience untouched.
      try {
        const d = await LibraryShell.fetch('skill', '/api/skills/discover');
        if (d.ok && d.data && Array.isArray(d.data.skills)) _discover = d.data;
      } catch (_) { /* discover stays as-was */ }
    },

    // Installed — calm cards, grouped per plugin. The shell's own
    // `.lib-filter` search is now the ONE filter (MS-4 retired the duplicate
    // legacy plugin/role selects that used to narrow this list).
    list() {
      return _items
        .map(it => ({
          id: skillKey(it.plugin_id, it.skill_id),
          title: it.name,
          meta: _oneLine(it.description),
          group: it.plugin_id,
          provenance: it.plugin_layer === 'user' ? 'user' : 'oob',
          blocks: ['context'],
          tags: _keywords(it.triggers),
          icon: _persona(it),
          chips: _triggerChips(it.triggers),
          badges: [{ label: it.plugin_layer, cls: 'skills-src' }],
        }));
    },

    // Discovered — Bundled / Marketplace / Remote groups from the last
    // /api/skills/discover read (the visible ⟳ Refresh re-reads it).
    discovered() {
      const skills = (_discover && _discover.skills) || [];
      return skills.map(s => {
        const remote = !!(s.marketplace || s.source === 'remote');
        const bundled = !!s.bundled || (s.installed && !s.has_body && !remote);
        const group = remote ? 'Remote' : (bundled ? 'Bundled' : 'Marketplace');
        const state = s.installed ? 'installed' : (s.has_body ? 'install' : 'bundled');
        return {
          id: DISC_PREFIX + s.id,
          title: s.name || s.id,
          meta: _oneLine(s.description),
          group,
          blocks: ['context'],
          tags: (s.tags || []).concat(s.triggers || []),
          icon: s.persona ||
            (window.AgentIcons
              ? AgentIcons.resolve({ name: s.name, description: s.description })
              : 'skill'),
          chips: (s.triggers || []).slice(0, 3).map(k => ({ label: String(k) })),
          badges: [{ label: state, cls: `skill-disc-${state}` }],
        };
      });
    },

    detail(id) {
      if (_isDisc(id)) {
        return { sections: { overview: (el) => _renderDiscOverview(el, id) } };
      }
      return {
        sections: {
          overview: (el) => _renderOverview(el, id),
          files: (el) => _renderFiles(el, id),
          examples: (el) => _renderExamples(el, id),
          relations: (el) => _renderRelations(el, id),
        },
      };
    },

    // Test subnav slot — the LB1 skill TestPane (trigger dry-run: matched
    // skills, matched keywords, exact injected text; nothing runs a model).
    testPane(id) {
      return (el) => {
        if (_isDisc(id)) {
          el.innerHTML = '<div class="model-empty">Install this skill first — the trigger dry-run exercises installed skills only.</div>';
          return;
        }
        const it = _item(id);
        return TestPane.mount('skill', id, el, {
          pluginId: it && it.plugin_id,
          skillId: it && it.skill_id,
        });
      };
    },

    actions(id) {
      if (_isDisc(id)) {
        const rec = _discRecord(id);
        const can = !!(rec && rec.has_body && !rec.installed);
        return [{
          action: 'skills.install', label: 'Install…', verb: 'install',
          accent: true, enabled: can,
          reason: can ? undefined
            : (rec && rec.installed
              ? `already installed in ${((rec.installed_in || []).join(', ')) || 'a plugin'}`
              : 'bundled entry — the body ships inside its plugin'),
        }];
      }
      if (_editing) {
        return [
          { action: 'skills.save', label: 'Save & reload', verb: 'edit', accent: true },
          { action: 'skills.cancel', label: 'Cancel', verb: 'edit' },
        ];
      }
      const it = _item(id);
      if (!it) return [];
      const isUser = it.plugin_layer === 'user';
      return [
        { action: 'skills.test', label: 'Test', verb: 'test', accent: true },
        { action: 'skills.edit', label: 'Edit source', verb: 'edit' },
        { action: 'skills.seed-chat', label: 'Seed chat', verb: 'test' },
        // Physical promote (LB3-U1): copy SKILL.md + registration into the
        // user-layer user-skills plugin. Disabled (never hidden) on
        // user-layer hosts so the verb row stays stable.
        { action: 'skills.promote', label: 'Promote', verb: 'promote',
          enabled: !isUser, reason: isUser ? 'already user-layer' : undefined },
        { action: 'skills.uninstall', label: 'Uninstall', verb: 'delete', danger: true },
      ];
    },
  });

  // ── Detail sections ─────────────────────────────────────────────────

  function _kvGrid(rows) {
    return `<div style="display:grid;grid-template-columns:90px 1fr;gap:6px 12px;font-size:0.72rem;margin-bottom:10px">
      ${rows.map(([k, v]) => `<div style="color:var(--text-muted)">${esc(k)}</div><div>${v}</div>`).join('')}
    </div>`;
  }

  function _renderOverview(el, id) {
    const it = _item(id);
    if (!it) { el.innerHTML = '<div class="model-empty">Skill not found — refresh.</div>'; return; }
    if (_editing) {
      el.innerHTML = `
        <div style="font-size:0.62rem;color:var(--text-muted);margin-bottom:6px">
          Editing <code>plugins/${esc(it.plugin_id)}/skills/${esc(it.skill_id)}.md</code>
          — Save rewrites the file and hot-reloads the plugin registry.</div>
        <textarea id="skills-edit-body" class="prompts-textarea" spellcheck="false"
          style="min-height:320px">${esc(it.content || '')}</textarea>`;
      return;
    }
    const triggerRows = (it.triggers || []).map(t => {
      if (t && t.manual) return '<li><code>manual</code> (only on direct invocation)</li>';
      if (t && t.keyword) return `<li>keyword <code>${esc(t.keyword)}</code></li>`;
      return `<li>${esc(JSON.stringify(t))}</li>`;
    }).join('') || '<li style="color:var(--text-muted)">(none — manual-only)</li>';
    const rolesLine = (it.roles && it.roles.length)
      ? it.roles.map(r => `<span class="role-pill">${esc(r)}</span>`).join(' ')
      : '<span class="role-pill role-pill-all">all</span>';
    el.innerHTML = `
      ${_kvGrid([
        ['Plugin', `<code>${esc(it.plugin_id)}</code> · ${esc(it.plugin_name)} <span class="lib-badge">${esc(it.plugin_layer)}</span>`],
        ['Skill ID', `<code>${esc(it.skill_id)}</code>`],
        ['Status', `<span class="plugin-status-pip"></span> registered · injects into <code>${esc(it.inject)}</code>`],
        ['Roles', rolesLine],
        ['Triggers', `<ul style="margin:0;padding-left:14px">${triggerRows}</ul>`],
      ])}
      <div style="font-size:0.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">SKILL.md (rendered)</div>
      <div class="skills-md-body">${renderMarkdown(it.content || '_(empty body)_')}</div>`;
  }

  // Files — LB3-U1 tree endpoint; file bodies fetched per node on click
  // (async section renderer, no side channel).
  async function _renderFiles(el, id) {
    const it = _item(id);
    if (!it) { el.innerHTML = '<div class="model-empty">Skill not found.</div>'; return; }
    const r = await LibraryShell.fetch('skill',
      `/api/skills/tree/${encodeURIComponent(it.skill_id)}?plugin_id=${encodeURIComponent(it.plugin_id)}`);
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Tree failed: ${esc(detail)}</div>`;
      return;
    }
    const d = r.data || {};
    const children = (d.root && d.root.children) || [];
    el.innerHTML = `
      <div style="font-size:0.62rem;color:var(--text-muted);margin-bottom:6px">
        ${d.node_count || children.length} node${(d.node_count || children.length) === 1 ? '' : 's'}
        under <code>plugins/${esc(it.plugin_id)}/</code></div>
      <div class="skills-tree">${_treeHtml(children, it.plugin_id, 0)}</div>
      <div id="skills-file-view" class="skills-file-view" hidden></div>`;
  }

  function _treeHtml(nodes, pluginId, depth) {
    return (nodes || []).map(n => {
      const pad = `style="margin-left:${depth * 14}px"`;
      if (n.type === 'dir') {
        return `<div class="skills-tree-dir" ${pad}>▾ ${esc(n.name)}/</div>` +
          _treeHtml(n.children, pluginId, depth + 1);
      }
      const flags = `${n.declared ? ' · declared' : ''}${n.exists === false ? ' · missing' : ''}`;
      return `<button type="button" class="btn-unstyled skills-tree-file" ${pad}
        data-action="skills.file" data-plugin="${esc(pluginId)}" data-path="${esc(n.path)}">
        ${esc(n.name)} <span class="skills-tree-meta">${esc(String(n.size || 0))}b${esc(flags)}</span>
      </button>`;
    }).join('');
  }

  async function openFile(pluginId, path) {
    const view = document.getElementById('skills-file-view');
    if (!view) return;
    view.hidden = false;
    view.innerHTML = '<div class="model-empty">Loading…</div>';
    const r = await LibraryShell.fetch('skill',
      `/api/skills/file?plugin_id=${encodeURIComponent(pluginId)}&path=${encodeURIComponent(path)}`);
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      view.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(detail)}</div>`;
      return;
    }
    const d = r.data || {};
    view.innerHTML = `
      <div class="skills-tree-meta" style="margin:8px 0 4px"><code>${esc(d.path || path)}</code> · ${esc(String(d.size || 0))}b</div>
      <pre class="prompts-body" style="max-height:300px">${esc(d.body || '(empty)')}</pre>`;
  }

  function _renderExamples(el, id) {
    const it = _item(id);
    if (!it) { el.innerHTML = '<div class="model-empty">Skill not found.</div>'; return; }
    // Frontend-parsed ## Example(s) / ## Usage sections from the SKILL.md.
    const sections = [];
    const parts = ('\n' + (it.content || '')).split(/\n(?=##\s+)/);
    parts.forEach(p => {
      const m = p.match(/^##\s+(.+)/);
      if (m && /example|usage/i.test(m[1])) sections.push(p.trim());
    });
    if (!sections.length) {
      el.innerHTML = `
        <div class="model-empty">No <code>## Example(s)</code> / <code>## Usage</code> sections in this SKILL.md yet.</div>
        <button type="button" class="action-btn" style="margin-top:8px"
          data-action="skills.edit" data-id="${esc(id)}">Edit source to add one</button>`;
      return;
    }
    el.innerHTML = sections
      .map(s => `<div class="skills-md-body" style="margin-bottom:12px">${renderMarkdown(s)}</div>`)
      .join('');
  }

  // Relations — "works with XYZ": host plugin, referencing workflows,
  // trigger keywords; agents honestly say none in v1.
  async function _renderRelations(el, id) {
    const it = _item(id);
    if (!it) { el.innerHTML = '<div class="model-empty">Skill not found.</div>'; return; }
    const r = await LibraryShell.fetch('skill',
      `/api/skills/relations/${encodeURIComponent(it.skill_id)}?plugin_id=${encodeURIComponent(it.plugin_id)}`);
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Relations failed: ${esc(detail)}</div>`;
      return;
    }
    const d = r.data || {};
    const wf = (d.workflows || []).map(w => `
      <li><code>${esc(w.id)}</code> — ${esc(w.name || '')}
        <span class="skills-tree-meta">via ${esc(w.via)}${w.step ? ` · step ${esc(w.step)}` : ''}</span></li>`).join('')
      || '<li style="color:var(--text-muted)">none reference this skill</li>';
    const trig = (d.triggers || []).map(t => `<span class="lib-chip">${esc(t)}</span>`).join(' ')
      || '<span style="color:var(--text-muted)">manual-only</span>';
    el.innerHTML = _kvGrid([
      ['Host plugins', (d.host_plugins || []).map(h => `<code>${esc(h)}</code>`).join(' · ') || '—'],
      ['Chat triggers', trig],
      ['Workflows', `<ul style="margin:0;padding-left:14px">${wf}</ul>`],
      ['Agents', `<span style="color:var(--text-muted)">${esc(d.agents_note || 'none')}</span>`],
    ]);
  }

  async function _renderDiscOverview(el, id) {
    const rec = _discRecord(id);
    if (!rec) { el.innerHTML = '<div class="model-empty">Not in the current catalog read — hit ⟳ Discover.</div>'; return; }
    const state = rec.installed ? 'installed' : (rec.has_body ? 'available' : 'bundled');
    el.innerHTML = _kvGrid([
      ['Skill ID', `<code>${esc(rec.id)}</code>`],
      ['Category', esc(rec.category || '—')],
      ['State', `<span class="skill-disc-chip ${esc(state)}">${esc(state)}</span>${rec.marketplace || rec.source === 'remote' ? ' <span class="skill-disc-chip marketplace">marketplace</span>' : ''}`],
      ['Installed in', (rec.installed_in || []).map(p => `<code>${esc(p)}</code>`).join(' · ') || '—'],
      ['Triggers', (rec.triggers || []).map(t => `<span class="lib-chip">${esc(String(t))}</span>`).join(' ') || '—'],
      ['Description', esc(rec.description || '(none)')],
    ]) + '<div id="skills-disc-body"><div class="model-empty">Loading body preview…</div></div>';
    const out = el.querySelector('#skills-disc-body');
    if (!rec.has_body) {
      out.innerHTML = '<div class="model-empty">Bundled entry — the body ships inside its plugin; open it under Installed.</div>';
      return;
    }
    const r = await LibraryShell.fetch('skill', `/api/skills/discover/${encodeURIComponent(rec.id)}`);
    if (!r.ok || !r.data || !r.data.skill_md) {
      out.innerHTML = '<div class="model-empty">No body preview available.</div>';
      return;
    }
    out.innerHTML = `
      <div style="font-size:0.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin:8px 0 4px">SKILL.md (would install)</div>
      <pre class="prompts-body" style="max-height:280px">${esc(r.data.skill_md)}</pre>`;
  }

  // ── Panel API (signature-identical to the pre-shell module) ─────────
  function load() { return LibraryShell.reload('skill'); }
  // Legacy Refresh button / filter selects: re-render with the current
  // filters applied (pre-shell semantics — no refetch).
  function refresh() { LibraryShell.renderSidebar('skill'); }
  function select(id) {
    _editing = false;
    LibraryShell.select('skill', id);
  }

  // ── Actions ──────────────────────────────────────────────────────────

  function edit(id) {
    const target = id || _selected();
    if (!target || _isDisc(target)) return;
    if (target !== _selected()) LibraryShell.select('skill', target);
    _editing = true;
    LibraryShell.renderDetail('skill');
  }

  function cancel() {
    _editing = false;
    LibraryShell.renderDetail('skill');
  }

  async function save(id) {
    const it = _item(id || _selected());
    const ta = document.getElementById('skills-edit-body');
    if (!it || !ta) return;
    if (!ta.value.trim()) { Toast.danger('Skill body cannot be empty'); return; }
    try {
      // retries:0 — PUT rewrites the skill file; don't double-apply.
      const r = await Net.call(`/api/skills/source/${encodeURIComponent(it.skill_id)}`, {
        retries: 0,
        init: {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ plugin_id: it.plugin_id, body: ta.value }),
        },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : (r.error || `HTTP ${r.status}`);
        Toast.danger('Save failed', detail);
        return;
      }
      // Hot-reload so the edited skill activates immediately for chat.
      let active = false;
      try {
        active = (await Net.call('/api/plugins/reload',
          { retries: 0, silent: true, init: { method: 'POST', headers: _headers() } })).ok;
      } catch (_) {}
      _editing = false;
      Toast.success('Skill saved', `${it.skill_id} → ${it.plugin_id}` + (active ? ' — active now' : ' (reload to activate)'));
      await load();
    } catch (e) { Toast.danger('Save failed', e.message); }
  }

  async function uninstall(id) {
    const it = _item(id || _selected());
    if (!it) return;
    const ok = await Confirm.ask({
      title: 'Uninstall skill',
      body: `Uninstall '${it.skill_id}' from '${it.plugin_id}'? This deletes the skill .md and removes the registration.`,
      okLabel: 'Uninstall', danger: true,
    });
    if (!ok) return;
    // retries:0 — DELETE removes files; never double-fire.
    const r = await Net.call(
      `/api/skills/discover/${encodeURIComponent(it.skill_id)}/uninstall?plugin_id=${encodeURIComponent(it.plugin_id)}`,
      { retries: 0, init: { method: 'DELETE', headers: _headers() } });
    if (!r.ok) {
      const detail = (r.data && r.data.detail) ? r.data.detail : (r.error || `HTTP ${r.status}`);
      Toast.danger('Uninstall failed', detail);
      return;
    }
    Toast.success('Skill uninstalled', `${it.skill_id} ↛ ${it.plugin_id}`);
    LibraryShell.select('skill', null);
    await load();
    // The host plugin's skill-count meta changed — refresh Plugins too.
    LibraryShell.notifyChanged(['plugin']);
  }

  async function promote(id) {
    const it = _item(id || _selected());
    if (!it) return;
    const ok = await Confirm.ask({
      title: 'Promote skill',
      body: `Copy '${it.skill_id}' (SKILL.md + registration) from '${it.plugin_id}' into the user-layer 'user-skills' plugin? The copy survives image rebuilds and is editable; the source stays untouched.`,
      okLabel: 'Promote',
    });
    if (!ok) return;
    try {
      // retries:0 — a retry after a slow success would surface a spurious 409.
      const r = await Net.call(`/api/skills/${encodeURIComponent(it.skill_id)}/promote`, {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ plugin_id: it.plugin_id }),
        },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : (r.error || `HTTP ${r.status}`);
        Toast.danger('Promote failed', detail);
        return;
      }
      const d = r.data || {};
      Toast.success('Skill promoted', `${it.skill_id} → ${d.target_plugin_id || 'user-skills'} (user layer)`);
      await load();
    } catch (e) { Toast.danger('Promote failed', e.message); }
  }

  // Visible Refresh — operator-triggered: re-fires the skills-marketplace
  // provider refresh (retries:0, fail-soft) then re-reads /api/skills/discover
  // via the adapter load. Reads on tab activation never trigger this.
  async function refreshDiscovery() {
    Toast.info('Refreshing skills discovery…');
    // Theme B: GET /api/skills/discover no longer fetches ENCLAVE_SKILLS_
    // CATALOG_URL on a stale TTL, so the operator's ⟳ is the one place that
    // may reach it. Both remote sources refresh together here — the
    // skills.sh discovery provider below, and the configured catalog URL.
    // Fail-soft and awaited before the re-read, so the cache it fills is the
    // one the read below serves.
    try {
      await Net.call('/api/skills/discover/refresh', {
        retries: 0,
        init: { method: 'POST', headers: _headers() },
      });
    } catch (_) { /* no catalog URL, or a dead one — keep the cached view */ }
    try {
      // The registered marketplace provider source id is `skills-sh`.
      const r = await Net.call('/api/discover/skills-sh/refresh', {
        retries: 0,
        init: { method: 'POST', headers: _headers() },
      });
      if (!r.ok && r.status !== 404) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.warn('Marketplace refresh degraded', detail);
        return;   // MS-4: a degraded refresh must NOT fall through to success
        //         (404 = no provider registered, tolerated — read the cache)
      }
    } catch (e) { Toast.warn('Marketplace refresh degraded', e.message); return; }
    await load();
    const st = LibraryShell.state('skill');
    if (st) { st.side = 'discovered'; st.chromeBuilt = false; }
    LibraryShell.renderSidebar('skill');
    Toast.success('Skills discovery refreshed');
  }

  function installWizard(id) {
    const rec = _discRecord(id || _selected());
    if (!rec) return;
    // Target-plugin flow through LibraryWizard (endpoint byte-identical to
    // the retired window.prompt() flow) — lives in discover.js so both the
    // shell and the catalog cards share ONE wizard.
    SkillsDiscover.install(rec.id, () => load());
  }

  function seedChat(id) {
    const it = _item(id || _selected());
    if (!it) return;
    const kw = _keywords(it.triggers).find(k => k !== 'manual');
    const starter = kw
      ? `${kw}: `
      : `Use the ${it.name} skill (${it.plugin_id}.${it.skill_id}) for this: `;
    if (window.AssetPeek) AssetPeek.seedChat(null, null, starter);
  }

  // Reload whenever the admin Skills panel is activated — keeps the list
  // fresh as plugins are added/removed under plugins/.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-skills') load();
  });

  // Delegated actions — the full skills.* grammar (side-tab/group/dtab are
  // functional aliases over the shell chrome, mirroring prompts.tab).
  Actions.click({
    'skills.select': el => select(el.dataset.id),
    'skills.side-tab': el => {
      const st = LibraryShell.state('skill');
      if (!st) return;
      st.side = el.dataset.side === 'discovered' ? 'discovered' : 'installed';
      st.chromeBuilt = false;
      LibraryShell.renderSidebar('skill');
    },
    'skills.group': el => {
      const st = LibraryShell.state('skill');
      if (!st) return;
      st.collapsed[el.dataset.group] = !st.collapsed[el.dataset.group];
      LibraryShell.renderRows('skill');
    },
    'skills.dtab': el => LibraryShell.setSubnav('skill', el.dataset.section),
    'skills.file': el => openFile(el.dataset.plugin, el.dataset.path),
    'skills.test': () => { if (_selected()) LibraryShell.setSubnav('skill', 'test'); },
    'skills.promote': el => promote(el.dataset.id),
    'skills.refresh-discovery': () => refreshDiscovery(),
    'skills.install': el => installWizard(el.dataset.id),
    'skills.import': () => SkillsDiscover.importFromUrl(() => load()),
    'skills.browse-repo': () => SkillsDiscover.browseGithubRepo(),
    'skills.create': () => { if (window.SkillsBuilder) SkillsBuilder.open(); },
    'skills.edit': el => edit(el.dataset.id),
    'skills.save': el => save(el.dataset.id),
    'skills.cancel': () => cancel(),
    'skills.uninstall': el => uninstall(el.dataset.id),
    'skills.seed-chat': el => seedChat(el.dataset.id),
  });

  return { load, refresh, select, edit, cancel, save, uninstall, promote,
           refreshDiscovery, installWizard, seedChat, openFile, adapter };
})();
