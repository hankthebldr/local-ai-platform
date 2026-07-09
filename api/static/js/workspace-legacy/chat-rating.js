// workspace-legacy/chat-rating.js — legacy chat rating (phase-2 U7).
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';

export const ChatRating = (function () {
  const STORE_KEY = 'enclave.chatRatings.v1';
  let _seq = 0;

  function _load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); }
    catch (_) { return {}; }
  }
  function _save(all) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch (_) {}
  }

  function nextId() {
    _seq += 1;
    return 'cmsg-' + Date.now().toString(36) + '-' + _seq;
  }

  function toolbarHtml(msgId, meta) {
    meta = meta || {};
    const metaAttr = encodeURIComponent(JSON.stringify(meta));
    return (
      '<div class="msg-actions" data-msg-id="' + msgId + '" data-msg-meta="' + metaAttr + '">' +
        // Boot-sequence dispatch — the dormant TTY that hands this answer to
        // the operator's LOCAL agents. margin-right:auto pushes the rating
        // buttons to the right; reuses the .msg-actions hover/opacity ramp.
        '<button type="button" class="bs-dispatch"' +
                ' aria-label="Hand this answer to your local agents to run"' +
                ' title="Resolve this into a local plan — steps, agents, and the models they run on. Nothing leaves this machine."' +
                ' onclick="BootSequence.dispatch(\'' + msgId + '\', this)">' +
          '<span class="bs-dispatch-glyph" aria-hidden="true">&#9656;</span>' +
          '<span class="bs-dispatch-label">run this with my agents</span>' +
          '<span class="bs-dispatch-caret" aria-hidden="true"></span>' +
        '</button>' +
        // Pin-as-step — mark this reply as a workflow step; 2+ pins convert
        // the conversation into a scaffolded DAG (Pins module).
        '<button type="button" class="msg-pin-btn" data-pin="' + msgId + '"' +
                ' title="Pin this reply as a workflow step"' +
                ' onclick="Pins.toggle(\'' + msgId + '\', this)">◇ pin as step</button>' +
        '<button type="button" class="msg-rating-btn up" title="Rate this response good"' +
                ' data-action="chat.rate" data-dir="up">' +
          '<span aria-hidden="true">▲</span>' +
        '</button>' +
        '<button type="button" class="msg-rating-btn down" title="Rate this response bad"' +
                ' data-action="chat.rate" data-dir="down">' +
          '<span aria-hidden="true">▼</span>' +
        '</button>' +
        '<button type="button" class="msg-rating-btn copy" title="Copy message text"' +
                ' data-action="chat.copy">copy</button>' +
        '<span class="msg-rating-status" data-status></span>' +
      '</div>'
    );
  }

  async function rate(msgId, kind, btn) {
    const all = _load();
    // Toggle off if the same button is clicked again.
    if (all[msgId] && all[msgId].kind === kind) {
      delete all[msgId];
      _save(all);
      _paintRowState(msgId, null);
      return;
    }
    const host = btn ? btn.closest('.msg-actions') : null;
    let meta = {};
    try {
      const raw = host ? host.getAttribute('data-msg-meta') : '{}';
      meta = JSON.parse(decodeURIComponent(raw || '{}'));
    } catch (_) { meta = {}; }

    const messageEl = document.getElementById(msgId);
    const textContent = messageEl ? messageEl.innerText.replace(/\s+▲\s+▼\s+copy.*$/s, '').trim() : '';
    const record = {
      kind,
      ts: new Date().toISOString(),
      meta,
      text: textContent.slice(0, 4000),
    };
    all[msgId] = record;
    _save(all);
    _paintRowState(msgId, kind);
    // Node-bound tuning: a vote while bound to a node tunes THAT agent.
    try {
      const bn = window._composerEngagedNodeId;
      if (bn != null && window.AgentTuning) AgentTuning.record(bn, kind, record.text);
    } catch (_) {}

    // Best-effort send to backend. Endpoint may not exist yet; that's fine.
    // silent — a 404 here is expected, no toast. retries:0 — feedback write.
    try {
      await Net.postJson('/api/feedback/messages', { id: msgId, ...record }, { silent: true, retries: 0 });
    } catch (_) { /* offline / not implemented */ }

    if (window.Toast) {
      window.Toast.success(
        kind === 'up' ? 'Marked good' : 'Marked bad',
        'Logged locally' + (kind === 'down' ? ' — consider regenerating with a different model' : ''),
        { ttl: 2500 }
      );
    }
  }

  function _paintRowState(msgId, kind) {
    const host = document.querySelector('.msg-actions[data-msg-id="' + msgId + '"]');
    if (!host) return;
    host.querySelectorAll('.msg-rating-btn').forEach(b => b.classList.remove('on'));
    if (kind === 'up')   host.querySelector('.msg-rating-btn.up')?.classList.add('on');
    if (kind === 'down') host.querySelector('.msg-rating-btn.down')?.classList.add('on');
    const s = host.querySelector('[data-status]');
    if (s) s.textContent = kind ? (kind === 'up' ? 'good' : 'bad') : '';
  }

  async function copy(msgId, btn) {
    const el = document.getElementById(msgId);
    if (!el) return;
    // Strip the toolbar text from the clone before reading.
    const clone = el.cloneNode(true);
    clone.querySelectorAll('.msg-actions').forEach(n => n.remove());
    const txt = clone.innerText.trim();
    try {
      await navigator.clipboard.writeText(txt);
      if (window.Toast) window.Toast.info('Copied', '', { ttl: 1500 });
    } catch (e) {
      if (window.Toast) window.Toast.warn('Copy failed', e.message || String(e), { ttl: 3000 });
    }
  }

  function ratingsFor(filter) {
    const all = _load();
    if (!filter) return all;
    return Object.fromEntries(
      Object.entries(all).filter(([_id, r]) => r.kind === filter)
    );
  }

  // Re-paint rating state when the messages list is rerendered (e.g. on
  // session-load). Idempotent.
  function rehydrate() {
    const all = _load();
    Object.entries(all).forEach(([id, r]) => _paintRowState(id, r.kind));
  }

  return { nextId, toolbarHtml, rate, copy, ratingsFor, rehydrate };
})();
