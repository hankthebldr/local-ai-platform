// workspace-legacy/composer-view.js — legacy composer view (phase-2 U8; retires Stage 2). df* via window bridge.

export const ComposerView = (function () {
  let _booted = false;

  function init() {
    // Boot the drawflow editor + palette regardless of whether the user
    // had previously visited the legacy Workflows tab.
    try { dfInitEditor(); dfInitPalette(); } catch (e) { console.warn(e); }
    try { ComposerSplit.init(); } catch (_) {}
    updateCanvasEmptyState();
    // Show the begin/end boundary immediately, even on an empty canvas.
    if (typeof dfScheduleAnchorRefresh === 'function') dfScheduleAnchorRefresh();
    if (_booted) {
      // Already initialised — workbenches refresh quickly to pick up
      // server-side changes (newly registered MCP, etc).
      loadWorkbenches();
      return;
    }
    _booted = true;
    // S0: loadAgentsForSelector() moved to ChatView.init() — #agent-select
    // lives in the Chat tab now (cold-start populates there, not here).
    loadWorkbenches();
    composerSwitchBench('steps');
    if (typeof Projects !== 'undefined') Projects.load();
  }

  function updateCanvasEmptyState() {
    const panel = document.querySelector('.composer-canvas-panel');
    if (!panel) return;
    // MS-2: the empty-state overlay is gated on REAL step count, not raw node
    // count. The boot seed is scaffolding (an input contract, not a composed
    // step) — counting it would falsely hide the "Compose a workflow" guide on
    // a fresh canvas and, worse, leave the overlay stale after a palette drop.
    const realSteps = Object.keys(dfNodeData || {})
      .filter((k) => dfNodeData[k] && !dfNodeData[k].is_seed).length;
    panel.classList.toggle('has-nodes', realSteps > 0);
    // Spine follows the canvas: dormant ghost when empty, live when primed.
    // It keys off ANY node presence (seed included) — unchanged from prior
    // behavior — so priming the workstream strip is decoupled from the overlay.
    // During a BootSequence reveal we hold it primed (window._bsPriming) so
    // composerNewWorkflow()'s transient 0-node window can't hide the canvas
    // mid-build — drawflow must lay nodes into a visible, sized canvas.
    const anyNodes = Object.keys(dfNodeData || {}).length > 0;
    if (typeof ComposerSplit !== 'undefined') {
      try { ComposerSplit.setSpinePrimed(window._bsPriming ? true : anyNodes); } catch (_) {}
    }
  }

  return { init, updateCanvasEmptyState };
})();
