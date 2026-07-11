// shell/context-node-rail.js — the CANONICAL, kind-agnostic node-rail.
//
// RX-2 lands this shared module and OWNS it (spec Blocker 2). Consumers register
// a node *kind* against a pane + a mount + a render callback; they never
// reimplement rail plumbing. The single pane-guard — the rule that a click in
// one surface can never drive another surface's rail — is declared exactly ONCE
// here, in `activate()`. Operate U14 CONSUMES this module (registers
// kind:'context-node'); it does not re-create it.
//
// No window global, no inline handlers — a pure ES module imported by the
// per-kind rail modules (research/research-node-rail.js today).

export const ContextNodeRail = (function () {
  // kind -> { pane, mount, render, auth }
  const _kinds = Object.create(null);
  // The pane-guard's single piece of memory: which pane last drove a rail.
  let _activePane = null;

  function register(kind, opts) {
    if (!kind || !opts || !opts.pane) return;
    _kinds[kind] = {
      pane: opts.pane,
      mount: opts.mount || null, // element id, or () => Element
      render: typeof opts.render === 'function' ? opts.render : null,
      auth: opts.auth || 'required',
    };
  }

  function isRegistered(kind) { return !!_kinds[kind]; }

  function _resolveMount(k) {
    if (typeof k.mount === 'function') return k.mount();
    if (typeof k.mount === 'string') return document.getElementById(k.mount);
    return null;
  }

  // THE pane-guard — declared once, for every registered kind. A node
  // activation renders a kind's rail ONLY when it originates in that kind's own
  // pane. Because every surface routes its node clicks through this function, a
  // Research-pane click can never paint the Context-pane rail (and vice-versa):
  // activate('research-node', node, 'context') short-circuits to false.
  function activate(kind, node, sourcePane) {
    const k = _kinds[kind];
    if (!k) return false;
    const pane = sourcePane || k.pane;
    if (pane !== k.pane) return false; // cross-pane drive rejected HERE, once
    _activePane = pane;
    const mount = _resolveMount(k);
    if (mount && k.render) {
      try { k.render(node, mount); } catch (_) { /* a bad render never breaks selection */ }
    }
    return true;
  }

  function activePane() { return _activePane; }

  function clear(kind) {
    const k = _kinds[kind];
    if (!k) return;
    const mount = _resolveMount(k);
    if (mount) mount.innerHTML = '';
  }

  return { register, isRegistered, activate, activePane, clear };
})();
