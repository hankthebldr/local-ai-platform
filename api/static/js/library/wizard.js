// library/wizard.js — LibraryWizard: uniform 4-step install/config modal (LB0-U1).
//
// Source → Configure → Secrets → Confirm/Result, generalizing the
// InstallWizard/builders.js flows onto the `.admin-modal` grammar. Empty
// steps are skipped. Submission is ALWAYS retries:0 (mutating POSTs must
// never double-fire). Secrets discipline mirrors cloud_providers masking:
// password inputs, never prefilled, never echoed back into summaries or
// results, never logged.
//
// Flow contract (consumers: prompt digest install LB2-U2, skills
// install/import LB3-U2, plugin forge + seed LB5-U3, task create LB6, MCP
// marketplace env keys LB1-U2 — model pull is the one named A5 carve-out):
//   LibraryWizard.open({
//     title: 'Install prompt',
//     steps: {
//       source?:    (bodyEl, state) => void,           // render fn
//       configure?: (bodyEl, state) => void,
//       secrets?:   { fields: [{key, label, hint?, placeholder?}] } | renderFn,
//       confirm?:   (bodyEl, state) => void,           // default: masked summary
//     },
//     validate?: (stepId, state) => true|false|string, // string = error message
//     onSubmit:  (state, {post}) => Promise<{ok, message?, detail?}>,
//     submitLabel?: 'Install',
//     state?: {},                                      // seed values
//   })
// Inputs inside step bodies marked with data-wiz-key are collected into
// state.values (or state.secrets for type=password) on every step advance.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Actions } from '../shell/actions.js';

export const LibraryWizard = (function () {
  const STEP_ORDER = ['source', 'configure', 'secrets', 'confirm'];
  const STEP_LABELS = { source: 'Source', configure: 'Configure', secrets: 'Secrets', confirm: 'Confirm' };

  let _flow = null;
  let _steps = [];
  let _idx = 0;
  let _state = null;
  let _busy = false;
  let _done = false;

  function isOpen() { return !!_flow; }

  function _modal() {
    let m = document.getElementById('lib-wizard-modal');
    if (!m) {
      m = document.createElement('div');
      m.id = 'lib-wizard-modal';
      m.className = 'admin-modal';
      m.hidden = true;
      m.setAttribute('role', 'dialog');
      m.setAttribute('aria-modal', 'true');
      m.setAttribute('aria-labelledby', 'lib-wizard-title');
      m.innerHTML = `
        <div class="admin-modal-card" style="width:min(620px,94vw)">
          <h3 id="lib-wizard-title">Wizard</h3>
          <div class="lib-wiz-steps" id="lib-wizard-steps"></div>
          <div class="lib-wiz-body" id="lib-wizard-body"></div>
          <div id="lib-wizard-error" class="admin-modal-error" hidden></div>
          <div class="admin-modal-actions" id="lib-wizard-actions"></div>
        </div>`;
      document.body.appendChild(m);
    }
    return m;
  }

  // retries:0 helper for consumers — the ONLY sanctioned submit transport.
  function post(url, body, headers) {
    return Net.call(url, {
      retries: 0,
      init: {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}),
        body: JSON.stringify(body || {}),
      },
    });
  }

  function open(flow) {
    _flow = flow || {};
    _state = Object.assign({ values: {}, secrets: {} }, _flow.state || {});
    _state.values = _state.values || {};
    _state.secrets = _state.secrets || {};
    // Empty steps are skipped; Confirm/Result always renders (it hosts the result).
    _steps = STEP_ORDER.filter(id => id === 'confirm' || (_flow.steps && _flow.steps[id]));
    _idx = 0;
    _busy = false;
    _done = false;
    const m = _modal();
    m.querySelector('#lib-wizard-title').textContent = _flow.title || 'Wizard';
    m.hidden = false;
    _render();
  }

  function close() {
    const m = document.getElementById('lib-wizard-modal');
    if (m) m.hidden = true;
    _flow = null;
    _state = null;
    _steps = [];
    _busy = false;
    _done = false;
  }

  function _error(msg) {
    const e = document.getElementById('lib-wizard-error');
    if (!e) return;
    e.textContent = msg || '';
    e.hidden = !msg;
  }

  // Collect data-wiz-key inputs. Passwords land in state.secrets and are
  // NEVER re-rendered into inputs or summaries.
  function _collect() {
    const body = document.getElementById('lib-wizard-body');
    if (!body || !_state) return;
    body.querySelectorAll('[data-wiz-key]').forEach(inp => {
      const k = inp.dataset.wizKey;
      const v = (inp.type === 'checkbox') ? inp.checked : inp.value;
      if (inp.type === 'password') {
        if (typeof v === 'string' && v.trim()) _state.secrets[k] = v.trim();
      } else {
        _state.values[k] = v;
      }
    });
  }

  function _defaultConfirm(bodyEl) {
    const rows = Object.entries(_state.values).map(([k, v]) =>
      `<div style="color:var(--text-muted)">${esc(k)}</div><div>${esc(String(v))}</div>`).join('');
    const secrets = Object.keys(_state.secrets).map(k =>
      `<div style="color:var(--text-muted)">${esc(k)}</div><div>••••••••</div>`).join('');
    bodyEl.innerHTML = `
      <div class="admin-modal-sub">Review, then submit.</div>
      <div style="display:grid;grid-template-columns:140px 1fr;gap:6px;font-size:0.72rem;line-height:1.6;margin-top:8px">
        ${rows}${secrets}
      </div>
      <div id="lib-wizard-result" style="margin-top:10px"></div>`;
  }

  function _renderSecrets(bodyEl, def) {
    const fields = (def && def.fields) || [];
    bodyEl.innerHTML = fields.map(f => `
      <label class="admin-modal-label" for="lib-wiz-secret-${esc(f.key)}">${esc(f.label || f.key)}</label>
      <input id="lib-wiz-secret-${esc(f.key)}" type="password" data-wiz-key="${esc(f.key)}"
        placeholder="${esc(f.placeholder || '')}" autocomplete="new-password">
      ${f.hint ? `<div class="admin-modal-sub" style="margin-top:2px">${esc(f.hint)}</div>` : ''}
    `).join('') || '<div class="admin-modal-sub">No secrets required.</div>';
    // never prefill: saved values are not echoed — inputs always start empty.
  }

  function _render() {
    const m = _modal();
    const stepId = _steps[_idx];
    _error('');
    // stepper rail
    m.querySelector('#lib-wizard-steps').innerHTML = _steps.map((s, i) => `
      <span class="lib-wiz-step ${i < _idx ? 'done' : ''} ${i === _idx ? 'on' : ''}">
        <span class="n">${i + 1}</span>${esc(STEP_LABELS[s])}</span>
      ${i < _steps.length - 1 ? '<span class="lib-wiz-conn"></span>' : ''}`).join('');
    // body
    const body = m.querySelector('#lib-wizard-body');
    body.innerHTML = '';
    const def = _flow.steps && _flow.steps[stepId];
    if (stepId === 'secrets' && def && typeof def !== 'function') _renderSecrets(body, def);
    else if (typeof def === 'function') def(body, _state);
    else if (stepId === 'confirm') _defaultConfirm(body);
    // actions
    const last = _idx === _steps.length - 1;
    m.querySelector('#lib-wizard-actions').innerHTML = _done ? `
      <button type="button" class="admin-modal-btn primary" data-action="lib.wizard.cancel">Close</button>` : `
      <button type="button" class="admin-modal-btn" data-action="lib.wizard.cancel">Cancel</button>
      ${_idx > 0 ? '<button type="button" class="admin-modal-btn" data-action="lib.wizard.back">Back</button>' : ''}
      ${last
        ? `<button type="button" class="admin-modal-btn primary" data-action="lib.wizard.submit" ${_busy ? 'disabled' : ''}>${esc(_flow.submitLabel || 'Submit')}</button>`
        : '<button type="button" class="admin-modal-btn primary" data-action="lib.wizard.next">Next</button>'}`;
  }

  function next() {
    if (!_flow || _busy) return;
    _collect();
    if (_flow.validate) {
      const v = _flow.validate(_steps[_idx], _state);
      if (v === false) return;
      if (typeof v === 'string') { _error(v); return; }
    }
    if (_idx < _steps.length - 1) { _idx += 1; _render(); }
  }

  function back() {
    if (!_flow || _busy || _idx === 0) return;
    _idx -= 1;
    _render();
  }

  function cancel() { close(); }

  async function submit() {
    if (!_flow || _busy) return;
    _collect();
    if (_flow.validate) {
      const v = _flow.validate(_steps[_idx], _state);
      if (v === false) return;
      if (typeof v === 'string') { _error(v); return; }
    }
    _busy = true;
    _render();
    const out = document.getElementById('lib-wizard-result');
    if (out) out.innerHTML = '<div class="model-empty">Submitting…</div>';
    try {
      const res = await _flow.onSubmit(_state, { post });
      _busy = false;
      if (res && res.ok) {
        _done = true;
        _render();
        const out2 = document.getElementById('lib-wizard-result');
        if (out2) out2.innerHTML = `<div class="admin-modal-sub" style="color:var(--accent)">✓ ${esc(res.message || 'Done.')}</div>`;
      } else {
        _render();
        _error((res && (res.detail || res.message)) || 'Submit failed.');
      }
    } catch (e) {
      _busy = false;
      _render();
      _error(e.message);
    }
  }

  Actions.click({
    'lib.wizard.next': () => next(),
    'lib.wizard.back': () => back(),
    'lib.wizard.cancel': () => cancel(),
    'lib.wizard.submit': () => submit(),
  });

  return { open, close, next, back, cancel, submit, isOpen, post };
})();
