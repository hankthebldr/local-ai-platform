// admin/auth.js — admin auth (phase-2 U6 carve).
import { Net } from '../core/net.js';

export const AdminAuth = (function () {
  const STORAGE_KEY = 'enclave.licenseKey';
  const LEGACY_SESSION_KEY = 'enclave.admin.masterKey';
  // After successful sign-in, the panel that triggered the modal gets reloaded.
  let pendingPanel = null;

  function getKey() {
    let k = localStorage.getItem(STORAGE_KEY) || '';
    if (!k) {
      // One-shot migration from the old sessionStorage slot.
      const legacy = sessionStorage.getItem(LEGACY_SESSION_KEY) || '';
      if (legacy) {
        localStorage.setItem(STORAGE_KEY, legacy);
        sessionStorage.removeItem(LEGACY_SESSION_KEY);
        k = legacy;
      }
    }
    return k;
  }

  function isSignedIn() {
    return !!getKey();
  }

  function setKey(key) {
    localStorage.setItem(STORAGE_KEY, key);
    sessionStorage.removeItem(LEGACY_SESSION_KEY);
    _refreshStatus();
  }

  function clearKey() {
    localStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(LEGACY_SESSION_KEY);
    _refreshStatus();
  }

  function authHeaders() {
    const key = getKey();
    return key ? { 'Authorization': 'Bearer ' + key } : {};
  }

  /** Wrap a fetch with master-key handling. Returns fetch's Response promise.
   *  If the response is 401, clears the key and re-renders the lock state for
   *  the panel identified by panelId (so the user can re-auth). */
  async function fetch(url, opts, panelId) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {}, authHeaders());
    // raw fetch: THE auth wrapper itself — Net retry around 401-key-clearing would break re-auth UX (Net doesn't support this)
    const r = await window.fetch(url, opts);
    if (r.status === 401) {
      clearKey();
      if (panelId) renderLock(panelId, 'Master key rejected — sign in again.');
    }
    return r;
  }

  /** Render a lock state into the named panel container. */
  function renderLock(panelId, banner) {
    const host = document.getElementById('tab-' + panelId);
    if (!host) return;
    host.innerHTML = `
      <div class="admin-lock">
        <div class="lock-icon" aria-hidden="true">🔒</div>
        <div class="lock-msg">Admin actions require the master key.</div>
        ${banner ? `<div class="admin-modal-error" style="margin:0">${banner}</div>` : ''}
        <button class="lock-btn" data-action="admin.sign-in" data-panel="${panelId}">Sign in as admin</button>
      </div>
    `;
  }

  function signIn(panelId) {
    pendingPanel = panelId;
    document.getElementById('admin-signin-error').hidden = true;
    document.getElementById('admin-signin-input').value = '';
    document.getElementById('admin-signin-modal').hidden = false;
    setTimeout(() => document.getElementById('admin-signin-input').focus(), 0);
  }

  function _cancelSignIn() {
    document.getElementById('admin-signin-modal').hidden = true;
    pendingPanel = null;
  }

  async function _submitSignIn() {
    const input = document.getElementById('admin-signin-input');
    const errBox = document.getElementById('admin-signin-error');
    const candidate = input.value.trim();
    if (!candidate) { errBox.hidden = false; errBox.textContent = 'Enter the master key.'; return; }

    // Validate by hitting an endpoint we know is master-key gated.
    // raw fetch: status-code probe with a candidate key — Net retry would delay 'rejected' feedback, and the module-local fetch() shadows the global here (Net doesn't support this)
    const r = await window.fetch('/api/keys/scopes', {
      headers: { 'Authorization': 'Bearer ' + candidate },
    });
    if (r.status !== 200) {
      errBox.hidden = false;
      errBox.textContent = 'Master key rejected.';
      return;
    }
    setKey(candidate);
    document.getElementById('admin-signin-modal').hidden = true;
    if (pendingPanel) {
      // Re-render the originating admin panel.
      window.dispatchEvent(new CustomEvent('adminPanelActivated', {detail: {panel: pendingPanel}}));
      pendingPanel = null;
    } else {
      // Boot-time / global 401 sign-in — reload so every tab's data fetch
      // reinitializes with the key now in sessionStorage.
      pendingPanel = null;
      window.location.reload();
    }
  }

  function signOut() {
    clearKey();
    // Re-render any visible admin panel as locked.
    document.querySelectorAll('.tab-content[id^="tab-admin-"]').forEach(el => {
      const id = el.id.replace(/^tab-/, '');
      if (el.classList.contains('active')) renderLock(id);
    });
  }

  function _refreshStatus() {
    const status = document.getElementById('admin-menu-status');
    const text = document.getElementById('admin-menu-status-text');
    const so = document.getElementById('admin-menu-signout');
    if (!status || !text || !so) return;
    if (isSignedIn()) {
      status.classList.add('unlocked');
      text.textContent = 'Signed in as admin';
      so.hidden = false;
    } else {
      status.classList.remove('unlocked');
      text.textContent = 'Locked';
      so.hidden = true;
    }
  }

  // Initial paint after DOM is ready.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _refreshStatus);
  } else {
    _refreshStatus();
  }

  // Listen for Enter in the sign-in input.
  document.addEventListener('keydown', function (e) {
    const modal = document.getElementById('admin-signin-modal');
    if (!modal || modal.hidden) return;
    if (e.key === 'Enter') { e.preventDefault(); _submitSignIn(); }
    if (e.key === 'Escape') { e.preventDefault(); _cancelSignIn(); }
  });

  return { isSignedIn, getKey, setKey, clearKey, authHeaders, fetch, renderLock,
           signIn, signOut, _cancelSignIn, _submitSignIn };
})();
