// workspace-legacy/composer-split.js — legacy composer split modes (phase-2 U7). df* via window bridge.

export const ComposerSplit = (function () {
  const KEY = 'enclave.composer.split';
  // MIN dropped 40→25 with the design-system pivot: in canvas mode the
  // chat docks as the test surface (~30%) and the canvas dominates.
  const MIN = 25, MAX = 85;          // chat-pane width as a % of the split
  const CHAT_FRAC = 58, CANVAS_FRAC = 30;
  let _wired = false;
  let _mode = 'chat';

  function _el() { return document.getElementById('composer-split'); }

  function _applyFrac(pct) {
    const el = _el(); if (!el) return;
    const clamped = Math.max(MIN, Math.min(MAX, pct));
    el.style.setProperty('--chat-frac', clamped + '%');
    const divider = document.getElementById('composer-divider');
    if (divider) divider.setAttribute('aria-valuenow', String(Math.round(clamped)));
  }

  function init() {
    const el = _el(); if (!el || _wired) return;
    _wired = true;
    const saved = parseFloat(localStorage.getItem(KEY));
    if (!isNaN(saved)) _applyFrac(saved);
    _wireDrag();
  }

  function _wireDrag() {
    const el = _el(); const divider = document.getElementById('composer-divider');
    if (!el || !divider) return;

    function onDown(e) {
      // Only the left column is draggable; ignore when collapsed/stacked.
      if (el.classList.contains('spine-collapsed')) return;
      if (window.matchMedia('(max-width: 900px)').matches) return;
      e.preventDefault();
      el.classList.add('is-dragging');
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp, { once: true });
    }
    function onMove(e) {
      const rect = el.getBoundingClientRect();
      if (!rect.height) return;
      _applyFrac(((e.clientY - rect.top) / rect.height) * 100);
    }
    function onUp() {
      el.classList.remove('is-dragging');
      window.removeEventListener('pointermove', onMove);
      const cur = el.style.getPropertyValue('--chat-frac').replace('%', '').trim();
      if (cur) localStorage.setItem(KEY, cur);
    }
    function _persist() {
      const cur = el.style.getPropertyValue('--chat-frac').replace('%', '').trim();
      if (cur) localStorage.setItem(KEY, cur);
    }
    // Keyboard resize for the role="separator" (a11y): ←/→ nudge, Home resets.
    function onKey(e) {
      if (el.classList.contains('spine-collapsed')) return;
      let f = parseFloat(el.style.getPropertyValue('--chat-frac'));
      if (isNaN(f)) f = 58;
      if (e.key === 'ArrowUp') f -= 3;
      else if (e.key === 'ArrowDown') f += 3;
      else if (e.key === 'Home') { f = 58; localStorage.removeItem(KEY); _applyFrac(f); return; }
      else return;
      e.preventDefault();
      _applyFrac(f);
      _persist();
    }
    divider.addEventListener('pointerdown', onDown);
    divider.addEventListener('keydown', onKey);
    divider.addEventListener('dblclick', () => { _applyFrac(58); localStorage.removeItem(KEY); });
  }

  // Swap the spine between its dormant ghost and the live canvas/workstream.
  function setSpinePrimed(primed) {
    const el = _el(); if (!el) return;
    el.classList.toggle('is-primed', !!primed);
    if (primed) el.classList.remove('spine-collapsed');
  }

  // Collapse the spine entirely → full-chat (toggle).
  function toggleSpine(force) {
    const el = _el(); if (!el) return;
    el.classList.toggle('spine-collapsed', force === undefined ? undefined : !force);
  }

  // ── In-shell pivot (design-system console-v2) ──────────────────────
  // One thread, two modes: CHAT (conversation leads, spine is the rail)
  // and CANVAS (workflow leads, chat docks as the test surface). The
  // Boot Sequence pivots to canvas on confirm — the composer takes the
  // stage exactly when there is a workflow to stage.
  function setMode(mode) {
    const el = _el(); if (!el) return;
    _mode = (mode === 'canvas' || mode === 'focus') ? mode : 'chat';
    el.classList.remove('spine-collapsed');
    el.classList.toggle('mode-canvas', _mode === 'canvas');
    el.classList.toggle('mode-focus', _mode === 'focus');
    if (_mode !== 'focus') _applyFrac(_mode === 'canvas' ? CANVAS_FRAC : CHAT_FRAC);
    for (const m of ['chat', 'canvas', 'focus']) {
      ['composer-mode-' + m, 'composer-fmode-' + m].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.setAttribute('aria-pressed', String(_mode === m));
      });
    }
    // The canvas just resized — let drawflow + anchors settle into it.
    setTimeout(() => {
      try { if (typeof dfScheduleAnchorRefresh === 'function') dfScheduleAnchorRefresh(); } catch (_) {}
    }, 60);
  }

  function getMode() { return _mode; }

  function focusChat() {
    const p = document.getElementById('prompt');
    if (p) { p.focus(); p.scrollIntoView({ block: 'nearest' }); }
  }

  return { init, setSpinePrimed, toggleSpine, setMode, getMode, focusChat };
})();
