// shell/router.js — hash -> tab router (phase-2 U3 carve).
// initRouter() is invoked from main.js at the ORIGINAL body position so the
// DOMContentLoaded registration order stays load-bearing (AFTER the IA
// relocators, BEFORE ComposerView boot). switchTab/RunsTab resolve via window
// (bridge sets them before DOMContentLoaded fires).

export function initRouter() {
  function parse() {
    const m = (location.hash || '').match(/^#\/([A-Za-z0-9_-]+)(?:\/(.+))?$/);
    if (!m) return null;
    let arg = null;
    if (m[2]) { try { arg = decodeURIComponent(m[2]); } catch (_) { arg = m[2]; } }
    return { tab: m[1], arg };
  }
  function go(route) {
    if (!route) return;
    // Whitelist against real panels. 'discover' and 'documents' are legacy
    // aliases that switchTab remaps (→ inventory / → research); they have no
    // own #tab- element, so exempt them from the existence guard or a
    // deep-link like #/documents would silently no-op. switchTab itself
    // warns on junk — this guard just avoids touching RunsTab state for a
    // bad hash.
    if (!document.getElementById('tab-' + route.tab)
        && route.tab !== 'discover' && route.tab !== 'documents') return;
    switchTab(route.tab);
    if (route.tab === 'runs' && route.arg && window.RunsTab) {
      // select() fetches the run directly, so it works before the runs
      // list lands; the row highlight catches up when load() renders.
      RunsTab.select(route.arg);
    }
  }
  document.addEventListener('DOMContentLoaded', () => go(parse()));
  window.addEventListener('hashchange', () => go(parse()));
}
