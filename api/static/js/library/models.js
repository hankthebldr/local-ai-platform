// library/models.js — Models catalog page (phase-2 U4 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';

export const CatalogPage = (function () {
  let _active = 'models';
  let _loaded = new Set();

  function show(name) {
    _active = name;
    document.querySelectorAll('.catalog-nav-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.catSec === name);
    });
    document.querySelectorAll('.catalog-section').forEach(s => {
      const matches = s.dataset.catSec === name;
      if (matches) s.removeAttribute('hidden');
      else s.setAttribute('hidden', '');
      s.classList.toggle('active', matches);
    });
    // Lazy-load the section's content on first activation.
    if (!_loaded.has(name)) {
      _loaded.add(name);
      _loadSection(name);
    }
  }

  async function _loadSection(name) {
    // For each section, populate the corresponding mount with either
    // a relocated panel or a freshly-built list. Models / Plugins /
    // Skills / MCP / External all get their relocated <details>
    // panels; Agents is built from /api/agents in place.
    if (name === 'agents') {
      const mount = document.getElementById('catalog-agents-mount');
      if (!mount) return;
      try {
        const list = await Net.getJson('/api/agents');
        mount.innerHTML = _renderAgentsList(list || []);
      } catch (e) {
        mount.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
      }
      return;
    }
    // For the discover sections we already triggered the loaders
    // (loadCatalog → loadPluginsDiscover etc.). The relocator moves
    // the populated <details> into the section mount on boot, so
    // first visit just shows what's already there.
    if (name === 'models' && typeof loadCatalog === 'function' && !window.catalogLoaded) {
      try { loadCatalog(); } catch (_) {}
    }
    if (name === 'skills' && window.SkillsDiscover) {
      try { SkillsDiscover.load(); } catch (_) {}
    }
    if (name === 'plugins' && typeof loadPluginsDiscover === 'function') {
      try { loadPluginsDiscover(); } catch (_) {}
    }
    if (name === 'mcp' && typeof loadMcpsDiscover === 'function') {
      try { loadMcpsDiscover(); } catch (_) {}
    }
    if (name === 'external' && typeof loadExternalDiscover === 'function') {
      try { loadExternalDiscover(); } catch (_) {}
    }
  }

  function _renderAgentsList(list) {
    if (!list.length) {
      return '<div class="model-empty">No agents yet. Click + New Agent above to author one.</div>';
    }
    return list.map(a => {
      const persona = (window.AgentIcons ? AgentIcons.resolve(a) : 'general');
      const icon = (window.AgentIcons ? AgentIcons.svg(persona) : '');
      const tone = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');
      return `<div class="agent-tile" role="button" tabindex="0" aria-label="Open chat with ${esc(a.name || a.id)}" data-action="agents.chat" data-agent-id="${esc(a.id)}">
        <div class="agent-tile-head">
          <span class="agent-tile-icon tone-${esc(tone)}">${icon}</span>
          <div class="agent-tile-titleblock">
            <div class="agent-tile-title">${esc(a.name || a.id)}</div>
            <div class="agent-tile-subtitle">${esc((a.description || '').split('\n')[0].slice(0, 90))}</div>
          </div>
          <div class="agent-tile-actions">
            <button data-action="agents.edit"
                    class="agent-tile-action" title="Edit">✎</button>
            <button data-action="agents.delete"
                    class="agent-tile-action" title="Delete">✕</button>
          </div>
        </div>
        <div class="agent-tile-meta">
          ${(a.tags || []).map(t => `<span class="agent-tile-tag">${esc(t)}</span>`).join('')}
          ${a.role ? `<span class="agent-tile-tag tag-role">${esc(a.role)}</span>` : ''}
          ${a.model ? `<span class="agent-tile-tag tag-model">${esc(a.model)}</span>` : ''}
        </div>
      </div>`;
    }).join('');
  }

  return { show, _active, _loaded, _renderAgentsList };
})();
