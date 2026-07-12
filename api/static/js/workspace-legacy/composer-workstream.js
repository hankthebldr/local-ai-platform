// workspace-legacy/composer-workstream.js — legacy composer workstream (phase-2 U7; retires in Stage 2).
// df* refs (dfApplyRunState/dfClearRunState) resolve via the window bridge at runtime.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, EmptyState, ErrorPanel, Skeleton } from '../core/ui.js';
import { logChip, stepChips, logBlock } from '../runs/step-log-render.js';

export const ComposerWorkstream = (function () {
  const panes = ['step', 'run', 'history', 'logs', 'in-progress'];

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
    if (name === 'logs')    _refreshLogs();
    // DR-1: In-Progress drafts pane — rendered by main.js (needs snapshot/
    // restore access); bridged onto window.
    if (name === 'in-progress' && typeof window.dfRefreshInProgress === 'function') {
      try { window.dfRefreshInProgress(); } catch (_) {}
    }
  }

  function focusStep(stepId) {
    // Called by the canvas node-click handler so the bottom strip pulls
    // attention to Step Config whenever a node is selected.
    _setActive('step');
    const meta = document.getElementById('ws-step-meta');
    if (meta) {
      meta.textContent = stepId ? '#' + stepId : '(none)';
      meta.setAttribute('data-step-id', stepId || '(none)');
      // A real node selection supersedes any bench inspection (BU5) —
      // the Step Config form the canvas renders wins over lingering
      // inspector content, so drop the inspect stamp.
      meta.removeAttribute('data-inspect-kind');
    }
  }

  // ── BU5: polymorphic bench inspector ──────────────────────────────
  // Hover/focus on a bench card paints a read-only detail view of the
  // RESOLVED object (agent / task template / capability) into the
  // bottom Step Config pane. Contract:
  //   - writes #df-config-panel ONLY — never auto-opens the popup;
  //   - switches the workstream to the step pane;
  //   - stamps #ws-step-meta with data-inspect-kind while data-step-id
  //     stays '(none)' — a node selection (focusStep +
  //     dfRenderConfigPanel) always wins by overwriting both.
  // The hover handlers live in main.js next to the bench caches and
  // pass the resolved object in — no cross-module state, no globals.

  function _inspKv(label, value) {
    if (value == null || value === '') return '';
    return `<div class="ws-insp-row" style="display:flex;gap:8px;padding:3px 0;font-size:0.66rem">
      <span style="min-width:76px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;font-size:0.54rem;padding-top:2px">${esc(label)}</span>
      <span style="color:var(--text);word-break:break-word">${esc(value)}</span>
    </div>`;
  }

  function _inspChips(label, items) {
    if (!items || !items.length) return _inspKv(label, 'none');
    return `<div class="ws-insp-row" style="display:flex;gap:8px;padding:3px 0">
      <span style="min-width:76px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.08em;font-size:0.54rem;padding-top:2px">${esc(label)}</span>
      <span style="display:flex;flex-wrap:wrap;gap:4px">${items.map(i => `<span class="df-tag">${esc(i)}</span>`).join('')}</span>
    </div>`;
  }

  function _inspBlock(label, text) {
    if (!text) return '';
    return `<div style="padding:6px 0 2px">
      <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:4px;font-weight:600">${esc(label)}</div>
      <div style="font-size:0.64rem;color:var(--text-muted);white-space:pre-wrap;word-break:break-word;max-height:120px;overflow:auto">${esc(text)}</div>
    </div>`;
  }

  function _renderInspector(spec) {
    const panel = document.getElementById('df-config-panel');
    if (!panel) return;
    const kind = spec.kind || 'inspect';
    panel.innerHTML = `
      <div class="ws-inspector" data-inspect-kind="${esc(kind)}">
        <div style="display:flex;align-items:baseline;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
          <strong style="font-size:0.72rem;color:var(--text)">${esc(spec.title || '')}</strong>
          <span class="workbench-item-pill">${esc(kind)}</span>
          <span style="flex:1"></span>
          <span style="font-size:0.52rem;color:var(--text-faint);letter-spacing:0.06em">read-only — click a canvas node for Step Config</span>
        </div>
        ${spec.html || ''}
      </div>`;
    const title = document.getElementById('df-config-title');
    if (title) title.textContent = spec.title || 'Inspector';
    _setActive('step');
    const meta = document.getElementById('ws-step-meta');
    if (meta) {
      meta.textContent = spec.title || '(inspect)';
      meta.setAttribute('data-inspect-kind', kind);
      meta.setAttribute('data-step-id', '(none)');
    }
  }

  // AGENT = model + tools + context — who does the work (ask #6).
  function inspectAgent(a) {
    if (!a) return;
    const tools = (a.tools || []).map(t => {
      if (typeof t === 'string') return t;
      if (t.plugin_id)  return `${t.plugin_id}__${t.tool_id || '*'}`;
      if (t.mcp_server) return `mcp__${t.mcp_server}__${t.tool_id || '*'}`;
      return t.type || t.id || t.name || 'tool';
    });
    const context = (a.context || []).map(c =>
      typeof c === 'string' ? c : (c.label || c.value || c.type || 'source'));
    const html =
      _inspKv('Model', a.model || '(role-based)') +
      _inspKv('Role', a.role || 'general') +
      _inspChips('Tools', tools) +
      _inspChips('Context', context) +
      _inspBlock('Description', (a.description || '').trim()) +
      _inspBlock('System prompt', (a.system_prompt || '').trim());
    _renderInspector({ title: a.name || a.id, kind: 'agent', html });
  }

  // TASK = agentic instructions — how the agent behaves (ask #7) — plus
  // the engine kind the template compiles to (Task bench cards all emit
  // an llm step; templates may declare their own kind).
  function inspectTemplate(tpl) {
    if (!tpl) return;
    const html =
      _inspKv('Compiles to', 'kind: ' + (tpl.kind || 'llm')) +
      _inspKv('Routing class', tpl.role || 'general') +
      _inspChips('Outputs', tpl.outputs || []) +
      _inspKv('Output format', tpl.format || '') +
      _inspBlock('Instructions', tpl.prompt || tpl.system_prompt || tpl.desc || '');
    _renderInspector({ title: tpl.name || tpl.key, kind: 'template', html });
  }

  // PATTERN = a whole sub-DAG topology (PT-1). The caller (main.js) owns the
  // shared dfRenderPatternStructure renderer and passes the built HTML in;
  // this just paints it through the same read-only inspector seam so a canvas
  // node selection always wins over the drill-down.
  function inspectPattern(spec) {
    if (!spec) return;
    _renderInspector({ title: spec.title || 'Pattern', kind: 'pattern', html: spec.html || '' });
  }

  // CAPABILITY = skill / plugin (tool) / MCP server (tool) detail.
  // cap: { kind:'skill', pluginId, skill } |
  //      { kind:'plugin', plugin, tool? } |
  //      { kind:'mcp', server, tool? }
  function inspectCapability(cap) {
    if (!cap) return;
    let title = '', html = '';
    if (cap.kind === 'skill') {
      const s = cap.skill || {};
      const triggers = (s.triggers || []).map(t => (t && t.keyword) || t).filter(Boolean);
      title = s.name || s.id || 'skill';
      html =
        _inspKv('Ref', `${cap.pluginId || '?'}::${s.id || '?'}`) +
        _inspChips('Triggers', triggers) +
        _inspBlock('Description', s.description || '');
    } else if (cap.kind === 'plugin') {
      const p = cap.plugin || {};
      title = (cap.tool && (cap.tool.id || cap.tool.name)) || p.name || p.id || 'plugin';
      html = cap.tool
        ? _inspKv('Ref', `${p.id}__${cap.tool.id}`) +
          _inspChips('Parameters', Object.keys(cap.tool.parameters || {})) +
          _inspBlock('Description', cap.tool.description || '')
        : _inspKv('Version', p.version || '0.0') +
          _inspChips('Tools', (p.tools || []).map(t => t.id || t.name)) +
          _inspBlock('Description', p.description || '');
    } else if (cap.kind === 'mcp') {
      const srv = cap.server || {};
      title = (cap.tool && (cap.tool.name || cap.tool.id)) || srv.name || srv.id || 'mcp';
      html =
        _inspKv('Server', srv.id || '?') +
        _inspKv('Transport', srv.transport || 'mcp') +
        _inspKv('Enabled', srv.enabled === false ? 'no' : 'yes') +
        (cap.tool
          ? _inspKv('Ref', `mcp__${srv.id}__${cap.tool.name || cap.tool.id}`) +
            _inspBlock('Description', cap.tool.description || '')
          : _inspChips('Tools', (srv.tools || []).map(t => t.name || t.id)) +
            _inspBlock('Description', srv.description || ''));
    } else if (cap.kind === 'prompt') {
      // PB-1 — a saved role/template. Reads its summary record (no body on
      // the list endpoint) so the inspector stays a cheap, read-only peek.
      const p = cap.prompt || {};
      title = p.name || p.id || 'prompt';
      html =
        _inspKv('Kind', p.kind || 'role') +
        _inspKv('Ref', p.id || '?') +
        _inspKv('Provenance', p.provenance || 'oob') +
        _inspChips('Variables', p.variables || []) +
        _inspBlock('Summary', p.summary || '');
    } else {
      return;
    }
    _renderInspector({ title, kind: cap.kind, html });
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
        detail: 'Hit Run ▶ or Run ▶ live on the toolbar above, or trigger a workflow from the Workflows tab.',
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
        detail: 'Run a workflow from the toolbar above or kick one off from the Workflows tab.',
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

  // ── BU6: Logs pane — per-step I/O + strategy strip ─────────────────
  // Resolves the active run the same way the Active Run pane does
  // (window._lastRunSummary, set by anything that runs a workflow) and
  // fetches the full run record — per-step rendered prompts and the
  // workspace outputs live in run.json, NOT in the SSE event stream.
  // Tool-call args/bodies are never persisted, so the strategy strip is
  // explicitly metadata-only (name · duration · status).
  const _expandedLogs = new Set();  // 'stepId:input' / 'stepId:output' keys
  let _logsRun = null;              // last fetched run, for toggle re-renders

  function _setLogsMeta(text) {
    const m = document.getElementById('ws-logs-meta');
    if (m) m.textContent = text;
  }

  // U7: the chip + block renderers now live in runs/step-log-render.js so the
  // Runs step-expand row and this pane render one grammar. These two thin
  // shims keep the local call-sites (and any legacy caller) working for one
  // release; they forward to the shared joined-mode renderer.
  function _logChip(name, duration, status) {
    return logChip(name, duration, status, { esc });
  }

  function _logBlock(stepId, which, label, text, captured) {
    return logBlock({ mode: 'joined', stepId, which, label, text, captured,
      expanded: _expandedLogs, esc });
  }

  function _renderLogs() {
    const body = document.getElementById('ws-logs-body');
    if (!body || !_logsRun) return;
    const run = _logsRun;
    const steps = run.step_results || [];
    if (!steps.length) {
      EmptyState.render(body, {
        title: 'No steps yet',
        detail: 'The engine hasn’t reported any step results for this run.',
        glyph: '≡',
      });
      _setLogsMeta(run.status || '—');
      return;
    }
    const workspace = (run.context && run.context.workspace) || {};
    body.innerHTML = steps.map(s => {
      // Input = what the engine actually sent (rendered Jinja2 prompts).
      const promptParts = [];
      if (s.rendered_system_prompt) promptParts.push('[system]\n' + s.rendered_system_prompt);
      if (s.rendered_prompt)        promptParts.push(s.rendered_prompt);
      const hasPrompt = promptParts.length > 0;
      // Output = this step's slice of the three-layer context workspace.
      const out = workspace[s.step_id];
      const hasOut = out !== undefined && out !== null;
      const outText = !hasOut ? 'no output captured'
        : (typeof out === 'string' ? out : JSON.stringify(out, null, 2));
      // Strategy strip — metadata only (args/bodies aren't persisted). Built
      // by the shared renderer so Composer and Runs surface identical chips.
      const stateClass = s.status === 'completed' ? 'ok' : s.status === 'failed' ? 'fail' : 'pending';
      const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
      return `
        <div class="ws-log-step ws-run-step-${stateClass}" data-step-id="${esc(s.step_id)}"
             style="padding:6px 0;border-bottom:1px solid var(--border)">
          <div style="display:flex;align-items:baseline;gap:8px">
            <strong style="font-size:0.66rem;color:var(--text)">${esc(s.step_id)}</strong>
            ${s.kind ? '<span class="workbench-item-pill">' + esc(s.kind) + '</span>' : ''}
            <span style="flex:1"></span>
            <span style="font-size:0.56rem;color:var(--text-muted)">${esc(s.model_used || '?')} · ${dur} · ${esc(s.status || '?')}</span>
          </div>
          ${_logBlock(s.step_id, 'input', 'Input', hasPrompt ? promptParts.join('\n\n') : 'prompt not captured', hasPrompt)}
          ${_logBlock(s.step_id, 'output', 'Output', outText, hasOut)}
          ${stepChips(s, { esc })}
        </div>`;
    }).join('');
    _setLogsMeta(steps.length + ' steps');
  }

  async function _refreshLogs() {
    const body = document.getElementById('ws-logs-body');
    if (!body) return;
    const last = window._lastRunSummary;
    if (!last || !last.run_id) {
      _logsRun = null;
      EmptyState.render(body, {
        title: 'No run yet',
        detail: 'Run the workflow to see per-step logs.',
        glyph: '≡',
      });
      _setLogsMeta('idle');
      return;
    }
    // silent + retries:0 — same posture as the run poller; the pane just
    // keeps its last render if a single fetch drops.
    const r = await Net.call('/api/workflows/runs/' + encodeURIComponent(last.run_id), { silent: true, retries: 0 });
    if (!r.ok) {
      if (!_logsRun) {
        ErrorPanel.render(body, {
          title: 'Couldn’t load run logs',
          detail: r.error,
          retry: () => _refreshLogs(),
        });
      }
      return;
    }
    _logsRun = r.data;
    _renderLogs();
  }

  // Expand/collapse one Input/Output block. Membership in _expandedLogs
  // survives the 1200 ms poll re-render, so open blocks stay open while
  // a live run streams in.
  function toggleLogExpand(el) {
    const key = (el && el.dataset.logKey) || '';
    if (!key) return;
    if (_expandedLogs.has(key)) _expandedLogs.delete(key);
    else _expandedLogs.add(key);
    if (_logsRun) _renderLogs();
    else _refreshLogs();
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
        // BU6: keep the Logs pane live too while it's the active tab.
        if (document.querySelector('.workstream-tab[data-ws="logs"].active')) _refreshLogs();
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
    inspectAgent,
    inspectCapability,
    inspectTemplate,
    inspectPattern,
    _renderInspector,
    recordRun,
    refresh,
    startPolling,
    stopPolling,
    clearRun,
    toggleRunCollapse,
    toggleLogExpand,
  };
})();
