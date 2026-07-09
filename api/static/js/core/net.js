// core/net.js — fetch/JSON wrapper (phase-2 U2 carve from main.js).

export const Net = (function () {
  let _offline = !navigator.onLine;
  let _offlineToast = null;

  function _setOffline(off) {
    if (_offline === off) return;
    _offline = off;
    if (off) {
      if (window.Toast) {
        _offlineToast = Toast.warn(
          'Offline',
          'Network unreachable. The app will keep trying.',
          { ttl: 0 }
        );
      }
    } else {
      if (_offlineToast) {
        Toast.dismiss(_offlineToast);
        _offlineToast = null;
      }
      if (window.Toast) Toast.success('Back online', 'Reconnected.', { ttl: 2000 });
    }
  }

  window.addEventListener('online',  () => _setOffline(false));
  window.addEventListener('offline', () => _setOffline(true));

  function _shouldRetry(status) {
    return status === 429 || status === 502 || status === 503 || status === 504;
  }

  async function call(url, opts) {
    opts = opts || {};
    const maxRetries = opts.retries == null ? 2 : opts.retries;
    const backoffMs  = opts.backoffMs || 600;
    const silent     = !!opts.silent;
    const expectJson = opts.expectJson !== false;

    let lastError = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const r = await window.fetch(url, opts.init || opts);
        if (!r.ok && _shouldRetry(r.status) && attempt < maxRetries) {
          const retryAfter = parseInt(r.headers.get('Retry-After') || '0', 10);
          const wait = retryAfter > 0 ? retryAfter * 1000 : backoffMs * Math.pow(2, attempt);
          await new Promise(rs => setTimeout(rs, wait));
          continue;
        }
        _setOffline(false);
        let data = null;
        if (expectJson) {
          try { data = await r.clone().json(); } catch (_) {
            try { data = await r.text(); } catch (_) { data = null; }
          }
        }
        return {
          ok: r.ok,
          status: r.status,
          data,
          response: r,
          retried: attempt,
          error: r.ok ? null : (data && typeof data === 'object' && (data.detail || data.error)) || ('HTTP ' + r.status),
        };
      } catch (e) {
        lastError = e;
        // Network error — exponential backoff before retrying.
        if (attempt < maxRetries) {
          await new Promise(rs => setTimeout(rs, backoffMs * Math.pow(2, attempt)));
          continue;
        }
        _setOffline(true);
        if (!silent && window.Toast) {
          Toast.danger('Request failed', String(e.message || e), { ttl: 4000 });
        }
        return {
          ok: false,
          status: 0,
          data: null,
          response: null,
          retried: attempt,
          error: e.message || String(e),
        };
      }
    }
    return { ok: false, status: 0, data: null, response: null, retried: maxRetries, error: String(lastError) };
  }

  // Convenience methods that return the data directly + throw on failure.
  // Use these in flows that already have local try/catch + want the
  // result body, not the wrapper.
  async function getJson(url, opts) {
    const r = await call(url, { ...(opts || {}), init: { method: 'GET', ...(opts && opts.init || {}) } });
    if (!r.ok) throw new Error(r.error || ('GET ' + url + ' failed: ' + r.status));
    return r.data;
  }
  async function postJson(url, body, opts) {
    const init = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...((opts && opts.init && opts.init.headers) || {}) },
      body: typeof body === 'string' ? body : JSON.stringify(body || {}),
    };
    const r = await call(url, { ...(opts || {}), init });
    if (!r.ok) throw new Error(r.error || ('POST ' + url + ' failed: ' + r.status));
    return r.data;
  }

  return { call, getJson, postJson, isOffline: () => _offline };
})();
