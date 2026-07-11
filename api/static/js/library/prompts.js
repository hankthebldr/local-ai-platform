// library/prompts.js — Prompts library panel (roles + templates), the FIRST
// LibraryShell adapter (LB0-U1). Full CRUD + live render preview over
// /api/prompts. Migration is endpoint-and-action-identical: every endpoint
// call, action id (prompts.select/edit/cancel/save/remove/promote/render/new/
// refresh/create-close/create-submit), container id (#prompts-list/#prompts-detail/
// #prompts-detail-label/#prompts-count) and selector from the pre-shell panel
// stays alive; the shell adds the uniform sidebar/subnav/actions grammar on
// top (`.lib-row` added ALONGSIDE the retained `.mcp-row`).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { LibraryWizard } from './wizard.js';
import { TestPane } from './test-pane.js';

export const PromptsLibrary = (function () {
  let _items = [];
  let _editing = false;
  let _metaEditing = false;    // meta sidecar editor (LB2-U1)
  let _ctxTokens = 8192;       // context window the token chip compares against
  let _digest = null;          // persisted prompt digest (LB2-U2) — read-GET only
  let _modelsLoaded = false;   // recommend-rail model datalist, populated lazily
  const DIGEST_PREFIX = 'digest/';

  // Shared taxonomy — keep in lockstep with api/services/prompt_meta.py
  // (one vocabulary across LB2 prompts / LB4 model tags / LB6 task schemas).
  const CATEGORIES = ['code', 'analysis', 'extraction', 'classification',
                      'planning', 'review', 'writing', 'security'];
  const TECHNIQUES = ['few-shot', 'chain-of-thought', 'persona',
                      'structured-output', 'critique', 'guardrail'];
  const CTX_CHOICES = [[4096, '4k'], [8192, '8k'], [32768, '32k'], [131072, '128k']];

  function _headers() { return LibraryShell.headers('prompt'); }
  function _key(p) { return `${p.kind}/${p.id}`; }
  function _selected() { return (LibraryShell.state('prompt') || {}).selected; }
  function _current() { return _items.find(p => _key(p) === _selected()) || null; }

  // ── LibraryShell adapter ────────────────────────────────────────────
  // auth 'optional': reads are open server-side; AdminAuth headers merge in
  // when present. Deliberately NOT 'admin' — prompts must not be over-gated.
  const adapter = LibraryShell.register({
    kind: 'prompt',
    tabId: 'prompts',
    countBadgeId: 'prompts-count',
    listElId: 'prompts-list',
    detailElId: 'prompts-detail',
    labelElId: 'prompts-detail-label',
    auth: 'optional',
    selectAction: 'prompts.select',   // legacy row action id kept alive
    rowKeyAttr: 'data-key',
    groupClass: 'prompts-group-label',
    emptyText: 'No prompts. Click "+ New" to add a role or template.',
    emptyDetailLabel: '// SELECT A PROMPT',
    emptyDetailText: 'Select a role or template on the left to view, edit, or render it.',
    title: 'Prompts',

    async load() {
      const r = await LibraryShell.fetch('prompt', '/api/prompts');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _items = r.data || [];
      // Discovered tab data: the PERSISTED digest + staleness stamp. This is
      // a local read-GET — the server never fetches on it (privacy: egress
      // only rides the operator's ⟳ Digest button). Fail-soft: a dead route
      // leaves the Installed experience untouched.
      try {
        const d = await LibraryShell.fetch('prompt', '/api/prompts/discover');
        if (d.ok && d.data && Array.isArray(d.data.records)) _digest = d.data;
      } catch (_) { /* digest stays as-was */ }
    },

    list() {
      // Group roles, templates, then hooks (LB2-U1) — role/template order and
      // labels identical to the pre-shell panel.
      const groups = [['role', 'Roles'], ['template', 'Templates'], ['hook', 'Hooks']];
      const rows = [];
      groups.forEach(([kind, label]) => {
        _items.filter(p => p.kind === kind).forEach(p => {
          let meta;
          if (kind === 'hook') {
            // A hook is a configured builtin preset — stage is the signal.
            meta = p.always_on ? 'hook · always-on' : `hook · ${p.stage || '?'}`;
          } else {
            const vars = (p.variables || []).length
              ? `${p.variables.length} var${p.variables.length > 1 ? 's' : ''}` : 'no vars';
            meta = `${kind} · ${vars}`;
          }
          rows.push({
            id: _key(p),
            title: p.name || p.id,
            meta,
            group: label,
            provenance: p.provenance,          // 'oob'|'user' — layer-derived (LB0-U3)
            blocks: ['context'],               // prompts feed the context building block
            tags: p.tags || [],
            badges: kind === 'hook' && p.target ? [{ label: p.target }] : [],
            dot: { cls: `prompts-kind-dot ${kind}`, title: kind },
          });
        });
      });
      return rows;
    },

    // Discovered sidebar tab (LB2-U2): rows from the persisted digest with
    // diff badges — digest content_sha vs installed sidecar provenance sha.
    discovered() {
      const recs = (_digest && _digest.records) || [];
      const diff = (_digest && _digest.diff) || {};
      const installed = {};   // digest record id -> installed source_sha
      _items.forEach(p => { if (p.source_id) installed[p.source_id] = p.source_sha; });
      return recs.map(rec => {
        const badges = [];
        if (rec.id in installed) {
          badges.push(installed[rec.id] === rec.content_sha
            ? { label: 'installed', cls: 'lib-diff-installed' }
            : { label: 'update', cls: 'lib-diff-update' });
        } else if ((diff.added || []).indexOf(rec.id) !== -1) {
          badges.push({ label: 'new', cls: 'lib-diff-new' });
        } else if ((diff.changed || []).indexOf(rec.id) !== -1) {
          badges.push({ label: 'changed', cls: 'lib-diff-update' });
        }
        if (rec.license) badges.push({ label: rec.license });
        return {
          id: DIGEST_PREFIX + rec.id,
          title: rec.title || rec.id,
          meta: `${rec.subkind || 'prompt'} · ${rec.prompt_kind || 'role'}`,
          group: (rec.source && rec.source.repo) || 'digest',
          tags: rec.tags || [],
          badges,
          blocks: ['context'],
        };
      });
    },

    detail(id) {
      if (id && id.indexOf(DIGEST_PREFIX) === 0) {
        return { sections: { overview: (mountEl) => _renderDigestOverview(mountEl, id) } };
      }
      return { sections: { overview: (mountEl) => _renderOverview(mountEl) } };
    },

    // LB1 prompt TestPane in the shell Test slot — runs render → test-step
    // (labeled model+prompt only). Hooks keep their own HOOK TEST in
    // Overview; digest records must be installed before they can run.
    testPane(id) {
      return (mountEl) => {
        if (id && id.indexOf(DIGEST_PREFIX) === 0) {
          mountEl.innerHTML = '<div class="model-empty">Install this discovered prompt first — the test harness runs installed prompts only.</div>';
          return;
        }
        const p = _current();
        if (p && p.kind === 'hook') {
          mountEl.innerHTML = '<div class="model-empty">Hooks test via the HOOK TEST box in Overview (factory instantiation + validate_output dry-run).</div>';
          return;
        }
        return TestPane.mount('prompt', id, mountEl);
      };
    },

    actions(id) {
      if (id && id.indexOf(DIGEST_PREFIX) === 0) {
        const rec = _digestRecord(id);
        const can = !!(rec && rec.body);
        return [{
          action: 'prompts.install', label: 'Install…', verb: 'install',
          accent: true, enabled: can,
          reason: can ? undefined
            : 'pointer-only record — license does not permit a body copy',
        }];
      }
      if (_editing) {
        return [
          { action: 'prompts.save', label: 'Save', verb: 'edit', accent: true },
          { action: 'prompts.cancel', label: 'Cancel', verb: 'edit' },
        ];
      }
      const p = _current();
      // Custom api/hooks/custom hooks are read-only always-on transparency
      // entries — no verbs (they attach to every bus, not per-step).
      if (p && p.always_on) return [];
      const isOob = !!p && p.provenance === 'oob';
      const isHook = !!p && p.kind === 'hook';
      const acts = [];
      if (isHook) {
        // v1 attach path: paste the preset into workflow YAML (per the
        // shipped workflows/xdm-*.yaml hook blocks). Composer attach is
        // named follow-up #4.
        acts.push({ action: 'prompts.copy-hook-yaml', label: 'Copy hooks: YAML',
                    verb: 'install', accent: true });
      } else {
        acts.push({ action: 'prompts.render', label: '▶ Render preview', verb: 'test', accent: true });
        // Jump to the Test tab — render → POST /api/workflows/test-step
        // (labeled model+prompt only: tools/skills/parsers not exercised).
        acts.push({ action: 'prompts.test-run', label: 'Test', verb: 'test' });
      }
      acts.push(
        { action: 'prompts.edit', label: 'Edit', verb: 'edit' },
        // Physical promote — copies the shipped file into the user layer.
        // Disabled (never hidden) on user-layer items so the verb row is stable.
        { action: 'prompts.promote', label: 'Promote', verb: 'promote',
          enabled: isOob, reason: isOob ? undefined : 'already user-layer' },
        { action: 'prompts.remove', label: 'Delete', verb: 'delete' },
      );
      return acts;
    },
  });

  async function _renderOverview(el) {
    const key = _selected();
    if (!key) return;
    const [kind, ...rest] = key.split('/');
    const id = rest.join('/');
    let p = _current();
    // Fetch the full body on demand (list only carries summaries) unless the
    // cache already holds it (post-save reload merges bodies back in).
    if (!p || p.body == null) {
      const r = await LibraryShell.fetch('prompt',
        `/api/prompts/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
      if (!r.ok) { el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Load failed (${r.status})</div>`; return; }
      p = r.data;
      const idx = _items.findIndex(x => _key(x) === _key(p));
      if (idx >= 0) _items[idx] = p; else _items.push(p);
    }
    const vars = (p.variables || []).length
      ? p.variables.map(v => `<code class="prompts-var">${esc(v)}</code>`).join(' ')
      : '<span style="color:var(--text-muted)">none</span>';
    if (_editing) {
      el.innerHTML = `
        <div class="prompts-meta">
          <code class="prompts-var">${esc(p.kind)}</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
        </div>
        <textarea id="prompts-edit-body" class="prompts-textarea" spellcheck="false">${esc(p.body || '')}</textarea>`;
      return;
    }
    if (p.kind === 'hook') {
      el.innerHTML = _hookOverviewHtml(p);
      return;
    }
    el.innerHTML = `
      <div class="prompts-meta">
        <code class="prompts-var">${esc(p.kind)}</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
        &nbsp;·&nbsp; variables: ${vars}
      </div>
      <pre class="prompts-body">${esc(p.body || '')}</pre>
      ${_metaBoxHtml(p)}
      <div id="prompts-render-out" class="prompts-render" hidden></div>`;
  }

  // ── Classification meta (LB2-U1: sidecar for roles/templates, frontmatter
  //    for hooks) — token-estimate chip vs model context, I/O scoping, tags ──

  function _tokenEstimate(p) {
    const m = p.meta || {};
    if (typeof m.token_estimate === 'number') return m.token_estimate;
    if (typeof p.token_estimate === 'number') return p.token_estimate;
    return Math.ceil(((p.body || '').length) / 3.6);
  }

  function _tokenChipHtml(p) {
    const est = _tokenEstimate(p);
    const ratio = est / _ctxTokens;
    const cls = ratio <= 0.5 ? 'ok' : ratio <= 0.9 ? 'warn' : 'over';
    const opts = CTX_CHOICES.map(([v, label]) =>
      `<option value="${v}" ${v === _ctxTokens ? 'selected' : ''}>${label} ctx</option>`).join('');
    return `<span id="prompts-token-chip" class="prompts-token-chip ${cls}"
        title="approximate — ceil(chars/3.6); red/amber/green vs the selected context window, never a gate">~${est} tok</span>
      vs <select id="prompts-ctx-select" class="prompts-ctx-select" data-action="prompts.ctx-model"
        aria-label="Model context window to compare against">${opts}</select>`;
  }

  function _metaBoxHtml(p) {
    const m = p.meta || {};
    if (_metaEditing) return _metaFormHtml(p, m);
    const chips = []
      .concat((m.tags || p.tags || []).map(t => `<span class="lib-chip">${esc(t)}</span>`))
      .concat(m.category ? [`<span class="lib-badge">${esc(m.category)}</span>`] : [])
      .concat((m.technique || []).map(t => `<span class="lib-badge">${esc(t)}</span>`))
      .concat((m.model_fit || []).map(t => `<span class="lib-badge prompts-fit-badge">${esc(t)}</span>`))
      .join('') || '<span style="color:var(--text-muted)">untagged</span>';
    const kv = [
      ['intended output', m.intended_output || p.intended_output],
      ['input scope', m.input_scope],
      ['output scope', m.output_scope],
    ].filter(([, v]) => v)
      .map(([k, v]) => `<div class="prompts-kv"><span class="prompts-kv-key">${esc(k)}</span>${esc(v)}</div>`)
      .join('');
    return `
      <div class="prompts-meta-box" id="prompts-meta-box">
        <div class="prompts-render-label">META ${_tokenChipHtml(p)}
          <button class="action-btn" style="float:right" data-action="prompts.meta-edit">Edit meta</button>
        </div>
        <div class="prompts-meta-chips">${chips}</div>
        ${kv}
      </div>`;
  }

  function _metaFormHtml(p, m) {
    const catOpts = ['<option value="">—</option>'].concat(CATEGORIES.map(c =>
      `<option value="${c}" ${m.category === c ? 'selected' : ''}>${c}</option>`)).join('');
    const f = (id, label, val, ph) => `
      <label class="admin-modal-label" for="${id}">${label}</label>
      <input id="${id}" type="text" value="${esc(val || '')}" placeholder="${esc(ph || '')}" autocomplete="off">`;
    return `
      <div class="prompts-meta-box editing" id="prompts-meta-box">
        <div class="prompts-render-label">EDIT META</div>
        ${f('prompts-meta-tags', 'Tags (comma-separated)', (m.tags || []).join(', '), 'xql, quality-gate')}
        <label class="admin-modal-label" for="prompts-meta-category">Category</label>
        <select id="prompts-meta-category">${catOpts}</select>
        ${f('prompts-meta-technique', `Technique (${TECHNIQUES.join(' / ')})`, (m.technique || []).join(', '))}
        ${f('prompts-meta-intended', 'Intended output', m.intended_output, 'e.g. Code — "update the readme"')}
        ${f('prompts-meta-model-fit', 'Model fit (role classes or model ids)', (m.model_fit || []).join(', '), 'reasoning, coding')}
        ${f('prompts-meta-input-scope', 'Input scope', m.input_scope, 'what context this expects')}
        ${f('prompts-meta-output-scope', 'Output scope', m.output_scope, 'what downstream consumes')}
        <div style="margin-top:10px;display:flex;gap:6px;justify-content:flex-end">
          <button class="action-btn" data-action="prompts.meta-edit">Cancel</button>
          <button class="action-btn accent" data-action="prompts.meta-save">Save meta</button>
        </div>
      </div>`;
  }

  function _hookOverviewHtml(p) {
    const m = p.meta || {};
    if (p.always_on) {
      return `
        <div class="prompts-meta">
          <code class="prompts-var">hook</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
          <span class="lib-badge">always-on</span>
        </div>
        <p style="color:var(--text-muted);font-size:0.72rem;margin:6px 0">
          Custom hook module from <code>api/hooks/custom/</code> — registers on
          every workflow bus at run time (not per-step). Read-only here.
        </p>
        <pre class="prompts-body">${esc(p.body || '')}</pre>`;
    }
    const cfg = m.config ? JSON.stringify(m.config, null, 2) : '{}';
    const isValidate = m.stage === 'validate_output';
    return `
      <div class="prompts-meta">
        <code class="prompts-var">hook</code> · <code style="color:var(--accent)">${esc(p.id)}</code>
      </div>
      <div class="prompts-kv"><span class="prompts-kv-key">stage</span><code class="prompts-var">${esc(m.stage || '?')}</code></div>
      <div class="prompts-kv"><span class="prompts-kv-key">target builtin</span><code class="prompts-var">${esc(m.target || '?')}</code></div>
      <div class="prompts-kv"><span class="prompts-kv-key">config</span></div>
      <pre class="prompts-body" style="max-height:180px">${esc(cfg)}</pre>
      <pre class="prompts-body">${esc(p.body || '')}</pre>
      ${_metaBoxHtml(p)}
      <div class="prompts-hook-test" id="prompts-hook-test">
        <div class="prompts-render-label">HOOK TEST</div>
        ${isValidate ? `
        <textarea id="prompts-hook-sample" class="prompts-textarea" style="min-height:90px"
          placeholder="Paste sample step output to dry-run through this validate_output hook…" spellcheck="false"></textarea>` : `
        <p style="color:var(--text-muted);font-size:0.7rem;margin:4px 0">
          ${esc(m.stage || 'this')} hooks verify factory instantiation only —
          sample dry-run applies to validate_output hooks.</p>`}
        <button class="action-btn accent" data-action="prompts.hook-test" style="margin-top:6px">Run test</button>
        <div id="prompts-hook-test-out" class="prompts-render" hidden></div>
      </div>`;
  }

  // ── Panel API (signature-identical to the pre-shell module) ─────────
  function load() { return LibraryShell.reload('prompt'); }
  function refresh() { load(); }
  function render() { LibraryShell.renderSidebar('prompt'); }
  function renderDetail() { LibraryShell.renderDetail('prompt'); }

  function select(key) {
    _editing = false;
    _metaEditing = false;
    LibraryShell.select('prompt', key);
  }

  function edit(key) {
    if (key === _selected()) { _editing = true; renderDetail(); }
  }
  function cancel() { _editing = false; renderDetail(); }

  async function save(key) {
    const p = _current();
    const ta = document.getElementById('prompts-edit-body');
    if (!p || !ta) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}`, {
        init: { method: 'PATCH', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({ body: ta.value }) }
      });
      if (!r.ok) { Toast.show(`Save failed (${r.status})`, 'error'); return; }
      _editing = false;
      Toast.show('Prompt saved', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  async function remove(key) {
    const p = _current();
    if (!p) return;
    const ok = await Confirm.ask({
      title: 'Delete prompt',
      body: `Delete ${p.kind} "${p.id}"? This removes the file on disk.`,
      okLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}`, {
        init: { method: 'DELETE', headers: _headers() }
      });
      if (!r.ok) {
        // 403 on pure-oob carries an explanatory detail — surface it.
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Delete failed: ${detail}`, 'error'); return;
      }
      LibraryShell.select('prompt', null);
      Toast.show('Prompt deleted', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  async function promote(key) {
    // Physical promote (LB0-U3): POST copies the oob file into the user
    // layer server-side. Master-key gated; retries:0 — a retry after a
    // slow success would surface a spurious 409.
    const p = _current();
    if (!p) return;
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}/promote`, {
        retries: 0,
        init: { method: 'POST', headers: _headers() }
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Promote failed: ${detail}`, 'error'); return;
      }
      Toast.show('Promoted to user layer', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  async function renderPreview(key) {
    const p = _current();
    const out = document.getElementById('prompts-render-out');
    if (!p || !out) return;
    out.hidden = false;
    out.innerHTML = '<div class="model-empty">Rendering…</div>';
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}/render`, {
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({ task: 'Draft a concise plan for the given objective.' }) }
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(detail)}</div>`;
        return;
      }
      const d = r.data;
      out.innerHTML = `
        <div class="prompts-render-label">SYSTEM</div>
        <pre class="prompts-body">${esc(d.system || '')}</pre>
        <div class="prompts-render-label">USER</div>
        <pre class="prompts-body">${esc(d.user || '')}</pre>`;
    } catch (e) {
      out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  // ── LB2-U1: meta editor, hook test, copy-hooks-YAML ──────────────────

  function metaEditToggle() {
    _metaEditing = !_metaEditing;
    LibraryShell.refreshSection('prompt', 'overview');
  }

  function _csv(id) {
    const v = (document.getElementById(id) || {}).value || '';
    const list = v.split(',').map(s => s.trim()).filter(Boolean);
    return list.length ? list : [];
  }

  async function metaSave() {
    const p = _current();
    if (!p) return;
    const payload = {
      tags: _csv('prompts-meta-tags'),
      category: (document.getElementById('prompts-meta-category') || {}).value || null,
      technique: _csv('prompts-meta-technique'),
      intended_output: (document.getElementById('prompts-meta-intended') || {}).value || null,
      model_fit: _csv('prompts-meta-model-fit'),
      input_scope: (document.getElementById('prompts-meta-input-scope') || {}).value || null,
      output_scope: (document.getElementById('prompts-meta-output-scope') || {}).value || null,
    };
    try {
      const r = await Net.call(`/api/prompts/${encodeURIComponent(p.kind)}/${encodeURIComponent(p.id)}/meta`, {
        retries: 0,
        init: { method: 'PATCH', headers: { 'Content-Type': 'application/json', ..._headers() },
                body: JSON.stringify(payload) },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Meta save failed: ${detail}`, 'error'); return;
      }
      p.meta = (r.data && r.data.meta) || payload;
      _metaEditing = false;
      Toast.show('Meta saved', 'success');
      await load();
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  function _ctxChange(el) {
    _ctxTokens = Number(el.value) || 8192;
    const p = _current();
    const chip = document.getElementById('prompts-token-chip');
    if (!p || !chip) return;
    const est = _tokenEstimate(p);
    const ratio = est / _ctxTokens;
    chip.classList.remove('ok', 'warn', 'over');
    chip.classList.add(ratio <= 0.5 ? 'ok' : ratio <= 0.9 ? 'warn' : 'over');
  }

  async function hookTest() {
    const p = _current();
    const out = document.getElementById('prompts-hook-test-out');
    if (!p || p.kind !== 'hook' || !out) return;
    const sample = (document.getElementById('prompts-hook-sample') || {}).value || '';
    out.hidden = false;
    out.innerHTML = '<div class="model-empty">Testing…</div>';
    try {
      const r = await Net.call(`/api/prompts/hook/${encodeURIComponent(p.id)}/test`, {
        retries: 0,
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() },
                body: JSON.stringify({ sample_output: sample || null }) },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(detail)}</div>`;
        return;
      }
      const d = r.data || {};
      const dry = d.dry_run
        ? `<div class="prompts-kv"><span class="prompts-kv-key">dry-run action</span>
             <code class="prompts-var ${d.dry_run.action === 'continue' ? '' : 'prompts-hook-fail'}">${esc(d.dry_run.action || '')}</code></div>
           ${d.dry_run.feedback ? `<pre class="prompts-body" style="max-height:140px">${esc(d.dry_run.feedback)}</pre>` : ''}`
        : '<div style="color:var(--text-muted);font-size:0.7rem">Factory instantiation OK — no dry-run (paste a sample for validate_output hooks).</div>';
      out.innerHTML = `
        <div class="prompts-render-label">RESULT — ${esc(d.target || '')} @ ${esc(d.stage || '')}</div>
        ${dry}`;
    } catch (e) {
      out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function _yamlVal(v, indent) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      const entries = Object.entries(v);
      if (!entries.length) return ' {}';
      return '\n' + entries.map(([k, val]) =>
        `${' '.repeat(indent)}${k}:${_yamlVal(val, indent + 2)}`).join('\n');
    }
    return ' ' + JSON.stringify(v === undefined ? null : v);  // JSON scalars/arrays are valid YAML
  }

  function copyHookYaml() {
    const p = _current();
    if (!p || p.kind !== 'hook' || p.always_on) return;
    const m = p.meta || {};
    const yaml = 'hooks:\n' +
      `  ${m.stage || 'validate_output'}:\n` +
      `    - name: ${m.target || ''}\n` +
      `      config:${_yamlVal(m.config || {}, 8)}\n`;
    const done = () => Toast.show('Hook YAML copied — paste into a workflow step\'s hooks block', 'success');
    const fail = () => Toast.show('Copy failed — clipboard unavailable', 'error');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(yaml).then(done, fail);
    } else { fail(); }
  }

  // ── LB2-U2: discovery (digest read + operator refresh + wizard install)
  //    and the hybrid recommend rail (deterministic + Ask Enclave) ────────

  function _digestRecord(rowId) {
    const rid = (rowId || '').slice(DIGEST_PREFIX.length);
    return (((_digest || {}).records) || []).find(r => r.id === rid) || null;
  }

  function _staleness() {
    const at = _digest && _digest.fetched_at;
    if (!at) return 'never fetched';
    const mins = Math.max(0, Math.round((Date.now() / 1000 - at) / 60));
    if (mins < 60) return `fetched ${mins}m ago`;
    if (mins < 60 * 48) return `fetched ${Math.round(mins / 60)}h ago`;
    return `fetched ${Math.round(mins / 1440)}d ago`;
  }

  function _renderDigestOverview(el, rowId) {
    const rec = _digestRecord(rowId);
    if (!rec) { el.innerHTML = '<div class="model-empty">Record not in the persisted digest — refresh it.</div>'; return; }
    const src = rec.source || {};
    const kv = [
      ['source', `${src.repo || '?'} · ${src.path || ''}`],
      ['pinned sha', (src.ref || '').slice(0, 12)],
      ['license', rec.license || 'unknown'],
      ['provenance', src.provenance || ''],
      ['installs as', rec.prompt_kind || 'role'],
      ['digest', _staleness()],
    ].filter(([, v]) => v)
      .map(([k, v]) => `<div class="prompts-kv"><span class="prompts-kv-key">${esc(k)}</span>${esc(String(v))}</div>`)
      .join('');
    const tags = (rec.tags || []).map(t => `<span class="lib-chip">${esc(t)}</span>`).join('');
    const body = rec.body
      ? `<div class="prompts-render-label">BODY (~${esc(String(rec.token_estimate || 0))} tok)</div>
         <pre class="prompts-body" style="max-height:260px">${esc(rec.body.slice(0, 4000))}${rec.body.length > 4000 ? '\n…' : ''}</pre>`
      : `<p style="color:var(--text-muted);font-size:0.72rem;margin:8px 0">
           Pointer-only record — the license does not permit a body copy.
           ${src.url ? `Open the source: <a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.url)}</a>` : ''}
         </p>`;
    el.innerHTML = `
      <div class="prompts-meta"><code class="prompts-var">${esc(rec.subkind || 'prompt')}</code>
        · <code style="color:var(--accent)">${esc(rec.id)}</code></div>
      ${tags ? `<div class="prompts-meta-chips">${tags}</div>` : ''}
      ${kv}${body}`;
  }

  async function discoverRefresh() {
    // The ONLY egress path — a visible operator button firing a master-key
    // gated POST against the allowlisted sources (Admin ▸ Sources governs).
    Toast.show('Refreshing prompt digest…', 'info');
    try {
      const r = await Net.call('/api/prompts/discover/refresh', {
        retries: 0,
        init: { method: 'POST', headers: _headers() },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Digest refresh failed: ${detail}`, 'error'); return;
      }
      _digest = r.data;
      const d = (r.data && r.data.diff) || {};
      Toast.show(`Digest refreshed — +${(d.added || []).length} ~${(d.changed || []).length} −${(d.removed || []).length}`, 'success');
      const st = LibraryShell.state('prompt');
      if (st) { st.side = 'discovered'; st.chromeBuilt = false; }
      LibraryShell.renderSidebar('prompt');
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  function installWizard() {
    const key = _selected();
    const rec = key ? _digestRecord(key) : null;
    if (!rec) return;
    if (!rec.body) {
      Toast.show('Pointer-only record — license does not permit a body copy', 'error');
      return;
    }
    const src = rec.source || {};
    LibraryWizard.open({
      title: 'Install prompt',
      submitLabel: 'Install',
      steps: {
        source: (el) => {
          el.innerHTML = `
            <div class="admin-modal-sub">From the persisted digest (${esc(_staleness())}).</div>
            <div class="prompts-kv"><span class="prompts-kv-key">title</span>${esc(rec.title || rec.id)}</div>
            <div class="prompts-kv"><span class="prompts-kv-key">source</span>${esc(src.repo || '')} · ${esc(src.path || '')}</div>
            <div class="prompts-kv"><span class="prompts-kv-key">pinned sha</span><code class="prompts-var">${esc((src.ref || '').slice(0, 12))}</code></div>
            <div class="prompts-kv"><span class="prompts-kv-key">license</span>${esc(rec.license || 'unknown')}</div>`;
        },
        configure: (el, state) => {
          el.innerHTML = `
            <div class="admin-modal-sub">Installs as a user-layer <b>${esc(rec.prompt_kind || 'role')}</b>; provenance sha lands in the sidecar.</div>
            <label class="admin-modal-label" for="prompts-install-id">Target id</label>
            <input id="prompts-install-id" type="text" data-wiz-key="target_id"
              autocomplete="off" placeholder="${esc(rec.id)}">`;
          const inp = el.querySelector('#prompts-install-id');
          if (inp) inp.value = state.values.target_id || rec.id;
        },
      },
      validate: (stepId, state) => {
        if (stepId !== 'configure') return true;
        const tid = (state.values.target_id || '').trim();
        return (!tid || /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(tid))
          ? true : 'Invalid id — use alnum, _ or -, max 80 chars';
      },
      onSubmit: async (state, { post }) => {
        const tid = (state.values.target_id || '').trim() || null;
        const r = await post(
          `/api/prompts/discover/${encodeURIComponent(rec.id)}/install`,
          { target_id: tid }, _headers());
        if (!r.ok) {
          const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
          return { ok: false, detail };
        }
        await load();
        return { ok: true, message: `Installed as ${rec.prompt_kind || 'role'} '${(r.data && r.data.id) || tid || rec.id}'` };
      },
    });
  }

  function testRun() {
    // Test tab = the LB1 prompt TestPane (render → test-step, labeled
    // model+prompt only). The action just navigates the shell subnav.
    if (_selected()) LibraryShell.setSubnav('prompt', 'test');
  }

  async function _fillModelOptions() {
    if (_modelsLoaded) return;
    _modelsLoaded = true;
    const dl = document.getElementById('prompts-model-options');
    if (!dl) return;
    try {
      const r = await Net.call('/api/models');
      const opts = ((r.data && r.data.options) || [])
        .map(o => `<option value="${esc(o.model || o.value || '')}"></option>`).join('');
      if (r.ok && opts) dl.innerHTML = opts;
    } catch (_) { /* datalist stays empty — plain text entry still works */ }
  }

  function _recInputs() {
    return {
      task: (document.getElementById('prompts-recommend-task') || {}).value || '',
      model: (document.getElementById('prompts-recommend-model') || {}).value || '',
    };
  }

  function _factorTitle(f) {
    return `tags ${f.task_tags.score}${f.task_tags.matched.length ? ` (${f.task_tags.matched.join(', ')})` : ''}`
      + ` · model-fit ${f.model_fit.score}${f.model_fit.matched.length ? ` (${f.model_fit.matched.join(', ')})` : ''}`
      + ` · size-fit ${f.size_fit.score} (~${f.size_fit.token_estimate} tok${f.size_fit.context_tokens ? ` vs ${f.size_fit.context_tokens}` : ''})`;
  }

  function _renderRecRows(out, items, note) {
    out.innerHTML = (note ? `<div class="prompts-rec-note">${esc(note)}</div>` : '') +
      (items.map(it => `
        <button type="button" class="btn-unstyled prompts-rec-row" data-action="prompts.select"
          data-key="${esc(`${it.kind}/${it.id}`)}" ${it.title ? `title="${esc(it.title)}"` : ''}>
          <span class="prompts-rec-score">${esc(String(it.score))}</span>
          <span class="prompts-rec-name">${esc(it.name || it.id)}</span>
          ${it.reason ? `<span class="prompts-rec-reason">${esc(it.reason)}</span>` : ''}
        </button>`).join('') || '<div class="model-empty">No hits.</div>');
  }

  async function recommend() {
    const out = document.getElementById('prompts-recommend-out');
    if (!out) return;
    _fillModelOptions();
    const { task, model } = _recInputs();
    out.innerHTML = '<div class="model-empty">Scoring…</div>';
    try {
      const qs = `task=${encodeURIComponent(task)}${model ? `&model=${encodeURIComponent(model)}` : ''}`;
      const r = await Net.call(`/api/prompts/recommend?${qs}`);
      if (!r.ok) { out.innerHTML = `<div class="model-empty" style="color:var(--danger)">HTTP ${r.status}</div>`; return; }
      const items = ((r.data && r.data.results) || []).map(x => ({
        id: x.id, kind: x.kind, name: x.name, score: x.score,
        title: _factorTitle(x.factors),
      }));
      _renderRecRows(out, items, 'deterministic scorer — hover a row for the per-factor breakdown');
    } catch (e) {
      out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  async function askEnclave() {
    const out = document.getElementById('prompts-recommend-out');
    if (!out) return;
    const { task, model } = _recInputs();
    out.innerHTML = '<div class="model-empty">Asking the local model… (nothing leaves the box)</div>';
    try {
      const r = await Net.call('/api/prompts/recommend/explain', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ task, model: model || null }),
        },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(detail)}</div>`;
        return;
      }
      const d = r.data || {};
      const note = d.explained
        ? `Ask Enclave — ${d.llm_model || 'local model'} (local only)`
        : 'local model unavailable — deterministic ranking';
      _renderRecRows(out, d.items || [], note);
    } catch (e) {
      out.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function showCreate() {
    const modal = document.getElementById('prompts-create-modal');
    if (modal) {
      modal.hidden = false;
      const idf = document.getElementById('prompts-create-id');
      if (idf) idf.value = '';
      const bodyf = document.getElementById('prompts-create-body');
      if (bodyf) bodyf.value = '';
    }
  }
  function closeCreate() {
    const modal = document.getElementById('prompts-create-modal');
    if (modal) modal.hidden = true;
  }
  async function submitCreate() {
    const kind = (document.getElementById('prompts-create-kind') || {}).value || 'role';
    const id = (document.getElementById('prompts-create-id') || {}).value || '';
    const body = (document.getElementById('prompts-create-body') || {}).value || '';
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(id)) {
      Toast.show('Invalid id — use alnum, _ or -, max 80 chars', 'error'); return;
    }
    try {
      const r = await Net.call('/api/prompts', {
        init: { method: 'POST', headers: { 'Content-Type': 'application/json', ..._headers() }, body: JSON.stringify({ id, kind, body }) }
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : `HTTP ${r.status}`;
        Toast.show(`Create failed: ${detail}`, 'error'); return;
      }
      closeCreate();
      Toast.show('Prompt created', 'success');
      await load();
      LibraryShell.select('prompt', `${kind}/${id}`);
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  // Legacy action ids — aliases over the shell-driven flows (migration
  // contract: old ids stay registered and behavior-identical).
  Actions.click({
    'prompts.select': el => select(el.dataset.key),
    'prompts.edit':   el => edit(el.dataset.key),
    'prompts.cancel': () => cancel(),
    'prompts.save':   el => save(el.dataset.key),
    'prompts.remove': el => remove(el.dataset.key),
    'prompts.promote': el => promote(el.dataset.key),
    'prompts.render': el => renderPreview(el.dataset.key),
    'prompts.new':    () => showCreate(),
    'prompts.refresh': () => refresh(),
    'prompts.create-close': () => closeCreate(),
    'prompts.create-submit': () => submitCreate(),
    // LB2-U1 — meta editor, hook test pane, copy-hooks-YAML.
    'prompts.meta-edit': () => metaEditToggle(),
    'prompts.meta-save': () => metaSave(),
    'prompts.hook-test': () => hookTest(),
    'prompts.copy-hook-yaml': () => copyHookYaml(),
    // LB2-U2 — discovery + hybrid recommender.
    'prompts.tab': el => {   // alias over the shell's Installed|Discovered switch
      const st = LibraryShell.state('prompt');
      if (!st) return;
      st.side = el.dataset.side === 'discovered' ? 'discovered' : 'installed';
      st.chromeBuilt = false;
      LibraryShell.renderSidebar('prompt');
    },
    'prompts.discover-refresh': () => discoverRefresh(),
    'prompts.install': () => installWizard(),
    'prompts.test-run': () => testRun(),
    'prompts.recommend': () => recommend(),
    'prompts.ask-enclave': () => askEnclave(),
  });
  Actions.change({
    'prompts.ctx-model': el => _ctxChange(el),
  });

  return { load, refresh, render, select, edit, cancel, save, remove, promote,
           renderPreview, showCreate, closeCreate, submitCreate,
           metaEditToggle, metaSave, hookTest, copyHookYaml,
           discoverRefresh, installWizard, testRun, recommend, askEnclave,
           adapter };
})();
