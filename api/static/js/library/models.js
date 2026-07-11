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

// CatalogModelsShare — relocates the models grid between the Models tab and
// the Library catalog mount (phase-2 U4 carve; was nested in a DOMContentLoaded
// handler — object build is side-effect-free, DOM work is method-only).
export const CatalogModelsShare = (function () {
  let inCatalog = false;
  const ids = ['inv-stats', 'inv-grid', 'discover-section'];
  const sel = ['.panel', '.inv-toolbar'];
  // LB4-U2 (F2): the legacy nodes' HOME is the hidden #inv-legacy-holder
  // inside #tab-inventory — ids unchanged, so showInCatalog() still moves
  // the same nodes to the Catalog page and the Admin Catalog keeps binding,
  // but the Models tab shows exactly ONE visible models surface
  // (#models-shell). Falls back to #tab-inventory if the holder is absent.
  function _home() {
    return document.getElementById('inv-legacy-holder')
      || document.getElementById('tab-inventory');
  }
  function _nodes() {
    const arr = [];
    // Hardware profile + toolbar live inside the holder (or, pre-holder,
    // as siblings under #tab-inventory); grab them by selector. The grid +
    // stats + discover have stable ids.
    sel.forEach(s => {
      const home = _home();
      const owned = document.getElementById('catalog-models-mount');
      (home?.querySelector(s) || owned?.querySelector(s))
        && arr.push(home?.querySelector(s) || owned.querySelector(s));
    });
    ids.forEach(id => { const n = document.getElementById(id); if (n) arr.push(n); });
    return arr;
  }
  function _moveTo(host) {
    if (!host) return;
    _nodes().forEach(n => { try { host.appendChild(n); } catch (_) {} });
  }
  return {
    showInCatalog() {
      if (inCatalog) return;
      const mount = document.getElementById('catalog-models-mount');
      if (!mount) return;
      // Drop the "Loading model catalog…" placeholder before we
      // move the real grid in.
      mount.replaceChildren();
      _moveTo(mount);
      inCatalog = true;
    },
    showInModelsTab() {
      if (!inCatalog) return;
      // Return the nodes to the hidden holder — parked, not shown: the
      // Models tab's visible surface is #models-shell.
      const home = _home();
      if (!home) return;
      _moveTo(home);
      inCatalog = false;
    },
    get isInCatalog() { return inCatalog; },
  };
})();
