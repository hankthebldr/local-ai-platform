// workspace-legacy/composer-split.js — legacy composer split (phase-2 U7). df* via window bridge.
//
// S0 (chat extraction): the chat pane moved to its own #tab-chat, so the
// chat/canvas/focus view modes and the drag divider are retired — the
// canvas owns the Composer split now (full-screen survives independently
// via dfToggleFullscreen / #canvas-fullscreen-btn). What remains is the
// spine state machine: dormant ghost ↔ live canvas (+ the collapse toggle),
// which ComposerView.updateCanvasEmptyState still drives.

export const ComposerSplit = (function () {
  let _wired = false;

  function _el() { return document.getElementById('composer-split'); }

  function init() {
    const el = _el(); if (!el || _wired) return;
    _wired = true;
  }

  // Swap the spine between its dormant ghost and the live canvas/workstream.
  function setSpinePrimed(primed) {
    const el = _el(); if (!el) return;
    el.classList.toggle('is-primed', !!primed);
    if (primed) el.classList.remove('spine-collapsed');
  }

  // Collapse the spine entirely (toggle).
  function toggleSpine(force) {
    const el = _el(); if (!el) return;
    el.classList.toggle('spine-collapsed', force === undefined ? undefined : !force);
  }

  function focusChat() {
    // The prompt lives in #tab-chat now; focusing it only makes sense
    // when that tab is showing (focus on a hidden element is a no-op).
    const p = document.getElementById('prompt');
    if (p) { p.focus(); p.scrollIntoView({ block: 'nearest' }); }
  }

  return { init, setSpinePrimed, toggleSpine, focusChat };
})();
