// library/skills-data.js — shared skills loader/normalizer (LB3-U2).
//
// ONE source of truth for the flattened skill records BOTH surfaces render:
// the Skills library shell (js/library/skills.js) and the Composer Skills
// bench (main.js renderSkillsWorkbench). The Composer drag-attach payload is
// part of the contract — mime `application/df-skill`, value
// `<plugin_id>::<skill_id>` — pinned by tests/ui/test_skills_shell.py and by
// the canvas drop handler; never change either side independently.

export const SKILL_DRAG_MIME = 'application/df-skill';

// Composite key — the drag value AND the Library shell row id.
export function skillKey(pluginId, skillId) {
  return `${pluginId}::${skillId}`;
}

// Flatten GET /api/plugins records into per-skill items. Field set matches
// what the pre-shell SkillsPanel carried, plus the plugin layer (LB0-U3
// provenance seam) so the shell can render honest oob/user chips.
export function flattenSkills(plugins) {
  const items = [];
  (plugins || []).forEach(p => {
    (p.skills || []).forEach(s => {
      items.push({
        plugin_id: p.id,
        plugin_name: p.name || p.id,
        plugin_layer: p.layer || p.origin || 'system',
        skill_id: s.id,
        name: s.name || s.id,
        description: s.description || '',
        inject: s.inject || 'none',
        content: s.content || '',
        triggers: s.triggers || [],
        roles: s.roles || [],
        persona: s.persona,
      });
    });
  });
  return items;
}

// Shared loader. fetchImpl: (url) => Promise<{ok, status, data}> — the shell
// passes its auth-tier-aware LibraryShell.fetch, the Composer bench path uses
// plain Net.call (the global auth wrapper merges headers there).
export async function loadSkills(fetchImpl) {
  const r = await fetchImpl('/api/plugins');
  if (!r.ok) throw new Error(`Load failed (${r.status})`);
  const plugins = Array.isArray(r.data) ? r.data : [];
  return { plugins, items: flattenSkills(plugins) };
}
