// workspace-legacy/boot-sequence.js — legacy boot sequence (phase-2 U7). df* via window bridge.
import { Toast } from '../core/ui.js';

export const BootSequence = (function () {
  let _plan = { spec: null, scaffold: null };
  let _escHandler = null;

  function _reduced() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function _thread() {
    const hist = (typeof chatHistory !== 'undefined' && Array.isArray(chatHistory)) ? chatHistory : [];
    return hist
      .filter(m => m && (m.content || '').trim())
      .map(m => ({ role: m.role || 'user', content: String(m.content) }));
  }

  async function _post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  function _emit(btn) {
    if (_reduced() || !btn) return Promise.resolve();
    const split = document.getElementById('composer-split');
    if (!split) return Promise.resolve();
    const b = btn.getBoundingClientRect();
    const target = document.getElementById('composer-spine-dormant') || split;
    const s = target.getBoundingClientRect();
    const dot = document.createElement('div');
    dot.className = 'bs-emit-dot';
    dot.style.left = b.right + 'px';
    dot.style.top = (b.top + b.height / 2) + 'px';
    dot.style.setProperty('--bs-emit-x', (s.left + s.width / 2 - b.right) + 'px');
    dot.style.setProperty('--bs-emit-y', (s.top + 60 - (b.top + b.height / 2)) + 'px');
    document.body.appendChild(dot);
    return new Promise(res => {
      dot.addEventListener('animationend', () => { dot.remove(); res(); }, { once: true });
      setTimeout(() => { dot.remove(); res(); }, 700);
    });
  }

  async function dispatch(msgId, btn) {
    if (document.getElementById('bs-plan-card')) return; // one plan at a time
    const split = document.getElementById('composer-split');
    if (!split) return;
    // Fresh dispatch → fresh plan. Without this, a failed capture-spec
    // leaves the PREVIOUS dispatch's spec/scaffold in _plan, and recompile/
    // confirm would silently operate on the stale plan.
    _plan = { spec: null, scaffold: null };
    const messages = _thread();
    if (!messages.length) {
      if (window.Toast) Toast.warn('Nothing to plan yet', 'Chat first, then hand it to your agents.');
      return;
    }
    try { localStorage.setItem('enclave.bs.hinted', '1'); } catch (_) {}
    document.body.classList.remove('bs-show-hint');

    // P0-10: the crystallize affordance ("run this with my agents") lives in the
    // Chat tab, but the plan card renders into #composer-split, which sits on the
    // Composer (#tab-dashboard). After the four-surface separation that tab is
    // hidden while the operator is in Chat, so the card + confirm button landed
    // on a display:none surface — a dead end. Reveal the Composer BEFORE render
    // so the plan card is on the visible tab and confirm is reachable.
    if (typeof switchTab === 'function') { try { switchTab('dashboard'); } catch (_) {} }

    await _emit(btn);
    _renderShell(split);
    try {
      const spec = await _post('/api/composer/capture-spec', { messages });
      _plan.spec = spec;
      const scaf = await _post('/api/composer/scaffold', {
        goal: spec.goal, inputs: spec.inputs, checks: spec.checks,
      });
      _plan.scaffold = scaf;
      _fill(spec, scaf);
    } catch (e) {
      _error(e);
    }
  }

  function _renderShell(split) {
    const card = document.createElement('div');
    card.id = 'bs-plan-card';
    card.className = 'bs-card panel bs-compiling';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Compiled plan');
    card.innerHTML =
      '<span class="corner-tr" aria-hidden="true"></span><span class="corner-bl" aria-hidden="true"></span>' +
      '<div class="bs-banner">' +
        '<span class="bs-banner-caret" aria-hidden="true"></span>' +
        '<span class="bs-banner-title">enclave · compiling plan</span>' +
        '<span class="bs-host-chip"><span class="status-pip online"></span>localhost · 0 cloud calls</span>' +
      '</div>' +
      '<div class="bs-body" id="bs-body">' +
        '<div class="bs-compiling-note">resolving your request into a local plan…</div>' +
      '</div>' +
      '<div class="bs-cmdbar">' +
        '<button type="button" class="bs-cmd bs-cmd-recompile" onclick="BootSequence.recompile()" disabled>recompile ⟳</button>' +
        '<button type="button" class="bs-cmd bs-cmd-cancel" onclick="BootSequence.cancel()">keep talking</button>' +
        '<button type="button" class="bs-cmd bs-cmd-confirm action-btn accent" onclick="BootSequence.confirm()" disabled>sign &amp; bring online ↵</button>' +
      '</div>';
    split.appendChild(card);
    _attachEsc();
  }

  function _esc(text) {
    const d = document.createElement('div');
    d.textContent = text == null ? '' : String(text);
    return d.innerHTML;
  }

  function _fill(spec, scaf) {
    const card = document.getElementById('bs-plan-card');
    if (!card) return;
    card.classList.remove('bs-compiling');
    const title = card.querySelector('.bs-banner-title');
    if (title) title.textContent = 'enclave · ' + (scaf.source === 'template' ? 'matched a local template' : 'plan compiled');

    const body = card.querySelector('#bs-body');
    const inputsText = (spec.inputs || []).map(i => i.key).join(', ');
    const checksText = (spec.checks || []).join(' · ');
    const bindings = scaf.bindings || [];
    const models = new Set(bindings.map(b => b.model).filter(Boolean));
    const N = bindings.length;

    let html =
      _stanza(0, 'goal', 'Goal', _esc(spec.goal), 'what should this accomplish') +
      _stanza(1, 'inputs', 'Inputs', _esc(inputsText), 'no run-time inputs') +
      _stanza(2, 'checks', 'Checks', _esc(checksText), 'no explicit checks');

    html += '<div class="bs-roster" aria-live="polite">';
    bindings.forEach((b, i) => {
      const stamp = '[ 0.' + String((i * 7 + 12) % 100).padStart(2, '0') + ' ]';
      const role = b.role || 'reasoning';
      html +=
        '<div class="bs-probe" style="--bs-i:' + i + '" data-kind="role">' +
          '<span class="bs-probe-rail" aria-hidden="true"></span>' +
          '<span class="bs-probe-glyph" aria-hidden="true">◦</span>' +
          '<span class="bs-probe-name">' + _esc(b.name || ('step ' + (i + 1))) + '</span>' +
          '<span class="bs-probe-bind"><span class="bs-pill bs-pill-role">ROLE · ' + _esc(role) + '</span></span>' +
          '<span class="bs-probe-ok" aria-hidden="true">→ ok</span>' +
          '<span class="bs-model"><span class="status-pip online"></span>' +
            '<span class="bs-model-name">@ ' + _esc(b.model || 'local model') + '</span>' +
            '<span class="bs-model-host">· local</span>' +
          '</span>' +
        '</div>';
    });
    html += '</div>';

    html +=
      '<div class="bs-seal-row">' +
        '<span class="bs-seal" data-state="unsigned">UNSIGNED</span>' +
        '<span class="bs-tally"><b data-count>0</b> local models · 0 calls leave this machine</span>' +
        '<span class="bs-lock" aria-hidden="true">🔓</span>' +
      '</div>';

    body.innerHTML = html;

    const recompileBtn = card.querySelector('.bs-cmd-recompile');
    const confirmBtn = card.querySelector('.bs-cmd-confirm');
    if (recompileBtn) recompileBtn.disabled = false;
    if (confirmBtn) confirmBtn.disabled = false;

    _countUp(card, models.size || N, N);

    const firstVal = card.querySelector('.bs-stanza-val');
    if (firstVal) { try { firstVal.focus(); } catch (_) {} }
  }

  function _stanza(i, field, label, val, placeholder) {
    return '<div class="bs-stanza" data-field="' + field + '" style="--bs-i:' + i + '">' +
      '<span class="bs-stanza-label">[ ' + label.toLowerCase() + ' ]</span>' +
      '<span class="bs-stanza-val" contenteditable="true" role="textbox" aria-label="' + label + '" ' +
        'data-placeholder="' + placeholder + '">' + val + '</span>' +
    '</div>';
  }

  function _countUp(card, target, steps) {
    const el = card.querySelector('.bs-tally b');
    if (!el) return;
    if (_reduced()) { el.textContent = String(target); return; }
    const startDelay = 440 + Math.max(0, steps - 1) * 140 + 220 + 90;
    setTimeout(() => {
      const dur = 600; const t0 = performance.now();
      function tick(now) {
        const k = Math.min(1, (now - t0) / dur);
        el.textContent = String(Math.round(k * target));
        if (k < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }, startDelay);
  }

  function _error(e) {
    const card = document.getElementById('bs-plan-card');
    if (!card) return;
    card.classList.remove('bs-compiling');
    const body = card.querySelector('#bs-body');
    if (body) body.innerHTML = '<div class="bs-compiling-note">Could not reach the local planner. ' +
      _esc((e && e.message) ? e.message.slice(0, 160) : '') + '</div>';
  }

  // Read the (possibly edited) spec out of the card's contenteditable stanzas.
  function _specFromCard(card) {
    const goalEl = card.querySelector('[data-field="goal"] .bs-stanza-val');
    const inputsEl = card.querySelector('[data-field="inputs"] .bs-stanza-val');
    const checksEl = card.querySelector('[data-field="checks"] .bs-stanza-val');
    const base = _plan.spec || { goal: '', inputs: [], checks: [] };
    return {
      goal: (goalEl ? goalEl.textContent : base.goal || '').trim(),
      inputs: inputsEl
        ? inputsEl.textContent.split(',').map(s => s.trim()).filter(Boolean).map(k => ({ key: k, description: '' }))
        : (base.inputs || []),
      checks: checksEl
        ? checksEl.textContent.split(/[·\n;]/).map(s => s.trim()).filter(Boolean)
        : (base.checks || []),
    };
  }

  function _specDiffers(a, b) {
    if (!b) return true;
    if ((a.goal || '') !== (b.goal || '')) return true;
    if ((a.inputs || []).map(i => i.key).join('|') !== (b.inputs || []).map(i => i.key).join('|')) return true;
    if ((a.checks || []).join('|') !== (b.checks || []).join('|')) return true;
    return false;
  }

  async function _rescaffold(spec) {
    const card = document.getElementById('bs-plan-card');
    if (card) card.classList.add('bs-compiling');
    const scaf = await _post('/api/composer/scaffold', spec);
    _plan.spec = spec;
    _plan.scaffold = scaf;
    _fill(spec, scaf);
    return scaf;
  }

  async function recompile() {
    const card = document.getElementById('bs-plan-card');
    if (!card || !_plan.spec) return;
    try { await _rescaffold(_specFromCard(card)); } catch (e) { _error(e); }
  }

  async function confirm() {
    const card = document.getElementById('bs-plan-card');
    const split = document.getElementById('composer-split');
    if (!card || !split || !_plan.scaffold) return;

    // Don't clobber a live workflow silently — composerLoadDefinition wipes
    // the canvas. Start/End anchors live only in the drawflow editor, never
    // in dfNodeData, so every entry here is a real step.
    const existing = (typeof dfNodeData !== 'undefined')
      ? Object.values(dfNodeData).filter(Boolean).length : 0;
    if (existing > 0 && !window.confirm(
        'The canvas already holds a workflow (' + existing + ' step' +
        (existing === 1 ? '' : 's') + '). Replace it with this plan?')) {
      return;
    }

    // If the operator edited the spec (goal / inputs / checks) since the last
    // scaffold, re-scaffold so the edits actually shape the DAG — not just the
    // goal, and not silently dropped.
    const edited = _specFromCard(card);
    if (_specDiffers(edited, _plan.spec)) {
      try { await _rescaffold(edited); }
      catch (e) { _error(e); return; }
    }

    const defn = _plan.scaffold.definition || {};
    if (edited.goal) defn.description = edited.goal;

    // STAMP — the sign gesture.
    const seal = card.querySelector('.bs-seal');
    if (seal) { seal.setAttribute('data-state', 'signed'); seal.textContent = 'SIGNED · LOCAL'; seal.classList.add('bs-stamping'); }
    const lock = card.querySelector('.bs-lock'); if (lock) lock.textContent = '🔒';
    _detachEsc();

    const reduced = _reduced();
    const begin = () => {
      split.classList.add('bs-booting');
      card.classList.add('bs-powerdown');
      // Prime FIRST so the canvas is visible + sized before drawflow lays out
      // nodes, and hold it primed across the build (the lock is read by
      // updateCanvasEmptyState). Then build via the shared load path.
      window._bsPriming = true;
      if (typeof ComposerSplit !== 'undefined') ComposerSplit.setSpinePrimed(true);
      // composerLoadDefinition switches to the Composer tab BEFORE spawning
      // nodes (S0 reveal-centralization) — the canvas is visible + sized when
      // drawflow lays out, replacing the retired canvas-mode pivot.
      composerLoadDefinition(defn);
      if (typeof ComposerSplit !== 'undefined') ComposerSplit.setSpinePrimed(true);
      window._bsPriming = false;
      // Mark the handoff in the transcript — the chat is the operator's
      // timeline, and without this the promotion never appears in it.
      try {
        const msgEl = document.getElementById('messages');
        if (msgEl) {
          const stepCount = (defn.steps || []).length;
          const note = document.createElement('div');
          note.className = 'msg system-msg';
          note.textContent = '⚙ Conversation promoted — workflow "' +
            (defn.name || defn.id || 'untitled') + '" (' + stepCount +
            ' step' + (stepCount === 1 ? '' : 's') + ') is live on the canvas.';
          msgEl.appendChild(note);
          msgEl.scrollTop = msgEl.scrollHeight;
        }
      } catch (_) {}
      // Re-layout once more now the canvas is definitely visible + sized.
      setTimeout(() => { try { if (typeof dfAutoLayout === 'function') dfAutoLayout(); } catch (_) {} }, 70);
      _igniteAndStream(split);
      const cleanup = () => {
        card.remove();
        split.classList.remove('bs-booting', 'bs-current');
      };
      setTimeout(cleanup, reduced ? 0 : 320);
    };
    if (reduced) begin(); else setTimeout(begin, 180);
  }

  function _igniteAndStream(split) {
    split.querySelectorAll('.wf-anchor-start, .wf-anchor-end').forEach(a => a.classList.add('bs-ignite'));
    const nodes = Array.from(split.querySelectorAll('#drawflow-canvas .drawflow-node'))
      .filter(n => !n.querySelector('.wf-anchor'));
    if (_reduced() || !nodes.length) return;
    nodes.forEach((n, i) => { n.style.setProperty('--bs-i', i); n.classList.add('bs-node-enter'); });
    setTimeout(() => nodes.forEach(n => n.classList.add('bs-node-in')), 90);
    const last = Math.max(0, nodes.length - 1) * 110 + 220 + 90;
    setTimeout(() => {
      split.classList.add('bs-current');
      setTimeout(() => split.classList.remove('bs-current'), 700);
    }, last);
  }

  function cancel() {
    const card = document.getElementById('bs-plan-card');
    if (card) card.remove();
    _detachEsc();
    if (typeof ComposerSplit !== 'undefined') ComposerSplit.focusChat();
  }

  function _attachEsc() {
    _escHandler = (e) => { if (e.key === 'Escape') cancel(); };
    document.addEventListener('keydown', _escHandler);
  }
  function _detachEsc() {
    if (_escHandler) { document.removeEventListener('keydown', _escHandler); _escHandler = null; }
  }

  // One-time discoverability hint on the affordance.
  try {
    if (!localStorage.getItem('enclave.bs.hinted') && document.body) {
      document.body.classList.add('bs-show-hint');
    }
  } catch (_) {}

  return { dispatch, recompile, confirm, cancel };
})();
