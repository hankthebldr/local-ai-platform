// library/test-pane.js — TestPane: the layered test harness that fills the
// LibraryShell Test subnav slot (LB1-U2, spec A2).
//
// TestPane.register(kind, impl) for six kinds — prompt, model, skill,
// plugin-tool, mcp-tool, step. The `agent` adapter is DEFERRED to the
// Agents-migration follow-up (#1): no adapter ships without a reachable
// surface. Live mounts arrive per track: mcp-tool + plugin-tool here
// (LB1-U2), prompt in LB2, skill in LB3-U2, model in LB4-U2, step in LB6.
//
// Layered config model (the answer to "ALL layers of configuration"):
//   L0 Component config — the component's own record; baseline snapshot at
//      mount; edits are SESSION-LOCAL overrides (never persisted implicitly).
//   L1 Attached skills/tools — chips; attach/detach for step kind.
//   L2 Model params — model picker + temperature/max_tokens; warm/cold via
//      GET /api/inventory/memory + POST /api/inventory/warm (Warm renders
//      disabled-with-reason on no-op runners — vLLM pins weights at start).
//   L3 Input sample — schema-driven form (the ToolFormKit extracted from
//      plugins.js) or a plain message box for LLM kinds.
// Every layer shows a diff chip ("2 overrides") with per-field and per-layer
// reset. Run → normalized result strip {content|result, usage?,
// model_fallback?, latency_ms, status} + last-5 history with snapshot
// restore. Input samples persist in localStorage (server-side test-case
// store is follow-up #5).
//
// Per-layer auth degradation: layers marked 'admin' render a small lock note
// when signed out (renderLock-style, never a wall) — LLM layers stay usable.
// Every run POST is retries:0. Promote (test.promote) is Confirm-gated and
// shows the exact diff being written; model promote is disabled with a
// reason (no home for tuned params in v1 — follow-up #10).
//
// No inline on*= handlers, no window globals — all wiring rides the
// delegated Actions registry (test.* action ids at the bottom).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { AdminAuth } from '../admin/auth.js';

// ── ToolFormKit — schema form kit extracted from plugins.js ─────────────
// plugins.js re-exports these so its public surface (renderToolForm,
// _collectParams) and the plugin tester DOM ids (tool-param-*, tool-form-*,
// tool-result-*, tool-history-*) stay byte-compatible.
export const ToolFormKit = (function () {
  function renderToolForm(tool, opts) {
    const idPrefix = (opts && opts.idPrefix) || 'tool-param-';
    const params = tool.parameters || {};
    if (typeof params !== 'object' || Array.isArray(params) || !Object.keys(params).length) {
      return '<div style="color:var(--text-muted);font-size:0.7rem">No parameter schema declared.</div>';
    }
    return Object.entries(params).map(([name, spec]) => {
      const required = spec && spec.required === true;
      const type = (spec && spec.type) || 'string';
      const def = spec && spec.default;
      const id = `${idPrefix}${name}`;
      const label = `<label class="admin-modal-label">${esc(name)}${required ? ' *' : ''}
        <span style="color:var(--text-muted);font-size:0.62rem">(${esc(type)})</span></label>`;
      let input;
      if (type === 'boolean') {
        input = `<input type="checkbox" id="${id}" ${def === true ? 'checked' : ''}>`;
      } else if (type === 'integer' || type === 'number') {
        input = `<input type="number" id="${id}" value="${esc(def ?? '')}" ${type === 'integer' ? 'step="1"' : ''}>`;
      } else if (Array.isArray(spec.enum)) {
        input = `<select id="${id}">${spec.enum.map(o =>
          `<option value="${esc(o)}" ${o === def ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      } else if (type === 'array' || type === 'object') {
        input = `<textarea id="${id}" rows="3" placeholder="JSON or one item per line"></textarea>`;
      } else {
        input = `<input type="text" id="${id}" value="${esc(def ?? '')}">`;
      }
      return label + input;
    }).join('');
  }

  function collectParams(tool, opts) {
    const idPrefix = (opts && opts.idPrefix) || 'tool-param-';
    const out = {};
    const params = tool.parameters || {};
    for (const [name, spec] of Object.entries(params)) {
      const el = document.getElementById(idPrefix + name);
      if (!el) continue;
      const type = (spec && spec.type) || 'string';
      let v;
      if (type === 'boolean') v = el.checked;
      else if (type === 'integer') v = el.value === '' ? null : parseInt(el.value, 10);
      else if (type === 'number') v = el.value === '' ? null : parseFloat(el.value);
      else if (type === 'array' || type === 'object') {
        const raw = el.value.trim();
        if (!raw) { v = type === 'array' ? [] : {}; }
        else if (raw[0] === '[' || raw[0] === '{') {
          try { v = JSON.parse(raw); } catch (e) { throw new Error(`${name}: invalid JSON`); }
        } else {
          v = raw.split(/\n/).map(s => s.trim()).filter(Boolean);
        }
      } else {
        v = el.value;
      }
      if (spec && spec.required && (v === null || v === undefined || v === '')) {
        throw new Error(`${name} is required`);
      }
      if (v !== null && v !== undefined && v !== '') out[name] = v;
    }
    return out;
  }

  // Legacy plugin-tester history strip — markup identical to the pre-extract
  // plugins.js _renderHistory (the accordion tester keeps its exact look).
  function renderHistory(host, hist) {
    if (!host) return;
    if (!hist || !hist.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div style="font-size:0.62rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-top:8px">Last invocations</div>
      ${hist.slice().reverse().map(h => `
        <div style="display:flex;gap:10px;font-size:0.66rem;color:var(--text-dim);padding:2px 0">
          <span style="color:var(--text-muted);min-width:130px">${new Date(h.ts).toLocaleTimeString()}</span>
          <span style="color:${h.status >= 200 && h.status < 300 ? 'var(--accent)' : 'var(--danger,#e54b4b)'};min-width:40px">${h.status}</span>
          <span style="min-width:50px">${h.ms} ms</span>
          <span style="opacity:0.85">${esc(h.summary)}…</span>
        </div>
      `).join('')}
    `;
  }

  return { renderToolForm, collectParams, renderHistory };
})();

export const TestPane = (function () {
  const LAYER_ORDER = ['l0', 'l1', 'l2', 'l3'];
  const LAYER_TAGS = { l0: 'L0', l1: 'L1', l2: 'L2', l3: 'L3' };
  const HISTORY_MAX = 5;
  const SAMPLE_LS_PREFIX = 'enclave.testpane.sample.';

  const _impls = Object.create(null);
  const _panes = Object.create(null);   // paneKey -> state
  let _modelList = null;                // /api/models cache for the datalist

  function register(kind, impl) {
    _impls[kind] = impl;
    return impl;
  }
  function kinds() { return Object.keys(_impls); }

  // ── helpers ─────────────────────────────────────────────────────────
  function _headersAdmin() {
    return (AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }
  // retries:0 — EVERY test run / warm / promote POST; mutating or live calls
  // must never double-fire from the harness.
  function _post(url, body, headers) {
    return Net.call(url, {
      retries: 0,
      init: {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}),
        body: JSON.stringify(body || {}),
      },
    });
  }

  function _state(el) {
    const root = el.closest('.test-pane');
    return root ? _panes[root.dataset.testKey] : null;
  }
  function _eff(st, layer, key) {
    const ov = st.overrides[layer] || {};
    return (key in ov) ? ov[key] : (st.baseline[layer] || {})[key];
  }
  function _diffCount(st, layer) {
    return Object.keys(st.overrides[layer] || {}).length;
  }
  function _totalDiff(st) {
    return LAYER_ORDER.reduce((n, l) => n + _diffCount(st, l), 0);
  }
  function _lockedLayer(st, layer) {
    const tiers = st.impl.layerAuth || {};
    return tiers[layer] === 'admin' && AdminAuth && !AdminAuth.isSignedIn();
  }
  function _pickedTool(st) {
    const tools = st.impl.tools ? (st.impl.tools(st) || []) : [];
    return tools.find(t => t.id === st.toolId) || null;
  }
  function _sampleKey(kind, id) { return `${SAMPLE_LS_PREFIX}${kind}.${id}`; }
  function _loadSample(kind, id) {
    try {
      const raw = localStorage.getItem(_sampleKey(kind, id));
      if (raw) return JSON.parse(raw);
    } catch (_) {}
    return {};
  }
  function _saveSample(st, input) {
    // saved input samples: localStorage v1 (server-side store is follow-up #5).
    // Params/message only — NEVER secrets (secrets never enter L3 forms).
    try {
      localStorage.setItem(_sampleKey(st.kind, st.id), JSON.stringify({
        message: input.message || '', params: input.params || {}, toolId: st.toolId || null,
      }));
    } catch (_) {}
  }

  // MCPTool.input_schema is JSON Schema — convert to the ToolFormKit's
  // {name: {type, required, default, enum}} spec shape.
  function _specFromJsonSchema(js) {
    const props = (js && js.properties) || {};
    const req = new Set((js && js.required) || []);
    const out = {};
    Object.entries(props).forEach(([k, v]) => {
      out[k] = {
        type: (v && v.type) || 'string',
        required: req.has(k),
        default: v ? v.default : undefined,
        enum: v && Array.isArray(v.enum) ? v.enum : undefined,
      };
    });
    return out;
  }

  async function _ensureModelDatalist() {
    if (document.getElementById('test-pane-models') && _modelList) return;
    if (!_modelList) {
      try {
        const r = await Net.call('/api/models', { silent: true });
        _modelList = (r.ok && r.data && Array.isArray(r.data.data))
          ? r.data.data.map(m => m.id) : [];
      } catch (_) { _modelList = []; }
    }
    let dl = document.getElementById('test-pane-models');
    if (!dl) {
      dl = document.createElement('datalist');
      dl.id = 'test-pane-models';
      document.body.appendChild(dl);
    }
    dl.innerHTML = _modelList.map(m => `<option value="${esc(m)}"></option>`).join('');
  }

  // ── mount ───────────────────────────────────────────────────────────
  async function mount(kind, id, mountEl, ctx) {
    const impl = _impls[kind];
    if (!impl || !mountEl) return null;
    const key = `${kind}::${id}`;
    const st = {
      kind, id, key, ctx: ctx || {}, impl,
      root: null,
      baseline: { l0: {}, l2: {} },
      fields: { l0: [], l2: [] },
      overrides: { l0: {}, l1: {}, l2: {}, l3: {} },
      collapsed: {},
      attached: [],
      toolId: null,
      sample: _loadSample(kind, id),
      history: [],
      warm: null,
      result: null,
    };
    _panes[key] = st;
    mountEl.innerHTML = '<div class="model-empty">Loading test pane…</div>';
    try {
      if (impl.prepare) await impl.prepare(st);
    } catch (e) {
      mountEl.innerHTML = `<div class="admin-modal-error" style="margin:0">Test pane failed: ${esc(e.message)}</div>`;
      return st;
    }
    if (st.fields.l2.length) await _ensureModelDatalist();
    const tools = impl.tools ? (impl.tools(st) || []) : null;
    if (tools && tools.length && !st.toolId) {
      st.toolId = (st.sample.toolId && tools.some(t => t.id === st.sample.toolId))
        ? st.sample.toolId : tools[0].id;
    }
    st.root = document.createElement('div');
    st.root.className = 'test-pane';
    st.root.dataset.testKey = key;
    st.root.dataset.kind = kind;
    st.root.dataset.tid = id;
    mountEl.textContent = '';
    mountEl.appendChild(st.root);
    _renderPane(st);
    return st;
  }

  // ── render ──────────────────────────────────────────────────────────
  function _fieldInputHtml(st, layer, f) {
    const val = _eff(st, layer, f.key);
    const shown = val == null ? '' : String(val);
    if (f.masked) {
      // Masked config values render read-only and never round-trip — the
      // pane must never echo or resubmit a secret.
      return `<input type="text" value="${esc(f.maskedValue || shown || '(not set)')}" disabled
        title="masked — secrets never round-trip through the test pane">`;
    }
    const common = `data-action="test.field" data-layer="${layer}" data-key="${esc(f.key)}"`;
    if (f.type === 'textarea') {
      return `<textarea rows="${f.rows || 6}" spellcheck="false" ${common}>${esc(shown)}</textarea>`;
    }
    if (f.type === 'number') {
      return `<input type="number" ${f.step ? `step="${esc(String(f.step))}"` : ''} value="${esc(shown)}" ${common}>`;
    }
    if (f.datalist) {
      return `<input type="text" list="test-pane-models" value="${esc(shown)}" placeholder="${esc(f.placeholder || 'auto')}" ${common}>`;
    }
    return `<input type="text" value="${esc(shown)}" placeholder="${esc(f.placeholder || '')}" ${common}>`;
  }

  function _fieldHtml(st, layer, f) {
    const changed = (f.key in (st.overrides[layer] || {}));
    return `
      <div class="test-field ${changed ? 'changed' : ''}" data-field-wrap="${layer}:${esc(f.key)}">
        <label class="admin-modal-label">${esc(f.label || f.key)}${f.masked ? ' <span class="test-masked-tag">masked</span>' : ''}</label>
        <div class="test-field-row">
          ${_fieldInputHtml(st, layer, f)}
          <button type="button" class="test-field-reset" data-action="test.field.reset"
            data-layer="${layer}" data-key="${esc(f.key)}" title="reset to baseline"
            ${changed ? '' : 'hidden'}>↺</button>
        </div>
      </div>`;
  }

  function _lockNoteHtml(st) {
    const panel = st.impl.lockPanel || '';
    return `
      <div class="test-layer-lock">
        <span aria-hidden="true">🔒</span> Master key required for this layer.
        <button type="button" class="lock-btn" data-action="admin.sign-in" data-panel="${esc(panel)}">Sign in</button>
      </div>`;
  }

  function _layerBodyHtml(st, lid, def) {
    if (_lockedLayer(st, lid)) return _lockNoteHtml(st);
    if (lid === 'l0' || lid === 'l2') {
      const fields = def.fields || [];
      let extra = '';
      if (lid === 'l2' && def.warm) {
        const w = st.warm || def.warm;
        const noop = !!w.noop;
        const badge = w.running != null
          ? `<span class="test-warm-badge ${w.running ? 'warm' : 'cold'}">${w.running ? 'warm' : 'cold'}</span>` : '';
        extra = `
          <div class="test-warm-row">
            ${badge}
            <button type="button" class="action-btn" data-action="test.model.warm"
              ${noop ? 'disabled' : ''} ${w.reason ? `title="${esc(w.reason)}"` : ''}>Warm</button>
            ${noop ? `<span class="test-warm-reason">${esc(w.reason || 'load is a no-op on this runner')}</span>` : ''}
            ${w.loadMs != null ? `<span class="test-warm-reason">loaded in ${esc(String(w.loadMs))} ms</span>` : ''}
          </div>`;
      }
      if (!fields.length && !extra) return '<div class="model-empty">Nothing configurable at this layer.</div>';
      return fields.map(f => _fieldHtml(st, lid, f)).join('') + extra;
    }
    if (lid === 'l1') {
      const items = def.items || [];
      const chips = items.map(it => `
        <span class="test-attach-chip">${esc(it.label || it.ref)}
          ${def.attach ? `<button type="button" class="test-chip-x" data-action="test.skill.detach" data-ref="${esc(it.ref)}" title="detach">×</button>` : ''}
        </span>`).join('');
      const attachRow = def.attach ? `
        <div class="test-attach-row">
          <input type="text" class="test-attach-input" placeholder="plugin_id.skill_id">
          <button type="button" class="action-btn" data-action="test.skill.attach">Attach</button>
        </div>` : '';
      return `<div class="test-attach-chips">${chips || '<span class="model-empty" style="padding:0">None attached.</span>'}</div>${attachRow}`;
    }
    // l3 — input sample
    if (def.empty) return `<div class="model-empty">${esc(def.empty)}</div>`;
    if (def.schema) {
      // saved-sample prefill happens post-render in _prefillSchemaSample.
      return ToolFormKit.renderToolForm({ parameters: def.schema }, { idPrefix: `tp-${st.key}-param-` });
    }
    const msg = st.sample.message || '';
    return `<textarea class="test-msg-input" rows="4" spellcheck="false" data-action="test.msg"
      placeholder="${esc(def.placeholder || 'Type a sample message…')}">${esc(msg)}</textarea>`;
  }

  function _layerHtml(st, lid, def) {
    if (!def) return '';
    const n = _diffCount(st, lid);
    const collapsed = !!st.collapsed[lid];
    return `
      <section class="test-layer ${collapsed ? 'collapsed' : ''}" data-layer="${lid}">
        <div class="test-layer-head">
          <button type="button" class="test-layer-toggle" data-action="test.layer.toggle" data-layer="${lid}"
            aria-expanded="${!collapsed}">
            <span class="test-caret">${collapsed ? '▸' : '▾'}</span>
            <span class="test-layer-tag">${LAYER_TAGS[lid]}</span>
            <span class="test-layer-label">${esc(def.label || lid)}</span>
          </button>
          <span class="test-diff-chip" data-layer="${lid}" ${n ? '' : 'hidden'}>${n} override${n === 1 ? '' : 's'}</span>
          <button type="button" class="test-layer-reset" data-action="test.layer.reset" data-layer="${lid}"
            ${n ? '' : 'hidden'} title="reset every field in this layer">reset</button>
        </div>
        <div class="test-layer-body" ${collapsed ? 'hidden' : ''}>${_layerBodyHtml(st, lid, def)}</div>
      </section>`;
  }

  function _toolPickerHtml(st) {
    const tools = st.impl.tools ? (st.impl.tools(st) || []) : null;
    if (!tools) return '';
    if (!tools.length) return '<div class="model-empty">No tools available to test.</div>';
    return `
      <div class="test-tool-row">
        <label class="admin-modal-label" style="margin:0">Tool</label>
        <select class="test-tool-pick" data-action="test.tool.pick">
          ${tools.map(t => `<option value="${esc(t.id)}" ${t.id === st.toolId ? 'selected' : ''}>${esc(t.label || t.id)}</option>`).join('')}
        </select>
        ${(_pickedTool(st) && _pickedTool(st).desc) ? `<span class="test-tool-desc">${esc(_pickedTool(st).desc)}</span>` : ''}
      </div>`;
  }

  function _promoteBtnHtml(st) {
    const reason = st.impl.promoteDisabledReason;
    if (!st.impl.promote) {
      return `<button type="button" class="action-btn" data-action="test.promote" disabled
        title="${esc(reason || 'promote not available for this kind')}">Promote</button>`;
    }
    const n = _totalDiff(st);
    return `<button type="button" class="action-btn" data-action="test.promote"
      ${n ? '' : 'disabled'} title="${n ? 'write the session overrides back' : 'no overrides to promote'}">Promote</button>`;
  }

  function _renderPane(st) {
    const layers = st.impl.layers(st) || {};
    st._layers = layers;
    st.root.innerHTML = `
      ${_toolPickerHtml(st)}
      <div class="test-layers">
        ${LAYER_ORDER.map(l => _layerHtml(st, l, layers[l])).join('')}
      </div>
      <div class="test-run-row">
        <button type="button" class="action-btn accent" data-action="test.run">▶ Run</button>
        <span class="test-ovr-total" data-role="ovr-total" ${_totalDiff(st) ? '' : 'hidden'}>${_totalDiff(st)} override${_totalDiff(st) === 1 ? '' : 's'}</span>
        ${_promoteBtnHtml(st)}
      </div>
      <div class="test-result-host"></div>
      <div class="test-history-host"></div>`;
    _prefillSchemaSample(st);
    if (st.result) _renderResult(st);
    _renderPaneHistory(st);
  }

  function _prefillSchemaSample(st) {
    const def = (st._layers || {}).l3;
    if (!def || !def.schema || !st.sample.params) return;
    Object.entries(st.sample.params).forEach(([k, v]) => {
      const el = document.getElementById(`tp-${st.key}-param-${k}`);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else if (typeof v === 'object') el.value = JSON.stringify(v);
      else el.value = String(v);
    });
  }

  function _refreshDiffUI(st) {
    LAYER_ORDER.forEach(lid => {
      const chip = st.root.querySelector(`.test-diff-chip[data-layer="${lid}"]`);
      const reset = st.root.querySelector(`.test-layer-reset[data-layer="${lid}"]`);
      const n = _diffCount(st, lid);
      if (chip) { chip.hidden = !n; chip.textContent = `${n} override${n === 1 ? '' : 's'}`; }
      if (reset) reset.hidden = !n;
    });
    const total = _totalDiff(st);
    const t = st.root.querySelector('[data-role="ovr-total"]');
    if (t) { t.hidden = !total; t.textContent = `${total} override${total === 1 ? '' : 's'}`; }
    const promote = st.root.querySelector('[data-action="test.promote"]');
    if (promote && st.impl.promote) {
      promote.disabled = !total;
      promote.title = total ? 'write the session overrides back' : 'no overrides to promote';
    }
  }

  // ── input collection ───────────────────────────────────────────────
  function _collectInput(st) {
    const def = (st._layers || {}).l3 || {};
    if (def.schema) {
      const params = ToolFormKit.collectParams(
        { parameters: def.schema }, { idPrefix: `tp-${st.key}-param-` });
      return { params };
    }
    const ta = st.root.querySelector('.test-msg-input');
    return { message: ta ? ta.value : '' };
  }

  // ── result strip ────────────────────────────────────────────────────
  function _renderResult(st) {
    const host = st.root.querySelector('.test-result-host');
    if (!host) return;
    const n = st.result;
    if (!n) { host.innerHTML = ''; return; }
    const ok = n.status !== 'error';
    const bits = [
      `<span class="test-status ${ok ? 'ok' : 'err'}">${esc(String(n.status || (ok ? 'ok' : 'error')).toUpperCase())}</span>`,
      n.latency_ms != null ? `<span>${esc(String(n.latency_ms))} ms</span>` : '',
      n.model ? `<span class="test-strip-model">${esc(n.model)}</span>` : '',
      (n.usage && (n.usage.total_tokens != null))
        ? `<span>${esc(String(n.usage.total_tokens))} tok</span>` : '',
      n.overrides ? `<span class="test-ovr-chip">${n.overrides} override${n.overrides === 1 ? '' : 's'}</span>` : '',
    ].filter(Boolean).join('<span class="test-strip-sep">·</span>');
    const fallback = n.model_fallback
      ? `<div class="test-fallback">⚠ Pinned <strong>${esc(n.model_fallback.requested)}</strong> not installed — ran on <strong>${esc(n.model_fallback.resolved)}</strong>.</div>` : '';
    let body;
    if (st.impl.renderResult) {
      body = st.impl.renderResult(st, n);
    } else if (typeof n.content === 'string') {
      body = `<pre class="md-code test-result-body">${esc(n.content)}</pre>`;
    } else if (n.result !== undefined) {
      body = `<pre class="md-code test-result-body">${esc(JSON.stringify(n.result, null, 2))}</pre>`;
    } else if (n.error) {
      body = `<div class="admin-modal-error" style="margin:0">${esc(n.error)}</div>`;
    } else {
      body = '<div class="model-empty">(empty response)</div>';
    }
    const raw = (n.raw !== undefined && n.raw !== null)
      ? `<details class="test-raw"><summary>raw response</summary>
           <pre class="md-code">${esc(JSON.stringify(n.raw, null, 2))}</pre></details>` : '';
    host.innerHTML = `
      <div class="test-result-strip">${bits}</div>
      ${fallback}
      ${n.error && ok ? `<div class="admin-modal-error" style="margin:6px 0 0">${esc(n.error)}</div>` : ''}
      ${body}
      ${raw}`;
  }

  // ── history — last 5 with snapshot restore ─────────────────────────
  function _snapshot(st, input) {
    return JSON.parse(JSON.stringify({
      overrides: st.overrides,
      attached: st.attached,
      toolId: st.toolId,
      input,
    }));
  }

  function _pushHistory(st, input, norm) {
    const summary = typeof norm.content === 'string'
      ? norm.content.slice(0, 80)
      : JSON.stringify(norm.result !== undefined ? norm.result : (norm.error || '')).slice(0, 80);
    st.history.push({
      ts: Date.now(),
      status: norm.status || 'ok',
      ms: norm.latency_ms,
      summary,
      snapshot: _snapshot(st, input),
    });
    while (st.history.length > HISTORY_MAX) st.history.shift();
    _renderPaneHistory(st);
  }

  function _renderPaneHistory(st) {
    const host = st.root.querySelector('.test-history-host');
    if (!host) return;
    if (!st.history.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div class="test-history-label">Last runs</div>
      ${st.history.slice().reverse().map((h, ri) => {
        const idx = st.history.length - 1 - ri;
        return `
        <div class="test-history-row">
          <span class="test-hist-ts">${new Date(h.ts).toLocaleTimeString()}</span>
          <span class="test-status ${h.status === 'error' ? 'err' : 'ok'}">${esc(String(h.status).toUpperCase())}</span>
          <span class="test-hist-ms">${h.ms != null ? `${h.ms} ms` : '—'}</span>
          <span class="test-hist-sum">${esc(h.summary)}</span>
          <button type="button" class="action-btn xs" data-action="test.history.restore" data-hidx="${idx}"
            title="restore this run's overrides + input">restore</button>
        </div>`;
      }).join('')}`;
  }

  function _restoreHistory(st, idx) {
    const h = st.history[idx];
    if (!h) return;
    const snap = JSON.parse(JSON.stringify(h.snapshot));
    st.overrides = Object.assign({ l0: {}, l1: {}, l2: {}, l3: {} }, snap.overrides);
    st.attached = snap.attached || [];
    st.toolId = snap.toolId || st.toolId;
    if (snap.input) {
      if (snap.input.message !== undefined) st.sample.message = snap.input.message;
      if (snap.input.params !== undefined) st.sample.params = snap.input.params;
    }
    _renderPane(st);
    if (window.Toast) Toast.info('Snapshot restored', 'Overrides and input sample reapplied.');
  }

  // ── run ─────────────────────────────────────────────────────────────
  async function _run(st) {
    const btn = st.root.querySelector('[data-action="test.run"]');
    const host = st.root.querySelector('.test-result-host');
    let input;
    try { input = _collectInput(st); } catch (e) {
      host.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
    const t0 = performance.now();
    const overridesAtRun = _totalDiff(st);
    try {
      const norm = await st.impl.run(st, input);
      if (norm.latency_ms == null) norm.latency_ms = Math.round(performance.now() - t0);
      norm.overrides = overridesAtRun;
      st.result = norm;
      _renderResult(st);
      _pushHistory(st, input, norm);
      _saveSample(st, input);
    } catch (e) {
      host.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '▶ Run'; }
    }
  }

  // ── warm ────────────────────────────────────────────────────────────
  async function _warm(st, el) {
    const model = String(_eff(st, 'l2', 'model') || st.id || '');
    if (!model) { Toast.info('No model', 'Pick a model first.'); return; }
    el.disabled = true;
    try {
      const r = await _post('/api/inventory/warm', { model }, _headersAdmin());
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) throw new Error((d && d.detail) || r.error || `HTTP ${r.status}`);
      st.warm = {
        running: true,
        noop: !!d.noop,
        reason: d.noop ? (d.reason || 'load is a no-op on this runner (weights pinned at server start)') : d.reason,
        loadMs: d.load_duration_ms,
      };
      if (d.noop) Toast.info('Warm is a no-op', st.warm.reason);
      else Toast.success('Model warmed', `${d.runner} · ${d.load_duration_ms} ms`);
    } catch (e) {
      Toast.danger('Warm failed', e.message);
      el.disabled = false;
      return;
    }
    _renderPane(st);
  }

  // ── promote — Confirm-gated write-back showing the diff ────────────
  async function _promote(st) {
    if (!st.impl.promote) return;
    let plan;
    try { plan = st.impl.promote(st); } catch (e) { Toast.danger('Promote failed', e.message); return; }
    if (!plan || !plan.diff || !plan.diff.length) {
      Toast.info('Nothing to promote', 'No session overrides to write back.');
      return;
    }
    const diffLines = plan.diff.map(d =>
      `${d.key} → ${typeof d.value === 'string' && d.value.length > 60 ? d.value.slice(0, 60) + '…' : JSON.stringify(d.value)}`
    ).join('\n');
    const ok = await Confirm.ask({
      title: 'Promote overrides',
      body: `${plan.label || 'Write the session overrides back'}:\n\n${diffLines}`,
      okLabel: 'Promote',
    });
    if (!ok) return;
    try {
      const res = await plan.apply();
      Toast.success('Promoted', (res && res.message) || 'Overrides written back.');
      _renderPane(st);
    } catch (e) {
      Toast.danger('Promote failed', e.message);
    }
  }

  // ── delegated actions (zero inline handlers) ────────────────────────
  Actions.input({
    'test.field': el => {
      const st = _state(el);
      if (!st) return;
      const layer = el.dataset.layer;
      const key = el.dataset.key;
      const meta = (st.fields[layer] || []).find(f => f.key === key) || {};
      let v = el.value;
      if (meta.type === 'number') v = el.value === '' ? null : Number(el.value);
      const base = (st.baseline[layer] || {})[key];
      if (v === base || (v == null && base == null) || String(v) === String(base)) {
        delete st.overrides[layer][key];
      } else {
        st.overrides[layer][key] = v;
      }
      const wrap = st.root.querySelector(`[data-field-wrap="${layer}:${key}"]`);
      if (wrap) {
        const changed = key in st.overrides[layer];
        wrap.classList.toggle('changed', changed);
        const rb = wrap.querySelector('.test-field-reset');
        if (rb) rb.hidden = !changed;
      }
      _refreshDiffUI(st);
    },
    // keep the typed message sticky across mid-session re-renders
    'test.msg': el => { const st = _state(el); if (st) st.sample.message = el.value; },
  });
  Actions.change({
    'test.tool.pick': el => {
      const st = _state(el);
      if (!st) return;
      st.toolId = el.value;
      _renderPane(st);
    },
  });
  Actions.click({
    'test.run': el => { const st = _state(el); if (st) _run(st); },
    'test.layer.toggle': el => {
      const st = _state(el);
      if (!st) return;
      const lid = el.dataset.layer;
      st.collapsed[lid] = !st.collapsed[lid];
      const sec = st.root.querySelector(`.test-layer[data-layer="${lid}"]`);
      if (sec) {
        sec.classList.toggle('collapsed', st.collapsed[lid]);
        const body = sec.querySelector('.test-layer-body');
        if (body) body.hidden = st.collapsed[lid];
        el.setAttribute('aria-expanded', String(!st.collapsed[lid]));
        const caret = el.querySelector('.test-caret');
        if (caret) caret.textContent = st.collapsed[lid] ? '▸' : '▾';
      }
    },
    'test.field.reset': el => {
      const st = _state(el);
      if (!st) return;
      delete st.overrides[el.dataset.layer][el.dataset.key];
      _renderPane(st);
    },
    'test.layer.reset': el => {
      const st = _state(el);
      if (!st) return;
      st.overrides[el.dataset.layer] = {};
      _renderPane(st);
    },
    'test.skill.attach': el => {
      const st = _state(el);
      if (!st) return;
      const inp = st.root.querySelector('.test-attach-input');
      const ref = inp ? inp.value.trim() : '';
      if (!ref) return;
      if (st.attached.indexOf(ref) === -1) st.attached.push(ref);
      _renderPane(st);
    },
    'test.skill.detach': el => {
      const st = _state(el);
      if (!st) return;
      st.attached = st.attached.filter(r => r !== el.dataset.ref);
      _renderPane(st);
    },
    'test.model.warm': el => { const st = _state(el); if (st && !el.disabled) _warm(st, el); },
    'test.history.restore': el => {
      const st = _state(el);
      if (st) _restoreHistory(st, Number(el.dataset.hidx));
    },
    'test.promote': el => { const st = _state(el); if (st && !el.disabled) _promote(st); },
  });

  // ── kind adapters — six kinds, agent DEFERRED (follow-up #1) ────────

  const _modelParamFields = () => ([
    { key: 'model', label: 'model', datalist: true, placeholder: 'auto (role-resolved)' },
    { key: 'temperature', label: 'temperature', type: 'number', step: 0.1 },
    { key: 'max_tokens', label: 'max_tokens', type: 'number', step: 1 },
  ]);

  // plugin-tool — the worked example (Plugins > websearch). L0 = the saved
  // tool-settings store (search settings; masked keys read-only), L1 = the
  // plugin's skills, L2 hidden (direct invoke), L3 = schema form. Run POSTs
  // the LB1-U1 test route with {params, config_overrides}; overrides never
  // persist implicitly. Promote merges L0 overrides through the now
  // master-key-gated POST /api/inventory/settings/search.
  register('plugin-tool', {
    layerAuth: { l0: 'admin', l3: 'admin' },
    lockPanel: 'admin-plugins',
    tools(st) {
      const p = st.ctx.plugin || {};
      return (p.tools || []).map(t => ({
        id: t.id, label: t.id, desc: t.description || '', schema: t.parameters || {},
      }));
    },
    async prepare(st) {
      st.fields.l0 = [];
      const r = await Net.call('/api/inventory/settings/search', { silent: true });
      const cfg = (r.ok && r.data && typeof r.data === 'object') ? r.data : {};
      ['searxng_url', 'default_backend', 'search_timeout', 'max_results'].forEach(k => {
        if (k in cfg) {
          st.baseline.l0[k] = cfg[k];
          st.fields.l0.push({ key: k, label: k, type: typeof cfg[k] === 'number' ? 'number' : 'text' });
        }
      });
      if ('brave_api_key_masked' in cfg) {
        st.fields.l0.push({
          key: 'brave_api_key', label: 'brave_api_key', masked: true,
          maskedValue: cfg.brave_api_key_masked || '(not set)',
        });
      }
    },
    layers(st) {
      const p = st.ctx.plugin || {};
      const tool = _pickedTool(st);
      return {
        l0: { label: 'Component config — saved tool settings', fields: st.fields.l0 },
        l1: { label: 'Attached skills', items: (p.skills || []).map(s => ({ ref: s.id, label: s.id })) },
        l2: null,   // direct invoke — no model layer
        l3: tool
          ? { label: 'Input sample', schema: tool.schema }
          : { label: 'Input sample', empty: 'Pick a tool above.' },
      };
    },
    async run(st, input) {
      const tool = _pickedTool(st);
      if (!tool) throw new Error('Pick a tool first.');
      const r = await _post(
        `/api/plugins/${encodeURIComponent(st.id)}/tools/${encodeURIComponent(tool.id)}/test`,
        { params: input.params || {}, config_overrides: { ...st.overrides.l0 } },
        _headersAdmin());
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) {
        return { status: 'error', error: (d && d.detail) || r.error || `HTTP ${r.status}`, raw: d };
      }
      return { status: d.status || 'ok', latency_ms: d.latency_ms, result: d.result, error: d.error, raw: d };
    },
    promote(st) {
      const ov = { ...st.overrides.l0 };
      delete ov.brave_api_key;   // masked — the pane never writes secrets back
      return {
        label: 'Merge these overrides into the saved search settings',
        diff: Object.entries(ov).map(([key, value]) => ({ key, value })),
        apply: async () => {
          const r = await _post('/api/inventory/settings/search', ov, _headersAdmin());
          if (!r.ok) throw new Error(r.error || `HTTP ${r.status}`);
          Object.assign(st.baseline.l0, ov);
          st.overrides.l0 = {};
          return { ok: true, message: 'Search settings updated.' };
        },
      };
    },
  });

  // mcp-tool — stateless invokes over the existing POST
  // /api/mcp/servers/{id}/invoke (the warm-session pool is CUT per YAGNI —
  // follow-up #5 gated on measured latency pain). L0 = server config knobs
  // (timeout), L3 = MCPTool.input_schema (JSON Schema) rendered by the kit.
  register('mcp-tool', {
    layerAuth: {},
    tools(st) {
      const s = st.ctx.server || {};
      return (s.tools || []).map(t => ({
        id: t.name, label: t.name, desc: t.description || '',
        schema: _specFromJsonSchema(t.input_schema),
      }));
    },
    async prepare(st) {
      const s = st.ctx.server || {};
      st.baseline.l0 = { timeout_seconds: s.timeout_seconds || 30 };
      st.fields.l0 = [{ key: 'timeout_seconds', label: 'timeout_seconds', type: 'number' }];
    },
    layers(st) {
      const tool = _pickedTool(st);
      return {
        l0: { label: 'Server config', fields: st.fields.l0 },
        l1: null,
        l2: null,
        l3: tool
          ? { label: 'Tool arguments', schema: tool.schema }
          : { label: 'Tool arguments', empty: 'No tools cached — run "Discover tools" first.' },
      };
    },
    async run(st, input) {
      const tool = _pickedTool(st);
      if (!tool) throw new Error('No tools cached — run "Discover tools" first.');
      const t0 = performance.now();
      const r = await _post(
        `/api/mcp/servers/${encodeURIComponent(st.id)}/invoke`,
        { tool: tool.id, arguments: input.params || {} });
      const ms = Math.round(performance.now() - t0);
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) return { status: 'error', latency_ms: ms, error: (d && d.detail) || r.error || `HTTP ${r.status}`, raw: d };
      return { status: 'ok', latency_ms: ms, result: d, raw: d };
    },
    promote(st) {
      const ov = { ...st.overrides.l0 };
      return {
        label: `PATCH MCP server '${st.id}'`,
        diff: Object.entries(ov).map(([key, value]) => ({ key, value })),
        apply: async () => {
          const r = await Net.call(`/api/mcp/servers/${encodeURIComponent(st.id)}`, {
            retries: 0,
            init: {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json', ..._headersAdmin() },
              body: JSON.stringify(ov),
            },
          });
          if (!r.ok) throw new Error(r.error || `HTTP ${r.status}`);
          Object.assign(st.baseline.l0, ov);
          st.overrides.l0 = {};
          return { ok: true, message: 'Server config updated.' };
        },
      };
    },
  });

  // prompt — id is '<kind>/<pid>'. L0 = the prompt body (session override),
  // L2 = model params, L3 = message. Run renders via POST
  // /api/prompts/{kind}/{pid}/render then executes through
  // POST /api/workflows/test-step — labeled "model+prompt only": tools,
  // skills and parsers are NOT exercised. Promote PATCHes the body
  // (copy-on-write to the user layer per the persistence seam).
  register('prompt', {
    layerAuth: {},
    async prepare(st) {
      const idx = st.id.indexOf('/');
      st.pkind = idx > 0 ? st.id.slice(0, idx) : 'role';
      st.pid = idx > 0 ? st.id.slice(idx + 1) : st.id;
      const r = await Net.call(
        `/api/prompts/${encodeURIComponent(st.pkind)}/${encodeURIComponent(st.pid)}`);
      if (!r.ok) throw new Error(`Prompt load failed (${r.status})`);
      st.baseline.l0 = { body: (r.data && r.data.body) || '' };
      st.fields.l0 = [{ key: 'body', label: 'prompt body', type: 'textarea', rows: 8 }];
      st.baseline.l2 = { model: '', temperature: 0.7, max_tokens: 1024 };
      st.fields.l2 = _modelParamFields();
    },
    layers(st) {
      return {
        l0: { label: 'Component config — prompt body', fields: st.fields.l0 },
        l1: null,
        l2: { label: 'Model params', fields: st.fields.l2 },
        l3: { label: 'Input sample', message: true, placeholder: 'Task / user message for the rendered prompt…' },
      };
    },
    async run(st, input) {
      // Render through the real renderer unless the body is overridden —
      // an overridden body runs as the system prompt directly (honest label:
      // the session override can't flow through the server-side renderer).
      let system, user = input.message || '';
      if ('body' in st.overrides.l0) {
        system = st.overrides.l0.body;
      } else {
        const rr = await _post(
          `/api/prompts/${encodeURIComponent(st.pkind)}/${encodeURIComponent(st.pid)}/render`,
          { task: input.message || '' }, _headersAdmin());
        if (!rr.ok) return { status: 'error', error: rr.error || `HTTP ${rr.status}`, raw: rr.data };
        system = (rr.data && rr.data.system) || '';
        user = (rr.data && rr.data.user) || user;
      }
      const r = await _post('/api/workflows/test-step', {
        step: {
          id: 'prompt-test', name: st.pid,
          model: _eff(st, 'l2', 'model') || null, role: null,
          system_prompt: system,
        },
        user_message: user || '(empty)',
        temperature: Number(_eff(st, 'l2', 'temperature')),
        max_tokens: Number(_eff(st, 'l2', 'max_tokens')),
      });
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) return { status: 'error', error: (d && d.detail) || r.error || `HTTP ${r.status}`, raw: d };
      return {
        status: 'ok', content: d.content, usage: d.usage, model: d.model,
        model_fallback: d.model_fallback, raw: d,
      };
    },
    promote(st) {
      if (!('body' in st.overrides.l0)) return { label: '', diff: [], apply: async () => ({ ok: true }) };
      const body = st.overrides.l0.body;
      return {
        label: `PATCH ${st.pkind} '${st.pid}' body (copy-on-write to the user layer)`,
        diff: [{ key: 'body', value: body }],
        apply: async () => {
          const r = await Net.call(
            `/api/prompts/${encodeURIComponent(st.pkind)}/${encodeURIComponent(st.pid)}`, {
              retries: 0,
              init: {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', ..._headersAdmin() },
                body: JSON.stringify({ body }),
              },
            });
          if (!r.ok) throw new Error(r.error || `HTTP ${r.status}`);
          st.baseline.l0.body = body;
          st.overrides.l0 = {};
          return { ok: true, message: 'Prompt saved.' };
        },
      };
    },
  });

  // model — L2 params + Warm (POST /api/inventory/warm via the runner-service
  // explicit-load path; no-op runners get a disabled button + reason chip,
  // never a dead control), L3 message, run through /v1/chat/completions.
  // Promote is DISABLED in v1: tuned params have no persistent home yet
  // (named follow-up #10).
  register('model', {
    layerAuth: {},
    promoteDisabledReason: 'No home for tuned model params in v1 (follow-up #10)',
    async prepare(st) {
      st.baseline.l2 = { temperature: 0.7, max_tokens: 512 };
      st.fields.l2 = _modelParamFields().filter(f => f.key !== 'model');
      const backend = st.ctx.backend || '';
      st.warm = backend === 'vllm'
        ? { noop: true, reason: 'vLLM pins weights at server start — warm is a no-op' }
        : { noop: false };
      try {
        const r = await Net.call('/api/inventory/memory', { silent: true });
        const running = (r.ok && r.data && r.data.running_models) || [];
        st.warm.running = running.some(m => m.name === st.id);
      } catch (_) {}
    },
    layers(st) {
      return {
        l0: null,
        l1: null,
        l2: { label: `Model params — ${st.id}`, fields: st.fields.l2, warm: st.warm },
        l3: { label: 'Input sample', message: true, placeholder: 'Prompt the model directly…' },
      };
    },
    async run(st, input) {
      const r = await _post('/v1/chat/completions', {
        model: st.id,
        messages: [{ role: 'user', content: input.message || '(empty)' }],
        temperature: Number(_eff(st, 'l2', 'temperature')),
        max_tokens: Number(_eff(st, 'l2', 'max_tokens')),
        stream: false,
      });
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) {
        const msg = (d.error && d.error.message) || d.detail || r.error || `HTTP ${r.status}`;
        return { status: 'error', error: msg, raw: d };
      }
      const content = d.choices && d.choices[0] && d.choices[0].message
        ? d.choices[0].message.content : '';
      return { status: 'ok', content, usage: d.usage, model: d.model, raw: d };
    },
  });

  // skill — trigger dry-run over the LB1-U1 POST /api/skills/test route:
  // matched skills + keywords + the EXACT text the injector would add.
  // Nothing runs a model; nothing is injected anywhere.
  register('skill', {
    layerAuth: { l3: 'admin' },
    lockPanel: 'admin-skills',
    promoteDisabledReason: 'Skill promote lands with the Skills library rebuild (LB3)',
    layers() {
      return {
        l0: null, l1: null, l2: null,
        l3: { label: 'Input sample — trigger dry-run message', message: true,
              placeholder: 'Message to match against skill trigger keywords…' },
      };
    },
    async run(st, input) {
      const body = { message: input.message || '' };
      if (st.ctx.pluginId && st.ctx.skillId) {
        body.plugin_id = st.ctx.pluginId;
        body.skill_id = st.ctx.skillId;
      }
      const r = await _post('/api/skills/test', body, _headersAdmin());
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) return { status: 'error', error: (d && d.detail) || r.error || `HTTP ${r.status}`, raw: d };
      return { status: 'ok', result: d, raw: d };
    },
    renderResult(st, n) {
      const d = n.result || {};
      const matched = d.matched || [];
      if (!matched.length) return '<div class="model-empty">No skills matched this message.</div>';
      return matched.map(m => `
        <div class="test-skill-match">
          <div class="test-skill-match-head">
            <code>${esc(m.plugin_id)}.${esc(m.skill_id)}</code>
            <span class="lib-chip">${esc(m.trigger)}</span>
            ${m.trigger_match ? `<span class="lib-chip">keyword: ${esc(m.trigger_match)}</span>` : ''}
            <span class="lib-chip">→ ${esc(m.injected_into)}</span>
          </div>
          ${(m.keywords || []).length ? `<div class="test-skill-kw">triggers: ${m.keywords.map(esc).join(', ')}</div>` : ''}
          <pre class="md-code test-result-body">${esc(m.injected_text || '(empty body)')}</pre>
        </div>`).join('');
    },
  });

  // step — the composer node harness (live mount rides LB6's Task track).
  // L0 = system prompt, L1 = attached skills (router-side injection pinned
  // to skill_injector parity), L2 = model params, L3 = message. Runs through
  // POST /api/workflows/test-step; promote writes back onto the canvas node
  // via dfUpdateNodeData (no server write — the canvas is the draft).
  register('step', {
    layerAuth: { l1: 'admin' },
    async prepare(st) {
      const d = st.ctx.stepData || {};
      st.baseline.l0 = { system_prompt: d.system_prompt || '' };
      st.fields.l0 = [{ key: 'system_prompt', label: 'system prompt', type: 'textarea', rows: 6 }];
      st.baseline.l2 = {
        model: d.model || '',
        temperature: d.temperature != null ? Number(d.temperature) : 0.7,
        max_tokens: d.max_tokens != null ? Number(d.max_tokens) : 2048,
      };
      st.fields.l2 = _modelParamFields();
      st.attached = Array.isArray(d.skills) ? d.skills.slice() : [];
    },
    layers(st) {
      return {
        l0: { label: 'Component config — step', fields: st.fields.l0 },
        l1: { label: 'Attached skills', attach: true,
              items: st.attached.map(rf => ({ ref: rf, label: rf })) },
        l2: { label: 'Model params', fields: st.fields.l2 },
        l3: { label: 'Input sample', message: true, placeholder: 'User message for this step…' },
      };
    },
    async run(st, input) {
      const d = st.ctx.stepData || {};
      const body = {
        step: {
          id: d.id || 'step', name: d.name || d.id || 'step',
          model: _eff(st, 'l2', 'model') || null,
          role: d.role || null,
          system_prompt: _eff(st, 'l0', 'system_prompt') || '',
        },
        user_message: input.message || '(empty)',
        temperature: Number(_eff(st, 'l2', 'temperature')),
        max_tokens: Number(_eff(st, 'l2', 'max_tokens')),
      };
      if (st.attached.length) body.skills = st.attached.slice();
      const r = await _post('/api/workflows/test-step', body);
      const dd = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) return { status: 'error', error: (dd && dd.detail) || r.error || `HTTP ${r.status}`, raw: dd };
      return {
        status: 'ok', content: dd.content, usage: dd.usage, model: dd.model,
        model_fallback: dd.model_fallback, raw: dd,
      };
    },
    promote(st) {
      const writes = [];
      if ('system_prompt' in st.overrides.l0) writes.push({ key: 'system_prompt', value: st.overrides.l0.system_prompt });
      ['model', 'temperature', 'max_tokens'].forEach(k => {
        if (k in st.overrides.l2) writes.push({ key: k, value: st.overrides.l2[k] });
      });
      return {
        label: `Write back onto canvas node '${(st.ctx.stepData || {}).id || st.id}'`,
        diff: writes,
        apply: async () => {
          if (typeof window.dfUpdateNodeData !== 'function') {
            throw new Error('Composer canvas not active — nothing to write back to.');
          }
          writes.forEach(w => {
            window.dfUpdateNodeData(st.ctx.nodeId, w.key, w.value);
            st.baseline[w.key === 'system_prompt' ? 'l0' : 'l2'][w.key] = w.value;
          });
          st.overrides.l0 = {};
          st.overrides.l2 = {};
          return { ok: true, message: 'Node updated on the canvas.' };
        },
      };
    },
  });

  return { register, kinds, mount };
})();
