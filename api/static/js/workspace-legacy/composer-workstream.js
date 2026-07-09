// workspace-legacy/composer-workstream.js — legacy composer workstream (phase-2 U7; retires in Stage 2).
// df* refs (dfApplyRunState/dfClearRunState) resolve via the window bridge at runtime.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, EmptyState, ErrorPanel, Skeleton } from '../core/ui.js';

export const ComposerWorkstream = (function () {
  const panes = ['step', 'run', 'history'];

  function _setActive(name) {
    panes.forEach(p => {
      const tab  = document.querySelector('.workstream-tab[data-ws="' + p + '"]');
      const pane = document.getElementById('ws-pane-' + p);
      if (!pane) return;
      const on = (p === name);
      pane.hidden = !on;
      if (tab) tab.classList.toggle('active', on);
    });
  }

  function switchTab(name, _el) {
    _setActive(name);
    if (name === 'run')     _refreshRun();
    if (name === 'history') _refreshHistory();
  }

  function focusStep(stepId) {
    // Called by the canvas node-click handler so the bottom strip pulls
    // attention to Step Config whenever a node is selected.
    _setActive('step');
    const meta = document.getElementById('ws-step-meta');
    if (meta) {
      meta.textContent = stepId ? '#' + stepId : '(none)';
      meta.setAttribute('data-step-id', stepId || '(none)');
    }
  }

  async function _refreshRun() {
    const body = document.getElementById('ws-run-body');
    if (!body) return;
    // _lastRunSummary is set by anything that POSTs /api/workflows/run.
    // We don't subscribe to live progress yet — but the Active Run pane
    // tails the last run so the operator always has somewhere to look.
    const last = window._lastRunSummary;
    if (!last) {
      EmptyState.render(body, {
        title: 'No active run',
        detail: 'Hit Run ▶ or Run ▶ live on the toolbar above, or trigger a workflow from the Workflow Index.',
        glyph: '▶',
      });
      _setRunMeta('idle');
      return;
    }
    const steps = (last.step_results || []).map(s => {
      const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
      const stateClass = s.status === 'completed' ? 'ok' : s.status === 'failed' ? 'fail' : 'pending';
      return `
        <div class="ws-run-step ws-run-step-${stateClass}">
          <span class="ws-run-step-id">${esc(s.step_id)}</span>
          <span class="ws-run-step-model">${esc(s.model_used || '?')}</span>
          <span class="ws-run-step-dur">${dur}</span>
          <span class="ws-run-step-status">${esc(s.status)}</span>
        </div>
      `;
    }).join('');
    body.innerHTML = `
      <div class="ws-run-head">
        <strong>${esc(last.workflow_id || '?')}</strong>
        <span class="ws-run-meta">run_id ${esc((last.run_id || '').slice(0, 12))} · status ${esc(last.status || '?')}</span>
        <span style="flex:1"></span>
        <button type="button" class="ws-run-action" data-action="ws.clear-run"
                title="Clear this run output">Clear</button>
        <button type="button" class="ws-run-action ghost" data-action="ws.run-collapse"
                id="ws-run-collapse-btn" title="Minimize / expand the run output">▾</button>
      </div>
      <div class="ws-run-body-collapsible" id="ws-run-body-collapsible">
        ${steps || '<div class="model-empty">no steps reported</div>'}
      </div>
    `;
    _setRunMeta(last.status === 'completed' ? '✓ ' + (last.step_results || []).length + ' steps' : last.status || 'running');
  }

  async function _refreshHistory() {
    const body = document.getElementById('ws-history-body');
    if (!body) return;
    Skeleton.fill(body, 3);
    const r = await Net.call('/api/workflows/runs?limit=20', { silent: true });
    if (!r.ok) {
      ErrorPanel.render(body, {
        title: 'Couldn’t load run history',
        detail: r.error,
        retry: () => _refreshHistory(),
      });
      return;
    }
    const list = r.data;
    const rows = Array.isArray(list) ? list : (list && list.runs) || [];
    if (!rows.length) {
      EmptyState.render(body, {
        title: 'No runs yet',
        detail: 'Run a workflow from the toolbar above or kick one off from the Workflow Index.',
        glyph: '▶',
      });
      const hm = document.getElementById('ws-history-meta');
      if (hm) hm.textContent = '0';
      return;
    }
    body.innerHTML = rows.map(row => {
      const stateClass = row.status === 'completed' ? 'ok' : row.status === 'failed' ? 'fail' : 'pending';
      const ts = row.started_at || row.created_at || '';
      return `
        <div class="ws-history-row ws-history-row-${stateClass}">
          <span class="ws-history-wf">${esc(row.workflow_id || '?')}</span>
          <code class="ws-history-id">${esc((row.run_id || '').slice(0, 12))}</code>
          <span class="ws-history-status">${esc(row.status || '?')}</span>
          <span class="ws-history-ts">${esc(ts)}</span>
        </div>
      `;
    }).join('');
    const hm = document.getElementById('ws-history-meta');
    if (hm) hm.textContent = rows.length + (rows.length === 20 ? '+' : '');
  }

  function _setRunMeta(text) {
    const m = document.getElementById('ws-run-meta');
    if (m) m.textContent = text;
  }

  function recordRun(summary) {
    window._lastRunSummary = summary;
    if (document.querySelector('.workstream-tab[data-ws="run"].active')) _refreshRun();
    else _setRunMeta(summary.status || 'running');
  }

  // Live polling. Call startPolling(run_id) right after POST /run-async;
  // the workstream auto-switches to the Active Run pane and updates the
  // per-step status as the engine checkpoints. Stops when the run reaches
  // a terminal status. Returns a stop() function for the caller.
  let _activePollHandle = null;
  function startPolling(runId, opts) {
    if (!runId) return () => {};
    if (_activePollHandle) clearInterval(_activePollHandle);
    opts = opts || {};
    const intervalMs = opts.interval || 1200;
    _setActive('run');
    _setRunMeta('queued');
    // Prime the canvas with a "queued" overlay so there's instant visual
    // feedback before the first poll response lands.
    if (typeof window.dfApplyRunState === 'function') {
      try { window.dfApplyRunState({ run_id: runId, status: 'queued', step_results: [] }); } catch (_) {}
    }
    const body = document.getElementById('ws-run-body');
    if (body) {
      body.innerHTML = `
        <div class="ws-run-head">
          <strong>${esc(runId.slice(0, 12))}…</strong>
          <span class="ws-run-meta">starting…</span>
          <span style="flex:1"></span>
          <button type="button" class="ws-run-action" data-action="ws.clear-run"
                  title="Cancel + clear this run output">Cancel</button>
          <button type="button" class="ws-run-action ghost" data-action="ws.run-collapse"
                  id="ws-run-collapse-btn" title="Minimize / expand the run output">▾</button>
        </div>
        <div class="ws-run-body-collapsible" id="ws-run-body-collapsible">
          <div class="skeleton skeleton-line long"></div>
          <div class="skeleton skeleton-line short"></div>
          <div class="skeleton skeleton-line long"></div>
        </div>
      `;
    }

    const seen = new Set();
    let lastStatus = '';
    let consecutiveFailures = 0;
    const maxFailures = 5;

    _activePollHandle = setInterval(async () => {
      try {
        // silent + retries:0 — Net's own retry/backoff would mask the
        // failures this counter is designed to count, and stack with
        // the interval timer.
        const r = await Net.call('/api/workflows/runs/' + encodeURIComponent(runId), { silent: true, retries: 0 });
        if (!r.ok) {
          consecutiveFailures++;
          if (consecutiveFailures >= maxFailures) {
            clearInterval(_activePollHandle);
            _activePollHandle = null;
            _setRunMeta('lost contact');
            if (window.Toast) Toast.danger('Run lost', 'Poll repeatedly returned ' + r.status);
          }
          return;
        }
        consecutiveFailures = 0;
        const run = r.data;
        recordRun(run);
        // Live canvas overlay — paints node statuses + the floating
        // progress chip so the operator can SEE which step is running.
        if (typeof window.dfApplyRunState === 'function') {
          try { window.dfApplyRunState(run); } catch (_) {}
        }
        if (document.querySelector('.workstream-tab[data-ws="run"].active')) _refreshRun();
        // Toast new completed steps once each.
        (run.step_results || []).forEach(s => {
          const key = s.step_id + ':' + s.status;
          if (!seen.has(key) && s.status === 'completed') {
            seen.add(key);
            if (window.Toast) {
              Toast.success(
                'Step ' + s.step_id,
                'completed in ' + Math.round(s.duration_seconds || 0) + 's · ' + (s.model_used || '?'),
                { ttl: 3500 }
              );
            }
          }
          if (!seen.has(s.step_id + ':failed') && s.status === 'failed') {
            seen.add(s.step_id + ':failed');
            if (window.Toast) Toast.danger('Step ' + s.step_id + ' failed', s.error || 'unknown error');
          }
        });
        // Terminal status — stop polling.
        if (['completed', 'failed', 'error'].includes(run.status) && lastStatus !== run.status) {
          lastStatus = run.status;
          clearInterval(_activePollHandle);
          _activePollHandle = null;
          if (window.Toast) {
            if (run.status === 'completed') {
              Toast.success('Run complete', run.workflow_id + ' · ' + (run.step_results || []).length + ' steps');
            } else {
              Toast.danger('Run failed', run.error || run.status);
            }
          }
        }
      } catch (e) {
        consecutiveFailures++;
      }
    }, intervalMs);

    return function stop() {
      if (_activePollHandle) {
        clearInterval(_activePollHandle);
        _activePollHandle = null;
      }
    };
  }

  function stopPolling() {
    if (_activePollHandle) {
      clearInterval(_activePollHandle);
      _activePollHandle = null;
    }
  }

  function refresh() {
    const active = document.querySelector('.workstream-tab.active');
    const name = active ? active.dataset.ws : 'step';
    switchTab(name);
  }

  // Wipe the active-run pane and stop any in-flight poller so the
  // operator can clear out a finished run's output without leaving
  // stale step rows on screen.
  function clearRun() {
    // If there's a live run we know about, ask the engine to cancel it
    // before tearing down the local view. Best-effort: a 404 just
    // means the engine never saw it, which is fine.
    const last = window._lastRunSummary;
    const liveId = last && last.run_id &&
      !['completed', 'failed', 'canceled', 'error'].includes((last.status || '').toLowerCase())
      ? last.run_id : null;
    if (liveId) {
      // silent + retries:0 — best-effort cancel; a 404 is expected and fine.
      Net.call(`/api/workflows/runs/${encodeURIComponent(liveId)}/cancel`, { silent: true, retries: 0, init: { method: 'POST' } })
        .then(r => {
          const j = r.ok ? r.data : null;
          if (window.Toast && j && j.accepted) {
            Toast.info('Run cancel requested', 'Engine will stop after the current step.');
          }
        })
        .catch(() => { /* non-fatal */ });
    }
    stopPolling();
    window._lastRunSummary = null;
    const body = document.getElementById('ws-run-body');
    if (body) {
      EmptyState.render(body, {
        title: liveId ? 'Cancel requested' : 'Run cleared',
        detail: liveId
          ? 'The engine will stop at the next step boundary. In-flight LLM calls finish first.'
          : 'Trigger a workflow to populate this pane again.',
        glyph: '▶',
      });
    }
    _setRunMeta(liveId ? 'canceling…' : 'idle');
    // Also wipe canvas overlays so the visual carries no leftover state.
    if (typeof window.dfClearRunState === 'function') {
      try { window.dfClearRunState(); } catch (_) {}
    }
  }

  // Toggle a collapsed state on just the run body (not the whole
  // workstream — that's the panel-level collapse). The head row with
  // run_id + status stays visible so the operator can still see what
  // they're hiding and re-expand later.
  function toggleRunCollapse() {
    const body = document.getElementById('ws-run-body-collapsible');
    const btn  = document.getElementById('ws-run-collapse-btn');
    if (!body) return;
    const collapsed = body.classList.toggle('collapsed');
    if (btn) btn.textContent = collapsed ? '▴' : '▾';
  }

  return {
    switch: switchTab,
    focusStep,
    recordRun,
    refresh,
    startPolling,
    stopPolling,
    clearRun,
    toggleRunCollapse,
  };
})();
