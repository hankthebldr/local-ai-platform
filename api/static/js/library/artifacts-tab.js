// library/artifacts-tab.js — Operate Artifacts tab (O5, U11).
//
// A three-pane Operate surface over three already-shipped read/write backends
// (the frozen engine is never touched):
//
//   outputs      GET /api/artifacts        — unified run/feedback/export inventory
//                (facets, provenance, capped preview, download, promote→feedback,
//                 open-run pivot to the U7 shared Runs render).
//   workspaces   GET /api/workspaces       — the in-platform C2 local-directory
//                runtime (stats/files/indexes + Requeue-stale / Render-MOC,
//                "Schedules operating here" filtered on ScheduleDefinition.workspace,
//                a workspace-prefilled scheduled-run wizard, + Bind Directory).
//                RX-2's Obsidian-like 'research' store IS one of these workspaces —
//                this pane LISTS it read-only and never forks a rival store or adds
//                ingest/write paths (writes stay through research.save-source).
//   formats      GET /api/format-sets      — output-format instruction presets;
//                edit/test/delete + a serialized-constraint preview. The Composer
//                bakes a chosen set into a step via the [format:<id>@<version>]
//                sentinel (see main.js dfComposeYamlString / composerLoadById).
//
// Each pane mounts a LibraryShell adapter. Per the renderLock rule (Hard
// constraints, F5): the outputs adapter is auth:'none' (reads only); the
// workspace + format-set adapters are auth:'optional' — writes carry explicit
// AdminAuth headers and a 401 renders a SCOPED lock row inside the pane, never
// AdminAuth.renderLock (which would wipe #tab-artifacts). No inline on*=
// handlers, no window globals: all wiring rides the delegated Actions table.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { LibraryWizard } from './wizard.js';
import { SchedulesView } from '../runs/schedules-view.js';

export const ArtifactsTab = (function () {
  const OUT = 'artifact-output';
  const WS = 'workspace';
  const FMT = 'format-set';

  let _pane = 'outputs';
  let _mounted = Object.create(null);   // kind → true once its shell is mounted

  // ── Outputs state ─────────────────────────────────────────────────────────
  let _outItems = [];
  let _outFacets = { source: {}, type: {}, model: {} };
  const _outFilter = { source: '', type: '' };
  const _outDetailCache = Object.create(null);   // id → detail promise

  // ── Workspaces state ──────────────────────────────────────────────────────
  let _wsRows = [];
  const _wsDetailCache = Object.create(null);    // name → {workspace, stats}
  const _wsIndexCache = Object.create(null);     // name → indexes[]
  let _schedulesAvailable = true;                // flips false only on endpoint-404

  // ── Format-set state ──────────────────────────────────────────────────────
  let _fmtRows = [];
  const _fmtDetailCache = Object.create(null);   // id → full record
  const _fmtPreviewCache = Object.create(null);  // id → preview

  function _authHeaders() {
    return (window.AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }
  function _when(iso) {
    if (!iso) return '—';
    const s = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z';
    const d = new Date(s);
    return isNaN(d.getTime()) ? '—'
      : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  function _bytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }
  // Scoped write-401 lock row inside a pane container (never a tab wipe).
  function _lockRow(hostId, msg) {
    const host = document.getElementById(hostId);
    if (!host) { Toast.warn('Sign in required', msg || 'Master key required.'); return; }
    if (host.querySelector('.artifacts-lock-row')) return;
    const row = document.createElement('div');
    row.className = 'artifacts-lock-row sched-lock-row';
    row.innerHTML = `<span class="sched-lock-icon" aria-hidden="true">🔒</span>
      <span class="sched-lock-msg">${esc(msg || 'Master key required for this action.')}</span>
      <button type="button" class="action-btn xs" data-action="admin.sign-in">Sign in</button>`;
    host.insertBefore(row, host.firstChild);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  OUTPUTS pane — adapter artifact-output (auth:'none')
  // ════════════════════════════════════════════════════════════════════════
  const _SRC_LABEL = { run: 'Run', feedback: 'Feedback', export: 'Export' };

  async function _outLoad() {
    const params = new URLSearchParams({ limit: '200', offset: '0' });
    if (_outFilter.source) params.set('source', _outFilter.source);
    if (_outFilter.type) params.set('type', _outFilter.type);
    const r = await LibraryShell.fetch(OUT, `/api/artifacts?${params.toString()}`);
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _outItems = (r.data && r.data.items) || [];
    _outFacets = (r.data && r.data.facets) || { source: {}, type: {}, model: {} };
    for (const k of Object.keys(_outDetailCache)) delete _outDetailCache[k];
    _renderFacets();
  }
  function _outFetchDetail(id) {
    if (_outDetailCache[id]) return _outDetailCache[id];
    _outDetailCache[id] = (async () => {
      const r = await LibraryShell.fetch(OUT, `/api/artifacts/${encodeURIComponent(id)}`);
      if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
      return r.data;
    })();
    return _outDetailCache[id];
  }
  function _outRow(id) { return _outItems.find(x => x.id === id) || null; }

  function _renderFacets() {
    const host = document.getElementById('artifacts-facets');
    if (!host) return;
    const chip = (dim, val, count, active) =>
      `<button type="button" class="artifacts-facet-chip${active ? ' active' : ''}"
         data-action="artifacts.filter" data-dim="${esc(dim)}" data-val="${esc(val)}"
         aria-pressed="${active}">${esc(val)}<span class="artifacts-facet-n">${count}</span></button>`;
    const sources = Object.keys(_outFacets.source || {}).sort();
    const types = Object.keys(_outFacets.type || {}).sort();
    host.innerHTML = `
      <div class="artifacts-facet-group">
        <span class="artifacts-facet-label">Source</span>
        <button type="button" class="artifacts-facet-chip${!_outFilter.source ? ' active' : ''}"
          data-action="artifacts.filter" data-dim="source" data-val=""
          aria-pressed="${!_outFilter.source}">All</button>
        ${sources.map(s => chip('source', s, _outFacets.source[s], _outFilter.source === s)).join('')}
      </div>
      <div class="artifacts-facet-group">
        <span class="artifacts-facet-label">Type</span>
        <button type="button" class="artifacts-facet-chip${!_outFilter.type ? ' active' : ''}"
          data-action="artifacts.filter" data-dim="type" data-val=""
          aria-pressed="${!_outFilter.type}">All</button>
        ${types.map(t => chip('type', t, _outFacets.type[t], _outFilter.type === t)).join('')}
      </div>`;
  }

  const _outAdapter = {
    kind: OUT,
    title: 'Outputs',
    tabId: 'tab-artifacts',
    countBadgeId: 'artifacts-count',
    auth: 'none',
    emptyText: 'No outputs yet — run a workflow to produce artifacts.',
    emptyDetailText: 'Select an output to see its provenance, preview, and pivots.',
    emptyDetailLabel: '// OUTPUT',
    load: _outLoad,
    list() {
      return _outItems.map(it => {
        const prov = it.provenance || {};
        const chips = [{ label: _SRC_LABEL[it.source] || it.source, cls: `artifacts-src-${esc(it.source)}` }];
        if (it.type) chips.push({ label: it.type, cls: 'artifacts-type-chip' });
        return {
          id: it.id,
          title: it.title || it.id,
          meta: `${_when(it.produced_at)} · ${_bytes(it.size_bytes)}${prov.model_used ? ' · ' + prov.model_used : ''}`,
          group: _SRC_LABEL[it.source] || it.source,
          chips,
        };
      });
    },
    detail(id) {
      return {
        sections: {
          overview: (el) => _outOverview(el, id),
          files: (el) => _outFiles(el, id),
          relations: (el) => _outRelations(el, id),
        },
      };
    },
    sectionLabels: { files: 'Preview', relations: 'Provenance' },
    actions(id) {
      const row = _outRow(id);
      const prov = (row && row.provenance) || {};
      const acts = [
        { verb: 'test', label: 'Download', action: 'artifacts.download', data: { 'art-id': id } },
        { verb: 'promote', label: 'Promote to Research', action: 'artifacts.promote', accent: true, data: { 'art-id': id } },
      ];
      if (prov.run_id) {
        acts.push({ verb: 'edit', label: 'Open run ▸', action: 'artifacts.open-run', data: { 'run-id': prov.run_id } });
      }
      return acts;
    },
    onSelect(id) { _outFetchDetail(id); },
  };

  async function _outOverview(el, id) {
    let d;
    try { d = await _outFetchDetail(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    const prov = d.provenance || {};
    const provRows = prov.run_id ? `
      <div class="artifacts-kv"><span>Run</span><span><code>${esc(prov.run_id)}</code></span></div>
      ${prov.step_id ? `<div class="artifacts-kv"><span>Step</span><span>${esc(prov.step_id)}</span></div>` : ''}
      ${prov.workflow_id ? `<div class="artifacts-kv"><span>Workflow</span><span>${esc(prov.workflow_id)}</span></div>` : ''}
      ${prov.model_used ? `<div class="artifacts-kv"><span>Model</span><span>${esc(prov.model_used)}</span></div>` : ''}`
      : '<div class="artifacts-kv"><span>Provenance</span><span style="color:var(--text-muted)">(none — not run-produced)</span></div>';
    el.innerHTML = `
      <div class="artifacts-ov">
        <div class="artifacts-kv"><span>Source</span><span>${esc(_SRC_LABEL[d.source] || d.source)}</span></div>
        <div class="artifacts-kv"><span>Type</span><span>${esc(d.type)}</span></div>
        <div class="artifacts-kv"><span>Produced</span><span>${_when(d.produced_at)}</span></div>
        <div class="artifacts-kv"><span>Size</span><span>${_bytes(d.size_bytes)}</span></div>
        ${provRows}
      </div>`;
  }
  async function _outFiles(el, id) {
    let d;
    try { d = await _outFetchDetail(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    const preview = d.preview || '';
    el.innerHTML = `
      <div class="artifacts-preview-head">
        <span>Body preview${d.preview_truncated ? ' · truncated' : ''}</span>
        <button type="button" class="action-btn xs" data-action="artifacts.download" data-art-id="${esc(id)}">Download</button>
      </div>
      <pre class="artifacts-preview">${esc(preview) || '<span style="color:var(--text-muted)">(empty)</span>'}</pre>`;
  }
  async function _outRelations(el, id) {
    let d;
    try { d = await _outFetchDetail(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    const prov = d.provenance || {};
    if (!prov.run_id) { el.innerHTML = '<div class="model-empty">No run provenance — this output is a standalone capture or export.</div>'; return; }
    el.innerHTML = `
      <div class="artifacts-rel">
        <p class="artifacts-rel-note">This output was produced by a workflow run. Open the run to inspect its per-step inputs and outputs.</p>
        <button type="button" class="action-btn accent" data-action="artifacts.open-run" data-run-id="${esc(prov.run_id)}">Open run ${esc(prov.run_id.slice(0, 8))} ▸</button>
      </div>`;
  }

  // Pivot to the Runs tab + shared per-step render (never duplicated here).
  function _openRun(runId) {
    if (!runId) return;
    try { if (window.SchedulesView && SchedulesView.setRailMode) SchedulesView.setRailMode('runs'); } catch (_) {}
    try { if (typeof window.switchTab === 'function') window.switchTab('runs'); } catch (_) {}
    try { if (window.RunsTab && RunsTab.select) RunsTab.select(runId); } catch (_) {}
    try { location.hash = '#/runs/' + runId; } catch (_) {}
  }

  async function _download(id) {
    const r = await Net.call(`/api/artifacts/${encodeURIComponent(id)}/raw`, {
      retries: 0, init: { method: 'GET', headers: _authHeaders() },
    });
    if (!r.ok) {
      if (r.status === 401) return _lockRow('artifacts-pane-outputs', 'Sign in to download this artifact.');
      Toast.danger('Download failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
      return;
    }
    // Net.call returns parsed data; fall back to a fresh blob fetch for bytes.
    try {
      const resp = await fetch(`/api/artifacts/${encodeURIComponent(id)}/raw`, { headers: _authHeaders() });
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = id.replace(/[^A-Za-z0-9._-]+/g, '_') + '.txt';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) { Toast.danger('Download failed', e.message); }
  }

  async function _promote(id) {
    let d;
    try { d = await _outFetchDetail(id); } catch (e) { Toast.danger('Promote failed', e.message); return; }
    const prov = d.provenance || {};
    const body = {
      source: 'workflow',
      title: d.title || id,
      body: d.preview || '',
      tags: ['artifact', d.source].filter(Boolean),
      context: {
        run_id: prov.run_id || null,
        step_id: prov.step_id || null,
        workflow_id: prov.workflow_id || null,
        model: prov.model_used || null,
        artifact_id: id,
      },
    };
    const r = await Net.call('/api/feedback/artifacts', {
      retries: 0,
      init: { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()), body: JSON.stringify(body) },
    });
    if (r.ok) { Toast.success('Promoted', 'Captured as a research artifact.'); return; }
    if (r.status === 401) return _lockRow('artifacts-pane-outputs', 'Sign in to promote outputs to research.');
    Toast.danger('Promote failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  WORKSPACES pane — adapter workspace (auth:'optional')
  // ════════════════════════════════════════════════════════════════════════
  async function _wsLoad() {
    const r = await LibraryShell.fetch(WS, '/api/workspaces');
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _wsRows = (r.data && r.data.workspaces) || [];
    for (const k of Object.keys(_wsDetailCache)) delete _wsDetailCache[k];
    for (const k of Object.keys(_wsIndexCache)) delete _wsIndexCache[k];
  }
  async function _wsFetchDetail(name) {
    if (_wsDetailCache[name]) return _wsDetailCache[name];
    const r = await LibraryShell.fetch(WS, `/api/workspaces/${encodeURIComponent(name)}`);
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _wsDetailCache[name] = r.data;
    return r.data;
  }
  async function _wsFetchIndexes(name) {
    if (_wsIndexCache[name]) return _wsIndexCache[name];
    const r = await LibraryShell.fetch(WS, `/api/workspaces/${encodeURIComponent(name)}/indexes`);
    _wsIndexCache[name] = (r.ok && r.data && r.data.indexes) || [];
    return _wsIndexCache[name];
  }
  // "Schedules operating here" — filter GET /api/schedules on the modeled
  // workspace field (C4). Silent-hide only when the endpoint is genuinely
  // absent (404), never for an unknown field.
  async function _wsSchedules(name) {
    if (!_schedulesAvailable) return null;
    const r = await LibraryShell.fetch(WS, '/api/schedules');
    if (r.status === 404) { _schedulesAvailable = false; return null; }
    if (!r.ok) return [];
    return ((r.data && r.data.schedules) || []).filter(s => s.workspace === name);
  }
  function _wsRow(name) { return _wsRows.find(w => w.name === name) || null; }

  const _wsAdapter = {
    kind: WS,
    title: 'Workspaces',
    tabId: 'tab-artifacts',
    auth: 'optional',
    emptyText: 'No workspaces yet. Use + Bind Directory to bind one.',
    emptyDetailText: 'Select a workspace to see its stats, files, indexes, and schedules.',
    emptyDetailLabel: '// WORKSPACE',
    load: _wsLoad,
    list() {
      return _wsRows.map(w => {
        const chips = [];
        const exts = (w.policy && w.policy.allowed_extensions) || null;
        if (exts && exts.length) chips.push({ label: exts.map(e => '.' + e).join(' '), cls: 'artifacts-ext-chip' });
        const badges = [];
        if (w.policy && w.policy.read_only) badges.push({ label: 'read-only', cls: 'artifacts-ro-badge' });
        return {
          id: w.name,
          title: w.name,
          meta: w.root || '',
          group: '',
          chips,
          badges,
        };
      });
    },
    selectAction: 'lib.select',
    detail(name) {
      return {
        sections: {
          overview: (el) => _wsOverview(el, name),
          files: (el) => _wsFiles(el, name),
          relations: (el) => _wsRelations(el, name),
        },
      };
    },
    sectionLabels: { relations: 'Schedules' },
    actions(name) {
      const row = _wsRow(name);
      const ro = row && row.policy && row.policy.read_only;
      return [
        { verb: 'test', label: 'Schedule a run here', action: 'artifacts.ws-schedule', accent: true, data: { 'ws-name': name } },
        { verb: 'edit', label: 'Requeue stale', action: 'artifacts.ws-requeue', enabled: !ro, reason: ro ? 'workspace is read-only' : '', data: { 'ws-name': name } },
        { verb: 'edit', label: 'Render MOC', action: 'artifacts.ws-render', enabled: !ro, reason: ro ? 'workspace is read-only' : '', data: { 'ws-name': name } },
        { verb: 'delete', label: 'Deregister', action: 'artifacts.ws-deregister', danger: true, data: { 'ws-name': name } },
      ];
    },
    onSelect(name) { _wsFetchDetail(name); },
  };

  async function _wsOverview(el, name) {
    let d;
    try { d = await _wsFetchDetail(name); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    const ws = d.workspace || {};
    const st = d.stats || {};
    const pol = ws.policy || {};
    const idxs = await _wsFetchIndexes(name);
    const idxHtml = idxs.length ? idxs.map(ix => {
      const c = ix.counts || {};
      const total = Object.values(c).reduce((a, b) => a + (Number(b) || 0), 0);
      return `<div class="artifacts-idx-row">
        <span class="artifacts-idx-name">${esc(ix.name)}</span>
        <span class="artifacts-idx-counts">${Object.entries(c).map(([k, v]) => `${esc(k)}:${v}`).join(' ')} · ${total} total${ix.complete ? ' · ✓' : ''}</span>
        <span class="artifacts-idx-btns">
          <button type="button" class="action-btn xs" data-action="artifacts.ws-requeue" data-ws-name="${esc(name)}" data-index="${esc(ix.name)}">Requeue stale</button>
          <button type="button" class="action-btn xs" data-action="artifacts.ws-render" data-ws-name="${esc(name)}" data-index="${esc(ix.name)}">Render MOC</button>
        </span>
      </div>`;
    }).join('') : '<div class="model-empty" style="padding:6px 0">No durable indexes bound.</div>';
    el.innerHTML = `
      <div class="artifacts-ov">
        <div class="artifacts-kv"><span>Root</span><span><code>${esc(ws.root || st.root || '')}</code></span></div>
        <div class="artifacts-kv"><span>Files</span><span>${st.file_count != null ? st.file_count : '—'} · ${_bytes(st.total_bytes)}</span></div>
        <div class="artifacts-kv"><span>Read-only</span><span>${pol.read_only ? 'yes' : 'no'}</span></div>
        <div class="artifacts-kv"><span>Extensions</span><span>${(pol.allowed_extensions && pol.allowed_extensions.length) ? pol.allowed_extensions.map(e => '.' + esc(e)).join(' ') : 'any'}</span></div>
        ${ws.description ? `<div class="artifacts-kv"><span>Description</span><span>${esc(ws.description)}</span></div>` : ''}
      </div>
      <div class="artifacts-sub-label">Durable indexes</div>
      <div class="artifacts-idx-list">${idxHtml}</div>`;
  }
  async function _wsFiles(el, name) {
    const r = await LibraryShell.fetch(WS, `/api/workspaces/${encodeURIComponent(name)}/files?glob=*`);
    if (!r.ok) { el.innerHTML = `<div class="model-empty">${esc((r.data && r.data.detail) || r.error || 'Could not list files.')}</div>`; return; }
    const files = (r.data && r.data.files) || [];
    if (!files.length) { el.innerHTML = '<div class="model-empty">No top-level files.</div>'; return; }
    el.innerHTML = `<div class="artifacts-file-list">${files.map(f => {
      const p = typeof f === 'string' ? f : (f.path || f.name || '');
      return `<button type="button" class="btn-unstyled artifacts-file-row" data-action="artifacts.ws-file" data-ws-name="${esc(name)}" data-path="${esc(p)}">${esc(p)}</button>`;
    }).join('')}</div>
    <div class="artifacts-file-view" id="artifacts-file-view"></div>`;
  }
  async function _wsFileView(name, path) {
    const host = document.getElementById('artifacts-file-view');
    if (!host) return;
    host.innerHTML = '<div class="model-empty">Loading…</div>';
    const r = await LibraryShell.fetch(WS, `/api/workspaces/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`);
    if (!r.ok) { host.innerHTML = `<div class="model-empty">${esc((r.data && r.data.detail) || 'Could not read file.')}</div>`; return; }
    host.innerHTML = `<div class="artifacts-preview-head"><span>${esc(path)}</span></div>
      <pre class="artifacts-preview">${esc((r.data && r.data.content) || '')}</pre>`;
  }
  async function _wsRelations(el, name) {
    const scheds = await _wsSchedules(name);
    if (scheds === null) { el.innerHTML = '<div class="model-empty">Scheduling is not available in this build.</div>'; return; }
    const list = scheds.length ? `<div class="artifacts-sched-list">${scheds.map(s => `
      <div class="artifacts-sched-row">
        <span class="lib-dot ${s.enabled ? 'ok' : 'off'}"></span>
        <span class="artifacts-sched-name">${esc(s.name || s.id)}</span>
        <span class="artifacts-sched-cad">${esc(s.cadence_human || (s.cadence && s.cadence.kind) || '')}</span>
      </div>`).join('')}</div>`
      : '<div class="model-empty" style="padding:6px 0">No schedules operate on this workspace yet.</div>';
    el.innerHTML = `
      <div class="artifacts-rel-note">Schedules operating here run a workflow with this workspace injected as its seed context.</div>
      ${list}
      <button type="button" class="action-btn accent" data-action="artifacts.ws-schedule" data-ws-name="${esc(name)}">+ Schedule a run here</button>`;
  }

  // Index mutations — reuse the existing workspace POSTs (master-key gated).
  async function _wsIndexMutate(name, index, verb) {
    if (!index) {
      // No explicit index — pick the first one bound to the workspace.
      const idxs = await _wsFetchIndexes(name);
      if (!idxs.length) { Toast.warn('No index', 'This workspace has no durable index to operate on.'); return; }
      index = idxs[0].name;
    }
    const url = `/api/workspaces/${encodeURIComponent(name)}/index/${encodeURIComponent(index)}/${verb}`;
    const body = verb === 'render' ? JSON.stringify({}) : undefined;
    const r = await Net.call(url, {
      retries: 0,
      init: { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()), body },
    });
    if (r.ok) {
      delete _wsIndexCache[name];
      Toast.success(verb === 'render' ? 'MOC rendered' : 'Requeued', `Index "${index}" updated.`);
      LibraryShell.refreshSection(WS, 'overview');
      return;
    }
    if (r.status === 401) return _lockRow('artifacts-pane-workspaces', 'Sign in to modify workspace indexes.');
    Toast.danger('Failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }

  async function _wsDeregister(name) {
    const ok = await Confirm.ask({
      title: 'Deregister workspace',
      body: `Deregister "${name}"? The directory and its files are NEVER deleted — only the binding is removed. Re-bind any time.`,
      okLabel: 'Deregister', danger: true,
    });
    if (!ok) return;
    const r = await Net.call(`/api/workspaces/${encodeURIComponent(name)}`, {
      retries: 0, init: { method: 'DELETE', headers: _authHeaders() },
    });
    if (r.ok) { await LibraryShell.reload(WS); Toast.success('Deregistered', `"${name}" unbound (files retained).`); return; }
    if (r.status === 401) return _lockRow('artifacts-pane-workspaces', 'Sign in to deregister workspaces.');
    Toast.danger('Deregister failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }

  // + Bind Directory wizard (LibraryWizard; post carries AdminAuth headers).
  function _openBindWizard() {
    LibraryWizard.open({
      title: 'Bind a directory',
      submitLabel: 'Bind directory',
      steps: {
        configure: (bodyEl, state) => {
          const v = state.values;
          bodyEl.innerHTML = `
            <div class="admin-modal-sub">Bind a local directory as a governed workspace. The directory is never modified by binding — Enclave only gains read/write access under the policy you set.</div>
            <label class="admin-modal-label" for="ws-name">Name</label>
            <input id="ws-name" class="chat-input" data-wiz-key="name" value="${esc(v.name || '')}" placeholder="my-notes" autocomplete="off">
            <label class="admin-modal-label" for="ws-root">Directory path <span style="color:var(--text-muted);font-weight:400">(absolute local path)</span></label>
            <input id="ws-root" class="chat-input" data-wiz-key="root" value="${esc(v.root || '')}" placeholder="/home/you/notes" autocomplete="off">
            <label class="admin-modal-label" for="ws-exts">Allowed extensions <span style="color:var(--text-muted);font-weight:400">(comma-separated, blank = any)</span></label>
            <input id="ws-exts" class="chat-input" data-wiz-key="exts" value="${esc(v.exts != null ? v.exts : 'md')}" placeholder="md, txt" autocomplete="off">
            <label class="admin-modal-label" style="display:flex;align-items:center;gap:6px;margin-top:8px">
              <input type="checkbox" data-wiz-key="read_only" ${v.read_only ? 'checked' : ''}> Read-only (refuse every write)
            </label>`;
        },
        confirm: (bodyEl, state) => {
          const v = state.values;
          bodyEl.innerHTML = `
            <div class="admin-modal-sub">Review, then bind the workspace.</div>
            <div class="sched-confirm">
              <div><span>Name</span><span>${esc(v.name || '')}</span></div>
              <div><span>Path</span><span>${esc(v.root || '')}</span></div>
              <div><span>Extensions</span><span>${esc((v.exts || '').trim() || 'any')}</span></div>
              <div><span>Read-only</span><span>${v.read_only ? 'yes' : 'no'}</span></div>
            </div>
            <div id="lib-wizard-result" style="margin-top:10px"></div>`;
        },
      },
      validate: (stepId, state) => {
        if (stepId === 'configure') {
          const v = state.values;
          if (!v.name || !v.name.trim()) return 'Give the workspace a name.';
          if (!v.root || !v.root.trim()) return 'Enter the directory path.';
        }
        return true;
      },
      onSubmit: async (state, { post }) => {
        const v = state.values;
        const exts = (v.exts || '').split(',').map(s => s.trim().replace(/^\./, '')).filter(Boolean);
        const body = {
          name: (v.name || '').trim(),
          root: (v.root || '').trim(),
          policy: {
            read_only: !!v.read_only,
            allowed_extensions: exts.length ? exts : null,
          },
        };
        const r = await post('/api/workspaces', body, _authHeaders());
        if (r.ok) {
          await LibraryShell.reload(WS);
          if (body.name) LibraryShell.select(WS, body.name);
          return { ok: true, message: `Workspace "${body.name}" bound.` };
        }
        if (r.status === 401) return { ok: false, detail: 'Sign in as admin to bind workspaces.' };
        return { ok: false, detail: (r.data && (r.data.detail || r.data.message)) || r.error || 'Bind failed.' };
      },
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  FORMAT SETS pane — adapter format-set (auth:'optional')
  // ════════════════════════════════════════════════════════════════════════
  const _TARGET_LABEL = { html: 'HTML', markdown: 'Markdown', sheet: 'Sheet' };

  async function _fmtLoad() {
    const r = await LibraryShell.fetch(FMT, '/api/format-sets');
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _fmtRows = r.data || [];
    for (const k of Object.keys(_fmtDetailCache)) delete _fmtDetailCache[k];
    for (const k of Object.keys(_fmtPreviewCache)) delete _fmtPreviewCache[k];
  }
  async function _fmtFetch(id) {
    if (_fmtDetailCache[id]) return _fmtDetailCache[id];
    const r = await LibraryShell.fetch(FMT, `/api/format-sets/${encodeURIComponent(id)}`);
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _fmtDetailCache[id] = r.data;
    return r.data;
  }
  async function _fmtPreview(id) {
    if (_fmtPreviewCache[id]) return _fmtPreviewCache[id];
    const r = await Net.call(`/api/format-sets/${encodeURIComponent(id)}/preview`, {
      retries: 0, init: { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()) },
    });
    if (!r.ok) throw new Error((r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
    _fmtPreviewCache[id] = r.data;
    return r.data;
  }
  function _fmtRow(id) { return _fmtRows.find(f => f.id === id) || null; }

  const _fmtAdapter = {
    kind: FMT,
    title: 'Format Sets',
    tabId: 'tab-artifacts',
    auth: 'optional',
    emptyText: 'No format sets. Use + New Format Set to author one.',
    emptyDetailText: 'Select a format set to see its instructions and serialized constraints.',
    emptyDetailLabel: '// FORMAT SET',
    load: _fmtLoad,
    list() {
      return _fmtRows.map(f => ({
        id: f.id,
        title: f.name || f.id,
        meta: f.summary || '',
        group: _TARGET_LABEL[f.target] || f.target || 'Format',
        provenance: f.provenance === 'user' ? 'user' : 'oob',
        chips: [{ label: `v${f.version || 1}`, cls: 'artifacts-ver-chip' }],
      }));
    },
    detail(id) {
      return {
        sections: {
          overview: (el) => _fmtOverview(el, id),
          files: (el) => _fmtBody(el, id),
          test: (el) => _fmtTest(el, id),
        },
      };
    },
    sectionLabels: { files: 'Instructions', test: 'Preview' },
    actions(id) {
      return [
        { verb: 'test', label: 'Preview constraints', action: 'artifacts.fmt-preview', accent: true, data: { 'fmt-id': id } },
        { verb: 'edit', label: 'Edit', action: 'artifacts.fmt-edit', data: { 'fmt-id': id } },
        { verb: 'delete', label: 'Delete', action: 'artifacts.fmt-delete', danger: true, data: { 'fmt-id': id } },
      ];
    },
    onSelect(id) { _fmtFetch(id); },
  };

  async function _fmtOverview(el, id) {
    let d;
    try { d = await _fmtFetch(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    el.innerHTML = `
      <div class="artifacts-ov">
        <div class="artifacts-kv"><span>Name</span><span>${esc(d.name || d.id)}</span></div>
        <div class="artifacts-kv"><span>Target</span><span>${esc(_TARGET_LABEL[d.target] || d.target)}</span></div>
        <div class="artifacts-kv"><span>Version</span><span>v${esc(String(d.version || 1))}</span></div>
        <div class="artifacts-kv"><span>Provenance</span><span>${esc(d.provenance || 'oob')}</span></div>
        ${d.summary ? `<div class="artifacts-kv"><span>Summary</span><span>${esc(d.summary)}</span></div>` : ''}
      </div>`;
  }
  async function _fmtBody(el, id) {
    let d;
    try { d = await _fmtFetch(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    el.innerHTML = `<pre class="artifacts-preview">${esc(d.body || '')}</pre>`;
  }
  async function _fmtTest(el, id) {
    el.innerHTML = '<div class="model-empty">Loading preview…</div>';
    let p;
    try { p = await _fmtPreview(id); } catch (e) { el.innerHTML = `<div class="model-empty">${esc(e.message)}</div>`; return; }
    el.innerHTML = `
      <div class="artifacts-rel-note">These are the exact constraint lines the Composer bakes into a step's <code>prompt.constraints[]</code> when this set is chosen.</div>
      <pre class="artifacts-preview artifacts-sentinel" data-testid="fmt-preview">${esc(p.text || (p.constraints || []).join('\n'))}</pre>`;
  }

  function _openFmtEditor(id) {
    const existing = id ? _fmtDetailCache[id] : null;
    const seedBody = existing ? existing.body : `---
name: My Format Set
summary: One-line description of the output shape.
target: markdown
version: 1
---
Write the deliverable as clean Markdown.
Use ## headings for each section.
`;
    LibraryWizard.open({
      title: id ? `Edit format set ${id}` : 'New format set',
      submitLabel: id ? 'Save changes' : 'Create format set',
      state: { values: { fid: id || '', body: seedBody } },
      steps: {
        configure: (bodyEl, state) => {
          const v = state.values;
          bodyEl.innerHTML = `
            ${id ? '' : `<label class="admin-modal-label" for="fmt-id">Id <span style="color:var(--text-muted);font-weight:400">(alnum, _ , - ; ≤80)</span></label>
            <input id="fmt-id" class="chat-input" data-wiz-key="fid" value="${esc(v.fid || '')}" placeholder="html-report" autocomplete="off">`}
            <label class="admin-modal-label" for="fmt-body">Body <span style="color:var(--text-muted);font-weight:400">(YAML front-matter + markdown instructions)</span></label>
            <textarea id="fmt-body" class="chat-input" data-wiz-key="body" spellcheck="false"
              style="min-height:220px;resize:vertical;font-family:var(--mono,monospace);font-size:0.72rem">${esc(v.body || '')}</textarea>`;
        },
      },
      validate: (stepId, state) => {
        const v = state.values;
        if (stepId === 'configure') {
          if (!id && (!v.fid || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(v.fid))) return 'Enter a valid id (alnum/_/-, ≤80).';
          if (!v.body || !v.body.trim().startsWith('---')) return 'Body must start with YAML front-matter (--- name/summary/target/version ---).';
        }
        return true;
      },
      onSubmit: async (state, { post }) => {
        const v = state.values;
        let r;
        if (id) {
          r = await Net.call(`/api/format-sets/${encodeURIComponent(id)}`, {
            retries: 0,
            init: { method: 'PUT', headers: Object.assign({ 'Content-Type': 'application/json' }, _authHeaders()), body: JSON.stringify({ body: v.body }) },
          });
        } else {
          r = await post('/api/format-sets', { id: v.fid, body: v.body }, _authHeaders());
        }
        if (r.ok) {
          const newId = id || v.fid;
          delete _fmtDetailCache[newId];
          delete _fmtPreviewCache[newId];
          await LibraryShell.reload(FMT);
          if (newId) LibraryShell.select(FMT, newId);
          return { ok: true, message: id ? 'Format set saved.' : 'Format set created.' };
        }
        if (r.status === 401) return { ok: false, detail: 'Sign in as admin to save format sets.' };
        return { ok: false, detail: (r.data && (r.data.detail || r.data.message)) || r.error || 'Save failed.' };
      },
    });
  }

  async function _fmtDelete(id) {
    // Surface workflow refs in the Confirm so a deletion's blast radius is clear.
    let refs = [];
    try {
      const rr = await LibraryShell.fetch(FMT, `/api/format-sets/${encodeURIComponent(id)}/refs`);
      if (rr.ok && rr.data) refs = rr.data.refs || [];
    } catch (_) {}
    const refNote = refs.length
      ? `\n\n⚠ ${refs.length} workflow${refs.length === 1 ? '' : 's'} reference this set: ${refs.join(', ')}. Their baked constraint lines are left intact.`
      : '';
    const ok = await Confirm.ask({
      title: 'Delete format set', body: `Delete format set "${id}"?${refNote}`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    const r = await Net.call(`/api/format-sets/${encodeURIComponent(id)}`, {
      retries: 0, init: { method: 'DELETE', headers: _authHeaders() },
    });
    if (r.ok) {
      delete _fmtDetailCache[id];
      await LibraryShell.reload(FMT);
      const msg = (r.data && r.data.reverted_to_oob) ? 'User copy removed — reverted to the shipped built-in.' : `Format set "${id}" deleted.`;
      Toast.success('Deleted', msg);
      return;
    }
    if (r.status === 401) return _lockRow('artifacts-pane-formats', 'Sign in to delete format sets.');
    if (r.status === 403) { Toast.warn('Protected', (r.data && r.data.detail) || 'Built-in format sets cannot be deleted.'); return; }
    Toast.danger('Delete failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Pane switching + init
  // ════════════════════════════════════════════════════════════════════════
  const _KIND_OF = { outputs: OUT, workspaces: WS, formats: FMT };
  const _HOST_OF = { outputs: 'artifacts-outputs-shell', workspaces: 'artifacts-workspaces-shell', formats: 'artifacts-formats-shell' };

  function _mountPane(pane) {
    const kind = _KIND_OF[pane];
    if (_mounted[kind]) { LibraryShell.reload(kind); return; }
    _mounted[kind] = true;
    LibraryShell.mount(kind, _HOST_OF[pane]);
  }

  function setPane(pane) {
    if (!_KIND_OF[pane]) pane = 'outputs';
    _pane = pane;
    ['outputs', 'workspaces', 'formats'].forEach(p => {
      const el = document.getElementById('artifacts-pane-' + p);
      if (el) el.hidden = p !== pane;
    });
    document.querySelectorAll('.artifacts-pane-btn').forEach(b => {
      const on = b.dataset.pane === pane;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    _mountPane(pane);
  }

  let _inited = false;
  function init() {
    if (!_inited) {
      _inited = true;
      LibraryShell.register(_outAdapter);
      LibraryShell.register(_wsAdapter);
      LibraryShell.register(_fmtAdapter);
    }
    setPane(_pane);
  }

  // ── Delegated actions (zero inline handlers, zero window globals) ─────────
  Actions.click({
    'artifacts.pane': el => setPane(el.dataset.pane),
    'artifacts.refresh': () => { const k = _KIND_OF[_pane]; if (k) LibraryShell.reload(k); },
    'artifacts.filter': el => {
      const dim = el.dataset.dim;
      if (dim === 'source' || dim === 'type') {
        _outFilter[dim] = el.dataset.val || '';
        LibraryShell.reload(OUT);
      }
    },
    'artifacts.download': el => _download(el.dataset.artId || el.dataset.id),
    'artifacts.promote': el => _promote(el.dataset.artId || el.dataset.id),
    'artifacts.open-run': el => _openRun(el.dataset.runId),
    // Workspaces
    'artifacts.ws-bind': () => _openBindWizard(),
    'artifacts.ws-schedule': el => {
      try { SchedulesView.openScheduleWizard({ workspace: el.dataset.wsName }); }
      catch (e) { Toast.danger('Schedule', e.message); }
    },
    'artifacts.ws-requeue': el => _wsIndexMutate(el.dataset.wsName, el.dataset.index || '', 'requeue'),
    'artifacts.ws-render': el => _wsIndexMutate(el.dataset.wsName, el.dataset.index || '', 'render'),
    'artifacts.ws-deregister': el => _wsDeregister(el.dataset.wsName || el.dataset.id),
    'artifacts.ws-file': el => _wsFileView(el.dataset.wsName, el.dataset.path),
    // Format sets
    'artifacts.fmt-new': () => _openFmtEditor(null),
    'artifacts.fmt-edit': el => _openFmtEditor(el.dataset.fmtId || el.dataset.id),
    'artifacts.fmt-delete': el => _fmtDelete(el.dataset.fmtId || el.dataset.id),
    'artifacts.fmt-preview': el => { LibraryShell.setSubnav(FMT, 'test'); },
  });

  return { init, setPane, pane: () => _pane };
})();
