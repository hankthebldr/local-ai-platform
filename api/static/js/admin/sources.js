// admin/sources.js — Admin ▸ Sources panel (LB0-U2).
//
// Admin determines the SOURCE of library inventory; Library panels own
// per-item behavior. This panel lists every discovery provider, offers
// per-source operator-triggered Refresh (the ONLY network-egress path —
// reads always serve the cached/persisted feed), and edits the persisted
// source config (allowlists, cache TTLs, masked GitHub token) through
// GET/PUT /api/discover/config.
//
// Gate is ApiKeysPanel-strict: AdminAuth.isSignedIn() + renderLock BEFORE
// any fetch. Keeps its local shadowing esc() like its admin/ siblings.
import { Toast } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { AdminAuth } from './auth.js';
import { AdminMenu } from './menu.js';

export const SourcesPanel = (function () {

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  let _providers = [];
  let _config = null;

  // AdminAuth.renderLock replaces the whole tab's innerHTML with the lock
  // screen; capture the pristine skeleton at module eval (type=module runs
  // after HTML parse) so a post-sign-in load() can restore the panels.
  const _tab0 = document.getElementById('tab-admin-sources');
  const _pristine = _tab0 ? _tab0.innerHTML : '';

  function _ensureSkeleton() {
    const tab = document.getElementById('tab-admin-sources');
    if (!tab) return false;
    if (!document.getElementById('admin-sources-list')) {
      if (!_pristine) return false;
      tab.innerHTML = _pristine; // heal after a renderLock overwrite
    }
    return true;
  }

  async function load() {
    // Strictest gate (ApiKeysPanel pattern): lock BEFORE any fetch.
    if (!AdminAuth.isSignedIn()) {
      AdminAuth.renderLock('admin-sources');
      return;
    }
    if (!_ensureSkeleton()) return;
    const list = document.getElementById('admin-sources-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">Loading…</div>';

    const [rp, rc] = await Promise.all([
      AdminAuth.fetch('/api/discover/sources', {}, 'admin-sources'),
      AdminAuth.fetch('/api/discover/config', {}, 'admin-sources'),
    ]);
    if (!rp.ok || !rc.ok) {
      // 401 already handled by AdminAuth.fetch (lock re-render).
      const el = document.getElementById('admin-sources-list');
      if (el) el.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed to load sources (HTTP ${rp.ok ? rc.status : rp.status})</div>`;
      return;
    }
    _providers = (await rp.json()).providers || [];
    _config = await rc.json();
    _renderProviders();
    _renderConfig();
  }

  function refresh() { load(); }

  function _renderProviders() {
    const list = document.getElementById('admin-sources-list');
    if (!list) return;
    if (!Array.isArray(_providers) || _providers.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">No discovery providers registered.</div>';
      return;
    }
    list.innerHTML = _providers.map(p => {
      const synced = p.last_synced
        ? new Date(p.last_synced * 1000).toLocaleString()
        : '<span style="color:var(--text-muted)">never</span>';
      return `
      <div class="plugin-card" style="width:100%" data-source="${esc(p.source)}">
        <div class="plugin-card-title">
          <span class="plugin-status-pip ${p.implemented ? '' : 'error'}"></span>${esc(p.name || p.source)}
          <span style="color:var(--text-muted);font-size:0.66rem;margin-left:6px"><code>${esc(p.source)}</code></span>
          <span style="float:right">
            <button class="action-btn small" type="button"
                    data-action="admin.sources.refresh-one" data-source="${esc(p.source)}">Refresh</button>
          </span>
        </div>
        <div class="plugin-card-meta">
          ${(p.kinds || []).map(k => `<span class="role-pill">${esc(k)}</span>`).join(' ')}
          · ${p.cached_count || 0} cached · last synced ${synced}
        </div>
        <div class="plugin-card-desc">${esc(p.description || '')}</div>
      </div>`;
    }).join('');
  }

  function _renderConfig() {
    const host = document.getElementById('admin-sources-config');
    if (!host || !_config) return;
    const c = _config;
    const listOrDash = (arr) => (arr && arr.length)
      ? arr.map(r => `<code>${esc(r)}</code>`).join(', ')
      : '<span style="color:var(--text-muted)">—</span>';
    const ttls = c.cache_ttls || {};
    const ttlRows = Object.keys(ttls).sort()
      .map(k => `<code>${esc(k)}</code>=${esc(ttls[k])}s`).join(' · ');
    host.innerHTML = `
      <div style="font-size:0.74rem;display:grid;grid-template-columns:160px 1fr;gap:6px 14px;margin-bottom:14px">
        <div style="color:var(--text-muted)">Skill repos</div><div>${listOrDash(c.skill_repos)}</div>
        <div style="color:var(--text-muted)">Plugin marketplaces</div><div>${listOrDash(c.plugin_marketplaces)}</div>
        <div style="color:var(--text-muted)">Prompt digest sources</div><div>${listOrDash(c.prompt_digest_sources)}</div>
        <div style="color:var(--text-muted)">Skills catalog URL</div><div>${c.catalog_urls && c.catalog_urls.skills ? `<code>${esc(c.catalog_urls.skills)}</code>` : '<span style="color:var(--text-muted)">—</span>'}</div>
        <div style="color:var(--text-muted)">MCP catalog URL</div><div>${c.catalog_urls && c.catalog_urls.mcp ? `<code>${esc(c.catalog_urls.mcp)}</code>` : '<span style="color:var(--text-muted)">—</span>'}</div>
        <div style="color:var(--text-muted)">Refresh cache TTLs</div><div>${ttlRows || '<span style="color:var(--text-muted)">—</span>'}</div>
        <div style="color:var(--text-muted)">GitHub token</div><div>${c.github_token_set
          ? `<span style="color:var(--accent)">set ✓</span> <code>${esc(c.github_token_masked)}</code>`
          : '<span style="color:var(--text-muted)">not set (60 req/hr unauthenticated ceiling)</span>'}</div>
      </div>
      <div style="color:var(--text-muted);font-size:0.68rem">
        Persisted to <code>data/config/discovery_sources.json</code> (file &gt; env &gt; default).
        Providers read it at fetch time — saved changes govern the next Refresh, no restart.
      </div>
    `;
  }

  async function refreshOne(source, el) {
    if (!AdminAuth.isSignedIn()) { AdminAuth.renderLock('admin-sources'); return; }
    if (!source) return;
    if (el) { el.disabled = true; el.textContent = 'Refreshing…'; }
    try {
      const r = await AdminAuth.fetch(
        `/api/discover/${encodeURIComponent(source)}/refresh`,
        { method: 'POST' }, 'admin-sources');
      if (!r.ok) {
        Toast.danger('Refresh failed', `${source}: HTTP ${r.status}`);
        return;
      }
      const feed = await r.json();
      if (feed.error) Toast.warn(`${source} refreshed with errors`, feed.error);
      else Toast.success(`${source} refreshed`, `${feed.count || 0} item${feed.count === 1 ? '' : 's'}`);
    } finally {
      load(); // re-render counts + last-synced stamps (also re-enables the button)
    }
  }

  function showEdit() {
    if (!AdminAuth.isSignedIn()) { AdminAuth.renderLock('admin-sources'); return; }
    if (!_ensureSkeleton() || !_config) return;
    const c = _config;
    const put = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    put('admin-sources-skill-repos', (c.skill_repos || []).join('\n'));
    put('admin-sources-marketplaces', (c.plugin_marketplaces || []).join('\n'));
    put('admin-sources-prompt-sources', (c.prompt_digest_sources || []).join('\n'));
    put('admin-sources-catalog-skills', (c.catalog_urls && c.catalog_urls.skills) || '');
    put('admin-sources-catalog-mcp', (c.catalog_urls && c.catalog_urls.mcp) || '');
    const ttls = c.cache_ttls || {};
    put('admin-sources-ttl-default', ttls.default != null ? String(ttls.default) : '300');
    put('admin-sources-ttl-hf', ttls['hf-discovery'] != null ? String(ttls['hf-discovery']) : '');
    const tok = document.getElementById('admin-sources-token');
    if (tok) {
      tok.value = ''; // the raw token NEVER round-trips; empty = keep current
      tok.placeholder = c.github_token_set ? `current: ${c.github_token_masked}` : 'ghp_… (optional)';
    }
    const clear = document.getElementById('admin-sources-token-clear');
    if (clear) clear.checked = false;
    const errBox = document.getElementById('admin-sources-edit-error');
    if (errBox) errBox.hidden = true;
    document.getElementById('admin-sources-edit-modal').hidden = false;
    setTimeout(() => { const el = document.getElementById('admin-sources-skill-repos'); if (el) el.focus(); }, 0);
  }

  function _closeModal() {
    const modal = document.getElementById('admin-sources-edit-modal');
    if (modal) modal.hidden = true;
    const tok = document.getElementById('admin-sources-token');
    if (tok) tok.value = ''; // no secret lingers in the DOM
  }

  function _lines(id) {
    const el = document.getElementById(id);
    if (!el) return [];
    return el.value.split(/[\n,]/).map(s => s.trim()).filter(Boolean);
  }

  async function _submit() {
    const errBox = document.getElementById('admin-sources-edit-error');
    errBox.hidden = true;

    const body = {
      skill_repos: _lines('admin-sources-skill-repos'),
      plugin_marketplaces: _lines('admin-sources-marketplaces'),
      prompt_digest_sources: _lines('admin-sources-prompt-sources'),
      catalog_urls: {
        skills: document.getElementById('admin-sources-catalog-skills').value.trim(),
        mcp: document.getElementById('admin-sources-catalog-mcp').value.trim(),
      },
    };

    const ttls = {};
    const defRaw = document.getElementById('admin-sources-ttl-default').value.trim();
    const hfRaw = document.getElementById('admin-sources-ttl-hf').value.trim();
    if (defRaw) ttls.default = Number(defRaw);
    if (hfRaw) ttls['hf-discovery'] = Number(hfRaw);
    for (const k in ttls) {
      if (!Number.isFinite(ttls[k]) || ttls[k] < 0) {
        errBox.hidden = false;
        errBox.textContent = `Cache TTL '${k}' must be a number >= 0 (seconds).`;
        return;
      }
    }
    if (Object.keys(ttls).length) body.cache_ttls = ttls;

    // Token: empty input = keep current; checkbox clears; new value rotates.
    const tokVal = document.getElementById('admin-sources-token').value;
    const clearTok = document.getElementById('admin-sources-token-clear').checked;
    if (clearTok) body.github_token = '';
    else if (tokVal.trim()) body.github_token = tokVal.trim();

    const r = await AdminAuth.fetch('/api/discover/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 'admin-sources');

    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try { const j = await r.json(); detail = j.detail || detail; } catch (e) { /* keep status */ }
      errBox.hidden = false;
      errBox.textContent = detail;
      return;
    }
    _config = await r.json();
    _closeModal();
    Toast.success('Sources config saved', 'Applied on the next refresh — no restart needed.');
    _renderConfig();
  }

  // Auto-load when this admin panel is activated (dropdown route AND the
  // switchTab admin-* re-emit path — both fire adminPanelActivated).
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-sources') load();
  });

  // Delegated actions — rows re-render per load; modal buttons are static.
  Actions.click({
    'admin.sources.open':        () => AdminMenu.select('admin-sources'),
    'admin.sources.refresh-one': el => refreshOne(el.dataset.source, el),
    'admin.sources.edit':        () => showEdit(),
    'admin.sources.save':        () => _submit(),
    'admin.sources.cancel':      () => _closeModal(),
  });

  return { load, refresh, refreshOne, showEdit, _submit, _closeModal };
})();
