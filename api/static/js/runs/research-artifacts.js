// runs/research-artifacts.js — research artifact viewer (phase-2 U5 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const ResearchArtifacts = (function () {
  // Capture payloads staged by renderResearchResults — buttons carry only
  // a data-idx into this array, never the (potentially huge) payload itself.
  let _payloads = [];
  function resetPayloads() { _payloads = []; }
  function addPayload(p) { return _payloads.push(p) - 1; }

  // Sentinel used when an angle produced no synthesis body — keeps the capture
  // from 422ing (empty body) while making the gap explicit in the record.
  const EMPTY_BODY_SENTINEL = '(no synthesis was generated for this angle)';

  // True when a payload has no real synthesis text — RX-2 gates promote on this.
  function isEmptyBody(payload) {
    const b = payload && payload.body;
    return !(typeof b === 'string' ? b.trim() : b);
  }

  // Truncate a title to <=200 chars at a word boundary (hard slice fallback),
  // mirroring the server clamp so the ONE capture path can't 422 on length.
  function _truncateTitle(title) {
    const t = String(title == null ? '' : title).trim();
    if (t.length <= 200) return t || '(untitled)';
    const hard = t.slice(0, 200);
    const cut = hard.lastIndexOf(' ');
    return (cut >= 160 ? hard.slice(0, cut) : hard).trim();
  }

  // Normalize a capture payload: bounded title + full-text body with an empty
  // body substituted by the sentinel. This is the ONE guard Research + (later)
  // Operate U14 promote share before POSTing.
  function _normalizeArtifact(payload) {
    const p = (payload && typeof payload === 'object') ? { ...payload } : {};
    p.title = _truncateTitle(p.title);
    const body = typeof p.body === 'string' ? p.body : (p.body == null ? '' : String(p.body));
    p.body = body.trim() ? body : EMPTY_BODY_SENTINEL;
    return p;
  }

  async function captureRaw(payloadJson) {
    let payload;
    try {
      payload = typeof payloadJson === 'string' ? JSON.parse(payloadJson) : payloadJson;
    } catch (e) {
      if (window.Toast) Toast.danger('Capture failed', 'Could not parse payload: ' + e.message);
      return;
    }
    payload = _normalizeArtifact(payload);
    if (window.Toast) Toast.info('Capturing…', payload.title || 'artifact', { ttl: 1500 });
    try {
      // retries:0 — artifact capture writes a record.
      const r = await Net.call('/api/feedback/artifacts', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      });
      if (!r.ok) {
        const text = typeof r.data === 'string' ? r.data : JSON.stringify(r.data || r.error || '');
        throw new Error('HTTP ' + r.status + ' — ' + String(text).slice(0, 200));
      }
      const rec = r.data;
      if (window.Toast) {
        Toast.success(
          'Captured',
          (rec.title || payload.title) + (rec.rag_ingested ? ' · also indexed in Research' : ''),
          { ttl: 3000 }
        );
      }
      return rec;
    } catch (e) {
      if (window.Toast) Toast.danger('Capture failed', String(e));
    }
  }

  async function openLibrary() {
    // Lightweight in-page list — no new tab needed. Renders into an
    // ad-hoc modal so the operator stays in the Skills Lab context.
    let modal = document.getElementById('artifact-library-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'artifact-library-modal';
      modal.className = 'admin-modal';
      modal.role = 'dialog';
      modal.setAttribute('aria-modal', 'true');
      modal.innerHTML = `
        <div class="admin-modal-card" style="width:680px;max-height:78vh;display:flex;flex-direction:column">
          <h3 style="display:flex;align-items:center;justify-content:space-between;gap:8px">
            <span>Captured artifacts</span>
            <button type="button" class="action-btn xs" data-action="research.lib-close">close</button>
          </h3>
          <div id="artifact-library-body" style="flex:1;overflow:auto;font-size:0.72rem"></div>
        </div>
      `;
      document.body.appendChild(modal);
    }
    modal.hidden = false;
    const body = document.getElementById('artifact-library-body');
    body.innerHTML = '<div class="skeleton skeleton-line long"></div><div class="skeleton skeleton-line short"></div><div class="skeleton skeleton-line long"></div>';
    try {
      const list = await Net.getJson('/api/feedback/artifacts?limit=50');
      if (!list.length) {
        body.innerHTML = '<div class="model-empty" style="padding:20px">No artifacts captured yet. Run a research and click <strong>+ Capture as artifact</strong>.</div>';
        return;
      }
      body.innerHTML = list.map(a => `
        <div class="artifact-row">
          <div class="artifact-row-head">
            <strong>${esc(a.title || '(untitled)')}</strong>
            <span class="artifact-row-meta">${esc(a.source || '?')} · ${(a.tags || []).map(t => esc(t)).join(', ')} · ${esc(a.captured_at || '')}</span>
          </div>
          <div class="artifact-row-body">${esc((a.body || '').slice(0, 320))}${(a.body || '').length > 320 ? '…' : ''}</div>
        </div>
      `).join('');
    } catch (e) {
      body.innerHTML = '<div class="model-empty" style="color:var(--red);padding:20px">Failed to load artifacts: ' + esc(String(e)) + '</div>';
    }
  }

  // Delegated actions — the research output re-renders per run; buttons
  // resolve their payload from _payloads by data-idx (module state).
  Actions.click({
    'research.capture': (el, e) => {
      // Capture buttons now live in the always-visible <summary> row; suppress
      // the native <details> toggle so a capture click doesn't collapse it.
      if (e) e.preventDefault();
      const p = _payloads[Number(el.dataset.idx)];
      if (p) captureRaw(p);
    },
    'research.library':   () => openLibrary(),
    'research.export':    () => exportResearch(),
    'research.lib-close': () => {
      const m = document.getElementById('artifact-library-modal');
      if (m) m.hidden = true;
    }
  });

  return { captureRaw, openLibrary, resetPayloads, addPayload, isEmptyBody };
})();
