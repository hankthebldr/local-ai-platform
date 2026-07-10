// workspace-legacy/chat-view.js — standalone Chat tab (S0 chat extraction).
// Mirrors ComposerView: an ES-module facade whose body calls the legacy
// chat functions as BARE references — they resolve through the window
// bridge (legacy-bridge.js) at call time, so no import cycle and no new
// window global. The chat JS itself stays in main.js (monolithic), which
// is what keeps the lexical dfNodeData bridge to the step-engage branch
// of sendMessage() intact across the DOM move.

export const ChatView = (function () {
  let _booted = false;

  function init() {
    // Refresh on every visit — models and roles change server-side.
    try { loadModels(); } catch (e) { console.warn(e); }
    try { populateSystemPromptRoles(); } catch (e) { console.warn(e); }
    if (_booted) return;
    _booted = true;
    // Cold start: Chat may be opened BEFORE the Composer has ever booted,
    // so the agent selector must populate here (moved out of ComposerView).
    try { loadAgentsForSelector(); } catch (e) { console.warn(e); }
  }

  return { init };
})();
