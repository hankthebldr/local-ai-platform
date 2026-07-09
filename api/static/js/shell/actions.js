// shell/actions.js — data-action delegation router (phase-2 U3 carve).
// Lazy per-event-type capture dispatch; the 162 Actions.click/change/input
// registration sites stay in main.js and call this instance.

export const Actions = (function () {
  const registry = Object.create(null);
  const installed = new Set();
  function _dispatch(e) {
    let el = e.target instanceof Element ? e.target.closest('[data-action]') : null;
    while (el) {
      const fn = registry[e.type + ':' + el.dataset.action];
      if (fn) { fn(el, e); return; }
      el = el.parentElement && el.parentElement.closest('[data-action]');
    }
  }
  function on(type, map) {
    if (!installed.has(type)) {
      // toggle/focus don't bubble — capture handles them uniformly.
      document.addEventListener(type, _dispatch, { capture: type === 'toggle' });
      installed.add(type);
    }
    for (const k in map) registry[type + ':' + k] = map[k];
  }
  return { on, click: m => on('click', m), change: m => on('change', m), input: m => on('input', m) };
})();
