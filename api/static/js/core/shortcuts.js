// core/shortcuts.js — keyboard shortcuts (phase-2 U2 carve).
import { esc } from './dom.js';

export const Shortcuts = (function () {
  const keymap = [
    { key: 'g d', label: 'Composer (dashboard)',  action: () => switchTab('dashboard') },
    { key: 'g w', label: 'Workflow Index',         action: () => switchTab('workflow-index') },
    { key: 'g a', label: 'Agents',                 action: () => switchTab('agents') },
    { key: 'g r', label: 'Skill Lab',              action: () => switchTab('research') },
    { key: 'g m', label: 'Models',                 action: () => switchTab('inventory') },
    { key: 'g c', label: 'Context',                action: () => switchTab('documents') },
    { key: 'g p', label: 'Plugins',                action: () => switchTab('admin-plugins') },
    { key: 'g s', label: 'Skills',                 action: () => switchTab('admin-skills') },
    { key: 'g x', label: 'MCP Servers',            action: () => switchTab('admin-mcp') },
    { key: 'g y', label: 'System (Memory)',        action: () => switchTab('memory') },
    { key: 'g k', label: 'License Keys',           action: () => switchTab('admin-keys') },
    { key: 'g h', label: 'Runs (history)',         action: () => switchTab('runs') },
    { key: '?',   label: 'Show this overlay',      action: () => toggle(true) },
    { key: 'Escape', label: 'Close overlay',       action: () => toggle(false), inOverlay: true },
  ];

  let _open = false;
  let _seq = '';
  let _seqTimer = null;

  function _modal() {
    let m = document.getElementById('shortcuts-modal');
    if (m) return m;
    m = document.createElement('div');
    m.id = 'shortcuts-modal';
    m.className = 'admin-modal';
    m.setAttribute('role', 'dialog');
    m.setAttribute('aria-modal', 'true');
    m.hidden = true;
    const rows = keymap.filter(e => !e.inOverlay || e.key === 'Escape').map(e => `
      <div class="kbd-row">
        <kbd class="kbd-key">${esc(e.key)}</kbd>
        <span class="kbd-label">${esc(e.label)}</span>
      </div>
    `).join('');
    m.innerHTML = `
      <div class="admin-modal-card" style="width:min(560px,90vw)">
        <h3 style="display:flex;align-items:center;justify-content:space-between">
          <span>Keyboard shortcuts</span>
          <button class="action-btn xs" type="button" data-action="shortcuts.close">close</button>
        </h3>
        <p class="admin-modal-sub">
          Shortcuts ignore your keystrokes when focus is on a text input,
          so typing inside fields is safe. <kbd class="kbd-key">g</kbd>
          followed by another key jumps tabs.
        </p>
        <div class="kbd-list">${rows}</div>
      </div>
    `;
    document.body.appendChild(m);
    return m;
  }

  function toggle(force) {
    const m = _modal();
    _open = (force === undefined) ? !_open : !!force;
    m.hidden = !_open;
  }

  function _isTextTarget(t) {
    if (!t) return false;
    const tag = (t.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable;
  }

  function _onKey(e) {
    // Cmd/Ctrl-K toggles overlay regardless of focus.
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      toggle();
      return;
    }
    // Escape closes overlay even when on text input.
    if (e.key === 'Escape' && _open) { toggle(false); return; }
    if (_isTextTarget(e.target)) return;

    // ? help
    if (e.key === '?') { e.preventDefault(); toggle(true); return; }

    // Two-key sequences: "g <x>"
    if (e.key === 'g') {
      _seq = 'g';
      if (_seqTimer) clearTimeout(_seqTimer);
      _seqTimer = setTimeout(() => { _seq = ''; }, 900);
      return;
    }
    if (_seq === 'g') {
      const combo = 'g ' + e.key.toLowerCase();
      _seq = '';
      const entry = keymap.find(k => k.key === combo);
      if (entry) { e.preventDefault(); entry.action(); }
    }
  }

  document.addEventListener('keydown', _onKey);
  return { toggle };
})();
