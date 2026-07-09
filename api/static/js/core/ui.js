// core/ui.js — Toast/Confirm/EmptyState/ErrorPanel/Skeleton primitives (phase-2 U2 carve).
import { esc } from './dom.js';

export const Toast = (function () {
  function _container() {
    let c = document.getElementById('enclave-toasts');
    if (!c) {
      c = document.createElement('div');
      c.id = 'enclave-toasts';
      // Live region: every async notification in the app funnels through
      // this one container, so screen readers hear all of them for free.
      c.setAttribute('role', 'status');
      c.setAttribute('aria-live', 'polite');
      document.body.appendChild(c);
    }
    return c;
  }
  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function show(kind, title, body, opts) {
    opts = opts || {};
    const el = document.createElement('div');
    el.className = 'enclave-toast kind-' + kind;
    // Danger toasts interrupt (role=alert → assertive); the rest queue
    // politely behind whatever the screen reader is saying.
    if (kind === 'danger') el.setAttribute('role', 'alert');
    el.innerHTML =
      (title ? '<div class="toast-title">' + _esc(title) + '</div>' : '') +
      '<div class="toast-body">' + _esc(body || title) + '</div>';
    el.addEventListener('click', () => dismiss(el));
    _container().appendChild(el);
    const ttl = opts.ttl != null ? opts.ttl : 4000;
    if (ttl > 0) setTimeout(() => dismiss(el), ttl);
    return el;
  }
  function dismiss(el) {
    if (!el || !el.isConnected) return;
    el.classList.add('dismissing');
    setTimeout(() => el.remove(), 240);
  }
  return {
    info:    (t, b, o) => show('info', t, b, o),
    success: (t, b, o) => show('success', t, b, o),
    warn:    (t, b, o) => show('warn', t, b, o),
    danger:  (t, b, o) => show('danger', t, b, o),
    dismiss,
  };
})();

export const ErrorPanel = (function () {
  function render(el, opts) {
    if (!el) return;
    opts = opts || {};
    const title = opts.title || 'Something went wrong';
    const detail = opts.detail || opts.error || '';
    const action = opts.retry
      ? `<button class="action-btn xs cyan" data-error-retry>Retry</button>`
      : '';
    el.innerHTML = `
      <div class="enclave-error-panel">
        <div class="enclave-error-icon" aria-hidden="true">!</div>
        <div class="enclave-error-body">
          <div class="enclave-error-title">${esc(title)}</div>
          ${detail ? `<div class="enclave-error-detail">${esc(String(detail).slice(0, 400))}</div>` : ''}
          ${action ? `<div class="enclave-error-actions">${action}</div>` : ''}
        </div>
      </div>`;
    if (opts.retry) {
      const btn = el.querySelector('[data-error-retry]');
      if (btn) btn.addEventListener('click', () => opts.retry());
    }
  }
  return { render };
})();

export const EmptyState = (function () {
  function render(el, opts) {
    if (!el) return;
    opts = opts || {};
    const title = opts.title || 'Nothing here yet';
    const detail = opts.detail || '';
    const cta = opts.cta;  // {label, onclick}
    el.innerHTML = `
      <div class="enclave-empty-state">
        <div class="enclave-empty-glyph" aria-hidden="true">${esc(opts.glyph || '◇')}</div>
        <div class="enclave-empty-title">${esc(title)}</div>
        ${detail ? `<div class="enclave-empty-detail">${esc(detail)}</div>` : ''}
        ${cta ? `<button class="action-btn accent" data-empty-cta>${esc(cta.label)}</button>` : ''}
      </div>`;
    if (cta && cta.onclick) {
      const btn = el.querySelector('[data-empty-cta]');
      if (btn) btn.addEventListener('click', cta.onclick);
    }
  }
  return { render };
})();

export const Skeleton = (function () {
  function fill(el, count, opts) {
    if (!el) return;
    count = count || 3;
    opts = opts || {};
    const lines = [];
    for (let i = 0; i < count; i++) {
      const cls = i % 2 === 0 ? 'long' : 'short';
      lines.push('<div class="skeleton skeleton-line ' + cls + '"></div>');
    }
    el.innerHTML = lines.join('');
  }
  return { fill };
})();

export const Confirm = (function () {
  let _open = false;   // re-entrancy guard — the singleton modal can't host two asks
  function ask(opts) {
    opts = opts || {};
    // A second ask() while one is pending would stack listeners on the
    // shared modal buttons (one OK → both promises resolve true). Decline
    // the overlap instead. Legitimate sequential confirms await the first,
    // so _open is already false by the time they call.
    if (_open) return Promise.resolve(false);
    return new Promise((resolve) => {
      _open = true;
      let m = document.getElementById('enclave-confirm-modal');
      if (!m) {
        m = document.createElement('div');
        m.id = 'enclave-confirm-modal';
        m.className = 'admin-modal';
        m.setAttribute('role', 'dialog');
        m.setAttribute('aria-modal', 'true');
        m.setAttribute('aria-labelledby', 'enclave-confirm-title');
        m.setAttribute('aria-describedby', 'enclave-confirm-body');
        m.innerHTML = `
          <div class="admin-modal-card" style="width:min(440px,90vw)">
            <h3 id="enclave-confirm-title">Confirm</h3>
            <p class="admin-modal-sub" id="enclave-confirm-body"></p>
            <div class="admin-modal-actions">
              <button type="button" class="admin-modal-btn"        id="enclave-confirm-cancel">Cancel</button>
              <button type="button" class="admin-modal-btn primary" id="enclave-confirm-ok">OK</button>
            </div>
          </div>
        `;
        document.body.appendChild(m);
      }
      m.querySelector('#enclave-confirm-title').textContent = opts.title || 'Confirm';
      m.querySelector('#enclave-confirm-body').textContent  = opts.body  || 'Are you sure?';
      m.querySelector('#enclave-confirm-ok').textContent    = opts.okLabel    || 'OK';
      m.querySelector('#enclave-confirm-cancel').textContent = opts.cancelLabel || 'Cancel';
      const okBtn = m.querySelector('#enclave-confirm-ok');
      okBtn.className = 'admin-modal-btn primary' + (opts.danger ? ' kind-danger' : '');
      m.hidden = false;

      const _restoreFocus = document.activeElement;
      function _close(value) {
        _open = false;
        m.hidden = true;
        okBtn.removeEventListener('click', _yes);
        cancelBtn.removeEventListener('click', _no);
        document.removeEventListener('keydown', _onKey, true);
        // Hand focus back to whatever opened the dialog (keyboard users
        // otherwise land back at the top of the document).
        if (_restoreFocus && _restoreFocus.isConnected) {
          try { _restoreFocus.focus(); } catch (_) {}
        }
        resolve(value);
      }
      function _yes() { _close(true); }
      function _no()  { _close(false); }
      function _onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); _no(); return; }
        // Enter confirms — but NOT when Cancel holds focus. Pressing Enter
        // on a focused Cancel is the standard decline gesture; mapping it to
        // _yes() (and preventDefault-ing the button's own activation) would
        // silently confirm a destructive action.
        if (e.key === 'Enter') {
          if (document.activeElement === cancelBtn) return;  // let Cancel activate natively
          e.preventDefault(); _yes(); return;
        }
        // Focus trap: keep Tab inside the two buttons so keyboard users
        // can't walk out to (and accidentally activate) background controls
        // while the dialog is open.
        if (e.key === 'Tab') {
          e.preventDefault();
          const next = (document.activeElement === okBtn) ? cancelBtn : okBtn;
          next.focus();
        }
      }
      const cancelBtn = m.querySelector('#enclave-confirm-cancel');
      okBtn.addEventListener('click', _yes);
      cancelBtn.addEventListener('click', _no);
      // Capture phase so the trap sees Tab before it reaches the document.
      document.addEventListener('keydown', _onKey, true);
      setTimeout(() => okBtn.focus(), 0);
    });
  }
  return { ask };
})();
