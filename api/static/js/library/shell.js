// library/shell.js — LibraryShell: the uniform Library master-detail grammar (LB0-U1).
//
// One in-tab shell for every Library kind (prompt, mcp, then skill/model/
// plugin/task as their tracks land). A kind registers an ADAPTER; the shell
// owns sidebar state (Installed|Discovered tabs, client-side filter,
// collapsible groups, `.lib-row` rows — added ALONGSIDE the retained
// `.mcp-row` class, never renaming), the detail pane (uniform subnav
// Overview/Config/Files/Examples/Test/Relations with absent sections hidden),
// and the actions row (verbs install/test/edit/promote/delete — no `version`
// verb in v1; version renders as row/badge metadata only).
//
// Adapter contract (per-kind, implemented inside the kind's module):
//   { kind, tabId, countBadgeId,
//     listElId?, detailElId?, labelElId?,   // adopt existing panel DOM (Prompts/MCP)
//     selectAction?, rowKeyAttr?, rowClass?, // legacy row action id / row class kept alive
//     auth: 'none'|'optional'|'admin',      // enforced in the shell's fetch paths
//     load(): Promise,                      // refresh backing data (uses LibraryShell.fetch)
//     list(): [{id, title, meta, group, status?, provenance?:'oob'|'user', blocks?:[],
//               tags?:[], icon?, chips?:[{label,cls}], badges?:[{label,cls}],
//               dot?:{cls,title}}],
//     discovered?(): rows,                  // Discovered sidebar tab (hidden when absent)
//     renderRowExtras?(item): Node|null,    // escape hatch beyond the fields above
//     detail(id): {sections:{overview,…}},  // value: html string | Node | async (mountEl)=>…
//                                           // fns are invoked on FIRST subnav activation
//     sectionOrder?: [...], sectionLabels?: {key: label},  // kind-specific
//                                           // subnav sections (LB4 models)
//     actions(id): [{action?, label, verb, enabled?, reason?, danger?, data?}],
//     testPane?(id): renderFn,              // Test tab slot — hidden when absent (LB1 fills)
//     onAction?(verb, id, el),              // generic lib.action dispatcher target
//     onSelect?(id) }
//
// No inline on*= handlers, no new window globals: all wiring rides the
// delegated Actions registry (lib.* action ids below); cross-module access
// goes through ES-module imports (modules are singletons, so a dynamic
// import in tests resolves to this same instance).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Confirm, ErrorPanel, Skeleton } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

export const LibraryShell = (function () {
  // Fixed subnav order — absent sections are simply not rendered.
  const SECTION_ORDER = ['overview', 'config', 'files', 'examples', 'test', 'relations'];
  const SECTION_LABELS = {
    overview: 'Overview', config: 'Config', files: 'Files',
    examples: 'Examples', test: 'Test', relations: 'Relations',
  };
  // v1 verb enum — deliberately NO 'version' verb (version is display metadata;
  // history/rollback is a named follow-up).
  const VERBS = ['install', 'test', 'edit', 'promote', 'delete'];

  const _adapters = Object.create(null);
  const _state = Object.create(null);

  function register(adapter) {
    if (!adapter || !adapter.kind) throw new Error('LibraryShell.register: adapter.kind required');
    _adapters[adapter.kind] = adapter;
    _state[adapter.kind] = {
      side: 'installed',        // 'installed' | 'discovered'
      filter: '',
      collapsed: Object.create(null),
      selected: null,
      subnav: 'overview',
      rendered: Object.create(null),  // section id -> true once its lazy fn ran
      loadedOnce: false,
      loading: null,            // in-flight reload promise (dedupe)
      chromeBuilt: false,
    };
    return adapter;
  }

  function adapter(kind) { return _adapters[kind] || null; }
  function state(kind) { return _state[kind] || null; }

  // ── Auth-tier enforcement (the shell's fetch paths) ─────────────────
  // none     → plain Net.call, no auth headers.
  // optional → AdminAuth headers merged in when available (never a wall).
  // admin    → AdminAuth.isSignedIn()/renderLock hard gate + AdminAuth.fetch.
  function headers(kind) {
    const a = _adapters[kind];
    if (!a || a.auth === 'none') return {};
    return (window.AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }

  function guard(kind) {
    const a = _adapters[kind];
    if (a && a.auth === 'admin' && window.AdminAuth && !AdminAuth.isSignedIn()) {
      AdminAuth.renderLock(a.lockPanelId || a.tabId);
      return false;
    }
    return true;
  }

  async function fetch(kind, url, opts) {
    const a = _adapters[kind] || {};
    opts = opts || {};
    if (a.auth === 'admin' && window.AdminAuth && AdminAuth.fetch) {
      // AdminAuth.fetch: raw Response + 401-key-clearing + relock semantics.
      const init = Object.assign({}, opts.init || {});
      const r = await AdminAuth.fetch(url, init, a.lockPanelId || a.tabId);
      let data = null;
      try { data = await r.clone().json(); } catch (_) { try { data = await r.text(); } catch (_) {} }
      return { ok: r.ok, status: r.status, data };
    }
    const init = Object.assign({}, opts.init || {});
    init.headers = Object.assign({}, init.headers || {}, headers(kind));
    return Net.call(url, Object.assign({}, opts, { init }));
  }

  // ── Element resolution ───────────────────────────────────────────────
  function _els(kind) {
    const a = _adapters[kind];
    return {
      list: a.listElId ? document.getElementById(a.listElId) : null,
      detail: a.detailElId ? document.getElementById(a.detailElId) : null,
      label: a.labelElId ? document.getElementById(a.labelElId) : null,
    };
  }

  // ── Mount (generic single-container skeleton, plugins-layout grammar) ─
  function mount(kind, containerId) {
    const a = _adapters[kind];
    const host = document.getElementById(containerId);
    if (!a || !host) return Promise.resolve(false);
    const p = `lib-${kind}`;
    host.innerHTML = `
      <div class="plugins-layout lib-shell">
        <div class="panel plugins-list-panel">
          <span class="corner-tr"></span><span class="corner-bl"></span>
          <div class="panel-label">// ${esc((a.title || kind).toUpperCase())}
            <span style="float:right">
              <button class="action-btn" data-action="lib.refresh" data-kind="${esc(kind)}">Refresh</button>
            </span>
          </div>
          <div id="${p}-list" style="margin-top:10px;font-size:0.78rem"></div>
        </div>
        <div class="panel plugins-detail-panel">
          <span class="corner-tr"></span><span class="corner-bl"></span>
          <div class="panel-label" id="${p}-detail-label">// SELECT</div>
          <div id="${p}-detail" style="margin-top:10px;color:var(--text-muted);font-size:0.78rem"></div>
        </div>
      </div>`;
    a.listElId = `${p}-list`;
    a.detailElId = `${p}-detail`;
    a.labelElId = `${p}-detail-label`;
    _state[kind].chromeBuilt = false;
    return reload(kind);
  }

  // ── Load + render ─────────────────────────────────────────────────────
  async function reload(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    if (!a || !st) return;
    if (st.loading) return st.loading;           // dedupe concurrent loads
    if (!guard(kind)) return;
    const els = _els(kind);
    if (!st.loadedOnce && els.list) {
      const rowsEl = els.list.querySelector('.lib-rows');
      Skeleton.fill(rowsEl || els.list, 3);
    }
    st.loading = (async () => {
      try {
        if (a.load) await a.load();
        st.loadedOnce = true;
        renderSidebar(kind);
        _updateCount(kind);
        renderDetail(kind);
      } catch (e) {
        const host = els.list && (els.list.querySelector('.lib-rows') || els.list);
        if (host) ErrorPanel.render(host, { title: 'Load failed', detail: e.message, retry: () => reload(kind) });
      } finally {
        st.loading = null;
      }
    })();
    return st.loading;
  }

  function _updateCount(kind) {
    const a = _adapters[kind];
    if (!a || !a.countBadgeId) return;
    const el = document.getElementById(a.countBadgeId);
    if (!el) return;
    let n = 0;
    try { n = (a.list() || []).length; } catch (_) { n = 0; }
    el.textContent = n ? String(n) : '';
  }

  // ── Sidebar ───────────────────────────────────────────────────────────
  function _sidebarChrome(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    const hasDiscovered = typeof a.discovered === 'function';
    const tabs = hasDiscovered ? `
      <div class="lib-side-tabs" role="tablist">
        <button type="button" class="lib-side-tab ${st.side === 'installed' ? 'active' : ''}" role="tab"
          aria-selected="${st.side === 'installed'}" data-action="lib.sidebar-tab" data-kind="${esc(kind)}" data-side="installed">Installed</button>
        <button type="button" class="lib-side-tab ${st.side === 'discovered' ? 'active' : ''}" role="tab"
          aria-selected="${st.side === 'discovered'}" data-action="lib.sidebar-tab" data-kind="${esc(kind)}" data-side="discovered">Discovered</button>
      </div>` : '';
    return `${tabs}
      <input type="search" class="lib-filter" data-action="lib.filter" data-kind="${esc(kind)}"
        placeholder="filter…" aria-label="Filter ${esc(kind)} list">
      <div class="lib-rows"></div>`;
  }

  function renderSidebar(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    const els = _els(kind);
    if (!a || !els.list) return;
    if (!st.chromeBuilt || !els.list.querySelector('.lib-rows')) {
      els.list.innerHTML = _sidebarChrome(kind);
      st.chromeBuilt = true;
    }
    // filter value set via DOM (never interpolated into markup); on rebuilds
    // this restores it, on row-only re-renders the live input stays untouched
    const inp = els.list.querySelector('.lib-filter');
    if (inp && inp.value !== st.filter) inp.value = st.filter;
    renderRows(kind);
  }

  function _matchesFilter(item, q) {
    if (!q) return true;
    const hay = [item.title, item.id, item.meta, (item.tags || []).join(' ')]
      .filter(Boolean).join(' ').toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function renderRows(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    const els = _els(kind);
    const rowsEl = els.list && els.list.querySelector('.lib-rows');
    if (!a || !rowsEl) return;
    let items = [];
    try {
      items = (st.side === 'discovered' && a.discovered) ? (a.discovered() || []) : (a.list() || []);
    } catch (_) { items = []; }
    const q = st.filter.trim().toLowerCase();
    items = items.filter(it => _matchesFilter(it, q));
    rowsEl.textContent = '';
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'model-empty';
      empty.textContent = q ? 'No matches.' : (st.side === 'discovered'
        ? (a.emptyDiscoveredText || 'Nothing discovered yet.')
        : (a.emptyText || 'Nothing here yet.'));
      rowsEl.appendChild(empty);
      return;
    }
    // Group by item.group preserving first-seen order; '' group renders flat.
    const order = [];
    const byGroup = Object.create(null);
    items.forEach(it => {
      const g = it.group || '';
      if (!(g in byGroup)) { byGroup[g] = []; order.push(g); }
      byGroup[g].push(it);
    });
    order.forEach(g => {
      let target = rowsEl;
      if (g) {
        const wrap = document.createElement('div');
        wrap.className = 'lib-group' + (st.collapsed[g] ? ' collapsed' : '');
        const head = document.createElement('button');
        head.type = 'button';
        head.className = `lib-group-label ${a.groupClass || ''}`.trim();
        head.dataset.action = 'lib.group-toggle';
        head.dataset.kind = kind;
        head.dataset.group = g;
        head.setAttribute('aria-expanded', String(!st.collapsed[g]));
        head.innerHTML = `<span class="lib-caret">${st.collapsed[g] ? '▸' : '▾'}</span>${esc(g)}`;
        wrap.appendChild(head);
        const inner = document.createElement('div');
        inner.className = 'lib-group-rows';
        wrap.appendChild(inner);
        rowsEl.appendChild(wrap);
        target = inner;
      }
      byGroup[g].forEach(it => target.appendChild(_buildRow(a, it, st)));
    });
  }

  function _chipHtml(c, cls) {
    return `<span class="${cls} ${esc(c.cls || '')}">${esc(c.label)}</span>`;
  }

  function _buildRow(a, item, st) {
    const btn = document.createElement('button');
    btn.type = 'button';
    // .mcp-row RETAINED (pinned by pre-shell tests/CSS); .lib-row added
    // alongside. adapter.rowClass lets a migrating kind keep ITS legacy row
    // class alive too (plugins: .plugin-card selectors, LB5-U1 only-add).
    btn.className = `btn-unstyled mcp-row lib-row${a.rowClass ? ' ' + a.rowClass : ''}${st.selected === item.id ? ' selected' : ''}`;
    btn.style.width = '100%';
    btn.setAttribute('aria-pressed', String(st.selected === item.id));
    btn.dataset.action = a.selectAction || 'lib.select';
    btn.dataset.kind = a.kind;
    btn.dataset.id = item.id;
    if (a.rowKeyAttr === 'data-key') btn.dataset.key = item.id;

    let iconHtml = '';
    if (item.icon && window.AgentIcons) {
      const tone = AgentIcons.tone(item.icon) || 'accent';
      iconHtml = `<span class="admin-card-icon admin-card-icon-sm tone-${esc(tone)}">${AgentIcons.svg(item.icon)}</span>`;
    }
    const dotHtml = item.dot
      ? `<span class="lib-dot ${esc(item.dot.cls || '')}" title="${esc(item.dot.title || '')}"></span>` : '';
    const chips = (item.chips || []).map(c => _chipHtml(c, 'lib-chip')).join('');
    const badges = (item.badges || []).map(b => _chipHtml(b, 'lib-badge')).join('');
    const status = item.status ? `<span class="lib-status">${esc(item.status)}</span>` : '';
    const prov = item.provenance
      ? `<span class="lib-prov-chip prov-${esc(item.provenance)}">${esc(item.provenance)}</span>` : '';
    const blocks = (item.blocks && item.blocks.length)
      ? `<span class="lib-blocks" title="building blocks: ${esc(item.blocks.join(', '))}">` +
        ['model', 'context', 'memory', 'tools'].map(b =>
          `<span class="lib-block-dot ${item.blocks.indexOf(b) !== -1 ? 'on' : ''}" data-block="${b}"></span>`).join('') +
        '</span>'
      : '';
    btn.innerHTML = `${iconHtml}${dotHtml}
      <div class="lib-row-main" style="flex:1;min-width:0">
        <div class="mcp-row-title lib-row-title">${esc(item.title)}${chips}</div>
        <div class="mcp-row-meta lib-row-meta">${esc(item.meta || '')}${status}${badges}</div>
      </div>${prov}${blocks}`;
    if (a.renderRowExtras) {
      const extra = a.renderRowExtras(item);
      if (extra) btn.appendChild(extra);
    }
    return btn;
  }

  // ── Selection + detail ────────────────────────────────────────────────
  function select(kind, id) {
    const st = _state[kind];
    if (!st) return;
    st.selected = id;
    st.subnav = 'overview';
    renderRows(kind);
    renderDetail(kind);
    const a = _adapters[kind];
    if (a && a.onSelect && id) { try { a.onSelect(id); } catch (_) {} }
  }

  function _sections(kind, id) {
    const a = _adapters[kind];
    let sections = {};
    try {
      const d = a.detail ? a.detail(id) : null;
      sections = (d && d.sections) || {};
    } catch (_) { sections = {}; }
    // Test tab slot: filled only when the adapter wires a testPane (LB1).
    if (a.testPane && !sections.test) sections.test = (mountEl) => a.testPane(id)(mountEl);
    // Adapters with kind-specific sections (LB4 models: weights/performance/
    // fit/prompts) may supply their own order; default order unchanged.
    const order = a.sectionOrder || SECTION_ORDER;
    const known = order.filter(s => sections[s] != null);
    const extra = Object.keys(sections).filter(s => order.indexOf(s) === -1);
    return { sections, ids: known.concat(extra) };
  }

  function renderDetail(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    const els = _els(kind);
    if (!a || !st || !els.detail) return;
    if (!st.selected) {
      if (els.label) els.label.textContent = a.emptyDetailLabel || '// SELECT';
      els.detail.innerHTML = esc(a.emptyDetailText || 'Select an item on the left.');
      return;
    }
    let item = null;
    try { item = (a.list() || []).find(x => x.id === st.selected) || null; } catch (_) {}
    if (!item && a.discovered) {
      try { item = (a.discovered() || []).find(x => x.id === st.selected) || null; } catch (_) {}
    }
    const title = item ? item.title : st.selected;
    if (els.label) els.label.textContent = `// ${title}`;

    // Section mounts are rebuilt below — lazy render fns run again on first
    // activation of each fresh mount ("invoked on first subnav activation").
    st.rendered = Object.create(null);
    const { ids } = _sections(kind, st.selected);
    if (ids.indexOf(st.subnav) === -1) st.subnav = ids[0] || 'overview';
    const subnav = ids.length ? `
      <div class="lib-subnav" role="tablist">${ids.map(s => `
        <button type="button" class="lib-subnav-pill ${st.subnav === s ? 'active' : ''}" role="tab"
          aria-selected="${st.subnav === s}" data-action="lib.subnav" data-kind="${esc(kind)}" data-section="${esc(s)}">
          ${esc((a.sectionLabels && a.sectionLabels[s]) || SECTION_LABELS[s] || s)}</button>`).join('')}
      </div>` : '';
    const prov = item && item.provenance
      ? ` <span class="lib-prov-chip prov-${esc(item.provenance)}">${esc(item.provenance)}</span>` : '';
    const head = `<div class="lib-detail-head"><code style="color:var(--accent)">${esc(st.selected)}</code>${prov}</div>`;
    els.detail.innerHTML = `${head}${subnav}
      <div class="lib-sections">${ids.map(s =>
        `<div class="lib-section" data-section="${esc(s)}" ${st.subnav === s ? '' : 'hidden'}></div>`).join('')}
      </div>
      <div class="lib-actions-row"></div>`;
    renderActions(kind);
    _activateSection(kind);
  }

  function renderActions(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    const els = _els(kind);
    const row = els.detail && els.detail.querySelector('.lib-actions-row');
    if (!a || !row || !st.selected) return;
    let acts = [];
    try { acts = (a.actions ? a.actions(st.selected) : []) || []; } catch (_) { acts = []; }
    row.innerHTML = acts.map(x => {
      const verb = VERBS.indexOf(x.verb) !== -1 ? x.verb : 'edit';
      const disabled = x.enabled === false;
      const extra = Object.entries(x.data || {})
        .map(([k, v]) => `data-${esc(k)}="${esc(String(v))}"`).join(' ');
      return `<button type="button" class="action-btn ${x.accent ? 'accent' : ''} ${x.danger || verb === 'delete' ? 'danger' : ''}"
        data-action="${esc(x.action || 'lib.action')}" data-kind="${esc(kind)}" data-verb="${esc(verb)}"
        data-id="${esc(st.selected)}" ${a.rowKeyAttr === 'data-key' ? `data-key="${esc(st.selected)}"` : ''}
        ${extra} ${disabled ? 'disabled' : ''} ${x.reason ? `title="${esc(x.reason)}"` : ''}>${esc(x.label)}</button>`;
    }).join('');
  }

  function setSubnav(kind, section) {
    const st = _state[kind];
    const els = _els(kind);
    if (!st || !els.detail) return;
    st.subnav = section;
    els.detail.querySelectorAll('.lib-subnav-pill').forEach(p => {
      const on = p.dataset.section === section;
      p.classList.toggle('active', on);
      p.setAttribute('aria-selected', String(on));
    });
    els.detail.querySelectorAll('.lib-section').forEach(sEl => {
      sEl.hidden = sEl.dataset.section !== section;
    });
    _activateSection(kind);
  }

  // Lazily render the active section — async render fns are invoked on FIRST
  // activation only (per selection), which is how per-node fetches (LB3 Files)
  // ride the shell without a side channel.
  function _activateSection(kind) {
    const a = _adapters[kind];
    const st = _state[kind];
    const els = _els(kind);
    if (!a || !st || !st.selected || !els.detail) return;
    const sEl = els.detail.querySelector(`.lib-section[data-section="${st.subnav}"]`);
    if (!sEl || st.rendered[st.subnav]) return;
    st.rendered[st.subnav] = true;
    const { sections } = _sections(kind, st.selected);
    const val = sections[st.subnav];
    if (val == null) return;
    if (typeof val === 'function') {
      sEl.innerHTML = '<div class="model-empty">Loading…</div>';
      Promise.resolve()
        .then(() => val(sEl))
        .then(out => {
          if (typeof out === 'string') sEl.innerHTML = out;
          else if (out instanceof Node) { sEl.textContent = ''; sEl.appendChild(out); }
          // fns that render into mountEl themselves return undefined — leave as-is
        })
        .catch(e => ErrorPanel.render(sEl, { title: 'Section failed', detail: e.message }));
    } else if (typeof val === 'string') {
      sEl.innerHTML = val;
    } else if (val instanceof Node) {
      sEl.textContent = '';
      sEl.appendChild(val);
    }
  }

  // Re-render the ACTIVE section (adapters call this when internal state —
  // e.g. an edit-mode flag — changes what the section shows).
  function refreshSection(kind, section) {
    const st = _state[kind];
    if (!st) return;
    delete st.rendered[section || st.subnav];
    _activateSection(kind);
  }

  // ── Programmatic cross-kind navigation ────────────────────────────────
  // switchTab + select + subnav restore. tasks.open-ref, the recommend rail
  // and plugins.goto-mcp all ride this instead of bespoke wiring.
  async function open(kind, id, section) {
    const a = _adapters[kind];
    if (!a) return false;
    if (typeof window.switchTab === 'function') {
      try { window.switchTab(a.tabId); } catch (_) {}
    }
    const st = _state[kind];
    if (!st.loadedOnce) await reload(kind);
    else if (st.loading) await st.loading;
    select(kind, id);
    if (section) setSubnav(kind, section);
    return true;
  }

  // ── Delegated shell actions (zero inline handlers) ────────────────────
  Actions.click({
    'lib.sidebar-tab': el => {
      const st = _state[el.dataset.kind];
      if (!st) return;
      st.side = el.dataset.side === 'discovered' ? 'discovered' : 'installed';
      st.chromeBuilt = false;   // tabs need active-state rebuild
      renderSidebar(el.dataset.kind);
    },
    'lib.group-toggle': el => {
      const st = _state[el.dataset.kind];
      if (!st) return;
      const g = el.dataset.group;
      st.collapsed[g] = !st.collapsed[g];
      renderRows(el.dataset.kind);
    },
    'lib.select': el => select(el.dataset.kind, el.dataset.id),
    'lib.subnav': el => setSubnav(el.dataset.kind, el.dataset.section),
    'lib.refresh': el => reload(el.dataset.kind),
    'lib.action': async el => {
      const a = _adapters[el.dataset.kind];
      if (!a || el.hasAttribute('disabled')) return;
      const verb = el.dataset.verb;
      const id = el.dataset.id;
      if (verb === 'delete') {
        const ok = await Confirm.ask({
          title: 'Delete', body: `Delete ${a.kind} "${id}"?`, okLabel: 'Delete', danger: true,
        });
        if (!ok) return;
      }
      if (a.onAction) a.onAction(verb, id, el);
    },
  });
  Actions.input({
    'lib.filter': el => {
      const st = _state[el.dataset.kind];
      if (!st) return;
      st.filter = el.value || '';
      renderRows(el.dataset.kind);
    },
  });

  return {
    register, adapter, state, mount, reload, open, select, setSubnav,
    renderSidebar, renderRows, renderDetail, renderActions, refreshSection,
    fetch, headers, guard,
  };
})();
