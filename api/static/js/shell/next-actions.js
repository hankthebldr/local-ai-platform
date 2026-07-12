// shell/next-actions.js — the iteration-chaining "what next?" strip (CH-1).
//
// ONE component. After a lifecycle event (a run finishes ok/failed, a run
// pauses at a gate, a workflow saves) it paints a persist-until-next-event
// strip of `data-action next.*` chips into #next-actions-strip so the operator
// always has the next hop one click away — closing the run→refine→re-run→save
// loop that today dead-ends at "the run finished, now what?".
//
// Persist-until-next-event: the strip stays visible until the NEXT lifecycle
// event replaces it (render) or the canvas is cleared (clear). It never
// auto-dismisses on a timer — the operator decides when they're done with it.
//
// No inline handlers, no window globals: chips carry data-action + data-*
// context attributes; main.js registers the `next.*` delegated handlers. The
// `research.done` + `chat.crystallized` rows are declared here as hooks that
// RX (research promote) and GP-1 (chat crystallize) mount into the same strip.

const MOUNT_ID = 'next-actions-strip';

// event → ordered chips. Each chip: { action, label, title, tone? }.
// `tone` maps to a chip accent class (accent / danger / ghost); default ghost.
const ROWS = {
  'run.finished.ok': [
    { action: 'next.save', label: '⤓ Save workflow', title: 'Persist this workflow so you can re-run and schedule it', tone: 'accent' },
    { action: 'next.rerun', label: '⟳ Re-run', title: 'Run it again with the same seed' },
    { action: 'next.schedule', label: '⏱ Schedule', title: 'Run it on a schedule (Operate plane)' },
    { action: 'next.promote', label: '↗ Promote', title: 'Promote this run into a workspace (Operate plane)' },
  ],
  'run.finished.failed': [
    { action: 'next.fix-step', label: '✎ Fix failing step', title: 'Open the failing step on the canvas to edit it', tone: 'accent' },
    { action: 'next.resume', label: '▶ Resume from failure', title: 'Re-dispatch from the failed step once you have saved your fix' },
    { action: 'next.rerun', label: '⟳ Re-run', title: 'Start a fresh run from the top' },
  ],
  'run.awaiting_gate': [
    { action: 'next.review-gate', label: '⚑ Review gate', title: 'Open the run to approve or reject the pending gate', tone: 'accent' },
  ],
  'save.ok': [
    { action: 'next.run', label: '▶ Run it live', title: 'Run the workflow you just saved and watch it live', tone: 'accent' },
    { action: 'next.schedule', label: '⏱ Schedule', title: 'Run it on a schedule (Operate plane)' },
  ],
  // Hooks for other builds — declared here so the strip is the ONE surface for
  // "what next" across the app. RX mounts research.done; GP-1 mounts
  // chat.crystallized. Empty until those builds populate them.
  'research.done': [
    { action: 'next.promote', label: '↗ Save to workspace', title: 'Promote this research artifact into a workspace (Operate plane)' },
  ],
  'chat.crystallized': [
    { action: 'next.run', label: '▶ Run it live', title: 'Run the workflow crystallized from this chat', tone: 'accent' },
  ],
};

function _toneClass(tone) {
  if (tone === 'accent') return 'na-chip na-accent';
  if (tone === 'danger') return 'na-chip na-danger';
  return 'na-chip';
}

// Last context so a delegated handler that wasn't given data-* attributes can
// still recover the run/workflow it applies to. Chips carry the same values as
// data-* attributes; this is the fallback for programmatic callers.
let _ctx = {};

export const NextActions = (function () {
  function ctx() { return _ctx; }

  // Paint the strip for `event`. `context` = { runId?, workflowId?, stepId? }.
  // Unknown events clear the strip (defensive — never leave a stale strip up).
  function render(event, context) {
    const host = document.getElementById(MOUNT_ID);
    if (!host) return;
    const rows = ROWS[event];
    _ctx = context || {};
    if (!rows || !rows.length) { clear(); return; }
    const d = _ctx;
    const attrs = [
      d.runId ? ` data-run-id="${_esc(d.runId)}"` : '',
      d.workflowId ? ` data-wf-id="${_esc(d.workflowId)}"` : '',
      d.stepId ? ` data-step-id="${_esc(d.stepId)}"` : '',
    ].join('');
    host.innerHTML =
      '<span class="na-lead" aria-hidden="true">Next</span>' +
      rows.map(c =>
        `<button type="button" class="${_toneClass(c.tone)}" data-action="${_esc(c.action)}"${attrs}` +
        ` title="${_esc(c.title || '')}">${_esc(c.label)}</button>`
      ).join('');
    host.dataset.event = event;
    host.hidden = false;
  }

  function clear() {
    const host = document.getElementById(MOUNT_ID);
    if (!host) return;
    host.innerHTML = '';
    host.hidden = true;
    delete host.dataset.event;
  }

  return { render, clear, ctx };
})();

// Local escaper — the strip is imported before main.js's dom.js graph is on
// window, and the values (ids, static labels) are trusted, but attribute-
// encoding untrusted-shaped ids (run/workflow ids) is cheap insurance.
function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
