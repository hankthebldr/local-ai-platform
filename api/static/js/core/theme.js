// core/theme.js — theme toggle/persistence (phase-2 U2 carve).

export const Theme = (function () {
  var STORAGE_KEY = 'enclave.theme';

  function current() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function apply(theme) {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    // Browser-chrome color follows the palette (mirrors --bg-deep).
    var tc = document.querySelector('meta[name="theme-color"]');
    if (tc) tc.setAttribute('content', theme === 'light' ? '#F2F4F7' : '#070A0F');
    _syncIcon();
  }

  function toggle() {
    var next = current() === 'light' ? 'dark' : 'light';
    apply(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch (e) { /* private mode */ }
  }

  function _syncIcon() {
    var icon = document.getElementById('theme-toggle-icon');
    if (!icon) return;
    // Sun when current is light (clicking → goes dark); moon when current is dark.
    icon.textContent = current() === 'light' ? '☀' : '☾';
  }

  // Initial sync on DOM ready.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _syncIcon);
  } else {
    _syncIcon();
  }

  return { toggle: toggle, apply: apply, current: current };
})();
