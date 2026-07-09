// library/skills.js — Skills catalog panel (phase-2 U4 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Actions } from '../shell/actions.js';

export const SkillsPanel = (function () {
  let _items = [];           // flattened [{ plugin, skill }]
  let _selectedId = null;    // composite "plugin_id::skill_id"

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function _matchesRole(skill, role) {
    if (!role) return true;
    // Forward-compat: skills may declare roles[] in their manifest. Until
    // that ships, treat unspecified roles[] as "applies to all roles" so
    // the filter doesn't hide anything pre-tagging.
    const roles = skill.roles;
    if (!Array.isArray(roles) || roles.length === 0) return true;
    return roles.includes(role) || roles.includes('*');
  }

  async function load() {
    const list = document.getElementById('skills-list');
    if (list) list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">Loading…</div>';
    try {
      const r = await Net.call('/api/plugins');
      if (!r.ok) {
        list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
        return;
      }
      const plugins = r.data;
      _items = [];
      (plugins || []).forEach(p => {
        (p.skills || []).forEach(s => {
          _items.push({
            plugin_id: p.id,
            plugin_name: p.name || p.id,
            skill_id: s.id,
            name: s.name || s.id,
            description: s.description || '',
            inject: s.inject || 'none',
            content: s.content || '',
            triggers: s.triggers || [],
            roles: s.roles || [],
          });
        });
      });

      // Populate the plugin filter dropdown — once, keep selection if any.
      const pluginSel = document.getElementById('skills-filter-plugin');
      if (pluginSel) {
        const cur = pluginSel.value;
        const ids = Array.from(new Set((plugins || []).map(p => p.id))).sort();
        const opts = ['<option value="">— all plugins —</option>']
          .concat(ids.map(id => `<option value="${esc(id)}"${cur === id ? ' selected' : ''}>${esc(id)}</option>`));
        pluginSel.innerHTML = opts.join('');
      }

      refresh();
    } catch (e) {
      if (list) list.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    }
  }

  function refresh() {
    const list = document.getElementById('skills-list');
    if (!list) return;
    const pluginFilter = (document.getElementById('skills-filter-plugin') || {}).value || '';
    const roleFilter   = (document.getElementById('skills-filter-role')   || {}).value || '';

    const filtered = _items.filter(it => {
      if (pluginFilter && it.plugin_id !== pluginFilter) return false;
      if (!_matchesRole(it, roleFilter)) return false;
      return true;
    });

    if (filtered.length === 0) {
      const reason = (pluginFilter || roleFilter)
        ? 'No skills match these filters.'
        : 'No skills installed. Add one under plugins/&lt;plugin&gt;/skills/.';
      list.innerHTML = `<div style="color:var(--text-muted);font-size:0.7rem">${reason}</div>`;
      return;
    }

    list.innerHTML = filtered.map(it => {
      const compositeId = `${it.plugin_id}::${it.skill_id}`;
      const triggers = (it.triggers || [])
        .map(t => t.keyword || (t.manual ? 'manual' : ''))
        .filter(Boolean)
        .slice(0, 4)
        .join(', ');
      const roleBadges = (it.roles && it.roles.length > 0)
        ? it.roles.map(r => `<span class="role-pill">${esc(r)}</span>`).join(' ')
        : '<span class="role-pill role-pill-all">all</span>';
      // Persona icon for each skill — prefer the skill's declared
      // persona if any (matches the icon-explorer view in Skills
      // Discover); fall back to the generic 'skill' glyph.
      const persona = it.persona ||
        (window.AgentIcons ? AgentIcons.resolve({ name: it.name, description: it.description }) : 'skill');
      const icon = (window.AgentIcons ? AgentIcons.svg(persona) : '');
      const tone = (window.AgentIcons ? AgentIcons.tone(persona) : 'amber');
      return `<button type="button" class="btn-unstyled plugin-card ${compositeId === _selectedId ? 'selected' : ''}"
                   style="width:100%" aria-pressed="${compositeId === _selectedId}"
                   data-action="skills.select" data-id="${esc(compositeId)}">
        <div class="plugin-card-head">
          <span class="admin-card-icon tone-${esc(tone)}">${icon}</span>
          <div class="plugin-card-head-text">
            <div class="plugin-card-title">
              <span class="plugin-status-pip"></span>${esc(it.name)}
              <span style="color:var(--text-muted);font-size:0.66rem;margin-left:6px">${esc(it.plugin_id)}</span>
            </div>
            <div class="plugin-card-meta">
              ${(it.triggers || []).length} trigger${(it.triggers || []).length === 1 ? '' : 's'}${triggers ? ' · ' + esc(triggers) : ''}
            </div>
            <div class="plugin-card-meta" style="margin-top:3px">${roleBadges}</div>
          </div>
        </div>
        <div class="plugin-card-desc">${esc((it.description || '').slice(0, 140))}</div>
      </button>`;
    }).join('');

    // Auto-select first match if nothing is currently selected.
    if (!_selectedId && filtered.length) select(`${filtered[0].plugin_id}::${filtered[0].skill_id}`);
  }

  function select(compositeId) {
    _selectedId = compositeId;
    document.querySelectorAll('#skills-list .plugin-card').forEach(c => c.classList.remove('selected'));
    document.querySelectorAll(`#skills-list .plugin-card[data-id="${CSS.escape(compositeId)}"]`)
      .forEach(c => c.classList.add('selected'));

    const detail = document.getElementById('skill-detail');
    const label  = document.getElementById('skill-detail-label');
    const it = _items.find(x => `${x.plugin_id}::${x.skill_id}` === compositeId);
    if (!detail || !it) return;

    if (label) label.textContent = `// ${it.skill_id.toUpperCase()}`;
    const triggerRows = (it.triggers || []).map(t => {
      if (t.manual) return '<li><code>manual</code> (only on direct invocation)</li>';
      if (t.keyword) return `<li>keyword <code>${esc(t.keyword)}</code></li>`;
      return `<li>${esc(JSON.stringify(t))}</li>`;
    }).join('') || '<li style="color:var(--text-muted)">(none — manual-only)</li>';

    const rolesLine = (it.roles && it.roles.length > 0)
      ? it.roles.map(r => `<span class="role-pill">${esc(r)}</span>`).join(' ')
      : '<span class="role-pill role-pill-all">all</span> <span style="color:var(--text-muted);font-size:0.62rem">(no roles[] field in manifest — defaults to all)</span>';

    detail.innerHTML = `
      <div style="font-size:0.72rem">
        <div style="display:grid;grid-template-columns:90px 1fr;gap:6px 12px;margin-bottom:10px">
          <div style="color:var(--text-muted)">Plugin</div><div><code>${esc(it.plugin_id)}</code> · ${esc(it.plugin_name)}</div>
          <div style="color:var(--text-muted)">Skill ID</div><div><code>${esc(it.skill_id)}</code></div>
          <div style="color:var(--text-muted)">Description</div><div>${esc(it.description || '(none)')}</div>
          <div style="color:var(--text-muted)">Inject</div><div><code>${esc(it.inject)}</code></div>
          <div style="color:var(--text-muted)">Roles</div><div>${rolesLine}</div>
          <div style="color:var(--text-muted)">Triggers</div><div><ul style="margin:0;padding-left:14px">${triggerRows}</ul></div>
        </div>
        <div style="font-size:0.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">Skill body (rendered when injected)</div>
        <pre style="background:var(--bg-deep);border:1px solid var(--border);border-radius:4px;padding:10px 12px;font-size:0.66rem;max-height:380px;overflow:auto;white-space:pre-wrap;color:var(--text-dim)">${esc(it.content || '(empty)')}</pre>
      </div>`;
  }

  // Reload whenever the admin Skills panel is activated — keeps the list
  // fresh as plugins are added/removed under plugins/.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-skills') load();
  });

  // Delegated action — skill rows re-render per filter/load.
  Actions.click({ 'skills.select': el => select(el.dataset.id) });

  return { load, refresh, select };
})();
