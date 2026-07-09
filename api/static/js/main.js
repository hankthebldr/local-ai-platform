// Enclave UI — module entry (phase-2 U1 flip).
// The former inline monolith <script> (index.html 2420-18154) + the 7
// component <script id=enclave-*-js> blocks, concatenated VERBATIM into one
// module. Vendored libs stay classic-defer globals; alias them into module
// scope so the moved code's bare references keep resolving.
const { Drawflow, d3, dagre, jsyaml } = window;

// core/ modules (phase-2 U2 carve). Imported for module scope so the bare
// esc()/renderMarkdown()/renderMarkdownBasic() call-sites keep resolving; still
// window-bridged via shell/legacy-bridge.js (esc, renderMarkdownBasic) below.
import { esc, renderMarkdown, renderMarkdownBasic } from './core/dom.js';
import { Net } from './core/net.js';
import { Theme } from './core/theme.js';
import { Toast, Confirm, EmptyState, ErrorPanel, Skeleton } from './core/ui.js';
import { Shortcuts } from './core/shortcuts.js';
import { Heartbeat } from './core/heartbeat.js';
import { Actions } from './shell/actions.js';
import { initRouter } from './shell/router.js';
import { AssetPeek } from './library/asset-peek.js';
import { SkillsPanel } from './library/skills.js';
import { PluginsPanel } from './library/plugins.js';
import { Kanban } from './library/kanban.js';
// Preserve early window availability (these were direct window.* assigns).
window.renderMarkdown = renderMarkdown;
window.Actions = Actions;
window.AssetPeek = AssetPeek;
window.SkillsPanel = SkillsPanel;
window.PluginsPanel = PluginsPanel;
window.Kanban = Kanban;
window.Net = Net;
window.Theme = Theme;
window.Toast = Toast;
window.Confirm = Confirm;
window.EmptyState = EmptyState;
window.ErrorPanel = ErrorPanel;
window.Skeleton = Skeleton;
window.Shortcuts = Shortcuts;
window.Heartbeat = Heartbeat;


/* ── THEME CONTROLLER ──────────────────────────────────────────── */
// Pairs with the early-bootstrap script in <head> that sets data-theme
// before paint. This handles the runtime toggle, persists the choice,
// and keeps the toggle's icon in sync.

/* ── TAB SWITCHING ─────────────────────────────────────────────── */
function switchTab(name, el) {
  // Legacy 'discover' routes (old links / bookmarks) land on Models with
  // the Discover section popped open. This remap must happen BEFORE the
  // panel lookup — there is no #tab-discover, so the old post-lookup
  // redirect block was dead code (the lookup threw first).
  if (name === 'discover') {
    name = 'inventory';
    const sect = document.getElementById('discover-section');
    if (sect) sect.open = true;
    if (typeof discoverLoaded !== 'undefined' && !discoverLoaded) loadDiscovery();
  }
  // Unknown tab names (stale hashes, removed tabs) must not take down the
  // caller — warn and stay on the current tab instead of throwing.
  const panel = document.getElementById('tab-' + name);
  if (!panel) { console.warn('switchTab: no panel for "' + name + '"'); return; }
  // Reset both the .active class AND any inline display left over by
  // AdminMenu.showPanel — without this, the last-opened admin subtab
  // bleeds through under every operational tab.
  document.querySelectorAll('.tab-content').forEach(t => {
    t.classList.remove('active');
    t.style.display = '';
  });
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('active');
    if (b.getAttribute('role') === 'tab') {
      b.setAttribute('aria-selected', 'false');
      b.setAttribute('tabindex', '-1');
    }
  });
  panel.classList.add('active');
  // Prefer explicitly-passed element; fall back to data-tab, then to onclick-string match.
  const btn = el
    || document.querySelector('.tab-btn[data-tab="' + name + '"]')
    || Array.from(document.querySelectorAll('.tab-btn')).find(
      b => (b.getAttribute('onclick') || '').indexOf("'" + name + "'") !== -1
    );
  if (btn) {
    btn.classList.add('active');
    if (btn.getAttribute('role') === 'tab') {
      btn.setAttribute('aria-selected', 'true');
      btn.setAttribute('tabindex', '0');
    }
  }

  if (name === 'dashboard') ComposerView.init();
  // Workflow Index no longer needs to refresh Kanban — the panel
  // moved to the Projects tab. Keep WorkflowIndex.load on its own.
  if (name === 'workflow-index') { WorkflowIndex.load(); }
  // Projects tab — refresh the Kanban (lists projects + the active
  // board) on every visit. Updates the count chip in the nav too.
  if (name === 'projects') {
    if (window.Kanban) {
      try { Kanban.refresh(); } catch (_) {}
    }
    _refreshProjectsCount();
  }
  if (name === 'runs' && window.RunsTab) {
    RunsTab.init();
    try { renderRunsPerfBand(); } catch (_) {}
  }
  if (name === 'inventory') {
    // Move the shared inventory DOM back from the Catalog mount so
    // the Models tab actually renders. Idempotent if it's already home.
    if (window.CatalogModelsShare) CatalogModelsShare.showInModelsTab();
    if (!catalogLoaded) loadCatalog();
    loadInstalledLocal();
  }
  // Catalog (legacy `workflows` data-tab): pull the shared inventory
  // DOM into the Catalog Models mount on demand. Only happens when
  // the Catalog is actually being shown, so the Models tab stays
  // populated on first load.
  if (name === 'workflows') {
    if (window.CatalogModelsShare) CatalogModelsShare.showInCatalog();
    // Pull the shared skills-discovery panel back into the Catalog's Skills
    // mount so Catalog → Skills shows it (it may be on the Skills tab).
    if (window.SkillsDiscoverShare) SkillsDiscoverShare.showInCatalog();
    if (!catalogLoaded) loadCatalog();
  }
  if (name === 'memory') { loadMemory(); loadMemoryTab(); loadArchitecturePanel(); WorkflowMemory && WorkflowMemory.refresh(); }
  else { _stopArchPressurePoll(); }
  // (Legacy 'discover' redirect now lives at the top of this function —
  // it has to run before the panel lookup to actually work.)
  // Skill Lab tab is gone from nav; Context now hosts the graph +
  // research panels. initResearch() runs from BOTH tab entries (the
  // hidden 'research' fallback is harmless).
  if (name === 'research') initResearch();
  if (name === 'documents') {
    try { initResearch(); } catch (_) {}
    // Role Library was relocated here from the legacy Runs tab — keep
    // it fresh on every visit since prompts/roles/ may have changed.
    if (typeof loadRoles === 'function') {
      try { loadRoles(); } catch (_) {}
    }
  }
  if (name === 'workflows') {
    // Legacy loader still runs (writes to the hidden mounts under
    // the Catalog page so refreshWorkflows + loadWorkflowDetail
    // don't NPE). The Catalog counts loader is what actually
    // populates the visible surface.
    if (typeof loadWorkflowsTab === 'function') { try { loadWorkflowsTab(); } catch (_) {} }
    if (typeof loadCatalogPage === 'function') { try { loadCatalogPage(); } catch (_) {} }
  }
  if (name === 'documents') loadDocumentsTab();
  if (name === 'agents') loadAgentsTab();

  // Promoted admin panels (Plugins / Skills / MCP / Cloud / Exports) were
  // moved out of the dropdown but still register their data-load handlers
  // on the `adminPanelActivated` event. Re-emit that event from switchTab
  // so first-class top-level entry to those tabs triggers the same load
  // path the dropdown route used to fire.
  // Standalone Skills tab — bring the shared discovery/catalog panel into
  // this tab (relocate-on-activate) and load it, so the homepage Skills tab
  // exposes the same discovery surface as Admin → Catalog → Skills.
  if (name === 'admin-skills') {
    if (window.SkillsDiscoverShare) SkillsDiscoverShare.showInSkillsTab();
    if (window.SkillsDiscover && typeof SkillsDiscover.load === 'function') {
      try { SkillsDiscover.load(); } catch (_) {}
    }
  }
  if (name === 'admin-plugins' || name === 'admin-skills' || name === 'admin-mcp'
      || name === 'admin-cloud' || name === 'admin-exports' || name === 'admin-keys') {
    window.dispatchEvent(new CustomEvent('adminPanelActivated', { detail: { panel: name } }));
    // Also activate the Admin trigger so the operator sees an admin-context
    // hint when they're on a system-area tab (admin-keys reached via System
    // sub-nav, etc.).
    const trig = document.getElementById('admin-trigger');
    if (trig && (name === 'admin-keys')) trig.classList.add('active');
  }

  // Deep-link: mirror the active tab into the hash. replaceState (not
  // location.hash=) so no hashchange feedback loop and no history spam.
  // Deeper paths under the same tab (#/runs/<id>) are preserved — the
  // startsWith check keeps bootSignIn's soft re-fire from clobbering a
  // restored run selection.
  try {
    const want = '#/' + name;
    if (!(location.hash + '/').startsWith(want + '/')) {
      history.replaceState(null, '', want);
    }
  } catch (_) { /* sandboxed contexts may deny history access */ }
}

/* ── TABLIST SEMANTICS (a11y) ───────────────────────────────────────
   The markup keeps plain .tab-btn buttons; roles + roving tabindex are
   assigned here so the nav is a real WAI-ARIA tablist: screen readers
   announce "tab, N of M, selected" and ←/→/Home/End move focus between
   tabs (manual activation — Enter/Space activates, so arrowing across
   the strip doesn't fire every panel's lazy loaders). The admin
   dropdown trigger inside .tab-nav is a menu button, not a tab — it
   keeps its own semantics and stays out of the roving order. */
document.addEventListener('DOMContentLoaded', () => {
  const nav = document.querySelector('.tab-nav');
  if (!nav) return;
  const tabs = Array.from(nav.querySelectorAll('.tab-btn[data-tab]'));
  tabs.forEach(btn => {
    const name = btn.dataset.tab;
    btn.setAttribute('role', 'tab');
    if (!btn.id) btn.id = 'tabbtn-' + name;
    btn.setAttribute('aria-controls', 'tab-' + name);
    const active = btn.classList.contains('active');
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
    btn.setAttribute('tabindex', active ? '0' : '-1');
    const panel = document.getElementById('tab-' + name);
    if (panel) {
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', btn.id);
    }
  });
  nav.addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    const current = tabs.indexOf(document.activeElement);
    if (current === -1) return;
    e.preventDefault();
    let next = current;
    if (e.key === 'ArrowLeft')  next = (current - 1 + tabs.length) % tabs.length;
    if (e.key === 'ArrowRight') next = (current + 1) % tabs.length;
    if (e.key === 'Home') next = 0;
    if (e.key === 'End')  next = tabs.length - 1;
    tabs[next].focus();
  });
});

/* ── CLOCK ──────────────────────────────────────────────────────── */
const startTime = Date.now();
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleTimeString('en-US', { hour12: false });
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  document.getElementById('uptime').textContent =
    `session: ${m}m ${s.toString().padStart(2,'0')}s`;
}
setInterval(updateClock, 1000);
updateClock();

/* ── GAUGE HELPER ───────────────────────────────────────────────── */
const CIRCUMFERENCE = 2 * Math.PI * 38;
function setGauge(arcId, valueId, pct) {
  const offset = CIRCUMFERENCE - (pct / 100) * CIRCUMFERENCE;
  document.getElementById(arcId).style.strokeDashoffset = offset;
  document.getElementById(valueId).textContent = Math.round(pct) + '%';
}

/* ── STATUS LOADER ──────────────────────────────────────────────── */
async function loadStatus() {
  try {
    // Polled every 10s — silent + no Net retries so backoff doesn't stack
    // with the interval timer; the catch below renders the offline state.
    const d = await Net.getJson('/health', { silent: true, retries: 0 });
    const s = d.system || {};

    // #status-content lives inside the horizontal chat-system-strip, so it
    // MUST be written in the strip grammar (.strip-stat > .stat-key +
    // .metric-val) — the old .metric-row panel markup has no styling here
    // and renders as one jammed run of text. One stat per runner: the
    // backend's runners array distinguishes Ollama from vLLM (GPU path)
    // instead of folding everything into "Ollama".
    const runners = d.runners || [{
      name: 'ollama',
      status: (d.ollama || {}).status || 'unknown',
      models_loaded: (d.ollama || {}).models_loaded || 0,
    }];
    const apiStat =
      '<span class="strip-stat"><span class="stat-key">API</span>' +
      `<span class="metric-val"><span class="status-pip online"></span>v${esc(d.version || '?')}</span></span>`;
    const runnerStats = runners.map(rn => {
      const up = rn.status === 'healthy';
      const pip = `<span class="status-pip ${up ? 'online' : 'offline'}"></span>`;
      const count = up ? `${rn.models_loaded || 0} <span class="stat-key">model${rn.models_loaded === 1 ? '' : 's'}</span>` : esc(rn.status || 'down');
      return `<span class="strip-stat"><span class="stat-key">${esc(rn.name)}</span>` +
             `<span class="metric-val">${pip}${count}</span></span>`;
    }).join('');
    document.getElementById('status-content').innerHTML = apiStat + runnerStats;

    // Ollama-down fallback: pause local planning (Promote/Pin) + show a banner
    // when the Ollama runner is unreachable, so the composer never silently
    // fails into a dead chat.
    const _ollamaRunner = runners.find(rn => rn.name === 'ollama');
    const _ollamaDown = _ollamaRunner ? _ollamaRunner.status !== 'healthy' : false;
    const _odb = document.getElementById('ollama-down-banner');
    if (_odb) _odb.hidden = !_ollamaDown;
    const _split = document.getElementById('composer-split');
    if (_split) _split.classList.toggle('ollama-down', _ollamaDown);

    // Host-utilization ring buffer — feeds the Runs tab's performance band
    // (UtilChart over the last ~15 min). 90 samples × 10s poll = 15 min.
    if (s.cpu_percent != null) {
      window._sysHistory = window._sysHistory || [];
      window._sysHistory.push({ t: Date.now(), cpu: s.cpu_percent, mem: s.memory_percent || 0 });
      if (window._sysHistory.length > 90) window._sysHistory.shift();
    }

    setGauge('cpu-arc', 'cpu-value', s.cpu_percent || 0);
    setGauge('mem-arc', 'mem-value', s.memory_percent || 0);
    document.getElementById('cpu-cores').textContent = (s.cpu_count || '--') + ' threads';
    document.getElementById('mem-detail').textContent =
      `${s.memory_used_gb || '--'} / ${s.memory_total_gb || '--'} GB`;

    const cpuArc = document.getElementById('cpu-arc');
    if (s.cpu_percent > 80) cpuArc.style.stroke = 'var(--red)';
    else if (s.cpu_percent > 50) cpuArc.style.stroke = 'var(--amber)';
    else cpuArc.style.stroke = 'var(--cyan)';

    const memArc = document.getElementById('mem-arc');
    if (s.memory_percent > 85) memArc.style.stroke = 'var(--red)';
    else if (s.memory_percent > 65) memArc.style.stroke = 'var(--amber)';
    else memArc.style.stroke = 'var(--green)';
  } catch(e) {
    document.getElementById('status-content').innerHTML =
      '<span class="strip-stat"><span class="stat-key">API</span>' +
      '<span class="metric-val"><span class="status-pip offline"></span>unreachable</span></span>';
  }
}

/* ── CALM ANALYTICS — dataviz atoms (design-system port) ─────────
   Pure functions of data → SVG/HTML strings. No interaction, no
   animation, no tooltips: sparklines first, fixed series colors
   (accent → accent-2 → info), amber for thresholds only, zero-based
   axes, data-ink only. */
function enclSparkline(data, opts) {
  opts = opts || {};
  const w = opts.width || 110, h = opts.height || 24, color = opts.color || 'var(--accent)';
  if (!Array.isArray(data) || data.length < 2) return '';
  const hi = opts.max != null ? opts.max : Math.max(...data, 1);
  const lo = opts.min != null ? opts.min : Math.min(...data, 0);
  const span = (hi - lo) || 1;
  const px = i => (2 + (i / (data.length - 1)) * (w - 4)).toFixed(1);
  const py = v => (2 + (h - 4) * (1 - (v - lo) / span)).toFixed(1);
  const line = data.map((v, i) => `${px(i)},${py(v)}`).join(' ');
  const lastX = px(data.length - 1), lastY = py(data[data.length - 1]);
  return `<svg width="${w}" height="${h}" aria-hidden="true">
    <polygon points="${px(0)},${h - 2} ${line} ${lastX},${h - 2}" fill="${color}" opacity="0.10"></polygon>
    <polyline points="${line}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"></polyline>
    <circle cx="${lastX}" cy="${lastY}" r="2" fill="${color}"></circle>
  </svg>`;
}

function enclTrendStat(opts) {
  // delta is caller-preformatted ("+12%", "-9s"). 'up' class is ALWAYS the
  // good color and 'down' always ember — deltaGood=false flips which arrow
  // direction counts as good (latency, memory: up is bad).
  const { label, value, delta, deltaGood = true, spark, color = 'var(--accent)' } = opts;
  let deltaHtml = '';
  if (delta) {
    const neg = String(delta).startsWith('-');
    const cls = neg ? (deltaGood ? 'down' : 'up') : (deltaGood ? 'up' : 'down');
    const glyph = neg ? '▾' : '▴';
    deltaHtml = `<span class="encl-trend-d ${cls}">${glyph} ${esc(String(delta).replace(/^-/, ''))}</span>`;
  }
  return `<div class="encl-trend">
    <span class="encl-trend-k">${esc(label)}</span>
    <div class="encl-trend-row"><span class="encl-trend-v">${esc(value)}</span>${deltaHtml}</div>
    ${Array.isArray(spark) && spark.length > 1 ? enclSparkline(spark, { color }) : ''}
  </div>`;
}

function enclUtilChart(series, opts) {
  opts = opts || {};
  const w = opts.width || 460, h = opts.height || 130, max = opts.max || 100;
  const unit = opts.unit || '%', warn = opts.warn, xlabels = opts.xlabels || [];
  const m = { t: 8, r: 36, b: 16, l: 6 };
  const pw = w - m.l - m.r, ph = h - m.t - m.b;
  const COLORS = ['var(--accent)', 'var(--accent-2)', 'var(--info)'];
  const y = v => (m.t + ph * (1 - Math.min(v, max) / max)).toFixed(1);
  let svg = '';
  for (const g of [0, 50, 100]) {
    const gv = g * max / 100;
    if (gv > max) continue;
    svg += `<line x1="${m.l}" y1="${y(gv)}" x2="${m.l + pw}" y2="${y(gv)}" stroke="var(--border)" stroke-width="1"></line>
            <text x="${m.l + pw + 5}" y="${(+y(gv) + 3).toFixed(1)}">${Math.round(gv)}${unit}</text>`;
  }
  if (warn != null) {
    svg += `<line x1="${m.l}" y1="${y(warn)}" x2="${m.l + pw}" y2="${y(warn)}" stroke="var(--warn)" stroke-width="1" stroke-dasharray="4 4" opacity="0.8"></line>
            <text x="${m.l + pw + 5}" y="${(+y(warn) + 3).toFixed(1)}" fill="var(--warn)">${warn}${unit}</text>`;
  }
  let legend = '';
  series.slice(0, 3).forEach((s, si) => {
    const c = s.color || COLORS[si % 3];
    const n = s.data.length;
    if (n >= 2) {
      const x = i => (m.l + (i / Math.max(1, n - 1)) * pw).toFixed(1);
      const line = s.data.map((v, i) => `${x(i)},${y(v)}`).join(' ');
      svg += `<polygon points="${m.l},${m.t + ph} ${line} ${m.l + pw},${m.t + ph}" fill="${c}" opacity="0.08"></polygon>
              <polyline points="${line}" fill="none" stroke="${c}" stroke-width="1.6" stroke-linejoin="round"></polyline>`;
    }
    const latest = s.data[n - 1];
    legend += `<span class="encl-util-key" style="--kc:${c}"><span class="d"></span>${esc(s.label)}
      <span class="v">${latest != null ? Math.round(latest) : '—'}</span><span class="u">${unit}</span></span>`;
  });
  xlabels.forEach((lb, i) => {
    const anchor = i === 0 ? 'start' : (i === xlabels.length - 1 ? 'end' : 'middle');
    const xx = m.l + (i / Math.max(1, xlabels.length - 1)) * pw;
    svg += `<text x="${xx.toFixed(1)}" y="${h - 3}" text-anchor="${anchor}">${esc(lb)}</text>`;
  });
  return `<div class="encl-util-legend">${legend}</div>
    <svg width="${w}" height="${h}" role="img" aria-label="${esc(series.map(s => s.label).join(', '))} over time">${svg}</svg>`;
}

/* GaugeStat — a single utilization reading as a calm linear meter (design-system
   dataviz). value/max → fill; optional warn tick. Returns an HTML string. */
function enclGaugeStat(opts) {
  opts = opts || {};
  var max = opts.max || 100, unit = opts.unit == null ? '%' : opts.unit;
  var pct = Math.max(0, Math.min(1, (opts.value || 0) / max)) * 100;
  var over = opts.warn != null && opts.value >= opts.warn;
  var fill = opts.color || (over ? 'var(--warn)' : 'var(--accent)');
  var scale = opts.scale === false ? '' :
    '<div class="encl-gauge-scale"><span>0</span>' +
    (opts.warn != null ? '<span style="color:var(--warn)">' + opts.warn + esc(unit) + '</span>' : '<span>' + Math.round(max / 2) + '</span>') +
    '<span>' + max + esc(unit) + '</span></div>';
  return '<div class="encl-gauge">' +
    '<div class="encl-gauge-top"><span class="encl-gauge-k">' + esc(opts.label || '') + '</span>' +
    (opts.sub ? '<span class="encl-gauge-sub">' + esc(opts.sub) + '</span>' : '') + '</div>' +
    '<span class="encl-gauge-v">' + esc(String(opts.value == null ? '—' : opts.value)) + '<span class="u">' + esc(unit) + '</span></span>' +
    '<div class="encl-gauge-track" role="meter" aria-valuenow="' + (opts.value || 0) + '" aria-valuemin="0" aria-valuemax="' + max + '" aria-label="' + esc(opts.label || '') + '">' +
    '<span class="encl-gauge-fill" style="width:' + pct.toFixed(1) + '%;--gc:' + fill + '"></span>' +
    (opts.warn != null ? '<span class="encl-gauge-warn" style="left:' + (Math.min(opts.warn, max) / max * 100).toFixed(1) + '%"></span>' : '') +
    '</div>' + scale + '</div>';
}

/* StatRange — min/avg/max for a series with a range bar + latest-reading dot
   (design-system dataviz; the distribution companion to TrendStat). */
function enclStatRange(opts) {
  opts = opts || {};
  var data = opts.data || [];
  var lo = opts.min != null ? opts.min : (data.length ? Math.min.apply(null, data) : 0);
  var hi = opts.max != null ? opts.max : (data.length ? Math.max.apply(null, data) : 0);
  var av = opts.avg != null ? opts.avg : (data.length ? data.reduce(function (a, b) { return a + b; }, 0) / data.length : 0);
  var cur = opts.current != null ? opts.current : (data.length ? data[data.length - 1] : av);
  var f = opts.floor != null ? opts.floor : lo, c = opts.ceil != null ? opts.ceil : hi;
  var span = (c - f) || 1;
  var pos = function (v) { return Math.max(0, Math.min(1, (v - f) / span)) * 100; };
  var fmt = function (n, d) { return Number.isFinite(n) ? (+n.toFixed(d || 0)).toString() : '—'; };
  var u = esc(opts.unit || '');
  return '<div class="encl-range" style="--rc:' + (opts.color || 'var(--accent)') + '">' +
    '<span class="encl-range-k">' + esc(opts.label || '') + '</span>' +
    '<div class="encl-range-stats">' +
    '<span class="encl-range-stat"><span class="l">min</span><span class="n">' + fmt(lo) + u + '</span></span>' +
    '<span class="encl-range-stat avg"><span class="l">avg</span><span class="n">' + fmt(av, 1) + u + '</span></span>' +
    '<span class="encl-range-stat"><span class="l">max</span><span class="n">' + fmt(hi) + u + '</span></span>' +
    '</div>' +
    '<div class="encl-range-track">' +
    '<span class="encl-range-span" style="left:' + pos(lo).toFixed(1) + '%;width:' + (pos(hi) - pos(lo)).toFixed(1) + '%"></span>' +
    '<span class="encl-range-avg" style="left:' + pos(av).toFixed(1) + '%"></span>' +
    '<span class="encl-range-cur" style="left:' + pos(cur).toFixed(1) + '%"></span>' +
    '</div>' +
    '<div class="encl-range-ends"><span>' + fmt(f) + u + '</span><span>' + fmt(c) + u + '</span></div></div>';
}

/* The Runs performance band — host utilization (live ring buffer) +
   cadence trends computed from the run history. Numbers live where the
   operating decisions happen; no dashboard page. */
async function renderRunsPerfBand() {
  const band = document.getElementById('runs-perf-band');
  if (!band) return;
  try {
    const hist = window._sysHistory || [];
    const utilEl = document.getElementById('runs-util-chart');
    if (utilEl && hist.length >= 2) {
      const spanMin = Math.max(1, Math.round((hist[hist.length - 1].t - hist[0].t) / 60000));
      utilEl.innerHTML = enclUtilChart(
        [{ label: 'cpu', data: hist.map(s => s.cpu) }, { label: 'mem', data: hist.map(s => s.mem) }],
        { warn: 85, max: 100, unit: '%', xlabels: [`-${spanMin}m`, `-${Math.round(spanMin / 2)}m`, 'now'] });
    } else if (utilEl) {
      utilEl.innerHTML = '<div class="model-empty" style="padding:20px 30px">Collecting host samples… (10s poll)</div>';
    }

    const r = await fetch('/api/workflows/runs?limit=60');
    const runs = (await r.json()) || [];
    const done = runs.filter(x => x.started_at && x.completed_at);
    const durs = done.map(x => (new Date(x.completed_at) - new Date(x.started_at)) / 1000).filter(d => d > 0);
    const fmtClock = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
    // Compare the recent half against the previous half — equal windows.
    const half = Math.floor(durs.length / 2);
    const avg = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;
    const avgRecent = avg(durs.slice(0, half || durs.length));
    const avgPrev = avg(durs.slice(half));
    const avgDelta = (half && avgPrev) ? Math.round(avgRecent - avgPrev) : null;
    const byDay = {};
    runs.forEach(x => { if (x.started_at) { const d = x.started_at.slice(0, 10); byDay[d] = (byDay[d] || 0) + 1; } });
    const days = Object.keys(byDay).sort();
    const perDay = days.map(d => byDay[d]);
    const ok = runs.filter(x => x.status === 'completed').length;
    const okPct = runs.length ? Math.round(100 * ok / runs.length) : 0;

    const trends = document.getElementById('runs-perf-trends');
    if (trends) {
      trends.innerHTML =
        enclTrendStat({ label: 'avg run', value: durs.length ? fmtClock(avgRecent) : '—',
          delta: avgDelta != null && avgDelta !== 0 ? `${avgDelta > 0 ? '+' : ''}${avgDelta}s` : '',
          deltaGood: false, spark: durs.slice(0, 16).reverse(), color: 'var(--accent-2)' }) +
        enclTrendStat({ label: 'runs / day', value: perDay.length ? String(perDay[perDay.length - 1]) : '0',
          spark: perDay.slice(-14), color: 'var(--info)' }) +
        enclTrendStat({ label: 'success', value: `${okPct}%`, spark: [], color: 'var(--accent)' });
    }
    // Live CPU / MEM gauges (GaugeStat) from the host ring buffer.
    const _h = window._sysHistory || [];
    const gaugesEl = document.getElementById('runs-perf-gauges');
    if (gaugesEl && _h.length) {
      const latest = _h[_h.length - 1];
      gaugesEl.innerHTML =
        enclGaugeStat({ label: 'CPU', value: Math.round(latest.cpu || 0), unit: '%', warn: 85 }) +
        enclGaugeStat({ label: 'MEM', value: Math.round(latest.mem || 0), unit: '%', warn: 85 });
    } else if (gaugesEl) { gaugesEl.innerHTML = ''; }
    band.hidden = false;
  } catch (e) { band.hidden = true; }
}

/* ── ASSET PEEK — unified deep-dive (design-system EntityCard→peek) ──
   One slide-over for models / agents / plugins. The model dive carries
   curated benchmark + role-fit enrichment (served from
   /api/inventory/enrichment, shipped as repo data — no phone-home) so
   pull decisions are educated ones: "this model, because HumanEval 88."
   Every figure is approximate published data; absence means no credible
   figure exists. */

/* ── MODELS LOADER (dashboard panel) ───────────────────────────── */
// Embedding-only model families that don't implement Ollama's /api/chat.
// Selecting one for chat causes Ollama to return 400 ("does not support chat"),
// which the API surfaces as InvalidRequestError. Filter them from the chat
// picker so users can't pick one by accident; they still appear in the
// system-status "Loaded Models" list since they ARE valid embedding models.
const EMBED_MODEL_PATTERNS = [
  /^nomic-embed/i,
  /^all-minilm/i,
  /^mxbai-embed/i,
  /^bge-/i,
  /^e5-/i,
  /-embed(-|$|:)/i,
  /^snowflake-arctic-embed/i,
];
function isEmbeddingOnlyModel(modelId) {
  return EMBED_MODEL_PATTERNS.some(re => re.test(modelId));
}

async function loadModels() {
  try {
    // Net.call (not getJson): a 401 returns a JSON body with no .data —
    // that must flow into the empty-state branch below (which also resets
    // the model-select), not into the catch. Only non-JSON / network
    // failures should reach the catch, matching the old r.json() throw.
    const r = await Net.call('/v1/models');
    const d = r.data;
    if (!d || typeof d !== 'object') throw new Error(r.error || 'Invalid response');
    const models = d.data || [];
    const container = document.getElementById('models-content');

    // Mirror the model count into the strip chip so the operator can
    // see how many models are loaded without expanding the popover.
    _setStripModelCount(models.length);

    if (models.length === 0) {
      container.innerHTML = '<div class="model-empty">No models. Run: ollama pull dolphin3</div>';
      // Also clear the model-select; otherwise the "loading…" sentinel
      // stays forever on a fresh stack (or a 401 response with d.data === undefined).
      // Cache must reflect reality for downstream node-config dropdowns.
      window._chatModels = [];
      const selEmpty = document.getElementById('model-select');
      if (selEmpty) {
        selEmpty.replaceChildren();
        const opt = document.createElement('option');
        opt.disabled = true;
        opt.selected = true;
        opt.textContent = 'No chat models — pull one (e.g. llama3.2:3b)';
        selEmpty.appendChild(opt);
      }
      return;
    }

    container.innerHTML = models.map(m => `
      <div class="model-item">
        <span class="model-name">${m.id}</span>
        <span class="model-size"><span class="status-pip online" style="animation-duration:3s"></span>${isEmbeddingOnlyModel(m.id) ? 'embed' : 'ready'}</span>
      </div>
    `).join('');

    // Only chat-capable models in the chat picker. Construct <option>s via
    // DOM API rather than innerHTML so model IDs (which originate from
    // Ollama and could theoretically contain HTML-active chars) can't
    // bleed into the document tree.
    const chatModels = models.filter(m => !isEmbeddingOnlyModel(m.id));
    // Cache for reuse by the composer's node config Model dropdown —
    // avoids a re-fetch on every node click and keeps the picker in
    // sync with what's actually loaded in Ollama.
    window._chatModels = chatModels.map(m => m.id);
    // Backend attribution per model id (/v1/models carries the serving
    // runner in owned_by: "ollama" | "vllm"). Read by the per-message
    // model chip so each reply names the backend that produced it.
    window._modelBackends = {};
    for (const m of chatModels) window._modelBackends[m.id] = m.owned_by || 'ollama';
    if (window.dfSelectedNodeId != null && typeof dfRenderConfigPanel === 'function') {
      try { dfRenderConfigPanel(window.dfSelectedNodeId); } catch (e) {}
    }
    const sel = document.getElementById('model-select');
    const prevValue = sel.value;
    sel.replaceChildren();
    if (chatModels.length === 0) {
      const opt = document.createElement('option');
      opt.disabled = true;
      opt.selected = true;
      opt.textContent = 'No chat models — pull one (e.g. llama3.2:3b)';
      sel.appendChild(opt);
    } else {
      // Group the picker by serving backend so the GPU path (vLLM) is
      // visibly distinct from the Ollama fallback instead of one
      // undifferentiated list.
      const byBackend = new Map();
      for (const m of chatModels) {
        const k = m.owned_by === 'vllm' ? 'vllm' : 'ollama';
        if (!byBackend.has(k)) byBackend.set(k, []);
        byBackend.get(k).push(m);
      }
      const groupLabel = { vllm: 'vLLM · GPU', ollama: 'Ollama' };
      for (const k of ['vllm', 'ollama']) {
        const group = byBackend.get(k);
        if (!group || !group.length) continue;
        const og = document.createElement('optgroup');
        og.label = groupLabel[k];
        for (const m of group) {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.id;
          og.appendChild(opt);
        }
        sel.appendChild(og);
      }
      // The 10s poll re-renders the picker — don't yank the operator's
      // current selection out from under them.
      if (prevValue && window._chatModels.includes(prevValue)) sel.value = prevValue;
    }
    // Surface any composition-pinned models the operator is using so
    // they can talk to the same model from the chat dock.
    try { syncCompositionModelsToChatPicker(); } catch (_) {}
  } catch(e) {
    document.getElementById('models-content').innerHTML =
      '<div class="model-empty" style="color:var(--red)">Failed to reach API</div>';
  }
}

/* ── SEARCH TOGGLE ───────────────────────────────────────────────── */
let webSearchEnabled = false;

function toggleSearch() {
  webSearchEnabled = !webSearchEnabled;
  const btn = document.getElementById('search-toggle');
  const label = document.getElementById('search-label');
  const input = document.getElementById('prompt');
  if (webSearchEnabled) {
    btn.classList.add('active');
    label.textContent = 'Search: ON';
    input.placeholder = 'Ask anything — web search enabled...';
  } else {
    btn.classList.remove('active');
    label.textContent = 'Search: OFF';
    input.placeholder = 'Enter query...';
  }
}

/* ── SEARCH SETTINGS ─────────────────────────────────────────────── */
let settingsDirty = false;

function toggleSettings() {
  const panel = document.getElementById('search-settings');
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) loadSearchSettings();
}

function markSettingsDirty() { settingsDirty = true; }

async function loadSearchSettings() {
  try {
    const cfg = await Net.getJson('/api/inventory/settings/search');
    document.getElementById('cfg-backend').value = cfg.default_backend || 'auto';
    document.getElementById('cfg-searxng').value = cfg.searxng_url || '';
    document.getElementById('cfg-brave').value = '';
    document.getElementById('cfg-brave').placeholder = cfg.brave_api_key_masked || 'Enter Brave Search API key...';
    document.getElementById('cfg-max-results').value = cfg.max_results || 5;
    document.getElementById('cfg-timeout').value = cfg.search_timeout || 10;

    // Status dots
    document.getElementById('dot-searxng').className = 'status-dot ' + (cfg.searxng_url ? 'active' : 'inactive');
    document.getElementById('dot-brave').className = 'status-dot ' + (cfg.brave_api_key_masked ? 'active' : 'inactive');

    // Active backend display
    const backendNames = { duckduckgo: 'DuckDuckGo (no API key required)', searxng: 'SearXNG (self-hosted)', brave: 'Brave Search (API key)', auto: 'Auto' };
    document.getElementById('cfg-active').innerHTML = 'Active: <strong>' + (backendNames[cfg.active_backend] || cfg.active_backend) + '</strong>';
    settingsDirty = false;
  } catch(e) {}
}

async function saveSearchSettings() {
  const body = {
    default_backend: document.getElementById('cfg-backend').value,
    searxng_url: document.getElementById('cfg-searxng').value,
    search_timeout: parseInt(document.getElementById('cfg-timeout').value) || 10,
    max_results: parseInt(document.getElementById('cfg-max-results').value) || 5,
  };
  // Only send brave key if the user typed something new
  const braveVal = document.getElementById('cfg-brave').value;
  if (braveVal) body.brave_api_key = braveVal;

  try {
    const d = await Net.postJson('/api/inventory/settings/search', body, { retries: 0 });
    if (d.status === 'saved') {
      loadSearchSettings();
      document.getElementById('cfg-save-btn').textContent = 'Saved!';
      setTimeout(() => { document.getElementById('cfg-save-btn').textContent = 'Save'; }, 1500);
    }
  } catch(e) {}
}

/* ── CITATION RENDERING ──────────────────────────────────────────── */
function renderCitations(text, sources) {
  // Render rich markdown (chat mode: code-block bars + → step hand-off), then
  // linkify [n] citations in the prose only — never inside <pre> code blocks.
  let html = (window.renderMarkdown ? window.renderMarkdown(text, { chat: true }) : esc(text));

  if (sources && sources.length > 0) {
    html = html.split(/(<pre[\s\S]*?<\/pre>)/g).map(seg => {
      if (seg.indexOf('<pre') === 0) return seg;
      return seg.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num) - 1;
        if (idx >= 0 && idx < sources.length) {
          return `<a class="citation" href="${esc(sources[idx].url)}" target="_blank" rel="noopener" title="${esc(sources[idx].title)}">[${num}]</a>`;
        }
        return match;
      });
    }).join('');
  }
  return html;
}

function renderSources(sources) {
  if (!sources || sources.length === 0) return '';
  const items = sources.map((s, i) =>
    `<div class="source-item">
      <span class="source-num">[${i+1}]</span>
      <span><span class="source-title">${esc(s.title)}</span> &mdash;
      <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></span>
    </div>`
  ).join('');

  return `<div class="sources-block">
    <div class="sources-label">// Sources</div>
    <div class="sources-list">${items}</div>
  </div>`;
}

/* ── PROVENANCE / CITATION RAIL ──────────────────────────────────────
   Closes the #1 gap: every grounded answer shows WHAT it was grounded on.
   `prov` is the {response_id, edges:[{source_type,source_id,source_label,
   metadata}]} summary returned inline by /v1/chat/completions (and emitted
   as a custom SSE event on streamed replies). Renders a compact chip rail
   grouped by source kind. Web sources are already shown by renderSources,
   so the rail folds in chunks / skills / tools (the previously-invisible
   grounding) and de-dupes web entries against the sources block. */
function renderProvenanceRail(prov) {
  if (!prov || !Array.isArray(prov.edges) || prov.edges.length === 0) return '';
  const meta = {
    rag_chunk:   { icon: '📄', cls: 'pv-chunk', label: 'Context' },
    skill:       { icon: '✦',  cls: 'pv-skill', label: 'Skills' },
    plugin_tool: { icon: '⚙',  cls: 'pv-tool',  label: 'Tools' },
    mcp_tool:    { icon: '⚙',  cls: 'pv-tool',  label: 'Tools' },
    web_source:  { icon: '🌐', cls: 'pv-web',   label: 'Web' },
  };
  const groups = {};
  prov.edges.forEach(e => {
    const m = meta[e.source_type] || { icon: '•', cls: 'pv-other', label: 'Other' };
    (groups[m.label] = groups[m.label] || { m, items: [] }).items.push(e);
  });
  const order = ['Context', 'Skills', 'Tools', 'Web', 'Other'];
  const sections = order.filter(k => groups[k]).map(k => {
    const g = groups[k];
    const chips = g.items.map(e => {
      const score = e.metadata && typeof e.metadata.score === 'number'
        ? ` <span class="pv-score">${(e.metadata.score * 100).toFixed(0)}%</span>` : '';
      return `<span class="pv-chip ${g.m.cls}" title="${esc(e.source_id)}">${g.m.icon} ${esc(e.source_label)}${score}</span>`;
    }).join('');
    return `<div class="pv-group"><span class="pv-group-label">${esc(k)}</span>${chips}</div>`;
  }).join('');
  return `<div class="provenance-rail" title="What this answer was grounded on">${sections}</div>`;
}

/* ── CHAT CODE-BLOCK HAND-OFF ────────────────────────────────────────
   Powers the copy / → step buttons on chat code blocks (rendered by
   renderMarkdown in chat mode). "→ step" pins the code as a workflow step
   (reuses the pin path) so a snippet flows straight into the composer. */
window.ChatCode = {
  copy: function (id) {
    var c = (window._mdCode || [])[id];
    if (!c) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(c.code).then(function () {
        if (window.Toast) Toast.success('Copied', (c.lang || 'code') + ' block');
      }).catch(function () {});
    }
  },
  toStep: function (id) {
    var c = (window._mdCode || [])[id];
    if (!c) return;
    var pins = window._enclavePins = window._enclavePins || [];
    var coding = /^(py|python|js|ts|javascript|typescript|bash|sh|shell|go|rust|sql|jsx|tsx|c|cpp|java)$/i.test(c.lang);
    pins.push({ id: 'code-' + id + '-' + pins.length, msgId: 'code', role: coding ? 'coding' : 'reasoning', text: c.code, title: (c.lang || 'code') + ' step' });
    if (window.Pins) window.Pins.render();
    if (window.OpPath) window.OpPath.refresh();
    if (window.Toast) Toast.success('Sent to composer', 'Added as a step — see the Pins bar; 2+ pins convert to a workflow.');
  },
};

/* ── CHAT ────────────────────────────────────────────────────────── */
// Enriched chat history: each entry has { role, content, timestamp, sources?, usage?, model? }
const chatHistory = [];       // Sent to API (role + content only)
const chatMetadata = [];      // Full metadata per message for export
const sessionStart = new Date();

function updateExportBtn() {
  const btn = document.getElementById('export-btn');
  if (chatMetadata.length > 0) btn.style.display = 'inline-block';
}

// ── SYSTEM PROMPT (applied to every chat turn) ─────────────────────────
const SYSPROMPT_KEY = 'enclave.chat.systemPrompt';

function toggleSystemPrompt() {
  const row = document.getElementById('system-prompt-row');
  const show = row.style.display === 'none';
  row.style.display = show ? 'block' : 'none';
  if (show) populateSystemPromptRoles();
}

async function populateSystemPromptRoles() {
  const sel = document.getElementById('sysprompt-role-select');
  if (!sel || sel.dataset.loaded === '1') return;
  try {
    const roles = await Net.getJson('/api/roles');
    for (const role of roles) {
      const opt = document.createElement('option');
      opt.value = role.id;
      opt.textContent = role.name;
      sel.appendChild(opt);
    }
    sel.dataset.loaded = '1';
  } catch (e) {
    console.warn('Failed to load roles for system prompt:', e);
  }
}

async function applyRoleAsSystemPrompt() {
  const sel = document.getElementById('sysprompt-role-select');
  const id = sel.value;
  if (!id) return;
  try {
    // Old silent !r.ok return now lands in the catch (console.warn) —
    // cosmetic-only difference, no UI state depends on it.
    const role = await Net.getJson(`/api/roles/${encodeURIComponent(id)}`);
    document.getElementById('system-prompt').value = role.content;
    saveSystemPrompt();
  } catch (e) { console.warn(e); }
}

function saveSystemPrompt() {
  const text = document.getElementById('system-prompt').value;
  try { localStorage.setItem(SYSPROMPT_KEY, text); } catch (_) {}
  updateSystemPromptStatus();
}

function clearSystemPrompt() {
  document.getElementById('system-prompt').value = '';
  try { localStorage.removeItem(SYSPROMPT_KEY); } catch (_) {}
  updateSystemPromptStatus();
}

function loadSystemPrompt() {
  try {
    const saved = localStorage.getItem(SYSPROMPT_KEY);
    if (saved) document.getElementById('system-prompt').value = saved;
  } catch (_) {}
  updateSystemPromptStatus();
}

function updateSystemPromptStatus() {
  const ta = document.getElementById('system-prompt');
  const status = document.getElementById('sysprompt-status');
  const btn = document.getElementById('sysprompt-btn');
  const active = !!(ta && ta.value.trim());
  if (status) status.textContent = active ? `active · ${ta.value.length} chars` : 'off';
  if (btn) btn.style.borderColor = active ? 'var(--accent-dim)' : 'var(--border)';
  if (btn) btn.style.color = active ? 'var(--accent)' : '';
}

function getSystemPromptMessage() {
  const ta = document.getElementById('system-prompt');
  const text = ta && ta.value.trim();
  return text ? { role: 'system', content: text } : null;
}

// Load on first paint; keep status synced as the user edits
document.addEventListener('DOMContentLoaded', () => {
  loadSystemPrompt();
  const ta = document.getElementById('system-prompt');
  if (ta) ta.addEventListener('input', updateSystemPromptStatus);
});

// When a composer node is selected, the dashboard chat input engages
// THAT step instead of the general chat — useful for iterating on a
// single step's prompt + model before saving the workflow. Wired via
// the #step-engage-badge above the input.
function composerExitStepEngage() {
  // Clear the engage badge — leaves the canvas + selection intact so
  // the operator can re-engage by re-clicking the node. The badge is
  // purely a chat-input mode signal.
  const badge = document.getElementById('step-engage-badge');
  if (badge) badge.hidden = true;
  window._composerEngagedNodeId = null;
}

async function _sendStepMessage(text, stepData) {
  const messages = document.getElementById('messages');
  const btn = document.getElementById('send-btn');
  const input = document.getElementById('prompt');
  const now = new Date();
  // Badge inline with the user message so the operator can see which
  // step was engaged for each turn in the chat history.
  const stepBadge = `<span style="color:var(--accent);font-size:0.6rem;vertical-align:middle;font-family:var(--mono)">⚡ ${esc(stepData.id || 'step')}</span>`;
  messages.innerHTML += `<div class="msg user">${esc(text)} ${stepBadge}</div>`;
  input.value = '';
  input.style.height = 'auto';
  btn.disabled = true;
  btn.textContent = 'Testing step…';
  const typingId = 'typing-' + Date.now();
  messages.innerHTML += `<div class="typing-indicator" id="${typingId}"><span class="dot"></span><span class="dot"></span><span class="dot"></span> running step</div>`;
  messages.scrollTop = messages.scrollHeight;

  try {
    // Send the live step definition — not a saved id — so unsaved
    // canvas edits flow through unchanged.
    // retries:0 — LLM step execution must not double-fire. Net.call (not
    // postJson) so API-error payloads still render inline, not as 'Connection error'.
    const r = await Net.call('/api/workflows/test-step', {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          step: {
            id: stepData.id,
            name: stepData.name,
            model: stepData.model || null,
            role: stepData.role || null,
            system_prompt: (stepData.system_prompt || '') +
              (window.AgentTuning ? AgentTuning.guidance(window._composerEngagedNodeId) : ''),
          },
          user_message: text,
        }),
      },
    });
    const d = (r.data && typeof r.data === 'object') ? r.data : {};
    document.getElementById(typingId)?.remove();
    if (!r.ok) {
      const errMsg = (d && d.error && d.error.message) || (d && d.detail) || `HTTP ${r.status}`;
      messages.innerHTML += `<div class="msg system-msg" style="color:var(--red)">${esc(errMsg)}</div>`;
    } else {
      const content = d.content || '(empty response)';
      const modelLabel = d.model ? `<span style="color:var(--text-muted);font-size:0.55rem;margin-left:6px;font-family:var(--mono)">${esc(d.model)}</span>` : '';
      let banner = '';
      if (d.model_fallback) {
        banner = `<div style="background:rgba(255,200,0,0.07);border:1px solid rgba(255,200,0,0.35);border-radius:4px;padding:4px 8px;font-size:0.62rem;color:var(--text-muted);margin-bottom:4px">⚠ Pinned <strong>${esc(d.model_fallback.requested)}</strong> not installed — ran on <strong>${esc(d.model_fallback.resolved)}</strong>.</div>`;
      }
      const mid = ChatRating.nextId();
      const stepBody = (window.renderMarkdown ? window.renderMarkdown(content, { chat: true }) : esc(content));
      messages.innerHTML += `<div class="msg assistant" id="${mid}">${banner}${stepBody}${modelLabel}${ChatRating.toolbarHtml(mid, {model: d.model, agent: window._chatAgent})}</div>`;
    }
  } catch (e) {
    document.getElementById(typingId)?.remove();
    messages.innerHTML += `<div class="msg system-msg" style="color:var(--red)">Connection error: ${esc(e.message)}</div>`;
  }
  btn.disabled = false;
  btn.textContent = 'Send';
  messages.scrollTop = messages.scrollHeight;
}

function composerEnterStepEngage(nodeId) {
  // dfNodeData is module-scoped; reference it lexically rather than via
  // window so this helper works from anywhere in the same script block.
  if (nodeId == null || typeof dfNodeData === 'undefined' || !dfNodeData[nodeId]) return;
  window._composerEngagedNodeId = nodeId;
  const badge = document.getElementById('step-engage-badge');
  const idEl  = document.getElementById('step-engage-id');
  const metaEl = document.getElementById('step-engage-meta');
  const d = dfNodeData[nodeId];
  if (badge && idEl) {
    idEl.textContent = d.id || ('node ' + nodeId);
    // Show the agent you're now talking to: its role @ model.
    if (metaEl) metaEl.textContent = '· ' + (d.role || 'general') + (d.model ? ' @ ' + d.model : ' @ auto');
    badge.hidden = false;
    if (window.AgentTuning) AgentTuning.refreshBadge(nodeId);
  }
  // Reflect the bound node's model in the chat model selector so the
  // operator sees — and can change (→ writes back via onChatModelChanged) —
  // which model this specific agent runs on.
  try {
    const sel = document.getElementById('model-select');
    if (sel && d.model && [...sel.options].some(o => o.value === d.model)) sel.value = d.model;
  } catch (_) {}
}

// Explicit "test in chat" — engage the selected step AND focus the chat input
// so the operator can immediately type a message and see only this step's reply
// (routes to /api/workflows/test-step via the sendMessage step-engage branch).
function composerTestStepInChat() {
  const nodeId = (typeof dfSelectedNodeId !== 'undefined' && dfSelectedNodeId != null)
    ? dfSelectedNodeId : window._composerEngagedNodeId;
  if (nodeId == null) return;
  composerEnterStepEngage(nodeId);
  const p = document.getElementById('prompt');
  if (p) {
    p.focus();
    p.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

// Chat-settings-as-node-config: when the chat is bound to a node, the chat's
// model selector configures THAT agent (writes back to the node). With no node
// bound it's the general-chat model as before.
function onChatModelChanged() {
  const sel = document.getElementById('model-select');
  if (!sel) return;
  const model = sel.value;
  const nodeId = window._composerEngagedNodeId;
  if (nodeId == null || typeof dfNodeData === 'undefined' || !dfNodeData[nodeId]) return;
  if (typeof dfUpdateNodeData === 'function') {
    try { dfUpdateNodeData(nodeId, 'model', model); } catch (_) { dfNodeData[nodeId].model = model; }
  } else { dfNodeData[nodeId].model = model; }
  const d = dfNodeData[nodeId];
  const metaEl = document.getElementById('step-engage-meta');
  if (metaEl) metaEl.textContent = '· ' + (d.role || 'general') + ' @ ' + model;
  if (window.Toast) Toast.info('Agent updated', (d.id || 'step') + ' now runs on ' + model);
}

// Seed the bound agent with context — appended to its system prompt. The
// in-chat "seed the agent with a particular context/output" affordance.
function composerSeedAgent() {
  const nid = window._composerEngagedNodeId;
  if (nid == null || typeof dfNodeData === 'undefined' || !dfNodeData[nid]) {
    if (window.Toast) Toast.info('No agent bound', 'Select a node first, then seed it.');
    return;
  }
  const ctx = window.prompt('Seed this agent with context (appended to its system prompt):', '');
  if (ctx == null || !ctx.trim()) return;
  const d = dfNodeData[nid];
  const sp = (d.system_prompt || '') + '\n\n[Seed context]\n' + ctx.trim();
  if (typeof dfUpdateNodeData === 'function') {
    try { dfUpdateNodeData(nid, 'system_prompt', sp); } catch (_) { d.system_prompt = sp; }
  } else { d.system_prompt = sp; }
  if (window.Toast) Toast.success('Agent seeded', (d.id || 'step') + ' got new context');
}

async function sendMessage() {
  const input = document.getElementById('prompt');
  const text = input.value.trim();
  if (!text) return;

  // ── Step-engage branch ────────────────────────────────────────────
  // If the composer has a selected node, route this turn to the
  // single-step test endpoint instead of /v1/chat/completions. Keeps
  // the iteration loop short: edit prompt → type message → see this
  // step's reply without saving + running the whole workflow.
  // dfNodeData is module-scoped — reference it lexically, not via window.
  if (window._composerEngagedNodeId != null && typeof dfNodeData !== 'undefined' && dfNodeData[window._composerEngagedNodeId]) {
    return _sendStepMessage(text, dfNodeData[window._composerEngagedNodeId]);
  }

  const model = document.getElementById('model-select').value;
  const messages = document.getElementById('messages');
  const btn = document.getElementById('send-btn');
  const now = new Date();

  chatHistory.push({ role: 'user', content: text });
  chatMetadata.push({ role: 'user', content: text, timestamp: now.toISOString(), model });

  const searchBadge = webSearchEnabled ? ' <span style="color:var(--amber);font-size:0.6rem;vertical-align:middle">&#x1F310; SEARCH</span>' : '';
  messages.innerHTML += `<div class="msg user">${esc(text)}${searchBadge}</div>`;
  input.value = '';
  input.style.height = 'auto';
  btn.disabled = true;
  btn.textContent = webSearchEnabled ? 'Searching…' : 'Sending…';

  const typingId = 'typing-' + Date.now();
  const typingLabel = webSearchEnabled ? 'searching & generating' : 'generating';
  messages.innerHTML += `<div class="typing-indicator" id="${typingId}"><span class="dot"></span><span class="dot"></span><span class="dot"></span> ${typingLabel}</div>`;
  messages.scrollTop = messages.scrollHeight;

  try {
    // Prepend the saved system prompt (if any) — OpenAI-style role=system turn.
    const sysMsg = getSystemPromptMessage();
    const outboundMessages = sysMsg ? [sysMsg, ...chatHistory] : chatHistory;

    // If an agent is selected in the composer's agent-chat dock, route
    // through /api/agents/{id}/chat so the agent's system prompt, model,
    // context sources, and tools are applied. Otherwise fall back to the
    // raw OpenAI-compatible chat endpoint.
    // retries:0 on both — LLM inference must never silently double-execute.
    // Net.call (not postJson) so API-error payloads (d.error) still render
    // as API errors, not 'Connection error'.
    let r;
    if (window._chatAgent) {
      r = await Net.call(`/api/agents/${encodeURIComponent(window._chatAgent)}/chat`, {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: chatHistory })
        },
      });
    } else {
      r = await Net.call('/v1/chat/completions', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model,
            messages: outboundMessages,
            max_tokens: 1024,
            web_search: webSearchEnabled,
          })
        },
      });
    }
    if (r.status === 0) throw new Error(r.error || 'network error');
    const d = (r.data && typeof r.data === 'object') ? r.data : {};
    const ti = document.getElementById(typingId);
    if (ti) ti.remove();

    if (d.error) {
      messages.innerHTML += `<div class="msg system-msg" style="color:var(--red)">${d.error.message || d.error.detail || 'Unknown error'}</div>`;
    } else {
      // /v1/chat/completions returns {choices:[{message:{content}}], usage};
      // /api/agents/{id}/chat returns {content, model, usage, model_fallback}.
      // The composer chat hits either endpoint depending on whether
      // window._chatAgent is set — read whichever shape applies so a
      // real agent reply isn't rendered as literal "(empty response)".
      const agentShape = (typeof d.content === 'string');
      const content = agentShape
        ? d.content
        : (d.choices?.[0]?.message?.content || '(empty response)');
      const sources = d.sources || [];
      const usage = d.usage || {};
      // Surface the agent's model_fallback warning (pinned model not
      // installed, ran on resolved alternative) so the operator sees
      // it in the composer chat just like in the agents-tab panel.
      if (agentShape && d.model_fallback) {
        const fb = d.model_fallback;
        messages.innerHTML += `<div class="msg system-msg" style="background:rgba(255,200,0,0.05);border-left-color:var(--amber)"><strong>⚠ Model fallback:</strong> Pinned <code>${esc(fb.requested || '?')}</code> not installed — using <code>${esc(fb.resolved || d.model || '?')}</code>.</div>`;
      }

      const provenance = d.provenance || null;
      chatHistory.push({ role: 'assistant', content });
      chatMetadata.push({
        role: 'assistant',
        content,
        timestamp: new Date().toISOString(),
        model,
        sources,
        provenance,
        usage,
        web_search: webSearchEnabled,
      });

      const citedContent = renderCitations(content, sources);
      const sourcesHtml = renderSources(sources);
      const provRailHtml = renderProvenanceRail(provenance);
      // Name the model AND the backend that served it (vLLM GPU path vs
      // Ollama) — without this every reply is backend-anonymous and the
      // operator can't tell which runner is doing the work.
      const ranModel = (agentShape && d.model) ? d.model : model;
      const backend = (window._modelBackends || {})[ranModel];
      const runChip = ranModel
        ? `<span style="color:var(--text-muted);font-size:0.55rem;margin-left:6px;font-family:var(--mono)">${esc(ranModel)}${backend ? ' · ' + esc(backend) : ''}</span>`
        : '';
      const mid = ChatRating.nextId();
      messages.innerHTML += `<div class="msg assistant" id="${mid}">${citedContent}${sourcesHtml}${provRailHtml}${runChip}${ChatRating.toolbarHtml(mid, {model: ranModel, backend, web_search: webSearchEnabled})}</div>`;
    }
  } catch(e) {
    const ti = document.getElementById(typingId);
    if (ti) ti.remove();
    messages.innerHTML += `<div class="msg system-msg" style="color:var(--red)">Connection error: ${e.message}</div>`;
  }

  btn.disabled = false;
  btn.textContent = 'Send';
  messages.scrollTop = messages.scrollHeight;
  updateExportBtn();
}


/* ── Actions: delegated events ─────────────────────────────────────
   data-action="ns.verb" + data-* args; one document-level listener per
   event type, lazily installed. Innermost [data-action] wins (closest),
   so nested actionables don't need stopPropagation. CSP-clean and
   module-split-safe: handlers are registered, not global. */

/* ── SESSION EXPORT ──────────────────────────────────────────────── */

function generateSessionMarkdown() {
  const model = document.getElementById('model-select').value;
  const now = new Date();
  const durationMs = now - sessionStart;
  const durationMin = Math.floor(durationMs / 60000);
  const durationSec = Math.floor((durationMs % 60000) / 1000);
  const msgCount = chatMetadata.length;
  const totalTokens = chatMetadata.reduce((sum, m) => sum + (m.usage?.total_tokens || 0), 0);
  const hadSearch = chatMetadata.some(m => m.web_search);

  let md = `# Chat Session \u2014 ${now.toLocaleDateString()} ${now.toLocaleTimeString()}\n\n`;
  md += `| Field | Value |\n|-------|-------|\n`;
  md += `| Model | ${model} |\n`;
  md += `| Duration | ${durationMin}m ${durationSec}s |\n`;
  md += `| Messages | ${msgCount} |\n`;
  md += `| Total Tokens | ${totalTokens.toLocaleString()} |\n`;
  md += `| Web Search | ${hadSearch ? 'Used' : 'Off'} |\n`;
  md += `\n---\n\n`;

  for (const msg of chatMetadata) {
    if (msg.role === 'user') {
      md += `## User\n${msg.content}\n\n`;
    } else if (msg.role === 'assistant') {
      md += `## Assistant\n${msg.content}\n`;
      if (msg.sources && msg.sources.length > 0) {
        md += `\n### Sources\n`;
        msg.sources.forEach((s, i) => {
          md += `${i + 1}. [${s.title}](${s.url}) \u2014 ${s.snippet}\n`;
        });
      }
      if (msg.usage && msg.usage.total_tokens) {
        md += `\n*Tokens: ${msg.usage.prompt_tokens} prompt + ${msg.usage.completion_tokens} completion = ${msg.usage.total_tokens} total*\n`;
      }
      md += `\n`;
    }
    md += `---\n\n`;
  }

  return md;
}

function generateFilename() {
  const now = new Date();
  const model = document.getElementById('model-select').value;
  const modelShort = model.replace(/[/:]/g, '-').replace(/:latest$/, '');
  const dateStr = now.toISOString().slice(0, 16).replace('T', '-').replace(':', '');
  return `${dateStr}-${modelShort}.md`;
}

async function exportSession() {
  if (chatMetadata.length === 0) return;

  const md = generateSessionMarkdown();
  const filename = generateFilename();

  // 1. Browser download
  const blob = new Blob([md], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);

  // 2. Save to server
  try {
    await Net.postJson('/api/exports/save', { filename, content: md }, { retries: 0, silent: true });
  } catch(e) {
    // Silent fail for server save — download already succeeded
  }

  // Brief visual feedback
  const btn = document.getElementById('export-btn');
  btn.textContent = 'SAVED!';
  setTimeout(() => { btn.textContent = 'EXPORT'; }, 1500);
}

(function wireChatInput() {
  const ta = document.getElementById('prompt');
  if (!ta) return;
  const autoGrow = () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 240) + 'px';
  };
  ta.addEventListener('input', autoGrow);
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    } else if (e.key === 'Escape') {
      ta.value = '';
      autoGrow();
    }
  });
})();

/* ══════════════════════════════════════════════════════════════════
   INVENTORY TAB
   ══════════════════════════════════════════════════════════════════ */

let catalogLoaded = false;
let catalogData = [];
let activeFilter = 'all';

function tagClass(t) {
  const map = { uncensored: 'uncensored', abliterated: 'abliterated', reasoning: 'reasoning', coding: 'coding', fast: 'fast' };
  return map[t] || '';
}

// ── Installed Locally — manage models actually resident on this box ──────
// The catalog grid below is for DISCOVERING new models; this manages what's
// already installed, across backends (Ollama + vLLM), catalogued or not.
async function loadInstalledLocal() {
  const body = document.getElementById('installed-local-body');
  const countEl = document.getElementById('installed-local-count');
  if (!body) return;
  try {
    const [st, mem] = await Promise.all([
      Net.getJson('/api/inventory/status'),
      Net.getJson('/api/inventory/memory'),
    ]);
    const local = st.installed_local || [];
    const runningNames = new Set((mem.running_models || []).map(m => m.name));
    if (countEl) countEl.textContent = local.length ? `(${local.length})` : '';
    if (!local.length) {
      body.innerHTML = '<div class="model-empty">No models installed locally yet. Install one from the catalog below.</div>';
      return;
    }
    body.innerHTML = local.map(m => {
      const isVllm = m.backend === 'vllm';
      const running = runningNames.has(m.name);
      const size = m.size_gb ? `${m.size_gb} GB` : '—';
      const badge = `<span class="rm-backend rm-backend-${isVllm ? 'vllm' : 'ollama'}">${isVllm ? 'vLLM · GPU' : 'Ollama'}</span>`;
      const status = running
        ? '<span class="il-running" title="Currently loaded in memory">● running</span>'
        : '<span class="il-idle">idle</span>';
      let actions;
      if (isVllm) {
        actions = `<span class="rm-pinned" title="Served by vLLM; change via docker compose (VLLM_MODEL)">pinned</span>`;
      } else {
        actions =
          (running ? `<button class="action-btn unload" data-action="models.unload" data-model="${esc(m.name)}">Unload</button>` : '') +
          `<button class="action-btn xs danger" data-action="models.remove-local" data-model="${esc(m.name)}">Remove</button>`;
      }
      return `<div class="running-model-card rm-clickable" data-action="models.detail" data-model="${esc(m.name)}" title="Double-click for details, metadata, and supported workflows">
        <div class="rm-info">
          <div class="rm-name">${esc(m.name)} ${badge} ${status}</div>
          <div class="rm-detail">${size} · ${m.in_catalog ? 'in catalog' : 'not in catalog'} · <span style="color:var(--text-muted)">double-click for details</span></div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">${actions}</div>
      </div>`;
    }).join('');
  } catch (e) {
    body.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed to load local models: ${esc(e.message)}</div>`;
  }
}

// Double-click a local model → rich detail: metadata + supported workflows.
async function openModelDetail(name) {
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
  const inner = document.createElement('div');
  inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:min(580px,94vw);max-height:88vh;overflow-y:auto;border-radius:6px;';
  inner.innerHTML = '<div class="model-empty">Loading model detail…</div>';
  modal.appendChild(inner);
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
  try {
    const d = await Net.getJson('/api/inventory/model/' + encodeURIComponent(name));
    const det = d.details || {};
    const ctxVal = Object.entries(d.model_info || {}).filter(([k]) => k.includes('context')).map(([, v]) => v)[0];
    const rows = [
      ['Backend', d.backend === 'vllm' ? 'vLLM · GPU' : 'Ollama'],
      ['Family', det.family], ['Parameters', det.parameter_size],
      ['Quantization', det.quantization_level], ['Format', det.format],
      ['Context window', ctxVal ? Number(ctxVal).toLocaleString() + ' tokens' : null],
      ['Capabilities', (d.capabilities || []).join(', ') || null],
      ['Modified', d.modified_at ? new Date(d.modified_at).toLocaleString() : null],
    ].filter(([, v]) => v != null && v !== '');
    const wfs = d.workflows || [];
    inner.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <div style="font-family:var(--mono);font-weight:600;font-size:0.92rem;flex:1;word-break:break-all">${esc(name)}</div>
        <span class="rm-backend rm-backend-${d.backend === 'vllm' ? 'vllm' : 'ollama'}">${d.backend === 'vllm' ? 'vLLM · GPU' : 'Ollama'}</span>
        <button class="action-btn xs ghost" data-action="models.close">×</button>
      </div>
      ${d.note ? `<div style="font-size:0.66rem;color:var(--text-muted);margin-bottom:10px">${esc(d.note)}</div>` : ''}
      ${d.error ? `<div class="admin-modal-error" style="margin:0 0 10px">${esc(d.error)}</div>` : ''}
      <div class="md-detail-grid">${rows.map(([k, v]) => `<div class="metric-row"><span class="metric-key">${esc(k)}</span><span class="metric-val">${esc(String(v))}</span></div>`).join('')}</div>
      <div class="panel-label" style="margin-top:16px">Supported workflows ${wfs.length ? `(${wfs.length})` : ''}</div>
      <div>${wfs.length
        ? wfs.map(w => `<div class="md-wf-row"><span class="md-wf-name">${esc(w.name)}</span><span class="md-wf-meta">${w.steps} steps</span><button class="action-btn xs" data-action="models.open-workflows">Open ↗</button></div>`).join('')
        : '<div style="color:var(--text-muted);font-size:0.66rem;padding:4px 0">No workflows reference this model yet.</div>'}</div>
      <div style="display:flex;gap:6px;justify-content:flex-end;margin-top:16px">
        <button class="action-btn sm cyan" data-action="models.modal-test" data-model="${esc(name)}">Test in chat</button>
      </div>`;
  } catch (e) {
    inner.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed to load model detail: ${esc(e.message)}</div>`;
  }
}

async function removeLocalModel(name) {
  const ok = await Confirm.ask({ title: 'Remove model', body: `Remove "${name}" from local storage? This deletes the weights from Ollama.`, okLabel: 'Remove', danger: true });
  if (!ok) return;
  try {
    // retries:0 — destructive remove.
    await Net.postJson('/api/inventory/remove', { model: name }, { retries: 0 });
    loadInstalledLocal();
    if (typeof loadCatalog === 'function') { catalogLoaded = false; loadCatalog(); }
  } catch (e) {
    Toast.danger('Remove failed', e.message);
  }
}

async function loadCatalog() {
  try {
    const d = await Net.getJson('/api/inventory/catalog');
    catalogData = d.models || [];
    catalogLoaded = true;

    // Hardware info
    const hw = d.hardware || {};
    document.getElementById('hw-info').innerHTML = `
      <span class="metric-key">${hw.name || 'Unknown'}</span>
      <span class="metric-val highlight">${hw.cpu || '?'} &mdash; ${hw.ram_gb || '?'}GB RAM (${hw.max_model_ram_gb || '?'}GB for models)</span>
    `;

    // Tab count
    document.getElementById('inv-count').textContent = `(${d.installed_count}/${d.total})`;

    renderCatalog();
    // Skills / Plugins / MCPs Discover live under this same tab now,
    // so kick their loaders. Idempotent if the operator never expands.
    if (window.SkillsDiscover) SkillsDiscover.load();
    loadPluginsDiscover();
    loadMcpsDiscover();
    loadExternalDiscover();
  } catch(e) {
    document.getElementById('inv-grid').innerHTML =
      `<div class="model-empty" style="color:var(--red)">Failed to load catalog: ${e.message}</div>`;
  }
}

// Projects-tab count chip — hits /api/projects and writes the count
// onto the nav tab. Best-effort; failure leaves the chip blank.
async function _refreshProjectsCount() {
  const chip = document.getElementById('projects-tab-count');
  if (!chip) return;
  try {
    const data = await Net.getJson('/api/projects', { silent: true });
    const list = Array.isArray(data) ? data : (data.projects || []);
    chip.textContent = list.length ? `(${list.length})` : '';
  } catch (_) { /* best-effort */ }
}

// Catalog page (legacy Workflows tab, repurposed) — paints tile
// icons + live counts for Plugins / Skills / MCP / External. Each
// tile click routes to the relevant admin tab. Counts come from
// the same endpoints the admin tabs use, so an idle Catalog visit
// is cheap (cached by the browser).
async function loadCatalogPage() {
  // Paint icons on the section selector.
  if (window.AgentIcons) {
    const ic = id => document.getElementById(id);
    if (ic('catalog-tile-icon-model'))  ic('catalog-tile-icon-model').innerHTML  = AgentIcons.svg('data');
    if (ic('catalog-tile-icon-plugin')) ic('catalog-tile-icon-plugin').innerHTML = AgentIcons.svg('plugin');
    if (ic('catalog-tile-icon-skill'))  ic('catalog-tile-icon-skill').innerHTML  = AgentIcons.svg('skill');
    if (ic('catalog-tile-icon-mcp'))    ic('catalog-tile-icon-mcp').innerHTML    = AgentIcons.svg('mcp');
    if (ic('catalog-tile-icon-agent'))  ic('catalog-tile-icon-agent').innerHTML  = AgentIcons.svg('coordinator');
    if (ic('catalog-tile-icon-ext'))    ic('catalog-tile-icon-ext').innerHTML    = AgentIcons.svg('tool');
  }
  // Counts — best effort, never block the page.
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v == null ? '—' : String(v);
  };
  try {
    const d = await Net.getJson('/v1/models', { silent: true });
    const list = d.data || [];
    set('catalog-count-models', list.length);
  } catch (_) {}
  try {
    const data = await Net.getJson('/api/plugins', { silent: true });
    const list = Array.isArray(data) ? data : (data.plugins || []);
    set('catalog-count-plugins', list.length);
    let totalSkills = 0;
    list.forEach(p => { totalSkills += ((p.skills || []).length); });
    set('catalog-count-skills', totalSkills);
  } catch (_) {}
  try {
    const data = await Net.getJson('/api/mcp/servers', { silent: true });
    const list = Array.isArray(data) ? data : (data.servers || []);
    set('catalog-count-mcp', list.length);
  } catch (_) {}
  try {
    const data = await Net.getJson('/api/agents', { silent: true });
    set('catalog-count-agents', (data || []).length);
  } catch (_) {}
  try {
    const data = await Net.getJson('/api/discover/sources', { silent: true });
    const provs = data.providers || [];
    const live = provs.filter(p => p.implemented).length;
    set('catalog-count-ext', provs.length ? `${live}/${provs.length}` : '—');
  } catch (_) {}
  // Activate the current section (or 'models' on first paint).
  if (window.CatalogPage) CatalogPage.show(CatalogPage._active || 'models');
}

// CatalogPage — section selector + per-section mount logic. Each
// section has a target mount element (#catalog-{name}-mount) where
// the DOMContentLoaded relocator moved the corresponding discover
// panels at boot. The show() function flips the active section + lazy-
// kicks the relevant loader.
const CatalogPage = (function () {
  let _active = 'models';
  let _loaded = new Set();

  function show(name) {
    _active = name;
    document.querySelectorAll('.catalog-nav-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.catSec === name);
    });
    document.querySelectorAll('.catalog-section').forEach(s => {
      const matches = s.dataset.catSec === name;
      if (matches) s.removeAttribute('hidden');
      else s.setAttribute('hidden', '');
      s.classList.toggle('active', matches);
    });
    // Lazy-load the section's content on first activation.
    if (!_loaded.has(name)) {
      _loaded.add(name);
      _loadSection(name);
    }
  }

  async function _loadSection(name) {
    // For each section, populate the corresponding mount with either
    // a relocated panel or a freshly-built list. Models / Plugins /
    // Skills / MCP / External all get their relocated <details>
    // panels; Agents is built from /api/agents in place.
    if (name === 'agents') {
      const mount = document.getElementById('catalog-agents-mount');
      if (!mount) return;
      try {
        const list = await Net.getJson('/api/agents');
        mount.innerHTML = _renderAgentsList(list || []);
      } catch (e) {
        mount.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
      }
      return;
    }
    // For the discover sections we already triggered the loaders
    // (loadCatalog → loadPluginsDiscover etc.). The relocator moves
    // the populated <details> into the section mount on boot, so
    // first visit just shows what's already there.
    if (name === 'models' && typeof loadCatalog === 'function' && !window.catalogLoaded) {
      try { loadCatalog(); } catch (_) {}
    }
    if (name === 'skills' && window.SkillsDiscover) {
      try { SkillsDiscover.load(); } catch (_) {}
    }
    if (name === 'plugins' && typeof loadPluginsDiscover === 'function') {
      try { loadPluginsDiscover(); } catch (_) {}
    }
    if (name === 'mcp' && typeof loadMcpsDiscover === 'function') {
      try { loadMcpsDiscover(); } catch (_) {}
    }
    if (name === 'external' && typeof loadExternalDiscover === 'function') {
      try { loadExternalDiscover(); } catch (_) {}
    }
  }

  function _renderAgentsList(list) {
    if (!list.length) {
      return '<div class="model-empty">No agents yet. Click + New Agent above to author one.</div>';
    }
    return list.map(a => {
      const persona = (window.AgentIcons ? AgentIcons.resolve(a) : 'general');
      const icon = (window.AgentIcons ? AgentIcons.svg(persona) : '');
      const tone = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');
      return `<div class="agent-tile" role="button" tabindex="0" aria-label="Open chat with ${esc(a.name || a.id)}" data-action="agents.chat" data-agent-id="${esc(a.id)}">
        <div class="agent-tile-head">
          <span class="agent-tile-icon tone-${esc(tone)}">${icon}</span>
          <div class="agent-tile-titleblock">
            <div class="agent-tile-title">${esc(a.name || a.id)}</div>
            <div class="agent-tile-subtitle">${esc((a.description || '').split('\n')[0].slice(0, 90))}</div>
          </div>
          <div class="agent-tile-actions">
            <button data-action="agents.edit"
                    class="agent-tile-action" title="Edit">✎</button>
            <button data-action="agents.delete"
                    class="agent-tile-action" title="Delete">✕</button>
          </div>
        </div>
        <div class="agent-tile-meta">
          ${(a.tags || []).map(t => `<span class="agent-tile-tag">${esc(t)}</span>`).join('')}
          ${a.role ? `<span class="agent-tile-tag tag-role">${esc(a.role)}</span>` : ''}
          ${a.model ? `<span class="agent-tile-tag tag-model">${esc(a.model)}</span>` : ''}
        </div>
      </div>`;
    }).join('');
  }

  return { show, _active, _loaded, _renderAgentsList };
})();
window.CatalogPage = CatalogPage;

// ── Skills Builder ───────────────────────────────────────────────────
// Authoring modal for a new skill. Posts to /api/skills/create which
// writes the markdown body to plugins/<plugin>/skills/<id>.md and
// registers it in the plugin's manifest.
const SkillsBuilder = (function () {
  function open() {
    const modal = document.getElementById('skill-builder-modal');
    if (!modal) return;
    // Populate the target-plugin dropdown from /api/plugins so the
    // operator can pick where the new skill lands.
    Net.getJson('/api/plugins', { silent: true }).then(data => {
      const list = Array.isArray(data) ? data : (data.plugins || []);
      const sel = document.getElementById('skill-builder-plugin');
      if (sel) {
        const ids = list.map(p => p.id).filter(Boolean);
        const def = ids.includes('general-skills') ? 'general-skills' : (ids[0] || '');
        sel.innerHTML = ids.map(id => `<option value="${esc(id)}"${id === def ? ' selected' : ''}>${esc(id)}</option>`).join('');
      }
    }).catch(() => {});
    modal.removeAttribute('hidden');
  }

  function close() {
    const modal = document.getElementById('skill-builder-modal');
    if (modal) modal.setAttribute('hidden', '');
    // Clear fields so the next open is fresh.
    ['skill-builder-id','skill-builder-name','skill-builder-desc','skill-builder-triggers','skill-builder-body']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const err = document.getElementById('skill-builder-error');
    if (err) { err.hidden = true; err.textContent = ''; }
  }

  async function submit() {
    const id = (document.getElementById('skill-builder-id') || {}).value || '';
    const name = (document.getElementById('skill-builder-name') || {}).value || '';
    const desc = (document.getElementById('skill-builder-desc') || {}).value || '';
    const plugin = (document.getElementById('skill-builder-plugin') || {}).value || '';
    const triggers = ((document.getElementById('skill-builder-triggers') || {}).value || '')
      .split(',').map(s => s.trim()).filter(Boolean);
    const body = (document.getElementById('skill-builder-body') || {}).value || '';
    const err = document.getElementById('skill-builder-error');

    function fail(msg) {
      if (err) { err.hidden = false; err.textContent = msg; }
    }
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) return fail('Skill ID must be alphanumeric/_/- (max 64 chars).');
    if (!name.trim())   return fail('Name is required.');
    if (!plugin)        return fail('Pick a target plugin.');
    if (!body.trim())   return fail('Body cannot be empty — that\'s the skill.');

    try {
      // retries:0 — creates a skill file. postJson's thrown message is
      // data.detail || data.error || 'HTTP n' — same copy reaches fail() below.
      await Net.postJson('/api/skills/create', {
        id, name, description: desc, plugin_id: plugin,
        triggers, body,
      }, { retries: 0 });
      if (window.Toast) Toast.success('Skill created', `${id} → ${plugin}`);
      close();
      // Refresh visible surfaces.
      if (window.SkillsDiscover) { try { SkillsDiscover.load(true); } catch (_) {} }
      if (window.SkillsPanel)    { try { SkillsPanel.load(); }       catch (_) {} }
    } catch (e) {
      fail(`Create failed: ${e.message}`);
    }
  }

  return { open, close, submit };
})();
window.SkillsBuilder = SkillsBuilder;

// WorkflowBuilder — the New-Workflow wizard. Same modal grammar as the
// Skill / Agent creators (validated slug id + name + defaults), but instead
// of POSTing a complete record it seeds the composer's identity fields and
// drops the operator on a blank canvas to build the step DAG (a workflow
// isn't complete until it has steps; Save/Run persist it from there).
const WorkflowBuilder = (function () {
  function _slugify(s) {
    return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
  }

  // Auto-suggest the id slug from the name until the operator edits the id
  // field themselves (the id input clears dataset.auto on manual input).
  function _maybeSlug() {
    const idEl = document.getElementById('workflow-builder-id');
    const nameEl = document.getElementById('workflow-builder-name');
    if (!idEl || !nameEl) return;
    if (!idEl.value || idEl.dataset.auto === '1') {
      idEl.value = _slugify(nameEl.value);
      idEl.dataset.auto = '1';
    }
  }

  function open() {
    const modal = document.getElementById('workflow-builder-modal');
    if (!modal) return;
    // Prefill from the composer toolbar so the wizard doubles as a
    // rename/redefine entry point for the in-progress workflow.
    const get = id => (document.getElementById(id) || {}).value || '';
    const set = (id, v) => { const el = document.getElementById(id); if (el && v) el.value = v; };
    set('workflow-builder-id', get('df-wf-id'));
    set('workflow-builder-name', get('df-wf-name'));
    set('workflow-builder-desc', get('df-wf-desc'));
    set('workflow-builder-role', get('df-wf-role'));
    set('workflow-builder-category', get('df-wf-category'));
    const err = document.getElementById('workflow-builder-error');
    if (err) { err.hidden = true; err.textContent = ''; }
    modal.removeAttribute('hidden');
    setTimeout(() => { const el = document.getElementById('workflow-builder-name'); if (el) el.focus(); }, 30);
  }

  function close() {
    const modal = document.getElementById('workflow-builder-modal');
    if (modal) modal.setAttribute('hidden', '');
    const err = document.getElementById('workflow-builder-error');
    if (err) { err.hidden = true; err.textContent = ''; }
  }

  function submit() {
    const id = ((document.getElementById('workflow-builder-id') || {}).value || '').trim();
    const name = ((document.getElementById('workflow-builder-name') || {}).value || '').trim();
    const desc = ((document.getElementById('workflow-builder-desc') || {}).value || '').trim();
    const role = (document.getElementById('workflow-builder-role') || {}).value || 'general';
    const category = (document.getElementById('workflow-builder-category') || {}).value || 'general';
    const err = document.getElementById('workflow-builder-error');
    function fail(msg) { if (err) { err.hidden = false; err.textContent = msg; } }

    if (!/^[a-z0-9-]+$/.test(id)) return fail('Workflow ID must be lowercase letters, digits, and hyphens only.');
    if (!name) return fail('Name is required.');

    // Ensure the drawflow editor exists before we blank + seed it (the wizard
    // can fire before the operator has ever opened the Composer tab).
    if (typeof ComposerView !== 'undefined' && ComposerView && ComposerView.init) {
      try { ComposerView.init(); } catch (_) {}
    }
    // Reset to a blank canvas, then write the identity into the toolbar
    // fields the rest of the composer (Save / Run) reads from.
    if (typeof composerNewWorkflow === 'function') { try { composerNewWorkflow(); } catch (_) {} }
    const set = (fid, v) => { const el = document.getElementById(fid); if (el) el.value = v; };
    set('df-wf-id', id);
    set('df-wf-name', name);
    set('df-wf-desc', desc);
    set('df-wf-role', role);
    set('df-wf-category', category);
    // Grow the auto-sizing description textarea to fit the seeded text.
    const descEl = document.getElementById('df-wf-desc');
    if (descEl) { descEl.style.height = 'auto'; descEl.style.height = Math.min(descEl.scrollHeight, 156) + 'px'; }

    close();
    if (typeof switchTab === 'function') switchTab('dashboard');
    if (window.Toast) Toast.success('Workflow created', `${name} — drag roles onto the canvas to add steps, then Save.`);
  }

  return { open, close, submit, _maybeSlug, _slugify };
})();
window.WorkflowBuilder = WorkflowBuilder;

// DfSeedSchema — the START anchor's seed-input editor. Edits the global
// dfSeedSchema ([{key, description}]); on save it redraws the anchors and the
// schema persists to context.inputs via dfExportYaml.
const DfSeedSchema = (function () {
  function _rows() { return document.getElementById('df-seed-rows'); }
  function _rowHtml(key, desc) {
    return `<div class="df-seed-row" style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
      <input type="text" class="df-seed-key" placeholder="thesis" value="${esc(key || '')}" style="flex:0 0 170px" autocomplete="off">
      <input type="text" class="df-seed-desc" placeholder="what this input is" value="${esc(desc || '')}" style="flex:1" autocomplete="off">
      <button type="button" class="action-btn xs" title="Remove" onclick="this.closest('.df-seed-row').remove()">×</button>
    </div>`;
  }
  function addRow(key, desc) {
    const r = _rows();
    if (r) r.insertAdjacentHTML('beforeend', _rowHtml(key, desc));
  }
  function open() {
    const m = document.getElementById('df-seed-modal');
    if (!m) return;
    const r = _rows();
    if (r) r.innerHTML = '';
    const seed = (dfSeedSchema && dfSeedSchema.length) ? dfSeedSchema : [{ key: '', description: '' }];
    seed.forEach(s => addRow(s.key, s.description));
    m.removeAttribute('hidden');
    setTimeout(() => { const i = m.querySelector('.df-seed-key'); if (i) i.focus(); }, 30);
  }
  function close() {
    const m = document.getElementById('df-seed-modal');
    if (m) m.setAttribute('hidden', '');
  }
  function save() {
    const out = [];
    document.querySelectorAll('#df-seed-rows .df-seed-row').forEach(row => {
      const rawKey = (row.querySelector('.df-seed-key') || {}).value || '';
      const desc = (row.querySelector('.df-seed-desc') || {}).value || '';
      // Normalize to a seed-ref-safe key (letters/digits/underscore).
      const key = rawKey.trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
      if (key) out.push({ key, description: desc.trim() });
    });
    dfSeedSchema = out;
    close();
    if (typeof dfRefreshAnchors === 'function') dfRefreshAnchors();
    if (window.Toast) Toast.success('Inputs saved', out.length ? out.map(s => s.key).join(', ') : 'no inputs declared');
  }
  return { open, close, addRow, save };
})();
window.DfSeedSchema = DfSeedSchema;

// Plugins / MCPs discover sections under the Models tab — small loaders
// that reuse the workbench renderers but mount into the System-page
// grids. Counts surface in the section header.
async function loadPluginsDiscover() {
  const grid = document.getElementById('plugins-discover-grid');
  if (!grid) return;
  try {
    const data = await Net.getJson('/api/plugins');
    const list = Array.isArray(data) ? data : (data.plugins || []);
    const countEl = document.getElementById('plugins-disc-count');
    if (countEl) countEl.textContent = list.length ? `(${list.length})` : '';
    // Re-use the workbench renderer; it expects to write to
    // #bench-plugins-list, so we swap the id-target by temporarily
    // pointing the helper at our grid.
    const tmpId = 'bench-plugins-list';
    const original = document.getElementById(tmpId);
    grid.id = tmpId;
    renderPluginsWorkbench(list);
    grid.id = 'plugins-discover-grid';
    if (original) original.id = tmpId;
  } catch (e) {
    grid.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed to load plugins: ${esc(e.message)}</div>`;
  }
}
async function loadMcpsDiscover() {
  const grid = document.getElementById('mcps-discover-grid');
  if (!grid) return;
  try {
    const data = await Net.getJson('/api/mcp/servers');
    const list = Array.isArray(data) ? data : (data.servers || []);
    const countEl = document.getElementById('mcps-disc-count');
    if (countEl) countEl.textContent = list.length ? `(${list.length})` : '';
    const tmpId = 'bench-mcps-list';
    const original = document.getElementById(tmpId);
    grid.id = tmpId;
    renderMcpsWorkbench(list);
    grid.id = 'mcps-discover-grid';
    if (original) original.id = tmpId;
  } catch (e) {
    grid.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed to load MCP servers: ${esc(e.message)}</div>`;
  }
}

// ── External Discovery loader ───────────────────────────────────────
// Lists every registered provider with a per-provider <details>
// section. Each section fetches its items lazily on open via the
// toggle handler so we don't fan out on every page load. The header
// chip shows the implementation status (✓ live, · stub).
async function loadExternalDiscover() {
  const host = document.getElementById('ext-discover-providers');
  if (!host) return;
  try {
    const d = await Net.getJson('/api/discover/sources');
    const providers = d.providers || [];
    const countEl = document.getElementById('ext-discover-count');
    if (countEl) {
      const live = providers.filter(p => p.implemented).length;
      countEl.textContent = providers.length ? `(${live}/${providers.length})` : '';
    }
    host.innerHTML = providers.map(_renderExternalProviderShell).join('');
  } catch (e) {
    host.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
  }
}

function _renderExternalProviderShell(p) {
  // Each provider gets its own <details>. The first open triggers
  // a lazy fetch; the result body lives inside .ext-prov-items.
  const status = p.implemented
    ? `<span class="ext-prov-status live" title="Real ingestion wired">live</span>`
    : `<span class="ext-prov-status stub" title="Provider registered but ingestion pipeline not yet wired — see api/services/discovery_providers">stub</span>`;
  const kindChips = (p.kinds || [])
    .map(k => `<span class="ext-prov-kind">${esc(k)}</span>`)
    .join('');
  return `<details class="ext-prov" data-source="${esc(p.source)}"
                   ${p.implemented ? '' : 'data-stub="1"'}
                   data-action="ext.toggle">
    <summary class="ext-prov-summary">
      <span class="ext-prov-name">${esc(p.name)}</span>
      ${status}
      ${kindChips}
      <span class="ext-prov-desc">${esc(p.description || '')}</span>
      <span style="flex:1"></span>
      <a href="${esc(p.homepage || '#')}" target="_blank" rel="noopener"
         onclick="event.stopPropagation()"
         class="ext-prov-link" title="Open the upstream homepage">↗</a>
    </summary>
    <div class="ext-prov-body" id="ext-prov-body-${esc(p.source)}">
      <div class="model-empty">Click to fetch from ${esc(p.name)}…</div>
    </div>
  </details>`;
}

const ExtDiscover = (function () {
  async function _toggle(detailsEl) {
    if (!detailsEl.open) return;
    const source = detailsEl.dataset.source;
    if (!source) return;
    const body = document.getElementById('ext-prov-body-' + source);
    if (!body) return;
    // Cache the fetch in-memory per session — re-clicking doesn't
    // re-hit the network unless the operator explicitly refreshes.
    if (body.dataset.loaded === '1') return;
    body.innerHTML = `<div class="model-empty">Fetching…</div>`;
    try {
      const feed = await Net.getJson(`/api/discover/${encodeURIComponent(source)}`);
      body.innerHTML = _renderFeedBody(feed, source);
      body.dataset.loaded = '1';
    } catch (e) {
      body.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
    }
  }

  async function refresh(source) {
    const body = document.getElementById('ext-prov-body-' + source);
    if (!body) return;
    body.innerHTML = `<div class="model-empty">Refreshing…</div>`;
    delete body.dataset.loaded;
    try {
      const feed = await Net.getJson(`/api/discover/${encodeURIComponent(source)}?force=true`);
      body.innerHTML = _renderFeedBody(feed, source);
      body.dataset.loaded = '1';
    } catch (e) {
      body.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
    }
  }

  function _renderFeedBody(feed, source) {
    const head = `<div class="ext-feed-head">
      <span class="ext-feed-count">${feed.count || 0} items</span>
      ${feed.last_synced
        ? `<span class="ext-feed-synced">synced ${new Date(feed.last_synced * 1000).toLocaleTimeString()}</span>`
        : ''}
      <span style="flex:1"></span>
      <button class="action-btn xs ghost" data-action="ext.refresh" data-source="${esc(source)}">⟲ Refresh</button>
    </div>`;
    if (feed.error) {
      return `${head}
        <div class="ext-feed-error">
          <span class="ext-feed-error-icon">!</span>
          <span>${esc(feed.error)}</span>
        </div>`;
    }
    if (!feed.items || !feed.items.length) {
      return `${head}<div class="model-empty">Provider returned no items.</div>`;
    }
    const items = feed.items.slice(0, 50).map(_renderItem).join('');
    // Cap at 50 cards per provider, but say so — silent truncation reads
    // as "that's everything" when it isn't.
    const more = feed.items.length > 50
      ? `<div class="model-empty">Showing 50 of ${feed.items.length} — refine the search to narrow results.</div>`
      : '';
    return `${head}<div class="ext-item-grid">${items}</div>${more}`;
  }

  function _renderItem(it) {
    const kindClass = `ext-item-kind-${esc(it.kind || 'other')}`;
    const toolCount = (it.tools || []).length;
    // Installable skills (e.g. the skills.sh provider) carry a raw SKILL.md
    // URL the native importer accepts. Render an Install action so the
    // External-Sources surface matches the Skills catalog's install
    // affordance instead of being display-only.
    const skillUrl = (it.kind === 'skill' && it.install && it.install.skill_md_url)
      ? it.install.skill_md_url : '';
    const installBtn = skillUrl
      ? `<button class="action-btn xs accent"
                 onclick="ExtDiscover.installSkill('${esc(skillUrl)}','${esc(it.id)}',this)"
                 title="Install this skill into general-skills">+ Install</button>`
      : '';
    // Surface the CLI one-liner (npx skills add …) when present.
    const cmd = (it.install && it.install.command) ? it.install.command : '';
    const cmdChip = cmd
      ? `<code class="ext-item-id" style="opacity:.75" title="CLI install">${esc(cmd)}</code>`
      : '';
    return `<div class="ext-item">
      <div class="ext-item-head">
        <span class="ext-item-kind ${kindClass}">${esc(it.kind || 'item')}</span>
        <span class="ext-item-name">${esc(it.name)}</span>
        <span class="ext-item-version">${esc(it.version || '')}</span>
        <span style="flex:1"></span>
        ${installBtn}
      </div>
      <div class="ext-item-desc">${esc(it.description || '')}</div>
      <div class="ext-item-foot">
        <code class="ext-item-id">${esc(it.id)}</code>
        ${cmdChip}
        ${toolCount ? `<span class="ext-item-toolcount">${toolCount} tools</span>` : ''}
        ${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener" class="ext-item-link">↗</a>` : ''}
      </div>
    </div>`;
  }

  // Install a discovered skill (kind=skill) via the same native importer
  // the Skills catalog uses, then refresh the Skills surfaces so a skill
  // found under External Sources lands in the catalog identically.
  async function installSkill(skillMdUrl, id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const r = await fetch('/api/skills/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: skillMdUrl, plugin_id: 'general-skills', id }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
      // Hot-reload the plugin registry so the skill activates immediately.
      try { await fetch('/api/plugins/reload', { method: 'POST' }); } catch (_) {}
      if (btn) { btn.textContent = '✓ Installed'; btn.classList.remove('accent'); btn.disabled = true; }
      if (window.Toast) Toast.success('Skill installed', `${d.name || id} → general-skills`);
      // Keep the two surfaces consistent: reflect the install in the Skills
      // catalog section, the catalog counts, and the composer workbench.
      if (window.SkillsDiscover && typeof SkillsDiscover.load === 'function') { try { SkillsDiscover.load(true); } catch (_) {} }
      if (typeof loadCatalogPage === 'function') { try { loadCatalogPage(); } catch (_) {} }
      if (typeof loadComposerCatalogs === 'function') { try { loadComposerCatalogs(); } catch (_) {} }
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
      if (window.Toast) Toast.error('Install failed: ' + e.message);
      else alert('Install failed: ' + e.message);
    }
  }

  return { _toggle, refresh, installSkill };
})();
window.ExtDiscover = ExtDiscover;

// Delegated actions for the external-discovery rails. `toggle` doesn't
// bubble — Actions registers toggle listeners with capture:true, so the
// document-level dispatcher still sees it on the <details> target. The
// homepage link's inline stopPropagation stays inline: a document-level
// handler runs too late to keep the click from activating the <summary>.
(function () {
  Actions.on('toggle', {
    'ext.toggle': el => ExtDiscover._toggle(el)
  });
  Actions.click({
    'ext.refresh': el => ExtDiscover.refresh(el.dataset.source)
  });
})();

function setFilter(f, el) {
  activeFilter = f;
  document.querySelectorAll('.inv-toolbar .filter-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  renderCatalog();
}

function filterCatalog() { renderCatalog(); }

function renderCatalog() {
  const search = (document.getElementById('inv-search').value || '').toLowerCase();
  let filtered = catalogData;

  if (activeFilter === 'installed') filtered = filtered.filter(m => m.installed);
  else if (activeFilter === 'available') filtered = filtered.filter(m => !m.installed);
  else if (activeFilter !== 'all') filtered = filtered.filter(m => (m.tags || []).includes(activeFilter));

  if (search) {
    filtered = filtered.filter(m =>
      m.name.toLowerCase().includes(search) ||
      m.id.toLowerCase().includes(search) ||
      m.description.toLowerCase().includes(search) ||
      (m.tags || []).some(t => t.includes(search))
    );
  }

  const installed = filtered.filter(m => m.installed).length;
  document.getElementById('inv-stats').innerHTML =
    `<span class="inv-stat">Showing <strong>${filtered.length}</strong> models</span>` +
    `<span class="inv-stat">Installed: <strong>${installed}</strong></span>` +
    `<span class="inv-stat">Available: <strong>${filtered.length - installed}</strong></span>`;

  if (filtered.length === 0) {
    document.getElementById('inv-grid').innerHTML = '<div class="model-empty">No models match filter</div>';
    return;
  }

  document.getElementById('inv-grid').innerHTML = filtered.map(m => {
    const badgeClass = m.installed ? 'installed' : 'available';
    const badgeText = m.installed ? 'installed' : 'available';
    const fitClass = m.fits_ram === false ? ' no-fit' : '';
    const tags = (m.tags || []).map(t => `<span class="tag ${tagClass(t)}">${t}</span>`).join('');

    let actions = '';
    // Uniform card action set — same vocabulary (Pull · Review · Test ·
    // Remove) and styling used across every catalog in the product.
    const repo = m.huggingface || m.gguf || '';
    const reviewBtn = repo
      ? `<button class="action-btn sm" data-action="models.review" data-repo="${esc(repo)}" title="View source on Hugging Face">Review</button>`
      : '';
    if (m.installed) {
      actions =
        `<button class="action-btn sm cyan" data-action="models.test" data-model="${esc(m.ollama || m.id)}" title="Open this model in the Composer chat">Test</button>` +
        reviewBtn +
        `<button class="action-btn sm danger" data-action="models.remove" data-model="${esc(m.ollama || m.id)}">Remove</button>`;
    } else {
      // GGUF-only models are now pullable via Ollama's hf.co/ path instead of
      // being a dead "GGUF only" label.
      const pullTarget = m.ollama || (m.gguf ? 'hf.co/' + m.gguf : '');
      const pullBtn = pullTarget
        ? `<button class="action-btn sm accent pull" id="pull-btn-${m.id}" data-action="models.pull" data-model="${esc(pullTarget)}" data-model-id="${m.id}">Pull</button>`
        : '';
      actions = pullBtn + reviewBtn;
    }

    return `
      <div class="inv-card ${badgeClass}${fitClass}">
        <div class="inv-card-header" onclick="AssetPeek.open('model','${esc(m.id)}')" style="cursor:pointer" title="Deep dive — specs, benchmarks, role fit">
          <div>
            <div class="inv-card-name">${esc(m.name)}</div>
            <div class="inv-card-id">${esc(m.id)}</div>
          </div>
          <span class="inv-card-badge ${badgeClass}">${badgeText}</span>
        </div>
        <div class="inv-card-desc">${esc(m.description)}</div>
        <div class="inv-card-meta">
          <span>Size: <span class="val">${m.size}</span></span>
          <span>Speed: <span class="val">${m.speed}</span></span>
          <span>Ctx: <span class="val">${m.context || '—'}</span></span>
        </div>
        <div class="inv-card-tags">${tags}</div>
        <div class="inv-card-actions">${actions}</div>
        <div class="pull-progress" id="progress-${m.id}" style="display:none">
          <div class="pull-progress-fill" id="progress-fill-${m.id}" style="width:0%"></div>
        </div>
        <div class="pull-progress-label" id="progress-label-${m.id}" style="display:none"></div>
      </div>
    `;
  }).join('');
}

// Uniform catalog actions — Review (inspect source) + Test (try it now).
// Same verbs are reused across Models / Skills / MCP / Agents catalogs.
function reviewModel(repo) {
  if (repo) window.open('https://huggingface.co/' + repo, '_blank', 'noopener');
}
function testModel(name) {
  // Jump to the Composer chat with this model preselected, ready to try.
  switchTab('dashboard');
  setTimeout(() => {
    const sel = document.getElementById('model-select');
    if (sel) {
      if (![...sel.options].some(o => o.value === name)) {
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name; sel.appendChild(opt);
      }
      sel.value = name;
      sel.dispatchEvent(new Event('change'));
    }
    const inp = document.querySelector('#agent-chat-input, .chat-input');
    if (inp) inp.focus();
  }, 250);
}

async function pullModel(ollamaName, modelId) {
  const btn = document.getElementById('pull-btn-' + modelId);
  const progressEl = document.getElementById('progress-' + modelId);
  const fillEl = document.getElementById('progress-fill-' + modelId);
  const labelEl = document.getElementById('progress-label-' + modelId);
  if (btn) { btn.disabled = true; btn.textContent = 'Pulling…'; }
  if (progressEl) progressEl.style.display = 'block';
  if (labelEl) { labelEl.style.display = 'block'; labelEl.textContent = 'starting…'; }
  // No byte totals yet → indeterminate shimmer.
  if (fillEl) fillEl.classList.add('indeterminate');

  const mb = b => (b / 1e6).toFixed(0);
  try {
    // retries:0 MANDATORY — a retried POST would double-trigger the multi-GB pull.
    await Net.postJson('/api/inventory/pull', { model: ollamaName }, { retries: 0 });

    const poll = setInterval(async () => {
      try {
        // 800ms poll — retries:0 so Net's backoff doesn't stack with the
        // interval timer; silent so a transient miss doesn't toast. The
        // catch below stays authoritative for failure handling (Retry).
        const d = await Net.getJson(
          '/api/inventory/pull-progress/' + encodeURIComponent(ollamaName),
          { silent: true, retries: 0 }
        );
        const phase = d.status_message || d.status || 'pulling';

        if (d.total > 0 && fillEl) {
          const pct = Math.round((d.progress / d.total) * 100);
          fillEl.classList.remove('indeterminate');
          fillEl.style.width = pct + '%';
          if (labelEl) labelEl.textContent = `${phase} — ${pct}%  (${mb(d.progress)} / ${mb(d.total)} MB)`;
          if (btn) btn.textContent = `Pulling ${pct}%`;
        } else if (labelEl) {
          labelEl.textContent = `${phase}…`;  // manifest / verify phases (no bytes)
        }

        if (d.status === 'complete' || d.status === 'error') {
          clearInterval(poll);
          if (d.status === 'complete') {
            if (fillEl) { fillEl.classList.remove('indeterminate'); fillEl.style.width = '100%'; }
            if (labelEl) { labelEl.textContent = '✓ installed'; labelEl.style.color = 'var(--green)'; }
            if (btn) btn.textContent = '✓ Installed';
            setTimeout(() => { catalogLoaded = false; loadCatalog(); if (typeof loadModels==='function') loadModels(); if (typeof loadInstalledLocal==='function') loadInstalledLocal(); }, 800);
          } else {
            if (fillEl) fillEl.classList.remove('indeterminate');
            if (labelEl) { labelEl.textContent = '✗ ' + (d.error || 'pull failed'); labelEl.style.color = 'var(--red)'; }
            if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
          }
        }
      } catch(e) { clearInterval(poll); if (btn){btn.disabled=false;btn.textContent='Retry';} }
    }, 800);
  } catch(e) {
    if (fillEl) fillEl.classList.remove('indeterminate');
    if (btn) { btn.disabled = false; btn.textContent = 'Pull'; }
    if (labelEl) { labelEl.textContent = '✗ ' + e.message; labelEl.style.color = 'var(--red)'; }
  }
}

async function removeModel(name) {
  const ok = await Confirm.ask({ title: 'Remove model', body: `Remove model "${name}"? This will delete the model files.`, okLabel: 'Remove', danger: true });
  if (!ok) return;
  try {
    // retries:0 — destructive remove.
    const d = await Net.postJson('/api/inventory/remove', { model: name }, { retries: 0 });
    if (d.status === 'removed') {
      catalogLoaded = false;
      loadCatalog();
      loadModels();
    }
  } catch(e) {}
}

/* ══════════════════════════════════════════════════════════════════
   MEMORY TAB
   ══════════════════════════════════════════════════════════════════ */

async function loadArchInfo() {
  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  try {
    const d = await Net.getJson('/api/system/architecture');
    // The endpoint returns the architecture under `arch` (not `architecture`);
    // reading the wrong key left every field as '—'.
    const arch = d.arch || d.architecture || {};
    const dep  = d.deployment  || {};
    const oll  = d.ollama      || {};

    const ARCH_LABELS = {
      apple_unified:     'Apple Unified (M-series)',
      cpu_x86:           'CPU x86 (no discrete GPU)',
      gpu_nvidia_single: 'NVIDIA Single-GPU',
      gpu_nvidia_multi:  'NVIDIA Multi-GPU',
    };
    const DEP_LABELS = {
      host_native: 'Host Native',
      container:   'Container',
      dmg_native:  'macOS DMG',
    };

    setText('arch-name',      ARCH_LABELS[arch.name] || arch.name || '—');
    setText('arch-mem-model', arch.memory_model || '—');
    setText('arch-total-mem', arch.total_memory_gb != null ? arch.total_memory_gb + ' GB' : '—');
    setText('arch-pools',     arch.pool_count    != null ? String(arch.pool_count) : '—');
    setText('arch-bw',        arch.bandwidth_estimate_gbps != null ? arch.bandwidth_estimate_gbps + ' GB/s' : '—');
    setText('arch-dep-mode',  DEP_LABELS[dep.mode] || dep.mode || '—');
    setText('arch-eff-ram',   dep.effective_memory_gb != null ? dep.effective_memory_gb + ' GB' : '—');

    const ver = oll.version || 'unreachable';
    const floorOk = oll.meets_floor !== false;
    const verEl = document.getElementById('arch-ollama-ver');
    if (verEl) {
      verEl.textContent = ver + (floorOk ? '' : ' ⚠ below floor');
      verEl.style.color = floorOk ? '' : 'var(--red)';
    }

    const memModelEl = document.getElementById('arch-mem-model');
    if (memModelEl) {
      memModelEl.style.color = arch.memory_model === 'unified' ? 'var(--cyan)' : '';
    }
  } catch(e) {
    setText('arch-name', 'Detection unavailable');
  }
}

async function loadMemory() {
  loadArchInfo();
  try {
    const [mem, sys] = await Promise.all([
      Net.getJson('/api/inventory/memory'),
      Net.getJson('/api/inventory/system')
    ]);

    // System memory bar
    const sysMem = sys.memory || {};
    const memPct = sysMem.percent || 0;
    const memClass = memPct > 85 ? 'danger' : memPct > 65 ? 'warn' : 'ok';
    document.getElementById('mem-sys-bars').innerHTML = `
      <div class="mem-bar-container">
        <div class="mem-bar-label">
          <span class="label">RAM Usage</span>
          <span class="value">${sysMem.used_gb || 0} / ${sysMem.total_gb || 0} GB (${memPct}%)</span>
        </div>
        <div class="mem-bar"><div class="mem-bar-fill ${memClass}" style="width:${memPct}%"></div></div>
      </div>
      <div class="mem-bar-container">
        <div class="mem-bar-label">
          <span class="label">Available for Models</span>
          <span class="value">${sysMem.available_gb || 0} GB free</span>
        </div>
        <div class="mem-bar"><div class="mem-bar-fill ok" style="width:${100 - memPct}%"></div></div>
      </div>
      <div class="metric-row"><span class="metric-key">CPU</span><span class="metric-val">${sys.cpu?.count_physical || '?'}C / ${sys.cpu?.count || '?'}T @ ${sys.cpu?.percent || 0}%</span></div>
      <div class="metric-row"><span class="metric-key">Hardware</span><span class="metric-val highlight">${sys.hardware?.name || 'Auto'}</span></div>
      ${(() => {
        // Surface the active Ollama perf knobs (LLM concurrency cap,
        // model keep-alive duration, request timeout) so operators
        // can see at a glance how the engine is tuned. Sourced from
        // /api/inventory/system's ollama_config block.
        const cfg = sys.ollama_config || {};
        const concur = cfg.max_concurrent_llm ?? 1;
        const ka = cfg.keep_alive ?? '10m';
        const timeout = cfg.request_timeout ?? 900;
        const ttl = cfg.model_list_ttl ?? 30;
        return `<div class="metric-row"><span class="metric-key">LLM Concurrency</span><span class="metric-val">${concur === 1 ? 'Serial (1)' : concur + ' parallel'}</span></div>
      <div class="metric-row"><span class="metric-key">Keep-Alive</span><span class="metric-val">${esc(String(ka))}</span></div>
      <div class="metric-row"><span class="metric-key">Request Timeout</span><span class="metric-val">${timeout}s</span></div>
      <div class="metric-row"><span class="metric-key">Model List TTL</span><span class="metric-val">${ttl}s</span></div>`;
      })()}
    `;

    // Disk bar
    const disk = sys.disk || {};
    const diskPct = disk.percent || 0;
    const diskClass = diskPct > 90 ? 'danger' : diskPct > 75 ? 'warn' : 'ok';
    document.getElementById('mem-disk-bars').innerHTML = `
      <div class="mem-bar-container">
        <div class="mem-bar-label">
          <span class="label">Disk Usage</span>
          <span class="value">${disk.used_gb || 0} / ${disk.total_gb || 0} GB (${diskPct}%)</span>
        </div>
        <div class="mem-bar"><div class="mem-bar-fill ${diskClass}" style="width:${diskPct}%"></div></div>
      </div>
      <div class="mem-bar-container">
        <div class="mem-bar-label">
          <span class="label">Free Space</span>
          <span class="value">${disk.free_gb || 0} GB</span>
        </div>
        <div class="mem-bar"><div class="mem-bar-fill ok" style="width:${100 - diskPct}%"></div></div>
      </div>
    `;

    // Running models
    const running = mem.running_models || [];
    // mem-count was removed from the markup; guard so a missing node doesn't
    // throw and abort the whole panel (which left "Running Models" showing a
    // "Cannot set properties of null" error instead of the model cards).
    const memCountEl = document.getElementById('mem-count');
    if (memCountEl) memCountEl.textContent = running.length > 0 ? `(${running.length})` : '';

    if (running.length === 0) {
      document.getElementById('mem-running').innerHTML =
        '<div class="model-empty">No models currently loaded in memory. Send a chat message to load one.</div>';
    } else {
      document.getElementById('mem-running').innerHTML = running.map(m => {
        const isVllm = m.backend === 'vllm';
        const expires = (m.expires_at && m.expires_at !== 'pinned')
          ? ` | Expires: ${new Date(m.expires_at).toLocaleTimeString()}` : '';
        const badge = `<span class="rm-backend rm-backend-${isVllm ? 'vllm' : 'ollama'}">${isVllm ? 'vLLM · GPU' : 'Ollama'}</span>`;
        const detail = isVllm
          ? 'Pinned · continuous batching'
          : `RAM: ${m.size_gb} GB${m.size_vram_gb > 0 ? ` | VRAM: ${m.size_vram_gb} GB` : ''}${expires}`;
        // vLLM pins its model at server start — there's nothing to unload.
        const action = isVllm
          ? `<span class="rm-pinned" title="vLLM loads its model at server start; restart the vllm service to change it">pinned</span>`
          : `<button class="action-btn unload" data-action="models.unload" data-model="${esc(m.name)}">Unload</button>`;
        return `<div class="running-model-card">
          <div class="rm-info">
            <div class="rm-name">${esc(m.name)} ${badge}</div>
            <div class="rm-detail">${detail}</div>
          </div>
          ${action}
        </div>`;
      }).join('');
    }
  } catch(e) {
    document.getElementById('mem-running').innerHTML =
      `<div class="model-empty" style="color:var(--red)">Failed to load memory info: ${e.message}</div>`;
  }
}

async function unloadModel(name) {
  try {
    await Net.postJson('/api/inventory/unload', { model: name }, { retries: 0 });
    loadMemory();
  } catch(e) {}
}

// Delegated actions for the Models surfaces — local-models list, catalog
// grid, memory panel, and the model-detail modal. The modal's former
// `${close}` snippet interpolation becomes models.close / compound modal
// actions; each button carries data-model (esc()'d) instead of an inline
// call. The detail card opens on dblclick, matching the old ondblclick.
(function () {
  const closeModal = el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); };
  Actions.click({
    'models.unload':       el => unloadModel(el.dataset.model),
    'models.remove-local': el => removeLocalModel(el.dataset.model),
    'models.remove':       el => removeModel(el.dataset.model),
    'models.test':         el => testModel(el.dataset.model),
    'models.review':       el => reviewModel(el.dataset.repo),
    'models.pull':         el => pullModel(el.dataset.model, el.dataset.modelId),
    'models.close':        closeModal,
    'models.open-workflows': el => { closeModal(el); switchTab('workflow-index'); },
    'models.modal-test':   el => { closeModal(el); testModel(el.dataset.model); }
  });
  Actions.on('dblclick', {
    'models.detail': el => openModelDetail(el.dataset.model)
  });
})();

/* ── Architecture & Pressure panel (Phase 2 observability) ──────────
 *
 * All dynamic strings are written via textContent — values come from the
 * trusted /api/system/* endpoints but the safe DOM API keeps us honest
 * even if a future arch impl reads gpu names from a less-trusted source
 * (e.g. NVML-reported model strings). No innerHTML in the dynamic path.
 */

const _ARCH_PRESSURE_POLL_MS = 5000;
window._archPressureTimer = null;

function _stopArchPressurePoll() {
  if (window._archPressureTimer) {
    clearInterval(window._archPressureTimer);
    window._archPressureTimer = null;
  }
}

function _archKvRow(key, value, opts) {
  const row = document.createElement('div');
  row.className = 'metric-row';
  const k = document.createElement('span');
  k.className = 'metric-key';
  k.textContent = key;
  const v = document.createElement('span');
  v.className = 'metric-val' + (opts && opts.highlight ? ' highlight' : '');
  v.textContent = value;
  if (opts && opts.color) v.style.color = opts.color;
  if (opts && opts.uppercase) {
    v.style.textTransform = 'uppercase';
    v.style.letterSpacing = '0.05em';
  }
  row.appendChild(k);
  row.appendChild(v);
  return row;
}

function _renderArchPressure(arch, deployment, ollama, pressure) {
  const root = document.getElementById('arch-pressure-content');
  if (!root) return;
  // Clear; the rebuild is cheap and ensures stale rows don't linger.
  while (root.firstChild) root.removeChild(root.firstChild);

  const poolCount = arch.pool_count ?? 1;
  root.appendChild(_archKvRow('Arch', arch.name || '?', { highlight: true }));
  root.appendChild(_archKvRow('Memory Model',
    (arch.memory_model || '?') + ' · ' + poolCount + ' pool' + (poolCount !== 1 ? 's' : '')));
  root.appendChild(_archKvRow('Total Memory', (arch.total_memory_gb || 0).toFixed(1) + ' GB'));
  root.appendChild(_archKvRow('Bandwidth', (arch.bandwidth_estimate_gbps || 0).toFixed(0) + ' GB/s'));
  (arch.gpus || []).forEach(g => {
    root.appendChild(_archKvRow(
      'GPU ' + (g.gpu_id ?? 0),
      (g.name || '?') + ' · ' + (g.vram_total_gb || 0).toFixed(0) + ' GB VRAM'
    ));
  });
  root.appendChild(_archKvRow('Deployment',
    (deployment.mode || '?') + ' · ' + (deployment.effective_memory_gb || 0).toFixed(1) + ' GB effective'));
  const ollamaVer = (ollama && ollama.version) || 'unreachable';
  const ollamaSuffix = (ollama && ollama.meets_floor === false) ? ' (below floor)' : '';
  root.appendChild(_archKvRow('Ollama', ollamaVer + ollamaSuffix,
    ollama && ollama.meets_floor === false ? { color: 'var(--orange, #E08A4C)' } : undefined));

  // Pressure section — visually separated.
  const sep = document.createElement('div');
  sep.style.borderTop = '1px solid var(--border)';
  sep.style.marginTop = '8px';
  sep.style.paddingTop = '8px';
  root.appendChild(sep);

  const lvl = (pressure && pressure.level) || 'unknown';
  const lvlColor = lvl === 'critical' ? 'var(--red, #ff5252)'
                 : lvl === 'warning'  ? 'var(--orange, #E08A4C)'
                 : lvl === 'ok'       ? 'var(--green, #00E87B)'
                 :                      'var(--text-dim)';
  root.appendChild(_archKvRow('Pressure', lvl, { color: lvlColor, uppercase: true }));
  (pressure && Array.isArray(pressure.per_pool) ? pressure.per_pool : []).forEach((p, i) => {
    root.appendChild(_archKvRow(
      'Pool ' + i,
      (p.free_gb ?? 0).toFixed(1) + ' GB free · ' + (p.used_gb ?? 0).toFixed(1) + ' GB used'
    ));
  });
}

function _renderArchError(msg, color) {
  const root = document.getElementById('arch-pressure-content');
  if (!root) return;
  while (root.firstChild) root.removeChild(root.firstChild);
  const div = document.createElement('div');
  div.className = 'model-empty';
  if (color) div.style.color = color;
  div.textContent = msg;
  root.appendChild(div);
}

async function loadArchitecturePanel() {
  _stopArchPressurePoll();
  try {
    // Net.call (not getJson): the status code is user-facing copy below.
    const archRes = await Net.call('/api/system/architecture');
    if (!archRes.ok) {
      _renderArchError('Architecture detection unavailable (status ' + archRes.status + ').');
      return;
    }
    const triple = archRes.data;
    _renderArchPressure(triple.arch, triple.deployment, triple.ollama, null);

    const pollOnce = async () => {
      try {
        // Interval poll — silent + retries:0 so Net's backoff doesn't
        // stack with the poll timer; failures keep the last good paint.
        const pressure = await Net.getJson('/api/system/pressure', { silent: true, retries: 0 });
        _renderArchPressure(triple.arch, triple.deployment, triple.ollama, pressure);
      } catch(_) { /* keep the last good paint on transient failures */ }
    };
    pollOnce();
    window._archPressureTimer = setInterval(pollOnce, _ARCH_PRESSURE_POLL_MS);
  } catch(e) {
    _renderArchError('Failed to load architecture: ' + e.message, 'var(--red)');
  }
}

async function refreshArchitectureDetection() {
  const btn = document.getElementById('arch-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Re-detecting…'; }
  try {
    // Net.call keeps the 'refresh returned N' copy. retries:0 — triggers re-detection.
    const r = await Net.call('/api/system/architecture/refresh', { retries: 0, init: { method: 'POST' } });
    if (!r.ok) throw new Error('refresh returned ' + r.status);
    await loadArchitecturePanel();
  } catch(e) {
    _renderArchError('Re-detect failed: ' + e.message, 'var(--red)');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Re-detect'; }
  }
}

/* ══════════════════════════════════════════════════════════════════
   DISCOVER TAB
   ══════════════════════════════════════════════════════════════════ */

let discoverData = [];
let discoverLoaded = false;
let discFilter = 'all';

// Lazy-load the HuggingFace discovery the first time the Discover
// sub-section is expanded inside the Models tab. Saves the network
// scan on Models-tab visits when the user doesn't need it.
document.addEventListener('DOMContentLoaded', () => {
  const sect = document.getElementById('discover-section');
  if (!sect) return;
  sect.addEventListener('toggle', () => {
    if (sect.open && !discoverLoaded) loadDiscovery();
  });
});

async function loadDiscovery(force = false) {
  const url = '/api/inventory/discover' + (force ? '?force=true' : '');
  try {
    document.getElementById('disc-refresh-btn').disabled = true;
    document.getElementById('disc-refresh-btn').textContent = force ? 'Scanning...' : 'Loading...';

    const d = await Net.getJson(url);
    discoverData = d.models || [];
    discoverLoaded = true;

    // Update tab count
    document.getElementById('disc-count').textContent = discoverData.length > 0 ? `(${discoverData.length})` : '';

    // Show timestamp
    if (d.timestamp) {
      const ts = new Date(d.timestamp);
      document.getElementById('disc-status').innerHTML =
        `Last scan: ${ts.toLocaleString()} &mdash; ${discoverData.length} models found` +
        (d.cache_fresh ? ' (cached)' : ' (fresh)');
    }

    // Show trusted authors
    if (d.trusted_authors) {
      document.getElementById('disc-authors').textContent =
        'Monitoring: ' + d.trusted_authors.join(', ');
    }

    renderDiscovery();
  } catch(e) {
    document.getElementById('disc-grid').innerHTML =
      `<div class="model-empty" style="color:var(--red)">Discovery failed: ${e.message}</div>`;
  } finally {
    document.getElementById('disc-refresh-btn').disabled = false;
    document.getElementById('disc-refresh-btn').textContent = 'Scan Now';
  }
}

function refreshDiscovery() {
  loadDiscovery(true);
}

function setDiscFilter(f, el) {
  discFilter = f;
  document.querySelectorAll('#tab-discover .inv-toolbar .filter-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  renderDiscovery();
}

function renderDiscovery() {
  const search = (document.getElementById('disc-search').value || '').toLowerCase();
  let filtered = discoverData;

  if (discFilter === 'trusted') filtered = filtered.filter(m => m.is_trusted_author);
  else if (discFilter === 'gguf') filtered = filtered.filter(m => m.has_gguf);
  else if (discFilter === 'large-ctx') filtered = filtered.filter(m => (m.context_window || 0) >= 128000);

  if (search) {
    filtered = filtered.filter(m =>
      (m.repo_id || '').toLowerCase().includes(search) ||
      (m.name || '').toLowerCase().includes(search) ||
      (m.author || '').toLowerCase().includes(search) ||
      (m.tags || []).some(t => t.toLowerCase().includes(search))
    );
  }

  const ggufCount = filtered.filter(m => m.has_gguf).length;
  const trustedCount = filtered.filter(m => m.is_trusted_author).length;
  document.getElementById('disc-stats').innerHTML =
    `<span class="inv-stat">Showing <strong>${filtered.length}</strong> models</span>` +
    `<span class="inv-stat">GGUF Ready: <strong>${ggufCount}</strong></span>` +
    `<span class="inv-stat">Trusted Authors: <strong>${trustedCount}</strong></span>`;

  if (filtered.length === 0) {
    document.getElementById('disc-grid').innerHTML =
      '<div class="model-empty">No models match filter. Try "Scan Now" to refresh.</div>';
    return;
  }

  document.getElementById('disc-grid').innerHTML = filtered.map(m => {
    const ctxStr = m.context_window ? (m.context_window >= 1000 ? Math.round(m.context_window/1000) + 'K' : m.context_window) : '?';
    const sizeStr = m.estimated_size_gb > 0 ? m.estimated_size_gb + 'GB' : '?';
    const paramStr = m.param_size || '?';
    const fitClass = m.fits_ram === false ? ' no-fit' : '';

    const badges = [];
    if (m.is_abliterated) badges.push('<span class="tag abliterated">abliterated</span>');
    if (m.is_trusted_author) badges.push('<span class="tag fast">trusted</span>');
    if (m.has_gguf) badges.push('<span class="tag coding">gguf</span>');

    // Show select tags from HF
    const skipTags = new Set(['transformers', 'pytorch', 'safetensors', 'text-generation', 'gguf', 'en', 'license:apache-2.0', 'license:other']);
    const hfTags = (m.tags || [])
      .filter(t => !skipTags.has(t) && t.length < 25)
      .slice(0, 4)
      .map(t => `<span class="tag">${esc(t)}</span>`);

    return `
      <div class="inv-card available${fitClass}">
        <div class="inv-card-header">
          <div>
            <div class="inv-card-name">${esc(m.name)}</div>
            <div class="inv-card-id">${esc(m.author)} &mdash; Score: ${m.score}</div>
          </div>
          <span class="inv-card-badge available">${paramStr}</span>
        </div>
        <div class="inv-card-meta">
          <span>Size: <span class="val">${sizeStr}</span></span>
          <span>Ctx: <span class="val">${ctxStr}</span></span>
          <span>DL: <span class="val">${(m.downloads || 0).toLocaleString()}</span></span>
          <span>Likes: <span class="val">${m.likes || 0}</span></span>
        </div>
        <div class="inv-card-tags">${badges.join('')}${hfTags.join('')}</div>
        <div class="inv-card-actions">
          <a href="https://huggingface.co/${esc(m.repo_id)}" target="_blank" rel="noopener"
             class="action-btn" style="text-decoration:none">View on HF</a>
        </div>
      </div>
    `;
  }).join('');
}

/* ── RESEARCH TAB ────────────────────────────────────────────────── */
let graphData = null;
let graphSim = null;
let selectedNode = null;
let researchLoaded = false;

function initResearch() {
  // Rehydrate the last research result every time the tab is shown.
  // This is what makes tab-switch-and-back keep the result visible.
  // window._lastResearch is set by renderResearchResults; nothing to do
  // if we don't have one yet.
  if (researchLoaded) {
    if (window._lastResearch) {
      try { renderResearchResults(window._lastResearch); } catch (_) {}
    } else if (window._researchInFlight) {
      _renderResearchInFlight(window._researchInFlight);
    }
    return;
  }
  researchLoaded = true;
  loadGraphData();
  populateResModelSelect();
  document.getElementById('res-depth').addEventListener('input', function() {
    document.getElementById('depth-hint').textContent = this.value + ' sub-questions';
  });
  // Open the Discover panel lazily — first paint loads the catalog.
  const disc = document.getElementById('skills-discover-panel');
  if (disc && !disc._initBound) {
    disc._initBound = true;
    disc.addEventListener('toggle', () => {
      if (disc.open && window.SkillsDiscover) SkillsDiscover.load();
    });
  }
}

function _renderResearchInFlight(state) {
  const out = document.getElementById('research-output');
  if (!out) return;
  out.innerHTML = `
    <div class="research-steps" id="res-steps">
      <div class="research-step ${state.stage === 'decompose' ? 'active' : state.passed.includes('decompose') ? 'done' : ''}"><span class="step-icon">🔬</span> Decomposing topic into sub-questions…</div>
      <div class="research-step ${state.stage === 'search' ? 'active' : state.passed.includes('search') ? 'done' : ''}"><span class="step-icon">🌐</span> Searching each angle…</div>
      <div class="research-step ${state.stage === 'synth' ? 'active' : state.passed.includes('synth') ? 'done' : ''}"><span class="step-icon">🧠</span> Synthesizing report…</div>
    </div>
    <div style="margin-top:10px;font-size:0.7rem;color:var(--text-muted)">
      Research running in the background for: <strong>${esc(state.topic)}</strong>.
      Safe to switch tabs — results will be here when you return.
    </div>
  `;
}

async function populateResModelSelect() {
  const sel = document.getElementById('res-model-select');
  try {
    const d = await Net.getJson('/v1/models', { silent: true });
    const models = d.data || [];
    sel.innerHTML = models.map(m => `<option value="${esc(m.id)}">${esc(m.id)}</option>`).join('');
    if (!sel.innerHTML) sel.innerHTML = '<option value="dolphin3:latest">dolphin3:latest</option>';
  } catch {
    sel.innerHTML = '<option value="dolphin3:latest">dolphin3:latest</option>';
  }
}

async function loadGraphData() {
  try {
    graphData = await Net.getJson('/api/graph');
    // Expose the dataset to window so the legend toggle handlers can
    // re-render without a network round-trip.
    window.graphData = graphData;
    renderGraph(graphData);
    updateResCount();
  } catch (e) {
    console.error('Graph load failed', e);
  }
}

async function rebuildGraph() {
  try {
    await Net.postJson('/api/graph/rebuild', {}, { retries: 0 });
    await loadGraphData();
  } catch (e) {
    console.error('Rebuild failed', e);
  }
}

function updateResCount() {
  const el = document.getElementById('res-count');
  if (!el) return;  // node was removed from the markup — don't throw + abort graph load
  el.textContent = (graphData && graphData.session_count) || '';
}

function resetGraphZoom() {
  if (!graphSim || !window._graphZoomBehavior) return;
  const svg = d3.select('#graph-svg');
  svg.transition().duration(400).call(
    window._graphZoomBehavior.transform,
    d3.zoomIdentity
  );
}
// Manual +/- zoom — bound to explicit buttons. Mouse-wheel zoom on
// the graph is disabled (it was capturing page scroll); these are
// the only way to change zoom programmatically along with the
// reset button.
function graphZoomIn()  { _stepGraphZoom(1.3); }
function graphZoomOut() { _stepGraphZoom(1 / 1.3); }
function _stepGraphZoom(factor) {
  if (!window._graphZoomBehavior) return;
  const svg = d3.select('#graph-svg');
  svg.transition().duration(200).call(
    window._graphZoomBehavior.scaleBy, factor
  );
}
window.graphZoomIn = graphZoomIn;
window.graphZoomOut = graphZoomOut;

// Graph config — lives across renders so the user's toggle choices
// survive a rebuild. Sliders + toggles are persisted to localStorage
// under the `enclave.graphConfig` key so reloads keep the same view.
//
// Modeled on the Obsidian graph view's settings panel:
//   - Display:  node scale, link width, link opacity, label fade, arrows
//   - Forces :  charge (repel), link distance, link strength, center
//
// Numeric values are stored as plain numbers (sliders read/write them
// directly). `linkKinds` stays a Set because it's a categorical filter.
const _GRAPH_CONFIG_DEFAULTS = {
  // Display
  nodeScale: 1.0,        // multiplier on nodeRadius output (0.5–2.0)
  linkWidth: 1.0,        // multiplier on link stroke-width (0.5–4.0)
  linkOpacity: 1.0,      // 0.2 → 1.0
  labelFadeZoom: 1.0,    // hide session labels below this zoom (0.4–2.0)
  showArrows: false,     // arrowheads on directed edges
  // Forces
  charge: -200,          // repel strength (more negative = stronger repel)
  linkDistance: 80,      // px between connected nodes
  linkStrength: 0.5,     // 0.05 → 1.0
  centerStrength: 0.05,  // gravitational pull to center (0 → 0.5)
  // Categorical
  linkKinds: new Set(),  // empty = show all
  sizingMode: 'importance', // 'importance' | 'content' | 'hybrid'
};

window.graphConfig = window.graphConfig || _loadGraphConfig();

function _loadGraphConfig() {
  // Merge defaults with whatever the operator persisted. linkKinds
  // round-trips as an array; rebuild the Set on load.
  const merged = Object.assign({}, _GRAPH_CONFIG_DEFAULTS, {
    linkKinds: new Set(_GRAPH_CONFIG_DEFAULTS.linkKinds),
  });
  try {
    const raw = localStorage.getItem('enclave.graphConfig');
    if (!raw) return merged;
    const saved = JSON.parse(raw);
    Object.keys(merged).forEach(k => {
      if (k === 'linkKinds') {
        if (Array.isArray(saved.linkKinds)) merged.linkKinds = new Set(saved.linkKinds);
      } else if (saved[k] !== undefined) {
        merged[k] = saved[k];
      }
    });
  } catch (_) {}
  return merged;
}

function _saveGraphConfig() {
  try {
    const c = window.graphConfig;
    const out = Object.assign({}, c, { linkKinds: Array.from(c.linkKinds || []) });
    localStorage.setItem('enclave.graphConfig', JSON.stringify(out));
  } catch (_) { /* private mode / quota — non-fatal */ }
}

function _renderGraphLegendToggles(data) {
  // Safety: every interpolated value below is either (a) escaped via
  // esc(), (b) sourced from the hardcoded LINK_STYLE map, or (c) a
  // numeric count. No raw user input reaches innerHTML.
  const row = document.getElementById('graph-link-filter');
  const picker = document.getElementById('graph-sizing-picker');
  if (!row || !picker) return;
  const counts = {};
  (data.links || []).forEach(l => { counts[l.type] = (counts[l.type] || 0) + 1; });
  const present = Object.keys(counts).sort();
  if (!present.length) {
    row.textContent = '';
    picker.textContent = '';
    return;
  }
  const active = window.graphConfig.linkKinds;
  const chips = present.map(kind => {
    const s = (typeof LINK_STYLE !== 'undefined' && LINK_STYLE[kind]) || { label: kind, tone: 'amber', color: '#ff8c0040' };
    const on = (!active.size || active.has(kind));
    return `<button type="button" class="link-kind-chip tone-${esc(s.tone)} ${on ? 'on' : 'off'}"
              data-kind="${esc(kind)}"
              data-action="graph.link-kind"
              title="${esc(kind)} — ${counts[kind]} link${counts[kind] === 1 ? '' : 's'}">
      <span class="link-kind-swatch" style="background:${esc(s.color)}"></span>
      <span>${esc(s.label || kind)}</span>
      <span class="link-kind-count">${counts[kind]}</span>
    </button>`;
  });
  row.innerHTML = '<span class="legend-row-label">Show</span>' + chips.join('') +
    ' <button type="button" class="link-kind-chip reset" data-action="graph.link-reset" title="Show all link kinds">All</button>';

  const modes = [
    ['importance', 'Importance', 'Size by reference count / citations / tag count'],
    ['content',    'Content',    'Size by artifact byte budget (description + prompt + outputs)'],
    ['hybrid',     'Hybrid',     'Mix of importance + content, capped'],
    ['tokens',     'Tokens',     'Size by token usage — LLM tokens consumed at that node'],
  ];
  picker.innerHTML = '<span class="legend-row-label">Size by</span>' + modes.map(([k, label, help]) =>
    `<button type="button" class="link-kind-chip ${graphConfig.sizingMode === k ? 'on' : 'off'}"
       data-mode="${esc(k)}"
       data-action="graph.sizing"
       title="${esc(help)}">${esc(label)}</button>`
  ).join('');
}

function toggleGraphLinkKind(kind) {
  const s = window.graphConfig.linkKinds;
  if (s.has(kind)) s.delete(kind);
  else s.add(kind);
  if (window.graphData) renderGraph(window.graphData);
}
function resetGraphLinkFilter() {
  window.graphConfig.linkKinds = new Set();
  if (window.graphData) renderGraph(window.graphData);
}
function setGraphSizingMode(mode) {
  window.graphConfig.sizingMode = mode;
  _saveGraphConfig();
  if (window.graphData) renderGraph(window.graphData);
}
window.toggleGraphLinkKind   = toggleGraphLinkKind;
window.resetGraphLinkFilter  = resetGraphLinkFilter;
window.setGraphSizingMode    = setGraphSizingMode;

// ── Obsidian-style Graph Config panel ────────────────────────────────
// Slider rail for visual + force tuning. Renders once into
// #graph-config-body; each slider updates window.graphConfig live
// and re-renders the graph. Saves to localStorage on change.
const _GRAPH_CONFIG_FIELDS = [
  // [key, label, min, max, step, suffix, group]
  { k: 'nodeScale',     label: 'Node size',       min: 0.3, max: 2.5, step: 0.05, group: 'Display' },
  { k: 'linkWidth',     label: 'Link width',      min: 0.3, max: 5.0, step: 0.1,  group: 'Display' },
  { k: 'linkOpacity',   label: 'Link opacity',    min: 0.1, max: 1.0, step: 0.05, group: 'Display' },
  { k: 'labelFadeZoom', label: 'Label fade ≤',    min: 0.3, max: 2.5, step: 0.1,  group: 'Display' },
  { k: 'showArrows',    label: 'Arrows',          type: 'toggle',             group: 'Display' },
  { k: 'charge',        label: 'Repel force',     min: -800, max: -20, step: 10, group: 'Forces' },
  { k: 'linkDistance',  label: 'Link distance',   min: 30,  max: 300, step: 5,   group: 'Forces' },
  { k: 'linkStrength',  label: 'Link strength',   min: 0.05, max: 1.0, step: 0.05, group: 'Forces' },
  { k: 'centerStrength',label: 'Center gravity',  min: 0,   max: 0.5, step: 0.01, group: 'Forces' },
];

function _renderGraphConfigPanel() {
  const body = document.getElementById('graph-config-body');
  if (!body) return;
  const cfg = window.graphConfig;
  const groups = {};
  _GRAPH_CONFIG_FIELDS.forEach(f => { (groups[f.group] = groups[f.group] || []).push(f); });
  const html = Object.keys(groups).map(g => {
    const rows = groups[g].map(f => {
      const v = cfg[f.k];
      if (f.type === 'toggle') {
        return `<div class="gc-row">
          <label class="gc-label" for="gc-${esc(f.k)}">${esc(f.label)}</label>
          <input type="checkbox" id="gc-${esc(f.k)}" class="gc-toggle"
                 ${v ? 'checked' : ''}
                 data-action="graph.config-toggle" data-key="${esc(f.k)}" />
        </div>`;
      }
      const displayVal = Number.isInteger(f.step) ? v : Number(v).toFixed(2);
      return `<div class="gc-row">
        <label class="gc-label" for="gc-${esc(f.k)}">${esc(f.label)}</label>
        <input type="range" id="gc-${esc(f.k)}" class="gc-slider"
               min="${f.min}" max="${f.max}" step="${f.step}" value="${esc(String(v))}"
               data-action="graph.config-slider" data-key="${esc(f.k)}" />
        <span class="gc-val" id="gc-val-${esc(f.k)}">${esc(String(displayVal))}</span>
      </div>`;
    }).join('');
    return `<div class="gc-group">
      <div class="gc-group-head">${esc(g)}</div>
      ${rows}
    </div>`;
  }).join('');
  body.innerHTML = html;
}

function setGraphConfigValue(key, value) {
  if (!_GRAPH_CONFIG_FIELDS.find(f => f.k === key)) return;
  window.graphConfig[key] = value;
  _saveGraphConfig();
  // Update the readout next to the slider without a full re-render so
  // the drag feels live.
  const valEl = document.getElementById(`gc-val-${key}`);
  if (valEl) {
    const f = _GRAPH_CONFIG_FIELDS.find(x => x.k === key);
    valEl.textContent = (f && Number.isInteger(f.step)) ? value : Number(value).toFixed(2);
  }
  // Trigger a re-render. For force changes we just bump the running
  // simulation instead of rebuilding the SVG, which is much smoother.
  if (['charge', 'linkDistance', 'linkStrength', 'centerStrength'].includes(key)) {
    _applyGraphForces();
  } else if (window.graphData) {
    renderGraph(window.graphData);
  }
}

// Delegated actions for the graph config panel + legend — chips and the
// slider rail re-render whenever the panel opens or the graph reloads.
// Slider values coerce via parseFloat (same as the old inline oninput);
// the toggle reads el.checked directly.
Actions.click({
  'graph.link-kind':  el => toggleGraphLinkKind(el.dataset.kind),
  'graph.link-reset': () => resetGraphLinkFilter(),
  'graph.sizing':     el => setGraphSizingMode(el.dataset.mode)
});
Actions.change({
  'graph.config-toggle': el => setGraphConfigValue(el.dataset.key, el.checked)
});
Actions.input({
  'graph.config-slider': el => setGraphConfigValue(el.dataset.key, parseFloat(el.value))
});

function _applyGraphForces() {
  const sim = window.graphSim;
  const cfg = window.graphConfig;
  if (!sim) return;
  const linkF = sim.force('link');
  const chargeF = sim.force('charge');
  const centerF = sim.force('center');
  if (linkF)   linkF.distance(cfg.linkDistance).strength(cfg.linkStrength);
  if (chargeF) chargeF.strength(cfg.charge);
  // forceCenter doesn't have its own strength; emulate via a forceX/forceY
  // gravity term if needed. For simplicity nudge alpha so the existing
  // center force re-engages.
  sim.alpha(0.4).restart();
}

function toggleGraphConfigPanel(force) {
  const panel = document.getElementById('graph-config-panel');
  const btn = document.getElementById('graph-config-toggle');
  if (!panel) return;
  const willOpen = force === undefined ? panel.hasAttribute('hidden') : !!force;
  if (willOpen) {
    panel.removeAttribute('hidden');
    _renderGraphConfigPanel();
    if (btn) btn.classList.add('active');
  } else {
    panel.setAttribute('hidden', '');
    if (btn) btn.classList.remove('active');
  }
}

function resetGraphConfigDefaults() {
  const linkKinds = window.graphConfig.linkKinds;  // preserve filter selection
  const sizingMode = window.graphConfig.sizingMode;
  window.graphConfig = Object.assign({}, _GRAPH_CONFIG_DEFAULTS, {
    linkKinds: new Set(linkKinds),
    sizingMode,
  });
  _saveGraphConfig();
  _renderGraphConfigPanel();
  if (window.graphData) renderGraph(window.graphData);
}

window.toggleGraphConfigPanel  = toggleGraphConfigPanel;
window.setGraphConfigValue     = setGraphConfigValue;
window.resetGraphConfigDefaults = resetGraphConfigDefaults;

function renderGraph(data) {
  const svgEl = document.getElementById('graph-svg');
  const W = svgEl.clientWidth || 600;
  const H = svgEl.clientHeight || 400;

  d3.select('#graph-svg').selectAll('*').remove();

  if (!data || !data.nodes || data.nodes.length === 0) {
    d3.select('#graph-svg').append('text')
      .attr('x', W / 2).attr('y', H / 2)
      .attr('text-anchor', 'middle')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('font-size', '12px')
      .attr('fill', '#556677')
      .text('No sessions exported yet. Export a chat to build the graph.');
    return;
  }

  const svg = d3.select('#graph-svg');
  const g = svg.append('g');

  // Zoom + pan. The zoom level also drives label fade-out — session
  // labels (cluttering at fully-zoomed-in views) hide below the
  // labelFadeZoom threshold from the config panel.
  //
  // IMPORTANT: wheel-zoom is filtered OUT. d3.zoom() defaults to
  // capturing the mouse wheel — that competes with page scroll
  // when the user wants to scroll past the graph on the Context
  // page. Operators zoom via the explicit +/− buttons in the
  // controls toolbar instead.
  const zoom = d3.zoom()
    .scaleExtent([0.2, 4])
    .filter(e => {
      // Disable wheel-driven zoom (lets the page scroll naturally
      // when the cursor passes over the graph). Still allow drag-
      // to-pan + the programmatic zoom-via-button path.
      if (e.type === 'wheel') return false;
      return !e.ctrlKey && !e.button;
    })
    .on('zoom', (e) => {
      g.attr('transform', e.transform);
      const fade = (window.graphConfig && graphConfig.labelFadeZoom) || 1.0;
      g.selectAll('text.gn-session-label')
        .attr('opacity', e.transform.k >= fade ? 1 : 0);
    });
  svg.call(zoom);
  // Expose the zoom behavior so the explicit +/− buttons can call
  // .scaleBy / .transform against it. Stored on window so it
  // survives across renderGraph() invocations.
  window._graphZoomBehavior = zoom;

  const nodeColor = (d) => {
    if (d.type === 'session')      return 'var(--cyan)';
    if (d.type === 'topic')        return 'var(--amber)';
    if (d.type === 'source')       return 'var(--purple)';
    if (d.type === 'agent')        return 'var(--accent)';
    if (d.type === 'workflow_run') return 'var(--cyan)';
    return 'var(--text-dim)';
  };

  // Node "weight" — used to size each node by its importance/artifact
  // size. Choose one of three strategies via graphConfig.sizingMode:
  //   'importance' : count + reference-driven (default)
  //   'content'    : artifact-byte-driven (description + prompts + outputs)
  //   'hybrid'     : a + b, capped
  // The actual radius formula is: base + sqrt(weight) * k, clamped.
  function _nodeWeight(d) {
    const mode = (window.graphConfig && graphConfig.sizingMode) || 'importance';
    let importance = 0;
    let content = 0;
    if (d.type === 'session')      importance = (d.topics || []).length + (d.sources || []).length;
    if (d.type === 'topic')        importance = d.session_count || 1;
    if (d.type === 'source')       importance = d.citation_count || 1;
    if (d.type === 'agent')        importance = (d.tags || []).length + 1;
    if (d.type === 'workflow_run') importance = (d.tokens ? Math.log10(d.tokens + 1) : 0) + (d.duration || 0) / 30;
    // Approximate content size in characters.
    const desc = d.description || d.preview || '';
    const name = d.name || d.label || '';
    content = (desc.length + name.length) / 80;
    // Token usage → node size: log-scaled so a 100k-token run reads as
    // clearly-bigger (not 100x) than a 1k-token one. Nodes with no token
    // usage stay at base radius — honest, not zero-width.
    if (mode === 'tokens')    return d.tokens ? Math.log10(d.tokens + 1) * 3 : 0;
    if (mode === 'content')   return content;
    if (mode === 'hybrid')    return Math.min(importance + content * 0.4, 30);
    return importance;
  }

  function _nodeBaseRadius(t) {
    // Default sizes tuned smaller per user feedback that nodes were
    // too big relative to the link lines. The config-panel
    // 'nodeScale' multiplier brings them back up if desired.
    return ({ session: 6, topic: 5, source: 5, agent: 6, workflow_run: 5 })[t] || 4;
  }
  const NODE_R_MAX = 24;

  const nodeRadius = (d) => {
    const w = Math.max(0, _nodeWeight(d));
    const r = _nodeBaseRadius(d.type) + Math.sqrt(w) * 1.8;
    const scale = (window.graphConfig && graphConfig.nodeScale) || 1.0;
    return Math.min(r * scale, NODE_R_MAX * scale);
  };

  // Link palette + filter. graphConfig.linkKinds is a Set of enabled
  // link types; an empty/undefined Set means "show all". The "kind"
  // also feeds an above-the-graph legend with toggleable chips.
  const LINK_STYLE = {
    related:       { color: '#2BD4B460', label: 'related', tone: 'green'  },
    cites:         { color: '#b388ff60', label: 'cites',    tone: 'purple' },
    mentions:      { color: '#ff8c0050', label: 'mentions', tone: 'amber',  dash: '3,3' },
    uses:          { color: '#2bd4b450', label: 'uses',     tone: 'green' },
    produced:      { color: '#00C0E860', label: 'produced', tone: 'cyan' },
    shares_tag:    { color: '#2bd4b460', label: 'tag',      tone: 'green' },
    shares_role:   { color: '#2bd4b440', label: 'role',     tone: 'green',  dash: '2,4' },
    same_workflow: { color: '#00C0E866', label: 'workflow', tone: 'cyan' },
    ran_role:      { color: '#b388ff66', label: 'ran',      tone: 'purple' },
  };
  function _linkStyle(d) {
    return LINK_STYLE[d.type] || { color: '#ff8c0040', label: d.type || '?', tone: 'amber' };
  }
  const linkColor = (d) => _linkStyle(d).color;
  function _linkVisible(d) {
    const kinds = window.graphConfig && graphConfig.linkKinds;
    if (!kinds || !kinds.size) return true;
    return kinds.has(d.type);
  }

  // Build the toggleable legend FIRST so the filter set is ready before
  // we filter the working links array.
  _renderGraphLegendToggles(data);

  const nodes = data.nodes.map(d => ({ ...d }));
  const links = data.links.map(d => ({ ...d })).filter(_linkVisible);

  // Build an id → node map + a neighbor index so click highlight is O(1).
  // Links may carry source/target as strings (post-clone) until the sim
  // has run once; resolve through nodeById either way.
  const nodeById = new Map(nodes.map(n => [n.id, n]));
  const neighborMap = new Map();   // nodeId → Set<nodeId>
  const linkPairs   = new Map();   // "a||b" key → link object (for highlight)
  for (const n of nodes) neighborMap.set(n.id, new Set());
  for (const l of links) {
    const s = typeof l.source === 'string' ? l.source : l.source.id;
    const t = typeof l.target === 'string' ? l.target : l.target.id;
    if (neighborMap.has(s)) neighborMap.get(s).add(t);
    if (neighborMap.has(t)) neighborMap.get(t).add(s);
    linkPairs.set(`${s}||${t}`, l);
    linkPairs.set(`${t}||${s}`, l);
  }

  // Force-simulation parameters come from graphConfig so the panel
  // sliders can tune them live. The link-distance multiplier on
  // 'related' edges keeps the visual hierarchy from the original
  // (related sessions sit a bit further from each other).
  const cfg = window.graphConfig || _GRAPH_CONFIG_DEFAULTS;
  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id)
      .distance(d => d.type === 'related' ? cfg.linkDistance * 1.5 : cfg.linkDistance)
      .strength(cfg.linkStrength))
    .force('charge', d3.forceManyBody().strength(cfg.charge))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 6));
  graphSim = sim;
  // Expose for the detail-expand handler so it can nudge the
  // force-center when the SVG viewport resizes.
  window.graphSim = sim;

  // Links — width scales with both the link's own weight AND the
  // global linkWidth multiplier so the user can fatten lines until
  // they read clearly against the node circles. Default thickness
  // bumped from 1px to ~1.6px per user feedback.
  const linkW = cfg.linkWidth || 1.0;
  const linkA = cfg.linkOpacity || 1.0;
  const link = g.append('g').selectAll('line')
    .data(links).enter().append('line')
    .attr('stroke', linkColor)
    .attr('stroke-width', d => {
      const base = d.type === 'related'
        ? ((d.weight || 1) * 0.6 + 0.8)
        : 1.6;
      return base * linkW;
    })
    .attr('stroke-opacity', linkA)
    .attr('stroke-dasharray', d => {
      const s = _linkStyle(d);
      return s.dash || 'none';
    })
    .attr('marker-end', cfg.showArrows ? 'url(#graph-arrow)' : null);

  // One global arrowhead marker — referenced by every link when arrows
  // are enabled. Sized to match the link width so it scales naturally.
  if (cfg.showArrows) {
    let defs = svg.select('defs');
    if (defs.empty()) defs = svg.append('defs');
    if (defs.select('#graph-arrow').empty()) {
      defs.append('marker')
        .attr('id', 'graph-arrow')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 10).attr('refY', 0)
        .attr('markerWidth', 6).attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', 'var(--text-dim)');
    }
  }

  // Nodes
  const node = g.append('g').selectAll('circle')
    .data(nodes).enter().append('circle')
    .attr('r', nodeRadius)
    .attr('fill', nodeColor)
    .attr('fill-opacity', 0.85)
    .attr('stroke', nodeColor)
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.4)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end',   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
    )
    .on('mouseover', (e, d) => showTooltip(e, d))
    .on('mousemove', (e) => moveTooltip(e))
    .on('mouseout', () => hideTooltip())
    .on('click', (e, d) => { e.stopPropagation(); selectNode(d); });

  // Labels for session nodes only
  const label = g.append('g').selectAll('text')
    .data(nodes.filter(d => d.type === 'session')).enter().append('text')
    .attr('class', 'gn-session-label')
    .attr('font-family', 'JetBrains Mono, monospace')
    .attr('font-size', '9px')
    .attr('fill', 'var(--text-dim)')
    .attr('text-anchor', 'middle')
    .attr('dy', d => nodeRadius(d) + 12)
    .text(d => (d.label || d.id).slice(0, 24))
    .style('pointer-events', 'none');

  sim.on('tick', () => {
    link
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
    label.attr('x', d => d.x).attr('y', d => d.y);
  });

  // Stash live d3 selections + indexes for the click handler.
  window._graphState = {
    nodeSel: node, linkSel: link, labelSel: label,
    nodeById, neighborMap, linkPairs,
  };

  // Deselect on background click
  svg.on('click', () => clearGraphSelection());
}

// Expand toggle for the session-detail panel. Flips classes on both
// the panel AND its parent .research-left so the graph above shrinks
// proportionally — gives the operator a half-canvas drilldown view.
function toggleSessionDetailExpand(force) {
  const panel = document.getElementById('session-detail');
  const left  = panel ? panel.parentElement : null;
  const btn   = document.getElementById('session-detail-expand-btn');
  if (!panel || !left) return;
  const willExpand = force === undefined
    ? !panel.classList.contains('is-expanded')
    : !!force;
  panel.classList.toggle('is-expanded', willExpand);
  left.classList.toggle('detail-expanded', willExpand);
  if (btn) btn.textContent = willExpand ? '⇲ collapse' : '⤢ expand';
  // The graph SVG uses clientWidth/Height for its force-center; when
  // the panel grows the SVG shrinks, so kick the simulation so nodes
  // settle in the new viewport center.
  if (window.graphSim) {
    try {
      const svgEl = document.getElementById('graph-svg');
      const W = svgEl.clientWidth || 600;
      const H = svgEl.clientHeight || 400;
      window.graphSim.force('center', d3.forceCenter(W / 2, H / 2));
      window.graphSim.alpha(0.4).restart();
    } catch (_) {}
  }
}
window.toggleSessionDetailExpand = toggleSessionDetailExpand;

// Per-link-kind expand state — Set<kind> grows/shrinks as the operator
// clicks "+N more" / "↑ collapse" buttons. Re-rendering selectNode
// reflects the current expand state.
window._connExpand = window._connExpand || new Set();
function toggleConnGroupExpand(kind) {
  if (window._connExpand.has(kind)) window._connExpand.delete(kind);
  else window._connExpand.add(kind);
  // Re-render the current selection so the expand state takes effect.
  if (window.selectedNode) selectNode(window.selectedNode);
}
window.toggleConnGroupExpand = toggleConnGroupExpand;

function clearGraphSelection() {
  selectedNode = null;
  const panel = document.getElementById('session-detail');
  if (panel) {
    panel.classList.remove('open');
    // Also drop the expand state — otherwise the panel stays large
    // and empty when the user clicks away.
    if (panel.classList.contains('is-expanded')) {
      toggleSessionDetailExpand(false);
    }
  }
  const st = window._graphState;
  if (!st) return;
  st.nodeSel.attr('fill-opacity', 0.85).attr('stroke-width', 1.5).attr('stroke-opacity', 0.4);
  st.linkSel.attr('stroke-opacity', 1);
  st.labelSel.attr('fill-opacity', 1);
}

function highlightNeighborhood(d) {
  const st = window._graphState;
  if (!st) return;
  const neighbors = st.neighborMap.get(d.id) || new Set();
  const inSet = (id) => id === d.id || neighbors.has(id);
  // Nodes: full opacity for the selected + its neighbors, dim everything else.
  st.nodeSel
    .attr('fill-opacity', n => inSet(n.id) ? 0.95 : 0.18)
    .attr('stroke-opacity', n => inSet(n.id) ? 1 : 0.15)
    .attr('stroke-width', n => n.id === d.id ? 3 : 1.5);
  // Links: full for any line that touches the selected node.
  st.linkSel.attr('stroke-opacity', l => {
    const s = typeof l.source === 'object' ? l.source.id : l.source;
    const t = typeof l.target === 'object' ? l.target.id : l.target;
    return (s === d.id || t === d.id) ? 1 : 0.12;
  });
  st.labelSel.attr('fill-opacity', n => inSet(n.id) ? 1 : 0.2);
}

function showTooltip(e, d) {
  const tt = document.getElementById('graph-tooltip');
  let html = `<strong>${esc(d.label || d.id)}</strong>`;
  if (d.type === 'session') {
    html += `<div class="tt-meta">Session · ${d.model || ''}</div>`;
    if (d.topics && d.topics.length) html += `<div class="tt-meta">${d.topics.slice(0,4).join(', ')}</div>`;
  } else if (d.type === 'topic') {
    html += `<div class="tt-meta">Topic · ${d.session_count || 1} sessions</div>`;
  } else if (d.type === 'source') {
    html += `<div class="tt-meta">Source · ${d.citation_count || 1} citations</div>`;
  }
  tt.innerHTML = html;
  tt.style.display = 'block';
  moveTooltip(e);
}
function moveTooltip(e) {
  const tt = document.getElementById('graph-tooltip');
  tt.style.left = (e.clientX + 14) + 'px';
  tt.style.top  = (e.clientY - 10) + 'px';
}
function hideTooltip() {
  document.getElementById('graph-tooltip').style.display = 'none';
}

function selectNode(d) {
  selectedNode = d;
  window.selectedNode = d;  // expose so re-render helpers can re-call selectNode
  const panel = document.getElementById('session-detail');
  if (!panel) return;
  panel.classList.add('open');
  highlightNeighborhood(d);

  // ── Kind chip + title (every node type) ────────────────────────
  const chip = document.getElementById('session-detail-kind');
  if (chip) {
    chip.textContent = d.type || 'node';
    chip.className = `detail-kind-chip kind-${esc(d.type || 'node')}`;
  }
  document.getElementById('session-detail-title').textContent =
    d.label || d.filename || d.id;
  document.getElementById('session-detail-meta').textContent =
    _detailMetaFor(d);

  // Topics chips reused for whichever node type has list-y data:
  //   session.topics, topic siblings, source citations.
  const topicsEl = document.getElementById('session-detail-topics');
  topicsEl.innerHTML = _detailChipsFor(d);

  // Preview body (only sessions have a transcript preview).
  const previewEl = document.getElementById('session-detail-preview');
  if (d.type === 'session') {
    previewEl.textContent = (d.preview || '').slice(0, 300)
      .replace(/^#+[^\n]*\n?/gm, '').trim();
  } else if (d.type === 'topic') {
    previewEl.textContent = `Topic surfaces across ${d.session_count || 0} session${(d.session_count || 0) === 1 ? '' : 's'}. Click a connected node to drill in.`;
  } else if (d.type === 'source') {
    previewEl.innerHTML = d.url
      ? `<a href="${esc(d.url)}" target="_blank" rel="noopener" style="color:var(--cyan);text-decoration:underline">${esc(d.url.slice(0, 80))}${d.url.length > 80 ? '…' : ''}</a>`
      : `<span style="color:var(--text-muted)">No URL recorded for this source.</span>`;
  } else if (d.type === 'agent') {
    // Agent nodes (new graph schema): description/role/model on one line.
    const bits = [d.role, d.model, d.description].filter(Boolean).join(' · ');
    previewEl.textContent = bits || `Agent node ${d.id}.`;
  } else if (d.type === 'workflow_run') {
    const bits = [
      d.workflow_id ? `workflow=${d.workflow_id}` : null,
      d.status ? `status=${d.status}` : null,
      d.started_at || null,
    ].filter(Boolean).join(' · ');
    previewEl.textContent = bits || `Workflow run ${d.id}.`;
  } else {
    // Generic fallback — surface whatever string-ish keys the backend
    // supplied so the user always sees *something* on click.
    const bits = [d.description, d.summary, d.label, d.id]
      .filter(v => typeof v === 'string' && v.trim()).slice(0, 1);
    previewEl.textContent = bits[0] || '';
  }

  // ── Connections drilldown — group by link kind, show shared
  //    attributes inline (tag/role/workflow), expand for >5. ─────────
  const connEl = document.getElementById('session-detail-connections');
  const st = window._graphState;
  if (connEl && st) {
    const neighbors = Array.from(st.neighborMap.get(d.id) || []);
    if (!neighbors.length) {
      connEl.innerHTML = `<div class="detail-conn-empty">No connections.</div>`;
    } else {
      // Build a per-neighbor record with the link kind + shared evidence.
      // The linkPairs map is keyed "a||b" so either direction resolves.
      const recs = neighbors.map(nid => {
        const link = st.linkPairs.get(`${d.id}||${nid}`) ||
                     st.linkPairs.get(`${nid}||${d.id}`);
        const n = st.nodeById.get(nid);
        return {
          nid, node: n,
          kind: link ? (link.type || 'related') : 'related',
          shared: (link && Array.isArray(link.shared)) ? link.shared : [],
          weight: (link && link.weight) || 1,
        };
      }).filter(r => r.node);
      // Group by link KIND (the relationship type), not the neighbor's
      // node type — that's the question the user is actually asking:
      // "why are these two connected?"
      const groups = {};
      recs.forEach(r => { (groups[r.kind] = groups[r.kind] || []).push(r); });
      const kindOrder = Object.keys(groups).sort((a, b) =>
        (groups[b].length) - (groups[a].length)
      );
      const html = kindOrder.map(kind => {
        const items = groups[kind].sort((a, b) => (b.weight || 1) - (a.weight || 1));
        const style = (typeof LINK_STYLE !== 'undefined' && LINK_STYLE[kind]) || { label: kind, tone: 'amber' };
        const showAll = (window._connExpand && window._connExpand.has(kind));
        const visible = showAll ? items : items.slice(0, 5);
        const moreCount = items.length - visible.length;
        const rows = visible.map(r => {
          const n = r.node;
          const sharedChips = (r.shared || []).slice(0, 4)
            .map(s => `<span class="conn-shared-chip">${esc(String(s).slice(0, 20))}</span>`)
            .join('');
          return `<button type="button" class="detail-conn-row" data-node-id="${esc(n.id)}"
                          data-action="graph.node-select"
                          title="Drill into ${esc(n.label || n.id)} — connected by ${esc(kind)}">
            <span class="detail-conn-dot kind-${esc(n.type)}"></span>
            <span class="detail-conn-label">${esc((n.label || n.id).slice(0, 60))}</span>
            <span class="detail-conn-shared">${sharedChips}</span>
          </button>`;
        }).join('');
        const expandBtn = items.length > 5
          ? `<button type="button" class="detail-conn-expand"
                data-action="graph.conn-group" data-kind="${esc(kind)}">
                ${showAll ? '↑ collapse' : `+${moreCount} more`}
             </button>`
          : '';
        return `<div class="detail-conn-group-block">
          <div class="detail-conn-group">
            <span class="detail-conn-kind tone-${esc(style.tone)}">${esc(style.label || kind)}</span>
            <span class="detail-conn-count">${items.length}</span>
          </div>
          ${rows}
          ${expandBtn}
        </div>`;
      }).join('');
      connEl.innerHTML = `<div class="detail-conn-title">Why connected · ${neighbors.length} link${neighbors.length === 1 ? '' : 's'}</div>${html}`;
    }
  }

  // ── Action footer — actions vary by node type ──────────────────
  const actEl = document.getElementById('session-detail-actions');
  if (actEl) {
    if (d.type === 'session') {
      actEl.innerHTML =
        `<button class="action-btn" data-action="graph.session-chat" style="font-size:0.65rem;padding:4px 10px">Open in Chat</button>
         <button class="action-btn" data-action="graph.session-deep-dive" style="font-size:0.65rem;padding:4px 10px;border-color:var(--amber);color:var(--amber)">Deep Dive</button>`;
    } else if (d.type === 'topic') {
      actEl.innerHTML =
        `<button class="action-btn" data-action="graph.node-deep-dive" style="font-size:0.65rem;padding:4px 10px;border-color:var(--amber);color:var(--amber)">Deep Dive on Topic</button>`;
    } else if (d.type === 'source') {
      actEl.innerHTML = d.url
        ? `<a class="action-btn" target="_blank" rel="noopener" href="${esc(d.url)}" style="font-size:0.65rem;padding:4px 10px;text-decoration:none;display:inline-block">Open Source ↗</a>`
        : '';
    } else {
      actEl.innerHTML = '';
    }
  }
}

// ── Detail-panel helpers (reused by every node type) ───────────────
function _detailMetaFor(d) {
  if (!d) return '';
  if (d.type === 'session') {
    return [d.model, d.date, d.filename].filter(Boolean).join(' · ');
  }
  if (d.type === 'topic') {
    const n = d.session_count || 0;
    return `Topic · referenced in ${n} session${n === 1 ? '' : 's'}`;
  }
  if (d.type === 'source') {
    const n = d.citation_count || 0;
    return `Source · cited ${n} time${n === 1 ? '' : 's'}`;
  }
  return d.type || '';
}

function _detailChipsFor(d) {
  if (!d) return '';
  // Sessions: their list of topics. Topic + source nodes don't carry
  // their own chip list — the Connections section enumerates neighbors.
  if (d.type === 'session' && Array.isArray(d.topics) && d.topics.length) {
    return d.topics.map(t => `<span class="session-topic">${esc(t)}</span>`).join('');
  }
  return '';
}

// Click-through from the Connections list — re-runs selectNode against
// the picked neighbor so you can hop session → topic → session.
function selectNodeById(id) {
  const st = window._graphState;
  if (!st) return;
  const target = st.nodeById.get(id);
  if (!target) return;
  selectNode(target);
}

function loadSessionIntoChat() {
  if (!selectedNode || selectedNode.type !== 'session') return;
  const topic = selectedNode.label || selectedNode.filename;
  document.getElementById('prompt').value = `Continuing our discussion on: ${topic}`;
  switchTab('dashboard');
  document.getElementById('prompt').focus();
}

function deepDiveFromSession() {
  if (!selectedNode || selectedNode.type !== 'session') return;
  document.getElementById('research-topic').value = selectedNode.label || selectedNode.filename;
  document.getElementById('session-detail').classList.remove('open');
  runDeepDive();
}

// Topic / source drilldown — feed the node label as the research topic.
function deepDiveFromNode() {
  if (!selectedNode) return;
  const topic = selectedNode.label || selectedNode.id;
  document.getElementById('research-topic').value = topic;
  document.getElementById('session-detail').classList.remove('open');
  runDeepDive();
}

// Delegated actions for the graph node-inspector panel — connection rows,
// expanders, and the per-node-type action footer all re-render on every
// node selection. Rows reuse their existing data-node-id attr.
Actions.click({
  'graph.node-select':       el => selectNodeById(el.dataset.nodeId),
  'graph.conn-group':        el => toggleConnGroupExpand(el.dataset.kind),
  'graph.session-chat':      () => loadSessionIntoChat(),
  'graph.session-deep-dive': () => deepDiveFromSession(),
  'graph.node-deep-dive':    () => deepDiveFromNode()
});

/* ── Deep Research ──────────────────────────────────────────────── */
async function runDeepDive() {
  const topic = document.getElementById('research-topic').value.trim();
  if (!topic) return;
  const model = document.getElementById('res-model-select').value;
  const depth = parseInt(document.getElementById('res-depth').value) || 3;

  const out = document.getElementById('research-output');
  const btn = document.getElementById('dive-btn');
  btn.disabled = true;
  btn.textContent = 'Researching…';

  // In-flight state — survives tab switches. initResearch() rehydrates
  // this if the Skills Lab tab is left and re-entered while the call
  // is still pending. Cleared in the finally block.
  window._researchInFlight = {
    topic,
    model,
    depth,
    started_at: new Date().toISOString(),
    stage: 'decompose',
    passed: [],
  };
  window._lastResearch = null;  // hide stale results while a new run is active
  _renderResearchInFlight(window._researchInFlight);

  try {
    // Tick step 1 → 2 after a beat
    await new Promise(r => setTimeout(r, 600));
    window._researchInFlight.passed.push('decompose');
    window._researchInFlight.stage = 'search';
    _renderResearchInFlight(window._researchInFlight);

    // retries:0 ESSENTIAL — minutes-long LLM research; a 504-retry would
    // launch a second full research run.
    const resp = await Net.call('/api/research/deep-dive', {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, model, depth }),
      },
    });

    window._researchInFlight.passed.push('search');
    window._researchInFlight.stage = 'synth';
    _renderResearchInFlight(window._researchInFlight);

    await new Promise(r => setTimeout(r, 300));

    const data = (resp.data && typeof resp.data === 'object') ? resp.data : {};
    if (!resp.ok) throw new Error(data.detail || resp.error || `HTTP ${resp.status}`);

    window._researchInFlight.passed.push('synth');
    window._researchInFlight = null;
    renderResearchResults(data);

    // Rebuild graph after research (new session may be added via export)
    await loadGraphData();

    if (window.Toast) {
      window.Toast.success(
        'Research complete',
        `${(data.sub_questions || []).length} sub-questions explored · ${(data.sources || []).length} sources`,
        { ttl: 4000 }
      );
    }
  } catch (e) {
    window._researchInFlight = null;
    out.innerHTML = `<div class="research-empty" style="color:var(--red)">Research failed: ${esc(String(e))}</div>`;
    if (window.Toast) window.Toast.danger('Research failed', String(e));
  } finally {
    btn.disabled = false;
    btn.textContent = 'Research';
  }
}

function renderResearchResults(data) {
  const out = document.getElementById('research-output');

  // Capture payloads live in ResearchArtifacts module state keyed by
  // data-idx — NOT URI-encoded into onclick attributes (sub-question
  // contexts can run to megabytes).
  ResearchArtifacts.resetPayloads();

  // Each sub-question gets its own "thinking" card — expandable, showing
  // what the research agent actually looked at for that angle. Backend's
  // `data.research` is [{question, context, sources}] aligned with sub_questions.
  const thinkingCards = (data.research || []).map((sec, idx) => {
    const qSrcs = (sec.sources || []).slice(0, 6);
    const srcHtml = qSrcs.length
      ? qSrcs.map(s =>
          `<a class="res-source-chip" href="${esc(s.url || '#')}" target="_blank" rel="noopener">${esc(s.title || s.url || '(untitled)').slice(0, 80)}</a>`
        ).join('')
      : '<span style="color:var(--text-muted);font-size:0.62rem">no sources for this angle</span>';
    const ctxPreview = (sec.context || '').slice(0, 320);
    const safeQ = esc(sec.question || '');
    const payloadIdx = ResearchArtifacts.addPayload({
      source: 'research',
      title: 'Sub-finding: ' + (sec.question || ''),
      body: (sec.context || '') + '\n\nSources:\n' + qSrcs.map(s => '- ' + (s.url || '')).join('\n'),
      tags: ['research', 'sub-question'],
      context: { parent_topic: data.topic, sub_question: sec.question, model: data.model }
    });
    return `
      <details class="research-thinking-card">
        <summary>
          <span class="thinking-step-num">${idx + 1}</span>
          <span class="thinking-step-q">${safeQ}</span>
          <span class="thinking-step-meta">${qSrcs.length} source${qSrcs.length === 1 ? '' : 's'}</span>
        </summary>
        <div class="thinking-step-body">
          <div class="thinking-step-context">${ctxPreview ? esc(ctxPreview) + (sec.context && sec.context.length > 320 ? '…' : '') : '<em style="color:var(--text-muted)">no context gathered</em>'}</div>
          <div class="thinking-step-sources">${srcHtml}</div>
          <div class="thinking-step-actions">
            <button class="action-btn xs cyan" data-action="research.capture" data-idx="${payloadIdx}">+ Capture as artifact</button>
          </div>
        </div>
      </details>
    `;
  }).join('');

  // Source chips
  const chips = (data.sources || []).map(s =>
    `<a class="res-source-chip" href="${esc(s.url || '#')}" target="_blank" rel="noopener" title="${esc(s.title || s.url || '')}">${esc(s.title || s.url || '')}</a>`
  ).join('');

  // Render synthesis markdown (basic)
  const synthesis = renderMarkdownBasic(data.synthesis || '');
  const synthIdx = ResearchArtifacts.addPayload({
    source: 'research',
    title: 'Synthesis: ' + (data.topic || 'untitled'),
    body: data.synthesis || '',
    tags: ['research', 'synthesis'],
    context: {
      topic: data.topic,
      model: data.model,
      sub_questions: data.sub_questions || [],
      source_count: (data.sources || []).length,
    }
  });

  out.innerHTML = `
    <div class="research-topic-bar">
      <span class="research-topic-label">TOPIC</span>
      <strong>${esc(data.topic || '')}</strong>
      <span class="research-topic-meta">model: ${esc(data.model || '?')} · ${(data.sub_questions || []).length} sub-questions · ${(data.sources || []).length} unique sources</span>
    </div>

    <div class="research-thinking-strip">
      <div class="research-thinking-strip-label">AGENT THINKING — per sub-question</div>
      ${thinkingCards || '<div style="color:var(--text-muted);font-size:0.65rem">no per-sub-question detail returned</div>'}
    </div>

    <div class="synthesis-block">
      <div class="synthesis-label">SYNTHESIS</div>
      ${synthesis}
    </div>
    ${chips ? `<div style="margin-top:12px;font-size:0.62rem;color:var(--text-muted);margin-bottom:6px">ALL SOURCES</div><div class="res-sources">${chips}</div>` : ''}
    <div class="research-actions" style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="action-btn accent" data-action="research.capture" data-idx="${synthIdx}">+ Capture synthesis as artifact</button>
      <button class="action-btn cyan" data-action="research.library">View captured artifacts</button>
      <button class="action-btn" data-action="research.export">Export as MD</button>
    </div>
  `;

  // Store for export AND for tab-switch rehydration.
  window._lastResearch = data;
}

// ── Research artifact capture ────────────────────────────────────────────
// Wraps POST /api/feedback/artifacts. Each click captures the finding as
// a durable record (and best-effort RAG-ingests it server-side so the
// artifact becomes semantically searchable in the Context tab).
window.ResearchArtifacts = (function () {
  // Capture payloads staged by renderResearchResults — buttons carry only
  // a data-idx into this array, never the (potentially huge) payload itself.
  let _payloads = [];
  function resetPayloads() { _payloads = []; }
  function addPayload(p) { return _payloads.push(p) - 1; }

  async function captureRaw(payloadJson) {
    let payload;
    try {
      payload = typeof payloadJson === 'string' ? JSON.parse(payloadJson) : payloadJson;
    } catch (e) {
      if (window.Toast) Toast.danger('Capture failed', 'Could not parse payload: ' + e.message);
      return;
    }
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
          (rec.title || payload.title) + (rec.rag_ingested ? ' · also indexed in Context' : ''),
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
    'research.capture': el => {
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

  return { captureRaw, openLibrary, resetPayloads, addPayload };
})();


async function exportResearch() {
  const d = window._lastResearch;
  if (!d) return;
  const ts = new Date().toISOString().slice(0, 16).replace('T', '-').replace(':', '');
  const topic_slug = d.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
  const filename = `research-${ts}-${topic_slug}.md`;

  const lines = [
    `# Research: ${d.topic}`,
    ``,
    `| Field | Value |`,
    `|-------|-------|`,
    `| Model | ${d.model} |`,
    `| Sub-questions | ${(d.sub_questions || []).length} |`,
    `| Sources | ${(d.sources || []).length} |`,
    ``,
    `---`,
    ``,
    `## Sub-Questions Explored`,
    ...(d.sub_questions || []).map((q, i) => `${i + 1}. ${q}`),
    ``,
    `## Research Report`,
    ``,
    d.synthesis || '',
    ``,
    `## Sources`,
    ...(d.sources || []).map((s, i) => `${i + 1}. [${s.title || s.url}](${s.url})`),
  ];
  const content = lines.join('\n');

  // Browser download
  const blob = new Blob([content], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);

  // Server save
  try {
    await Net.postJson('/api/exports/save', { filename, content }, { retries: 0, silent: true });
    // Rebuild graph to include new research export
    await loadGraphData();
  } catch {}
}

/* ── WORKFLOWS TAB ─────────────────────────────────────────────── */
let workflowsLoaded = false;
let currentWorkflowDef = null;

async function loadWorkflowsTab() {
  if (!workflowsLoaded) {
    await refreshWorkflows();
    await loadRecentRuns();
    workflowsLoaded = true;
  }
  // Roles are cheap to reload; refresh each time the tab is opened so edits
  // to prompts/roles/ show up without a page reload.
  await loadRoles();
}

async function loadRoles() {
  const container = document.getElementById('wf-roles-list');
  if (!container) return;
  try {
    const roles = await Net.getJson('/api/roles');
    if (!Array.isArray(roles) || roles.length === 0) {
      container.innerHTML = '<div class="model-empty">No roles defined in prompts/roles/</div>';
      return;
    }
    container.innerHTML = roles.map(r => `
      <button type="button" class="btn-unstyled wf-role-card" style="width:100%" data-action="roles.preview" data-id="${esc(r.id)}">
        <div class="wf-role-name">${esc(r.name)}</div>
        <div class="wf-role-summary">${esc(r.summary)}</div>
        <div class="wf-role-id">${esc(r.id)}</div>
      </button>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="model-empty">Failed to load roles: ${esc(e.message)}</div>`;
  }
}

// Delegated action shared by the role cards (loadRoles) and the role
// chips rendered inside workflow detail views.
Actions.click({ 'roles.preview': el => previewRole(el.dataset.id) });

async function previewRole(id) {
  const box = document.getElementById('wf-role-preview');
  if (!box) return;
  try {
    // silent — HTTP miss hides the box quietly; only a network error
    // (status 0) falls through to the 'Preview failed' catch path.
    const resp = await Net.call(`/api/roles/${encodeURIComponent(id)}`, { silent: true });
    if (resp.status === 0) throw new Error(resp.error || 'network error');
    if (!resp.ok) { box.style.display = 'none'; return; }
    const r = resp.data;
    box.textContent = r.content;
    box.style.display = 'block';
    box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } catch (e) {
    box.textContent = 'Preview failed: ' + e.message;
    box.style.display = 'block';
  }
}

async function refreshWorkflows() {
  try {
    const workflows = await Net.getJson('/api/workflows');
    const sel = document.getElementById('wf-select');
    sel.innerHTML = '<option value="">-- select workflow --</option>';
    workflows.forEach(wf => {
      const opt = document.createElement('option');
      opt.value = wf.file || wf.id;
      opt.textContent = `${wf.name} (${wf.steps} steps)`;
      opt.dataset.id = wf.id;
      opt.dataset.desc = wf.description || '';
      opt.dataset.version = wf.version || '';
      sel.appendChild(opt);
    });
  } catch (e) {
    console.error('Failed to load workflows:', e);
  }
  // Refresh A2A panel alongside workflows: every YAML change is also an
  // Agent Card change, so the two are inherently linked.
  loadA2ACard();
}

// ── A2A Integrations Panel ─────────────────────────────────────────────
// Surfaces the protocol surface from PR #18: shows the Agent Card URL
// and the advertised skills (chat + workflow:<id>...). The panel only
// renders if /.well-known/agent.json responds — older builds without
// A2A wired up keep the workflows tab clean.

async function loadA2ACard() {
  const panel = document.getElementById('a2a-panel');
  if (!panel) return;
  try {
    // silent + retries:0 — endpoint legitimately absent on older builds;
    // must not toast or retry a build that simply lacks A2A.
    const resp = await Net.call('/.well-known/agent.json', { silent: true, retries: 0 });
    if (!resp.ok) { panel.style.display = 'none'; return; }
    const card = resp.data;
    panel.style.display = '';

    // Resolve the absolute URL the way an external agent would see it.
    const cardUrl = new URL('/.well-known/agent.json', window.location.origin).toString();
    document.getElementById('a2a-card-url').textContent = cardUrl;
    document.getElementById('a2a-card-url').dataset.url = cardUrl;

    const skills = card.skills || [];
    document.getElementById('a2a-skill-count').textContent =
      `${skills.length} skill${skills.length === 1 ? '' : 's'} advertised`;

    document.getElementById('a2a-skills-list').innerHTML = skills.map(s => `
      <div style="padding:4px 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--cyan)">${esc(s.id)}</span>
        <span style="color:var(--text-muted)">·</span>
        <span style="color:var(--text)">${esc(s.name || '')}</span>
        ${s.description ? `<div style="color:var(--text-dim);font-size:0.65rem;margin-top:2px">${esc(s.description)}</div>` : ''}
      </div>
    `).join('') || '<div style="color:var(--text-muted)">No skills advertised.</div>';
  } catch (e) {
    // Don't surface a console error if the Agent Card endpoint just doesn't exist.
    panel.style.display = 'none';
  }
}

function copyA2ACardUrl() {
  const el = document.getElementById('a2a-card-url');
  const url = el.dataset.url || el.textContent;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(url).then(() => {
      const orig = el.textContent;
      el.textContent = 'copied!';
      setTimeout(() => { el.textContent = orig; }, 900);
    });
  }
}

function toggleA2ASkills() {
  const el = document.getElementById('a2a-skills-list');
  el.style.display = el.style.display === 'none' ? '' : 'none';
}

async function loadWorkflowDetail() {
  const sel = document.getElementById('wf-select');
  const opt = sel.selectedOptions[0];
  if (!opt || !opt.value) return;

  try {
    // Load via validate endpoint to parse the definition
    const workflows = await Net.getJson('/api/workflows');
    const wf = workflows.find(w => w.id === opt.dataset.id);
    if (!wf) return;

    // raw fetch: dead call — defResp is never read (defResp2 below supersedes
    // it); left raw deliberately, candidate for deletion (Net adds nothing here).
    const defResp = await fetch(opt.value.replace(/^\.\//, '/'));

    document.getElementById('wf-detail-name').textContent = opt.textContent;
    document.getElementById('wf-detail-desc').textContent = opt.dataset.desc;
    document.getElementById('wf-detail').style.display = 'block';
    document.getElementById('wf-results').style.display = 'none';

    // Fetch the full workflow definition (with hooks + prompt blocks).
    // silent — the ok→null fallback (skeleton def) is load-bearing.
    const defResp2 = await Net.call(`/api/workflows/${encodeURIComponent(opt.dataset.id)}`, { silent: true });
    const defn = defResp2.ok ? defResp2.data : null;
    currentWorkflowDef = defn || { id: opt.dataset.id, name: opt.textContent, steps: [] };

    // Build static pipeline visualization showing declared hooks + role_ref.
    const pipeline = document.getElementById('wf-pipeline');
    if (defn && Array.isArray(defn.steps) && defn.steps.length > 0) {
      pipeline.innerHTML = defn.steps.map((step, i) =>
        (i > 0 ? '<div class="wf-arrow">&rarr;</div>' : '') +
        renderStepBox(step, 'pending', null)
      ).join('');
    } else {
      pipeline.innerHTML = `<div style="color:var(--text-dim);font-size:0.72rem">${wf.steps} step pipeline &mdash; execute to see detailed step visualization</div>`;
    }

    // Interactive composer-style DAG view of this workflow (clickable nodes).
    try { renderWorkflowDag(defn); } catch (e) { console.warn('renderWorkflowDag:', e); }

    // Update seed textarea placeholder from the workflow's context.description.
    // Parses "Required seed keys: vendor, product, raw_log." → skeleton JSON.
    updateSeedPlaceholder(defn);

  } catch (e) {
    console.error('Failed to load workflow:', e);
  }
}

function updateSeedPlaceholder(defn) {
  const seedEl = document.getElementById('wf-seed');
  if (!seedEl) return;
  const ctxDesc = defn && defn.context && defn.context.description;
  if (!ctxDesc) { seedEl.placeholder = '{"key": "value"}'; return; }

  let keys = [];
  // Inline format: "Required seed keys: vendor, product, raw_log."
  const inlineMatch = ctxDesc.match(/[Rr]equired\s+seed\s+keys?:\s+([^\n.]+)/);
  if (inlineMatch && inlineMatch[1].includes(',')) {
    keys = inlineMatch[1].split(',').map(k => k.trim().split(/\s/)[0]).filter(Boolean);
  } else {
    // Multi-line format: "Required seed keys:\n  vendor — desc\n  product — desc"
    const headerPos = ctxDesc.search(/[Rr]equired\s+seed\s+keys?:/);
    if (headerPos >= 0) {
      const afterNewline = ctxDesc.indexOf('\n', headerPos);
      if (afterNewline >= 0) {
        // Grab only the first paragraph (stop at blank line)
        const paragraph = ctxDesc.slice(afterNewline + 1).split('\n\n')[0];
        keys = [...paragraph.matchAll(/^[ \t]+([a-zA-Z_][a-zA-Z0-9_]*)/gm)].map(m => m[1]);
      }
    }
  }

  if (!keys.length) return;
  const skeleton = {};
  keys.forEach(k => { skeleton[k] = ''; });
  seedEl.placeholder = JSON.stringify(skeleton, null, 2);
}

/* Phase 5c — render the per-run pre-warm summary.
 *
 * Surfaces RunTelemetrySummary.pre_warm_count / hits / misses + the total
 * overlap cost. Returns empty string when the run has no pre-warm events
 * (the arch said no at every boundary, defaults.disable_pre_warm was set,
 * or the workflow has only one model). Sits between the run-status row
 * and the per-step rows so the operator gets the "did pre-warm pay off"
 * answer before reading individual step chips.
 *
 * All interpolated values are numeric (counts, ms→s conversion) so
 * template-literal interpolation is safe — no esc() needed.
 */
function _renderPreWarmSummary(run) {
  const ts = run && run.telemetry_summary;
  if (!ts || !ts.pre_warm_count) return '';
  const hits = ts.pre_warm_hits || 0;
  const misses = ts.pre_warm_misses || 0;
  const total = ts.pre_warm_count;
  const indeterminate = total - hits - misses;
  const overlap_s = (ts.total_pre_warm_load_ms || 0) / 1000;
  // Color by hit ratio; "indeterminate" wins when nothing resolved
  // (workflow short-circuited before consumers ran).
  let cls = 'indeterminate';
  if (hits + misses > 0) {
    if (misses === 0) cls = 'all-hits';
    else if (hits === 0) cls = 'all-misses';
    else cls = 'partial';
  }
  const overlap_text = overlap_s >= 0.05
    ? ` · ${overlap_s.toFixed(1)}s overlap (hidden behind inference)`
    : '';
  const indet_text = indeterminate > 0 ? ` · ${indeterminate} unresolved` : '';
  return `
    <div class="pre-warm-summary ${cls}" title="Pre-warm aggregates from arch.transition_plan() decisions across the run">
      <span class="pre-warm-label">Pre-warm</span>
      <span class="pre-warm-stats">${hits} hit${hits !== 1 ? 's' : ''} / ${misses} miss${misses !== 1 ? 'es' : ''}${indet_text}${overlap_text}</span>
    </div>
  `;
}

// Interactive DAG for the workflow drill-down — a composer-style graph view.
// dagre-laid-out compact node cards + SVG connectors, scaled to fit; clicking
// a node opens that step in the Composer (with node-bound chat).
function renderWorkflowDag(defn) {
  const mount = document.getElementById('wf-dag');
  const actions = document.getElementById('wf-dag-actions');
  if (!mount) return;
  const steps = (defn && Array.isArray(defn.steps)) ? defn.steps : [];
  if (!steps.length || typeof dagre === 'undefined') {
    mount.style.display = 'none'; mount.style.height = '0';
    if (actions) actions.style.display = 'none';
    return;
  }
  const NODE_W = 150, NODE_H = 52;
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 26, ranksep: 58, marginx: 16, marginy: 16 });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(steps.map(s => s.id));
  steps.forEach(s => g.setNode(s.id, { width: NODE_W, height: NODE_H }));
  const edges = [];
  steps.forEach(s => {
    const deps = Array.isArray(s.depends_on) ? s.depends_on : (s.depends_on ? [s.depends_on] : []);
    deps.forEach(d => { if (ids.has(d)) { g.setEdge(d, s.id); edges.push([d, s.id]); } });
  });
  if (!edges.length && steps.length > 1) {
    for (let i = 1; i < steps.length; i++) { g.setEdge(steps[i - 1].id, steps[i].id); edges.push([steps[i - 1].id, steps[i].id]); }
  }
  dagre.layout(g);
  let maxX = 0, maxY = 0;
  steps.forEach(s => { const p = g.node(s.id); if (p) { maxX = Math.max(maxX, p.x + NODE_W / 2); maxY = Math.max(maxY, p.y + NODE_H / 2); } });
  const contentW = maxX + 16, contentH = maxY + 16;
  const ch = 250;
  mount.style.display = 'block'; mount.style.height = ch + 'px';
  if (actions) actions.style.display = 'flex';
  const cw = mount.clientWidth || 600;
  const scale = Math.min(1, (cw - 12) / contentW, (ch - 12) / contentH);
  const ROLE_TINT = { reasoning: '--node-reasoning', coding: '--node-coding', fast: '--node-fast', general: '--node-general', uncensored: '--node-uncensored' };
  const wfId = (defn.id || (currentWorkflowDef && currentWorkflowDef.id) || '');
  let svg = `<svg width="${contentW}" height="${contentH}" style="position:absolute;inset:0;pointer-events:none;overflow:visible">`;
  edges.forEach(([a, c]) => {
    const pa = g.node(a), pc = g.node(c); if (!pa || !pc) return;
    const x1 = pa.x + NODE_W / 2, y1 = pa.y, x2 = pc.x - NODE_W / 2, y2 = pc.y, mx = (x1 + x2) / 2;
    svg += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="var(--accent-dim)" stroke-width="1.5"/>`;
  });
  svg += '</svg>';
  const nodes = steps.map(s => {
    const p = g.node(s.id); if (!p) return '';
    const left = p.x - NODE_W / 2, top = p.y - NODE_H / 2;
    const tint = 'var(' + (ROLE_TINT[s.role] || '--accent') + ')';
    const model = s.model || (s.prompt && s.prompt.model) || '';
    return `<div class="wf-dag-node" style="left:${left}px;top:${top}px;width:${NODE_W}px;height:${NODE_H}px;border-left-color:${tint}"
        onclick="openWorkflowInComposer('${esc(wfId)}','${esc(s.id)}')"
        title="Open '${esc(s.id)}' in the Composer + chat with its agent">
        <span class="wf-dag-node-name">${esc(s.name || s.id)}</span>
        <span class="wf-dag-node-meta">${esc(s.role || 'general')}${model ? ' · ' + esc(model) : ''}</span>
      </div>`;
  }).join('');
  mount.innerHTML = `<div class="wf-dag-inner" style="width:${contentW}px;height:${contentH}px;transform:scale(${scale})">${svg}${nodes}</div>`;
}

// Open the drilled-into workflow in the Composer canvas. If a step id is given
// (clicked a DAG node), bind the chat to that node once it's loaded.
async function openWorkflowInComposer(wfId, stepId) {
  if (!wfId) { if (window.Toast) Toast.info('No workflow', 'Pick a workflow first.'); return; }
  try {
    await composerLoadById(wfId);
    if (typeof switchTab === 'function') switchTab('dashboard');
    if (typeof ComposerSplit !== 'undefined' && ComposerSplit.setMode) ComposerSplit.setMode('canvas');
    if (stepId) {
      setTimeout(() => {
        try {
          let nid = null;
          for (const k in dfNodeData) { if (dfNodeData[k] && dfNodeData[k].id === stepId) { nid = k; break; } }
          if (nid != null && typeof composerEnterStepEngage === 'function') composerEnterStepEngage(nid);
        } catch (_) {}
      }, 150);
    }
  } catch (e) { if (window.Toast) Toast.danger('Open failed', String(e)); }
}

function renderStepBox(step, status, result) {
  // Declared hooks (from WorkflowDefinition). Live hook execution status
  // will be added in a follow-up (requires engine instrumentation).
  const hooks = step.hooks || {};
  const slots = ['before_step', 'transform_prompt', 'validate_output', 'after_step', 'on_failure'];
  const hookBlocks = slots.map(slot => {
    const entries = (hooks[slot] || []);
    if (!entries.length) return '';
    const pills = entries.map(h =>
      `<span class="wf-hook-pill" title="${esc(JSON.stringify(h.config || {}))}">${esc(h.name)}</span>`
    ).join('');
    return `<div class="wf-hook-slot">
      <span class="wf-hook-slot-label">${slot.replace('_', ' ')}</span>${pills}
    </div>`;
  }).filter(Boolean).join('');

  // Role chip: prefer v2 prompt.role_ref (clickable), fallback to v1 role.
  const roleRef = step.prompt && step.prompt.role_ref;
  const roleChip = roleRef
    ? `<button type="button" class="btn-unstyled wf-role-chip" data-action="roles.preview" data-id="${esc(roleRef)}">role: ${esc(roleRef)}</button>`
    : (step.role
      ? `<span class="wf-role-chip inline" title="v1 role alias">role: ${esc(step.role)}</span>`
      : '');

  const modelUsed = (result && result.model_used) ? result.model_used : '';
  const retries = (result && result.retries) ? result.retries : 0;
  const attemptBadge = retries > 0
    ? `<span class="wf-attempt-badge">${retries + 1} attempts</span>`
    : '';

  return `
    <div class="wf-step">
      <div class="wf-step-box ${status || 'pending'}">
        <div class="wf-step-name">${esc(step.id || step.step_id)}${attemptBadge}</div>
        <div class="wf-step-role">${esc(modelUsed)}</div>
        ${roleChip}
        <div class="wf-step-status ${status || 'pending'}">${status || 'pending'}</div>
        ${hookBlocks ? `<div class="wf-step-hooks">${hookBlocks}</div>` : ''}
      </div>
    </div>
  `;
}

async function runWorkflow() {
  const sel = document.getElementById('wf-select');
  const opt = sel.selectedOptions[0];
  if (!opt || !opt.value) return;

  const btn = document.getElementById('wf-run-btn');
  btn.disabled = true;
  btn.textContent = 'EXECUTING...';

  let seed = {};
  try {
    seed = JSON.parse(document.getElementById('wf-seed').value || '{}');
  } catch (e) {
    Toast.warn('Invalid JSON in seed data');
    btn.disabled = false;
    btn.textContent = 'Run';
    return;
  }

  try {
    // retries:0 ESSENTIAL — synchronous run blocks for minutes; a 504-retry
    // would re-execute the entire workflow.
    const resp = await Net.call('/api/workflows/run', {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow_id: opt.dataset.id,
          seed: seed,
        }),
      },
    });
    if (resp.status === 0) throw new Error(resp.error || 'network error');
    const run = (resp.data && typeof resp.data === 'object') ? resp.data : {};

    // Show results
    document.getElementById('wf-results').style.display = 'block';
    const content = document.getElementById('wf-results-content');

    // Build pipeline visualization with results. Prefer the declared-step
    // metadata (hooks, role_ref) from currentWorkflowDef so each box still
    // shows its hook chain + role chip even when execution is mid-flight.
    const pipeline = document.getElementById('wf-pipeline');
    const defSteps = (currentWorkflowDef && currentWorkflowDef.steps) || [];
    const byId = new Map(defSteps.map(s => [s.id, s]));
    let pipeHtml = '';
    (run.step_results || []).forEach((res, i) => {
      if (i > 0) {
        const arrowClass = res.status === 'completed' ? 'done' : (res.status === 'running' ? 'active' : '');
        pipeHtml += `<div class="wf-arrow ${arrowClass}">&rarr;</div>`;
      }
      const step = byId.get(res.step_id) || { id: res.step_id, hooks: {} };
      pipeHtml += renderStepBox(step, res.status, res);
    });
    pipeline.innerHTML = pipeHtml;

    // Build results table
    let statusColor = run.status === 'completed' ? 'var(--green)' : 'var(--red)';
    let html = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-size:0.8rem;color:${statusColor};text-transform:uppercase;letter-spacing:0.1em;font-weight:600">${run.status}</span>
        <span class="wf-run-id">${run.run_id}</span>
      </div>
    `;
    html += _renderPreWarmSummary(run);  // Phase 5c — empty unless pre-warm fired

    (run.step_results || []).forEach(step => {
      const dur = step.duration_seconds ? step.duration_seconds.toFixed(1) + 's' : '-';
      const tokens = step.token_count ? step.token_count.total_tokens : 0;
      // Phase 2 telemetry: load chip shows whether the model was warm in
      // VRAM/RAM (<100ms) or cold-loaded for this step. Helps operators
      // debug "why is this step slow" without diving into Ollama logs.
      const loadChip = step.load_duration_ms != null
        ? (step.load_duration_ms < 100
            ? `<span class="step-load warm" title="model warm in memory (${step.load_duration_ms.toFixed(0)}ms)">warm</span>`
            : `<span class="step-load cold" title="cold-loaded for this step">${(step.load_duration_ms / 1000).toFixed(1)}s load</span>`)
        : '';
      html += `
        <div class="wf-result-step ${step.status}">
          <span class="step-name">${esc(step.step_id)}</span>
          <span class="step-model">${esc(step.model_used || '-')}</span>
          <span class="step-dur">${dur}</span>
          <span class="step-tokens">${tokens} tok</span>
          ${loadChip}
          <span style="color:${step.status === 'completed' ? 'var(--green)' : 'var(--red)'};font-size:0.68rem">${step.status}</span>
        </div>
      `;
    });

    if (run.error) {
      html += `<div style="margin-top:10px;padding:10px;background:var(--red-dim);border:1px solid var(--red);font-size:0.72rem;color:var(--text)">${esc(run.error)}</div>`;
    }

    // Context inspector — seed / workspace / shared
    html += renderContextInspector(run.context);

    content.innerHTML = html;

    // Refresh recent runs
    await loadRecentRuns();

  } catch (e) {
    document.getElementById('wf-results').style.display = 'block';
    document.getElementById('wf-results-content').innerHTML =
      `<div style="color:var(--red);font-size:0.75rem">Execution failed: ${esc(String(e))}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run';
  }
}

async function loadRecentRuns() {
  try {
    const runs = await Net.getJson('/api/workflows/runs?limit=10');
    const container = document.getElementById('wf-runs-list');

    if (!runs.length) {
      container.innerHTML = '<div class="model-empty">No workflow runs yet</div>';
      return;
    }

    container.innerHTML = runs.map(r => {
      // status color: green=done, red=failed, amber=running (likely a
      // crashed run since we only ever read persisted state, never live)
      const statusColor = r.status === 'completed' ? 'var(--green)'
                        : r.status === 'running' ? 'var(--amber)'
                        : 'var(--red)';
      const time = r.started_at ? new Date(r.started_at).toLocaleString() : '-';
      // Resume is offered only for runs left in "running" — those are
      // crashed mid-flight and have a persisted checkpoint to pick up
      // from. Terminal runs (completed/failed/canceled) don't show it
      // because resume() is a no-op for them.
      const resumeBtn = r.status === 'running'
        ? `<button class="action-btn" style="padding:2px 8px;font-size:0.65rem;color:var(--amber);border-color:var(--amber);"
                   data-action="runhist.resume"
                   title="Resume from the last checkpointed step">Resume</button>`
        : '';
      return `
        <div class="wf-run-item" role="button" tabindex="0" aria-label="View run ${(r.run_id || '').slice(0, 8)} of ${esc(r.workflow_id)}" data-action="runhist.view" data-run-id="${esc(r.run_id)}">
          <span class="wf-run-wf">${esc(r.workflow_id)}</span>
          <span class="wf-run-status" style="color:${statusColor}">${r.status}</span>
          <span class="wf-run-id">${(r.run_id || '').slice(0, 8)}...</span>
          <span class="wf-run-time">${time}</span>
          ${resumeBtn}
        </div>
      `;
    }).join('');
  } catch (e) {
    console.error('Failed to load runs:', e);
  }
}

// Delegated actions for the Composer run-history rows — the list refreshes
// after every run/resume. The row (role=button) carries data-run-id; the
// Resume button resolves it via closest() and keeps keyboard parity for
// the row through the delegated keydown below.
(function () {
  const runIdOf = el => {
    const row = el.closest('[data-run-id]');
    return row ? row.dataset.runId : '';
  };
  Actions.click({
    'runhist.view':   el => viewRun(runIdOf(el)),
    'runhist.resume': el => resumeRun(runIdOf(el), el)
  });
  Actions.on('keydown', {
    'runhist.view': (el, e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      viewRun(runIdOf(el));
    }
  });
})();

async function resumeRun(runId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'Resuming...'; }
  try {
    // retries:0 — resume re-executes steps and blocks until the run completes.
    const run = await Net.postJson(`/api/workflows/runs/${runId}/resume`, {}, { retries: 0 });
    // Refresh the list to reflect the new terminal status, then open the
    // detail panel so the operator sees what happened.
    await loadRecentRuns();
    viewRun(run.run_id);
  } catch (e) {
    console.error('Resume failed:', e);
    Toast.danger('Resume failed', e.message);
    loadRecentRuns();
  }
}

async function viewRun(runId) {
  try {
    const run = await Net.getJson(`/api/workflows/runs/${runId}`);

    // Show results panel
    document.getElementById('wf-detail').style.display = 'block';
    document.getElementById('wf-results').style.display = 'block';
    document.getElementById('wf-detail-name').textContent = run.workflow_id;
    document.getElementById('wf-detail-desc').textContent = `Run: ${runId}`;

    // Build pipeline from step results. Fetch full definition so hook chips
    // + role chips appear on historical runs too (requires engine workflow
    // to still exist on disk — otherwise we fall back to step_results only).
    const pipeline = document.getElementById('wf-pipeline');
    let defSteps = [];
    try {
      // silent: a 404 here is expected for deleted/private workflows —
      // the throw lands in this catch and we fall back to step_results.
      const d = await Net.getJson(`/api/workflows/${encodeURIComponent(run.workflow_id)}`, { silent: true });
      defSteps = d.steps || [];
      currentWorkflowDef = d;
    } catch (_) { /* fallback below */ }
    const byId = new Map(defSteps.map(s => [s.id, s]));
    let pipeHtml = '';
    (run.step_results || []).forEach((res, i) => {
      if (i > 0) {
        const arrowClass = res.status === 'completed' ? 'done' : '';
        pipeHtml += `<div class="wf-arrow ${arrowClass}">&rarr;</div>`;
      }
      const step = byId.get(res.step_id) || { id: res.step_id, hooks: {} };
      pipeHtml += renderStepBox(step, res.status, res);
    });
    pipeline.innerHTML = pipeHtml;

    // Build results
    const content = document.getElementById('wf-results-content');
    let statusColor = run.status === 'completed' ? 'var(--green)' : 'var(--red)';
    let html = `<div style="margin-bottom:12px;font-size:0.8rem;color:${statusColor};text-transform:uppercase;letter-spacing:0.1em;font-weight:600">${run.status}</div>`;
    html += _renderPreWarmSummary(run);  // Phase 5c — empty unless pre-warm fired
    (run.step_results || []).forEach(step => {
      const dur = step.duration_seconds ? step.duration_seconds.toFixed(1) + 's' : '-';
      const tokens = step.token_count ? step.token_count.total_tokens : 0;
      // Phase 2 telemetry: load chip shows whether the model was warm in
      // VRAM/RAM (<100ms) or cold-loaded for this step. Helps operators
      // debug "why is this step slow" without diving into Ollama logs.
      const loadChip = step.load_duration_ms != null
        ? (step.load_duration_ms < 100
            ? `<span class="step-load warm" title="model warm in memory (${step.load_duration_ms.toFixed(0)}ms)">warm</span>`
            : `<span class="step-load cold" title="cold-loaded for this step">${(step.load_duration_ms / 1000).toFixed(1)}s load</span>`)
        : '';
      html += `
        <div class="wf-result-step ${step.status}">
          <span class="step-name">${esc(step.step_id)}</span>
          <span class="step-model">${esc(step.model_used || '-')}</span>
          <span class="step-dur">${dur}</span>
          <span class="step-tokens">${tokens} tok</span>
          ${loadChip}
        </div>
      `;
    });

    html += renderContextInspector(run.context);

    content.innerHTML = html;
  } catch (e) {
    console.error('Failed to load run:', e);
  }
}

/**
 * Render the three-layer workflow context as a collapsible inspector.
 * Closes the "context-store has no UI" P1 gap from the 2026-04-23 audit.
 */
function renderContextInspector(ctx) {
  if (!ctx || typeof ctx !== 'object') return '';
  const seed = ctx.seed || {};
  const workspace = ctx.workspace || {};
  const shared = ctx.shared || {};
  const hasData = Object.keys(seed).length + Object.keys(workspace).length + Object.keys(shared).length > 0;
  if (!hasData) return '';

  const workspaceHtml = Object.keys(workspace).length === 0
    ? '<div class="ctx-empty">—</div>'
    : Object.entries(workspace).map(([stepId, outputs]) => `
        <details class="ctx-step">
          <summary>${esc(stepId)} <span class="ctx-step-keys">(${Object.keys(outputs || {}).length} outputs)</span></summary>
          <pre class="ctx-json">${esc(JSON.stringify(outputs, null, 2))}</pre>
        </details>
      `).join('');

  return `
    <details class="ctx-inspector">
      <summary>
        <span class="ctx-label">// WORKFLOW CONTEXT</span>
        <span class="ctx-meta">seed: ${Object.keys(seed).length} · workspace: ${Object.keys(workspace).length} steps · shared: ${Object.keys(shared).length}</span>
      </summary>
      <div class="ctx-body">
        <div class="ctx-section">
          <div class="ctx-heading">SEED <span class="ctx-sub">immutable user input</span></div>
          <pre class="ctx-json">${esc(JSON.stringify(seed, null, 2) || '{}')}</pre>
        </div>
        <div class="ctx-section">
          <div class="ctx-heading">WORKSPACE <span class="ctx-sub">per-step outputs</span></div>
          ${workspaceHtml}
        </div>
        <div class="ctx-section">
          <div class="ctx-heading">SHARED <span class="ctx-sub">cross-cutting state</span></div>
          <pre class="ctx-json">${esc(JSON.stringify(shared, null, 2) || '{}')}</pre>
        </div>
      </div>
    </details>
  `;
}

/* ── INIT ──────────────────────────────────────────────────────────
   IMPORTANT: must run AFTER the Auth fetch-wrapper IIFE installs
   (further down at the AdminAuth block). Otherwise the first
   loadModels() call goes out un-injected, hits /v1/models with no
   auth, gets 401 with d.data===undefined, and the picker stays
   stuck on the "loading…" sentinel forever. Deferring to
   DOMContentLoaded guarantees the wrapper is in place by then. */
document.addEventListener('DOMContentLoaded', () => {
  loadStatus();
  loadModels();
  setInterval(loadStatus, 10000);
});

// ── Memory Tab (Sessions / Facts / Stats) ────────────────────────
async function loadMemoryTab() {
  loadSessions();
  loadFacts();
  loadInjectionPreview();
  loadMemoryStats();
  loadProfiles();
  loadActiveSessions();
}

async function loadActiveSessions() {
  const el = document.getElementById('live-sessions-list');
  if (!el) return;
  try {
    const sessions = await Net.getJson('/api/context');
    if (!sessions.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.75rem;text-align:center;padding:20px;">No active sessions</div>';
      return;
    }
    el.innerHTML = sessions.map(s => {
      const started = new Date(s.started_at).toLocaleTimeString();
      const active  = new Date(s.last_activity).toLocaleTimeString();
      const skills  = s.skills_injected && s.skills_injected.length ? s.skills_injected.join(', ') : '—';
      const toolsHtml = s.tool_calls && s.tool_calls.length
        ? s.tool_calls.map(tc => `
            <div style="display:flex;gap:8px;padding:3px 0;border-bottom:1px solid var(--border);font-size:0.62rem;">
              <span style="color:var(--cyan);min-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(tc.tool_name)}</span>
              <span style="color:var(--text-muted)">${tc.duration_ms}ms</span>
              <span style="color:var(--text-dim)">${esc(new Date(tc.timestamp).toLocaleTimeString())}</span>
            </div>`).join('')
        : '<div style="color:var(--text-muted);font-size:0.62rem;padding:4px 0">No tool calls this session</div>';
      return `
        <div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div>
              <span style="font-family:var(--mono);font-size:0.7rem;color:var(--amber)">${esc(s.model)}</span>
              <span style="font-size:0.62rem;color:var(--text-muted);margin-left:8px">${esc((s.conversation_id||'').slice(0,12))}…</span>
            </div>
            <div style="display:flex;gap:6px;align-items:center">
              <span style="font-size:0.62rem;color:var(--text-dim)">${s.message_count||0} msgs · ${(s.tool_calls||[]).length} tools</span>
              <button data-action="mem.session-close" data-id="${esc(s.conversation_id)}"
                style="background:none;border:1px solid var(--red);color:var(--red);cursor:pointer;font-size:0.6rem;padding:1px 6px;border-radius:3px">close</button>
            </div>
          </div>
          <div style="font-size:0.62rem;color:var(--text-muted);margin-bottom:6px">
            started ${started} · active ${active} · skills: ${esc(skills)}
          </div>
          <details style="font-size:0.62rem">
            <summary style="color:var(--text-dim);cursor:pointer;user-select:none">Tool calls (${(s.tool_calls||[]).length})</summary>
            <div style="margin-top:4px;padding:4px;background:var(--bg-deep);border-radius:3px;max-height:120px;overflow-y:auto">
              ${toolsHtml}
            </div>
          </details>
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div style="color:var(--red);font-size:0.75rem;padding:10px">Error loading sessions: ${esc(String(e))}</div>`;
  }
}

async function closeSession(convId) {
  try {
    await Net.postJson('/api/context/' + encodeURIComponent(convId) + '/close', {}, { retries: 0 });
    loadActiveSessions();
  } catch (e) {
    Toast.danger('Failed to close session', String(e));
  }
}

async function cleanupStaleSessions() {
  try {
    const d = await Net.postJson('/api/context/cleanup', {}, { retries: 0 });
    await loadActiveSessions();
    if (typeof showToast === 'function') showToast('Cleaned up ' + (d.closed || 0) + ' stale session(s)');
  } catch (e) {
    Toast.danger('Cleanup failed', String(e));
  }
}

async function loadInjectionPreview() {
  try {
    const data = await Net.getJson('/api/memory/injection-preview');
    const pre = document.getElementById('injection-preview');
    const empty = document.getElementById('injection-empty');
    if (!data.injection_text) {
      pre.style.display = 'none';
      empty.style.display = '';
    } else {
      pre.style.display = '';
      empty.style.display = 'none';
      pre.textContent = data.injection_text;
    }
  } catch(e) { console.error('Failed to load injection preview:', e); }
}

async function loadSessions() {
  try {
    const sessions = await Net.getJson('/api/memory/sessions');
    const el = document.getElementById('session-list');
    if (!sessions.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No saved sessions yet.</div>';
      return;
    }
    el.innerHTML = sessions.map(s => `
      <div style="padding:10px;border-bottom:1px solid var(--border);cursor:pointer;" role="button" tabindex="0" aria-expanded="false" aria-controls="session-detail-${esc(s.id)}" data-action="mem.session-toggle" data-id="${esc(s.id)}">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div style="font-size:0.85rem;color:var(--text);max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(s.preview || 'No preview')}</div>
          <button data-action="mem.session-delete" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.75rem;">delete</button>
        </div>
        <div style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">
          ${esc(s.model || '')} · ${s.message_count || 0} msgs · ${s.tool_calls_count || 0} tool calls · ${s.duration_minutes || 0}m
        </div>
        <div id="session-detail-${esc(s.id)}" style="display:none;margin-top:8px;padding:8px;background:var(--bg-deep);border-radius:4px;font-size:0.75rem;"></div>
      </div>
    `).join('');
  } catch(e) { console.error('Failed to load sessions:', e); }
}

async function toggleSessionDetail(id) {
  const el = document.getElementById('session-detail-' + id);
  if (!el) return;
  const row = el.closest('[role="button"]');  // session row carries aria-expanded
  if (el.style.display !== 'none') { el.style.display = 'none'; if (row) row.setAttribute('aria-expanded', 'false'); return; }
  try {
    const s = await Net.getJson('/api/memory/sessions/' + id);
    let html = '<div style="color:var(--text-dim);">';
    if (s.tools_used && s.tools_used.length) html += '<div>Tools: ' + s.tools_used.join(', ') + '</div>';
    if (s.topics && s.topics.length) html += '<div>Topics: ' + s.topics.join(', ') + '</div>';
    if (s.tool_calls && s.tool_calls.length) {
      html += '<div style="margin-top:6px;font-weight:500;color:var(--text);">Tool Calls:</div>';
      s.tool_calls.forEach(tc => {
        html += '<div style="margin:4px 0;padding:4px;background:var(--bg);border-radius:3px;">' +
          '<span style="color:var(--cyan);">' + esc(tc.tool_name || '') + '</span> ' +
          '<span style="color:var(--text-muted);">' + (tc.duration_ms || 0) + 'ms</span></div>';
      });
    }
    html += '</div>';
    el.innerHTML = html;
    el.style.display = '';
    if (row) row.setAttribute('aria-expanded', 'true');
  } catch(e) { el.innerHTML = '<div style="color:var(--red);">Failed to load</div>'; el.style.display = ''; if (row) row.setAttribute('aria-expanded', 'true'); }
}

async function deleteSession(id) {
  // Net.call never throws — also fixes the latent unhandled rejection here.
  await Net.call('/api/memory/sessions/' + id, { retries: 0, init: { method: 'DELETE' } });
  loadSessions();
  loadMemoryStats();
}

async function loadFacts() {
  try {
    const facts = await Net.getJson('/api/memory/facts');
    const el = document.getElementById('facts-list');
    if (!facts.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No pinned facts. Add one above.</div>';
      return;
    }
    // Each fact gets a toggle + click-to-edit on the content. Disabled
    // facts are dimmed and excluded from the injection preview.
    el.innerHTML = facts.map(f => {
      const enabled = f.enabled !== false;
      const dim = enabled ? '' : 'opacity:0.45;';
      return `
      <div style="padding:8px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:start;gap:8px;${dim}">
        <div style="flex:1;min-width:0;">
          <div class="fact-content" id="fact-content-${esc(f.id)}"
               style="font-size:0.85rem;color:var(--text);cursor:text;word-wrap:break-word;"
               role="button" tabindex="0" aria-label="Edit fact"
               data-action="mem.fact-edit" data-id="${esc(f.id)}"
               title="Click to edit">${esc(f.content)}</div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:2px;">
            ${(f.tags||[]).map(t => '<span style="color:var(--cyan);">#'+esc(t)+'</span>').join(' ')}
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
          <button data-action="mem.fact-toggle" data-id="${esc(f.id)}" data-enabled="${enabled}"
                  title="${enabled ? 'Disable (parks the fact, won\'t inject)' : 'Enable (resume injection)'}"
                  style="background:none;border:1px solid var(--border);color:${enabled ? 'var(--cyan)' : 'var(--text-muted)'};cursor:pointer;font-size:0.7rem;padding:2px 8px;border-radius:3px;">
            ${enabled ? 'on' : 'off'}
          </button>
          <button data-action="mem.fact-delete" data-id="${esc(f.id)}" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.75rem;">delete</button>
        </div>
      </div>
    `;
    }).join('');
  } catch(e) { console.error('Failed to load facts:', e); }
}

async function toggleFact(id, currentlyEnabled) {
  try {
    await Net.call('/api/memory/facts/' + id, {
      retries: 0,
      init: {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: !currentlyEnabled}),
      },
    });
    loadFacts();
    loadInjectionPreview();
  } catch(e) { console.error('Toggle failed:', e); }
}

async function editFact(id, contentEl) {
  // Replace the content div with an inline textarea on click.
  if (contentEl.querySelector('textarea')) return;  // already editing
  const original = contentEl.textContent;
  const ta = document.createElement('textarea');
  ta.value = original;
  ta.style.cssText = 'width:100%;min-height:40px;background:var(--bg-deep);color:var(--text);border:1px solid var(--cyan);border-radius:3px;padding:4px;font:inherit;';
  contentEl.innerHTML = '';
  contentEl.appendChild(ta);
  ta.focus();
  ta.select();

  const commit = async () => {
    const next = ta.value.trim();
    if (!next || next === original) { loadFacts(); return; }
    try {
      await Net.call('/api/memory/facts/' + id, {
        retries: 0,
        init: {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({content: next}),
        },
      });
      loadFacts();
      loadInjectionPreview();
    } catch(e) { console.error('Edit failed:', e); loadFacts(); }
  };
  ta.addEventListener('blur', commit, {once: true});
  ta.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); ta.blur(); }
    if (ev.key === 'Escape') { loadFacts(); }
  });
}

async function addFact() {
  const input = document.getElementById('new-fact-input');
  const content = input.value.trim();
  if (!content) return;
  // .catch — postJson throws where the old bare fetch only rejected on
  // network error; without it a failure becomes an unhandled rejection.
  await Net.postJson('/api/memory/facts', { content, tags: [] }, { retries: 0 }).catch(() => {});
  input.value = '';
  loadFacts();
  loadInjectionPreview();
  loadMemoryStats();
}

async function deleteFact(id) {
  // Net.call never throws — also fixes the latent unhandled rejection here.
  await Net.call('/api/memory/facts/' + id, { retries: 0, init: { method: 'DELETE' } });
  loadFacts();
  loadInjectionPreview();
  loadMemoryStats();
}

// Delegated actions for the Memory tab dynamic rows — active sessions,
// saved sessions, and pinned facts all re-render on search/refresh. The
// fact toggle's former boolean `${enabled}` arg rides as a data-enabled
// "true"/"false" string; role=button divs keep Enter/Space operability
// via delegated keydown. The fact-edit keydown only fires for keys on
// the div itself (e.target check) so Space/Enter typed in the inline
// edit textarea aren't swallowed.
(function () {
  const idOf = el => {
    const host = el.closest('[data-id]');
    return host ? host.dataset.id : '';
  };
  Actions.click({
    'mem.session-close':  el => closeSession(el.dataset.id),
    'mem.session-toggle': el => toggleSessionDetail(el.dataset.id),
    'mem.session-delete': el => deleteSession(idOf(el)),
    'mem.fact-edit':      el => editFact(el.dataset.id, el),
    'mem.fact-toggle':    el => toggleFact(el.dataset.id, el.dataset.enabled === 'true'),
    'mem.fact-delete':    el => deleteFact(el.dataset.id)
  });
  Actions.on('keydown', {
    'mem.session-toggle': (el, e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      toggleSessionDetail(el.dataset.id);
    },
    'mem.fact-edit': (el, e) => {
      if (e.target !== el || (e.key !== 'Enter' && e.key !== ' ')) return;
      e.preventDefault();
      editFact(el.dataset.id, el);
    }
  });
})();

async function loadMemoryStats() {
  try {
    const s = await Net.getJson('/api/memory/stats', { silent: true });
    document.getElementById('stat-sessions').textContent = s.total_sessions || 0;
    document.getElementById('stat-tool-calls').textContent = s.total_tool_calls || 0;
    document.getElementById('stat-facts').textContent = s.total_facts || 0;
  } catch(e) {}
}

async function loadProfiles() {
  try {
    const [profiles, active] = await Promise.all([
      Net.getJson('/api/profiles'),
      Net.getJson('/api/profiles/active'),
    ]);
    document.getElementById('active-profile-id').textContent = active.default_profile_id || 'default';

    const el = document.getElementById('profiles-list');
    if (!profiles.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">No profiles loaded.</div>';
      return;
    }
    el.innerHTML = profiles.map(p => {
      const pluginCount = (p.allowed_plugins || []).length;
      const sandboxMode = (p.sandbox || {}).mode || 'none';
      const wildcard = (p.allowed_plugins || []).includes('*');
      return `
        <div style="padding:10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-deep);">
          <div style="font-size:0.85rem;color:var(--text);font-weight:500;">${esc(p.name || p.id)}</div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:2px;">${esc(p.description || '')}</div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:6px;">
            <span style="color:var(--cyan);">${wildcard ? 'all plugins' : pluginCount + ' plugins'}</span>
            · <span>sandbox: ${esc(sandboxMode)}</span>
          </div>
        </div>
      `;
    }).join('');
  } catch(e) { console.error('Failed to load profiles:', e); }
}

async function reloadProfiles() {
  try {
    await Net.postJson('/api/profiles/reload', {}, { retries: 0 });
    loadProfiles();
  } catch(e) { console.error('Reload failed:', e); }
}

async function searchMemory(query) {
  if (!query.trim()) { loadSessions(); return; }
  try {
    // Idempotent query-style POST (read-only search) — default retries kept.
    const r = await Net.call('/api/memory/sessions/search', {
      init: {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      },
    });
    if (r.status === 0) throw new Error(r.error || 'network error');
    const results = Array.isArray(r.data) ? r.data : [];
    const el = document.getElementById('session-list');
    if (!results.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No results for "' + esc(query) + '"</div>';
      return;
    }
    el.innerHTML = results.map(s => `
      <div style="padding:10px;border-bottom:1px solid var(--border);">
        <div style="font-size:0.85rem;color:var(--text);">${esc(s.preview || 'No preview')}</div>
        <div style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">${esc(s.model || '')} · ${s.message_count || 0} msgs</div>
      </div>
    `).join('');
  } catch(e) {}
}

// ── Documents Tab ────────────────────────────────────────────────
async function loadDocumentsTab() {
  loadDocumentsList();
  loadDocStats();
}

async function loadDocumentsList() {
  try {
    const docs = await Net.getJson('/api/documents');
    const el = document.getElementById('documents-list');
    if (!docs.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No documents yet. Upload above.</div>';
      return;
    }
    el.innerHTML = docs.map(d => {
      const sizeKb = ((d.size_bytes||0)/1024).toFixed(1);
      const statusColor = d.status === 'indexed' ? 'var(--cyan)' : (d.status === 'failed' ? 'var(--red)' : 'var(--text-dim)');
      return `
        <div style="padding:10px;border-bottom:1px solid var(--border);">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-size:0.85rem;color:var(--text);max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(d.filename)}</div>
            <div>
              <button data-action="docs.agent" data-id="${esc(d.id)}" data-filename="${esc(d.filename||'')}" title="Generate an agent from this document" style="background:none;border:none;color:var(--accent);cursor:pointer;font-size:0.75rem;margin-right:8px;font-weight:600;">→ Agent</button>
              <button data-action="docs.reindex" data-id="${esc(d.id)}" style="background:none;border:none;color:var(--cyan);cursor:pointer;font-size:0.75rem;margin-right:8px;">reindex</button>
              <button data-action="docs.delete" data-id="${esc(d.id)}" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.75rem;">delete</button>
            </div>
          </div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">
            <span style="color:${statusColor};">${esc(d.status)}</span>
            · ${sizeKb} KB · ${d.chunk_count||0} chunks
          </div>
        </div>
      `;
    }).join('');
  } catch(e) { console.error('Failed to load documents:', e); }
}

async function loadDocStats() {
  try {
    const s = await Net.getJson('/api/documents/stats', { silent: true });
    document.getElementById('doc-stat-count').textContent = s.total_documents || 0;
    document.getElementById('doc-stat-chunks').textContent = s.total_chunks || 0;
    const emb = s.embedding || {};
    document.getElementById('doc-stat-backend').textContent = `${emb.backend || '—'} (${emb.model || '—'})`;
  } catch(e) {}
}

// Internal: post a single File to /api/documents and refresh the list.
// Called both from the <input onchange> auto-upload AND the drag-drop
// handler, so file-selection and drag-drop share the same code path.
async function _uploadDocumentFile(file) {
  const status = document.getElementById('doc-upload-status');
  status.textContent = `Uploading ${file.name}…`;
  const form = new FormData();
  form.append('file', file);
  try {
    // raw fetch: FormData multipart upload — Net.postJson JSON-encodes the body,
    // and a retry would double-upload the file (Net doesn't support this).
    const r = await fetch('/api/documents', { method: 'POST', body: form });
    const data = await r.json();
    if (!r.ok) { status.textContent = `Error: ${data.detail || 'upload failed'}`; return; }
    status.textContent = `✓ Indexed ${data.filename} (${data.chunk_count} chunks)`;
    loadDocumentsList();
    loadDocStats();
  } catch(e) { status.textContent = `Error: ${e.message}`; }
}

async function uploadDocument() {
  const input = document.getElementById('doc-file-input');
  if (!input.files.length) {
    const status = document.getElementById('doc-upload-status');
    if (status) status.textContent = 'Pick a file first.';
    return;
  }
  await _uploadDocumentFile(input.files[0]);
  input.value = '';   // reset so picking the same file again re-fires onchange
}

// Drag-and-drop wiring for the Documents drop zone. Mirrors the visual
// state class `.is-dragging` so the zone highlights under the cursor.
// IA shuffle (2026-05-18): the Knowledge Graph + Deep Research panel
// used to live in the now-removed "Skill Lab" tab. Move them into the
// Context tab once on boot — preserves IDs, listeners, and the
// existing initResearch() lifecycle without any per-call DOM lookup
// changes elsewhere.
document.addEventListener('DOMContentLoaded', () => {
  const layout = document.querySelector('#tab-research .research-layout');
  const ctxTab = document.getElementById('tab-documents');
  if (layout && ctxTab) {
    // Prepend so the graph + research are at the top of the Context
    // tab; existing documents/search panels follow.
    ctxTab.insertBefore(layout, ctxTab.firstChild);
    // Add a thin header separating the new content from the legacy
    // documents UI below.
    const sep = document.createElement('div');
    sep.className = 'panel-label';
    sep.style.cssText = 'margin: 18px 0 10px; padding-top: 8px; border-top: 1px dashed var(--border)';
    sep.textContent = '// Documents + RAG';
    layout.after(sep);
  }

  // IA shuffle (cont.): the 5 Discover panels that previously lived
  // INSIDE the Models tab (#tab-inventory) move into the Catalog
  // page's per-section mounts. Each panel keeps its existing ID
  // (#discover-section, #skills-discover-panel, #plugins-discover-
  // section, #mcps-discover-section, #ext-discover-section) so the
  // loaders that target those IDs keep writing to the right element.
  //
  // The Models inventory list (.inv-grid #inv-grid + hw-info +
  // .inv-toolbar) also moves so the Catalog's "Models" section
  // hosts the full management surface, not just the HF discover.
  {
    const moves = [
      // [destination-mount-id, source-element-id]
      ['catalog-skills-mount',   'skills-discover-panel'],
      ['catalog-plugins-mount',  'plugins-discover-section'],
      ['catalog-mcp-mount',      'mcps-discover-section'],
      ['catalog-external-mount', 'ext-discover-section'],
    ];
    moves.forEach(([destId, srcId]) => {
      const dest = document.getElementById(destId);
      const src  = document.getElementById(srcId);
      if (dest && src) {
        // Clear the placeholder first.
        dest.innerHTML = '';
        dest.appendChild(src);
      }
    });
    // Models section — keep the canonical inventory DOM IN PLACE
    // (inside #tab-inventory) so the Models tab still renders, and
    // have the Catalog Models section LAZILY relocate when active.
    // window.CatalogModelsShare is the move-back-and-forth manager;
    // _relocateInventoryToCatalog / _relocateInventoryBack swap the
    // shared DOM between the two homes on tab activation.
    //
    // (The previous version ran modelsMount.innerHTML = '' + a single
    // appendChild loop here at DOMContentLoaded, which permanently
    // ripped the inventory grid out of #tab-inventory — the Models
    // tab rendered empty thereafter. Bug surfaced in PR #71 review.)
    window.CatalogModelsShare = (function () {
      let inCatalog = false;
      const ids = ['inv-stats', 'inv-grid', 'discover-section'];
      const sel = ['.panel', '.inv-toolbar'];
      function _nodes() {
        const arr = [];
        // Hardware profile + toolbar are sibling elements of
        // #tab-inventory; grab them by selector. The grid + stats +
        // discover have stable ids.
        sel.forEach(s => {
          const home = document.getElementById('tab-inventory');
          const owned = document.getElementById('catalog-models-mount');
          (home?.querySelector(s) || owned?.querySelector(s))
            && arr.push(home?.querySelector(s) || owned.querySelector(s));
        });
        ids.forEach(id => { const n = document.getElementById(id); if (n) arr.push(n); });
        return arr;
      }
      function _moveTo(host) {
        if (!host) return;
        _nodes().forEach(n => { try { host.appendChild(n); } catch (_) {} });
      }
      return {
        showInCatalog() {
          if (inCatalog) return;
          const mount = document.getElementById('catalog-models-mount');
          if (!mount) return;
          // Drop the "Loading model catalog…" placeholder before we
          // move the real grid in.
          mount.replaceChildren();
          _moveTo(mount);
          inCatalog = true;
        },
        showInModelsTab() {
          if (!inCatalog) return;
          const home = document.getElementById('tab-inventory');
          if (!home) return;
          _moveTo(home);
          inCatalog = false;
        },
        get isInCatalog() { return inCatalog; },
      };
    })();

    // SkillsDiscoverShare — the discovery/catalog panel (#skills-discover-
    // panel) is a single DOM node. By default it lives in the Catalog's
    // Skills mount (the move above). This manager relocates it into the
    // standalone Skills tab (#skills-tab-discover-mount) when that tab is
    // active and back to the Catalog when the Catalog is shown — so the
    // SAME discovery surface (curated catalog + Browse repo + Import URL +
    // installable external-source skills) appears in both places.
    window.SkillsDiscoverShare = (function () {
      let inSkillsTab = false;
      function _panel() { return document.getElementById('skills-discover-panel'); }
      return {
        showInSkillsTab() {
          if (inSkillsTab) return;
          const panel = _panel();
          const mount = document.getElementById('skills-tab-discover-mount');
          if (!panel || !mount) return;
          mount.replaceChildren();
          mount.appendChild(panel);
          panel.open = true;  // expand by default in its dedicated tab
          inSkillsTab = true;
        },
        showInCatalog() {
          if (!inSkillsTab) return;
          const panel = _panel();
          const mount = document.getElementById('catalog-skills-mount');
          if (!panel || !mount) return;
          mount.replaceChildren();
          mount.appendChild(panel);
          inSkillsTab = false;
        },
        get isInSkillsTab() { return inSkillsTab; },
      };
    })();
  }

  // IA shuffle (cont.): Projects + Kanban relocates from inside the
  // Workflow Index to its own top-level tab. Move the panel + its
  // modal so the IDs (kanban-panel, kanban-board, kanban-project-
  // select, kanban-modal, …) keep working — every Kanban call site
  // looks them up by id at use-time, so a DOM move is transparent.
  const projTab = document.getElementById('tab-projects');
  const kanbanPanel = document.getElementById('kanban-panel');
  const kanbanModal = document.getElementById('kanban-modal');
  if (projTab && kanbanPanel) {
    const placeholder = document.getElementById('projects-tab-placeholder');
    if (placeholder) placeholder.remove();
    projTab.appendChild(kanbanPanel);
    if (kanbanModal) projTab.appendChild(kanbanModal);
  }

  // IA shuffle (cont.): the Role Library now lives at the bottom of
  // the Context tab. Built fresh here because the original panel
  // inside tab-workflows was replaced by the Catalog dashboard; the
  // legacy IDs (#wf-roles-list, #wf-role-preview) live in a hidden
  // mount inside tab-workflows so loadRoles() still has targets if
  // ever called from there — but we ALSO mount visible copies into
  // Context. loadRoles() finds the FIRST matching id, so the newest
  // wf-roles-list is the visible one.
  if (ctxTab) {
    const rolesSep = document.createElement('div');
    rolesSep.className = 'panel-label';
    rolesSep.style.cssText = 'margin: 18px 0 10px; padding-top: 8px; border-top: 1px dashed var(--border)';
    rolesSep.textContent = '// Role Library';
    ctxTab.appendChild(rolesSep);

    const rolesPanel = document.createElement('div');
    rolesPanel.className = 'panel';
    rolesPanel.style.marginBottom = '16px';
    rolesPanel.innerHTML = `
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div class="panel-label">// ROLE LIBRARY
        <span style="float:right;font-size:0.6rem;color:var(--text-muted);letter-spacing:0.1em">prompts/roles/</span>
      </div>
      <div id="wf-roles-list-ctx" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;margin-top:10px"></div>
      <div id="wf-role-preview-ctx" style="display:none;margin-top:14px;padding:12px;background:var(--bg-deep);border-left:2px solid var(--accent-dim);font-family:var(--mono);font-size:0.72rem;line-height:1.6;white-space:pre-wrap;color:var(--text-dim)"></div>`;
    ctxTab.appendChild(rolesPanel);
    // Rewrite the legacy IDs so loadRoles() (which targets
    // #wf-roles-list) writes into the new visible container.
    // Sequence: rename legacy → strip; promote ctx → legacy id.
    const legacy = document.getElementById('wf-roles-list');
    if (legacy) legacy.id = 'wf-roles-list-legacy';
    const legacyPv = document.getElementById('wf-role-preview');
    if (legacyPv) legacyPv.id = 'wf-role-preview-legacy';
    document.getElementById('wf-roles-list-ctx').id = 'wf-roles-list';
    document.getElementById('wf-role-preview-ctx').id = 'wf-role-preview';
  }
});

/* ── HASH ROUTES (deep links) ───────────────────────────────────────
   #/<tab> mirrors the active tab; #/runs/<run_id> additionally selects
   that run. replaceState keeps history clean — back/forward tab-surfing
   is deliberately NOT a feature (tabs are workspace state, not pages),
   but every tab, filter view, and selected run is now shareable and
   reload-safe. Registration order matters: this DOMContentLoaded
   handler must run AFTER the IA relocators above (moved panels exist)
   and BEFORE the ComposerView lazy-boot (whose dashboard-active guard
   then correctly skips when the hash routed elsewhere). bootSignIn's
   soft re-init re-fires the active tab, which is hash-stable. */
initRouter();  // hash router — registered here to preserve DOMContentLoaded order (phase-2 U3)

document.addEventListener('DOMContentLoaded', () => {
  const zone = document.getElementById('doc-drop-zone');
  if (!zone) return;
  ['dragenter','dragover'].forEach(evt =>
    zone.addEventListener(evt, e => {
      e.preventDefault(); e.stopPropagation();
      zone.classList.add('is-dragging');
    })
  );
  ['dragleave','dragend','drop'].forEach(evt =>
    zone.addEventListener(evt, e => {
      e.preventDefault(); e.stopPropagation();
      zone.classList.remove('is-dragging');
    })
  );
  zone.addEventListener('drop', async (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) await _uploadDocumentFile(f);
  });
});

async function deleteDocument(id) {
  // Net.call never throws — also fixes the latent unhandled rejection here.
  await Net.call('/api/documents/' + id, { retries: 0, init: { method: 'DELETE' } });
  loadDocumentsList();
  loadDocStats();
}

async function reindexDocument(id) {
  const status = document.getElementById('doc-upload-status');
  status.textContent = 'Reindexing...';
  // Net.call: needs ok + body simultaneously. retries:0 — reindex triggers work.
  const r = await Net.call('/api/documents/' + id + '/reindex', { retries: 0, init: { method: 'POST' } });
  const data = (r.data && typeof r.data === 'object') ? r.data : {};
  status.textContent = r.ok ? `Reindexed: ${data.filename}` : `Error: ${data.detail || 'reindex failed'}`;
  loadDocumentsList();
  loadDocStats();
}

// Delegated actions for the Documents tab rows — the list re-renders on
// every upload/reindex/delete.
Actions.click({
  'docs.agent':   el => AgentGen.openFromDocument(el.dataset.id, el.dataset.filename),
  'docs.reindex': el => reindexDocument(el.dataset.id),
  'docs.delete':  el => deleteDocument(el.dataset.id)
});

async function searchDocuments() {
  const input = document.getElementById('doc-search-input');
  const query = input.value.trim();
  const el = document.getElementById('doc-search-results');
  if (!query) { el.innerHTML = ''; return; }
  el.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem;padding:8px;">Searching...</div>';
  try {
    // Idempotent query-style POST (read-only search) — default retries kept.
    const r = await Net.call('/api/documents/search', {
      init: {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ query, top_k: 5 }),
      },
    });
    if (r.status === 0) throw new Error(r.error || 'network error');
    const data = (r.data && typeof r.data === 'object') ? r.data : {};
    if (!data.results || !data.results.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No matches.</div>';
      return;
    }
    el.innerHTML = data.results.map((r, i) => `
      <div style="padding:10px;border-bottom:1px solid var(--border);">
        <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:4px;">
          <span style="color:var(--cyan);">[${i+1}]</span> ${esc(r.filename)} (chunk ${r.chunk_index}, score: ${r.score})
        </div>
        <div style="font-size:0.8rem;color:var(--text);">${esc(r.text).slice(0, 300)}${r.text.length > 300 ? '…' : ''}</div>
      </div>
    `).join('');
  } catch(e) {
    el.innerHTML = `<div style="color:var(--red);font-size:0.8rem;padding:8px;">Error: ${esc(e.message)}</div>`;
  }
}

/* ══════════════════════════════════════════════════════════════════
   WORKFLOW COMPOSER — Visual node-based workflow builder
   ══════════════════════════════════════════════════════════════════ */

let dfEditor = null;
let dfNodeData = {};
let dfNextId = 0;
let dfSelectedNodeId = null;
// Declared seed schema (the START anchor's editable input contract):
// [{ key, description }]. Persisted to the workflow definition under
// context.inputs and round-tripped on load. Drives the START anchor chips
// and the run-seed scaffold.
let dfSeedSchema = [];
// Guard so the anchor refresh (which itself adds/removes drawflow nodes +
// connections) doesn't recurse through the node/connection event hooks.
let _dfAnchorBusy = false;
let _dfAnchorTimer = null;

// Each template carries a `persona` key — the same vocabulary AgentIcons
// uses, so the palette glyph, the agent card glyph, and the run-state
// overlay all share one visual language. `role` is the LLM-routing class
// (reasoning / coding / fast / uncensored / general) and is independent
// of persona.
const dfStepTemplates = [
  { key: 'analyzer',    persona: 'analyzer',  name: 'Analyzer',       role: 'reasoning',   prompt: 'Analyze the provided data and extract key findings.',      outputs: ['analysis'],        format: 'json', color: '#00C0E8' },
  { key: 'classifier',  persona: 'classifier',name: 'Classifier',     role: 'reasoning',   prompt: 'Classify the following items into categories.',           outputs: ['classification'],  format: 'json', color: '#00C0E8' },
  { key: 'planner',     persona: 'planner',   name: 'Planner',        role: 'reasoning',   prompt: 'Decompose the request into an ordered plan of sub-tasks.', outputs: ['plan'],           format: 'json', color: '#00C0E8' },
  { key: 'retriever',   persona: 'retriever', name: 'Retriever',      role: 'fast',        prompt: 'Retrieve the most relevant context for the question.',     outputs: ['chunks'],         format: 'json', color: '#b388ff' },
  { key: 'code_gen',    persona: 'coder',     name: 'Code Generator', role: 'coding',      prompt: 'Generate code that implements the requirements.',          outputs: ['code'],           format: 'raw',  color: '#2bd4b4' },
  { key: 'rule_writer', persona: 'writer',    name: 'Rule Writer',    role: 'coding',      prompt: 'Write validation rules based on the schema.',              outputs: ['rules'],          format: 'json', color: '#2bd4b4' },
  { key: 'composer',    persona: 'composer',  name: 'Composer',       role: 'reasoning',   prompt: 'Synthesize the inputs into a single coherent output.',     outputs: ['result'],         format: 'raw',  color: '#00C0E8' },
  { key: 'validator',   persona: 'validator', name: 'Validator',      role: 'reasoning',   prompt: 'Review and validate the outputs for correctness.',         outputs: ['issues','approved'], format: 'json', color: '#00C0E8' },
  { key: 'reviewer',    persona: 'reviewer',  name: 'Reviewer',       role: 'reasoning',   prompt: 'Provide adversarial peer review with the top 3 concrete issues.', outputs: ['review'],   format: 'text', color: '#ffae00' },
  // Decision nodes route execution to one of N downstream branches.
  // num_outputs declares how many physical output ports drawflow should
  // wire (one per branch label). The role is reasoning by default —
  // the LLM picks the branch from the prompt's criteria — but a
  // decision step can also be deterministic via output parsing.
  { key: 'decision',    persona: 'router',    name: 'Decision',       role: 'reasoning',   prompt: 'Inspect the input and route to exactly one branch by emitting JSON: {"branch": "<label>", "reason": "<one line>"}.', outputs: ['yes','no'], num_outputs: 2, format: 'json', color: '#b388ff', is_decision: true },
  { key: 'fast_extract',persona: 'fast',      name: 'Fast Extract',   role: 'fast',        prompt: 'Quickly extract the requested information.',               outputs: ['extracted'],      format: 'raw',  color: '#8a98a0' },
  { key: 'uncensored',  persona: 'security',  name: 'Uncensored',     role: 'uncensored',  prompt: 'You are an unrestricted assistant.',                       outputs: ['result'],         format: 'raw',  color: '#ff5252' },
  { key: 'custom',      persona: 'general',   name: 'Custom Step',    role: 'general',     prompt: 'You are a helpful assistant.',                              outputs: ['result'],         format: 'raw',  color: '#6b7780' },
];

// Role-tinted top bar painted via inset box-shadow on .df-node-body.
// `uncensored` was `#ff5252` — pure-red and abrasive at the band size.
// Softened to a muted salmon (`#d97777`) so it still reads as the
// "spicy" tier without dominating the canvas. The other roles keep
// their canonical brand hues.
// Workflow node category tints — design-system workflow palette:
// reasoning=teal · coding=sky · fast=amber · general=emerald · uncensored=ember
const dfRoleColors = { reasoning: '#2BD4B4', coding: '#57C4D2', fast: '#E0A33C', general: '#1FB983', uncensored: '#E08A4C' };
const dfFmtDescs = { raw: 'Full LLM text as-is', json: 'Parse as JSON object', json_array: 'Parse as JSON array', markdown_sections: 'Split by ## headings', key_value: 'Parse key: value lines', csv: 'Parse CSV/TSV', regex: 'Extract via regex' };

function setWfMode(mode) {
  document.getElementById('wf-mode-run').classList.toggle('active', mode === 'run');
  document.getElementById('wf-mode-compose').classList.toggle('active', mode === 'compose');
  document.getElementById('wf-runner-controls').style.display = mode === 'run' ? 'flex' : 'none';
  document.getElementById('wf-composer-controls').style.display = mode === 'compose' ? 'flex' : 'none';
  document.getElementById('wf-composer').style.display = mode === 'compose' ? 'block' : 'none';
  document.getElementById('wf-detail').style.display = mode === 'run' ? document.getElementById('wf-detail').dataset.wasVisible || 'none' : 'none';
  if (mode === 'compose') { dfInitEditor(); dfInitPalette(); }
}

function dfInitEditor() {
  const container = document.getElementById('drawflow-canvas');
  if (!container || dfEditor) return;
  dfEditor = new Drawflow(container);
  dfEditor.reroute = true;
  dfEditor.reroute_fix_curvature = true;
  dfEditor.start();
  dfEditor.on('nodeSelected', (id) => {
    dfSelectedNodeId = id;
    dfRenderConfigPanel(id);
    // Engage the dashboard chat input against this step so the
    // operator can iterate by typing without leaving the canvas.
    if (typeof composerEnterStepEngage === 'function') composerEnterStepEngage(id);
    // Surface the selection in the bottom workstream — auto-switch to
    // Step Config and stamp the meta with the node id.
    if (window.ComposerWorkstream) {
      try {
        const data = dfNodeData && dfNodeData[id];
        const label = data && (data.id || data.name) ? (data.id || data.name) : id;
        ComposerWorkstream.focusStep(label);
      } catch (_) { ComposerWorkstream.focusStep(id); }
    }
  });
  dfEditor.on('nodeUnselected', () => {
    dfSelectedNodeId = null;
    dfClearConfigPanel();
    if (typeof composerExitStepEngage === 'function') composerExitStepEngage();
  });
  dfEditor.on('nodeRemoved', (id) => {
    delete dfNodeData[id];
    if (dfSelectedNodeId === id) dfSelectedNodeId = null;
    dfClearConfigPanel();
    if (typeof composerExitStepEngage === 'function') composerExitStepEngage();
    // Composition just lost a step — refresh the chat picker so the
    // "From composition" group reflects what's actually on the canvas.
    if (typeof syncCompositionModelsToChatPicker === 'function') {
      try { syncCompositionModelsToChatPicker(); } catch (_) {}
    }
    if (!_dfAnchorBusy) dfScheduleAnchorRefresh();  // re-bracket begin/end
  });
  dfEditor.on('connectionCreated', (conn) => { dfOnConnectionCreated(conn); if (!_dfAnchorBusy) dfScheduleAnchorRefresh(); });
  dfEditor.on('connectionRemoved', (conn) => { dfOnConnectionRemoved(conn); if (!_dfAnchorBusy) dfScheduleAnchorRefresh(); });

  container.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; });
  container.addEventListener('drop', (e) => {
    e.preventDefault();
    const rect = container.getBoundingClientRect();
    const canvasX = (e.clientX - rect.left - dfEditor.precanvas.getBoundingClientRect().left + rect.left);
    const canvasY = (e.clientY - rect.top  - dfEditor.precanvas.getBoundingClientRect().top  + rect.top);
    // Templates take priority — they're the cheapest spawn.
    const tmplKey = e.dataTransfer.getData('application/df-template');
    if (tmplKey) {
      dfAddNodeFromTemplate(tmplKey, canvasX, canvasY);
      return;
    }
    // Agent drop: fetch the agent's full definition, then spawn a step
    // pre-filled with its role, model, system_prompt, name. The user
    // can edit any field afterwards just like any other step.
    const agentId = e.dataTransfer.getData('application/df-agent');
    if (agentId) {
      dfAddNodeFromAgent(agentId, canvasX, canvasY);
      return;
    }
    // Skills / plugin tools / MCP tools attach to the SELECTED step
    // rather than spawning a new node — they're per-step equipment.
    // (Existing flow elsewhere in the file handles this; left intact.)
  });
}

// Click-to-add fallback for the workbench agent cards. HTML5 drag-and-
// drop is finicky across browser zoom + macOS trackpad gestures; in
// the live demo the operator reported drag-from-side-panel-to-canvas
// silently dropping events. This handler spawns the agent at the
// visible-center of the canvas, scrolled-into-view, so a single click
// is always reliable. dfInitEditor + the existing dfAddNodeFromAgent
// path are reused — no parallel implementation.
async function composerAddAgentAtCenter(agentId) {
  // Make sure the composer canvas exists. If the operator clicked the
  // card while on a different tab, switch over first so the canvas
  // mounts (idempotent if already there).
  if (typeof switchTab === 'function' && document.getElementById('tab-dashboard') &&
      !document.getElementById('tab-dashboard').classList.contains('active')) {
    switchTab('dashboard');
  }
  if (typeof ComposerView !== 'undefined' && ComposerView && ComposerView.init) {
    try { ComposerView.init(); } catch (_) {}
  } else if (typeof dfInitEditor === 'function') {
    try { dfInitEditor(); } catch (_) {}
  }
  if (typeof dfEditor === 'undefined' || !dfEditor) {
    if (window.Toast) Toast.warn('Canvas not ready', 'Try again in a moment', { ttl: 1800 });
    return;
  }
  // Find the canvas's visible center in precanvas coordinates so the
  // node lands where the operator is looking. Account for any zoom +
  // pan the operator has applied so the spawn is predictable.
  const canvas = document.getElementById('drawflow-canvas');
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const precanvas = dfEditor.precanvas || canvas;
  const pre = precanvas.getBoundingClientRect();
  const zoom = (typeof dfEditor.zoom === 'number') ? dfEditor.zoom : 1;
  // Center of the visible canvas region, in precanvas coords.
  const visibleCx = rect.left + rect.width / 2;
  const visibleCy = rect.top + rect.height / 2;
  const canvasX = (visibleCx - pre.left) / zoom;
  const canvasY = (visibleCy - pre.top) / zoom;
  // Apply a tiny offset so multiple successive clicks don't stack
  // exactly on top of each other.
  const jitter = (Math.random() - 0.5) * 60;
  await dfAddNodeFromAgent(agentId, canvasX + jitter, canvasY + jitter);
  if (window.Toast) Toast.info('Added agent', agentId, { ttl: 1400 });
}
window.composerAddAgentAtCenter = composerAddAgentAtCenter;

async function dfAddNodeFromAgent(agentId, x, y) {
  // Fetch agent definition; spawn an AgentStep clone.
  try {
    const r = await Net.call(`/api/agents/${encodeURIComponent(agentId)}`);
    if (!r.ok) { Toast.danger(`Could not load agent '${agentId}'`, `HTTP ${r.status}`); return; }
    const a = r.data;
    const data = {
      id: agentId + '_' + (++dfNextId),
      name: a.name || agentId,
      role: a.role || 'general',
      // Persona resolves through the same AgentIcons rules used in the
      // workbench, so a step forked from an agent inherits that agent's
      // glyph on the canvas.
      persona: (window.AgentIcons ? AgentIcons.resolve(a) : (a.icon || 'general')),
      model: a.model || '',
      system_prompt: a.system_prompt || `You are ${a.name || agentId}.`,
      outputs: ['result'],
      output_format: 'text',
      quality_gates: [],
      inputs: [],
      // Provenance — surfaced in the node config panel so the operator
      // remembers which agent this step was forked from.
      _from_agent: agentId,
    };
    const nodeId = dfEditor.addNode(data.id, 1, 1, x, y, data.id, {}, dfNodeHtml(data));
    dfNodeData[nodeId] = data;
    dfSelectedNodeId = nodeId;
    dfRenderConfigPanel(nodeId);
    dfAutoChain(nodeId);  // native wire onto the current tail
    if (!_dfAnchorBusy) dfScheduleAnchorRefresh();
    return nodeId;
  } catch (e) {
    Toast.danger('Drop failed', e.message);
  }
}

// ── Workflow run-state overlay on the canvas ────────────────────────
// Translates a run object (from /api/workflows/runs/{id}) into per-node
// status classes + a floating progress chip. Called by:
//   - ComposerWorkstream.startPolling() on every poll tick
//   - dfClearRunState() when the user starts a fresh edit/run
//
// Step-id matching: drawflow IDs are integers; the *logical* step id
// (matching `step_results[].step_id`) lives in dfNodeData[drawflowId].id.
function dfFindNodeIdForStep(stepId) {
  if (!stepId) return null;
  if (!window.dfNodeData) return null;
  for (const dfId of Object.keys(dfNodeData)) {
    const data = dfNodeData[dfId];
    if (data && (data.id === stepId || data.name === stepId)) return dfId;
  }
  return null;
}

function dfClearRunState() {
  document.querySelectorAll('.drawflow-node').forEach(el => {
    el.classList.remove('is-queued', 'is-running', 'is-completed', 'is-failed', 'is-skipped');
  });
  const chip = document.getElementById('df-run-progress');
  if (chip) chip.classList.remove('visible');
  // No active run → hide the toolbar Stop control.
  _dfToggleStopBtn(false);
  window._composerActiveRunId = null;
}

// Show/hide + reset the composer toolbar Stop button. Centralized so the
// run-state hooks stay one-liners.
function _dfToggleStopBtn(show) {
  const btn = document.getElementById('composer-stop-btn');
  if (!btn) return;
  btn.hidden = !show;
  if (show) { btn.disabled = false; btn.textContent = '◼ Stop'; }
}

function dfApplyRunState(run) {
  if (!run) { dfClearRunState(); return; }
  const results = Array.isArray(run.step_results) ? run.step_results : [];
  // Build a step_id → status map. Steps without a result entry are
  // implicitly queued (the engine hasn't started them yet).
  const status = new Map();
  results.forEach(r => { if (r && r.step_id) status.set(r.step_id, r.status || ''); });

  // The run's `steps` field (if present) lists the planned step order
  // so we can mark un-started ones as queued.
  const planned = Array.isArray(run.steps) ? run.steps
                : Array.isArray(run.workflow_steps) ? run.workflow_steps
                : Object.keys(dfNodeData || {}).map(k => (dfNodeData[k] || {}).id).filter(Boolean);
  const terminalRunStatus = ['completed', 'failed', 'error', 'cancelled', 'canceled'].includes(String(run.status || '').toLowerCase());

  // Toolbar Stop button: live only while the run is non-terminal. Track the
  // active run id so composerStopRun() can target it.
  if (terminalRunStatus) {
    _dfToggleStopBtn(false);
    window._composerActiveRunId = null;
  } else {
    window._composerActiveRunId = run.run_id || window._composerActiveRunId || null;
    _dfToggleStopBtn(true);
  }

  let completed = 0;
  let total = 0;
  let currentLabel = '';

  // Tag every known canvas node.
  (planned || []).forEach(stepId => {
    if (!stepId) return;
    total += 1;
    const st = status.get(stepId);
    const dfId = dfFindNodeIdForStep(stepId);
    if (!dfId) return;
    const el = document.getElementById('node-' + dfId);
    if (!el) return;
    el.classList.remove('is-queued', 'is-running', 'is-completed', 'is-failed', 'is-skipped');
    if (st === 'completed') { el.classList.add('is-completed'); completed += 1; }
    else if (st === 'running') { el.classList.add('is-running'); currentLabel = stepId; }
    else if (st === 'failed' || st === 'error') { el.classList.add('is-failed'); }
    else if (st === 'skipped') { el.classList.add('is-skipped'); }
    else if (!terminalRunStatus) { el.classList.add('is-queued'); }
  });

  // Update the floating chip.
  const chip = document.getElementById('df-run-progress');
  if (!chip) return;
  const spinner = document.getElementById('df-run-progress-spinner');
  const labelEl = document.getElementById('df-run-progress-current');
  const countEl = document.getElementById('df-run-progress-count');
  const barEl   = document.getElementById('df-run-progress-bar-fill');

  if (terminalRunStatus && String(run.status).toLowerCase() === 'completed') {
    spinner.className = 'df-run-progress-spinner done';
    labelEl.textContent = 'complete';
    if (countEl) countEl.textContent = `${completed}/${total}`;
    if (barEl) barEl.style.width = '100%';
    chip.classList.add('visible');
    // Linger briefly so the operator sees the green, then fade.
    clearTimeout(window._dfRunChipFadeTimer);
    window._dfRunChipFadeTimer = setTimeout(() => chip.classList.remove('visible'), 4500);
    return;
  }
  if (terminalRunStatus) {
    spinner.className = 'df-run-progress-spinner failed';
    labelEl.textContent = String(run.status || 'failed');
    if (countEl) countEl.textContent = `${completed}/${total}`;
    if (barEl) barEl.style.width = `${total ? (completed / total) * 100 : 0}%`;
    chip.classList.add('visible');
    return;
  }
  // Running.
  spinner.className = 'df-run-progress-spinner';
  labelEl.textContent = currentLabel || run.workflow_id || run.run_id || 'queued';
  if (countEl) countEl.textContent = `${completed}/${total}`;
  if (barEl) barEl.style.width = `${total ? (completed / total) * 100 : 0}%`;
  chip.classList.add('visible');
}
window.dfApplyRunState = dfApplyRunState;
window.dfClearRunState = dfClearRunState;

function dfInitPalette() {
  const palette = document.getElementById('df-palette');
  if (!palette || palette.dataset.initialized) return;
  palette.dataset.initialized = '1';
  palette.innerHTML = '';
  dfStepTemplates.forEach(tmpl => {
    // Persona → icon + tone. Falls back to AgentIcons.resolve on the
    // role/name if the template doesn't declare a persona explicitly.
    const persona = tmpl.persona ||
      (window.AgentIcons ? AgentIcons.resolve({ role: tmpl.role, name: tmpl.name }) : 'general');
    const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');

    const item = document.createElement('div');
    item.className = 'df-palette-item';
    item.draggable = true;
    item.dataset.persona = persona;
    item.innerHTML = `
      <span class="df-palette-icon tone-${esc(tone)}">${iconSvg}</span>
      <span class="df-palette-titleblock">
        <span class="df-palette-label">${esc(tmpl.name)}</span>
        <span class="df-palette-role">${esc(tmpl.role)}</span>
      </span>`;
    item.addEventListener('dragstart', (e) => { e.dataTransfer.setData('application/df-template', tmpl.key); e.dataTransfer.effectAllowed = 'move'; });
    palette.appendChild(item);
  });
}

function dfAddNodeFromTemplate(templateKey, x, y, opts) {
  opts = opts || {};
  const tmpl = dfStepTemplates.find(t => t.key === templateKey);
  if (!tmpl) return;
  const data = {
    id: templateKey + '_' + (++dfNextId),
    name: tmpl.name,
    role: tmpl.role,
    persona: tmpl.persona,
    system_prompt: tmpl.prompt,
    outputs: [...tmpl.outputs],
    output_format: tmpl.format,
    quality_gates: [],
    inputs: [],
    // Decision-node flag — controls extra config-panel UI (branch
    // labels) and is preserved through save/restore via dfNodeData.
    is_decision: !!tmpl.is_decision,
  };
  // Drawflow output-port count matches the template's declared branches
  // for decision nodes; everything else stays single-output.
  const numOut = Math.max(1, tmpl.num_outputs || 1);
  const nodeId = dfEditor.addNode(data.id, 1, numOut, x, y, data.id, {}, dfNodeHtml(data));
  dfNodeData[nodeId] = data;
  if (data.is_decision) {
    const wrap = document.getElementById('node-' + nodeId);
    if (wrap) wrap.classList.add('is-decision-node');
  }
  dfSelectedNodeId = nodeId;
  dfRenderConfigPanel(nodeId);
  // Native auto-wire: a freshly dropped piece chains onto the current tail
  // so the flow stays connected START→…→END. Suppressed during load (the
  // definition carries its own depends_on).
  if (opts.autoChain !== false) dfAutoChain(nodeId);
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();  // re-bracket begin/end
  return nodeId;
}

// Auto-connect a newly created step node onto the current chain tail (the
// most-recent terminal real step). The first node stays unchained — the
// START/END anchors bracket it. The connection is a real edge → persists as
// depends_on and the anchors re-bracket around it.
function dfAutoChain(newNodeId) {
  if (!dfEditor || newNodeId == null) return;
  newNodeId = Number(newNodeId);
  let home = {};
  try {
    const ex = dfEditor.export();
    home = (ex && ex.drawflow && ex.drawflow.Home && ex.drawflow.Home.data) || {};
  } catch (_) { return; }
  const realIds = Object.keys(dfNodeData).map(Number).filter(id => id !== newNodeId);
  if (!realIds.length) return;  // first node → anchors handle START→node→END
  // A node is a terminal if it has no outgoing connection to another REAL node.
  const hasRealDownstream = id => {
    const info = home[id];
    if (!info || !info.outputs) return false;
    return Object.values(info.outputs).some(out =>
      (out.connections || []).some(c => {
        const n = parseInt(c.node);
        return n !== newNodeId && dfNodeData[n];
      }));
  };
  const terminals = realIds.filter(id => !hasRealDownstream(id));
  const tail = (terminals.length ? terminals : realIds).reduce((a, b) => Math.max(a, b));
  try { dfEditor.addConnection(tail, newNodeId, 'output_1', 'input_1'); } catch (_) {}
}

function dfNodeHtml(data) {
  const color = dfRoleColors[data.role] || '#6b7780';
  const outputTags = (data.outputs || []).map(o => `<span class="df-node-output-tag${data.is_decision ? ' branch' : ''}">${esc(o)}</span>`).join('');
  const gateLabel = (data.quality_gates && data.quality_gates.length)
    ? `<span class="df-node-gate">[${data.quality_gates.length}G]</span>`
    : '';
  const decisionPill = data.is_decision
    ? '<span class="df-node-decision-pill">DECISION</span>'
    : '';
  // Persona resolution: explicit data.persona wins, then AgentIcons keyword
  // scan, then 'general'. Tone drives the icon-block tint so canvas nodes
  // match the palette glyph they were dragged from.
  const persona = data.persona ||
    (window.AgentIcons ? AgentIcons.resolve(data) : 'general');
  const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
  const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');
  // Capability chips — surface skills/tools/MCPs attached to this step
  // so the operator can read attachments at a glance without opening
  // the config panel. Each chip uses the matching capability icon and
  // tone so the visual language ties back to the workbench palette.
  const skillsList = data.skills || [];
  const toolsList  = (data.tools || []).map(t => typeof t === 'string' ? t : (t.id || ''));
  const _capChip = (capKey, label) => {
    const svg  = (window.AgentIcons ? AgentIcons.svg(capKey) : '');
    const tone = (window.AgentIcons ? AgentIcons.tone(capKey) : 'accent');
    return `<span class="df-node-cap tone-${esc(tone)}" data-cap="${esc(capKey)}" title="${esc(label)}">${svg}</span>`;
  };
  let capsHtml = '';
  if (skillsList.length || toolsList.length) {
    const parts = [];
    skillsList.slice(0, 3).forEach(s => parts.push(_capChip('skill', s)));
    toolsList.slice(0, 3).forEach(t => parts.push(_capChip(t.startsWith('mcp__') ? 'mcp' : 'tool', t)));
    const more = Math.max(0, (skillsList.length + toolsList.length) - parts.length);
    if (more > 0) parts.push(`<span class="df-node-cap more">+${more}</span>`);
    capsHtml = `<div class="df-node-caps">${parts.join('')}</div>`;
  }

  return `
    <div class="df-node-body${data.is_decision ? ' is-decision' : ''}" style="--role-color:${color}" data-persona="${esc(persona)}">
      <span class="df-node-icon tone-${esc(tone)}">${iconSvg}</span>
      <div class="df-node-meta">
        <div class="df-node-title">${esc(data.name)}${gateLabel}${decisionPill}</div>
        <div class="df-node-subline">
          <span class="df-node-role">${esc(data.role)}</span>
          <span class="df-node-fmt">${esc(data.output_format)}</span>
        </div>
        <div class="df-node-outputs">${outputTags}</div>
        ${capsHtml}
      </div>
    </div>`;
}

function dfRenderConfigPanel(nodeId) {
  const data = dfNodeData[nodeId];
  // Two target surfaces share one HTML body: the popup (primary, auto-
  // opens on node select) and the workstream tab (dock fallback).
  const panel = document.getElementById('df-config-panel');
  const popupBody = document.getElementById('df-config-popup-body');
  const popupTitle = document.getElementById('df-config-popup-title');
  const title = document.getElementById('df-config-title');
  if (!data || (!panel && !popupBody)) return;
  if (title) title.textContent = data.id;
  if (popupTitle) popupTitle.textContent = data.id;
  const gateOps = ['not_empty','contains','not_contains','matches','has_key','all_keys','gt','lt','gte','lte','equals','not_equals','length_gt','length_lt','is_type'];
  let gatesHtml = (data.quality_gates || []).map((gate, idx) => `
    <div class="df-gate-row">
      <input type="text" value="${esc(gate.field||'')}" class="chat-input" placeholder="field" data-action="df.gate-update" data-idx="${idx}" data-field="field" />
      <select class="model-select" data-action="df.gate-update" data-idx="${idx}" data-field="operator">${gateOps.map(op => `<option value="${op}"${gate.operator===op?' selected':''}>${op}</option>`).join('')}</select>
      <input type="text" value="${esc(gate.value||'')}" class="chat-input" placeholder="value" data-action="df.gate-update" data-idx="${idx}" data-field="value" />
      <button data-action="df.gate-remove" data-idx="${idx}" style="background:none;border:none;color:var(--red);cursor:pointer;padding:2px 4px">✕</button>
    </div>`).join('');
  const fmtOptions = Object.keys(dfFmtDescs).map(f => `<option value="${f}"${data.output_format===f?' selected':''}>${f}</option>`).join('');
  const html = `
    <div style="display:flex;flex-direction:column;gap:0" data-node-id="${nodeId}">
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Identity</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
          <div><label class="df-config-label">Step ID</label><input type="text" value="${esc(data.id)}" class="chat-input" style="font-size:0.68rem;padding:4px 8px"
            data-action="df.node-field" data-field="id" /></div>
          <div><label class="df-config-label">Name</label><input type="text" value="${esc(data.name)}" class="chat-input" style="font-size:0.68rem;padding:4px 8px"
            data-action="df.node-field" data-field="name" /></div>
        </div>
        <div style="margin-top:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px">
          <div><label class="df-config-label">Role</label>
            <select class="model-select" style="font-size:0.66rem;padding:3px 6px;width:100%" data-action="df.node-set" data-field="role">
              ${Object.keys(dfRoleColors).map(r=>`<option value="${r}"${data.role===r?' selected':''}>${r}</option>`).join('')}
            </select>
          </div>
          <div><label class="df-config-label">Model</label>
            <select class="model-select" style="font-size:0.66rem;padding:3px 6px;width:100%" data-action="df.node-set" data-field="model"
                    title="Pin a specific model. Leave on '(role-based)' to let the resolver pick the best match for the role.">
              <option value=""${!data.model?' selected':''}>(role-based)</option>
              ${(window._chatModels || []).map(m=>`<option value="${esc(m)}"${data.model===m?' selected':''}>${esc(m)}</option>`).join('')}
              ${data.model && !(window._chatModels||[]).includes(data.model) ? `<option value="${esc(data.model)}" selected>${esc(data.model)} (not loaded)</option>` : ''}
            </select>
          </div>
        </div>
        ${data._from_agent ? `<div style="margin-top:6px;font-size:0.56rem;color:var(--text-muted);letter-spacing:0.04em">forked from agent <code style="color:var(--accent)">${esc(data._from_agent)}</code></div>` : ''}
      </div>
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Prompt</div>
        <textarea class="chat-input" style="min-height:80px;font-size:0.66rem;resize:vertical"
          data-action="df.node-field" data-field="system_prompt">${esc(data.system_prompt)}</textarea>
      </div>
      ${data.is_decision ? `
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--purple);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Branches <span style="color:var(--text-muted);letter-spacing:0.06em">(routing labels)</span></div>
        <div style="display:flex;flex-direction:column;gap:4px">
          ${(data.outputs || []).map((label, i) => `
            <div style="display:flex;align-items:center;gap:6px">
              <span style="font-size:0.5rem;color:var(--text-muted);width:18px;text-align:right">${i + 1}</span>
              <input type="text" class="chat-input" style="font-size:0.66rem;padding:3px 8px;flex:1"
                value="${esc(label)}"
                data-action="df.branch" data-idx="${i}" />
            </div>`).join('')}
        </div>
        <div style="font-size:0.5rem;color:var(--text-muted);margin-top:6px;letter-spacing:0.04em">
          Rename the labels — the router's prompt should emit JSON like <code style="color:var(--purple)">{"branch":"&lt;label&gt;"}</code>. To change the number of branches, drop a fresh Decision node.
        </div>
      </div>` : ''}
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">${data.is_decision ? 'Output Format' : 'Outputs'}</div>
        <div id="df-outputs-${nodeId}" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">${data.outputs.map((o,i)=>`<span class="df-tag">${esc(o)}<button type="button" class="btn-unstyled df-tag-remove" aria-label="Remove output ${esc(o)}" data-action="df.output-remove" data-idx="${i}">✕</button></span>`).join('')}</div>
        <div style="display:flex;gap:4px"><input type="text" id="df-new-output-${nodeId}" class="chat-input" style="font-size:0.64rem;padding:3px 6px" placeholder="output_key" data-action="df.output-add" /><button class="action-btn" style="font-size:0.56rem;padding:2px 8px" data-action="df.output-add">Add</button></div>
        <div style="margin-top:6px"><label class="df-config-label">Output format</label><select class="model-select" style="font-size:0.64rem;padding:2px 4px" data-action="df.node-set" data-field="output_format">${fmtOptions}</select></div>
      </div>
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Tools &amp; Skills</div>
        <label class="df-config-label">Tools (plugin / MCP)</label>
        <div id="df-tools-${nodeId}" style="display:flex;flex-wrap:wrap;gap:4px;margin:2px 0 6px">${(data.tools||[]).map((t,i)=>`<span class="df-tag">${esc(typeof t==='string'?t:(t.mcp?('mcp:'+t.mcp):(t.plugin||t.tool_id||t.name||t.id||JSON.stringify(t))))}<span class="df-tag-remove" onclick="dfRemoveTool(${nodeId},${i})">✕</span></span>`).join('') || '<span style="font-size:0.56rem;color:var(--text-faint)">none</span>'}</div>
        <div style="display:flex;gap:4px;margin-bottom:8px"><input type="text" id="df-new-tool-${nodeId}" class="chat-input" style="font-size:0.64rem;padding:3px 6px" placeholder="plugin.tool or mcp:server.tool" onkeydown="if(event.key==='Enter'){dfAddTool(${nodeId});event.preventDefault()}" /><button class="action-btn" style="font-size:0.56rem;padding:2px 8px" onclick="dfAddTool(${nodeId})">Add</button></div>
        <label class="df-config-label">Skills</label>
        <div id="df-skills-${nodeId}" style="display:flex;flex-wrap:wrap;gap:4px;margin:2px 0 6px">${(data.skills||[]).map((s,i)=>`<span class="df-tag">${esc(typeof s==='string'?s:(s.id||s.name||JSON.stringify(s)))}<span class="df-tag-remove" onclick="dfRemoveSkill(${nodeId},${i})">✕</span></span>`).join('') || '<span style="font-size:0.56rem;color:var(--text-faint)">none</span>'}</div>
        <div style="display:flex;gap:4px"><input type="text" id="df-new-skill-${nodeId}" class="chat-input" style="font-size:0.64rem;padding:3px 6px" placeholder="skill-id" onkeydown="if(event.key==='Enter'){dfAddSkill(${nodeId});event.preventDefault()}" /><button class="action-btn" style="font-size:0.56rem;padding:2px 8px" onclick="dfAddSkill(${nodeId})">Add</button></div>
        <div id="df-companions-${nodeId}" style="margin-top:8px"></div>
      </div>
      <div style="padding:8px 0">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Quality Gates</div>
        <div id="df-gates-${nodeId}">${gatesHtml}</div>
        <button class="action-btn" style="font-size:0.56rem;padding:2px 8px;margin-top:4px" data-action="df.gate-add">+ Gate</button>
        <div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border)">
          <button class="action-btn" style="font-size:0.56rem;padding:2px 10px;color:var(--red);border-color:var(--red)" data-action="df.node-delete">Delete Node</button>
        </div>
      </div>
    </div>`;
  // Write the same body to both targets. Popup is the primary surface
  // (opens automatically on node-select); workstream tab is the dock
  // fallback for operators who prefer a stationary panel.
  if (panel)     panel.innerHTML     = html;
  if (popupBody) popupBody.innerHTML = html;
  // Auto-open the popup unless the operator has docked it.
  if (!window._stepConfigDocked) openStepConfigPopup();
  // Phase 4 — ask the archetype service what companion MCPs/skills this step
  // is missing, then render one-click "add" chips. Best-effort; the panel
  // stays usable if the call fails or the backend is older.
  dfFetchCompanions(nodeId);
}

// Phase 4 — composer↔capabilities: surface archetype companion suggestions.
async function dfFetchCompanions(nodeId) {
  const data = dfNodeData[nodeId];
  if (!data) return;
  const tools = (data.tools || []).map(t => (typeof t === 'string'
    ? (t.startsWith('mcp:') ? { mcp: t.slice(4).trim() } : { plugin: t.replace(/^plugin:/, '').trim() })
    : t));
  const stepPayload = { role: data.role, tools, skills: data.skills || [] };
  if (data.archetype) stepPayload.archetype = data.archetype;
  let res;
  try {
    const resp = await fetch('/api/workflows/composer/assist', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: stepPayload }),
    });
    if (!resp.ok) return;
    res = await resp.json();
  } catch (e) { return; }
  // The panel may have been re-rendered for another node since we fired.
  const boxes = [document.getElementById(`df-companions-${nodeId}`)].filter(Boolean);
  // Both the popup and the docked tab carry an element with this id; querySelectorAll
  // catches the second copy.
  document.querySelectorAll(`#df-companions-${nodeId}`).forEach(el => { if (!boxes.includes(el)) boxes.push(el); });
  if (!boxes.length) return;
  const mcps = (res.suggested_mcps || []);
  const skills = (res.suggested_skills || []);
  const arch = res.inferred_archetype;
  let html = '';
  if (arch) html += `<div style="font-size:0.54rem;color:var(--text-faint);margin-bottom:4px">archetype: <span style="color:var(--cyan)">${esc(arch)}</span></div>`;
  if (mcps.length || skills.length) {
    html += `<div style="font-size:0.56rem;color:var(--accent);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;font-weight:600">Suggested companions</div>`;
    html += `<div style="display:flex;flex-wrap:wrap;gap:4px">`;
    mcps.forEach(m => { const ref = (typeof m === 'string' ? m : (m.mcp || m.id || m.name || '')); if (ref) html += `<span class="df-tag" style="cursor:pointer;border-style:dashed" title="add MCP tool" onclick="dfAddCompanionTool(${nodeId},'mcp:${esc(ref)}')">+ ${esc(ref)}</span>`; });
    skills.forEach(s => { const ref = (typeof s === 'string' ? s : (s.id || s.name || '')); if (ref) html += `<span class="df-tag" style="cursor:pointer;border-style:dashed" title="add skill" onclick="dfAddCompanionSkill(${nodeId},'${esc(ref)}')">+ ${esc(ref)}</span>`; });
    html += `</div>`;
  }
  (res.warnings || []).forEach(w => { html += `<div style="font-size:0.54rem;color:var(--amber,#e0b341);margin-top:4px">⚠ ${esc(typeof w === 'string' ? w : JSON.stringify(w))}</div>`; });
  boxes.forEach(b => { b.innerHTML = html; });
}
function dfAddCompanionTool(nodeId, ref) {
  if (!dfNodeData[nodeId]) return;
  dfNodeData[nodeId].tools = dfNodeData[nodeId].tools || [];
  if (!dfNodeData[nodeId].tools.includes(ref)) dfNodeData[nodeId].tools.push(ref);
  dfUpdateNodeData(nodeId, 'tools', dfNodeData[nodeId].tools);
  dfRenderConfigPanel(nodeId);
}
function dfAddCompanionSkill(nodeId, ref) {
  if (!dfNodeData[nodeId]) return;
  dfNodeData[nodeId].skills = dfNodeData[nodeId].skills || [];
  if (!dfNodeData[nodeId].skills.includes(ref)) dfNodeData[nodeId].skills.push(ref);
  dfUpdateNodeData(nodeId, 'skills', dfNodeData[nodeId].skills);
  dfRenderConfigPanel(nodeId);
}

// ── Step Config popup controls ─────────────────────────────────────
function openStepConfigPopup() {
  const pop = document.getElementById('df-config-popup');
  if (!pop) return;
  pop.removeAttribute('hidden');
  // Re-validate position so the close X is always visible. Covers
  // the case where the viewport shrank while the popup was hidden.
  if (typeof window._clampPopupToViewport === 'function') {
    window._clampPopupToViewport();
  }
}
function closeStepConfigPopup() {
  const pop = document.getElementById('df-config-popup');
  if (!pop) return;
  pop.setAttribute('hidden', '');
}
function toggleStepConfigDock() {
  // Docked → the popup stays closed even on node-select; the operator
  // works from the workstream Step Config tab instead. Toggling back
  // restores the auto-open behaviour.
  window._stepConfigDocked = !window._stepConfigDocked;
  const btn = document.getElementById('df-config-popup-dock');
  if (btn) {
    btn.textContent = window._stepConfigDocked ? '⤴' : '⤓';
    btn.title = window._stepConfigDocked
      ? 'Undock: floating popup auto-opens on node select'
      : 'Dock to the bottom workstream tab instead of floating';
  }
  if (window._stepConfigDocked) closeStepConfigPopup();
}
window.openStepConfigPopup   = openStepConfigPopup;
window.closeStepConfigPopup  = closeStepConfigPopup;
window.toggleStepConfigDock  = toggleStepConfigDock;

// Drag-to-reposition. Persist position to localStorage so the popup
// stays where the operator left it across reloads.
(function bindStepConfigDrag() {
  let dragging = false;
  let startX = 0, startY = 0, baseLeft = 0, baseTop = 0;
  document.addEventListener('mousedown', (e) => {
    const head = e.target.closest('#df-config-popup-head');
    if (!head) return;
    if (e.target.closest('.df-config-popup-btn')) return; // skip close/dock clicks
    const pop = document.getElementById('df-config-popup');
    if (!pop) return;
    dragging = true;
    const r = pop.getBoundingClientRect();
    startX = e.clientX; startY = e.clientY;
    baseLeft = r.left; baseTop = r.top;
    pop.classList.add('is-dragging');
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const pop = document.getElementById('df-config-popup');
    if (!pop) return;
    const x = baseLeft + (e.clientX - startX);
    const y = baseTop  + (e.clientY - startY);
    // Constrain to viewport so the head stays grabable.
    const W = window.innerWidth, H = window.innerHeight;
    pop.style.left  = Math.max(8, Math.min(x, W - 80)) + 'px';
    pop.style.top   = Math.max(8, Math.min(y, H - 80)) + 'px';
    pop.style.right = 'auto';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    const pop = document.getElementById('df-config-popup');
    if (pop) {
      pop.classList.remove('is-dragging');
      try {
        localStorage.setItem('enclave.stepConfigPos', JSON.stringify({
          left: pop.style.left, top: pop.style.top,
        }));
      } catch (_) {}
    }
  });
  // Clamp the popup to the viewport. Saved position from a wider
  // window can leave the close-X off-screen — re-validate any time
  // the popup is opened or the window resizes.
  function _clampPopupToViewport() {
    const pop = document.getElementById('df-config-popup');
    if (!pop) return;
    const r = pop.getBoundingClientRect();
    // The popup is absolute inside the canvas panel — fall back to
    // the viewport when it's outside (e.g. canvas not visible yet).
    const W = window.innerWidth;
    const H = window.innerHeight;
    // Require at least the head's right edge (close + dock buttons)
    // to remain visible — those buttons are ~28px wide each at the
    // end of the head.
    const minVisibleRight = 100; // px of head visible on the left side
    const minLeft = 8;
    const maxLeft = Math.max(minLeft, W - minVisibleRight);
    const maxTop  = Math.max(8, H - 80);
    let leftPx = parseFloat(pop.style.left);
    let topPx  = parseFloat(pop.style.top);
    if (!isFinite(leftPx)) leftPx = r.left;
    if (!isFinite(topPx))  topPx  = r.top;
    if (leftPx < minLeft || leftPx > maxLeft || topPx < 8 || topPx > maxTop) {
      pop.style.left = Math.max(minLeft, Math.min(leftPx, maxLeft)) + 'px';
      pop.style.top  = Math.max(8, Math.min(topPx, maxTop)) + 'px';
      pop.style.right = 'auto';
    }
  }
  window._clampPopupToViewport = _clampPopupToViewport;

  // Restore last-saved position on first paint, then clamp it so a
  // position saved on a wider window can never put the close X
  // off-screen.
  try {
    const saved = localStorage.getItem('enclave.stepConfigPos');
    if (saved) {
      const pos = JSON.parse(saved);
      const pop = document.getElementById('df-config-popup');
      if (pop && pos.left) { pop.style.left = pos.left; pop.style.top = pos.top; pop.style.right = 'auto'; }
    }
  } catch (_) {}
  _clampPopupToViewport();
  window.addEventListener('resize', _clampPopupToViewport);
})();

// Escape key closes the popup (matches every other modal in the SPA).
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const pop = document.getElementById('df-config-popup');
  if (pop && !pop.hasAttribute('hidden')) closeStepConfigPopup();
});

// Debounce timers per node — the live-edit path fires on every
// keystroke for text fields, but we batch the canvas re-render to one
// frame and only re-render the config panel on the final commit
// (avoids stealing focus mid-typing for inputs that the panel re-renders).
const _dfUpdateTimers = {};
function dfUpdateNodeData(nodeId, field, value, opts) {
  if (!dfNodeData[nodeId]) return;
  opts = opts || {};
  dfNodeData[nodeId][field] = value;

  const apply = () => {
    if (!dfNodeData[nodeId]) return;
    const html = dfNodeHtml(dfNodeData[nodeId]);
    try { dfEditor.drawflow.drawflow.Home.data[nodeId].html = html; } catch (_) {}
    const nodeEl = document.querySelector(`#node-${nodeId} .drawflow_content_node`);
    if (nodeEl) nodeEl.innerHTML = html;
    // Pinned models from a node should surface in the chat picker —
    // any edit might have changed the model field. Safe no-op if the
    // function isn't ready yet.
    if (typeof syncCompositionModelsToChatPicker === 'function') {
      try { syncCompositionModelsToChatPicker(); } catch (_) {}
    }
    // Only re-render the config panel on the final commit, not on
    // every live-edit tick — re-rendering blows away the textarea
    // focus + caret position.
    if (opts.commit && dfSelectedNodeId === nodeId) dfRenderConfigPanel(nodeId);
  };

  if (opts.live) {
    clearTimeout(_dfUpdateTimers[nodeId]);
    _dfUpdateTimers[nodeId] = setTimeout(apply, 90);
  } else {
    clearTimeout(_dfUpdateTimers[nodeId]);
    apply();
  }
}

// Decision-node branch labels are just an `outputs` array, but we keep
// the array length pinned (drawflow can't resize ports without
// recreating the node). This helper updates label `i` in place and
// repaints both the canvas card and the config panel.
function dfUpdateDecisionBranch(nodeId, idx, label, opts) {
  if (!dfNodeData[nodeId] || !Array.isArray(dfNodeData[nodeId].outputs)) return;
  const trimmed = (label || '').trim() || `branch_${idx + 1}`;
  dfNodeData[nodeId].outputs[idx] = trimmed;
  dfUpdateNodeData(nodeId, 'outputs', dfNodeData[nodeId].outputs, opts);
}

function dfAddOutput(nodeId) {
  const inp = document.getElementById(`df-new-output-${nodeId}`);
  if (!inp || !inp.value.trim()) return;
  dfNodeData[nodeId].outputs.push(inp.value.trim());
  inp.value = '';
  dfUpdateNodeData(nodeId, 'outputs', dfNodeData[nodeId].outputs);
}

function dfRemoveOutput(nodeId, idx) {
  if (!dfNodeData[nodeId]) return;
  dfNodeData[nodeId].outputs.splice(idx, 1);
  dfUpdateNodeData(nodeId, 'outputs', dfNodeData[nodeId].outputs);
}

// Node tools/skills editing — expose + edit a step's capabilities on the canvas.
function dfAddTool(nodeId) {
  const inp = document.getElementById(`df-new-tool-${nodeId}`);
  if (!inp || !inp.value.trim() || !dfNodeData[nodeId]) return;
  dfNodeData[nodeId].tools = dfNodeData[nodeId].tools || [];
  dfNodeData[nodeId].tools.push(inp.value.trim());
  inp.value = '';
  dfUpdateNodeData(nodeId, 'tools', dfNodeData[nodeId].tools);
  dfRenderConfigPanel(nodeId);
}
function dfRemoveTool(nodeId, idx) {
  if (!dfNodeData[nodeId] || !dfNodeData[nodeId].tools) return;
  dfNodeData[nodeId].tools.splice(idx, 1);
  dfUpdateNodeData(nodeId, 'tools', dfNodeData[nodeId].tools);
  dfRenderConfigPanel(nodeId);
}
function dfAddSkill(nodeId) {
  const inp = document.getElementById(`df-new-skill-${nodeId}`);
  if (!inp || !inp.value.trim() || !dfNodeData[nodeId]) return;
  dfNodeData[nodeId].skills = dfNodeData[nodeId].skills || [];
  dfNodeData[nodeId].skills.push(inp.value.trim());
  inp.value = '';
  dfUpdateNodeData(nodeId, 'skills', dfNodeData[nodeId].skills);
  dfRenderConfigPanel(nodeId);
}
function dfRemoveSkill(nodeId, idx) {
  if (!dfNodeData[nodeId] || !dfNodeData[nodeId].skills) return;
  dfNodeData[nodeId].skills.splice(idx, 1);
  dfUpdateNodeData(nodeId, 'skills', dfNodeData[nodeId].skills);
  dfRenderConfigPanel(nodeId);
}

function dfAddGate(nodeId) {
  if (!dfNodeData[nodeId]) return;
  if (!dfNodeData[nodeId].quality_gates) dfNodeData[nodeId].quality_gates = [];
  dfNodeData[nodeId].quality_gates.push({ field: '', operator: 'not_empty', value: '' });
  dfRenderConfigPanel(nodeId);
}

function dfRemoveGate(nodeId, idx) {
  if (!dfNodeData[nodeId] || !dfNodeData[nodeId].quality_gates) return;
  dfNodeData[nodeId].quality_gates.splice(idx, 1);
  dfRenderConfigPanel(nodeId);
}

function dfUpdateGate(nodeId, idx, field, value) {
  if (!dfNodeData[nodeId] || !dfNodeData[nodeId].quality_gates) return;
  dfNodeData[nodeId].quality_gates[idx][field] = value;
}

function dfDeleteNode(nodeId) {
  if (!dfEditor) return;
  dfEditor.removeNodeId('node-' + nodeId);
}

// Delegated actions for the step-config dock/popup (dfRenderConfigPanel).
// The panel root carries data-node-id; per-control data-field/data-idx args.
// input → {live:true} (debounced repaint), change → {commit:true} (panel
// re-render); df.node-set selects pass no opts (immediate, no re-render),
// matching the original inline handlers exactly.
(function () {
  const nodeIdOf = el => {
    const root = el.closest('[data-node-id]');
    return root ? Number(root.dataset.nodeId) : NaN;
  };
  const fieldOpts = e => e.type === 'input' ? { live: true } : { commit: true };
  const nodeField = (el, e) => dfUpdateNodeData(nodeIdOf(el), el.dataset.field, el.value, fieldOpts(e));
  const branch    = (el, e) => dfUpdateDecisionBranch(nodeIdOf(el), Number(el.dataset.idx), el.value, fieldOpts(e));
  Actions.input({ 'df.node-field': nodeField, 'df.branch': branch });
  Actions.change({
    'df.node-field': nodeField,
    'df.branch': branch,
    'df.node-set':    el => dfUpdateNodeData(nodeIdOf(el), el.dataset.field, el.value),
    'df.gate-update': el => dfUpdateGate(nodeIdOf(el), Number(el.dataset.idx), el.dataset.field, el.value)
  });
  Actions.click({
    'df.gate-add':      el => dfAddGate(nodeIdOf(el)),
    'df.gate-remove':   el => dfRemoveGate(nodeIdOf(el), Number(el.dataset.idx)),
    'df.output-remove': el => dfRemoveOutput(nodeIdOf(el), Number(el.dataset.idx)),
    // The "output_key" text input shares this action for Enter-to-add;
    // ignore plain clicks on it (focusing the input must not add).
    'df.output-add':    el => { if (el.tagName !== 'INPUT') dfAddOutput(nodeIdOf(el)); }
  });
  Actions.on('keydown', {
    'df.output-add': (el, e) => {
      if (el.tagName !== 'INPUT' || e.key !== 'Enter') return;
      e.preventDefault();
      dfAddOutput(nodeIdOf(el));
    }
  });
  Actions.click({ 'df.node-delete': el => dfDeleteNode(nodeIdOf(el)) });
})();

function dfOnConnectionCreated(conn) {
  const fromId = parseInt(conn.output_id), toId = parseInt(conn.input_id);
  const from = dfNodeData[fromId], to = dfNodeData[toId];
  if (from && to) {
    from.outputs.forEach(out => { const ref = `${from.id}.${out}`; if (!to.inputs.includes(ref)) to.inputs.push(ref); });
    if (dfSelectedNodeId === toId) dfRenderConfigPanel(toId);
  }
}

function dfOnConnectionRemoved(conn) {
  const fromId = parseInt(conn.output_id), toId = parseInt(conn.input_id);
  const from = dfNodeData[fromId], to = dfNodeData[toId];
  if (from && to) {
    to.inputs = to.inputs.filter(ref => !ref.startsWith(from.id + '.'));
    if (dfSelectedNodeId === toId) dfRenderConfigPanel(toId);
  }
}

// Add START (seed) / END (deliverable) anchor nodes to the composer canvas,
// mirroring the runs DAG. NOT added to dfNodeData → dfExportYaml skips them.
function dfAddAnchors(steps, idMap, hasDeps, extraSeedKeys) {
  if (!dfEditor) return;
  steps = steps || [];
  idMap = idMap || {};
  const depOf = s => Array.isArray(s.depends_on) ? s.depends_on : (s.depends_on ? [s.depends_on] : []);
  // Seed keys = declared schema (extraSeedKeys, from the START editor) UNION
  // the keys actually referenced via seed.* in step inputs. So a declared-but-
  // not-yet-wired key still shows, and a wired-but-undeclared one isn't lost.
  const inferred = steps.flatMap(s =>
    (s.inputs || []).filter(i => typeof i === 'string' && i.startsWith('seed.')).map(i => i.slice(5)));
  const seedKeys = [...new Set([...(extraSeedKeys || []), ...inferred])];
  let rootSteps = [], terminalSteps = [];
  if (steps.length) {
    if (hasDeps) {
      const depended = new Set(steps.flatMap(depOf));
      rootSteps = steps.filter(s => depOf(s).length === 0);
      terminalSteps = steps.filter(s => !depended.has(s.id));
    } else {
      rootSteps = [steps[0]];
      terminalSteps = [steps[steps.length - 1]];
    }
  }
  const deliverable = [...new Set(terminalSteps.flatMap(s => Array.isArray(s.outputs) ? s.outputs : []))];
  const keyChips = arr => (arr.length ? arr : ['—']).map(k => `<span>${esc(k)}</span>`).join('');
  try {
    // START carries an inline edit affordance → opens the seed-schema editor.
    const startHtml = `<div class="wf-anchor wf-anchor-start">`
      + `<div class="wf-anchor-label">▶ START`
      + `<span class="wf-anchor-edit" title="Edit the workflow's seed inputs" onclick="event.stopPropagation();DfSeedSchema.open()">✎</span>`
      + `</div>`
      + `<div class="wf-anchor-sub">seed input</div>`
      + `<div class="wf-anchor-keys">${keyChips(seedKeys)}</div></div>`;
    const startId = dfEditor.addNode('__start__', 0, 1, 40, 200, '__start__', {}, startHtml);
    rootSteps.forEach(s => { const t = idMap[s && s.id]; if (t != null) { try { dfEditor.addConnection(startId, t, 'output_1', 'input_1'); } catch (_) {} } });
    const endHtml = `<div class="wf-anchor wf-anchor-end"><div class="wf-anchor-label">■ END</div><div class="wf-anchor-sub">deliverable</div><div class="wf-anchor-keys">${keyChips(deliverable.length ? deliverable : ['output'])}</div></div>`;
    const endId = dfEditor.addNode('__end__', 1, 0, 980, 200, '__end__', {}, endHtml);
    terminalSteps.forEach(s => { const src = idMap[s && s.id]; if (src != null) { try { dfEditor.addConnection(src, endId, 'output_1', 'input_1'); } catch (_) {} } });
  } catch (_) { /* anchors are best-effort decoration */ }
}

// Rebuild the START/END anchors from the CURRENT canvas state. Removes the old
// anchor nodes first, derives steps + deps from dfNodeData + connections, then
// redraws — so the begin/end boundary stays live while authoring (not just on
// load). Guarded by _dfAnchorBusy so the node/connection it adds don't recurse.
function dfRefreshAnchors() {
  if (!dfEditor) return;
  _dfAnchorBusy = true;
  try {
    const ex = dfEditor.export();
    const home = (ex && ex.drawflow && ex.drawflow.Home && ex.drawflow.Home.data) || {};
    // Drop existing anchors.
    Object.keys(home).forEach(id => {
      const n = home[id];
      if (n && (n.name === '__start__' || n.name === '__end__')) {
        try { dfEditor.removeNodeId('node-' + id); } catch (_) {}
      }
    });
    // Reconstruct steps + idMap from real (dfNodeData-backed) nodes.
    const steps = [], idMap = {};
    let hasDeps = false;
    Object.keys(dfNodeData).forEach(nid => {
      const d = dfNodeData[nid];
      if (!d) return;
      const info = home[nid];
      const deps = [];
      if (info && info.inputs) {
        Object.values(info.inputs).forEach(inp => (inp.connections || []).forEach(c => {
          const src = dfNodeData[parseInt(c.node)];
          if (src && !deps.includes(src.id)) deps.push(src.id);
        }));
      }
      if (deps.length) hasDeps = true;
      steps.push({ id: d.id, inputs: d.inputs || [], outputs: d.outputs || [], depends_on: deps });
      idMap[d.id] = parseInt(nid);
    });
    const declaredKeys = (dfSeedSchema || []).map(s => s && s.key).filter(Boolean);
    dfAddAnchors(steps, idMap, hasDeps, declaredKeys);
  } catch (_) { /* best-effort */ }
  _dfAnchorBusy = false;
}

// Debounced refresh — coalesces the burst of events a bulk load / multi-edit
// fires, and is a no-op while an anchor refresh is already in flight.
function dfScheduleAnchorRefresh() {
  if (_dfAnchorBusy) return;
  clearTimeout(_dfAnchorTimer);
  _dfAnchorTimer = setTimeout(() => { try { dfRefreshAnchors(); } catch (_) {} }, 150);
}

function dfExportYaml() {
  if (!dfEditor) return;
  const exported = dfEditor.export();
  const homeData = exported.drawflow.Home.data;
  const nodeIds = Object.keys(homeData).map(Number);
  const wfId   = document.getElementById('df-wf-id')?.value   || 'my-workflow';
  const wfName = document.getElementById('df-wf-name')?.value || 'My Workflow';
  const wfDesc = document.getElementById('df-wf-desc')?.value || '';
  const wfRole = document.getElementById('df-wf-role')?.value || 'general';

  let yaml = `id: ${wfId}\nname: "${wfName}"\nversion: "1.0"\n`;
  if (wfDesc) yaml += `description: "${wfDesc}"\n`;
  // Persist the START anchor's declared seed schema as context.inputs so the
  // input contract round-trips (read back in composerLoadById).
  if (Array.isArray(dfSeedSchema) && dfSeedSchema.length) {
    yaml += `\ncontext:\n  inputs:\n`;
    dfSeedSchema.forEach(s => {
      if (!s || !s.key) return;
      yaml += `    - key: ${s.key}\n`;
      if (s.description) yaml += `      description: "${String(s.description).replace(/"/g, '\\"')}"\n`;
    });
  }
  yaml += `\ndefaults:\n  role: ${wfRole}\n  temperature: 0.7\n  max_tokens: 4096\n  retries: 2\n  retry_delay: 5\n\nsteps:\n`;

  nodeIds.forEach(nid => {
    const data = dfNodeData[nid];
    if (!data) return;
    const nodeInfo = homeData[nid];
    const deps = [];
    if (nodeInfo.inputs) Object.values(nodeInfo.inputs).forEach(inp => (inp.connections||[]).forEach(conn => { const src = dfNodeData[parseInt(conn.node)]; if (src && !deps.includes(src.id)) deps.push(src.id); }));
    yaml += `  - id: ${data.id}\n    name: "${data.name}"\n    role: ${data.role}\n    system_prompt: |\n`;
    data.system_prompt.split('\n').forEach(line => { yaml += `      ${line}\n`; });
    if (data.inputs.length) { yaml += `    inputs:\n`; data.inputs.forEach(i => { yaml += `      - ${i}\n`; }); }
    yaml += `    outputs:\n`; data.outputs.forEach(o => { yaml += `      - ${o}\n`; });
    if (deps.length) { yaml += `    depends_on:\n`; deps.forEach(d => { yaml += `      - ${d}\n`; }); }
    if (data.tools && data.tools.length) {
      yaml += `    tools:\n`;
      data.tools.forEach(t => {
        if (t && typeof t === 'object') {
          if (t.mcp) yaml += `      - mcp: "${t.mcp}"\n`;
          else if (t.plugin) yaml += `      - plugin: "${t.plugin}"\n`;
          return;
        }
        const ref = String(t).trim();
        if (ref.startsWith('mcp:')) yaml += `      - mcp: "${ref.slice(4).trim()}"\n`;
        else yaml += `      - plugin: "${ref.replace(/^plugin:/, '').trim()}"\n`;
      });
    }
    if (data.skills && data.skills.length) {
      yaml += `    skills:\n`;
      data.skills.forEach(s => { yaml += `      - ${typeof s === 'string' ? s : (s.id || s.name || '')}\n`; });
    }
    if (data.output_format !== 'raw') yaml += `    output_parser:\n      format: ${data.output_format}\n`;
    if (data.quality_gates && data.quality_gates.length) {
      yaml += `    quality_gates:\n`;
      data.quality_gates.forEach(g => { yaml += `      - field: ${g.field}\n        operator: ${g.operator}\n`; if (g.value) yaml += `        value: "${g.value}"\n`; });
    }
    yaml += `\n`;
  });

  document.getElementById('df-yaml-panel').style.display = 'block';
  document.getElementById('df-yaml-output').textContent = yaml;
  return yaml;
}

async function dfSave() {
  const yamlText = dfExportYaml();
  if (!yamlText) return;
  let definition;
  try { definition = jsyaml.load(yamlText); } catch (e) { Toast.warn('YAML error', e.message); return; }
  const overwrite = true;
  try {
    const resp = await Net.call('/api/workflows/save', { retries: 0, init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ definition, overwrite }) } });
    if (resp.ok) {
      const result = resp.data;
      Toast.success('Saved', result.path);
      if (typeof refreshWorkflows === 'function') refreshWorkflows();
    } else {
      const err = (resp.data && typeof resp.data === 'object') ? resp.data : {};
      Toast.danger('Save failed', err.detail || JSON.stringify(err));
    }
  } catch (e) { Toast.danger('Save error', e.message); }
}

async function dfRunWorkflow() {
  const yamlText = dfExportYaml();
  if (!yamlText) return;
  let definition;
  try { definition = jsyaml.load(yamlText); } catch (e) { Toast.warn('YAML error', e.message); return; }
  try { await Net.postJson('/api/workflows/save', { definition, overwrite: true }, { retries: 0, silent: true }); } catch (e) { /* ignore save errors for run */ }
  setWfMode('run');
  const id = document.getElementById('df-wf-id')?.value || 'my-workflow';
  if (typeof refreshWorkflows === 'function') {
    await refreshWorkflows();
    const sel = document.getElementById('wf-select');
    if (sel) { sel.value = id; if (typeof loadWorkflowDetail === 'function') loadWorkflowDetail(); }
  }
}

function dfClearConfigPanel() {
  const panel = document.getElementById('df-config-panel');
  const title = document.getElementById('df-config-title');
  const popupBody = document.getElementById('df-config-popup-body');
  const popupTitle = document.getElementById('df-config-popup-title');
  const emptyHtml = '<div style="padding:30px 0;text-align:center;color:var(--text-muted);font-size:0.64rem">Drag a step from the palette to begin. Click a node to configure it.</div>';
  if (panel)      panel.innerHTML      = emptyHtml;
  if (popupBody)  popupBody.innerHTML  = emptyHtml;
  if (title)      title.textContent    = 'Config';
  if (popupTitle) popupTitle.textContent = 'Step Config';
  // Close the popup so it doesn't linger empty after a deselect.
  closeStepConfigPopup();
}

/* ── Canvas controls: zoom + fullscreen ─────────────────────────── */
// Drawflow ships native zoom_in/zoom_out/zoom_reset that already track
// the precanvas transform — we just expose them to the toolbar.
function dfZoomIn()    { if (window.dfEditor) dfEditor.zoom_in(); }
function dfZoomOut()   { if (window.dfEditor) dfEditor.zoom_out(); }
function dfZoomReset() { if (window.dfEditor) dfEditor.zoom_reset(); }

// Fullscreen toggles a class on the canvas PANEL (not the body) so the
// rest of the dashboard chrome stays mounted; Esc exits. Using a class
// instead of the Fullscreen API keeps the in-page chat input usable
// from within the maximized canvas (Fullscreen API would steal focus
// and inhibit text entry in some browsers).
function dfToggleFullscreen() {
  const panel = document.getElementById('composer-canvas-panel');
  const btn   = document.getElementById('canvas-fullscreen-btn');
  if (!panel) return;
  const entering = !panel.classList.contains('is-fullscreen');
  panel.classList.toggle('is-fullscreen', entering);
  if (btn) {
    btn.textContent = entering ? '⤓' : '⛶';
    btn.title = entering
      ? 'Exit fullscreen (Esc)'
      : 'Maximize the composer to fill the viewport (Esc to exit)';
  }
  // Force Drawflow to recompute its canvas size after the dimensions
  // change — its precanvas math is based on the panel rect.
  if (window.dfEditor) {
    try { dfEditor.zoom_reset(); } catch (e) {}
  }
}
// Bind Esc to exit fullscreen — one-time listener.
if (!window._dfFullscreenEscBound) {
  window._dfFullscreenEscBound = true;
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const panel = document.getElementById('composer-canvas-panel');
      if (panel && panel.classList.contains('is-fullscreen')) {
        dfToggleFullscreen();
      }
    }
  });
}

function dfAutoLayout() {
  if (!dfEditor || typeof dagre === 'undefined') return;
  const exported = dfEditor.export();
  const nodes = exported.drawflow.Home.data;
  const nodeIds = Object.keys(nodes);
  if (!nodeIds.length) return;

  // Approximate node size — wider than legacy because our new node body
  // has the icon block + metadata column.
  const NODE_W = 200;
  const NODE_H = 90;

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 90, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodeIds.forEach(id => g.setNode(id, { width: NODE_W, height: NODE_H }));
  nodeIds.forEach(id => {
    const node = nodes[id];
    // Walk every output port — decision/router nodes have multiple
    // outputs (output_1, output_2, …) and each may have connections.
    Object.keys(node.outputs || {}).forEach(outKey => {
      const conns = (node.outputs[outKey] || {}).connections || [];
      conns.forEach(conn => g.setEdge(id, String(conn.node)));
    });
  });
  dagre.layout(g);

  // Compute bounding box of the laid-out graph so we can translate
  // everything to center it inside the visible canvas viewport. dagre
  // emits coordinates relative to (0,0), so without this the structure
  // hugs the top-left corner regardless of canvas size.
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  nodeIds.forEach(id => {
    const pos = g.node(id);
    if (!pos) return;
    minX = Math.min(minX, pos.x - NODE_W / 2);
    minY = Math.min(minY, pos.y - NODE_H / 2);
    maxX = Math.max(maxX, pos.x + NODE_W / 2);
    maxY = Math.max(maxY, pos.y + NODE_H / 2);
  });
  const bboxW = (maxX - minX) || NODE_W;
  const bboxH = (maxY - minY) || NODE_H;

  // Canvas viewport — measured from the drawflow container element.
  // Account for the current zoom factor so centering still lands
  // correctly when the user has zoomed in/out before clicking auto-layout.
  const canvas = document.getElementById('drawflow-canvas');
  const rect = canvas ? canvas.getBoundingClientRect() : { width: 1200, height: 700 };
  const zoom = (dfEditor && typeof dfEditor.zoom === 'number') ? dfEditor.zoom : 1;
  const viewW = rect.width  / zoom;
  const viewH = rect.height / zoom;

  // Reset zoom first so the framing is predictable across runs. This
  // also prevents the "structure ends up in the top-right" symptom —
  // a leftover zoom transform from a previous session was offsetting
  // the precanvas while we wrote absolute pixel positions.
  try { dfEditor.zoom_reset(); } catch (_) {}

  // Offset to translate (minX, minY) → top-left of the centered region.
  const offsetX = Math.max(40, (viewW - bboxW) / 2 - minX);
  const offsetY = Math.max(40, (viewH - bboxH) / 2 - minY);

  nodeIds.forEach(id => {
    const pos = g.node(id);
    if (!pos) return;
    const left = pos.x - NODE_W / 2 + offsetX;
    const top  = pos.y - NODE_H / 2 + offsetY;
    nodes[id].pos_x = left;
    nodes[id].pos_y = top;
    // Mirror into drawflow's internal model so save/export reflect it.
    try {
      const d = dfEditor.drawflow.drawflow.Home.data[id];
      if (d) { d.pos_x = left; d.pos_y = top; }
    } catch (_) {}
    const el = document.querySelector(`#node-${id}`);
    if (el) { el.style.left = left + 'px'; el.style.top = top + 'px'; }
  });
  nodeIds.forEach(id => { try { dfEditor.updateConnectionNodes(`node-${id}`); } catch(e) {} });
}

function dfImportYaml() {
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
  modal.innerHTML = `<div style="background:var(--bg);border:1px solid var(--border);padding:20px;width:600px;max-height:80vh;display:flex;flex-direction:column;gap:10px"><div style="font-size:0.8rem;color:var(--text);font-weight:600">Import Workflow YAML</div><div style="font-size:0.6rem;color:var(--text-dim)">Paste a workflow YAML definition. All current nodes will be replaced.</div><textarea id="df-import-textarea" style="width:100%;min-height:300px;background:var(--bg-deep);color:var(--text);border:1px solid var(--border);font-family:var(--mono);font-size:0.65rem;padding:10px;resize:vertical"></textarea><div style="display:flex;gap:8px;justify-content:flex-end"><button class="action-btn" data-action="df.import-cancel">Cancel</button><button class="action-btn" data-action="df.import-run" style="color:var(--cyan);border-color:var(--cyan-dim)">Import</button></div></div>`;
  document.body.appendChild(modal);
}

// Delegated actions for the YAML import modal (dfImportYaml).
Actions.click({
  'df.import-cancel': el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); },
  'df.import-run':    () => dfDoImport()
});

function dfDoImport() {
  const textarea = document.getElementById('df-import-textarea');
  if (!textarea) return;
  const yamlText = textarea.value;
  textarea.closest('div[style*=fixed]').remove();
  if (!yamlText.trim()) return;

  let parsed;
  try { parsed = jsyaml.load(yamlText); } catch (e) { Toast.warn('Invalid YAML', e.message); return; }
  if (!parsed || !parsed.steps || !Array.isArray(parsed.steps)) { Toast.warn('YAML must have a "steps" array'); return; }

  dfEditor.clear();
  dfNodeData = {};
  if (parsed.id)   document.getElementById('df-wf-id').value   = parsed.id;
  if (parsed.name) document.getElementById('df-wf-name').value  = parsed.name;
  if (parsed.description) {
    const descEl = document.getElementById('df-wf-desc');
    descEl.value = typeof parsed.description === 'string' ? parsed.description.trim() : '';
    // Fire the inline oninput handler so the textarea auto-sizes to
    // fit the imported description (handler bumps height up to 156px).
    descEl.dispatchEvent(new Event('input'));
  }
  if (parsed.defaults && parsed.defaults.role) document.getElementById('df-wf-role').value = parsed.defaults.role;

  if (typeof dagre === 'undefined') {
    parsed.steps.forEach((step, i) => { dfAddNodeFromImportedStep(step, 80 + i * 200, 80); });
    return;
  }

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  const stepIds = new Set(parsed.steps.map(s => s.id));
  parsed.steps.forEach(step => g.setNode(step.id, { width: 170, height: 70 }));
  parsed.steps.forEach(step => {
    const deps = new Set();
    if (step.depends_on) step.depends_on.forEach(d => deps.add(d));
    if (step.inputs) step.inputs.forEach(inp => { const ns = inp.split('.')[0]; if (ns !== 'seed' && ns !== 'shared' && stepIds.has(ns)) deps.add(ns); });
    deps.forEach(dep => { if (stepIds.has(dep)) g.setEdge(dep, step.id); });
  });
  dagre.layout(g);

  const stepToNodeId = {};
  parsed.steps.forEach(step => {
    const pos = g.node(step.id);
    const x = pos ? pos.x - 85 : 100, y = pos ? pos.y - 35 : 80;
    const nodeId = dfAddNodeFromImportedStep(step, x, y);
    stepToNodeId[step.id] = nodeId;
  });

  parsed.steps.forEach(step => {
    if (!step.depends_on) return;
    step.depends_on.forEach(dep => {
      const fromId = stepToNodeId[dep], toId = stepToNodeId[step.id];
      if (fromId && toId) try { dfEditor.addConnection(fromId, toId, 'output_1', 'input_1'); } catch(e) {}
    });
  });
}

function dfAddNodeFromImportedStep(step, x, y) {
  const tmpl = dfStepTemplates.find(t => t.key === (step.role || 'custom')) || dfStepTemplates[dfStepTemplates.length - 1];
  const data = {
    id: step.id || (tmpl.key + '_' + (++dfNextId)),
    name: step.name || step.id || tmpl.name,
    role: step.role || 'general',
    system_prompt: (step.system_prompt || tmpl.prompt || '').trim(),
    outputs: step.outputs || [...tmpl.outputs],
    output_format: (step.output_parser && step.output_parser.format) || tmpl.format,
    quality_gates: step.quality_gates || [],
    inputs: step.inputs || [],
  };
  const nodeId = dfEditor.addNode(data.id, 1, 1, x, y, data.id, {}, dfNodeHtml(data));
  dfNodeData[nodeId] = data;
  return nodeId;
}

/* ── AGENTS TAB ─────────────────────────────────────────────────── */
let _activeAgentId = null;
let _agentHistory = [];

// ── Chat persistence ────────────────────────────────────────────────
// User feedback (post-#71): "change tabs and the chat has been cleared
// without intentionally clearing it." The chat panel DOM technically
// survived tab switches, but (a) page reloads wiped _agentHistory, and
// (b) when the agents grid re-rendered above the chat panel, the
// active conversation slid below the fold and felt "lost." Persist
// the conversation to localStorage and restore it on every
// loadAgentsTab so navigating tabs (or reloading) leaves the
// conversation exactly where the operator left it.
const _CHAT_LS_KEY = 'enclave.agentChat.v1';

function _persistAgentChat() {
  try {
    if (!_activeAgentId) {
      localStorage.removeItem(_CHAT_LS_KEY);
      return;
    }
    const headerName = document.getElementById('agent-chat-name')?.textContent || '';
    const headerModel = document.getElementById('agent-chat-model')?.textContent || '';
    localStorage.setItem(_CHAT_LS_KEY, JSON.stringify({
      activeAgentId: _activeAgentId,
      history: _agentHistory,
      headerName,
      headerModel,
      savedAt: Date.now(),
    }));
  } catch (_) { /* quota / private-mode — non-fatal */ }
}

function _restoreAgentChat() {
  try {
    const raw = localStorage.getItem(_CHAT_LS_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    if (!parsed.activeAgentId || !Array.isArray(parsed.history)) return false;
    _activeAgentId = parsed.activeAgentId;
    _agentHistory = parsed.history;
    // Rebuild the chat panel UI without re-fetching the agent. The
    // header model/name we cached at last persist is good enough; if
    // the agent has been edited since, openAgentChat will refresh on
    // next click.
    const nameEl = document.getElementById('agent-chat-name');
    const modelEl = document.getElementById('agent-chat-model');
    const panel = document.getElementById('agent-chat-panel');
    const msgEl = document.getElementById('agent-chat-messages');
    if (!nameEl || !modelEl || !panel || !msgEl) return false;
    nameEl.textContent = parsed.headerName || _activeAgentId;
    modelEl.textContent = parsed.headerModel || '';
    panel.style.display = 'block';
    // Rebuild the bubbles. Use createElement + textContent to keep
    // the security_reminder_hook happy on hardcoded restored content.
    msgEl.replaceChildren();
    for (const m of _agentHistory) {
      const bubble = document.createElement('div');
      if (m.role === 'user') {
        bubble.style.cssText =
          'align-self:flex-end;background:var(--bg-panel);border:1px solid var(--border);'
          + 'border-radius:6px;padding:7px 11px;max-width:80%;font-size:0.82rem;white-space:pre-wrap;';
      } else {
        bubble.style.cssText =
          'align-self:flex-start;background:var(--bg-deep);border:1px solid var(--border);'
          + 'border-radius:6px;padding:7px 11px;max-width:85%;font-size:0.82rem;white-space:pre-wrap;';
      }
      bubble.textContent = m.content || '';
      msgEl.appendChild(bubble);
    }
    msgEl.scrollTop = msgEl.scrollHeight;
    return true;
  } catch (_) { return false; }
}

// Insert a small "↓ Active chat with X" badge at the top of the agents
// list when a chat is already running, so the operator sees it
// immediately on tab return and can jump straight to it.
function _renderActiveChatPill() {
  const list = document.getElementById('agents-list');
  if (!list) return;
  // Drop any prior pill first.
  list.querySelector('.agent-active-chat-pill')?.remove();
  if (!_activeAgentId) return;
  const name = document.getElementById('agent-chat-name')?.textContent || _activeAgentId;
  const pill = document.createElement('button');
  pill.className = 'agent-active-chat-pill';
  pill.type = 'button';
  pill.style.cssText =
    'grid-column:1/-1;display:flex;gap:8px;align-items:center;justify-content:flex-start;'
    + 'padding:7px 12px;background:rgba(87, 196, 210,0.06);border:1px solid var(--cyan-dim);'
    + 'border-radius:6px;color:var(--text);font-size:0.75rem;cursor:pointer;font-family:var(--mono);';
  const arrow = document.createElement('span');
  arrow.style.cssText = 'color:var(--cyan);';
  arrow.textContent = '↓';
  const label = document.createElement('span');
  label.append('Active chat with ',
    Object.assign(document.createElement('strong'), {textContent: name, style: 'color:var(--cyan)'}),
    ' — click to jump');
  pill.append(arrow, label);
  pill.addEventListener('click', () => {
    document.getElementById('agent-chat-panel')?.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
  list.prepend(pill);
}

async function loadAgentsTab() {
  // Try to restore a persisted chat BEFORE rendering the agents grid
  // so the active-chat pill can show up at the top of the list.
  _restoreAgentChat();

  const listEl = document.getElementById('agents-list');
  const emptyEl = document.getElementById('agents-empty');
  listEl.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">Loading…</div>';
  emptyEl.style.display = 'none';

  let agents = [];
  try {
    agents = await Net.getJson('/api/agents');
  } catch (e) {
    listEl.innerHTML = '<div style="color:var(--red,#f44);font-size:0.8rem;padding:8px;">Failed to load agents.</div>';
    return;
  }

  const countEl = document.getElementById('agents-count');
  if (countEl) countEl.textContent = agents.length || '';

  if (!agents.length) {
    listEl.innerHTML = '';
    emptyEl.style.display = 'block';
    return;
  }
  emptyEl.style.display = 'none';

  listEl.innerHTML = agents.map(a => {
    const persona  = (window.AgentIcons ? AgentIcons.resolve(a) : 'general');
    const iconSvg  = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const tone     = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');
    const subtitle = (a.description || '').split('\n')[0].trim().slice(0, 90);
    return `
    <div class="agent-tile" role="button" tabindex="0" aria-label="Open chat with ${esc(a.name)}" data-action="agents.chat" data-agent-id="${esc(a.id)}">
      <div class="agent-tile-head">
        <span class="agent-tile-icon tone-${esc(tone)}" data-persona="${esc(persona)}">${iconSvg}</span>
        <div class="agent-tile-titleblock">
          <div class="agent-tile-title">${esc(a.name)}</div>
          <div class="agent-tile-subtitle">${esc(subtitle || (a.role ? 'Role · ' + a.role : ''))}</div>
        </div>
        <div class="agent-tile-actions">
          <button onclick="event.stopPropagation();AssetPeek.open('agent','${esc(a.id)}')"
                  class="agent-tile-action" title="Deep dive — binding, starters, persona">⌕</button>
          <button data-action="agents.edit"
                  class="agent-tile-action" title="Edit agent">✎</button>
          <button data-action="agents.delete"
                  class="agent-tile-action" title="Delete agent">✕</button>
        </div>
      </div>
      <div class="agent-tile-meta">
        ${(a.tags||[]).map(t=>`<span class="agent-tile-tag">${esc(t)}</span>`).join('')}
        ${a.role ? `<span class="agent-tile-tag tag-role">${esc(a.role)}</span>` : ''}
        ${a.model ? `<span class="agent-tile-tag tag-model">${esc(a.model)}</span>` : ''}
      </div>
      ${a.starters && a.starters.length ? `
        <div class="agent-tile-starters">
          ${a.starters.slice(0,2).map(s=>`
            <button data-action="agents.starter" data-starter="${esc(s)}"
                    class="agent-tile-starter">
              <span class="starter-arrow">↗</span> ${esc(s)}
            </button>`).join('')}
        </div>` : ''}
    </div>`;
  }).join('');
  // After the grid renders, surface the "active chat" jump pill so a
  // restored conversation is visually obvious at the top of the page.
  _renderActiveChatPill();
}

async function openAgentChat(agentId) {
  _activeAgentId = agentId;
  _agentHistory = [];
  _persistAgentChat();
  let agent;
  try {
    agent = await Net.getJson(`/api/agents/${agentId}`);
  } catch(e) {
    Toast.danger('Failed to load agent', agentId);
    return;
  }
  // Render the SVG persona glyph in the chat header (tone-tinted block).
  const chatIcon = document.getElementById('agent-chat-icon');
  if (chatIcon) {
    const persona = (window.AgentIcons ? AgentIcons.resolve(agent) : 'general');
    const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'accent');
    chatIcon.className = `agent-chat-icon-block tone-${tone}`;
    chatIcon.innerHTML = (window.AgentIcons ? AgentIcons.svg(persona) : '');
  }
  document.getElementById('agent-chat-name').textContent = agent.name;
  document.getElementById('agent-chat-model').textContent = agent.role ? `role:${agent.role}` : (agent.model || '');
  document.getElementById('agent-chat-messages').innerHTML = `
    <div style="font-size:0.75rem;color:var(--text-muted);text-align:center;">
      Chat with <strong style="color:var(--cyan)">${esc(agent.name)}</strong> — type a message below
    </div>`;
  document.getElementById('agent-chat-panel').style.display = 'block';
  document.getElementById('agent-chat-input').focus();
}

function openAgentChatWithStarter(agentId, starter) {
  openAgentChat(agentId).then(() => {
    document.getElementById('agent-chat-input').value = starter;
    sendAgentMessage();
  });
}

// Delegated actions shared by BOTH agent-grid render paths (the Agents tab
// grid and the CatalogPage preview copy). The tile carries data-agent-id;
// inner edit/delete/starter buttons resolve it via closest(). Innermost
// data-action wins in the dispatcher, so the inner buttons no longer need
// the stopPropagation guards (the tile's agents.chat never fires for them).
(function () {
  const agentIdOf = el => {
    const tile = el.closest('[data-agent-id]');
    return tile ? tile.dataset.agentId : '';
  };
  Actions.click({
    'agents.chat':    el => openAgentChat(agentIdOf(el)),
    'agents.edit':    el => showEditAgentModal(agentIdOf(el)),
    'agents.delete':  el => deleteAgent(agentIdOf(el)),
    'agents.starter': el => openAgentChatWithStarter(agentIdOf(el), el.dataset.starter)
  });
  // Tile is a role=button div — keep Enter/Space operability.
  Actions.on('keydown', {
    'agents.chat': (el, e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      openAgentChat(agentIdOf(el));
    }
  });
})();

function closeAgentChat() {
  _activeAgentId = null;
  _agentHistory = [];
  _persistAgentChat();  // clears the localStorage slot
  document.getElementById('agent-chat-panel').style.display = 'none';
  // Drop the "active chat" jump pill from the agents grid.
  document.querySelector('.agent-active-chat-pill')?.remove();
}

async function sendAgentMessage() {
  // If a composer step is engaged, chat in THAT step's context (its system
  // prompt + model) rather than only the selected agent persona — so you can
  // iterate on the actual workflow step / its adopted agent context.
  const _engId = window._composerEngagedNodeId;
  const _engStep = (_engId != null && typeof dfNodeData !== 'undefined' && dfNodeData[_engId])
    ? dfNodeData[_engId] : null;
  if (!_activeAgentId && !_engStep) return;
  const input = document.getElementById('agent-chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  _agentHistory.push({ role: 'user', content: text });
  // Persist the user's message immediately — if the agent times out
  // (Ollama's 300s read timeout on slow CPU prefill) the operator's
  // typed message still survives navigation/reload.
  _persistAgentChat();

  const msgEl = document.getElementById('agent-chat-messages');
  const userBubble = `<div style="align-self:flex-end;background:var(--bg-panel);border:1px solid var(--border);border-radius:6px;padding:7px 11px;max-width:80%;font-size:0.82rem;white-space:pre-wrap;">${esc(text)}</div>`;
  const thinkingBubble = `<div id="agent-thinking" style="align-self:flex-start;color:var(--text-muted);font-size:0.78rem;padding:4px 8px;">thinking…</div>`;
  msgEl.insertAdjacentHTML('beforeend', userBubble + thinkingBubble);
  msgEl.scrollTop = msgEl.scrollHeight;

  let result;
  try {
    if (_engStep) {
      // Step context: run the step's system prompt + model directly via the
      // OpenAI-compatible endpoint, so the chat reflects exactly what this
      // workflow step would run with.
      const sys = _engStep.system_prompt || '';
      // step model → current dropdown choice (if a real model id, not the
      // "no models, pull one" placeholder) → safe default.
      const selVal = (document.getElementById('model-select') || {}).value || '';
      const validSel = selVal && !/\s/.test(selVal) ? selVal : '';
      const model = _engStep.model || validSel || 'qwen2.5:7b';
      const messages = sys
        ? [{ role: 'system', content: sys }, ..._agentHistory]
        : _agentHistory.slice();
      // retries:0 — LLM inference must never silently double-execute.
      const r = await Net.call('/v1/chat/completions', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model, messages, max_tokens: 2048, temperature: 0.7 }),
        },
      });
      const d = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) throw new Error((d.error && d.error.message) || d.detail || 'Chat failed');
      result = { content: (d.choices && d.choices[0] && d.choices[0].message.content) || '', model };
    } else {
      // retries:0 — agent chat is an LLM call; Net.call (not postJson) so the
      // error body's detail still reaches the inline bubble.
      const r = await Net.call(`/api/agents/${_activeAgentId}/chat`, {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: _agentHistory }),
        },
      });
      result = (r.data && typeof r.data === 'object') ? r.data : {};
      if (!r.ok) throw new Error(result.detail || 'Chat failed');
    }
  } catch(e) {
    document.getElementById('agent-thinking')?.remove();
    msgEl.insertAdjacentHTML('beforeend',
      `<div style="align-self:flex-start;color:var(--red,#f44);font-size:0.78rem;padding:4px 8px;">${esc(String(e))}</div>`);
    msgEl.scrollTop = msgEl.scrollHeight;
    return;
  }

  document.getElementById('agent-thinking')?.remove();
  const content = result.content || '';
  _agentHistory.push({ role: 'assistant', content });

  // Show fallback banner when the agent's pinned model wasn't available.
  if (result.model_fallback) {
    const fb = result.model_fallback;
    const pullHint = fb.requested
      ? ` <button type="button" class="btn-unstyled" style="opacity:.7;text-decoration:underline" title="Copy pull command" data-action="agents.copy-pull" data-cmd="ollama pull ${esc(fb.requested)}">ollama pull ${esc(fb.requested)}</button>`
      : '';
    msgEl.insertAdjacentHTML('beforeend',
      `<div style="align-self:stretch;background:rgba(255,200,0,.07);border:1px solid rgba(255,200,0,.35);border-radius:4px;padding:5px 9px;font-size:0.7rem;color:var(--text-muted);display:flex;gap:6px;align-items:center;">` +
      `<span style="color:#fc0;font-size:0.9rem;">⚠</span>` +
      `<span>Pinned model <strong>${esc(fb.requested || '?')}</strong> not installed — running on <strong>${esc(fb.resolved || result.model || '?')}</strong>.${pullHint}</span>` +
      `</div>`);
  }

  msgEl.insertAdjacentHTML('beforeend',
    `<div style="align-self:flex-start;background:var(--bg-deep);border:1px solid var(--border);border-radius:6px;padding:7px 11px;max-width:85%;font-size:0.82rem;white-space:pre-wrap;">${esc(content)}</div>`);
  msgEl.scrollTop = msgEl.scrollHeight;
  // Persist the conversation now that we have a complete turn. The
  // localStorage write survives tab switches AND page reloads, so the
  // operator's chat history is durable across the whole session.
  _persistAgentChat();
}

async function deleteAgent(agentId) {
  const ok = await Confirm.ask({ title: 'Delete agent', body: `Delete agent "${agentId}"?`, okLabel: 'Delete', danger: true });
  if (!ok) return;
  try {
    const r = await Net.call(`/api/agents/${agentId}`, { retries: 0, init: { method: 'DELETE' } });
    if (!r.ok) throw new Error((r.data && r.data.detail) || 'Delete failed');
    loadAgentsTab();
    if (_activeAgentId === agentId) closeAgentChat();
  } catch(e) {
    Toast.danger('Failed to delete agent', e.message);
  }
}

/* ── Agent Create / Edit Modal ──────────────────────────────────────── */

function _agentModalHtml(mode, a) {
  const isEdit = mode === 'edit';
  const inputStyle = 'width:100%;background:var(--bg-deep);border:1px solid var(--border);color:var(--text);padding:6px 9px;border-radius:4px;font-family:var(--mono);font-size:0.78rem;box-sizing:border-box;';
  const labelStyle = 'font-size:0.7rem;color:var(--text-muted);margin-bottom:3px;display:block;';
  const roleOpts = ['','general','coding','reasoning','fast','uncensored']
    .map(r => `<option value="${r}" ${(a&&a.role===r)||(!a&&r==='')?'selected':''}>${r||'— none —'}</option>`)
    .join('');
  const startersVal = a && a.starters && a.starters.length ? a.starters.join('\n') : '';
  const tempVal = a && a.temperature !== undefined ? a.temperature : 0.7;
  const modelVal = a && a.model ? esc(a.model) : '';
  const contextJson = JSON.stringify(a && a.context ? a.context : []);
  const toolsJson   = JSON.stringify(a && a.tools   ? a.tools   : []);
  return `
  <div style="font-size:0.82rem;color:var(--text);font-weight:600;margin-bottom:2px;">${isEdit ? 'Edit Agent' : 'New Agent'}</div>
  <div style="font-size:0.68rem;color:var(--text-dim);margin-bottom:12px;">${isEdit ? `Editing <strong style="color:var(--cyan)">${esc(a.id)}</strong>` : 'Define a custom AI persona'}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
    <div>
      <label style="${labelStyle}">ID (slug) *</label>
      <input id="am-id" type="text" placeholder="my-assistant" value="${a?esc(a.id):''}" ${isEdit?'disabled':''} style="${inputStyle}${isEdit?'opacity:0.5;cursor:not-allowed;':''}">
    </div>
    <div>
      <label style="${labelStyle}">Display name *</label>
      <input id="am-name" type="text" placeholder="My Assistant" value="${a?esc(a.name):''}" style="${inputStyle}">
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 60px;gap:10px;margin-top:8px;">
    <div>
      <label style="${labelStyle}">Description</label>
      <input id="am-desc" type="text" placeholder="What this agent does…" value="${a&&a.description?esc(a.description):''}" style="${inputStyle}">
    </div>
    <div>
      <label style="${labelStyle}">Icon</label>
      <input id="am-icon" type="text" placeholder="🤖" value="${a&&a.icon?esc(a.icon):''}" style="${inputStyle}text-align:center;">
    </div>
  </div>
  <div style="margin-top:8px;">
    <label style="${labelStyle}">System prompt *</label>
    <textarea id="am-prompt" rows="5" placeholder="You are a helpful assistant…" style="${inputStyle}resize:vertical;">${a?esc(a.system_prompt):''}</textarea>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;">
    <div>
      <label style="${labelStyle}">Role</label>
      <select id="am-role" style="${inputStyle}">${roleOpts}</select>
    </div>
    <div>
      <label style="${labelStyle}">Tags (comma-separated)</label>
      <input id="am-tags" type="text" placeholder="coding, review" value="${a&&a.tags?esc(a.tags.join(', ')):''}" style="${inputStyle}">
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 90px 90px;gap:10px;margin-top:8px;">
    <div>
      <label style="${labelStyle}">Model override <span style="color:var(--text-dim)">(leave blank to use role)</span></label>
      <input id="am-model" type="text" placeholder="llama3.2 or leave blank" value="${modelVal}" style="${inputStyle}">
    </div>
    <div>
      <label style="${labelStyle}">Temperature</label>
      <input id="am-temp" type="number" min="0" max="2" step="0.05" value="${tempVal}" style="${inputStyle}text-align:center;">
    </div>
    <div>
      <label style="${labelStyle}">Max tokens</label>
      <input id="am-max-tokens" type="number" min="256" max="32768" step="256" value="${a && a.max_tokens ? a.max_tokens : 4096}" style="${inputStyle}text-align:center;">
    </div>
  </div>
  <div style="margin-top:8px;">
    <label style="${labelStyle}">Conversation starters <span style="color:var(--text-dim)">(one per line, shown as quick-start chips)</span></label>
    <textarea id="am-starters" rows="3" placeholder="Review this function for bugs&#10;What's the time complexity here?" style="${inputStyle}resize:vertical;">${esc(startersVal)}</textarea>
  </div>
  <div style="margin-top:10px;">
    <label style="${labelStyle}">Tools &amp; Capabilities <span style="color:var(--text-dim)">(what this agent may invoke — built-ins, plugin tools, MCP)</span></label>
    <div id="am-tools-picker" class="am-tools-picker"><div style="color:var(--text-muted);font-size:0.7rem">Loading capabilities…</div></div>
  </div>
  <div style="margin-top:10px;">
    <label style="${labelStyle}">Context &amp; Grounding <span style="color:var(--text-dim)">(data injected into every turn)</span></label>
    <div id="am-context-picker" class="am-context-picker"></div>
    <div class="am-ctx-add">
      <select id="am-ctx-type" class="model-select" style="width:auto;min-width:120px">
        <option value="text">Text snippet</option>
        <option value="file">File / Document</option>
        <option value="url">URL</option>
        <option value="graph_query">Graph query</option>
        <option value="workflow_output">Workflow output</option>
      </select>
      <input id="am-ctx-value" class="search-input" style="flex:1" placeholder="value (text, doc id, URL, query…)" list="am-ctx-docs">
      <datalist id="am-ctx-docs"></datalist>
      <input id="am-ctx-label" class="search-input" style="width:110px" placeholder="label">
      <button type="button" class="action-btn sm accent" data-action="agents.ctx-add">Add</button>
    </div>
  </div>
  <input type="hidden" id="am-context-json" value="${esc(contextJson)}">
  <input type="hidden" id="am-tools-json" value="${esc(toolsJson)}">
  <div id="am-error" style="display:none;color:var(--red,#f44);font-size:0.72rem;margin-top:8px;padding:6px 8px;background:rgba(255,68,68,0.08);border-radius:4px;"></div>
  <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">
    <button class="action-btn" data-action="agents.modal-cancel">Cancel</button>
    <button class="action-btn" id="am-save-btn" data-action="agents.modal-save" data-agent-id="${isEdit ? esc(a.id) : ''}"
            style="color:var(--cyan);border-color:var(--cyan-dim);">${isEdit ? 'Save changes' : 'Create agent'}</button>
  </div>`;
}

function showCreateAgentModal() {
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
  const inner = document.createElement('div');
  inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:560px;max-height:90vh;overflow-y:auto;border-radius:6px;display:flex;flex-direction:column;gap:0;';
  inner.innerHTML = _agentModalHtml('create', null);
  modal.appendChild(inner);
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
  _renderAgentToolsPicker([]);
  _renderAgentContextPicker([]);
  inner.querySelector('#am-id').focus();
}

async function showEditAgentModal(agentId) {
  let agent;
  try {
    agent = await Net.getJson(`/api/agents/${agentId}`);
  } catch(e) {
    Toast.danger('Failed to load agent for editing', agentId);
    return;
  }
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
  const inner = document.createElement('div');
  inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:560px;max-height:90vh;overflow-y:auto;border-radius:6px;display:flex;flex-direction:column;gap:0;';
  inner.innerHTML = _agentModalHtml('edit', agent);
  modal.appendChild(inner);
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
  _renderAgentToolsPicker(agent.tools || []);
  _renderAgentContextPicker(agent.context || []);
  inner.querySelector('#am-name').focus();
}

// ── Agent tools/capabilities picker ──────────────────────────────────────
// Builds a checkbox grid of everything an agent can invoke — built-in tools,
// every registered plugin tool, and MCP-server tools — keeping the hidden
// #am-tools-json in sync (the shape _saveAgentModal sends). This is the
// "agents need specific tools/capabilities/MCP alignment" piece.
async function _renderAgentToolsPicker(selected) {
  const host = document.getElementById('am-tools-picker');
  if (!host) return;
  const sel = new Set((selected || []).map(t =>
    t && t.type ? 'builtin:' + t.type
      : (t && t.plugin_id ? 'plugin:' + t.plugin_id + '::' + t.tool_id
        : (t && t.mcp_server ? 'mcp:' + t.mcp_server + '::' + (t.tool_id || '*') : ''))
  ).filter(Boolean));

  const groups = [];
  groups.push(['Built-in', [
    ['builtin:web_search', 'web_search', 'Live web search'],
    ['builtin:workflow', 'workflow', 'Run a workflow'],
    ['builtin:code_exec', 'code_exec', 'Execute code'],
  ]]);

  try {
    const d = await Net.getJson('/api/plugins', { silent: true });
    (Array.isArray(d) ? d : (d.plugins || [])).forEach(p => {
      const tools = p.tools || [];
      if (!tools.length) return;
      groups.push([p.name || p.id, tools.map(t => {
        const tid = t.id || t.name;
        return ['plugin:' + (p.id || p.name) + '::' + tid, tid, t.description || ''];
      })]);
    });
  } catch (_) { /* plugins unavailable — built-ins only */ }

  try {
    const servers = await Net.getJson('/api/mcp/servers', { silent: true });
    (Array.isArray(servers) ? servers : []).forEach(s => {
      groups.push(['MCP · ' + (s.name || s.id), [
        ['mcp:' + (s.id) + '::*', (s.name || s.id) + ' (all tools)', 'MCP server'],
      ]]);
    });
  } catch (_) { /* no MCP servers */ }

  const chip = (key, label, sub, on) => `
    <label class="am-tool-chip${on ? ' on' : ''}" title="${esc(sub || '')}">
      <input type="checkbox" data-tool="${esc(key)}" ${on ? 'checked' : ''} data-action="agents.tool-sync">
      <span class="am-tool-name">${esc(label)}</span>
    </label>`;
  host.innerHTML = groups.map(([gl, items]) =>
    `<div class="am-tools-group-label">${esc(gl)}</div><div class="am-tools-row">` +
    items.map(([k, l, sub]) => chip(k, l, sub, sel.has(k))).join('') + '</div>'
  ).join('');
  _syncAgentTools();
}

function _syncAgentTools() {
  const host = document.getElementById('am-tools-picker');
  if (!host) return;
  const tools = [];
  host.querySelectorAll('input[type=checkbox]').forEach(cb => {
    const chip = cb.closest('.am-tool-chip');
    if (chip) chip.classList.toggle('on', cb.checked);
    if (!cb.checked) return;
    const key = cb.getAttribute('data-tool') || '';
    if (key.startsWith('builtin:')) tools.push({ type: key.slice(8) });
    else if (key.startsWith('plugin:')) {
      const [pid, tid] = key.slice(7).split('::');
      tools.push({ plugin_id: pid, tool_id: tid });
    } else if (key.startsWith('mcp:')) {
      const [sid, tid] = key.slice(4).split('::');
      tools.push({ mcp_server: sid, tool_id: tid });
    }
  });
  const hidden = document.getElementById('am-tools-json');
  if (hidden) hidden.value = JSON.stringify(tools);
}

// ── Agent context/grounding picker ───────────────────────────────────────
// An editable list of ContextSource entries ({type,value,label}) injected
// into every turn. Mirrors the tools picker — the "context/data-aligned"
// half of agent creation. Kept in sync with the hidden #am-context-json.
let _agentCtx = [];

async function _renderAgentContextPicker(sources) {
  _agentCtx = Array.isArray(sources) ? sources.map(s => ({ ...s })) : [];
  // Offer ingested RAG documents as file-type values (dynamic — empty until
  // documents are ingested).
  try {
    const docs = await Net.getJson('/api/documents', { silent: true });
    const dl = document.getElementById('am-ctx-docs');
    if (dl && Array.isArray(docs)) {
      dl.innerHTML = docs.map(d =>
        `<option value="${esc(d.id || d.name || d.filename || '')}">${esc(d.name || d.filename || d.id || '')}</option>`
      ).join('');
    }
  } catch (_) { /* no documents */ }
  _agentCtxRender();
}

function _agentCtxRender() {
  const host = document.getElementById('am-context-picker');
  if (!host) return;
  host.innerHTML = _agentCtx.length
    ? _agentCtx.map((s, i) => `
      <div class="am-ctx-row">
        <span class="am-ctx-type">${esc(s.type)}</span>
        <span class="am-ctx-val" title="${esc(s.value || '')}">${esc(s.label || s.value || '')}</span>
        <button type="button" class="am-ctx-rm" data-action="agents.ctx-remove" data-idx="${i}" title="Remove">×</button>
      </div>`).join('')
    : '<div style="color:var(--text-muted);font-size:0.66rem;padding:2px 0">No context sources yet — add grounding data below.</div>';
  _agentCtxSync();
}

function _agentCtxAdd() {
  const type = document.getElementById('am-ctx-type')?.value || 'text';
  const value = (document.getElementById('am-ctx-value')?.value || '').trim();
  const label = (document.getElementById('am-ctx-label')?.value || '').trim();
  if (!value) return;
  _agentCtx.push({ type, value, label: label || null });
  document.getElementById('am-ctx-value').value = '';
  document.getElementById('am-ctx-label').value = '';
  _agentCtxRender();
}

function _agentCtxRemove(i) { _agentCtx.splice(i, 1); _agentCtxRender(); }

function _agentCtxSync() {
  const h = document.getElementById('am-context-json');
  if (h) h.value = JSON.stringify(_agentCtx);
}

// Delegated actions for the agent create/edit modal internals (context
// picker rows, tools checkboxes, save/cancel) + the model-fallback
// copy-pull chip in agent chat. The save button carries the edit id in
// data-agent-id ('' for create, matching the old interpolated arg).
(function () {
  Actions.click({
    'agents.ctx-add':      () => _agentCtxAdd(),
    'agents.ctx-remove':   el => _agentCtxRemove(Number(el.dataset.idx)),
    'agents.modal-cancel': el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); },
    'agents.modal-save':   el => _saveAgentModal(el.dataset.agentId),
    'agents.copy-pull':    el => navigator.clipboard.writeText(el.dataset.cmd)
  });
  Actions.change({
    'agents.tool-sync': () => _syncAgentTools()
  });
})();

async function _saveAgentModal(existingId) {
  const isEdit = !!existingId;
  const idVal    = isEdit ? existingId : (document.getElementById('am-id')?.value.trim() || '');
  const nameVal  = document.getElementById('am-name')?.value.trim() || '';
  const descVal  = document.getElementById('am-desc')?.value.trim() || '';
  const iconVal  = document.getElementById('am-icon')?.value.trim() || '';
  const promptVal = document.getElementById('am-prompt')?.value.trim() || '';
  const roleVal  = document.getElementById('am-role')?.value || '';
  const tagsRaw  = document.getElementById('am-tags')?.value || '';
  const tags     = tagsRaw.split(',').map(t => t.trim()).filter(Boolean);

  const errEl = document.getElementById('am-error');
  const showErr = msg => { errEl.textContent = msg; errEl.style.display = 'block'; };

  if (!isEdit && !/^[a-z0-9-]+$/.test(idVal)) { showErr('ID must be lowercase letters, numbers, and hyphens only.'); return; }
  if (!nameVal) { showErr('Display name is required.'); return; }
  if (!promptVal) { showErr('System prompt is required.'); return; }

  const modelField = document.getElementById('am-model')?.value.trim() || null;
  const tempField  = parseFloat(document.getElementById('am-temp')?.value);
  const temperature = isNaN(tempField) ? 0.7 : tempField;
  const maxTokField = parseInt(document.getElementById('am-max-tokens')?.value, 10);
  const max_tokens = isNaN(maxTokField) ? 4096 : maxTokField;
  const startersRaw = document.getElementById('am-starters')?.value || '';
  const starters = startersRaw.split('\n').map(s => s.trim()).filter(Boolean);
  let context = [], tools = [];
  try { context = JSON.parse(document.getElementById('am-context-json')?.value || '[]'); } catch(_) {}
  try { tools   = JSON.parse(document.getElementById('am-tools-json')?.value   || '[]'); } catch(_) {}

  const payload = {
    id: idVal, name: nameVal, description: descVal || null,
    icon: iconVal || null, system_prompt: promptVal,
    role: roleVal || null, tags,
    model: modelField, temperature, max_tokens, starters, context, tools,
  };

  const btn = document.getElementById('am-save-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }

  try {
    const url = isEdit ? `/api/agents/${existingId}` : '/api/agents';
    const method = isEdit ? 'PUT' : 'POST';
    // Net.call (not postJson): PUT branch + error body rendered inline. retries:0 — create/update.
    const r = await Net.call(url, {
      retries: 0,
      init: {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    });
    const d = (r.data && typeof r.data === 'object') ? r.data : {};
    if (!r.ok) { showErr(d.detail || JSON.stringify(d)); if (btn) { btn.disabled = false; btn.textContent = isEdit ? 'Save changes' : 'Create agent'; } return; }
    document.querySelector('div[style*=fixed]')?.remove();
    loadAgentsTab();
  } catch(e) {
    showErr('Request failed: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = isEdit ? 'Save changes' : 'Create agent'; }
  }
}

// ── AdminMenu ─────────────────────────────────────────────────────────────
window.AdminMenu = (function () {
  const trigger = () => document.getElementById('admin-trigger');
  const menu = () => document.getElementById('admin-menu');

  function open() {
    menu().hidden = false;
    trigger().setAttribute('aria-expanded', 'true');
    document.addEventListener('click', onOutsideClick, true);
    document.addEventListener('keydown', onKeydown);
    // Focus first menu item for keyboard users.
    const first = menu().querySelector('.admin-menu-item');
    if (first) first.focus();
  }

  function close() {
    menu().hidden = true;
    trigger().setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onOutsideClick, true);
    document.removeEventListener('keydown', onKeydown);
  }

  function toggle(_el) {
    if (menu().hidden) open(); else close();
  }

  function onOutsideClick(e) {
    if (!menu().contains(e.target) && !trigger().contains(e.target)) close();
  }

  function onKeydown(e) {
    if (e.key === 'Escape') { close(); trigger().focus(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const items = Array.from(menu().querySelectorAll('.admin-menu-item'));
      const i = items.indexOf(document.activeElement);
      const next = e.key === 'ArrowDown'
        ? items[(i + 1) % items.length]
        : items[(i - 1 + items.length) % items.length];
      next.focus();
    }
  }

  function select(panelId) {
    close();
    showPanel(panelId);
  }

  function showPanel(panelId) {
    // Hide every .tab-content (operational + admin).
    document.querySelectorAll('.tab-content').forEach(t => {
      t.classList.remove('active');
      t.style.display = '';
    });
    // De-active every .tab-btn.
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

    const target = document.getElementById('tab-' + panelId);
    if (target) {
      target.classList.add('active');
      target.style.display = 'block';
    }
    trigger().classList.add('active');

    // Notify panels so they can lazy-load.
    window.dispatchEvent(new CustomEvent('adminPanelActivated', {detail: {panel: panelId}}));
  }

  // Reset Admin trigger active state when an operational tab is chosen.
  document.addEventListener('click', function (e) {
    if (e.target.classList.contains('tab-btn') && e.target.id !== 'admin-trigger') {
      trigger().classList.remove('active');
    }
  }, true);

  return { toggle, select, open, close, showPanel };
})();

// ── AdminAuth ─────────────────────────────────────────────────────────────
// Persists the operator's license key in localStorage so it survives
// reloads and tab close. Legacy installs that stored under the old
// sessionStorage key are migrated forward on first read.
window.AdminAuth = (function () {
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

// Delegated action for the admin lock screens (renderLock re-renders one
// per gated panel).
Actions.click({ 'admin.sign-in': el => AdminAuth.signIn(el.dataset.panel) });

// ── Auth — single-tier wrapper around AdminAuth ─────────────────────────
// Collapses the legacy dual-tier (operator vs. admin master key) into one
// key that gates every same-origin /api/* and /v1/* request. The dropdown
// stays as an organizational surface, not an RBAC boundary.
window.Auth = window.AdminAuth;

// ── Toast API ─────────────────────────────────────────────────────────────
// Replaces alert()-style notifications with a non-blocking corner stack.
// Usage:
//   Toast.info('Title', 'Body text')
//   Toast.success('Saved')
//   Toast.warn('Rate limit nearing', 'Slow down or bump RATE_LIMIT_RPM')
//   Toast.danger('Workflow failed', err.message)
// Toasts auto-dismiss after 4s; click to dismiss earlier.

// ── Global error safety net ───────────────────────────────────────────────
// Catches uncaught exceptions and unhandled promise rejections so they
// surface to the operator instead of dying silently in the console.
// Rate-limited so a runaway loop can't spam the toast stack. Also tracks
// the error in localStorage for post-incident debugging.
(function installGlobalErrorHandlers() {
  const STORE_KEY = 'enclave.errorLog.v1';
  const MAX_LOG = 50;
  let _lastToast = 0;

  function _logError(kind, info) {
    try {
      const log = JSON.parse(localStorage.getItem(STORE_KEY) || '[]');
      log.push({ kind, info, ts: new Date().toISOString(), href: location.href });
      while (log.length > MAX_LOG) log.shift();
      localStorage.setItem(STORE_KEY, JSON.stringify(log));
    } catch (_) { /* localStorage full / disabled — fine */ }
  }

  function _toastOnce(title, detail) {
    const now = Date.now();
    if (now - _lastToast < 2500) return; // rate-limit
    _lastToast = now;
    if (window.Toast) Toast.danger(title, detail, { ttl: 4500 });
  }

  window.addEventListener('error', (e) => {
    if (!e) return;
    const info = (e.message || '') + ' @ ' + (e.filename || '?') + ':' + (e.lineno || '?');
    _logError('error', info);
    _toastOnce('Unhandled error', info.slice(0, 200));
  });

  window.addEventListener('unhandledrejection', (e) => {
    const info = (e && e.reason && (e.reason.message || String(e.reason))) || 'unknown promise rejection';
    _logError('rejection', info);
    // Don't toast on common AbortError — those are normal during nav.
    if (/AbortError|aborted/.test(String(info))) return;
    _toastOnce('Unhandled promise rejection', String(info).slice(0, 200));
  });

  window.EnclaveErrorLog = {
    list: () => { try { return JSON.parse(localStorage.getItem(STORE_KEY) || '[]'); } catch (_) { return []; } },
    clear: () => { try { localStorage.removeItem(STORE_KEY); } catch (_) {} },
  };
})();

// ── Net: hardened fetch wrapper ───────────────────────────────────────────
// Single chokepoint for every API call so retry/backoff/offline detection
// and error semantics are consistent across the whole SPA. The existing
// monkey-patched window.fetch handles auth-header injection; Net wraps
// that with:
//   • automatic retry-with-backoff on transient failures (network errors,
//     5xx, 429 with Retry-After)
//   • offline detection — surfaces a single sticky toast while offline
//     and auto-dismisses when back
//   • structured error returns: { ok, status, data, error, retried }
//   • silent mode for polling loops that shouldn't toast on every miss
//
// Existing call sites that use window.fetch directly still work — Net is
// opt-in and additive.

// ── ErrorPanel: consistent inline error rendering ─────────────────────────
// Drop the same visual treatment everywhere a panel fails to load. Pairs
// with EmptyState for the success-but-empty case.

// ── EmptyState: consistent zero-data treatment ───────────────────────────

// ── Heartbeat: backend liveness + degraded-state banner ───────────────────
// Polls /health every 30s with no auth (it's a public endpoint). Surfaces
// degraded states in a chip glued to the header so the operator sees
// instantly when Ollama drops out, the auth keystore is misconfigured,
// or the API itself starts erroring. Reuses the existing #env-chip
// container so we don't compete for header real estate.

// ── Confirm: styled replacement for window.confirm() ──────────────────────
// Same call-site shape as a real promise-based confirm. Returns a
// promise that resolves to true/false. Built on the admin-modal CSS so
// it inherits the brand palette + motion.

// ── Keyboard Shortcuts ────────────────────────────────────────────────────
// Operator productivity layer: command palette + tab jumps. Press
// Cmd/Ctrl-K to toggle, or any of the keymap entries for direct jumps.
// Designed to fail silently when focus is on a text input so users can
// type the keys literally without triggering shortcuts.

// Delegated action for the shortcuts overlay close button.
Actions.click({ 'shortcuts.close': () => Shortcuts.toggle(false) });

// ── Kanban (Projects + Tasks) ─────────────────────────────────────────────
// Lightweight task board inside Workflow Index. Tasks live server-side as
// JSONL events under data/projects/<id>/tasks.jsonl, fetched via
// /api/projects/{id}/tasks. State is per-project so switching the
// project_select in the kanban head swaps the board.

// Delegated actions for the Kanban board — cards re-render on every board
// mutation; the card carries data-task-id + data-action="kanban.card" and
// the column bodies are dropzones keyed by data-status. dragover MUST
// preventDefault for the body to stay a valid drop target (same contract
// the old inline ondragover honored); drop itself preventDefaults inside
// Kanban.drop.
(function () {
  const taskIdOf = el => {
    const card = el.closest('[data-task-id]');
    return card ? card.dataset.taskId : '';
  };
  Actions.on('dragstart', {
    'kanban.card': (el, e) => Kanban._dragStart(e, taskIdOf(el))
  });
  Actions.on('dragend', {
    'kanban.card': (el, e) => Kanban._dragEnd(e)
  });
  Actions.on('dblclick', {
    'kanban.card': el => Kanban.showEditTask(taskIdOf(el))
  });
  Actions.click({
    'kanban.edit':   el => Kanban.showEditTask(taskIdOf(el)),
    'kanban.delete': el => Kanban.deleteTask(taskIdOf(el)),
    'kanban.add':    el => Kanban.showCreateTask(el.dataset.status)
  });
  Actions.on('dragover', {
    'kanban.dropzone': (el, e) => { e.preventDefault(); el.classList.add('drop-target'); }
  });
  Actions.on('dragleave', {
    'kanban.dropzone': el => el.classList.remove('drop-target')
  });
  Actions.on('drop', {
    'kanban.dropzone': (el, e) => Kanban.drop(e, el.dataset.status)
  });
})();

// ── Composer Workstream ───────────────────────────────────────────────────
// Controller for the three-tab strip at the bottom of the Composer:
//   Step Config · Active Run · History
// All three are mounted in the same panel so the canvas above keeps its
// full real estate. The Step pane wraps the existing df-config-panel
// element so node-click handlers don't need any wiring change.
window.ComposerWorkstream = (function () {
  const panes = ['step', 'run', 'history'];

  function _setActive(name) {
    panes.forEach(p => {
      const tab  = document.querySelector('.workstream-tab[data-ws="' + p + '"]');
      const pane = document.getElementById('ws-pane-' + p);
      if (!pane) return;
      const on = (p === name);
      pane.hidden = !on;
      if (tab) tab.classList.toggle('active', on);
    });
  }

  function switchTab(name, _el) {
    _setActive(name);
    if (name === 'run')     _refreshRun();
    if (name === 'history') _refreshHistory();
  }

  function focusStep(stepId) {
    // Called by the canvas node-click handler so the bottom strip pulls
    // attention to Step Config whenever a node is selected.
    _setActive('step');
    const meta = document.getElementById('ws-step-meta');
    if (meta) {
      meta.textContent = stepId ? '#' + stepId : '(none)';
      meta.setAttribute('data-step-id', stepId || '(none)');
    }
  }

  async function _refreshRun() {
    const body = document.getElementById('ws-run-body');
    if (!body) return;
    // _lastRunSummary is set by anything that POSTs /api/workflows/run.
    // We don't subscribe to live progress yet — but the Active Run pane
    // tails the last run so the operator always has somewhere to look.
    const last = window._lastRunSummary;
    if (!last) {
      EmptyState.render(body, {
        title: 'No active run',
        detail: 'Hit Run ▶ or Run ▶ live on the toolbar above, or trigger a workflow from the Workflow Index.',
        glyph: '▶',
      });
      _setRunMeta('idle');
      return;
    }
    const steps = (last.step_results || []).map(s => {
      const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
      const stateClass = s.status === 'completed' ? 'ok' : s.status === 'failed' ? 'fail' : 'pending';
      return `
        <div class="ws-run-step ws-run-step-${stateClass}">
          <span class="ws-run-step-id">${esc(s.step_id)}</span>
          <span class="ws-run-step-model">${esc(s.model_used || '?')}</span>
          <span class="ws-run-step-dur">${dur}</span>
          <span class="ws-run-step-status">${esc(s.status)}</span>
        </div>
      `;
    }).join('');
    body.innerHTML = `
      <div class="ws-run-head">
        <strong>${esc(last.workflow_id || '?')}</strong>
        <span class="ws-run-meta">run_id ${esc((last.run_id || '').slice(0, 12))} · status ${esc(last.status || '?')}</span>
        <span style="flex:1"></span>
        <button type="button" class="ws-run-action" data-action="ws.clear-run"
                title="Clear this run output">Clear</button>
        <button type="button" class="ws-run-action ghost" data-action="ws.run-collapse"
                id="ws-run-collapse-btn" title="Minimize / expand the run output">▾</button>
      </div>
      <div class="ws-run-body-collapsible" id="ws-run-body-collapsible">
        ${steps || '<div class="model-empty">no steps reported</div>'}
      </div>
    `;
    _setRunMeta(last.status === 'completed' ? '✓ ' + (last.step_results || []).length + ' steps' : last.status || 'running');
  }

  async function _refreshHistory() {
    const body = document.getElementById('ws-history-body');
    if (!body) return;
    Skeleton.fill(body, 3);
    const r = await Net.call('/api/workflows/runs?limit=20', { silent: true });
    if (!r.ok) {
      ErrorPanel.render(body, {
        title: 'Couldn’t load run history',
        detail: r.error,
        retry: () => _refreshHistory(),
      });
      return;
    }
    const list = r.data;
    const rows = Array.isArray(list) ? list : (list && list.runs) || [];
    if (!rows.length) {
      EmptyState.render(body, {
        title: 'No runs yet',
        detail: 'Run a workflow from the toolbar above or kick one off from the Workflow Index.',
        glyph: '▶',
      });
      const hm = document.getElementById('ws-history-meta');
      if (hm) hm.textContent = '0';
      return;
    }
    body.innerHTML = rows.map(row => {
      const stateClass = row.status === 'completed' ? 'ok' : row.status === 'failed' ? 'fail' : 'pending';
      const ts = row.started_at || row.created_at || '';
      return `
        <div class="ws-history-row ws-history-row-${stateClass}">
          <span class="ws-history-wf">${esc(row.workflow_id || '?')}</span>
          <code class="ws-history-id">${esc((row.run_id || '').slice(0, 12))}</code>
          <span class="ws-history-status">${esc(row.status || '?')}</span>
          <span class="ws-history-ts">${esc(ts)}</span>
        </div>
      `;
    }).join('');
    const hm = document.getElementById('ws-history-meta');
    if (hm) hm.textContent = rows.length + (rows.length === 20 ? '+' : '');
  }

  function _setRunMeta(text) {
    const m = document.getElementById('ws-run-meta');
    if (m) m.textContent = text;
  }

  function recordRun(summary) {
    window._lastRunSummary = summary;
    if (document.querySelector('.workstream-tab[data-ws="run"].active')) _refreshRun();
    else _setRunMeta(summary.status || 'running');
  }

  // Live polling. Call startPolling(run_id) right after POST /run-async;
  // the workstream auto-switches to the Active Run pane and updates the
  // per-step status as the engine checkpoints. Stops when the run reaches
  // a terminal status. Returns a stop() function for the caller.
  let _activePollHandle = null;
  function startPolling(runId, opts) {
    if (!runId) return () => {};
    if (_activePollHandle) clearInterval(_activePollHandle);
    opts = opts || {};
    const intervalMs = opts.interval || 1200;
    _setActive('run');
    _setRunMeta('queued');
    // Prime the canvas with a "queued" overlay so there's instant visual
    // feedback before the first poll response lands.
    if (typeof window.dfApplyRunState === 'function') {
      try { window.dfApplyRunState({ run_id: runId, status: 'queued', step_results: [] }); } catch (_) {}
    }
    const body = document.getElementById('ws-run-body');
    if (body) {
      body.innerHTML = `
        <div class="ws-run-head">
          <strong>${esc(runId.slice(0, 12))}…</strong>
          <span class="ws-run-meta">starting…</span>
          <span style="flex:1"></span>
          <button type="button" class="ws-run-action" data-action="ws.clear-run"
                  title="Cancel + clear this run output">Cancel</button>
          <button type="button" class="ws-run-action ghost" data-action="ws.run-collapse"
                  id="ws-run-collapse-btn" title="Minimize / expand the run output">▾</button>
        </div>
        <div class="ws-run-body-collapsible" id="ws-run-body-collapsible">
          <div class="skeleton skeleton-line long"></div>
          <div class="skeleton skeleton-line short"></div>
          <div class="skeleton skeleton-line long"></div>
        </div>
      `;
    }

    const seen = new Set();
    let lastStatus = '';
    let consecutiveFailures = 0;
    const maxFailures = 5;

    _activePollHandle = setInterval(async () => {
      try {
        // silent + retries:0 — Net's own retry/backoff would mask the
        // failures this counter is designed to count, and stack with
        // the interval timer.
        const r = await Net.call('/api/workflows/runs/' + encodeURIComponent(runId), { silent: true, retries: 0 });
        if (!r.ok) {
          consecutiveFailures++;
          if (consecutiveFailures >= maxFailures) {
            clearInterval(_activePollHandle);
            _activePollHandle = null;
            _setRunMeta('lost contact');
            if (window.Toast) Toast.danger('Run lost', 'Poll repeatedly returned ' + r.status);
          }
          return;
        }
        consecutiveFailures = 0;
        const run = r.data;
        recordRun(run);
        // Live canvas overlay — paints node statuses + the floating
        // progress chip so the operator can SEE which step is running.
        if (typeof window.dfApplyRunState === 'function') {
          try { window.dfApplyRunState(run); } catch (_) {}
        }
        if (document.querySelector('.workstream-tab[data-ws="run"].active')) _refreshRun();
        // Toast new completed steps once each.
        (run.step_results || []).forEach(s => {
          const key = s.step_id + ':' + s.status;
          if (!seen.has(key) && s.status === 'completed') {
            seen.add(key);
            if (window.Toast) {
              Toast.success(
                'Step ' + s.step_id,
                'completed in ' + Math.round(s.duration_seconds || 0) + 's · ' + (s.model_used || '?'),
                { ttl: 3500 }
              );
            }
          }
          if (!seen.has(s.step_id + ':failed') && s.status === 'failed') {
            seen.add(s.step_id + ':failed');
            if (window.Toast) Toast.danger('Step ' + s.step_id + ' failed', s.error || 'unknown error');
          }
        });
        // Terminal status — stop polling.
        if (['completed', 'failed', 'error'].includes(run.status) && lastStatus !== run.status) {
          lastStatus = run.status;
          clearInterval(_activePollHandle);
          _activePollHandle = null;
          if (window.Toast) {
            if (run.status === 'completed') {
              Toast.success('Run complete', run.workflow_id + ' · ' + (run.step_results || []).length + ' steps');
            } else {
              Toast.danger('Run failed', run.error || run.status);
            }
          }
        }
      } catch (e) {
        consecutiveFailures++;
      }
    }, intervalMs);

    return function stop() {
      if (_activePollHandle) {
        clearInterval(_activePollHandle);
        _activePollHandle = null;
      }
    };
  }

  function stopPolling() {
    if (_activePollHandle) {
      clearInterval(_activePollHandle);
      _activePollHandle = null;
    }
  }

  function refresh() {
    const active = document.querySelector('.workstream-tab.active');
    const name = active ? active.dataset.ws : 'step';
    switchTab(name);
  }

  // Wipe the active-run pane and stop any in-flight poller so the
  // operator can clear out a finished run's output without leaving
  // stale step rows on screen.
  function clearRun() {
    // If there's a live run we know about, ask the engine to cancel it
    // before tearing down the local view. Best-effort: a 404 just
    // means the engine never saw it, which is fine.
    const last = window._lastRunSummary;
    const liveId = last && last.run_id &&
      !['completed', 'failed', 'canceled', 'error'].includes((last.status || '').toLowerCase())
      ? last.run_id : null;
    if (liveId) {
      // silent + retries:0 — best-effort cancel; a 404 is expected and fine.
      Net.call(`/api/workflows/runs/${encodeURIComponent(liveId)}/cancel`, { silent: true, retries: 0, init: { method: 'POST' } })
        .then(r => {
          const j = r.ok ? r.data : null;
          if (window.Toast && j && j.accepted) {
            Toast.info('Run cancel requested', 'Engine will stop after the current step.');
          }
        })
        .catch(() => { /* non-fatal */ });
    }
    stopPolling();
    window._lastRunSummary = null;
    const body = document.getElementById('ws-run-body');
    if (body) {
      EmptyState.render(body, {
        title: liveId ? 'Cancel requested' : 'Run cleared',
        detail: liveId
          ? 'The engine will stop at the next step boundary. In-flight LLM calls finish first.'
          : 'Trigger a workflow to populate this pane again.',
        glyph: '▶',
      });
    }
    _setRunMeta(liveId ? 'canceling…' : 'idle');
    // Also wipe canvas overlays so the visual carries no leftover state.
    if (typeof window.dfClearRunState === 'function') {
      try { window.dfClearRunState(); } catch (_) {}
    }
  }

  // Toggle a collapsed state on just the run body (not the whole
  // workstream — that's the panel-level collapse). The head row with
  // run_id + status stays visible so the operator can still see what
  // they're hiding and re-expand later.
  function toggleRunCollapse() {
    const body = document.getElementById('ws-run-body-collapsible');
    const btn  = document.getElementById('ws-run-collapse-btn');
    if (!body) return;
    const collapsed = body.classList.toggle('collapsed');
    if (btn) btn.textContent = collapsed ? '▴' : '▾';
  }

  return {
    switch: switchTab,
    focusStep,
    recordRun,
    refresh,
    startPolling,
    stopPolling,
    clearRun,
    toggleRunCollapse,
  };
})();

// Delegated actions for the workstream Active Run pane — its head row is
// re-rendered on every poll tick during live runs.
Actions.click({
  'ws.clear-run':    () => ComposerWorkstream.clearRun(),
  'ws.run-collapse': () => ComposerWorkstream.toggleRunCollapse()
});

// ── Chat Rating ───────────────────────────────────────────────────────────
// Thumbs up/down + optional note on every assistant message. Each rating
// is appended to a localStorage log keyed by message id, AND posted to
// /api/feedback when that endpoint is available (silently no-ops on 404
// so the rating UI still works in older builds). The rating becomes
// per-conversation training data: which outputs the operator marked good
// vs bad with optional context.
/* ── AGENT TUNING ─────────────────────────────────────────────────────
   Up/down votes in a node-bound chat become persisted, per-agent behavior
   tuning. Keyed by the step's semantic id (e.g. 'researcher') so the same
   agent in another workflow inherits the feedback — "the centerpoint for
   other workflows". The tuning is applied as a system-prompt guidance block
   when that agent runs (preferred / avoided exemplars). */
window.AgentTuning = (function () {
  const KEY = 'enclave.agentTuning.v1';
  function _load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function _save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  function _key(nodeId) {
    try { const d = (typeof dfNodeData !== 'undefined') && dfNodeData[nodeId]; return d ? (d.id || ('role:' + (d.role || 'general'))) : null; } catch (e) { return null; }
  }
  function record(nodeId, kind, text) {
    const k = _key(nodeId); if (!k) return;
    const s = _load();
    const t = s[k] || { up: 0, down: 0, prefer: [], avoid: [] };
    if (kind === 'up') { t.up++; if (text) { t.prefer.unshift(text.slice(0, 600)); t.prefer = t.prefer.slice(0, 3); } }
    else if (kind === 'down') { t.down++; if (text) { t.avoid.unshift(text.slice(0, 600)); t.avoid = t.avoid.slice(0, 3); } }
    s[k] = t; _save(s);
    refreshBadge(nodeId);
    // Mirror to the server so tuning survives reload + aggregates across
    // sessions. Best-effort; the localStorage copy is the offline fallback.
    try {
      fetch('/api/feedback/agent-tuning', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_key: k, kind: kind, text: text || null }),
      }).catch(function () {});
    } catch (e) {}
    if (window.Toast) Toast.info('Agent tuned', k + ' · ▲' + t.up + ' ▼' + t.down + ' (applies on next run, here + other workflows)');
  }
  // Pull the durable server-side map on load and adopt it as the source of
  // truth (it has accumulated every synced up/down across sessions).
  function _syncFromServer() {
    try {
      fetch('/api/feedback/agent-tuning').then(function (r) { return r.ok ? r.json() : null; })
        .then(function (map) {
          if (!map || typeof map !== 'object') return;
          const local = _load();
          Object.keys(map).forEach(function (k) {
            const sv = map[k] || {};
            local[k] = { up: sv.up || 0, down: sv.down || 0, prefer: sv.prefer || [], avoid: sv.avoid || [] };
          });
          _save(local);
          if (window._composerEngagedNodeId != null) refreshBadge(window._composerEngagedNodeId);
        }).catch(function () {});
    } catch (e) {}
  }
  function get(nodeId) { const k = _key(nodeId); return k ? (_load()[k] || null) : null; }
  function guidance(nodeId) {
    const t = get(nodeId); if (!t || (!t.prefer.length && !t.avoid.length)) return '';
    const one = x => x.replace(/\s+/g, ' ').slice(0, 200);
    let g = '\n\n[Operator tuning — learned from up/down feedback]';
    if (t.prefer.length) g += '\nPrefer responses in the style/substance of:\n- ' + t.prefer.map(one).join('\n- ');
    if (t.avoid.length) g += '\nAvoid responses like:\n- ' + t.avoid.map(one).join('\n- ');
    return g;
  }
  function refreshBadge(nodeId) {
    if (window._composerEngagedNodeId !== nodeId) return;
    const el = document.getElementById('step-engage-tuning');
    const t = get(nodeId);
    if (el) el.textContent = (t && (t.up || t.down)) ? ('▲' + t.up + ' ▼' + t.down + ' tuned') : '';
  }
  _syncFromServer();
  return { record, get, guidance, refreshBadge };
})();

window.ChatRating = (function () {
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

// Delegated actions for the per-message rating toolbar — appended with
// every chat message, so the markup stays handler-free. The msg id lives
// on the .msg-actions container (data-msg-id).
(function () {
  const msgIdOf = el => {
    const host = el.closest('[data-msg-id]');
    return host ? host.dataset.msgId : '';
  };
  Actions.click({
    'chat.rate': el => ChatRating.rate(msgIdOf(el), el.dataset.dir, el),
    'chat.copy': el => ChatRating.copy(msgIdOf(el), el)
  });
})();

// ── Skeleton helper ───────────────────────────────────────────────────────
// Render N shimmer placeholder lines into a container, replacing whatever
// "Loading…" sentinel the panel currently shows. The caller swaps these
// out when its data arrives:
//   Skeleton.fill(el, 3)
//   ... fetch ...
//   el.innerHTML = renderedRows;

(function installGlobalAuthFetch() {
  const _origFetch = window.fetch.bind(window);
  const apiPath = /^\/(api|v1)\//;
  let _reauthInFlight = false;

  // Boot gate — the panel loaders all fire on DOMContentLoaded, racing
  // bootSignIn()'s key fetch. Anything that lost the race went out with no
  // Authorization header and 401'd (console noise + panels rendering from a
  // failed first fetch). Hold every pre-sign-in API request until the boot
  // sign-in attempt settles; the wrapper re-enters itself so the deferred
  // request picks up the key. If sign-in failed (remote install, no local
  // license) the gate still opens and requests proceed unauthenticated —
  // same behavior as before, minus the race.
  let _bootSettled = false;
  let _openBootGate;
  const _bootGate = new Promise((res) => { _openBootGate = res; });

  function pathOf(input) {
    let url = typeof input === 'string' ? input : (input && input.url) || '';
    if (/^https?:\/\//.test(url)) {
      try {
        const u = new URL(url);
        if (u.origin === window.location.origin) return u.pathname + u.search;
        return '';  // cross-origin — skip injection
      } catch (_) { return ''; }
    }
    return url;
  }

  window.fetch = function (input, init) {
    const path = pathOf(input);
    if (path && apiPath.test(path) && !_bootSettled && !Auth.isSignedIn()) {
      return _bootGate.then(() => window.fetch(input, init));
    }
    let wasAuthed = false;
    if (path && apiPath.test(path) && Auth.isSignedIn()) {
      init = init || {};
      init.headers = Object.assign({}, init.headers || {}, Auth.authHeaders());
      wasAuthed = true;
    }
    return _origFetch(input, init).then(function (r) {
      // Only treat a 401 as "signed out" if WE actually sent a key the server
      // rejected. A 401 on a request made before sign-in (no auth header — the
      // parallel panel fetches that fire during boot) is expected; ignoring it
      // prevents a stale pre-auth response from wiping the key we just set +
      // flashing the modal (the race the old full-page reload used to mask).
      if (r.status === 401 && wasAuthed && path && apiPath.test(path) && !_reauthInFlight) {
        _reauthInFlight = true;
        Auth.signOut();
        Auth.signIn(null);
        const reset = () => { _reauthInFlight = false; };
        const m = document.getElementById('admin-signin-modal');
        if (m) m.addEventListener('transitionend', reset, { once: true });
        setTimeout(reset, 1500);  // fallback if no transition fires
      }
      return r;
    });
  };

  // Boot — auto-deliver the local "license" key so the operator isn't
  // gated by the modal during local testing. The endpoint is public-path
  // and localhost-only on the backend; if it fails (remote install, key
  // file missing, future paid activation flow), fall back to the manual
  // sign-in modal so there's always a path forward.
  async function bootSignIn() {
    if (Auth.isSignedIn()) return;
    try {
      const r = await _origFetch('/api/setup/local-license', {
        headers: { 'Accept': 'application/json' },
      });
      if (r.ok) {
        const data = await r.json();
        if (data && data.key) {
          Auth.setKey(data.key);  // also refreshes the admin status pill
          // Soft re-init instead of a full-page reload. The fetch wrapper
          // reads the key dynamically, so subsequent fetches are already
          // authed; we just re-fire the active tab's loaders (panels that
          // fetched before the key landed). A reload here aborts the page's
          // in-flight navigation (net::ERR_ABORTED — breaks the Playwright
          // suite) and flashes the whole UI for the user.
          try {
            // The pre-auth 401 race may have popped the sign-in modal before
            // the key landed — close it now that we're authed.
            const modal = document.getElementById('admin-signin-modal');
            if (modal) modal.hidden = true;
            const activeBtn = document.querySelector('.tab-btn.active');
            const tab = activeBtn ? activeBtn.getAttribute('data-tab') : null;
            if (tab && typeof switchTab === 'function') switchTab(tab, activeBtn);
          } catch (_) { /* best-effort */ }
          return;
        }
      }
    } catch (_) { /* fall through to manual modal */ }
    Auth.signIn(null);
  }
  function runBootSignIn() {
    Promise.resolve()
      .then(bootSignIn)
      .catch(() => {})
      .finally(() => { _bootSettled = true; _openBootGate(); });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runBootSignIn);
  } else {
    runBootSignIn();
  }
})();

// ── ApiKeysPanel ──────────────────────────────────────────────────────────
window.ApiKeysPanel = (function () {

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  let _knownScopes = null;     // cached list from /api/keys/scopes
  let _selectedScopes = new Set();
  let _newKeyValue = '';

  async function load() {
    if (!AdminAuth.isSignedIn()) {
      AdminAuth.renderLock('admin-keys');
      return;
    }
    const list = document.getElementById('api-keys-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';

    const r = await AdminAuth.fetch('/api/keys', {}, 'admin-keys');
    if (!r.ok) {
      // 401 already handled by AdminAuth.fetch.
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed to load keys (HTTP ${r.status})</div>`;
      return;
    }
    const keys = await r.json();
    if (!Array.isArray(keys) || keys.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);padding:10px 0">No keys yet. Click "+ New Key" to create one.</div>';
      return;
    }

    // Header + rows.
    list.innerHTML = `
      <table class="api-keys-table" role="table">
        <thead>
          <tr>
            <th>Name</th><th>Key</th><th>Scopes</th>
            <th>RPM</th><th>Last used</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          ${keys.map(rowHtml).join('')}
        </tbody>
      </table>
    `;
  }

  function rowHtml(k) {
    const enabled = k.enabled !== false;
    const last = k.last_used_at
      ? new Date(k.last_used_at).toLocaleString()
      : '<span style="color:var(--text-muted)">never</span>';
    const scopes = (k.scopes || []).map(s =>
      `<span class="scope-chip">${esc(s)}</span>`).join(' ');
    const masked = `${esc(k.prefix || '')}…${esc(k.last_four || '')}`;
    return `
      <tr class="${enabled ? '' : 'key-disabled'}">
        <td>${esc(k.name)}</td>
        <td><code>${masked}</code></td>
        <td>${scopes || '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${k.rate_limit_rpm ?? '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${last}</td>
        <td>${enabled
          ? '<span style="color:var(--accent)">enabled</span>'
          : '<span style="color:var(--text-muted)">revoked</span>'}</td>
        <td class="row-actions">
          ${enabled ? `
            <button class="action-btn small" data-action="keys.rotate" data-key-id="${esc(k.id)}" data-key-name="${esc(k.name)}">Rotate</button>
            <button class="action-btn small danger" data-action="keys.revoke" data-key-id="${esc(k.id)}" data-key-name="${esc(k.name)}">Revoke</button>
          ` : ''}
        </td>
      </tr>
    `;
  }

  function refresh() { load(); }

  async function _ensureScopes() {
    if (_knownScopes) return _knownScopes;
    const r = await AdminAuth.fetch('/api/keys/scopes', {}, 'admin-keys');
    if (!r.ok) throw new Error('failed to load scopes');
    _knownScopes = (await r.json()).scopes || [];
    return _knownScopes;
  }

  async function showCreate() {
    if (!AdminAuth.isSignedIn()) { AdminAuth.renderLock('admin-keys'); return; }
    document.getElementById('create-key-form').hidden = false;
    document.getElementById('create-key-reveal').hidden = true;
    document.getElementById('create-key-error').hidden = true;
    document.getElementById('new-key-name').value = '';
    document.getElementById('new-key-rpm').value = '';
    document.getElementById('new-key-expires').value = '';
    document.getElementById('new-key-confirm-copied').checked = false;
    document.getElementById('create-key-close-btn').disabled = true;

    _selectedScopes = new Set();
    const scopes = await _ensureScopes();
    const picker = document.getElementById('new-key-scopes');
    picker.innerHTML = scopes.map(s =>
      `<button type="button" class="btn-unstyled scope-chip" data-scope="${esc(s)}" aria-pressed="false"
        data-action="keys.scope">${esc(s)}</button>`
    ).join('');

    document.getElementById('create-key-modal').hidden = false;
    setTimeout(() => document.getElementById('new-key-name').focus(), 0);
  }

  function _toggleScope(s, el) {
    if (_selectedScopes.has(s)) {
      _selectedScopes.delete(s);
      el.classList.remove('selected');
    } else {
      _selectedScopes.add(s);
      el.classList.add('selected');
    }
    el.setAttribute('aria-pressed', _selectedScopes.has(s) ? 'true' : 'false');
  }

  async function _submitCreate() {
    const name = document.getElementById('new-key-name').value.trim();
    const rpmRaw = document.getElementById('new-key-rpm').value.trim();
    const expRaw = document.getElementById('new-key-expires').value.trim();
    const errBox = document.getElementById('create-key-error');

    if (!name) { errBox.hidden = false; errBox.textContent = 'Name is required.'; return; }
    if (_selectedScopes.size === 0) {
      errBox.hidden = false; errBox.textContent = 'Pick at least one scope.'; return;
    }

    const body = {
      name,
      scopes: Array.from(_selectedScopes),
      rate_limit_rpm: rpmRaw ? Number(rpmRaw) : null,
      expires_at: expRaw ? expRaw + 'T00:00:00Z' : null,
    };

    const r = await AdminAuth.fetch('/api/keys', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }, 'admin-keys');

    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      errBox.hidden = false;
      errBox.textContent = detail.detail || `Failed (HTTP ${r.status})`;
      return;
    }

    const result = await r.json();
    _newKeyValue = result.key || '';
    document.getElementById('new-key-value').textContent = _newKeyValue;
    document.getElementById('create-key-form').hidden = true;
    document.getElementById('create-key-reveal').hidden = false;
    document.getElementById('copy-confirm').style.display = 'none';
    load(); // refresh the table behind the modal
  }

  function _copyKey() {
    if (!_newKeyValue || !navigator.clipboard) return;
    navigator.clipboard.writeText(_newKeyValue).then(() => {
      const c = document.getElementById('copy-confirm');
      c.style.display = 'block';
      setTimeout(() => { c.style.display = 'none'; }, 1500);
    });
  }

  function _closeCreate() {
    _newKeyValue = '';
    document.getElementById('new-key-value').textContent = '';
    document.getElementById('create-key-modal').hidden = true;
  }

  async function rotate(id, name) {
    const ok = await Confirm.ask({ title: `Rotate key "${name}"?`, body: 'The old key will stop working immediately.', okLabel: 'Rotate', danger: true });
    if (!ok) return;
    const r = await AdminAuth.fetch(`/api/keys/${encodeURIComponent(id)}/rotate`, {
      method: 'POST',
    }, 'admin-keys');
    if (!r.ok) {
      Toast.danger('Rotate failed', `HTTP ${r.status}`);
      return;
    }
    const result = await r.json();
    _newKeyValue = result.key || '';
    document.getElementById('new-key-value').textContent = _newKeyValue;
    document.getElementById('create-key-form').hidden = true;
    document.getElementById('create-key-reveal').hidden = false;
    document.getElementById('new-key-confirm-copied').checked = false;
    document.getElementById('create-key-close-btn').disabled = true;
    document.getElementById('copy-confirm').style.display = 'none';
    document.getElementById('create-key-modal').hidden = false;
    load();
    refreshAudit();
  }

  async function revoke(id, name) {
    const ok = await Confirm.ask({ title: `Revoke key "${name}"?`, body: 'This cannot be undone via the UI.', okLabel: 'Revoke', danger: true });
    if (!ok) return;
    const r = await AdminAuth.fetch(`/api/keys/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }, 'admin-keys');
    if (!r.ok) {
      Toast.danger('Revoke failed', `HTTP ${r.status}`);
      return;
    }
    load();
    refreshAudit();
  }

  async function refreshAudit() {
    const host = document.getElementById('api-keys-audit');
    if (!host) return;
    const r = await AdminAuth.fetch('/api/keys/audit', {}, 'admin-keys');
    if (!r.ok) {
      host.innerHTML = `<div class="admin-modal-error" style="margin:0">Audit unavailable (HTTP ${r.status})</div>`;
      return;
    }
    const events = await r.json();
    if (!Array.isArray(events) || events.length === 0) {
      host.innerHTML = '<div style="color:var(--text-muted)">No admin actions recorded yet.</div>';
      return;
    }
    // Last 20, newest first.
    const recent = events.slice(-20).reverse();
    host.innerHTML = recent.map(e => `
      <div style="display:flex;gap:14px;padding:4px 0;border-bottom:1px dashed var(--border)">
        <span style="color:var(--text-muted);min-width:170px">${esc(new Date(e.ts).toLocaleString())}</span>
        <span style="color:var(--accent);min-width:90px">${esc(e.action)}</span>
        <span style="color:var(--text-dim)">${esc(e.name || '')}</span>
        <span style="color:var(--text-muted);font-family:var(--mono)">${esc(e.key_id)}</span>
      </div>
    `).join('');
  }

  // Auto-load when this admin panel is activated.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-keys') {
      load();
      refreshAudit();
    }
  });

  return { load, refresh, showCreate, rotate, revoke, refreshAudit,
           _toggleScope, _submitCreate, _copyKey, _closeCreate };
})();

// Delegated actions — key rows re-render on every load/rotate/revoke;
// scope chips re-render per showCreate(). Chips reuse their existing
// data-scope attr (aria-pressed templating unchanged).
Actions.click({
  'keys.rotate': el => ApiKeysPanel.rotate(el.dataset.keyId, el.dataset.keyName),
  'keys.revoke': el => ApiKeysPanel.revoke(el.dataset.keyId, el.dataset.keyName),
  'keys.scope':  el => ApiKeysPanel._toggleScope(el.dataset.scope, el)
});

// ── PluginsPanel ──────────────────────────────────────────────────────────

// ── SkillsPanel ───────────────────────────────────────────────────────────
// Flat view of every skill across every installed plugin. Lets the admin
// browse + filter (by plugin, by role) + inspect the markdown body, without
// needing to dig per-plugin. Auth-mirrors the Plugins panel: list view uses
// the anonymous /api/plugins GET (open since PR #43); no write actions yet.

// Tiny styles for the role pills, scoped to the skills admin panel.
(function () {
  const style = document.createElement('style');
  style.textContent = `
    .role-pill { display:inline-block; padding:1px 6px; margin-right:3px;
                 font-size:0.55rem; font-family:var(--mono);
                 border:1px solid var(--accent-dim); color:var(--accent);
                 border-radius:2px; letter-spacing:0.06em; text-transform:uppercase; }
    .role-pill-all { border-color:var(--text-muted); color:var(--text-muted); }
  `;
  document.head.appendChild(style);
})();

// ── CloudPanel ────────────────────────────────────────────────────────────
// Admin panel for external/frontier LLM provider configs. Mirrors the
// MCPPanel pattern: list + detail + register/edit modal. Writes hit
// /api/cloud-providers which require the master key; the GET list is
// open (returns redacted records — api_key never appears on the wire,
// just an `api_key_set` boolean).
window.CloudPanel = (function () {
  let _items = [];
  let _selectedId = null;
  let _editId = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    const list = document.getElementById('cloud-list');
    if (!list) return;
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">Loading…</div>';
    try {
      const r = await Net.call('/api/cloud-providers');
      if (!r.ok) {
        list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
        return;
      }
      _items = r.data;
      _render();
    } catch (e) {
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    }
  }

  function refresh() { load(); }

  function _render() {
    const list = document.getElementById('cloud-list');
    if (!list) return;
    if (!Array.isArray(_items) || _items.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.7rem">No cloud providers configured. Click <strong>+ Add Provider</strong> to register one.</div>';
      _renderDetailPlaceholder();
      return;
    }
    list.innerHTML = _items.map(p => `
      <button type="button" class="btn-unstyled plugin-card ${p.id === _selectedId ? 'selected' : ''}"
           style="width:100%" aria-pressed="${p.id === _selectedId}"
           data-action="cloud.select" data-id="${esc(p.id)}">
        <div class="plugin-card-title">
          <span class="plugin-status-pip ${p.enabled ? '' : 'error'}"></span>${esc(p.name || p.id)}
          <span style="color:var(--text-muted);font-size:0.66rem;margin-left:6px">${esc(p.kind || 'custom')}</span>
        </div>
        <div class="plugin-card-meta">
          ${p.api_key_set ? '<span style="color:var(--accent)">⚿ key set</span>' : '<span style="color:var(--warn)">no key</span>'}
          · ${(p.models || []).length} curated model${(p.models || []).length === 1 ? '' : 's'}
        </div>
        <div class="plugin-card-desc"><code style="color:var(--text-muted)">${esc(p.base_url || '')}</code></div>
      </button>
    `).join('');
    if (!_selectedId && _items.length) select(_items[0].id);
  }

  function _renderDetailPlaceholder() {
    const detail = document.getElementById('cloud-detail');
    const label = document.getElementById('cloud-detail-label');
    if (label) label.textContent = '// SELECT A PROVIDER';
    if (detail) detail.innerHTML = 'Select a provider to inspect its config or rotate its API key. Use <strong>+ Add Provider</strong> to register a new one.';
  }

  function select(id) {
    _selectedId = id;
    document.querySelectorAll('#cloud-list .plugin-card').forEach(c => c.classList.remove('selected'));
    const card = document.querySelector(`#cloud-list .plugin-card[data-id="${CSS.escape(id)}"]`);
    if (card) card.classList.add('selected');

    const p = _items.find(x => x.id === id);
    const detail = document.getElementById('cloud-detail');
    const label = document.getElementById('cloud-detail-label');
    if (!p || !detail) return;
    if (label) label.textContent = `// ${esc(p.id.toUpperCase())}`;

    const tagList = (p.tags || []).map(t => `<span class="role-pill">${esc(t)}</span>`).join(' ') || '<span style="color:var(--text-muted)">none</span>';
    const modelList = (p.models || []).map(m => `<code>${esc(m)}</code>`).join(', ') || '<span style="color:var(--text-muted)">(empty — will list from provider /v1/models on first use)</span>';
    detail.innerHTML = `
      <div style="font-size:0.74rem;display:grid;grid-template-columns:120px 1fr;gap:6px 14px;margin-bottom:14px">
        <div style="color:var(--text-muted)">Name</div><div>${esc(p.name)}</div>
        <div style="color:var(--text-muted)">Kind</div><div><code>${esc(p.kind)}</code></div>
        <div style="color:var(--text-muted)">Base URL</div><div><code>${esc(p.base_url)}</code></div>
        <div style="color:var(--text-muted)">API key</div><div>${p.api_key_set ? '<span style="color:var(--accent)">set ✓</span> (re-save with a new value to rotate)' : '<span style="color:var(--warn)">not set</span>'}</div>
        <div style="color:var(--text-muted)">Enabled</div><div>${p.enabled ? '<span style="color:var(--accent)">yes</span>' : '<span style="color:var(--warn)">no</span>'}</div>
        <div style="color:var(--text-muted)">Curated models</div><div>${modelList}</div>
        <div style="color:var(--text-muted)">Tags</div><div>${tagList}</div>
        <div style="color:var(--text-muted)">Description</div><div>${esc(p.description || '(none)')}</div>
      </div>
      <div class="admin-modal-actions" style="justify-content:flex-end">
        <button type="button" class="admin-modal-btn" data-action="cloud.edit" data-id="${esc(p.id)}">Edit</button>
        <button type="button" class="admin-modal-btn" style="color:var(--danger);border-color:var(--danger-dim)" data-action="cloud.delete" data-id="${esc(p.id)}">Delete</button>
      </div>
    `;
  }

  function showCreate() {
    _editId = null;
    _resetModal();
    document.getElementById('cloud-edit-title').textContent = 'Add cloud provider';
    document.getElementById('cloud-edit-modal').hidden = false;
    setTimeout(() => document.getElementById('cloud-edit-id').focus(), 0);
  }

  function showEdit(id) {
    const p = _items.find(x => x.id === id);
    if (!p) return;
    _editId = id;
    _resetModal();
    document.getElementById('cloud-edit-title').textContent = `Edit ${p.id}`;
    document.getElementById('cloud-edit-id').value = p.id;
    document.getElementById('cloud-edit-id').disabled = true; // ID is immutable
    document.getElementById('cloud-edit-name').value = p.name || '';
    document.getElementById('cloud-edit-kind').value = p.kind || 'custom';
    document.getElementById('cloud-edit-base-url').value = p.base_url || '';
    document.getElementById('cloud-edit-desc').value = p.description || '';
    document.getElementById('cloud-edit-models').value = (p.models || []).join(', ');
    document.getElementById('cloud-edit-tags').value = (p.tags || []).join(', ');
    document.getElementById('cloud-edit-enabled').checked = p.enabled !== false;
    document.getElementById('cloud-edit-modal').hidden = false;
    setTimeout(() => document.getElementById('cloud-edit-api-key').focus(), 0);
  }

  function _resetModal() {
    ['cloud-edit-id','cloud-edit-name','cloud-edit-base-url','cloud-edit-api-key',
     'cloud-edit-desc','cloud-edit-models','cloud-edit-tags']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('cloud-edit-id').disabled = false;
    document.getElementById('cloud-edit-kind').value = 'openai';
    document.getElementById('cloud-edit-enabled').checked = true;
    document.getElementById('cloud-edit-error').hidden = true;
  }

  function _closeModal() {
    document.getElementById('cloud-edit-modal').hidden = true;
    _editId = null;
  }

  async function _submit() {
    const errBox = document.getElementById('cloud-edit-error');
    errBox.hidden = true;
    const id = document.getElementById('cloud-edit-id').value.trim();
    const name = document.getElementById('cloud-edit-name').value.trim();
    const kind = document.getElementById('cloud-edit-kind').value;
    const baseUrl = document.getElementById('cloud-edit-base-url').value.trim();
    const apiKey = document.getElementById('cloud-edit-api-key').value;
    const description = document.getElementById('cloud-edit-desc').value.trim();
    const modelsRaw = document.getElementById('cloud-edit-models').value.trim();
    const tagsRaw = document.getElementById('cloud-edit-tags').value.trim();
    const enabled = document.getElementById('cloud-edit-enabled').checked;

    if (!id) { errBox.hidden = false; errBox.textContent = 'ID is required.'; return; }
    if (!name) { errBox.hidden = false; errBox.textContent = 'Display name is required.'; return; }
    if (!baseUrl) { errBox.hidden = false; errBox.textContent = 'Base URL is required.'; return; }
    if (!/^[A-Za-z0-9_-]+$/.test(id)) {
      errBox.hidden = false;
      errBox.textContent = "ID can only contain letters, digits, '_' and '-'.";
      return;
    }

    const body = {
      name, kind, base_url: baseUrl, description, enabled,
      models: modelsRaw ? modelsRaw.split(',').map(s => s.trim()).filter(Boolean) : [],
      tags: tagsRaw ? tagsRaw.split(',').map(s => s.trim()).filter(Boolean) : [],
    };
    if (apiKey) body.api_key = apiKey;

    try {
      let r;
      if (_editId) {
        r = await AdminAuth.fetch(`/api/cloud-providers/${encodeURIComponent(_editId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }, 'admin-cloud');
      } else {
        body.id = id;
        r = await AdminAuth.fetch('/api/cloud-providers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }, 'admin-cloud');
      }
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const j = await r.json(); detail = j.detail || detail; } catch (e) {}
        errBox.hidden = false;
        errBox.textContent = detail;
        return;
      }
      _closeModal();
      _selectedId = id;
      await load();
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = e.message;
    }
  }

  async function del(id) {
    const ok = await Confirm.ask({ title: 'Delete cloud provider', body: `Delete cloud provider '${id}'?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    const r = await AdminAuth.fetch(`/api/cloud-providers/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }, 'admin-cloud');
    if (!r.ok) {
      Toast.danger('Delete failed', `HTTP ${r.status}`);
      return;
    }
    if (_selectedId === id) _selectedId = null;
    await load();
  }

  // Hot-load whenever the Cloud Models admin panel becomes active.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-cloud') load();
  });

  // Delegated actions — provider rows + detail buttons re-render per
  // load/select.
  Actions.click({
    'cloud.select': el => select(el.dataset.id),
    'cloud.edit':   el => showEdit(el.dataset.id),
    'cloud.delete': el => del(el.dataset.id)
  });

  return { load, refresh, select, showCreate, showEdit, del, _closeModal, _submit };
})();

// ── ExportsPanel ──────────────────────────────────────────────────────────
window.ExportsPanel = (function () {
  let _selected = new Set();
  let _items = [];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    const list = document.getElementById('exports-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';
    // Exports endpoint is not master-key gated today, but we still attach the
    // header for future-proofing (cheap, harmless, consistent with other admin panels).
    const r = await Net.call('/api/exports', { init: { headers: AdminAuth.authHeaders() } });
    if (!r.ok) {
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
      return;
    }
    const data = r.data;
    _items = data.exports || [];
    if (!_items.length) {
      list.innerHTML = '<div style="color:var(--text-muted);padding:14px 0">No exports yet — use "Export session" from the Chat tab.</div>';
      _refreshBulkBar();
      return;
    }
    list.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;font-size:0.66rem;color:var(--text-dim);margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid var(--border)">
        <input type="checkbox" id="exports-select-all" data-action="exports.select-all">
        <span>Select all</span>
      </div>
      ${_items.map(rowHtml).join('')}
    `;
    _refreshBulkBar();
  }

  function rowHtml(e) {
    const kb = (e.size / 1024).toFixed(1);
    const date = new Date(e.modified * 1000).toLocaleString();
    const checked = _selected.has(e.filename) ? 'checked' : '';
    return `
      <div class="export-row" id="export-row-${esc(e.filename)}" data-filename="${esc(e.filename)}" style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
        <input type="checkbox" data-filename="${esc(e.filename)}" ${checked}
               data-action="exports.toggle" style="margin-top:3px">
        <div style="flex:1;min-width:0">
          <div style="font-size:0.8rem;color:var(--text);font-weight:500">${esc(e.filename)}</div>
          <div style="font-size:0.66rem;color:var(--text-dim);margin-top:2px">${date} · ${kb} KB</div>
          <div style="font-size:0.7rem;color:var(--text-muted);margin-top:3px;white-space:pre-wrap;max-height:48px;overflow:hidden">${esc((e.preview || '').trim())}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;align-self:flex-start">
          <button class="action-btn small" data-action="exports.view">View</button>
          <button class="action-btn small" data-action="exports.download">Download</button>
          <button class="action-btn small danger" data-action="exports.delete">Delete</button>
        </div>
      </div>
    `;
  }

  function _toggle(name, on) {
    if (on) _selected.add(name); else _selected.delete(name);
    _refreshBulkBar();
  }

  function _toggleSelectAll(on) {
    _selected = on ? new Set(_items.map(e => e.filename)) : new Set();
    document.querySelectorAll('#exports-list input[type=checkbox][data-filename]')
      .forEach(c => { c.checked = on; });
    _refreshBulkBar();
  }

  function _refreshBulkBar() {
    const bar = document.getElementById('exports-bulk-bar');
    if (!bar) return;
    const count = _selected.size;
    bar.hidden = count === 0;
    document.getElementById('exports-selected-count').textContent = count;
  }

  async function view(filename) {
    // expectJson:false — body is raw markdown, read it as text from the response.
    const r = await Net.call('/api/exports/' + encodeURIComponent(filename), { expectJson: false, init: { headers: AdminAuth.authHeaders() } });
    if (!r.ok) { Toast.warn('Export not found'); return; }
    const text = await r.response.text();
    document.getElementById('export-view-title').textContent = filename;
    document.getElementById('export-view-body').innerHTML = renderMarkdown(text);
    document.getElementById('export-view-modal').hidden = false;
  }

  function _closeView() {
    document.getElementById('export-view-modal').hidden = true;
  }

  function download(filename) {
    const url = '/api/exports/' + encodeURIComponent(filename);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function deleteOne(filename) {
    const ok = await Confirm.ask({ title: 'Delete export', body: `Delete "${filename}"?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    const r = await Net.call('/api/exports/' + encodeURIComponent(filename), {
      retries: 0,
      init: { method: 'DELETE', headers: AdminAuth.authHeaders() },
    });
    if (!r.ok) { Toast.danger('Delete failed', `HTTP ${r.status}`); return; }
    _selected.delete(filename);
    load();
  }

  function downloadZip() {
    if (_selected.size === 0) return;
    const names = Array.from(_selected).join(',');
    const url = '/api/exports/zip?names=' + encodeURIComponent(names);
    // We can't easily set Authorization on a window navigation, but the
    // exports zip endpoint is not master-key gated. Use anchor click.
    const a = document.createElement('a');
    a.href = url;
    a.download = 'enclave-exports.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function bulkDelete() {
    const count = _selected.size;
    if (count === 0) return;
    const ok = await Confirm.ask({ title: 'Delete exports', body: `Delete ${count} export${count === 1 ? '' : 's'}?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    // Fire deletes in parallel.
    const names = Array.from(_selected);
    const results = await Promise.all(names.map(n =>
      Net.call('/api/exports/' + encodeURIComponent(n), {
        retries: 0,
        init: { method: 'DELETE', headers: AdminAuth.authHeaders() },
      })
    ));
    const failed = names.filter((_, i) => !results[i].ok);
    if (failed.length) Toast.danger('Delete failed', failed.join(', '));
    _selected.clear();
    load();
  }

  function refresh() { load(); }

  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-exports') load();
  });

  // Esc closes the view modal.
  document.addEventListener('keydown', e => {
    const m = document.getElementById('export-view-modal');
    if (m && !m.hidden && e.key === 'Escape') _closeView();
  });

  // Delegated actions — rows re-render on every load(). Row buttons
  // resolve the filename from the row's data-filename; the checkboxes
  // read el.checked directly (change event), same as the old inline
  // this.checked args.
  const _filenameOf = el => {
    const host = el.closest('[data-filename]');
    return host ? host.dataset.filename : '';
  };
  Actions.click({
    'exports.view':     el => view(_filenameOf(el)),
    'exports.download': el => download(_filenameOf(el)),
    'exports.delete':   el => deleteOne(_filenameOf(el))
  });
  Actions.change({
    'exports.toggle':     el => _toggle(el.dataset.filename, el.checked),
    'exports.select-all': el => _toggleSelectAll(el.checked)
  });

  return { load, refresh, view, download, deleteOne, downloadZip, bulkDelete,
           _toggle, _toggleSelectAll, _closeView };
})();

/* ══════════════════════════════════════════════════════════════════
   COMPOSER VIEW — the Composer is now the Dashboard. This module
   bootstraps the drawflow canvas, palette, workbenches, agent chat
   wiring, and the import/export-bundle plumbing.
   ══════════════════════════════════════════════════════════════════ */
const ComposerView = (function () {
  let _booted = false;

  function init() {
    // Boot the drawflow editor + palette regardless of whether the user
    // had previously visited the legacy Workflows tab.
    try { dfInitEditor(); dfInitPalette(); } catch (e) { console.warn(e); }
    try { ComposerSplit.init(); } catch (_) {}
    updateCanvasEmptyState();
    // Show the begin/end boundary immediately, even on an empty canvas.
    if (typeof dfScheduleAnchorRefresh === 'function') dfScheduleAnchorRefresh();
    if (_booted) {
      // Already initialised — workbenches refresh quickly to pick up
      // server-side changes (newly registered MCP, etc).
      loadWorkbenches();
      return;
    }
    _booted = true;
    loadAgentsForSelector();
    loadWorkbenches();
    composerSwitchBench('steps');
    if (typeof Projects !== 'undefined') Projects.load();
  }

  function updateCanvasEmptyState() {
    const panel = document.querySelector('.composer-canvas-panel');
    if (!panel) return;
    const hasNodes = Object.keys(dfNodeData || {}).length > 0;
    panel.classList.toggle('has-nodes', hasNodes);
    // Spine follows the canvas: dormant ghost when empty, live when primed.
    // During a BootSequence reveal we hold it primed (window._bsPriming) so
    // composerNewWorkflow()'s transient 0-node window can't hide the canvas
    // mid-build — drawflow must lay nodes into a visible, sized canvas.
    if (typeof ComposerSplit !== 'undefined') {
      try { ComposerSplit.setSpinePrimed(window._bsPriming ? true : hasNodes); } catch (_) {}
    }
  }

  return { init, updateCanvasEmptyState };
})();

// The dashboard tab is the *default-active* tab on page load (see the
// `tab-btn active` on `data-tab="dashboard"` near the top of the body).
// switchTab() is what wires ComposerView.init() — but switchTab is only
// fired when the user *clicks* a tab. On first paint nobody clicks, so
// without this hook the composer renders its static template (palette
// items as "Loading...", empty canvas) and the JS never runs the fetches
// that would populate it. Boot it here once DOM is ready.
document.addEventListener('DOMContentLoaded', () => {
  const dashboardTab = document.getElementById('tab-dashboard');
  if (dashboardTab && dashboardTab.classList.contains('active')) {
    try { ComposerView.init(); } catch (e) { console.warn('ComposerView.init failed:', e); }
  }
});

/* ── Workbench tab switcher ─────────────────────────────────────── */
function composerSwitchBench(bench, el) {
  document.querySelectorAll('.workbench-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.bench === bench);
  });
  document.querySelectorAll('.workbench-pane').forEach(p => {
    p.hidden = (p.id !== 'bench-' + bench);
  });
}

/* ── Workbench loaders ──────────────────────────────────────────── */
async function loadWorkbenches() {
  // Auth is handled globally by the monkey-patched window.fetch (installed
  // alongside the Auth module). Each pane fails independently so one
  // failing endpoint doesn't blank the whole sidebar.

  // Plugins (powers both Skills and Plugins panes)
  try {
    const r = await Net.call('/api/plugins');
    if (r.ok) {
      const plugins = r.data;
      renderSkillsWorkbench(plugins);
      renderPluginsWorkbench(plugins);
    } else {
      renderWorkbenchError('bench-skills-list', `HTTP ${r.status}`);
      renderWorkbenchError('bench-plugins-list', `HTTP ${r.status}`);
    }
  } catch (e) {
    renderWorkbenchError('bench-skills-list', e.message);
    renderWorkbenchError('bench-plugins-list', e.message);
  }

  // MCP servers
  try {
    const r = await Net.call('/api/mcp/servers');
    if (r.ok) {
      const servers = r.data;
      renderMcpsWorkbench(servers);
    } else {
      renderWorkbenchError('bench-mcps-list', `HTTP ${r.status}`);
    }
  } catch (e) {
    renderWorkbenchError('bench-mcps-list', e.message);
  }

  // Agents — the agent library. Drag-into-canvas spawns an AgentStep
  // pre-filled with the agent's role + model + system_prompt so the
  // step starts as a faithful clone of the agent.
  try {
    const r = await Net.call('/api/agents');
    if (r.ok) {
      const agents = r.data;
      renderAgentsWorkbench(agents);
    } else {
      renderWorkbenchError('bench-agents-list', `HTTP ${r.status}`);
    }
  } catch (e) {
    renderWorkbenchError('bench-agents-list', e.message);
  }
}

// ── AgentIcons ─────────────────────────────────────────────────────────────
// Persona-keyed SVG icon registry. Each icon is 20x20, stroke-only, uses
// currentColor so theme tokens (--cyan / --amber / etc) flow through.
// The card resolves a persona key from agent.icon → agent.role → name/id
// keyword scan, then falls back to a generic "agent" glyph.
const AgentIcons = (() => {
  const _S = (paths) =>
    `<svg viewBox="0 0 24 24" width="20" height="20" fill="none"
          stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
          stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

  // Each entry is a short, distinct glyph for a recognisable step persona.
  const ICONS = {
    // Inspection / interrogation
    analyzer:   _S('<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.3-4.3"/><path d="M8 11h6M11 8v6"/>'),
    search:     _S('<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.3-4.3"/>'),
    // Sorting / decision
    classifier: _S('<path d="M4 6h16M7 12h10M10 18h4"/>'),
    router:     _S('<circle cx="6" cy="12" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 12l8-6M8 12l8 6"/>'),
    // Building / writing
    writer:     _S('<path d="M5 19l4-1 10-10-3-3L6 15l-1 4z"/><path d="M14 6l3 3"/>'),
    composer:   _S('<path d="M4 5h16M4 12h10M4 19h16"/><path d="M18 9v6M21 12h-6"/>'),
    // Validation / review
    validator:  _S('<path d="M12 3l8 3v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/>'),
    reviewer:   _S('<circle cx="12" cy="12" r="3.2"/><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>'),
    // Retrieval / knowledge
    retriever:  _S('<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"/><path d="M5 11.5v6c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-6"/>'),
    library:    _S('<rect x="4" y="4" width="4" height="16"/><rect x="10" y="4" width="4" height="16"/><path d="M17 4l3 16"/>'),
    // Planning / orchestration
    planner:    _S('<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M8 6h4a4 4 0 014 4v0M8 18h4a4 4 0 004-4v0"/>'),
    coordinator:_S('<circle cx="12" cy="12" r="3"/><circle cx="12" cy="4" r="1.6"/><circle cx="12" cy="20" r="1.6"/><circle cx="4" cy="12" r="1.6"/><circle cx="20" cy="12" r="1.6"/><path d="M12 7v2M12 15v2M7 12h2M15 12h2"/>'),
    // Domain
    security:   _S('<path d="M12 3l8 3v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6l8-3z"/>'),
    data:       _S('<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13"/>'),
    coder:      _S('<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 6l-4 12"/>'),
    reasoning:  _S('<path d="M8 14V8a4 4 0 018 0v6"/><path d="M6 14a3 3 0 003 3h6a3 3 0 003-3"/><path d="M9 17v2M15 17v2M12 5V3"/>'),
    fast:       _S('<path d="M13 3l-8 11h6l-1 7 8-11h-6l1-7z"/>'),
    general:    _S('<circle cx="12" cy="8" r="3"/><path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6"/>'),
    // Capability glyphs — used by the workbench Skills / Plugins / MCPs
    // panes (and the canvas badges that attach those capabilities to a
    // step). Same currentColor + stroke discipline as the agent icons.
    skill:      _S('<path d="M12 3l2.4 5 5.6.8-4 3.9.9 5.5L12 15.6 7.1 18.2 8 12.7l-4-3.9 5.6-.8L12 3z"/>'),
    plugin:     _S('<path d="M9 3v4H5v6h4v4M15 3v4h4v6h-4v4M9 7h6M9 17h6"/>'),
    mcp:        _S('<rect x="3" y="5" width="18" height="6" rx="1"/><rect x="3" y="13" width="18" height="6" rx="1"/><circle cx="7" cy="8" r="0.8" fill="currentColor"/><circle cx="7" cy="16" r="0.8" fill="currentColor"/><path d="M11 8h7M11 16h7"/>'),
    tool:       _S('<path d="M14.7 5.3a4 4 0 00-5.3 5.3l-6 6 2.7 2.7 6-6a4 4 0 005.3-5.3l-2 2-1.4-1.4 2-2z"/>'),
    server:     'mcp',
    extension:  'plugin',
    // Aliases that map common YAML keywords from older configs.
    'scan-eye': 'reviewer',
    book:       'library',
    magnify:    'search',
    curator:    'library',
    chart:      _S('<path d="M4 20V8M10 20V4M16 20v-8M22 20H2"/>'),
    pen:        'writer',
    brain:      'reasoning',
    code:       'coder',
    shield:     'security',
  };

  // Persona keywords that map to one of the canonical icons. The scan
  // runs against agent.role, agent.id, agent.name and the agent
  // description (lowercased), so any agent gets a sensible glyph.
  const KEYWORDS = [
    [/analy[sz]|inspect|classif|triage/, 'analyzer'],
    [/class|categor|label|tag/,           'classifier'],
    [/rout|dispatch|switch/,              'router'],
    [/write|draft|compose|author/,        'writer'],
    [/synth|aggregate|consolidat/,        'composer'],
    [/valid|lint|verify|gate/,            'validator'],
    [/review|critic|audit/,               'reviewer'],
    [/retriev|search|navigator|find/,     'retriever'],
    [/library|snippet|catalog|index/,     'library'],
    [/plan|outline|decompose/,            'planner'],
    [/orchestrat|coordinator|conductor/,  'coordinator'],
    [/security|threat|risk|detect/,       'security'],
    [/schema|xdm|data/,                   'data'],
    [/code|coder|rule.engineer/,          'coder'],
    [/reason|reasoner|think|brain/,       'reasoning'],
    [/fast|quick|lite/,                   'fast'],
  ];

  function resolve(agent) {
    if (!agent) return 'general';
    // 1. Explicit icon keyword (allowing aliases via string-redirect)
    const ic = (agent.icon || '').toLowerCase().trim();
    if (ic && ICONS[ic]) {
      return typeof ICONS[ic] === 'string' ? ICONS[ic] : ic;
    }
    // 2. Keyword scan across persona-flavored fields
    const hay = [agent.id, agent.name, agent.role, agent.description]
      .filter(Boolean).join(' ').toLowerCase();
    for (const [re, key] of KEYWORDS) {
      if (re.test(hay)) return key;
    }
    // 3. Last-resort: role → icon mapping
    const role = (agent.role || '').toLowerCase();
    if (ICONS[role]) return role;
    return 'general';
  }

  function svg(keyOrAgent) {
    const key = typeof keyOrAgent === 'string' ? keyOrAgent : resolve(keyOrAgent);
    let entry = ICONS[key] || ICONS.general;
    // Chase one alias indirection (e.g. shield → security)
    if (typeof entry === 'string' && ICONS[entry]) entry = ICONS[entry];
    return entry;
  }

  // Each persona gets a stable theme color so glyphs are recognisable
  // at a glance. Falls back to --accent for unknowns.
  const TONES = {
    analyzer:    'cyan',
    classifier:  'amber',
    router:      'purple',
    writer:      'cyan',
    composer:    'cyan',
    validator:   'green',
    reviewer:    'amber',
    retriever:   'purple',
    library:     'purple',
    planner:     'cyan',
    coordinator: 'cyan',
    security:    'amber',
    data:        'purple',
    coder:       'cyan',
    reasoning:   'cyan',
    fast:        'amber',
    general:     'accent',
    // Capability tones — match the bucket colors used by graph/run-state
    // overlays so the operator builds a stable association.
    skill:       'amber',
    plugin:      'green',
    mcp:         'purple',
    tool:        'cyan',
    server:      'purple',
    extension:   'green',
  };

  function tone(keyOrAgent) {
    const key = typeof keyOrAgent === 'string' ? keyOrAgent : resolve(keyOrAgent);
    return TONES[key] || 'accent';
  }

  return { svg, resolve, tone };
})();
window.AgentIcons = AgentIcons;

function renderAgentsWorkbench(agents) {
  const el = document.getElementById('bench-agents-list');
  if (!el) return;
  if (!agents || !agents.length) {
    el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">No agents yet. Drop a YAML into agents/&lt;id&gt;.yaml.</div>';
    return;
  }
  el.innerHTML = agents.map(a => {
    const persona = AgentIcons.resolve(a);
    const icon = AgentIcons.svg(persona);
    const tone = AgentIcons.tone(persona);
    const role = a.role || 'general';
    // Subtitle: prefer a one-line function summary; fall back to role.
    const subtitle = (a.description || '').split('\n')[0].trim().slice(0, 70);
    // Click-to-add fallback: HTML5 drag is finicky across zoom states
    // + macOS gestures; a plain click on the card spawns the agent at
    // the center of the canvas. Drag still works when it works; click
    // is the always-reliable path. The dblclick prevents an accidental
    // double-spawn on rapid clicks.
    return `<div class="workbench-item agent-card" draggable="true" role="button" tabindex="0"
       aria-label="Add agent ${esc(a.name || a.id)} to canvas"
       data-action="bench.add-agent" data-agent-id="${esc(a.id)}"
       data-drag-mime="application/df-agent" data-drag-value="${esc(a.id)}"
       title="Click to add (or drag onto the canvas)">
      <div class="agent-card-head">
        <span class="agent-card-icon tone-${esc(tone)}" data-persona="${esc(persona)}">${icon}</span>
        <div class="agent-card-titleblock">
          <div class="agent-card-title">${esc(a.name || a.id)}</div>
          <div class="agent-card-subtitle">${esc(subtitle || role)}</div>
        </div>
        <span class="workbench-item-pill">${esc(role)}</span>
      </div>
      <div class="workbench-tool-row">
        <span class="workbench-tool-dot"></span>
        <code style="color:var(--accent)">${esc(a.id)}</code>
        ${a.model ? `<span style="color:var(--text-muted);flex:1;text-align:right">${esc(a.model)}</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

function renderWorkbenchAuthHint(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">Sign in via Admin to load this workbench.</div>';
}
function renderWorkbenchError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<div class="model-empty" style="color:var(--danger);font-size:0.62rem">${esc(msg || 'load failed')}</div>`;
}

// Workbench renderers — Skills / Plugins / MCPs.
// All three share the icon-block card grammar used by .agent-card so
// the composer's left rail reads as one consistent surface.

function _capCard(opts) {
  // opts: { iconKey, title, subtitle, pill, pillKind, drag, descId, body }
  // - drag: { mime, value } to make the card draggable, or null
  // - pillKind: '', 'warn', 'dim'
  const iconSvg = (window.AgentIcons ? AgentIcons.svg(opts.iconKey) : '');
  const tone    = (window.AgentIcons ? AgentIcons.tone(opts.iconKey) : 'accent');
  const draggable = opts.drag
    ? `draggable="true" data-action="bench.drag" data-drag-mime="${esc(opts.drag.mime)}" data-drag-value="${esc(opts.drag.value)}"`
    : '';
  const pillCls = opts.pillKind ? `workbench-item-pill ${opts.pillKind}` : 'workbench-item-pill';
  return `<div class="workbench-item agent-card cap-card cap-${esc(opts.iconKey)}" ${draggable} ${opts.title ? `title="${esc(opts.titleAttr || opts.title)}"` : ''}>
    <div class="agent-card-head">
      <span class="agent-card-icon tone-${esc(tone)}" data-cap="${esc(opts.iconKey)}">${iconSvg}</span>
      <div class="agent-card-titleblock">
        <div class="agent-card-title">${esc(opts.title)}</div>
        <div class="agent-card-subtitle">${esc(opts.subtitle || '')}</div>
      </div>
      ${opts.pill ? `<span class="${pillCls}">${esc(opts.pill)}</span>` : ''}
    </div>
    ${opts.body || ''}
  </div>`;
}

function renderSkillsWorkbench(plugins) {
  const el = document.getElementById('bench-skills-list');
  if (!el) return;
  const items = [];
  (plugins || []).forEach(p => {
    (p.skills || []).forEach(s => items.push({ plugin: p.id, skill: s }));
  });
  if (!items.length) {
    el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">No skills yet. Drop a skill .md file into plugins/&lt;plugin&gt;/skills/.</div>';
    return;
  }
  el.innerHTML = items.map(({ plugin, skill }) => {
    const triggers = (skill.triggers || []).map(t => t.keyword).filter(Boolean).slice(0, 3).join(', ');
    return _capCard({
      iconKey: 'skill',
      title: skill.name || skill.id,
      subtitle: skill.description || '',
      pill: 'skill',
      drag: { mime: 'application/df-skill', value: `${plugin}::${skill.id}` },
      titleAttr: 'Drag onto a step to attach this skill manually',
      body: `<div class="cap-card-foot">
        <code class="cap-card-id">${esc(plugin)}::${esc(skill.id)}</code>
        ${triggers ? `<span class="cap-card-meta">triggers · ${esc(triggers)}</span>` : ''}
      </div>`,
    });
  }).join('');
}

function renderPluginsWorkbench(plugins) {
  const el = document.getElementById('bench-plugins-list');
  if (!el) return;
  if (!plugins || !plugins.length) {
    el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">No plugins installed. Add one under plugins/&lt;name&gt;/plugin.yaml.</div>';
    return;
  }
  el.innerHTML = plugins.map(p => {
    const toolCount = (p.tools || []).length;
    const toolRows = (p.tools || []).map(t => `
      <div class="cap-tool-row" draggable="true"
           data-action="bench.drag" data-drag-mime="application/df-tool" data-drag-value="${esc(p.id)}__${esc(t.id)}"
           title="Drag onto a step to attach this tool">
        <span class="cap-tool-icon">${window.AgentIcons ? AgentIcons.svg('tool') : ''}</span>
        <code class="cap-tool-id">${esc(p.id)}__${esc(t.id)}</code>
        <span class="cap-tool-desc">${esc((t.description || '').slice(0, 60))}</span>
      </div>`).join('');
    return _capCard({
      iconKey: 'plugin',
      title: p.name || p.id,
      subtitle: p.description || '',
      pill: `v${p.version || '0.0'}`,
      pillKind: 'dim',
      drag: null,
      body: toolRows
        ? `<div class="cap-card-tools">
            <div class="cap-card-tools-head">tools · <span style="color:var(--text)">${toolCount}</span></div>
            ${toolRows}
          </div>`
        : `<div class="cap-card-foot"><span class="cap-card-meta">no tools registered</span></div>`,
    });
  }).join('');
}

function renderMcpsWorkbench(servers) {
  const el = document.getElementById('bench-mcps-list');
  if (!el) return;
  if (!servers || !servers.length) {
    el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">No MCP servers yet. Register one under Admin → MCP Servers.</div>';
    return;
  }
  el.innerHTML = servers.map(s => {
    const toolCount = (s.tools || []).length;
    const toolRows = toolCount === 0
      ? `<div class="cap-card-foot"><span class="cap-card-meta">no tools cached — test in Admin → MCP</span></div>`
      : `<div class="cap-card-tools">
          <div class="cap-card-tools-head">tools · <span style="color:var(--text)">${toolCount}</span></div>
          ${(s.tools || []).map(t => `
            <div class="cap-tool-row" draggable="true"
                 data-action="bench.drag" data-drag-mime="application/df-mcp" data-drag-value="${esc(s.id)}::${esc(t.name)}"
                 title="Drag onto a step to invoke this MCP tool">
              <span class="cap-tool-icon">${window.AgentIcons ? AgentIcons.svg('tool') : ''}</span>
              <code class="cap-tool-id">mcp__${esc(s.id)}__${esc(t.name)}</code>
            </div>`).join('')}
        </div>`;
    return _capCard({
      iconKey: 'mcp',
      title: s.name || s.id,
      subtitle: s.description || '',
      pill: s.transport || 'mcp',
      pillKind: s.enabled ? '' : 'warn',
      body: toolRows,
    });
  }).join('');
}

// Delegated actions for the composer benches (agents / skills / plugins /
// MCP rails). One generic dragstart reads data-drag-mime/data-drag-value;
// agent cards also add-on-click (with keyboard parity for the role=button
// div) and swallow dblclick so a rapid double-click can't mis-select text.
(function () {
  const benchDrag = (el, e) => {
    e.dataTransfer.setData(el.dataset.dragMime, el.dataset.dragValue);
  };
  Actions.on('dragstart', {
    'bench.drag': benchDrag,
    'bench.add-agent': benchDrag  // agent cards: click adds, drag still works
  });
  Actions.click({
    'bench.add-agent': el => composerAddAgentAtCenter(el.dataset.agentId)
  });
  Actions.on('keydown', {
    'bench.add-agent': (el, e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      composerAddAgentAtCenter(el.dataset.agentId);
    }
  });
  Actions.on('dblclick', {
    'bench.add-agent': (el, e) => { e.preventDefault(); }
  });
})();

// ── Skills Discover ──────────────────────────────────────────────────────
// Skills Lab counterpart to the Models tab's HuggingFace discover. Backed
// by the curated catalog at /api/skills/discover; install drops the skill
// body into a chosen plugin and registers it in the manifest.
const SkillsDiscover = (function () {
  let _data = null;
  let _loaded = false;
  // View mode — 'list' is the original dense card view, 'icons' is the
  // icon-explorer grid that leads with persona glyphs.
  let _view = 'list';

  async function load(force) {
    if (_loaded && !force) { render(); return; }
    const grid = document.getElementById('skills-discover-grid');
    if (grid) grid.innerHTML = '<div class="model-empty">Loading discoverable skills…</div>';
    try {
      _data = await Net.getJson('/api/skills/discover');
      _loaded = true;
      _populateCats();
      _setMeta(`${_data.count || 0} skills · updated ${_data.updated || '—'}`);
      render();
    } catch (e) {
      _setMeta('failed');
      if (grid) grid.innerHTML = `<div class="model-empty" style="color:var(--red)">Discover failed: ${esc(e.message)}</div>`;
    }
  }

  function _setMeta(text) {
    const m = document.getElementById('skills-discover-meta');
    if (m) m.textContent = text;
  }

  function _populateCats() {
    const sel = document.getElementById('skills-discover-cat');
    if (!sel || !_data) return;
    const cur = sel.value;
    const cats = Array.from(new Set((_data.skills || []).map(s => s.category).filter(Boolean))).sort();
    sel.innerHTML = '<option value="">All categories</option>' +
      cats.map(c => `<option value="${esc(c)}"${cur === c ? ' selected' : ''}>${esc(c)}</option>`).join('');
  }

  function render() {
    const grid = document.getElementById('skills-discover-grid');
    if (!grid || !_data) return;
    const q   = (document.getElementById('skills-discover-search')?.value || '').toLowerCase();
    const cat = (document.getElementById('skills-discover-cat')?.value || '');
    const items = (_data.skills || []).filter(s => {
      if (cat && s.category !== cat) return false;
      if (!q) return true;
      const hay = [s.id, s.name, s.description, ...(s.tags || []), ...(s.triggers || [])]
        .filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
    if (!items.length) {
      grid.innerHTML = '<div class="model-empty">No skills match the filter.</div>';
      return;
    }
    // View-mode router. Both renderers know how to handle the
    // already-filtered item list.
    grid.classList.toggle('view-icons', _view === 'icons');
    grid.innerHTML = _view === 'icons'
      ? _renderIconExplorer(items)
      : items.map(_card).join('');
  }

  function _card(s) {
    // Use the skill's declared persona for the icon block so the
    // visual carries over to wherever the skill ends up installed.
    const persona = s.persona || (window.AgentIcons ? AgentIcons.resolve({ name: s.name, description: s.description }) : 'skill');
    const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'amber');
    const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const triggers = (s.triggers || []).slice(0, 3).map(t => `<span class="cap-card-meta">${esc(t)}</span>`).join(' · ');
    // Source badge — remote marketplace entries are visually distinct.
    const sourceChip = (s.marketplace || s.source === 'remote')
      ? `<span class="skill-disc-chip marketplace" title="From a remote marketplace catalog">marketplace</span>`
      : '';
    const stateChip = sourceChip + (s.installed
      ? `<span class="skill-disc-chip installed" title="Already installed in ${esc((s.installed_in || []).join(', '))}">installed</span>`
      : (s.has_body
          ? `<span class="skill-disc-chip available">install</span>`
          : `<span class="skill-disc-chip bundled" title="Ships pre-installed with the platform">bundled</span>`));
    // Same .action-btn sizing/vocabulary as the Models catalog cards so the
    // install/remove experience reads identically across the product.
    const action = s.installed
      ? `<button class="action-btn sm danger" data-action="sdisc.uninstall">Remove</button>`
      : (s.has_body
          ? `<button class="action-btn sm accent" data-action="sdisc.install">Install</button>`
          : '');
    return `<div class="workbench-item agent-card cap-card skill-disc-card cap-skill" data-skill-id="${esc(s.id)}">
      <button type="button" class="btn-unstyled agent-card-head" title="Open detail" data-action="sdisc.detail">
        <span class="agent-card-icon tone-${esc(tone)}">${iconSvg}</span>
        <div class="agent-card-titleblock">
          <div class="agent-card-title">${esc(s.name)}</div>
          <div class="agent-card-subtitle">${esc(s.description || '')}</div>
        </div>
        ${stateChip}
      </button>
      <div class="cap-card-foot">
        <code class="cap-card-id">${esc(s.id)}</code>
        ${triggers ? `<span class="cap-card-meta">${triggers}</span>` : ''}
      </div>
      ${action ? `<div class="skill-disc-actions">${action}</div>` : ''}
    </div>`;
  }

  // Install → asks for the target plugin id. We default to general-skills
  // since it's the catch-all bundle, but the operator can override.
  async function install(skillId) {
    const plugins = await _availablePlugins();
    const def = plugins.includes('general-skills') ? 'general-skills' : (plugins[0] || 'general-skills');
    const target = prompt(`Install '${skillId}' into which plugin?`, def);
    if (!target) return;
    // retries:0 — install writes skill files; don't double-install.
    const r = await Net.call(`/api/skills/discover/${encodeURIComponent(skillId)}/install`, {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_id: target }),
      },
    });
    if (!r.ok) {
      const body = typeof r.data === 'string' ? r.data : (r.error || '');
      Toast.danger('Install failed', body || `HTTP ${r.status}`);
      return;
    }
    if (window.Toast) Toast.success('Skill installed', `${skillId} → ${target}`);
    await load(true);
    // Refresh the workbench so the newly installed skill appears in the
    // composer's Skills tab without a full page reload.
    if (typeof loadComposerCatalogs === 'function') loadComposerCatalogs();
  }

  async function uninstall(skillId, pluginId) {
    if (!pluginId) {
      Toast.warn('Could not determine target plugin');
      return;
    }
    const ok = await Confirm.ask({ title: 'Uninstall skill', body: `Uninstall '${skillId}' from '${pluginId}'? This deletes the skill .md and removes the registration.`, okLabel: 'Uninstall', danger: true });
    if (!ok) return;
    const r = await Net.call(`/api/skills/discover/${encodeURIComponent(skillId)}/uninstall?plugin_id=${encodeURIComponent(pluginId)}`, { retries: 0, init: { method: 'DELETE' } });
    if (!r.ok) {
      const body = typeof r.data === 'string' ? r.data : (r.error || '');
      Toast.danger('Uninstall failed', body || `HTTP ${r.status}`);
      return;
    }
    if (window.Toast) Toast.success('Skill uninstalled', `${skillId} ↛ ${pluginId}`);
    await load(true);
    if (typeof loadComposerCatalogs === 'function') loadComposerCatalogs();
  }

  async function _availablePlugins() {
    try {
      const data = await Net.getJson('/api/plugins', { silent: true });
      const list = Array.isArray(data) ? data : (data.plugins || []);
      return list.map(p => p.id).filter(Boolean);
    } catch { return []; }
  }

  function setView(v) {
    if (v !== 'list' && v !== 'icons') return;
    _view = v;
    document.querySelectorAll('.skills-disc-view').forEach(b => {
      b.classList.toggle('active', b.dataset.view === v);
    });
    render();
  }

  // Browse every skill in a GitHub repo (skills.sh repos are at
  // skills.sh/<owner>/<repo>) and install any of them.
  async function browseGithubRepo() {
    const repo = prompt('GitHub repo to browse (owner/repo):', 'anthropics/skills');
    if (!repo || !repo.trim()) return;
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:min(680px,94vw);max-height:88vh;overflow-y:auto;border-radius:6px;';
    inner.innerHTML = '<div class="model-empty">Loading repo skills…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
    try {
      // getJson's thrown message already prefers the body's detail/error
      // field, matching the old d.detail || HTTP-status throw.
      const d = await Net.getJson('/api/skills/github?repo=' + encodeURIComponent(repo.trim()));
      const rows = (d.skills || []).map(s => `
        <div class="gh-skill-row">
          <div class="gh-skill-info">
            <div class="gh-skill-name">${esc(s.name)}</div>
            <div class="gh-skill-desc">${esc(s.description || s.path || '')}</div>
          </div>
          <button class="action-btn sm accent" data-action="sdisc.gh-install" data-raw-url="${esc(s.raw_url)}" data-skill-id="${esc(s.id)}">Install</button>
        </div>`).join('');
      inner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="font-family:var(--mono);font-weight:600;flex:1">${esc(d.repo)} <span style="color:var(--text-muted);font-weight:400">· ${d.count} skill${d.count === 1 ? '' : 's'}</span></div>
          <button class="action-btn xs ghost" data-action="sdisc.close">×</button>
        </div>
        <div style="font-size:0.64rem;color:var(--text-muted);margin-bottom:10px">Installs go to <code>general-skills</code> and activate immediately.</div>
        <div class="gh-skills">${rows || '<div class="model-empty">No SKILL.md files found in this repo.</div>'}</div>`;
    } catch (e) {
      inner.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed: ${esc(e.message)}</div>`;
    }
  }

  async function _installGithub(rawUrl, id, btn) {
    btn.disabled = true; btn.textContent = '…';
    try {
      // retries:0 — import writes a skill file; don't double-install.
      await Net.postJson('/api/skills/import', { url: rawUrl, plugin_id: 'general-skills', id }, { retries: 0 });
      try { await Net.postJson('/api/plugins/reload', {}, { retries: 0, silent: true }); } catch (_) {}
      btn.textContent = '✓ Installed'; btn.classList.remove('accent');
      load(true);
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Retry';
      if (window.Toast) Toast.danger('Install failed', e.message);
    }
  }

  // Import a SKILL.md from a URL (skills.sh entries are GitHub-backed — grab
  // the SKILL.md's GitHub link). Fetches + parses frontmatter server-side,
  // installs into the chosen plugin, then refreshes discovery.
  async function importFromUrl() {
    const url = prompt('SKILL.md URL to import\n(a GitHub raw or blob link — e.g. from a skills.sh skill):');
    if (!url || !url.trim()) return;
    const plugin = prompt('Install into which plugin?', 'general-skills');
    if (!plugin || !plugin.trim()) return;
    _setMeta('Importing…');
    try {
      // retries:0 — import writes a skill file; don't double-install.
      const d = await Net.postJson('/api/skills/import', { url: url.trim(), plugin_id: plugin.trim() }, { retries: 0 });
      // Hot-reload the plugin registry so the skill activates immediately —
      // no API restart. The chat path reads the same live registry.
      let active = false;
      try { active = (await Net.call('/api/plugins/reload', { retries: 0, silent: true, init: { method: 'POST' } })).ok; } catch (_) {}
      const msg = `Imported "${d.name || d.skill_id}" → ${d.plugin_id}` + (active ? ' — active now.' : ' (reload to activate).');
      Toast.info(msg);
      load(true);
    } catch (e) {
      Toast.danger('Import failed', e.message);
      _setMeta('');
    }
  }

  // Icon-explorer renderer — groups skills by persona (their primary
  // visual axis), with a large icon tile per skill. Each tile carries
  // an install/uninstall affordance.
  function _renderIconExplorer(items) {
    const groups = {};
    items.forEach(s => {
      const persona = s.persona ||
        (window.AgentIcons ? AgentIcons.resolve({ name: s.name, description: s.description }) : 'general');
      (groups[persona] = groups[persona] || []).push(s);
    });
    const order = Object.keys(groups).sort();
    return order.map(p => {
      const tone = (window.AgentIcons ? AgentIcons.tone(p) : 'accent');
      const skillsIn = groups[p].sort((a, b) => a.id.localeCompare(b.id));
      const tiles = skillsIn.map(s => {
        const icon = (window.AgentIcons ? AgentIcons.svg(p) : '');
        const action = s.installed
          ? `<button class="skill-tile-action uninstall" data-action="sdisc.uninstall" title="Uninstall this skill">−</button>`
          : (s.has_body
              ? `<button class="skill-tile-action install" data-action="sdisc.install" title="Install this skill">+</button>`
              : '');
        const stateClass = s.installed ? 'installed' : (s.has_body ? 'available' : 'bundled');
        return `<div class="skill-tile ${stateClass}" data-skill-id="${esc(s.id)}"
                     title="${esc(s.name)} — ${esc(s.description || '')}">
          <span class="skill-tile-icon tone-${esc(tone)}">${icon}</span>
          <span class="skill-tile-label">${esc(s.name)}</span>
          <span class="skill-tile-state">${esc(stateClass)}</span>
          ${action}
        </div>`;
      }).join('');
      return `<div class="skill-icon-group">
        <div class="skill-icon-group-head">
          <span class="skill-icon-group-icon tone-${esc(tone)}">${window.AgentIcons ? AgentIcons.svg(p) : ''}</span>
          <span class="skill-icon-group-name">${esc(p)}</span>
          <span class="skill-icon-group-count">${skillsIn.length}</span>
        </div>
        <div class="skill-icon-tiles">${tiles}</div>
      </div>`;
    }).join('');
  }

  // Deep-dive — expand a skill into its full SKILL.md body. Installed skills
  // open editable (saved in place via PUT /source + a live plugin reload);
  // catalog/remote skills are read-only previews of the body that would land
  // on install. Mirrors the Models/Workflows deep-dive pattern.
  async function openDetail(skillId) {
    const s = (_data?.skills || []).find(x => x.id === skillId);
    if (!s) return;
    const persona = s.persona || (window.AgentIcons ? AgentIcons.resolve({ name: s.name, description: s.description }) : 'skill');
    const tone    = (window.AgentIcons ? AgentIcons.tone(persona) : 'amber');
    const iconSvg = (window.AgentIcons ? AgentIcons.svg(persona) : '');
    const plugin  = (s.installed_in || [])[0] || '';

    const modal = document.createElement('div');
    modal.className = 'skill-detail-overlay';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);width:min(780px,95vw);max-height:90vh;display:flex;flex-direction:column;border-radius:8px;overflow:hidden';
    inner.innerHTML = '<div class="model-empty" style="padding:28px">Loading skill…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);

    // Resolve the body: installed → on-disk editable source; else catalog body.
    let body = '', editable = false, srcPlugin = plugin;
    try {
      if (s.installed && plugin) {
        const r = await Net.call(`/api/skills/source/${encodeURIComponent(skillId)}?plugin_id=${encodeURIComponent(plugin)}`, { silent: true });
        if (r.ok) { const d = r.data; body = d.body || ''; editable = true; srcPlugin = d.plugin_id || plugin; }
      }
      if (!body) {
        const r = await Net.call(`/api/skills/discover/${encodeURIComponent(skillId)}`, { silent: true });
        if (r.ok) { const d = r.data; body = d.skill_md || ''; }
      }
    } catch (_) {}

    const triggers = (s.triggers || []).map(t => `<span class="cap-card-meta">${esc(t)}</span>`).join(' · ');
    const stateLabel = s.installed
      ? `installed${plugin ? ' · ' + esc(plugin) : ''}`
      : (s.marketplace || s.source === 'remote' ? 'marketplace' : (s.has_body ? 'available' : 'bundled'));
    const removeBtn = (s.installed && plugin)
      ? `<button class="action-btn sm danger" data-action="sdisc.overlay-uninstall" data-skill-id="${esc(skillId)}" data-plugin="${esc(plugin)}">Remove</button>` : '';
    const installBtn = (!s.installed && s.has_body)
      ? `<button class="action-btn sm accent" data-action="sdisc.overlay-install" data-skill-id="${esc(skillId)}">Install</button>` : '';
    const editControls = editable
      ? `<button class="action-btn sm" id="skill-edit-toggle" data-action="sdisc.edit-toggle">Edit</button>` : '';

    inner.innerHTML = `
      <div style="display:flex;align-items:flex-start;gap:11px;padding:16px 18px;border-bottom:1px solid var(--border)">
        <span class="agent-card-icon tone-${esc(tone)}" style="flex:0 0 auto">${iconSvg}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:650;font-size:0.96rem">${esc(s.name || skillId)}</div>
          <div style="font-size:0.72rem;color:var(--text-muted);margin-top:2px">${esc(s.description || '')}</div>
          <div style="display:flex;gap:8px;align-items:center;margin-top:7px;flex-wrap:wrap">
            <code class="cap-card-id">${esc(skillId)}</code>
            <span class="skill-disc-chip ${s.installed ? 'installed' : (s.has_body ? 'available' : 'bundled')}">${stateLabel}</span>
            ${triggers ? `<span class="cap-card-meta">${triggers}</span>` : ''}
          </div>
        </div>
        <button class="action-btn xs ghost" data-action="sdisc.overlay-close">×</button>
      </div>
      <div style="flex:1;min-height:0;overflow:auto;padding:14px 18px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:0.64rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-muted)">SKILL.md ${editable ? '' : '· read-only'}</span>
          <span id="skill-edit-status" style="font-size:0.64rem;color:var(--text-muted)"></span>
        </div>
        <textarea id="skill-detail-body" readonly spellcheck="false"
          style="width:100%;min-height:340px;font-family:var(--mono);font-size:0.72rem;line-height:1.5;background:var(--bg-deep);color:var(--text);border:1px solid var(--border-strong);border-radius:5px;padding:11px;resize:vertical;box-sizing:border-box">${esc(body || '(no body — this entry ships pre-bundled in the plugin)')}</textarea>
      </div>
      <div style="display:flex;gap:8px;align-items:center;padding:12px 18px;border-top:1px solid var(--border)">
        ${editControls}
        <span id="skill-edit-save-wrap" style="display:none;gap:8px">
          <button class="action-btn sm accent" id="skill-edit-save" data-action="sdisc.edit-save" data-skill-id="${esc(skillId)}" data-plugin="${esc(srcPlugin)}">Save &amp; reload</button>
          <button class="action-btn sm ghost" data-action="sdisc.edit-cancel">Cancel</button>
        </span>
        <span style="flex:1"></span>
        ${installBtn}${removeBtn}
      </div>`;
    SkillsDiscover._detailOrig = body;
  }

  function _toggleEdit() {
    const ta = document.getElementById('skill-detail-body');
    const toggle = document.getElementById('skill-edit-toggle');
    const saveWrap = document.getElementById('skill-edit-save-wrap');
    if (!ta) return;
    ta.readOnly = false;
    ta.focus();
    if (toggle) toggle.style.display = 'none';
    if (saveWrap) saveWrap.style.display = 'inline-flex';
    const st = document.getElementById('skill-edit-status');
    if (st) st.textContent = 'editing — unsaved';
  }

  function _cancelEdit() {
    const ta = document.getElementById('skill-detail-body');
    if (ta && typeof SkillsDiscover._detailOrig === 'string') ta.value = SkillsDiscover._detailOrig;
    if (ta) ta.readOnly = true;
    const toggle = document.getElementById('skill-edit-toggle');
    const saveWrap = document.getElementById('skill-edit-save-wrap');
    if (toggle) toggle.style.display = '';
    if (saveWrap) saveWrap.style.display = 'none';
    const st = document.getElementById('skill-edit-status');
    if (st) st.textContent = '';
  }

  async function _saveEdit(skillId, pluginId) {
    const ta = document.getElementById('skill-detail-body');
    const save = document.getElementById('skill-edit-save');
    const st = document.getElementById('skill-edit-status');
    if (!ta) return;
    const newBody = ta.value;
    if (!newBody.trim()) { if (window.Toast) Toast.danger('Skill body cannot be empty'); return; }
    if (save) { save.disabled = true; save.textContent = 'Saving…'; }
    try {
      // retries:0 — PUT rewrites the skill file; don't double-apply.
      const r = await Net.call(`/api/skills/source/${encodeURIComponent(skillId)}`, {
        retries: 0,
        init: {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ plugin_id: pluginId, body: newBody }),
        },
      });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      // Hot-reload so the edited skill activates immediately for chat.
      let active = false;
      try { active = (await Net.call('/api/plugins/reload', { retries: 0, silent: true, init: { method: 'POST' } })).ok; } catch (_) {}
      SkillsDiscover._detailOrig = newBody;
      ta.readOnly = true;
      const toggle = document.getElementById('skill-edit-toggle');
      const saveWrap = document.getElementById('skill-edit-save-wrap');
      if (toggle) toggle.style.display = '';
      if (saveWrap) saveWrap.style.display = 'none';
      if (st) st.textContent = active ? 'saved — active now' : 'saved (reload to activate)';
      if (window.Toast) Toast.success('Skill saved', `${skillId} → ${pluginId}`);
      load(true);
    } catch (e) {
      if (window.Toast) Toast.danger('Save failed', e.message);
      if (st) st.textContent = 'save failed';
    } finally {
      if (save) { save.disabled = false; save.textContent = 'Save & reload'; }
    }
  }

  // Delegated actions — the discover grid re-renders per keystroke, so
  // cards/tiles carry data-action and resolve the skill id via the closest
  // data-skill-id host. The (s.installed_in||[])[0] target-plugin lookup
  // lives here against module state instead of being interpolated into
  // attribute strings. Registered inside the module for _data access.
  const _skillIdOf = el => {
    const host = el.closest('[data-skill-id]');
    return host ? host.dataset.skillId : '';
  };
  const _installedPluginOf = id => {
    const s = ((_data && _data.skills) || []).find(x => x.id === id);
    return (s && (s.installed_in || [])[0]) || '';
  };
  const _overlayOf = el => el.closest('.skill-detail-overlay');
  Actions.click({
    'sdisc.install':    el => install(_skillIdOf(el)),
    'sdisc.uninstall':  el => uninstall(_skillIdOf(el), _installedPluginOf(_skillIdOf(el))),
    'sdisc.detail':     el => openDetail(_skillIdOf(el)),
    'sdisc.gh-install': el => _installGithub(el.dataset.rawUrl, el.dataset.skillId, el),
    'sdisc.close':      el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); },
    'sdisc.overlay-close':     el => { const o = _overlayOf(el); if (o) o.remove(); },
    'sdisc.overlay-install':   el => { install(el.dataset.skillId); const o = _overlayOf(el); if (o) o.remove(); },
    'sdisc.overlay-uninstall': el => { uninstall(el.dataset.skillId, el.dataset.plugin); const o = _overlayOf(el); if (o) o.remove(); },
    'sdisc.edit-toggle': () => _toggleEdit(),
    'sdisc.edit-save':   el => _saveEdit(el.dataset.skillId, el.dataset.plugin),
    'sdisc.edit-cancel': () => _cancelEdit()
  });

  return { load, render, install, uninstall, setView, importFromUrl, browseGithubRepo, _installGithub,
           openDetail, _toggleEdit, _cancelEdit, _saveEdit };
})();
window.SkillsDiscover = SkillsDiscover;

/* ── Drag-to-node handlers: attach a workbench item to a node ────── */
(function wireWorkbenchDropHandlers() {
  document.addEventListener('drop', (e) => {
    const canvas = document.getElementById('drawflow-canvas');
    if (!canvas || !canvas.contains(e.target)) return;
    const skillRef = e.dataTransfer.getData('application/df-skill');
    const toolRef  = e.dataTransfer.getData('application/df-tool');
    const mcpRef   = e.dataTransfer.getData('application/df-mcp');
    if (!skillRef && !toolRef && !mcpRef) return;
    // Find the node under the cursor
    const nodeEl = e.target.closest('.drawflow-node');
    if (!nodeEl) {
      console.log('Drop a workbench item onto a step node to attach it.');
      return;
    }
    const nodeIdMatch = nodeEl.id.match(/^node-(\d+)$/);
    if (!nodeIdMatch) return;
    const nodeId = parseInt(nodeIdMatch[1], 10);
    const data = dfNodeData[nodeId];
    if (!data) return;
    data.skills = data.skills || [];
    data.tools  = data.tools  || [];
    if (skillRef) { if (!data.skills.includes(skillRef)) data.skills.push(skillRef); }
    if (toolRef)  { if (!data.tools.find(t => (typeof t === 'string' ? t : t.id) === toolRef)) data.tools.push(toolRef); }
    if (mcpRef)   {
      const [serverId, toolName] = mcpRef.split('::');
      const ref = `mcp__${serverId}__${toolName}`;
      if (!data.tools.find(t => (typeof t === 'string' ? t : t.id) === ref)) data.tools.push(ref);
    }
    // Re-render the canvas node so the newly attached skill/tool/MCP
    // shows up as a chip + refresh the config panel if it's open.
    if (typeof dfUpdateNodeData === 'function') {
      dfUpdateNodeData(nodeId, 'skills', data.skills, { commit: true });
    }
  }, true);
})();

// Detach helpers — used by the chips on the canvas node + the config
// panel's attachments section. Both write back through dfUpdateNodeData
// so the canvas re-renders.
function dfDetachSkill(nodeId, ref) {
  const d = dfNodeData[nodeId];
  if (!d) return;
  d.skills = (d.skills || []).filter(s => s !== ref);
  dfUpdateNodeData(nodeId, 'skills', d.skills, { commit: true });
}
function dfDetachTool(nodeId, ref) {
  const d = dfNodeData[nodeId];
  if (!d) return;
  d.tools = (d.tools || []).filter(t => (typeof t === 'string' ? t : t.id) !== ref);
  dfUpdateNodeData(nodeId, 'tools', d.tools, { commit: true });
}

/* ── Agent selector for the chat dock ────────────────────────────── */
async function loadAgentsForSelector() {
  const sel = document.getElementById('agent-select');
  if (!sel) return;
  try {
    const list = await Net.getJson('/api/agents', { silent: true });
    const opts = ['<option value="">— none (use model directly) —</option>']
      .concat((list || []).map(a => `<option value="${esc(a.id)}">${esc(a.name || a.id)}${a.role ? ' (' + esc(a.role) + ')' : ''}</option>`));
    sel.innerHTML = opts.join('');
  } catch (e) { /* non-fatal */ }
}

function onAgentSelectionChanged() {
  const sel = document.getElementById('agent-select');
  if (!sel || !sel.value) return;
  // Scope subsequent chat turns to this agent. The existing sendMessage
  // path reads window._chatAgent before composing the request body.
  window._chatAgent = sel.value;
  const msgEl = document.getElementById('messages');
  if (msgEl) {
    const note = document.createElement('div');
    note.className = 'msg system-msg';
    note.textContent = `Scoped to agent: ${sel.options[sel.selectedIndex].text}`;
    msgEl.appendChild(note);
    msgEl.scrollTop = msgEl.scrollHeight;
  }
}

function toggleAgentDock(force) {
  const dock = document.getElementById('agent-chat-dock');
  if (!dock) return;
  const willCollapse = force === undefined ? !dock.classList.contains('collapsed') : !!force;
  dock.classList.toggle('collapsed', willCollapse);
  // Sync the caret on whichever toggle button drove this.
  const btn = dock.querySelector('[onclick*="toggleAgentDock"]');
  if (btn) btn.textContent = willCollapse ? '▴' : '▾';
}

function toggleComposerWorkstream(force) {
  const panel = document.getElementById('composer-workstream');
  if (!panel) return;
  const willCollapse = force === undefined ? !panel.classList.contains('collapsed') : !!force;
  panel.classList.toggle('collapsed', willCollapse);
  const btn = document.getElementById('workstream-collapse-btn');
  if (btn) btn.textContent = willCollapse ? '▴' : '▾';
}

// ── ComposerSplit ────────────────────────────────────────────────────
// Owns the chat | workflow-spine layout: the draggable divider (persists
// the chat fraction), full-chat collapse, and the dormant↔primed swap.
// Pure layout — no behaviour change to chat or the canvas.
const ComposerSplit = (function () {
  const KEY = 'enclave.composer.split';
  // MIN dropped 40→25 with the design-system pivot: in canvas mode the
  // chat docks as the test surface (~30%) and the canvas dominates.
  const MIN = 25, MAX = 85;          // chat-pane width as a % of the split
  const CHAT_FRAC = 58, CANVAS_FRAC = 30;
  let _wired = false;
  let _mode = 'chat';

  function _el() { return document.getElementById('composer-split'); }

  function _applyFrac(pct) {
    const el = _el(); if (!el) return;
    const clamped = Math.max(MIN, Math.min(MAX, pct));
    el.style.setProperty('--chat-frac', clamped + '%');
    const divider = document.getElementById('composer-divider');
    if (divider) divider.setAttribute('aria-valuenow', String(Math.round(clamped)));
  }

  function init() {
    const el = _el(); if (!el || _wired) return;
    _wired = true;
    const saved = parseFloat(localStorage.getItem(KEY));
    if (!isNaN(saved)) _applyFrac(saved);
    _wireDrag();
  }

  function _wireDrag() {
    const el = _el(); const divider = document.getElementById('composer-divider');
    if (!el || !divider) return;

    function onDown(e) {
      // Only the left column is draggable; ignore when collapsed/stacked.
      if (el.classList.contains('spine-collapsed')) return;
      if (window.matchMedia('(max-width: 900px)').matches) return;
      e.preventDefault();
      el.classList.add('is-dragging');
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp, { once: true });
    }
    function onMove(e) {
      const rect = el.getBoundingClientRect();
      if (!rect.height) return;
      _applyFrac(((e.clientY - rect.top) / rect.height) * 100);
    }
    function onUp() {
      el.classList.remove('is-dragging');
      window.removeEventListener('pointermove', onMove);
      const cur = el.style.getPropertyValue('--chat-frac').replace('%', '').trim();
      if (cur) localStorage.setItem(KEY, cur);
    }
    function _persist() {
      const cur = el.style.getPropertyValue('--chat-frac').replace('%', '').trim();
      if (cur) localStorage.setItem(KEY, cur);
    }
    // Keyboard resize for the role="separator" (a11y): ←/→ nudge, Home resets.
    function onKey(e) {
      if (el.classList.contains('spine-collapsed')) return;
      let f = parseFloat(el.style.getPropertyValue('--chat-frac'));
      if (isNaN(f)) f = 58;
      if (e.key === 'ArrowUp') f -= 3;
      else if (e.key === 'ArrowDown') f += 3;
      else if (e.key === 'Home') { f = 58; localStorage.removeItem(KEY); _applyFrac(f); return; }
      else return;
      e.preventDefault();
      _applyFrac(f);
      _persist();
    }
    divider.addEventListener('pointerdown', onDown);
    divider.addEventListener('keydown', onKey);
    divider.addEventListener('dblclick', () => { _applyFrac(58); localStorage.removeItem(KEY); });
  }

  // Swap the spine between its dormant ghost and the live canvas/workstream.
  function setSpinePrimed(primed) {
    const el = _el(); if (!el) return;
    el.classList.toggle('is-primed', !!primed);
    if (primed) el.classList.remove('spine-collapsed');
  }

  // Collapse the spine entirely → full-chat (toggle).
  function toggleSpine(force) {
    const el = _el(); if (!el) return;
    el.classList.toggle('spine-collapsed', force === undefined ? undefined : !force);
  }

  // ── In-shell pivot (design-system console-v2) ──────────────────────
  // One thread, two modes: CHAT (conversation leads, spine is the rail)
  // and CANVAS (workflow leads, chat docks as the test surface). The
  // Boot Sequence pivots to canvas on confirm — the composer takes the
  // stage exactly when there is a workflow to stage.
  function setMode(mode) {
    const el = _el(); if (!el) return;
    _mode = (mode === 'canvas' || mode === 'focus') ? mode : 'chat';
    el.classList.remove('spine-collapsed');
    el.classList.toggle('mode-canvas', _mode === 'canvas');
    el.classList.toggle('mode-focus', _mode === 'focus');
    if (_mode !== 'focus') _applyFrac(_mode === 'canvas' ? CANVAS_FRAC : CHAT_FRAC);
    for (const m of ['chat', 'canvas', 'focus']) {
      ['composer-mode-' + m, 'composer-fmode-' + m].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.setAttribute('aria-pressed', String(_mode === m));
      });
    }
    // The canvas just resized — let drawflow + anchors settle into it.
    setTimeout(() => {
      try { if (typeof dfScheduleAnchorRefresh === 'function') dfScheduleAnchorRefresh(); } catch (_) {}
    }, 60);
  }

  function getMode() { return _mode; }

  function focusChat() {
    const p = document.getElementById('prompt');
    if (p) { p.focus(); p.scrollIntoView({ block: 'nearest' }); }
  }

  return { init, setSpinePrimed, toggleSpine, setMode, getMode, focusChat };
})();

// ── BootSequence ──────────────────────────────────────────────────────
// The flagship "Promote": hand a chat answer to the operator's LOCAL agents.
// Act 1 (affordance) lives in .msg-actions; this module owns Act 2 (the
// self-typing "compile log" plan card) and Act 3 (the reveal as the dormant
// spine ignites into a live DAG). It calls the local /api/composer endpoints
// to capture a spec + scaffold a definition, then primes the spine through the
// shared composerLoadDefinition() — the same path that loads a saved workflow.
window.BootSequence = (function () {
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
      composerLoadDefinition(defn);
      if (typeof ComposerSplit !== 'undefined') {
        ComposerSplit.setSpinePrimed(true);
        // The in-shell pivot: the workflow just became the artifact, so
        // the canvas takes the stage and the chat docks as test surface.
        ComposerSplit.setMode('canvas');
      }
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

// Loaded-models popover (status strip chip). Hidden by default; the
// chip click toggles. Pass `false` to force-close.
function toggleLoadedModelsPopover(force) {
  const pop  = document.getElementById('strip-models-pop');
  const chip = document.getElementById('strip-models-chip');
  if (!pop || !chip) return;
  const open = force === undefined ? pop.hasAttribute('hidden') : !!force;
  if (open) {
    pop.removeAttribute('hidden');
    chip.setAttribute('aria-expanded', 'true');
    // Close on outside click (mounted once per open).
    setTimeout(() => {
      const onDown = (e) => {
        if (!pop.contains(e.target) && !chip.contains(e.target)) {
          toggleLoadedModelsPopover(false);
          document.removeEventListener('mousedown', onDown);
        }
      };
      document.addEventListener('mousedown', onDown);
    }, 0);
  } else {
    pop.setAttribute('hidden', '');
    chip.setAttribute('aria-expanded', 'false');
  }
}

// Internal helper used by loadModels() + composition syncs to keep
// the strip chip count fresh.
function _setStripModelCount(n) {
  const el = document.getElementById('models-chip-count');
  if (el) el.textContent = (n == null || n === '' ? '—' : String(n));
}

// Mirror models pinned by canvas steps into the chat-dock model picker
// so the operator can target the same model the workflow is using.
// Idempotent: drops any previous "from composition" optgroup before
// inserting a fresh one, preserves current selection.
function syncCompositionModelsToChatPicker() {
  const sel = document.getElementById('model-select');
  if (!sel) return;
  // Remove any previously injected group so duplicates can't pile up.
  Array.from(sel.querySelectorAll('optgroup[data-composition="1"]')).forEach(g => g.remove());

  if (!window.dfNodeData) return;
  // Distinct, non-empty models referenced by any node on the canvas.
  const pinned = new Set();
  Object.values(window.dfNodeData).forEach(d => {
    if (d && typeof d.model === 'string' && d.model.trim()) pinned.add(d.model.trim());
  });
  if (!pinned.size) return;

  const previousValue = sel.value;
  const known = new Set();
  Array.from(sel.options).forEach(o => o.value && known.add(o.value));

  const group = document.createElement('optgroup');
  group.label = 'From composition';
  group.dataset.composition = '1';
  Array.from(pinned).sort().forEach(modelId => {
    const opt = document.createElement('option');
    opt.value = modelId;
    // If the pinned model isn't actually loaded in Ollama, mark it so
    // the operator notices before sending a message that would fail.
    opt.textContent = known.has(modelId) ? modelId : `${modelId} (not loaded)`;
    if (!known.has(modelId)) opt.style.color = 'var(--text-muted)';
    group.appendChild(opt);
  });
  sel.appendChild(group);

  // Restore selection — if the previous pick was one of the pinned
  // models, the matching option still exists; otherwise this no-ops.
  if (previousValue) sel.value = previousValue;
}
window.syncCompositionModelsToChatPicker = syncCompositionModelsToChatPicker;

/* ── Bundle import / export from composer ─────────────────────────── */
async function composerExportBundle() {
  const wfId = (document.getElementById('df-wf-id') || {}).value;
  if (!wfId) { Toast.warn('Set a workflow ID first.'); return; }
  // Save first so the export reflects the current canvas state.
  await dfSave().catch(() => { /* user dismissed */ });
  try {
    const r = await Net.call(`/api/workflow-index/${encodeURIComponent(wfId)}/export`);
    if (!r.ok) { Toast.danger('Export failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
    const bundle = r.data;
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${wfId}.bundle.json`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) { Toast.danger('Export error', e.message); }
}

function dfImportBundle() {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.json';
  inp.onchange = async () => {
    const file = inp.files && inp.files[0];
    if (!file) return;
    const text = await file.text();
    let bundle;
    try { bundle = JSON.parse(text); } catch (e) { Toast.warn('Invalid JSON', e.message); return; }
    try {
      const r = await Net.call('/api/workflow-index/import?overwrite=true', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(bundle),
        },
      });
      if (!r.ok) { Toast.danger('Import failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      const result = r.data;
      Toast.success(`Imported workflow '${result.workflow_id}'`, `+${result.agents_installed.length} agents`);
      if (typeof WorkflowIndex !== 'undefined') WorkflowIndex.load();
      if (typeof refreshWorkflows === 'function') refreshWorkflows();
    } catch (e) { Toast.danger('Import error', e.message); }
  };
  inp.click();
}

/* ── Composer convenience: new workflow / load from index ─────────── */
// Explicit "Clear" — prompts before wiping so unsaved composer state
// isn't lost to a stray click. Falls through to composerNewWorkflow
// (the existing cleanup path); the only difference is the confirm
// gate. Cancelling the Confirm.ask dialog leaves the composer untouched.
async function composerClearWithConfirm() {
  const hasNodes = (typeof dfEditor !== 'undefined' && dfEditor &&
                    Object.keys(dfEditor.drawflow.drawflow.Home.data || {}).length > 0);
  const hasMeta = ['df-wf-id', 'df-wf-name', 'df-wf-desc']
    .some(id => (document.getElementById(id)?.value || '').trim().length > 0);
  if (!hasNodes && !hasMeta) {
    // Already empty — nothing to confirm. Trigger the cleanup so the
    // canvas-empty-state flag stays in sync with the actual state.
    composerNewWorkflow();
    return;
  }
  const msg = hasNodes
    ? 'Clear the composer? All canvas nodes + metadata will be wiped. (Unsaved work cannot be recovered.)'
    : 'Clear the workflow metadata? (No canvas nodes will be affected.)';
  const ok = await Confirm.ask({ title: 'Clear composer', body: msg, okLabel: 'Clear', danger: hasNodes });
  if (!ok) return;
  composerNewWorkflow();
  if (window.Toast) Toast.info('Composer cleared', '', { ttl: 1600 });
}

function composerNewWorkflow() {
  // Wipe all nodes and reset metadata so the user starts blank.
  if (typeof dfEditor !== 'undefined' && dfEditor) {
    Object.keys(dfEditor.drawflow.drawflow.Home.data || {}).forEach(id => {
      try { dfEditor.removeNodeId('node-' + id); } catch (e) {}
    });
  }
  // Drop the chat's step-engage pointer with the nodes it pointed into.
  // dfNextId resets below, so a NEW workflow reuses the same numeric node
  // ids — a stale engaged id would silently re-match a different step and
  // route the next chat message to it.
  try { composerExitStepEngage(); } catch (_) {}
  dfNodeData = {}; dfNextId = 0; dfSelectedNodeId = null;
  dfSeedSchema = [];  // fresh workflow → empty input contract
  ['df-wf-id', 'df-wf-name', 'df-wf-desc'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  const yamlPanel = document.getElementById('df-yaml-panel');
  if (yamlPanel) yamlPanel.style.display = 'none';
  ComposerView.updateCanvasEmptyState();
  if (typeof dfScheduleAnchorRefresh === 'function') dfScheduleAnchorRefresh();
}

async function composerLoadFromIndex() {
  switchTab('workflow-index');
}

async function composerLoadById(wfId) {
  if (!wfId) return;
  try {
    const r = await Net.call(`/api/workflows/${encodeURIComponent(wfId)}`);
    if (!r.ok) { Toast.danger('Load failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
    const defn = r.data;
    if (!defn.id) defn.id = wfId;
    composerLoadDefinition(defn);
  } catch (e) { Toast.danger('Load error', e.message); }
}

// Load a workflow-definition OBJECT directly onto the canvas. Shared by
// composerLoadById's fetch path and the chat-led BootSequence scaffold, so a
// scaffolded plan primes the spine through exactly the same code that loads a
// saved workflow. Places step nodes, wires depends_on (or infers a linear
// chain), restores the seed schema, draws START/END anchors, and lays out.
function composerLoadDefinition(defn) {
  defn = defn || {};
  try {
    // Ensure the drawflow editor exists BEFORE the cleanup + node spawn path
    // runs (idempotent). A scaffold/open before the operator has ever visited
    // the Composer tab would otherwise silently produce zero nodes.
    if (typeof ComposerView !== 'undefined' && ComposerView && ComposerView.init) {
      try { ComposerView.init(); } catch (_) {}
    } else if (typeof dfInitEditor === 'function') {
      try { dfInitEditor(); } catch (_) {}
    }
    composerNewWorkflow();
    // jsyaml import path uses the modal textarea; call the function that
    // accepts a definition object directly via the same path.
    document.getElementById('df-wf-id').value = defn.id || '';
    document.getElementById('df-wf-name').value = defn.name || '';
    const _descEl = document.getElementById('df-wf-desc');
    _descEl.value = defn.description || '';
    // Auto-size the description textarea to fit the loaded text.
    _descEl.dispatchEvent(new Event('input'));
    if (defn.defaults && defn.defaults.role) {
      const r = document.getElementById('df-wf-role'); if (r) r.value = defn.defaults.role;
    }
    if (defn.category) {
      const c = document.getElementById('df-wf-category'); if (c) c.value = defn.category;
    }
    // Place steps on the canvas via the existing palette template hook.
    // Track step.id → drawflow node id so we can wire depends_on edges
    // after every node exists.
    const idMap = {};
    (defn.steps || []).forEach((step, i) => {
      const tmplKey = (step.role && dfStepTemplates.find(t => t.role === step.role)) ? step.role : 'custom';
      const tmpl = dfStepTemplates.find(t => t.key === tmplKey) || dfStepTemplates.find(t => t.key === 'custom');
      const x = 80 + (i % 4) * 220;
      const y = 60 + Math.floor(i / 4) * 140;
      // No auto-chain on load — the definition's depends_on drives wiring.
      const nodeId = dfAddNodeFromTemplate(tmpl.key, x, y, { autoChain: false });
      if (nodeId != null) {
        const d = dfNodeData[nodeId];
        d.id = step.id || d.id;
        d.name = step.name || d.name;
        d.role = step.role || d.role;
        // Accept the v2 structured prompt (prompt.task / prompt.role_inline)
        // as a fallback so template-matched workflows that use the v2 schema
        // render with real instructions instead of an empty 'custom' node.
        d.system_prompt = step.system_prompt
          || (step.prompt && (step.prompt.task || step.prompt.role_inline))
          || d.system_prompt;
        d.outputs = Array.isArray(step.outputs) ? step.outputs : d.outputs;
        d.output_format = (step.output_parser && step.output_parser.format) || 'raw';
        d.quality_gates = Array.isArray(step.quality_gates) ? step.quality_gates : [];
        d.tools = step.tools || [];
        d.skills = step.skills || [];
        dfUpdateNodeData(nodeId, 'name', d.name);
        idMap[d.id] = nodeId;
      }
    });

    // Wire the DAG. Each step's `depends_on` is the upstream step id(s);
    // every dependency becomes an edge from upstream.output_1 →
    // downstream.input_1. dfEditor.addConnection expects DRAWFLOW ids
    // (integers), not logical step ids, so we route through idMap.
    //
    // If the YAML doesn't declare any depends_on at all, infer a
    // linear chain from step order — that matches what the engine
    // actually executes for unordered step lists and keeps the
    // visual "this is a flow" rather than a pile of disconnected
    // boxes the operator has to wire manually.
    const allSteps = defn.steps || [];
    const anyDepsDeclared = allSteps.some(s => {
      const d = s.depends_on;
      return (Array.isArray(d) && d.length > 0) || (typeof d === 'string' && d);
    });
    let edgesAdded = 0;
    if (anyDepsDeclared) {
      allSteps.forEach((step) => {
        const downstreamId = idMap[step.id];
        if (downstreamId == null) return;
        const deps = Array.isArray(step.depends_on) ? step.depends_on
                   : (step.depends_on ? [step.depends_on] : []);
        deps.forEach((depStepId) => {
          const upstreamId = idMap[depStepId];
          if (upstreamId == null) return;
          try {
            dfEditor.addConnection(upstreamId, downstreamId, 'output_1', 'input_1');
            edgesAdded += 1;
          } catch (e) {
            console.warn(`Connection ${depStepId}→${step.id} failed:`, e && e.message);
          }
        });
      });
    } else {
      // Inferred linear chain: step[i-1] → step[i].
      for (let i = 1; i < allSteps.length; i++) {
        const upstreamId = idMap[allSteps[i - 1].id];
        const downstreamId = idMap[allSteps[i].id];
        if (upstreamId == null || downstreamId == null) continue;
        try {
          dfEditor.addConnection(upstreamId, downstreamId, 'output_1', 'input_1');
          edgesAdded += 1;
        } catch (e) {
          console.warn(`Inferred chain ${allSteps[i - 1].id}→${allSteps[i].id} failed:`, e && e.message);
        }
      }
    }

    // Restore the declared seed schema (the START anchor's input contract)
    // from context.inputs so it round-trips, then draw the begin/end anchors.
    try {
      const ci = (defn.context && Array.isArray(defn.context.inputs)) ? defn.context.inputs : [];
      dfSeedSchema = ci.map(x => (typeof x === 'string'
        ? { key: x, description: '' }
        : { key: x.key, description: x.description || '' })).filter(s => s.key);
    } catch (_) { dfSeedSchema = []; }
    // START/END anchor nodes — same seed→deliverable brackets as the runs
    // DAG. Not tracked in dfNodeData, so dfExportYaml skips them (they're
    // decoration, not steps).
    try { dfAddAnchors(allSteps, idMap, anyDepsDeclared, dfSeedSchema.map(s => s.key)); } catch (_) {}

    // Auto-layout AFTER edges exist so dagre's topological sort actually
    // has a graph to lay out (with no edges it stacked everything at
    // top-left). Then ComposerView refreshes the empty-state flag.
    setTimeout(() => {
      try { dfAutoLayout(); } catch (e) { console.warn('auto-layout failed', e); }
    }, 50);
    if (window.Toast) {
      Toast.info(
        `Loaded ${defn.id}`,
        `${(defn.steps || []).length} steps, ${edgesAdded} edges`,
        { ttl: 2400 }
      );
    }
    ComposerView.updateCanvasEmptyState();
    // Node-bound chat: the agent always starts on the workflow's starting
    // point — auto-engage the first/root step so the chat opens already
    // "talking to" the seed agent (the user can click any node to switch).
    try {
      const firstStep = (defn.steps || [])[0];
      const firstNodeId = firstStep ? idMap[firstStep.id] : null;
      if (firstNodeId != null && typeof composerEnterStepEngage === 'function') composerEnterStepEngage(firstNodeId);
    } catch (_) {}
    // Parity with the pre-split composer: loading a definition is a
    // canvas-intent action, so the canvas takes the stage. Focus mode is
    // respected if the operator already chose it; chat mode pivots.
    try {
      if (typeof ComposerSplit !== 'undefined' && ComposerSplit.getMode() === 'chat') {
        ComposerSplit.setMode('canvas');
      }
    } catch (_) {}
  } catch (e) { Toast.danger('Load error', e.message); }
}

async function composerLoadByIdAndSwitch() {
  const sel = document.getElementById('wf-select');
  if (!sel || !sel.value) { Toast.warn('Pick a workflow first.'); return; }
  switchTab('dashboard');
  setTimeout(() => composerLoadById(sel.value), 100);
}

async function dfRunWorkflowFromComposer() {
  // Use the existing run path; it saves + kicks the engine. The
  // post-run landing moved to the dedicated Runs tab (was the legacy
  // 'workflows' Catalog page).
  if (typeof dfRunWorkflow === 'function') {
    await dfRunWorkflow();
    switchTab('runs');
  }
}

// Live-mode run: POSTs to /api/workflows/run-async, returns run_id
// immediately, then hands off to ComposerWorkstream.startPolling which
// surfaces step-by-step progress in the Active Run pane below the
// canvas. Operator stays in the Composer and watches the run unfold.
async function dfRunWorkflowLive() {
  if (!window.dfNodeData || Object.keys(window.dfNodeData).length === 0) {
    if (window.Toast) Toast.warn('Empty workflow', 'Add at least one step to the canvas before running.');
    return;
  }
  let definition;
  try {
    if (typeof dfBuildWorkflowDefinition === 'function') {
      definition = dfBuildWorkflowDefinition();
    } else if (typeof dfExportYaml === 'function') {
      const yamlText = dfExportYaml();
      // Best-effort: parse it back to a dict via a tiny YAML loader.
      // If we don't have one client-side, send as workflow_id assumes
      // the workflow was just saved.
      definition = null;
    }
  } catch (e) {
    if (window.Toast) Toast.danger('Build failed', e.message || String(e));
    return;
  }

  let seed = {};
  try {
    const seedEl = document.getElementById('wf-seed');
    if (seedEl && seedEl.value) seed = JSON.parse(seedEl.value || '{}');
  } catch (_) { seed = {}; }

  const wfId = (document.getElementById('df-wf-id') || {}).value;
  const body = definition ? { definition, seed } : (wfId ? { workflow_id: wfId, seed } : null);
  if (!body) {
    if (window.Toast) Toast.warn('Need a workflow', 'Save the workflow first or open one from the index.');
    return;
  }

  if (window.Toast) Toast.info('Kicking off…', 'live polling will surface step progress', { ttl: 2200 });
  try {
    // retries:0 — a retried kickoff would start two runs.
    const r = await Net.call('/api/workflows/run-async', {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    });
    if (!r.ok) {
      const t = typeof r.data === 'string' ? r.data : JSON.stringify(r.data || r.error || '');
      throw new Error('HTTP ' + r.status + ' — ' + String(t).slice(0, 200));
    }
    const data = r.data;
    if (data.run_id && window.ComposerWorkstream) {
      ComposerWorkstream.startPolling(data.run_id);
    }
  } catch (e) {
    if (window.Toast) Toast.danger('Run kickoff failed', String(e));
  }
}

// Stop the active composer run. Mirrors RunsTab.cancelCurrent /
// ComposerWorkstream.clearRun's cancel — POST .../cancel — but reachable
// straight from the composer toolbar so the operator doesn't have to leave
// the canvas. The current run id is tracked by dfApplyRunState; falls back
// to the last run summary if needed.
async function composerStopRun() {
  const runId = window._composerActiveRunId
    || (window._lastRunSummary && window._lastRunSummary.run_id);
  if (!runId) {
    if (window.Toast) Toast.warn('No active run', 'Start a run first.');
    return;
  }
  if (!confirm('Stop this run? The engine halts at the next step boundary; the in-flight step finishes first.')) return;
  const btn = document.getElementById('composer-stop-btn');
  if (btn) { btn.disabled = true; btn.textContent = '◼ Stopping…'; }
  try {
    const r = await fetch(`/api/workflows/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    if (window.Toast) Toast.info('Stop requested', 'Run will halt after the current step.');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '◼ Stop'; }
    if (window.Toast) Toast.danger('Stop failed', String(e));
  }
}
window.composerStopRun = composerStopRun;

/* ══════════════════════════════════════════════════════════════════
   WORKFLOW INDEX — categorized catalogue + import/export bundles.
   ══════════════════════════════════════════════════════════════════ */
const WorkflowIndex = (function () {
  let _data = { workflows: [], categories: [] };
  let _activeCat = 'all';

  async function load() {
    const grid = document.getElementById('wfi-grid');
    if (grid) Skeleton.fill(grid, 5);
    const r = await Net.call('/api/workflow-index', { silent: true });
    if (!r.ok) {
      if (grid) {
        ErrorPanel.render(grid, {
          title: 'Couldn’t load workflows',
          detail: r.error,
          retry: () => load(),
        });
      }
      return;
    }
    _data = r.data || { workflows: [], categories: [] };
    const wfiCount = document.getElementById('wfi-count');
    if (wfiCount) wfiCount.textContent = _data.total || '';
    renderChips();
    render();
  }

  function refresh() { load(); }

  function setCategory(cat) { _activeCat = cat; renderChips(); render(); }

  function renderChips() {
    const el = document.getElementById('wfi-category-chips');
    if (!el) return;
    const chips = [{id:'all', count:_data.total || 0}].concat(_data.categories || []);
    el.innerHTML = chips.map(c => `<button class="wfi-category-chip ${_activeCat===c.id?'active':''}"
      data-action="wfi.category" data-category="${esc(c.id)}">${esc(c.id)} · ${c.count || 0}</button>`).join('');
  }

  function render() {
    const grid = document.getElementById('wfi-grid');
    if (!grid) return;
    const q = (document.getElementById('wfi-search') || {}).value || '';
    const ql = q.toLowerCase();
    const filtered = (_data.workflows || []).filter(w =>
      (_activeCat === 'all' || w.category === _activeCat) &&
      (!ql || (w.id + ' ' + (w.name || '') + ' ' + (w.description || '')).toLowerCase().includes(ql))
    );
    if (!filtered.length) {
      grid.innerHTML = '<div class="model-empty">No workflows match.</div>';
      return;
    }
    grid.innerHTML = filtered.map(w => {
      const refs = w.references || {};
      const refTags = []
        .concat((refs.plugins || []).map(p => `plugin:${p}`))
        .concat((refs.mcp_servers || []).map(s => `mcp:${s}`))
        .concat((refs.agents || []).map(a => `agent:${a}`))
        .slice(0, 6);
      // Pick a persona glyph from the workflow's category so the card
      // reads at a glance. Tags also feed the resolver as a fallback.
      const iconKey = _workflowIconKey(w);
      const iconSvg = (window.AgentIcons ? AgentIcons.svg(iconKey) : '');
      const tone    = (window.AgentIcons ? AgentIcons.tone(iconKey) : 'accent');
      const sourceChip = w.source === 'private'
        ? `<span class="wfi-card-source" title="Loaded from workflows-private/ overlay — never pushed to git">internal</span>`
        : '';
      // Card is NOT whole-clickable any more — that triggered
      // composerNewWorkflow() on every stray click (description text,
      // tags, mini-DAG) and silently wiped unsaved composer state.
      // Explicit buttons stay as the only action affordance.
      return `<div class="wfi-card" data-action="wfi.card" data-workflow-id="${esc(w.id)}" title="Double-click to deep-dive into the steps, prompts, and outputs">
        <div class="wfi-card-head">
          <span class="wfi-card-icon tone-${esc(tone)}" data-cat="${esc(w.category)}">${iconSvg}</span>
          <span class="wfi-card-title">${esc(w.name)}</span>
          ${sourceChip}
          <span class="wfi-card-cat">${esc(w.category)}</span>
        </div>
        <div class="wfi-card-desc">${esc(w.description || '—')}</div>
        <!-- Inline DAG preview — populated by _renderWorkflowMiniDag()
             lazily after the cards mount. Read-only visual; use the
             buttons below to act. -->
        <div class="wfi-card-dag" data-wf-id="${esc(w.id)}">
          <div class="wfi-card-dag-empty">loading preview…</div>
        </div>
        <div class="wfi-card-meta">
          <span>${w.steps} steps</span>
          ${w.version ? `<span>v${esc(w.version)}</span>` : ''}
          <span style="flex:1;text-align:right;color:var(--text-muted)">${esc(w.id)}</span>
        </div>
        <div class="wfi-card-refs">${refTags.map(t => `<span class="wfi-card-tag">${esc(t)}</span>`).join('')}</div>
        <div class="wfi-card-actions">
          <button class="action-btn accent" data-action="wfi.deep-dive">Deep Dive</button>
          <button class="action-btn" data-action="wfi.compose">Compose</button>
          <button class="action-btn" data-action="wfi.run">Run</button>
          <button class="action-btn" data-action="wfi.export">Export</button>
        </div>
      </div>`;
    }).join('');
    // Kick the lazy DAG-preview loader after the grid is painted.
    // Each card fetches its own /api/workflows/{id} in sequence with
    // a small delay so the index doesn't fan out N parallel requests.
    _hydrateDagPreviews(filtered);
  }

  // Lazy DAG-preview cache — keyed by workflow id. Survives across
  // re-renders so filtering doesn't refetch.
  const _dagCache = new Map();

  async function _hydrateDagPreviews(workflows) {
    // Process in small bursts so the API isn't slammed.
    for (let i = 0; i < workflows.length; i++) {
      const w = workflows[i];
      const slot = document.querySelector(`.wfi-card-dag[data-wf-id="${CSS.escape(w.id)}"]`);
      if (!slot) continue;
      let defn = _dagCache.get(w.id);
      if (!defn) {
        try {
          // silent + retries:0 — per-card soft-fail loop; retry/backoff
          // would stall the whole preview strip.
          const r = await Net.call(`/api/workflows/${encodeURIComponent(w.id)}`, { silent: true, retries: 0 });
          if (!r.ok) { slot.innerHTML = '<div class="wfi-card-dag-err">no preview</div>'; continue; }
          defn = r.data;
          _dagCache.set(w.id, defn);
        } catch (e) {
          slot.innerHTML = '<div class="wfi-card-dag-err">preview failed</div>';
          continue;
        }
        // Small breath so an index full of fresh workflows doesn't
        // stall the API. Skip the delay for cached entries.
        await new Promise(res => setTimeout(res, 60));
      }
      slot.innerHTML = _renderWorkflowMiniDag(defn);
    }
  }

  // Build an SVG mini-DAG silhouette for the card. The composer
  // canvas has space to show the *real* topology; at card scale
  // (~280×48px) what matters is "how many stages, where are the
  // fan-outs". So we collapse each topological rank into a single
  // horizontal slot and draw a pill instead of a circle when a rank
  // has >1 parallel node — with a small "×N" badge.
  //
  // Earlier versions used dagre's LR layout directly. That gave
  // geometrically-correct but visually-stacked results for fan-in
  // shapes like code-review (3 passes → synthesize) because dagre
  // places parallel siblings on different y-coords, which at 48px
  // tall reads as "blank dots under the heading."
  function _renderWorkflowMiniDag(defn) {
    const steps = (defn && Array.isArray(defn.steps)) ? defn.steps : [];
    if (!steps.length) {
      return '<div class="wfi-card-dag-empty">no steps</div>';
    }
    // Compute topological rank per step. If no depends_on is declared
    // anywhere, fall back to YAML order (engine behaviour).
    const stepIds = new Set(steps.map(s => s.id));
    const declaredDeps = steps.some(s => {
      const d = s.depends_on;
      return (Array.isArray(d) && d.length > 0) || (typeof d === 'string' && d);
    });
    let ranks;
    if (!declaredDeps) {
      // Implicit linear chain — every step is its own rank.
      ranks = steps.map((s, i) => ({ rank: i, step: s }));
    } else {
      const depMap = new Map(steps.map(s => [s.id, []]));
      steps.forEach(s => {
        const deps = Array.isArray(s.depends_on) ? s.depends_on
                   : (s.depends_on ? [s.depends_on] : []);
        depMap.set(s.id, deps.filter(d => stepIds.has(d)));
      });
      const rankOf = new Map();
      // Iterate until stable: a node's rank = max(deps.rank) + 1.
      let dirty = true, guard = steps.length + 2;
      while (dirty && guard-- > 0) {
        dirty = false;
        for (const s of steps) {
          const deps = depMap.get(s.id) || [];
          const r = deps.length === 0 ? 0
                  : Math.max(...deps.map(d => rankOf.has(d) ? rankOf.get(d) + 1 : 0));
          if (rankOf.get(s.id) !== r) { rankOf.set(s.id, r); dirty = true; }
        }
      }
      ranks = steps.map(s => ({ rank: rankOf.get(s.id) || 0, step: s }));
    }
    // Bucket steps by rank, preserving YAML order within a rank.
    const buckets = new Map();
    ranks.forEach(({ rank, step }) => {
      if (!buckets.has(rank)) buckets.set(rank, []);
      buckets.get(rank).push(step);
    });
    const sortedRanks = Array.from(buckets.keys()).sort((a, b) => a - b);
    return _renderRankSilhouette(sortedRanks.map(r => buckets.get(r)));
  }

  // Draw a left-to-right rank silhouette where parallel siblings within
  // a rank are STACKED VERTICALLY inside their slot (rather than
  // collapsed to a single pill) so fan-in / fan-out shapes are visually
  // unmistakable even at card scale. Earlier versions used a `pill+×N`
  // badge — geometrically compact but visually identical to a single
  // dot at 48px tall, which made every workflow card read as a flat
  // row of dots. Stacking the parallel nodes is what dagre does on the
  // composer canvas; this is just the compressed twin.
  function _renderRankSilhouette(rankBuckets) {
    const W = 280, H = 84, pad = 16;
    const NODE_R = 4;
    const n = rankBuckets.length;
    const xs = rankBuckets.map((_, i) => pad + (i / Math.max(1, n - 1)) * (W - 2 * pad));
    const midY = H / 2;
    // Compute the y-coordinate for the k-th node within a bucket of
    // size m — evenly distributed across the slot height, centered.
    const SLOT_INNER = H - 2 * pad;
    const yFor = (k, m) => {
      if (m === 1) return midY;
      const span = Math.min(SLOT_INNER, m * 14);  // 14 px per stacked node max
      return midY - span / 2 + (k * span) / (m - 1);
    };
    // Edges between rank i and rank i+1: connect every upstream node
    // to every downstream node. At card scale this draws the fan
    // outlines cleanly without needing real edge-by-edge dep tracking.
    const lines = [];
    for (let i = 0; i < rankBuckets.length - 1; i++) {
      const aBucket = rankBuckets[i], bBucket = rankBuckets[i + 1];
      const x1 = xs[i], x2 = xs[i + 1];
      aBucket.forEach((_, ai) => {
        const y1 = yFor(ai, aBucket.length);
        bBucket.forEach((_, bi) => {
          const y2 = yFor(bi, bBucket.length);
          lines.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" />`);
        });
      });
    }
    const nodes = rankBuckets.flatMap((bucket, i) => bucket.map((s, k) => {
      const cx = xs[i];
      const cy = yFor(k, bucket.length);
      const cls = s.is_decision ? 'mini-decision' : 'mini-step';
      return `<circle cx="${cx}" cy="${cy}" r="${NODE_R}" class="${cls}"><title>${esc(s.id)}</title></circle>`;
    }));
    return `<svg class="wfi-card-dag-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${lines.join('')}${nodes.join('')}</svg>`;
  }

  // ── obsolete pill helpers kept as no-op shims so any inline call
  //    sites that survived the migration don't crash; remove once
  //    git-grep is clean. ────────────────────────────────────────────
  function _renderRankSilhouette_legacy_pill(rankBuckets) {
    const W = 280, H = 70, pad = 14;
    const n = rankBuckets.length;
    const xs = rankBuckets.map((_, i) => pad + (i / Math.max(1, n - 1)) * (W - 2 * pad));
    const y = H / 2;
    const lines = xs.slice(1).map((x, i) =>
      `<line x1="${xs[i]}" y1="${y}" x2="${x}" y2="${y}" />`
    ).join('');
    const nodes = rankBuckets.map((bucket, i) => {
      const cx = xs[i];
      const isDecision = bucket.some(s => s.is_decision);
      const cls = isDecision ? 'mini-decision' : 'mini-step';
      const title = bucket.map(s => s.id).join(' · ');
      if (bucket.length === 1) {
        return `<circle cx="${cx}" cy="${y}" r="5" class="${cls}"><title>${esc(title)}</title></circle>`;
      }
      const pillW = 18, pillH = 10;
      const rx = cx - pillW / 2, ry = y - pillH / 2;
      return `<g><title>${esc(title)}</title>` +
             `<rect x="${rx}" y="${ry}" width="${pillW}" height="${pillH}" rx="5" ry="5" class="${cls} mini-pill" />` +
             `<text x="${cx}" y="${y + 3.5}" class="mini-pill-label" text-anchor="middle">×${bucket.length}</text>` +
             `</g>`;
    }).join('');
    return `<svg class="wfi-card-dag-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${lines}${nodes}</svg>`;
  }

  // Kept for the legacy "no edges declared" path — not used directly
  // any more (rank silhouette handles both cases) but referenced by
  // tests that snapshot the renderer.
  function _renderChainDag(steps) {
    return _renderRankSilhouette(steps.map(s => [s]));
  }

  // Resolve a workflow card's persona key from its category + tags +
  // id. Drives the icon-block tone in the card head.
  function _workflowIconKey(w) {
    const cat = String(w.category || '').toLowerCase();
    const CAT_TO_KEY = {
      security:   'security',
      code:       'coder',
      content:    'writer',
      research:   'retriever',
      data:       'data',
      devops:     'coordinator',
      automation: 'router',
      general:    'general',
    };
    if (CAT_TO_KEY[cat]) return CAT_TO_KEY[cat];
    // Fallback: keyword-scan against tags + name + id.
    const hay = [w.name, w.id, ...(w.tags || [])].filter(Boolean).join(' ').toLowerCase();
    if (window.AgentIcons) return AgentIcons.resolve({ name: hay });
    return 'general';
  }

  function openInComposer(id) {
    switchTab('dashboard');
    setTimeout(() => composerLoadById(id), 80);
  }

  // Deep dive — drill into a workflow's steps: model, what each prompt
  // expects (inputs/system prompt), what it produces (outputs), and the
  // sub-agents/tools/skills it uses. Edit affordance = open in Composer.
  async function deepDive(id) {
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:min(720px,95vw);max-height:90vh;overflow-y:auto;border-radius:6px;';
    inner.innerHTML = '<div class="model-empty">Loading workflow…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
    const asKey = x => typeof x === 'string' ? x : (x && (x.key || x.name) || JSON.stringify(x));
    try {
      const w = await Net.getJson('/api/workflows/' + encodeURIComponent(id));
      const steps = w.steps || [];
      const stepCard = s => {
        const ins = (s.inputs || []).map(asKey);
        const outs = (s.outputs || []).map(asKey);
        const caps = [
          ...(s.tools || []).map(t => 'tool:' + (t.tool_id || t.type || t.plugin_id || '?')),
          ...(s.skills || []).map(x => 'skill:' + asKey(x)),
        ];
        const sp = s.system_prompt || '', up = s.prompt || '';
        return `<div class="wf-dd-step">
          <div class="wf-dd-step-head">
            <span class="wf-dd-step-name">${esc(s.name || s.id)}</span>
            <span class="run-step-kind kind-${esc(s.kind || 'llm')}">${esc(s.kind || 'llm')}</span>
            <span style="flex:1"></span>
            <span class="wf-dd-step-model">${esc(s.model || s.role || '—')}</span>
          </div>
          ${s.depends_on && s.depends_on.length ? `<div class="wf-dd-meta">runs after: ${s.depends_on.map(esc).join(', ')}</div>` : ''}
          <div class="wf-dd-io"><span class="wf-dd-io-k">expects</span><span>${ins.length ? ins.map(esc).join(', ') : 'seed input'}</span></div>
          <div class="wf-dd-io"><span class="wf-dd-io-k">produces</span><span>${outs.length ? outs.map(esc).join(', ') : '—'}</span></div>
          ${caps.length ? `<div class="wf-dd-io"><span class="wf-dd-io-k">uses</span><span>${caps.map(esc).join(', ')}</span></div>` : ''}
          ${sp ? `<details class="wf-dd-prompt"><summary>system prompt · ${sp.length} ch</summary><pre>${esc(sp)}</pre></details>` : ''}
          ${up ? `<details class="wf-dd-prompt"><summary>prompt template · ${up.length} ch</summary><pre>${esc(up)}</pre></details>` : ''}
        </div>`;
      };
      inner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="font-weight:600;font-size:0.95rem;flex:1">${esc(w.name || id)}</div>
          <button class="action-btn xs ghost" data-action="wfi.close">×</button>
        </div>
        <div style="font-size:0.7rem;color:var(--text-dim);margin-bottom:12px">${esc(w.description || '')}</div>
        <div class="panel-label">Steps (${steps.length})</div>
        <div class="wf-dd-steps">${steps.map(stepCard).join('')}</div>
        <div style="display:flex;gap:6px;justify-content:flex-end;margin-top:14px">
          <button class="action-btn sm" data-action="wfi.modal-run" data-workflow-id="${esc(id)}">Run ▶</button>
          <button class="action-btn sm accent" data-action="wfi.modal-compose" data-workflow-id="${esc(id)}">Edit in Composer</button>
        </div>`;
    } catch (e) {
      inner.innerHTML = `<div class="model-empty" style="color:var(--red)">Failed to load workflow: ${esc(e.message)}</div>`;
    }
  }

  async function run(id) {
    // Kick the run via the async endpoint, then route the operator to
    // the Runs tab and auto-select the new run so they see the live
    // DAG instead of the legacy System → Runs page.
    try {
      // retries:0 — a retried kickoff would start two runs.
      const out = await Net.postJson('/api/workflows/run-async', { workflow_id: id, seed: {} }, { retries: 0 });
      switchTab('runs');
      // Give the tab dispatcher a beat to mount + fetch the list,
      // then drill into the new run.
      setTimeout(() => {
        if (window.RunsTab) {
          RunsTab.load();
          if (out.run_id) setTimeout(() => RunsTab.select(out.run_id), 150);
        }
      }, 80);
      if (window.Toast) Toast.success('Run started', `${id} · ${(out.run_id || '').slice(0, 12)}…`);
    } catch (e) {
      Toast.danger('Run failed', e.message);
    }
  }

  async function exportBundle(id) {
    try {
      const r = await Net.call(`/api/workflow-index/${encodeURIComponent(id)}/export`);
      if (!r.ok) { Toast.danger('Export failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      const bundle = r.data;
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${id}.bundle.json`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) { Toast.danger('Export error', e.message); }
  }

  function openImportDialog() { dfImportBundle(); }

  return { load, refresh, setCategory, openInComposer, deepDive, run, exportBundle, openImportDialog };
})();

// Delegated actions for the Workflow Index — category chips + cards
// re-render on every search keystroke. Card buttons resolve the workflow
// id from the card root's data-workflow-id; the deep-dive modal's former
// `${close}` snippet becomes wfi.close / compound wfi.modal-* actions.
(function () {
  const wfIdOf = el => {
    const host = el.closest('[data-workflow-id]');
    return host ? host.dataset.workflowId : '';
  };
  const closeModal = el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); };
  Actions.click({
    'wfi.category':  el => WorkflowIndex.setCategory(el.dataset.category),
    'wfi.deep-dive': el => WorkflowIndex.deepDive(wfIdOf(el)),
    'wfi.compose':   el => WorkflowIndex.openInComposer(wfIdOf(el)),
    'wfi.run':       el => WorkflowIndex.run(wfIdOf(el)),
    'wfi.export':    el => WorkflowIndex.exportBundle(wfIdOf(el)),
    'wfi.close':     closeModal,
    'wfi.modal-run':     el => { closeModal(el); WorkflowIndex.run(el.dataset.workflowId); },
    'wfi.modal-compose': el => { closeModal(el); WorkflowIndex.openInComposer(el.dataset.workflowId); }
  });
  Actions.on('dblclick', {
    'wfi.card': el => WorkflowIndex.deepDive(wfIdOf(el))
  });
})();

// ── Runs tab ────────────────────────────────────────────────────────
// A read-only mirror of the composer canvas, populated with whichever
// workflow run the operator selects. Per-step status overlays come from
// the same `is-running / is-completed / is-failed` classes the composer
// uses, so live runs animate identically here.
const RunsTab = (function () {
  let _rows = [];
  let _activeFilter = 'all';
  let _selectedId = null;
  let _editor = null;          // separate drawflow instance for this tab
  let _idMap = {};             // logical step id → drawflow node id
  let _pollHandle = null;
  let _currentRun = null;      // last fetched run (for cascade / context analysis)
  let _currentSteps = [];      // step list used for the rendered DAG
  let _drawerCopyTexts = [];   // bottom-drawer Copy payloads, keyed by data-idx
  let _sseSource = null;       // active EventSource for run stream (or null)
  const _expandedSteps = new Set();  // step_ids the user clicked to expand
  const _expandedOutputs = new Set();  // "stepId::key" of fully-expanded outputs

  function init() {
    // Defer the drawflow editor init until the first run is actually
    // selected — initializing now (while the tab content is still
    // hidden) gives drawflow a 0×0 container, which breaks layout
    // until the next window resize. The lazy path in _renderRunGraph
    // already calls _initEditor() before each render.
    //
    // load() runs immediately but uses requestAnimationFrame so the
    // browser has a chance to lay out the now-visible tab before the
    // fetch updates the rows container (avoids the "Loading…"
    // placeholder being immediately replaced by an empty grid that
    // hasn't had its scroll height resolved yet).
    requestAnimationFrame(() => load());
  }

  async function load(retry) {
    const box = document.getElementById('runs-tab-rows');
    if (!box) return;
    // Surface loading explicitly so the "Loading…" placeholder can't
    // linger if a previous render flushed it.
    box.innerHTML = '<div class="model-empty">Loading runs…</div>';
    try {
      // Net.call (not getJson): the 401 branch below needs the status code.
      // retries:0 so Net's backoff doesn't delay the 401 auth-bootstrap retry.
      const r = await Net.call('/api/workflows/runs?limit=40', { retries: 0 });
      if (r.status === 401) {
        // Auth hadn't initialized when the tab first opened. Retry
        // once after a beat — the global fetch wrapper will inject
        // the Bearer header now that Auth has bootstrapped.
        if (!retry) {
          await new Promise(res => setTimeout(res, 600));
          return load(true);
        }
        box.innerHTML = `<div class="model-empty" style="color:var(--red)">Not signed in — visit Admin to enter your license key.</div>`;
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = r.data;
      _rows = Array.isArray(data) ? data : (data.runs || []);
      const chip = document.getElementById('runs-tab-count');
      if (chip) chip.textContent = _rows.length ? `(${_rows.length})` : '';
      render();
    } catch (e) {
      box.innerHTML =
        `<div class="model-empty" style="color:var(--red)">Failed to load runs: ${esc(e.message)}.
          <br><br><button class="action-btn xs" data-action="runs.load">Retry</button></div>`;
    }
  }

  function setFilter(f) {
    _activeFilter = f;
    document.querySelectorAll('.runs-tab-filter').forEach(b => {
      b.classList.toggle('active', b.dataset.filter === f);
    });
    render();
  }

  function render() {
    const box = document.getElementById('runs-tab-rows');
    if (!box) return;
    const q = (document.getElementById('runs-tab-search') || {}).value || '';
    const ql = q.toLowerCase();
    const filtered = _rows.filter(r => {
      const s = (r.status || '').toLowerCase();
      if (_activeFilter === 'running'   && !['running', 'queued'].includes(s)) return false;
      if (_activeFilter === 'completed' && s !== 'completed') return false;
      if (_activeFilter === 'failed'    && !['failed', 'error'].includes(s)) return false;
      if (!ql) return true;
      const hay = [r.workflow_id, r.run_id, r.status].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(ql);
    });
    if (!filtered.length) {
      box.innerHTML = '<div class="model-empty">No runs match.</div>';
      return;
    }
    box.innerHTML = filtered.map(r => {
      const s = (r.status || 'unknown').toLowerCase();
      const ts = r.started_at || r.created_at || '';
      const sel = r.run_id === _selectedId ? ' selected' : '';
      return `<button type="button" class="btn-unstyled runs-tab-row${sel}" style="width:100%" data-run-id="${esc(r.run_id)}"
                   aria-pressed="${r.run_id === _selectedId}"
                   data-action="runs.select">
        <span class="runs-tab-row-title">${esc(r.workflow_id || '?')}</span>
        <span class="runs-tab-row-status ${esc(s)}">${esc(s)}</span>
        <span class="runs-tab-row-meta">${esc((r.run_id || '').slice(0, 12))} · ${esc(ts)}</span>
      </button>`;
    }).join('');
  }

  async function select(runId) {
    _selectedId = runId;
    render();
    // Deep-link: a selected run is shareable + reload-safe. Only when
    // the Runs tab owns the hash (select can fire from cross-tab jumps).
    try {
      if ((location.hash || '').indexOf('#/runs') === 0) {
        history.replaceState(null, '', '#/runs/' + encodeURIComponent(runId));
      }
    } catch (_) {}
    // Detail head + buttons.
    const meta = document.getElementById('runs-tab-detail-meta');
    if (meta) meta.textContent = `Loading ${runId.slice(0, 12)}…`;
    document.getElementById('runs-tab-graph-empty').setAttribute('hidden', '');
    // Stop any prior poller and SSE stream.
    if (_pollHandle) { clearInterval(_pollHandle); _pollHandle = null; }
    _unsubscribeSSE();
    // Hide the live plan panel until a plan.updated SSE frame arrives.
    const _livePlanPanel = document.getElementById('runs-tab-live-plan');
    if (_livePlanPanel) _livePlanPanel.hidden = true;
    // Fetch the run + the workflow definition so we can lay out the DAG.
    try {
      const run = await Net.getJson(`/api/workflows/runs/${encodeURIComponent(runId)}`);
      const wfId = run.workflow_id;
      let defn = null;
      if (wfId) {
        try {
          // silent + retries:0 — 404 for private workflows is expected if
          // the overlay doesn't carry the YAML; must not toast or retry.
          const dr = await Net.call(`/api/workflows/${encodeURIComponent(wfId)}`, { silent: true, retries: 0 });
          if (dr.ok) defn = dr.data;
        } catch (_) { /* fall through */ }
      }
      // Pass the run into the graph builder so it can reconstruct
      // the scaffold from step_results when the workflow definition
      // is missing or stale. Cache the run so other helpers
      // (cascade detection, context trace) can read it without a
      // round-trip.
      _currentRun = run;
      _renderRunGraph(defn, run);
      _applyStatus(run);
      _renderSteps(run);
      _renderContextTrace(run);
      _toggleActionButtons(run);
      // Live stream (SSE) + poll while running. SSE is additive — polling
      // keeps going as a fallback if the stream errors or isn't supported.
      if (['running', 'queued'].includes((run.status || '').toLowerCase())) {
        _subscribeSSE(runId);
        _pollHandle = setInterval(async () => {
          try {
            // silent + retries:0 — poll loop: no toast spam, and Net's
            // backoff must not stack with the 1.5s interval timer.
            const r2 = await Net.call(`/api/workflows/runs/${encodeURIComponent(runId)}`, { silent: true, retries: 0 });
            if (!r2.ok) return;
            const run2 = r2.data;
            _currentRun = run2;
            _applyStatus(run2);
            _renderSteps(run2);
            _renderContextTrace(run2);
            _toggleActionButtons(run2);
            if (['completed', 'failed', 'canceled', 'error'].includes((run2.status || '').toLowerCase())) {
              clearInterval(_pollHandle); _pollHandle = null;
              // Refresh the list so the row shows the new status.
              load();
            }
          } catch (_) { /* keep trying */ }
        }, 1500);
      }
    } catch (e) {
      const meta2 = document.getElementById('runs-tab-detail-meta');
      if (meta2) meta2.textContent = `Error: ${e.message}`;
      // Re-show the empty hint so the right pane isn't a void.
      const empty = document.getElementById('runs-tab-graph-empty');
      if (empty) empty.removeAttribute('hidden');
      // Wipe step strip + context to avoid stale data from a prior run.
      const stepsBody = document.getElementById('runs-tab-steps-body');
      if (stepsBody) stepsBody.innerHTML = `<div class="model-empty" style="color:var(--red)">Couldn't load run: ${esc(e.message)}</div>`;
      const ctxBody = document.getElementById('runs-tab-context-body');
      if (ctxBody) ctxBody.innerHTML = '<div class="model-empty">—</div>';
    }
  }

  function _initEditor() {
    const container = document.getElementById('runs-tab-canvas');
    if (!container || typeof Drawflow === 'undefined') return;
    // Defensive: if the container was previously initialized at 0×0
    // (because the tab was hidden), recreating wipes any stale state.
    if (_editor) {
      try { _editor.clear(); } catch (_) {}
    }
    // Drawflow appends its own children to the container; wipe before
    // re-init to avoid duplicated DOM if we re-init.
    container.innerHTML = '';
    _editor = new Drawflow(container);
    _editor.reroute = true;
    _editor.reroute_fix_curvature = true;
    // 'fixed' silently no-ops addConnection in some drawflow builds —
    // keep 'edit' so edges wire, then disable pan/drag via the
    // .readonly-canvas CSS class which routes pointer-events around
    // drawflow's mousedown→pan handler on the wrapper.
    _editor.editor_mode = 'edit';
    _editor.start();
    container.classList.add('readonly-canvas');

    // Click-to-drill: when the operator clicks a node card, find the
    // matching step row in the strip below and scroll it into view
    // + open it. Bound on the container so it survives drawflow's
    // node re-renders during graph updates.
    container.addEventListener('click', (e) => {
      const nodeEl = e.target.closest('.drawflow-node');
      if (!nodeEl) return;
      const m = nodeEl.id.match(/^node-(\d+)$/);
      if (!m) return;
      const dfId = m[1];
      // Resolve dfId → step.id via the _idMap we built at render time.
      const stepId = Object.keys(_idMap).find(k => String(_idMap[k]) === dfId);
      if (!stepId) return;
      // Auto-expand the step's row in the result strip + scroll it
      // into view so the operator sees its error / output immediately.
      _expandedSteps.add(stepId);
      if (_currentRun) _renderSteps(_currentRun);
      // Brief flash on the matching step row so the operator sees
      // where in the strip their click landed.
      setTimeout(() => {
        const row = document.querySelector(
          `#runs-tab-steps-body .ws-run-step[data-step-id="${CSS.escape(stepId)}"]`
        );
        if (row) {
          row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          row.classList.add('flash-highlight');
          setTimeout(() => row.classList.remove('flash-highlight'), 1200);
        }
      }, 30);
    });
  }

  function _renderRunGraph(defn, run) {
    if (!_editor) _initEditor();
    if (!_editor) return;
    // Wipe any previous render.
    try { _editor.clear(); } catch (_) {}
    _idMap = {};

    // Build the step list. If we have a workflow definition use it;
    // otherwise reconstruct the scaffold from the run's step_results
    // (preserves the agent process layout even when the workflow YAML
    // has been deleted, renamed, or changed since the run executed).
    let steps = (defn && Array.isArray(defn.steps) && defn.steps.length)
      ? defn.steps.map(s => ({ ...s }))
      : [];

    // Merge: ensure every step_id from results exists as a step. Adds
    // any "phantom" steps the run actually executed but that aren't
    // in the current definition (e.g. dynamically inserted steps).
    const resultsById = new Map();
    (run && run.step_results || []).forEach(r => {
      if (r && r.step_id) resultsById.set(r.step_id, r);
    });
    const knownIds = new Set(steps.map(s => s.id));
    Array.from(resultsById.keys()).forEach(id => {
      if (!knownIds.has(id)) {
        const r = resultsById.get(id);
        steps.push({
          id, name: id,
          role: r.role || 'general',
          // Marker so we can label "reconstructed" nodes in the UI.
          _reconstructed: true,
        });
      }
    });

    // Determine the depends_on linkage. If the definition supplies it,
    // use it. Otherwise infer a linear chain from the order step_results
    // were appended (which is the engine's execution order).
    const hasDefDeps = (defn && Array.isArray(defn.steps) &&
      defn.steps.some(s => Array.isArray(s.depends_on) ? s.depends_on.length : !!s.depends_on));
    if (!hasDefDeps && run && Array.isArray(run.step_results)) {
      const ordered = run.step_results.map(r => r.step_id).filter(Boolean);
      const byId = new Map(steps.map(s => [s.id, s]));
      for (let i = 1; i < ordered.length; i++) {
        const cur = byId.get(ordered[i]);
        if (cur && !cur.depends_on) cur.depends_on = [ordered[i - 1]];
      }
    }

    // Spawn a node per step using the composer's same dfNodeHtml so the
    // visual is identical. We use logical positions; auto-layout below
    // re-flows via dagre.
    steps.forEach((step, i) => {
      const data = {
        id: step.id, name: step.name || step.id,
        role: step.role || 'general',
        system_prompt: step.system_prompt || '',
        outputs: Array.isArray(step.outputs) ? step.outputs : ['result'],
        output_format: (step.output_parser && step.output_parser.format) || 'raw',
        quality_gates: [], inputs: [],
        is_decision: !!step.is_decision,
        persona: step.persona ||
          (window.AgentIcons ? AgentIcons.resolve({ role: step.role, name: step.name }) : 'general'),
        skills: step.skills || [], tools: step.tools || [],
        _reconstructed: !!step._reconstructed,
      };
      const x = 80 + (i % 4) * 220;
      const y = 60 + Math.floor(i / 4) * 140;
      const numOut = data.outputs.length > 1 && data.is_decision ? data.outputs.length : 1;
      const dfId = _editor.addNode(data.id, 1, numOut, x, y, data.id, {}, dfNodeHtml(data));
      _idMap[data.id] = dfId;
      // Tag the wrapper for reconstructed-step markers in CSS.
      if (data._reconstructed) {
        const el = document.querySelector(`#runs-tab-canvas #node-${dfId}`);
        if (el) el.classList.add('is-reconstructed');
      }
    });
    // Connect via depends_on (definition or inferred linear chain).
    steps.forEach((step) => {
      const tgt = _idMap[step.id];
      if (!tgt) return;
      const deps = Array.isArray(step.depends_on) ? step.depends_on
                 : (step.depends_on ? [step.depends_on] : []);
      deps.forEach(dep => {
        const src = _idMap[dep];
        if (!src) return;
        try { _editor.addConnection(src, tgt, 'output_1', 'input_1'); } catch (_) {}
      });
    });

    // START / END anchor nodes — make the workflow's input (seed) and final
    // deliverable (terminal-step outputs) explicit, bracketing the DAG.
    try {
      const depOf = s => Array.isArray(s.depends_on) ? s.depends_on : (s.depends_on ? [s.depends_on] : []);
      const seedKeys = [...new Set(steps.flatMap(s =>
        (s.inputs || []).filter(i => typeof i === 'string' && i.startsWith('seed.')).map(i => i.slice(5))))];
      const depended = new Set(steps.flatMap(depOf));
      const rootSteps = steps.filter(s => depOf(s).length === 0);
      const terminalSteps = steps.filter(s => !depended.has(s.id));
      const deliverable = [...new Set(terminalSteps.flatMap(s => Array.isArray(s.outputs) ? s.outputs : []))];
      const keyChips = arr => (arr.length ? arr : ['—']).map(k => `<span>${esc(k)}</span>`).join('');

      const startHtml = `<div class="wf-anchor wf-anchor-start"><div class="wf-anchor-label">▶ START</div><div class="wf-anchor-sub">seed input</div><div class="wf-anchor-keys">${keyChips(seedKeys)}</div></div>`;
      const startId = _editor.addNode('__start__', 0, 1, 0, 0, '__start__', {}, startHtml);
      rootSteps.forEach(s => { const t = _idMap[s.id]; if (t) { try { _editor.addConnection(startId, t, 'output_1', 'input_1'); } catch (_) {} } });

      const endHtml = `<div class="wf-anchor wf-anchor-end"><div class="wf-anchor-label">■ END</div><div class="wf-anchor-sub">deliverable</div><div class="wf-anchor-keys">${keyChips(deliverable.length ? deliverable : ['output'])}</div></div>`;
      const endId = _editor.addNode('__end__', 1, 0, 0, 0, '__end__', {}, endHtml);
      terminalSteps.forEach(s => { const src = _idMap[s.id]; if (src) { try { _editor.addConnection(src, endId, 'output_1', 'input_1'); } catch (_) {} } });
    } catch (_) { /* anchors are best-effort decoration */ }
    // Stash the resolved step list for cascade detection.
    _currentSteps = steps;
    // Auto-layout. We reuse the composer's dagre helper but target our
    // separate editor — swap dfEditor pointer temporarily.
    try { _runTabAutoLayout(); } catch (e) { console.warn('runs auto-layout:', e); }
  }

  function _runTabAutoLayout() {
    if (typeof dagre === 'undefined' || !_editor) return;
    const exported = _editor.export();
    const nodes = exported.drawflow.Home.data;
    const ids = Object.keys(nodes);
    if (!ids.length) return;
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 90, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    const NODE_W = 200, NODE_H = 90;
    ids.forEach(id => g.setNode(id, { width: NODE_W, height: NODE_H }));
    ids.forEach(id => {
      Object.keys(nodes[id].outputs || {}).forEach(k => {
        (nodes[id].outputs[k].connections || []).forEach(c => g.setEdge(id, String(c.node)));
      });
    });
    dagre.layout(g);
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    ids.forEach(id => {
      const p = g.node(id); if (!p) return;
      minX = Math.min(minX, p.x - NODE_W/2); minY = Math.min(minY, p.y - NODE_H/2);
      maxX = Math.max(maxX, p.x + NODE_W/2); maxY = Math.max(maxY, p.y + NODE_H/2);
    });
    const canvas = document.getElementById('runs-tab-canvas');
    const rect = canvas ? canvas.getBoundingClientRect() : { width: 1000, height: 600 };
    const bboxW = (maxX - minX) || NODE_W;
    const bboxH = (maxY - minY) || NODE_H;
    const offX = Math.max(40, (rect.width  - bboxW) / 2 - minX);
    const offY = Math.max(40, (rect.height - bboxH) / 2 - minY);
    ids.forEach(id => {
      const p = g.node(id); if (!p) return;
      const left = p.x - NODE_W/2 + offX;
      const top  = p.y - NODE_H/2 + offY;
      try {
        const d = _editor.drawflow.drawflow.Home.data[id];
        if (d) { d.pos_x = left; d.pos_y = top; }
      } catch (_) {}
      const el = document.querySelector(`#runs-tab-canvas #node-${id}`);
      if (el) { el.style.left = left + 'px'; el.style.top = top + 'px'; }
    });
    ids.forEach(id => { try { _editor.updateConnectionNodes(`node-${id}`); } catch (_) {} });

    // Fit-to-screen: zoom the whole precanvas so EVERY node is visible (the
    // run-detail graph should always fit). Measure the ACTUAL rendered node
    // bounds (offset*) — dagre's NODE_H estimate is smaller than the real node
    // cards. Deferred a frame so node cards have reached their final height
    // (their content/fonts grow them taller after addNode).
    requestAnimationFrame(() => { try {
      const cvEl = document.getElementById('runs-tab-canvas');
      const pre = _editor && _editor.precanvas;
      if (cvEl && pre) {
        let bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
        ids.forEach(id => {
          const el = document.querySelector(`#runs-tab-canvas #node-${id}`);
          if (!el) return;
          const x = parseFloat(el.style.left) || 0, y = parseFloat(el.style.top) || 0;
          bx0 = Math.min(bx0, x); by0 = Math.min(by0, y);
          bx1 = Math.max(bx1, x + el.offsetWidth); by1 = Math.max(by1, y + el.offsetHeight);
        });
        const gw = bx1 - bx0, gh = by1 - by0;
        const cw = cvEl.clientWidth, ch = cvEl.clientHeight, pad = 80;
        if (gw > 0 && gh > 0 && cw > 0 && ch > 0) {
          // 0.94 safety factor — connection curves bow ~15-20px beyond the
          // node bounding box, so leave headroom or a sliver clips.
          const z = Math.min(1, ((cw - pad) / gw) * 0.94, ((ch - pad) / gh) * 0.94);
          const cx = (cw - gw * z) / 2 - bx0 * z;
          const cy = (ch - gh * z) / 2 - by0 * z;
          _editor.zoom = z; _editor.zoom_last_value = z;
          _editor.canvas_x = cx; _editor.canvas_y = cy;
          pre.style.transform = 'translate(' + cx + 'px, ' + cy + 'px) scale(' + z + ')';
        }
      }
    } catch (_) { /* fit is best-effort */ } });
  }

  // A run is "zombie" if its status says running/queued but it
  // shipped no progress in over ZOMBIE_MS. Container restarts
  // mid-run leave the persisted status frozen, so we detect this in
  // the UI and surface a banner + an option to force-fail.
  const ZOMBIE_MS = 10 * 60 * 1000;  // 10 minutes without progress
  function _isZombieRun(run) {
    const s = (run.status || '').toLowerCase();
    if (!['running', 'queued'].includes(s)) return false;
    const started = Date.parse(run.started_at || '') || 0;
    if (!started) return false;
    const ageMs = Date.now() - started;
    if (ageMs < ZOMBIE_MS) return false;
    // If at least one step finished recently the run is still alive.
    const results = run.step_results || [];
    if (!results.length) return true;
    // Check the last step's completion timestamp if any.
    const lastDone = results
      .filter(r => r && (r.completed_at || r.started_at))
      .map(r => Date.parse(r.completed_at || r.started_at || '') || 0);
    const newest = lastDone.length ? Math.max(...lastDone) : started;
    return (Date.now() - newest) > ZOMBIE_MS;
  }

  function _applyStatus(run) {
    const results = run.step_results || [];
    const statusMap = new Map();
    results.forEach(r => { if (r && r.step_id) statusMap.set(r.step_id, r.status); });
    const planned = Object.keys(_idMap);
    let completed = 0, current = '';
    const statusLower = (run.status || '').toLowerCase();
    const terminal = ['completed', 'failed', 'error', 'canceled'].includes(statusLower);
    const zombie = _isZombieRun(run);
    planned.forEach(stepId => {
      const dfId = _idMap[stepId];
      const el = document.querySelector(`#runs-tab-canvas #node-${dfId}`);
      if (!el) return;
      el.classList.remove('is-queued','is-running','is-completed','is-failed','is-skipped');
      const st = statusMap.get(stepId);
      if (st === 'completed') { el.classList.add('is-completed'); completed += 1; }
      else if (st === 'running') { el.classList.add('is-running'); current = stepId; }
      else if (st === 'failed' || st === 'error') { el.classList.add('is-failed'); }
      else if (st === 'skipped') { el.classList.add('is-skipped'); }
      else if (!terminal) { el.classList.add('is-queued'); }
    });

    // Stop the live poller for zombie runs — there's nothing to
    // observe and re-fetching the same orphaned payload every 1.5s
    // is just noise.
    if (zombie && _pollHandle) {
      clearInterval(_pollHandle);
      _pollHandle = null;
    }

    // Update the chip. For a healthy running run with 0 steps yet,
    // show an indeterminate bar (stripe animation) so the operator
    // sees motion. For zombies, show a static "stalled" badge.
    const chip = document.getElementById('runs-tab-progress-chip');
    const cur = document.getElementById('runs-tab-current');
    const cnt = document.getElementById('runs-tab-chip-count');
    const bar = document.getElementById('runs-tab-bar');
    const spinner = document.getElementById('runs-tab-spinner');
    if (chip) chip.hidden = false;
    if (chip) chip.classList.toggle('is-zombie', zombie);
    if (cur) {
      if (zombie) cur.textContent = 'stalled — engine likely restarted mid-run';
      else cur.textContent = current || (statusLower === 'queued' ? 'queued' : (run.workflow_id || '—'));
    }
    if (cnt) cnt.textContent = `${completed}/${planned.length || 0}`;
    if (bar) {
      // Indeterminate animation when there's a count of zero in a non-
      // terminal state; concrete % otherwise.
      if (!terminal && !zombie && planned.length && completed === 0) {
        bar.classList.add('is-indeterminate');
        bar.style.width = '100%';
      } else {
        bar.classList.remove('is-indeterminate');
        bar.style.width = `${planned.length ? (completed / planned.length) * 100 : 0}%`;
      }
    }
    if (spinner) {
      spinner.classList.toggle('done', statusLower === 'completed');
      spinner.classList.toggle('failed', ['failed', 'error', 'canceled'].includes(statusLower) || zombie);
    }
    // Detail meta line + data-status attribute (read by Playwright selectors
    // and the SSE run.status handler for test assertions).
    const meta = document.getElementById('runs-tab-detail-meta');
    if (meta) {
      const tag = zombie ? `${run.status || '?'} (stalled)` : (run.status || '?');
      meta.textContent = `${run.workflow_id || '?'} · ${tag} · ${completed}/${planned.length} steps`;
      meta.dataset.status = statusLower;
    }
    // Zombie banner above the steps strip — gives the operator a
    // clear surface to mark the run as failed.
    _renderZombieBanner(run, zombie);
  }

  function _renderZombieBanner(run, zombie) {
    const stepsBody = document.getElementById('runs-tab-steps-body');
    if (!stepsBody) return;
    const existing = document.getElementById('runs-tab-zombie-banner');
    if (existing) existing.remove();
    if (!zombie) return;
    const startedAgo = (() => {
      const t = Date.parse(run.started_at || '') || 0;
      if (!t) return 'unknown time';
      const mins = Math.round((Date.now() - t) / 60000);
      return mins > 60 ? `${Math.round(mins / 60)}h ${mins % 60}m ago` : `${mins}m ago`;
    })();
    const banner = document.createElement('div');
    banner.id = 'runs-tab-zombie-banner';
    banner.className = 'runs-zombie-banner';
    banner.innerHTML = `<span class="zb-icon">!</span>
      <span class="zb-msg">
        This run started <strong>${esc(startedAgo)}</strong> and has shipped no
        progress for over 10 minutes. The engine likely restarted mid-run,
        leaving the run status frozen as <code>${esc(run.status || '')}</code>.
      </span>
      <button class="action-btn xs" data-action="runs.mark-failed">Mark Failed</button>`;
    stepsBody.prepend(banner);
  }

  async function markFailed() {
    if (!_selectedId) return;
    const ok = await Confirm.ask({ title: 'Mark run failed', body: 'Mark this stalled run as failed? This persists status="failed" so the UI stops polling.', okLabel: 'Mark Failed', danger: true });
    if (!ok) return;
    try {
      // The cancel endpoint accepts running/queued and marks them
      // canceled — which is the closest existing signal we have for
      // "this run is dead, stop polling." If the backend grows a
      // dedicated mark-failed verb later, swap the URL.
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(_selectedId)}/cancel`, {}, { retries: 0 });
      if (window.Toast) Toast.info('Run marked', 'Engine cancel sent; refreshing.');
      await load();
      select(_selectedId);
    } catch (e) {
      if (window.Toast) Toast.danger('Could not mark failed', e.message);
    }
  }

  // ── Sandbox / code-exec helpers (Task 18) ────────────────────────

  // Returns an HTML snippet summarising the code-exec result for a step.
  // Rendered inside the expandedBody section when code_exit_code is non-null.
  function _renderSandboxCodePanel(s) {
    if (s.code_exit_code == null) return '';
    const exitOk = s.code_exit_code === 0;
    const exitCls = exitOk ? 'ok' : 'fail';
    const tierChip = s.tier_used
      ? `<span class="scp-chip">${esc(s.tier_used)}</span>`
      : '';
    const exitChip = `<span class="scp-chip ${exitCls}">exit ${s.code_exit_code}</span>`;
    const rssChip = s.peak_rss_mb != null
      ? `<span class="scp-chip dim">${s.peak_rss_mb.toFixed(0)} MB</span>`
      : '';
    const files = Array.isArray(s.files_produced) ? s.files_produced : [];
    const filesChip = `<span class="scp-chip dim">${files.length} file${files.length === 1 ? '' : 's'}</span>`;
    const scopeChip = s.promoted
      ? `<span class="scp-chip ok">promoted</span>`
      : `<span class="scp-chip dim">in-scratch</span>`;
    const approvalChip = s.approval_status
      ? `<span class="scp-chip ${s.approval_status === 'approved' ? 'ok' : (s.approval_status === 'rejected' ? 'fail' : 'dim')}">${esc(s.approval_status)}</span>`
      : '';
    return `<div class="sandbox-code-panel">
      <span class="scp-label">code</span>
      ${tierChip}${exitChip}${rssChip}${filesChip}${scopeChip}${approvalChip}
    </div>`;
  }

  // Renders the approval-gate bar and prepends it to stepsBody.
  // Called from _renderSteps whenever run.status === 'awaiting_approval'
  // and run.pending_gate is present.
  function _renderApprovalGate(run, body) {
    const existing = document.getElementById('runs-tab-approval-gate');
    if (existing) existing.remove();
    if ((run.status || '').toLowerCase() !== 'awaiting_approval') return;
    const gate = run.pending_gate;
    if (!gate) return;
    const files = Array.isArray(gate.files) ? gate.files : [];
    const metaParts = [];
    if (gate.tier)    metaParts.push(`tier ${esc(gate.tier)}`);
    if (gate.network) metaParts.push(`net ${esc(gate.network)}`);
    metaParts.push(`${files.length} file${files.length === 1 ? '' : 's'} out`);
    const questionLine = gate.question
      ? `<div class="agb-question">${esc(gate.question)}</div>`
      : '';
    const el = document.createElement('div');
    el.id = 'runs-tab-approval-gate';
    el.className = 'approval-gate-bar';
    el.innerHTML = `
      <div class="agb-head">
        <span class="agb-icon">?</span>
        <span class="agb-title">AWAITING APPROVAL</span>
        <span class="agb-meta">${metaParts.join(' · ')}</span>
      </div>
      ${questionLine}
      <pre class="agb-code">${esc(gate.proposed_code || '')}</pre>
      <div class="agb-actions">
        <button class="action-btn xs"
                style="color:var(--green);border-color:var(--green)"
                data-action="runs.gate" data-run-id="${esc(run.run_id)}" data-gate-id="${esc(gate.gate_id)}" data-decision="approve">Approve</button>
        <button class="action-btn xs"
                style="color:var(--red);border-color:var(--red)"
                data-action="runs.gate" data-run-id="${esc(run.run_id)}" data-gate-id="${esc(gate.gate_id)}" data-decision="reject">Reject</button>
      </div>`;
    body.prepend(el);
  }

  // POSTs approve/reject to the backend then re-selects the run to refresh.
  async function resolveGate(runId, gateId, action) {
    try {
      // retries:0 — HITL gate decisions must fire exactly once.
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(gateId)}`, { action }, { retries: 0 });
      if (window.Toast) Toast.info(action === 'approve' ? 'Gate approved' : 'Gate rejected',
        `Run ${runId.slice(0, 12)}… will ${action === 'approve' ? 'continue' : 'be halted'}.`);
      select(runId);
    } catch (e) {
      if (window.Toast) Toast.danger('Gate action failed', e.message);
      else console.error('resolveGate failed:', e);
    }
  }

  function _renderSteps(run) {
    const body = document.getElementById('runs-tab-steps-body');
    if (!body) return;
    const results = run.step_results || [];
    // Compute cascade markers. A "root failure" is a step whose
    // status is failed/error. A "starved" step is one that depended
    // on a root failure and either didn't run (no result) or whose
    // workspace input was the failed step's output.
    const cascade = _computeCascade(run);

    // Top-level header — root error line first if any.
    const errorBanner = (run.status || '').toLowerCase() === 'failed' && run.error
      ? `<div class="run-error-banner">
           <span class="run-error-banner-icon">!</span>
           <span class="run-error-banner-text">${esc(run.error)}</span>
         </div>`
      : '';

    if (!results.length) {
      body.innerHTML = errorBanner + '<div class="model-empty">No step results yet.</div>';
      return;
    }

    const rows = results.map(s => {
      const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
      const status = (s.status || '').toLowerCase();
      const cls = status === 'completed' ? 'ok' : (['failed', 'error'].includes(status) ? 'fail' : 'pending');
      const isExpanded = _expandedSteps.has(s.step_id);
      const isRoot = cascade.roots.has(s.step_id);
      const isStarved = cascade.starved.has(s.step_id);
      const retries = s.retries || 0;
      const tokens = (s.token_count || {}).total_tokens || 0;

      // One-line preview of the error, full text revealed in the
      // expanded section.
      const errOneLine = s.error ? esc(String(s.error).split('\n')[0].slice(0, 90)) : '';
      const errFull = s.error ? esc(s.error) : '';

      const badges = [];
      if (isRoot)     badges.push(`<span class="run-step-badge fail">root</span>`);
      if (isStarved)  badges.push(`<span class="run-step-badge starved" title="Downstream step couldn't get its expected context from an upstream failure">starved</span>`);
      if (retries)    badges.push(`<span class="run-step-badge dim">${retries}× retry</span>`);

      const expandedBody = isExpanded ? `
        <div class="run-step-expanded">
          ${s.error ? `<div class="run-step-row-kv error">
            <span class="run-step-row-k">error</span>
            <pre class="run-step-error-text">${errFull}</pre>
          </div>` : ''}
          ${tokens ? `<div class="run-step-row-kv">
            <span class="run-step-row-k">tokens</span>
            <span>${tokens.toLocaleString()}</span>
          </div>` : ''}
          ${s.model_used ? `<div class="run-step-row-kv">
            <span class="run-step-row-k">model</span>
            <span>${esc(s.model_used)}</span>
          </div>` : ''}
          ${s.started_at ? `<div class="run-step-row-kv">
            <span class="run-step-row-k">started</span>
            <span>${esc(s.started_at)}</span>
          </div>` : ''}
          ${_renderStepPrompt(s)}
          ${_renderStepOutputs(run, s.step_id)}
          ${_renderSandboxCodePanel(s)}
        </div>` : '';

      return `<div class="ws-run-step ws-run-step-${cls} ${isRoot ? 'is-root-fail' : ''} ${isStarved ? 'is-starved' : ''}"
                   data-step-id="${esc(s.step_id)}">
        <div class="ws-run-step-head" role="button" tabindex="0"
             data-action="runs.step-detail"
             title="Open full step detail">
          <button type="button" class="btn-unstyled run-step-caret" title="Quick inline peek"
                aria-label="Toggle inline details for step ${esc(s.step_id)}" aria-expanded="${isExpanded}"
                data-action="runs.step-expand">${isExpanded ? '▾' : '▸'}</button>
          <span class="ws-run-step-id">${esc(s.step_id)}</span>
          <span class="run-step-kind kind-${esc(s.kind || 'llm')}" title="step kind">${esc(s.kind || 'llm')}</span>
          <span class="ws-run-step-model">${esc(s.model_used || '—')}</span>
          ${badges.join('')}
          <span style="flex:1"></span>
          ${errOneLine ? `<span class="ws-run-step-err-preview">${errOneLine}</span>` : ''}
          <span class="ws-run-step-dur">${dur}</span>
          <span class="ws-run-step-status">${esc(s.status)}</span>
        </div>
        ${expandedBody}
      </div>`;
    }).join('');

    // Cascade summary if there's a root failure.
    let cascadeSummary = '';
    if (cascade.roots.size) {
      const rootList = Array.from(cascade.roots).slice(0, 3).join(', ');
      const starvedList = Array.from(cascade.starved);
      cascadeSummary = `<div class="run-cascade-summary">
        <span class="run-cascade-label">CASCADE</span>
        <span>Root failure${cascade.roots.size > 1 ? 's' : ''}: <code>${esc(rootList)}</code>.</span>
        ${starvedList.length
          ? `<span>Starved downstream: <code>${esc(starvedList.slice(0, 5).join(', '))}</code>${starvedList.length > 5 ? ` +${starvedList.length - 5}` : ''}.</span>`
          : '<span>No downstream steps were starved (run halted at root).</span>'}
      </div>`;
    }

    // START / END entries bracketing the step list — the workflow's explicit
    // entry point (seed) and output (deliverable). Clickable to inspect the
    // ACTUAL values (e.g. the code that was reviewed, the review produced).
    const seed = (run.context && run.context.seed) || {};
    const seedEntries = Object.entries(seed);
    const ws = (run.context && run.context.workspace) || {};
    const terminal = results[results.length - 1];
    const delivEntries = terminal ? Object.entries(ws[terminal.step_id] || {}) : [];
    const previewOf = entries => {
      if (!entries.length) return 'none';
      const v = entries[0][1];
      const s = typeof v === 'string' ? v : JSON.stringify(v);
      return s.replace(/\s+/g, ' ').slice(0, 44) + (s.length > 44 ? '…' : '');
    };
    const anchorRow = (cls, glyph, label, kind, entries) => `
      <button type="button" class="btn-unstyled ws-run-step ws-run-anchor-row ${cls}" style="width:100%" data-action="runs.anchor-detail" data-kind="${kind}" title="Open the full ${kind} (actual values)">
        <span class="run-step-caret">${glyph}</span>
        <span class="ws-run-step-id">${label}</span>
        <span class="ws-anchor-count">${entries.length} field${entries.length === 1 ? '' : 's'}</span>
        <span style="flex:1"></span>
        <span class="ws-anchor-keys-inline">${entries.length ? esc(entries.map(e => e[0]).join(', ')) + ' · ' + esc(previewOf(entries)) : '—'}</span>
      </button>`;
    const startRow = anchorRow('ws-anchor-start-row', '▶', 'START · seed', 'seed', seedEntries);
    const endRow = anchorRow('ws-anchor-end-row', '■', 'END · deliverable', 'deliverable', delivEntries);

    body.innerHTML = errorBanner + cascadeSummary + startRow + rows + endRow;
    // Approval gate bar — rendered above step rows when a human-in-the-loop
    // gate is waiting. Uses prepend so it appears above the error banner too.
    _renderApprovalGate(run, body);
  }

  // Inspect run.context.workspace for the step's outputs. Returns
  // HTML showing what fields the step wrote (so the operator can
  // trace context handoff). Empty when the step has nothing in
  // workspace (e.g. it failed before producing output).
  function _renderStepPrompt(s) {
    // What actually went IN to the model — the rendered system + user prompt
    // captured on the StepResult at execution time. Each is click-to-expand to
    // its full text (reusing the output-viewer styling). LLM steps populate
    // these; non-LLM steps and pre-capture runs leave them null.
    const items = [];
    if (s.rendered_system_prompt) items.push(['system prompt', s.rendered_system_prompt]);
    if (s.rendered_prompt) items.push(['prompt', s.rendered_prompt]);
    if (!items.length) {
      return `<div class="run-step-row-kv">
        <span class="run-step-row-k">input</span>
        <span style="color:var(--text-muted)">prompt not captured (re-run this workflow to record it)</span>
      </div>`;
    }
    const rows = items.map(([label, text]) => {
      const key = '⟦' + label + '⟧';
      const open = _expandedOutputs.has(s.step_id + '::' + key);
      const preview = text.replace(/\s+/g, ' ').slice(0, 60) + (text.length > 60 ? '…' : '');
      return `<div class="run-step-output${open ? ' open' : ''}">
        <button type="button" class="btn-unstyled run-step-output-head" style="width:100%" aria-expanded="${open}" data-action="runs.output-toggle" data-step-id="${esc(s.step_id)}" data-key="${esc(key)}">
          <span class="run-step-caret">${open ? '▾' : '▸'}</span>
          <span class="ctx-field-k">${esc(label)}</span>
          ${open ? '' : `<span class="ctx-field-v">${esc(preview)}</span>`}
          <span style="flex:1"></span>
          <span class="run-step-output-meta">${text.length} chars</span>
        </button>
        ${open ? `<pre class="run-step-output-full">${esc(text)}</pre>` : ''}
      </div>`;
    }).join('');
    return `<div class="run-step-row-kv run-step-outputs-kv">
      <span class="run-step-row-k">input</span>
      <div class="run-step-outputs">${rows}</div>
    </div>`;
  }

  function _renderStepOutputs(run, stepId) {
    const ws = (run && run.context && run.context.workspace) || {};
    const slot = ws[stepId];
    if (!slot) {
      return `<div class="run-step-row-kv">
        <span class="run-step-row-k">workspace</span>
        <span class="run-step-warn">No output written (step did not complete successfully).</span>
      </div>`;
    }
    const keys = Object.keys(slot);
    if (!keys.length) {
      return `<div class="run-step-row-kv">
        <span class="run-step-row-k">workspace</span>
        <span style="color:var(--text-muted)">(empty object)</span>
      </div>`;
    }
    // Each workspace key is click-to-expand: a collapsed row shows a short
    // preview; expanding reveals the COMPLETE produced value (string verbatim,
    // objects/arrays pretty-printed) in a scrollable block, so the operator can
    // actually read what a step output — not just a 50-char teaser.
    const rows = keys.slice(0, 24).map(k => {
      const v = slot[k];
      const isStr = typeof v === 'string';
      const full = isStr ? v : JSON.stringify(v, null, 2);
      const preview = isStr
        ? v.replace(/\s+/g, ' ').slice(0, 60) + (v.length > 60 ? '…' : '')
        : (v === null ? 'null' : Array.isArray(v) ? `array[${v.length}]` : 'object');
      const meta = isStr ? `${v.length} chars`
        : (Array.isArray(v) ? `${v.length} items` : (v === null ? '' : 'object'));
      const open = _expandedOutputs.has(stepId + '::' + k);
      return `<div class="run-step-output${open ? ' open' : ''}">
        <button type="button" class="btn-unstyled run-step-output-head" style="width:100%" aria-expanded="${open}" data-action="runs.output-toggle" data-step-id="${esc(stepId)}" data-key="${esc(k)}">
          <span class="run-step-caret">${open ? '▾' : '▸'}</span>
          <span class="ctx-field-k">${esc(k)}</span>
          ${open ? '' : `<span class="ctx-field-v">${esc(String(preview))}</span>`}
          <span style="flex:1"></span>
          <span class="run-step-output-meta">${esc(meta)}</span>
        </button>
        ${open ? `<pre class="run-step-output-full">${esc(full)}</pre>` : ''}
      </div>`;
    }).join('');
    return `<div class="run-step-row-kv run-step-outputs-kv">
      <span class="run-step-row-k">output</span>
      <div class="run-step-outputs">${rows}${keys.length > 24 ? `<span class="ctx-field-more">+${keys.length - 24} more</span>` : ''}</div>
    </div>`;
  }

  // Cascade detection — given a run, identify the root failure(s) and
  // the downstream "starved" steps. Approach:
  //   1. Walk step_results in order. Any failed/error step is a root.
  //   2. Any step in _currentSteps that comes AFTER a root in the DAG
  //      (via depends_on transitively) AND either didn't run OR ran
  //      but couldn't find its expected input in workspace, is starved.
  function _computeCascade(run) {
    const roots = new Set();
    const starved = new Set();
    const resultsById = new Map();
    (run.step_results || []).forEach(r => {
      if (!r || !r.step_id) return;
      resultsById.set(r.step_id, r);
      if (['failed', 'error'].includes((r.status || '').toLowerCase())) roots.add(r.step_id);
    });
    if (!roots.size) return { roots, starved };

    // Reachability: iterative BFS from each root through reverse
    // depends_on edges. Iterative + visited set is safe even if the
    // depends_on graph has a cycle (shouldn't, but defensive).
    const reverseEdges = new Map();  // from id → Set<children>
    _currentSteps.forEach(s => {
      const deps = Array.isArray(s.depends_on) ? s.depends_on
                 : (s.depends_on ? [s.depends_on] : []);
      deps.forEach(dep => {
        if (!reverseEdges.has(dep)) reverseEdges.set(dep, new Set());
        reverseEdges.get(dep).add(s.id);
      });
    });
    function descendants(rootId) {
      const out = new Set();
      const queue = Array.from(reverseEdges.get(rootId) || []);
      while (queue.length) {
        const cur = queue.shift();
        if (out.has(cur)) continue;
        out.add(cur);
        (reverseEdges.get(cur) || []).forEach(c => { if (!out.has(c)) queue.push(c); });
      }
      return out;
    }
    roots.forEach(r => {
      descendants(r).forEach(d => {
        const result = resultsById.get(d);
        // A starved step is one that either didn't run at all OR
        // failed because its input wasn't available. We mark both —
        // the run-step row's badge surfaces it.
        if (!result || ['failed', 'error', 'skipped'].includes((result.status || '').toLowerCase())) {
          starved.add(d);
        }
      });
    });
    return { roots, starved };
  }

  function toggleStepExpand(stepId) {
    if (_expandedSteps.has(stepId)) _expandedSteps.delete(stepId);
    else _expandedSteps.add(stepId);
    if (_currentRun) _renderSteps(_currentRun);
  }

  function toggleStepOutput(stepId, key) {
    const id = stepId + '::' + key;
    if (_expandedOutputs.has(id)) _expandedOutputs.delete(id);
    else _expandedOutputs.add(id);
    if (_currentRun) _renderSteps(_currentRun);
  }

  // ── Step-detail popup + troubleshooting pivots ───────────────────────────
  let _detailStepId = null;

  function _detailStep() {
    return _currentRun
      ? (_currentRun.step_results || []).find(x => x.step_id === _detailStepId)
      : null;
  }

  function _stepWorkspace(s) {
    return (((_currentRun || {}).context || {}).workspace || {})[s.step_id] || {};
  }

  function _stepContextText(s) {
    const ws = _stepWorkspace(s);
    const out = Object.values(ws)
      .map(v => (typeof v === 'string' ? v : JSON.stringify(v, null, 2)))
      .join('\n\n');
    return out || s.rendered_prompt || '';
  }

  // The agentic record: what the platform decided and invoked for this
  // step — model + arch placement, the timing anatomy (load vs prompt-eval
  // vs eval), token economics, memory-pressure delta, and every skill /
  // MCP call / plugin tool that fired. This is the context-tuning view:
  // see WHY a step behaved the way it did, then tune.
  // Composite kinds keep their children in the run workspace (loop/ralph →
  // `iterations`, parallel → `branches`), not as nested StepResults. Read that
  // structure back so the run detail can summarize a fan-out / loop / ralph
  // step instead of showing it as one opaque box.
  const _COMPOSITE_KINDS = { parallel: 1, loop: 1, ralph: 1, orchestrator: 1 };
  function _compositeSummary(s) {
    if (!s || !_COMPOSITE_KINDS[s.kind]) return '';
    const ws = _stepWorkspace(s) || {};
    const parts = [];
    const iters = ws.iterations || ws.iteration_results;
    if (iters != null) {
      const n = Array.isArray(iters) ? iters.length : Object.keys(iters).length;
      parts.push(`${n} iteration${n === 1 ? '' : 's'}`);
    }
    const branches = ws.branches || ws.branch_results;
    if (branches != null) {
      const n = Array.isArray(branches) ? branches.length : Object.keys(branches).length;
      parts.push(`${n} branch${n === 1 ? '' : 'es'}`);
    }
    const workers = ws.workers || ws.worker_results;
    if (workers != null) {
      const n = Array.isArray(workers) ? workers.length : Object.keys(workers).length;
      parts.push(`${n} worker${n === 1 ? '' : 's'}`);
    }
    // Ralph / loop halt signals, when the executor recorded them.
    const halt = ws.halt_reason || (ws.halt && ws.halt.reason);
    if (halt) parts.push(`halt: ${halt}`);
    if (ws.consecutive_failures) parts.push(`${ws.consecutive_failures} consecutive fails`);
    if (ws.goal_reached != null) parts.push(ws.goal_reached ? 'goal reached' : 'goal not reached');
    if (!parts.length) return '';
    const tone = s.kind === 'ralph' ? 'var(--amber)' : 'var(--accent)';
    return `<div class="run-decision-chips" style="margin-top:4px"><span class="run-decision-chip" style="border-color:${tone};color:${tone}">▦ ${esc(s.kind)} · ${esc(parts.join(' · '))}</span></div>`;
  }

  function _renderStepDecisions(s) {
    const tk = s.token_count || {};
    const kv = [];
    if (s.kind && s.kind !== 'llm') kv.push(['kind', s.kind]);
    kv.push(['model', s.model_used || '—']);
    if (s.arch_name) kv.push(['arch', s.arch_name]);
    if (tk.prompt_tokens != null) kv.push(['tokens', `${tk.prompt_tokens} in · ${tk.completion_tokens || 0} out`]);
    if (s.duration_seconds != null && tk.completion_tokens) {
      kv.push(['throughput', `${Math.round(tk.completion_tokens / Math.max(0.1, s.duration_seconds))} tok/s`]);
    }
    if (s.keep_alive_used != null) kv.push(['keep-alive', String(s.keep_alive_used)]);
    if (s.retries) kv.push(['retries', `${s.retries}×`]);
    if (s.extension_overhead_ms) kv.push(['ext overhead', `${Math.round(s.extension_overhead_ms)}ms`]);
    const pb = s.pressure_before, pa = s.pressure_after;
    if (pb && pa && pb.level) kv.push(['pressure', `${pb.level} → ${pa.level}`]);
    const kvHtml = kv.map(([k, v]) => `<span class="k">${esc(k)}</span><span class="v">${esc(String(v))}</span>`).join('');

    // Timing anatomy — proportional bar: where the wall-clock actually went.
    let timing = '';
    const load = s.load_duration_ms || 0, pe = s.prompt_eval_duration_ms || 0, ev = s.eval_duration_ms || 0;
    const total = load + pe + ev;
    if (total > 0) {
      const pct = x => Math.max(1, Math.round(100 * x / total));
      timing = `<div class="run-timing-bar">
          <i class="seg-load" style="width:${pct(load)}%" title="model load ${Math.round(load)}ms"></i>
          <i class="seg-prompt" style="width:${pct(pe)}%" title="prompt eval ${Math.round(pe)}ms"></i>
          <i class="seg-eval" style="width:${pct(ev)}%" title="generation ${Math.round(ev)}ms"></i>
        </div>
        <div class="run-timing-legend">
          <span><i class="seg-load" style="background:var(--warn-dim)"></i>load ${(load / 1000).toFixed(1)}s</span>
          <span><i style="background:var(--info-dim)"></i>prompt eval ${(pe / 1000).toFixed(1)}s</span>
          <span><i style="background:var(--accent-dim)"></i>generation ${(ev / 1000).toFixed(1)}s</span>
        </div>`;
    }

    // Invocation chips — the decisions: which skills auto-activated, which
    // MCP servers were called, which plugin tools ran.
    const chips = [];
    (s.skills_activated || []).forEach(x => chips.push(`<span class="run-decision-chip skill" title="skill auto-activated">⚡ ${esc(typeof x === 'string' ? x : x.name || JSON.stringify(x))}</span>`));
    (s.mcp_calls || []).forEach(x => chips.push(`<span class="run-decision-chip mcp" title="MCP call">⇄ ${esc(typeof x === 'string' ? x : (x.server || x.tool || JSON.stringify(x).slice(0, 40)))}</span>`));
    (s.plugin_tools_called || []).forEach(x => chips.push(`<span class="run-decision-chip tool" title="plugin tool">⚙ ${esc(typeof x === 'string' ? x : x.name || JSON.stringify(x).slice(0, 40))}</span>`));
    const chipsHtml = chips.length
      ? `<div class="run-decision-chips">${chips.join('')}</div>`
      : '<div class="run-decision-chips"><span class="run-decision-chip none">no skills / MCP / tools invoked — pure LLM turn</span></div>';

    return `<div class="run-decisions">
      <div class="run-decisions-kv">${kvHtml}</div>
      ${timing}${chipsHtml}${_compositeSummary(s)}
    </div>`;
  }

  function _renderStepDetailFull(s) {
    // Everything fully expanded (no click-to-expand) for the popup: the
    // prompt that ran + every output the step wrote, as scrollable blocks.
    const blocks = [];
    if (s.rendered_system_prompt) blocks.push(['system prompt', s.rendered_system_prompt]);
    if (s.rendered_prompt) blocks.push(['prompt', s.rendered_prompt]);
    const ws = _stepWorkspace(s);
    Object.keys(ws).forEach(k => {
      const v = ws[k];
      blocks.push(['output · ' + k, typeof v === 'string' ? v : JSON.stringify(v, null, 2)]);
    });
    const body = blocks.map(([label, text]) => `
      <div class="run-step-output open" style="margin-bottom:8px">
        <div class="run-step-output-head" style="cursor:default">
          <span class="ctx-field-k">${esc(label)}</span><span style="flex:1"></span>
          <span class="run-step-output-meta">${String(text).length} chars</span>
        </div>
        <pre class="run-step-output-full" style="max-height:280px">${esc(String(text))}</pre>
      </div>`).join('');
    return body || '<div class="model-empty">No prompt or output captured for this step.</div>';
  }

  function openStepDetail(stepId) {
    if (!_currentRun) return;
    _detailStepId = stepId;
    const s = _detailStep();
    if (!s) return;
    const tokens = (s.token_count || {}).total_tokens || 0;
    const dur = s.duration_seconds != null ? Math.round(s.duration_seconds) + 's' : '?';
    const title = document.getElementById('runs-step-modal-title');
    const sub = document.getElementById('runs-step-modal-sub');
    const body = document.getElementById('runs-step-modal-body');
    if (title) title.textContent = s.step_id;
    if (sub) sub.textContent = `${s.kind || 'llm'} · ${esc(s.model_used || '—')} · ${esc(s.status || '')} · ${dur}` +
      (tokens ? ` · ${tokens.toLocaleString()} tok` : '') + (s.retries ? ` · ${s.retries}× retry` : '');
    if (body) {
      body.innerHTML =
        (s.error ? `<div class="run-step-row-kv error"><span class="run-step-row-k">error</span><pre class="run-step-error-text">${esc(s.error)}</pre></div>` : '') +
        _renderStepDecisions(s) +
        _renderStepDetailFull(s);
    }
    const modal = document.getElementById('runs-step-modal');
    if (modal) modal.hidden = false;
  }

  function closeStepDetail() {
    const m = document.getElementById('runs-step-modal');
    if (m) m.hidden = true;
    _detailStepId = null;
  }

  // Inspect the workflow's actual entry-point (seed) or output (deliverable)
  // VALUES — e.g. the code that was reviewed, the review that was produced.
  function openAnchorDetail(kind) {
    if (!_currentRun) return;
    const ctx = _currentRun.context || {};
    let title, sub, entries, accent;
    if (kind === 'seed') {
      title = '▶ START · Seed Input';
      sub = 'The entry-point data this run executed on';
      entries = Object.entries(ctx.seed || {});
      accent = 'var(--accent)';
    } else {
      title = '■ END · Deliverable';
      sub = 'The final output this run produced';
      const results = _currentRun.step_results || [];
      const terminal = results[results.length - 1];
      const ws = ctx.workspace || {};
      entries = terminal ? Object.entries(ws[terminal.step_id] || {}) : [];
      accent = 'var(--cyan)';
    }
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);padding:20px;width:min(720px,94vw);max-height:88vh;overflow-y:auto;border-radius:6px;';
    const blocks = entries.length
      ? entries.map(([k, v]) => {
          const text = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
          return `<div class="run-step-output open" style="margin-bottom:8px">
            <div class="run-step-output-head" style="cursor:default"><span class="ctx-field-k">${esc(k)}</span><span style="flex:1"></span><span class="run-step-output-meta">${String(text).length} chars</span></div>
            <pre class="run-step-output-full">${esc(String(text))}</pre>
          </div>`;
        }).join('')
      : `<div class="model-empty">No ${esc(kind)} data captured on this run.</div>`;
    inner.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <div style="font-family:var(--mono);font-weight:600;font-size:0.92rem;flex:1;color:${accent}">${esc(title)}</div>
        <button class="action-btn xs ghost" data-action="runs.modal-close">×</button>
      </div>
      <div style="font-size:0.66rem;color:var(--text-muted);margin-bottom:12px">${esc(sub)}</div>
      ${blocks}`;
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
  }

  function pivotResearch() {
    const s = _detailStep(); if (!s) return;
    const ctx = _stepContextText(s);
    closeStepDetail();
    switchTab('research');
    setTimeout(() => {
      const inp = document.getElementById('research-topic');
      if (inp) {
        inp.value = `Research and verify the output of workflow step "${s.step_id}":\n\n${ctx}`.slice(0, 2000);
        inp.focus();
      }
    }, 300);
  }

  function pivotContextGraph() {
    closeStepDetail();
    // The knowledge graph (#graph-svg) lives in the research / Skill-Lab
    // tab — there is no standalone 'graph' tab anymore, so switchTab('graph')
    // null-threw on getElementById('tab-graph') and the pivot did nothing.
    // Route to the tab that actually hosts the graph (matching pivotResearch),
    // then (re)load the graph data and bring the panel into view.
    switchTab('research');
    setTimeout(() => {
      try { if (typeof loadGraphData === 'function') loadGraphData(); } catch (_) {}
      const g = document.querySelector('#tab-research .graph-panel')
        || document.getElementById('graph-svg');
      if (g && g.scrollIntoView) {
        try { g.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) {}
      }
    }, 250);
  }

  function pivotNewAgent() {
    const s = _detailStep(); if (!s) return;
    closeStepDetail();
    if (typeof showCreateAgentModal !== 'function') return;
    showCreateAgentModal();
    // Seed the new agent from this step: its system prompt becomes the agent's,
    // and the description notes the provenance.
    setTimeout(() => {
      const name = document.getElementById('am-name');
      const desc = document.getElementById('am-desc');
      const prompt = document.getElementById('am-prompt');
      if (name && !name.value) name.value = `Agent from ${s.step_id}`;
      if (desc && !desc.value) desc.value = `Seeded from run ${(_currentRun.run_id || '').slice(0, 8)} · step "${s.step_id}"`;
      if (prompt && s.rendered_system_prompt && !prompt.value.trim()) prompt.value = s.rendered_system_prompt;
    }, 300);
  }

  function copyStepContext() {
    const s = _detailStep(); if (!s) return;
    const payload = {
      run_id: _currentRun.run_id,
      step_id: s.step_id,
      model: s.model_used,
      system_prompt: s.rendered_system_prompt,
      prompt: s.rendered_prompt,
      output: _stepWorkspace(s),
    };
    try { navigator.clipboard.writeText(JSON.stringify(payload, null, 2)); } catch (_) {}
  }

  // ── SSE live-stream subscriber ────────────────────────────────────────────
  // Opens an EventSource against the run's /stream endpoint and handles
  // named event types. On onerror the source is closed and polling continues
  // as before (polling was already started by select() before this fires).
  // Call _unsubscribeSSE() when navigating away from the detail view.

  function _unsubscribeSSE() {
    if (_sseSource) {
      try { _sseSource.close(); } catch (_) {}
      _sseSource = null;
    }
    const badge = document.getElementById('rtp-sse-badge');
    if (badge) badge.hidden = true;
  }

  function _renderLivePlan(items) {
    const panel = document.getElementById('runs-tab-live-plan');
    const body  = document.getElementById('runs-tab-plan-body');
    if (!panel || !body) return;
    panel.hidden = false;
    if (!items || !items.length) {
      body.innerHTML = '<div class="model-empty">No plan items yet.</div>';
      return;
    }
    body.innerHTML = items.map(item => {
      const s = (item.status || 'pending').toLowerCase();
      return `<div class="rtp-plan-item" data-testid="plan-item" data-plan-id="${esc(item.id || '')}">
        <span class="rtp-plan-status ${esc(s)}">${esc(s)}</span>
        <span class="rtp-plan-title">${esc(item.title || item.id || '?')}</span>
        ${item.origin ? `<span class="rtp-plan-origin">${esc(item.origin)}</span>` : ''}
      </div>`;
    }).join('');
  }

  function _subscribeSSE(runId) {
    _unsubscribeSSE();
    if (typeof EventSource === 'undefined') return; // SSE not supported
    const src = new EventSource('/api/workflows/runs/' + encodeURIComponent(runId) + '/stream');
    _sseSource = src;

    // Show SSE badge once connected.
    src.addEventListener('stream.hello', () => {
      const badge = document.getElementById('rtp-sse-badge');
      if (badge) badge.hidden = false;
    });

    // Run-level status update — mirror into the data-status attribute.
    src.addEventListener('run.status', e => {
      try {
        const frame = JSON.parse(e.data);
        const status = (frame.data && frame.data.status) || '';
        const meta = document.getElementById('runs-tab-detail-meta');
        if (meta && status) meta.dataset.status = status.toLowerCase();
        // If the run just reached a terminal state, close the stream
        // and let the poller do one final refresh.
        if (['completed', 'failed', 'canceled', 'error'].includes(status.toLowerCase())) {
          _unsubscribeSSE();
          load();
        }
      } catch (_) {}
    });

    // Step started — upsert a synthetic result so the strip shows "running".
    src.addEventListener('step.started', e => {
      try {
        const frame = JSON.parse(e.data);
        const stepId = frame.step_id || (frame.data && frame.data.step_id);
        if (_currentRun && stepId) {
          const results = _currentRun.step_results || [];
          const existing = results.find(r => r.step_id === stepId);
          if (existing) { existing.status = 'running'; }
          else { results.push({ step_id: stepId, status: 'running' }); _currentRun.step_results = results; }
          _renderSteps(_currentRun);
          _applyStatus(_currentRun);
        }
      } catch (_) {}
    });

    // Step completed — upsert result with final status + duration.
    src.addEventListener('step.completed', e => {
      try {
        const frame = JSON.parse(e.data);
        const stepId = frame.step_id || (frame.data && frame.data.step_id);
        const stepData = frame.data || {};
        if (_currentRun && stepId) {
          const results = _currentRun.step_results || [];
          const existing = results.find(r => r.step_id === stepId);
          const status = stepData.status || 'completed';
          if (existing) {
            existing.status = status;
            if (stepData.duration_ms != null) existing.duration_ms = stepData.duration_ms;
          } else {
            results.push({ step_id: stepId, status, duration_ms: stepData.duration_ms });
            _currentRun.step_results = results;
          }
          _renderSteps(_currentRun);
          _applyStatus(_currentRun);
        }
      } catch (_) {}
    });

    // Plan updated — re-render the live plan panel.
    src.addEventListener('plan.updated', e => {
      try {
        const frame = JSON.parse(e.data);
        const plan = frame.data && frame.data.plan;
        if (plan && Array.isArray(plan.items)) {
          _renderLivePlan(plan.items);
        }
      } catch (_) {}
    });

    // Gate pending — surface the approval bar (re-use existing machinery
    // by patching _currentRun with a synthetic pending_gate and calling
    // _renderSteps, which already calls _renderApprovalGate).
    src.addEventListener('gate.pending', e => {
      try {
        const frame = JSON.parse(e.data);
        const gateData = frame.data || {};
        if (_currentRun) {
          _currentRun.status = 'awaiting_approval';
          _currentRun.pending_gate = {
            gate_id:  gateData.gate_id || '',
            step_id:  gateData.step_id || frame.step_id || '',
            question: gateData.prompt  || '',
          };
          _renderSteps(_currentRun);
          _toggleActionButtons(_currentRun);
          if (window.Toast) Toast.info('Gate pending', gateData.prompt || 'Approval required');
        }
      } catch (_) {}
    });

    // Gate resolved — clear synthetic gate state.
    src.addEventListener('gate.resolved', e => {
      try {
        if (_currentRun) {
          delete _currentRun.pending_gate;
          // status will be corrected by the next run.status or poll tick
          _renderSteps(_currentRun);
        }
      } catch (_) {}
    });

    // Stream end — clean up; polling keeps going until terminal status.
    src.addEventListener('stream.end', () => {
      _unsubscribeSSE();
    });

    // On any SSE error fall back to polling (already running) and close.
    src.onerror = () => {
      _unsubscribeSSE();
      // Polling was already started by select() before SSE was opened,
      // so no action needed — the interval keeps running.
    };
  }

  function _toggleActionButtons(run) {
    const s = (run.status || '').toLowerCase();
    const isLive = ['running', 'queued'].includes(s);
    const isFailed = ['failed', 'error'].includes(s);
    const isTerminal = ['completed', 'canceled', 'failed', 'error'].includes(s);
    _setBtn('runs-tab-pause-btn',  isLive);     // shown but disabled — placeholder
    _setBtn('runs-tab-resume-btn', isFailed);
    _setBtn('runs-tab-cancel-btn', isLive);
    _setBtn('runs-tab-rerun-btn',  isTerminal && !!run.workflow_id);
    _setBtn('runs-tab-detail-btn', true);
  }
  function _setBtn(id, show) {
    const b = document.getElementById(id);
    if (b) b.hidden = !show;
  }

  async function resumeCurrent() {
    if (!_selectedId) return;
    try {
      // retries:0 — resume re-executes steps; must fire exactly once.
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(_selectedId)}/resume`, {}, { retries: 0 });
      if (window.Toast) Toast.info('Resuming run', 'Picking up at the first un-completed step.');
      select(_selectedId);
    } catch (e) {
      if (window.Toast) Toast.danger('Resume failed', e.message);
    }
  }
  async function cancelCurrent() {
    if (!_selectedId) return;
    const ok = await Confirm.ask({ title: 'Stop run', body: 'Stop this run? The in-flight LLM call will complete first; no further steps will execute.', okLabel: 'Stop Run', danger: true });
    if (!ok) return;
    try {
      await Net.postJson(`/api/workflows/runs/${encodeURIComponent(_selectedId)}/cancel`, {}, { retries: 0 });
      if (window.Toast) Toast.info('Stop requested', 'Engine will halt at the next step boundary.');
    } catch (e) {
      if (window.Toast) Toast.danger('Stop failed', e.message);
    }
  }
  function pauseCurrent() {
    // Engine doesn't yet support cooperative pause (see SIDE_FINDS).
    if (window.Toast) Toast.info('Pause not yet supported',
      'Engine-side pause is on the SIDE_FINDS list — use Stop for now.');
  }
  async function rerunCurrent() {
    if (!_selectedId || !_currentRun) return;
    const wfId = _currentRun.workflow_id;
    const seed = (_currentRun.context && _currentRun.context.seed) || {};
    if (!wfId) {
      if (window.Toast) Toast.danger('Re-run failed', 'No workflow_id on this run.');
      return;
    }
    const ok = await Confirm.ask({ title: 'Re-run workflow', body: `Re-run ${wfId} with the same seed?`, okLabel: 'Re-run' });
    if (!ok) return;
    try {
      // Prefer the async endpoint so the runs tab can immediately
      // start polling without blocking on a possibly-long sync run.
      // retries:0 on BOTH endpoints — a Net retry stacked on the manual
      // sync-fallback could kick off the same workflow run multiple times.
      const r = await Net.call('/api/workflows/run-async', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workflow_id: wfId, seed }),
        },
      });
      if (!r.ok) {
        // Fall back to the sync endpoint for older engines.
        const r2 = await Net.call('/api/workflows/run', {
          retries: 0,
          init: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow_id: wfId, seed }),
          },
        });
        if (!r2.ok) throw new Error(`HTTP ${r2.status}`);
        if (window.Toast) Toast.success('Re-run started (sync)', wfId);
        load();
        return;
      }
      const out = r.data;
      if (window.Toast) Toast.success('Re-run started', `${wfId} · ${(out.run_id || '').slice(0, 12)}…`);
      // Refresh list + auto-select the new run.
      await load();
      if (out.run_id) select(out.run_id);
    } catch (e) {
      if (window.Toast) Toast.danger('Re-run failed', e.message);
    }
  }
  function toggleBottomDrawer() {
    const drawer = document.getElementById('runs-tab-bottom-drawer');
    if (!drawer) return;
    const open = drawer.classList.toggle('open');
    if (open) _renderBottomDrawer(_currentRun);
  }

  // Context-trace panel — shows the run.context.workspace as a
  // producer/consumer map so the operator can see exactly which step
  // wrote which key, and which downstream step couldn't read it.
  // Bottom drawer — fuller drilldown content. Shows seed JSON, the
  // full step list (with system prompts when available from the
  // workflow definition), and the workspace bag in raw form. Heavy
  // content, hence drawer-not-default.
  function _renderBottomDrawer(run) {
    const body = document.getElementById('runs-tab-bottom-drawer-body');
    if (!body) return;
    if (!run) {
      body.innerHTML = '<div class="model-empty">No run selected.</div>';
      return;
    }
    const seed = (run.context && run.context.seed) || {};
    const workspace = (run.context && run.context.workspace) || {};
    const shared = (run.context && run.context.shared) || {};
    // Copy payloads live in module state keyed by data-idx — the raw JSON
    // can be huge and JSON.stringify-into-onclick was attribute-hostile.
    _drawerCopyTexts = [];
    function _jsonPre(label, obj) {
      const txt = JSON.stringify(obj, null, 2);
      const lines = txt.split('\n').length;
      const truncated = lines > 80
        ? txt.split('\n').slice(0, 80).join('\n') + `\n… (${lines - 80} more lines)`
        : txt;
      const copyIdx = _drawerCopyTexts.push(txt) - 1;
      return `<div class="rdd-block">
        <div class="rdd-block-head">
          <span class="rdd-block-label">${esc(label)}</span>
          <button class="action-btn xs ghost"
                  data-action="runs.copy-json" data-idx="${copyIdx}"
                  title="Copy raw JSON to clipboard">Copy</button>
        </div>
        <pre class="rdd-block-pre">${esc(truncated)}</pre>
      </div>`;
    }
    // Step roster — name + status + (if available) system_prompt
    // sourced from _currentSteps which carries the resolved scaffold.
    const stepRoster = (_currentSteps || []).map(s => {
      const result = (run.step_results || []).find(r => r.step_id === s.id);
      const status = (result && result.status) || 'pending';
      const cls = status === 'completed' ? 'ok' : (['failed','error'].includes(status) ? 'fail' : 'pending');
      return `<div class="rdd-step rdd-step-${cls}">
        <span class="rdd-step-id">${esc(s.id)}</span>
        <span class="rdd-step-role">${esc(s.role || '')}</span>
        <span class="rdd-step-status">${esc(status)}</span>
        ${s.system_prompt
          ? `<details class="rdd-step-prompt"><summary>system prompt</summary><pre>${esc(s.system_prompt.slice(0, 1200))}${s.system_prompt.length > 1200 ? '\n…' : ''}</pre></details>`
          : ''}
      </div>`;
    }).join('');

    body.innerHTML = `
      <div class="rdd-cols">
        <div class="rdd-col rdd-col-roster">
          <div class="rdd-block-head"><span class="rdd-block-label">Step roster (${(_currentSteps || []).length})</span></div>
          <div class="rdd-roster">${stepRoster || '<div class="model-empty">No steps.</div>'}</div>
        </div>
        <div class="rdd-col rdd-col-state">
          ${_jsonPre('seed', seed)}
          ${_jsonPre('workspace', workspace)}
          ${Object.keys(shared).length ? _jsonPre('shared', shared) : ''}
        </div>
      </div>
    `;
  }

  function _renderContextTrace(run) {
    const box = document.getElementById('runs-tab-context-body');
    if (!box) return;
    const ws = (run && run.context && run.context.workspace) || {};
    const seed = (run && run.context && run.context.seed) || {};
    const stepIds = Object.keys(ws);
    if (!stepIds.length && !Object.keys(seed).length) {
      box.innerHTML = '<div class="model-empty">No workspace context recorded for this run.</div>';
      return;
    }

    // Producers — every step_id in workspace, with the keys it wrote.
    const producerRows = stepIds.map(stepId => {
      const keys = Object.keys(ws[stepId] || {});
      const result = (run.step_results || []).find(r => r.step_id === stepId);
      const status = (result && result.status) || 'unknown';
      const cls = status === 'completed' ? 'ok' : (['failed', 'error'].includes(status) ? 'fail' : 'pending');
      return `<div class="ctx-row ctx-row-${cls}">
        <span class="ctx-row-step">${esc(stepId)}</span>
        <span class="ctx-row-arrow">→</span>
        <span class="ctx-row-keys">${keys.length
          ? keys.map(k => `<span class="ctx-key-chip">${esc(k)}</span>`).join('')
          : '<span style="color:var(--text-muted)">no output</span>'}</span>
      </div>`;
    }).join('');

    const seedKeys = Object.keys(seed);
    const seedBlock = seedKeys.length ? `<div class="ctx-row ctx-row-ok">
      <span class="ctx-row-step ctx-row-seed">seed</span>
      <span class="ctx-row-arrow">→</span>
      <span class="ctx-row-keys">${seedKeys.map(k => `<span class="ctx-key-chip">${esc(k)}</span>`).join('')}</span>
    </div>` : '';

    box.innerHTML = `<div class="ctx-section-head">Producers (steps → workspace keys)</div>
      ${seedBlock}${producerRows || '<div class="model-empty">No producers yet.</div>'}`;
  }

  // Zoom controls — operate against this tab's own drawflow editor
  // (NOT window.dfEditor, which is the composer's separate instance).
  // Used by the floating zoom toolbar over the runs canvas.
  function zoomIn()    { if (_editor) try { _editor.zoom_in();    } catch (_) {} }
  function zoomOut()   { if (_editor) try { _editor.zoom_out();   } catch (_) {} }
  function zoomReset() {
    if (_editor) try { _editor.zoom_reset(); } catch (_) {}
    // Re-center the bbox after the zoom reset — same auto-layout the
    // initial render uses, so the DAG snaps back to fit the viewport.
    try { _runTabAutoLayout(); } catch (_) {}
  }

  // Registered inside the module for _drawerCopyTexts access — the rest
  // of the runs.* actions live in the block after the module.
  Actions.click({
    'runs.copy-json': el => {
      const t = _drawerCopyTexts[Number(el.dataset.idx)];
      if (t != null) navigator.clipboard.writeText(t);
    }
  });

  return { init, load, render, setFilter, select,
    resumeCurrent, cancelCurrent, pauseCurrent, rerunCurrent,
    toggleStepExpand, toggleStepOutput, toggleBottomDrawer, markFailed,
    openStepDetail, closeStepDetail, openAnchorDetail, pivotResearch, pivotContextGraph,
    pivotNewAgent, copyStepContext,
    zoomIn, zoomOut, zoomReset,
    resolveGate };
})();
window.RunsTab = RunsTab;

// Delegated actions for the RunsTab dynamic surfaces (run list, step strip,
// gate bar, output disclosures) — these re-render on the 1.5s live poll, so
// the markup carries data-action instead of inline handlers.
(function () {
  const stepIdOf = el => {
    const row = el.closest('[data-step-id]');
    return row ? row.dataset.stepId : '';
  };
  Actions.click({
    'runs.load':        () => RunsTab.load(),
    'runs.select':      el => RunsTab.select(el.dataset.runId),
    'runs.mark-failed': () => RunsTab.markFailed(),
    'runs.gate':        el => RunsTab.resolveGate(el.dataset.runId, el.dataset.gateId, el.dataset.decision),
    'runs.step-detail': el => RunsTab.openStepDetail(stepIdOf(el)),
    'runs.step-expand': el => RunsTab.toggleStepExpand(stepIdOf(el)),
    'runs.anchor-detail': el => RunsTab.openAnchorDetail(el.dataset.kind),
    'runs.output-toggle': el => RunsTab.toggleStepOutput(el.dataset.stepId, el.dataset.key),
    'runs.modal-close':   el => { const m = el.closest('div[style*=fixed]'); if (m) m.remove(); }
  });
  // The step head is a role=button div — keep keyboard operability.
  Actions.on('keydown', {
    'runs.step-detail': (el, e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      RunsTab.openStepDetail(stepIdOf(el));
    }
  });
})();

// ── Workflow Memory panel ──────────────────────────────────────────────
// Backs the Memory tab's "Workflow Memory" panel against the three durable
// stores (playbooks / semantic / episodic). Lists each, click an item to
// inspect its content inline. Reads only — writes happen via
// kind=consolidate steps inside workflow runs.
const WorkflowMemory = (function () {
  const TARGETS = [
    { kind: 'playbooks', list_id: 'wm-playbooks-list', count_id: 'wm-playbooks-count', read_path: 'playbooks' },
    { kind: 'semantic',  list_id: 'wm-semantic-list',  count_id: 'wm-semantic-count',  read_path: 'semantic'  },
    { kind: 'episodic',  list_id: 'wm-episodic-list',  count_id: 'wm-episodic-count',  read_path: 'episodic'  },
  ];

  async function refresh() {
    for (const t of TARGETS) {
      const listEl = document.getElementById(t.list_id);
      const countEl = document.getElementById(t.count_id);
      if (!listEl) continue;
      try {
        const resp = await Net.call(`/api/workflows/memory/${t.kind}`, {
          init: { headers: typeof getAuthHeaders === 'function' ? getAuthHeaders() : {} },
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = resp.data;
        const items = data[t.kind] || [];
        if (countEl) countEl.textContent = items.length;
        if (!items.length) {
          listEl.innerHTML = `<div class="wm-empty">No ${t.kind} written yet — run a workflow with a <code>kind: consolidate</code> step.</div>`;
          continue;
        }
        listEl.innerHTML = items.map(it => {
          const meta = (t.kind === 'episodic')
            ? `${it.record_count} rec${it.record_count !== 1 ? 's' : ''}`
            : `${(it.size_bytes || 0).toLocaleString()} B`;
          return `<button type="button" class="btn-unstyled wm-item" style="width:100%" data-action="wm.open" data-kind="${esc(t.kind)}" data-name="${esc(it.name)}">
            <span class="wm-item-name">${esc(it.name)}</span>
            <span class="wm-item-meta">${esc(meta)}</span>
          </button>`;
        }).join('');
      } catch (e) {
        listEl.innerHTML = `<div class="wm-empty">Failed: ${esc(String(e))}</div>`;
        if (countEl) countEl.textContent = '!';
      }
    }
  }

  async function open(kind, name) {
    const label = document.getElementById('wm-detail-label');
    const body = document.getElementById('wm-detail-body');
    const detail = document.getElementById('wm-detail');
    if (!detail || !label || !body) return;
    label.textContent = `${kind}: ${name}`;
    body.textContent = 'Loading…';
    detail.hidden = false;
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    try {
      const resp = await Net.call(`/api/workflows/memory/${kind}/${encodeURIComponent(name)}`, {
        init: { headers: typeof getAuthHeaders === 'function' ? getAuthHeaders() : {} },
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = resp.data;
      if (kind === 'episodic') {
        // Render the recency log as a readable digest.
        const lines = (data.records || []).map(r =>
          `### ${r.timestamp || '?'} (run ${r.run_id || '?'})\n${r.content || ''}`
        );
        body.textContent = lines.join('\n\n') || '(empty)';
      } else {
        body.textContent = data.body || '(empty)';
      }
    } catch (e) {
      body.textContent = 'Failed to load: ' + String(e);
    }
  }

  function closeDetail() {
    const detail = document.getElementById('wm-detail');
    if (detail) detail.hidden = true;
  }

  // Delegated action — the three store lists re-render on every refresh.
  Actions.click({ 'wm.open': el => open(el.dataset.kind, el.dataset.name) });

  return { refresh, open, closeDetail };
})();
window.WorkflowMemory = WorkflowMemory;

function renderWorkflowIndex() { WorkflowIndex && WorkflowIndex.refresh && document.getElementById('wfi-grid') && (function(){
  // Re-render with current cache by triggering a refresh of the chip filter.
  const ev = new Event('input');
  document.getElementById('wfi-search').dispatchEvent(ev);
})(); }

/* ══════════════════════════════════════════════════════════════════
   MCP ADMIN PANEL — register / inspect / test / invoke MCP servers.
   ══════════════════════════════════════════════════════════════════ */
const MCPPanel = (function () {
  let _servers = [];
  let _selected = null;
  // Marketplace catalog entries from the last browseMarketplace() fetch —
  // install buttons reference them by data-idx instead of serializing the
  // whole entry object into an onclick attribute.
  let _catalogItems = [];

  function _headers() {
    return (window.AdminAuth && AdminAuth.authHeaders) ? AdminAuth.authHeaders() : {};
  }

  async function load() {
    const el = document.getElementById('mcp-list');
    if (!el) return;
    el.innerHTML = '<div class="model-empty">Loading…</div>';
    try {
      const r = await Net.call('/api/mcp/servers', { init: { headers: _headers() } });
      if (!r.ok) { el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Load failed (${r.status})</div>`; return; }
      _servers = r.data;
      render();
    } catch (e) {
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function refresh() { load(); }

  function render() {
    const el = document.getElementById('mcp-list');
    if (!el) return;
    if (!_servers.length) {
      el.innerHTML = '<div class="model-empty">No MCP servers registered. Click "+ Register" to add one.</div>';
      return;
    }
    el.innerHTML = _servers.map(s => {
      // Persona icon — every MCP server gets the canonical mcp glyph
      // with purple tone, matching the System-page Discover surface.
      const icon = (window.AgentIcons ? AgentIcons.svg('mcp') : '');
      const tone = (window.AgentIcons ? AgentIcons.tone('mcp') : 'purple');
      return `<button type="button" class="btn-unstyled mcp-row ${_selected === s.id ? 'selected' : ''}" style="width:100%" aria-pressed="${_selected === s.id}" data-action="mcp.select" data-id="${esc(s.id)}">
        <span class="admin-card-icon admin-card-icon-sm tone-${esc(tone)}">${icon}</span>
        <span class="mcp-row-dot ${s.tools_count > 0 ? 'up' : 'unknown'}"></span>
        <div style="flex:1;min-width:0">
          <div class="mcp-row-title">${esc(s.name || s.id)}</div>
          <div class="mcp-row-meta">${esc(s.transport)} · ${s.enabled ? 'enabled' : 'disabled'} · ${s.tools_count || 0} tools</div>
        </div>
      </button>`;
    }).join('');
  }

  function select(id) {
    _selected = id;
    render();
    renderDetail();
  }

  function renderDetail() {
    const el = document.getElementById('mcp-detail');
    const label = document.getElementById('mcp-detail-label');
    if (!el || !label) return;
    const s = _servers.find(x => x.id === _selected);
    if (!s) {
      label.textContent = '// SELECT A SERVER';
      el.innerHTML = 'Select a server from the left.';
      return;
    }
    label.textContent = `// ${s.name || s.id}`;
    const envStr = Object.entries(s.env || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—';
    el.innerHTML = `
      <div style="display:grid;grid-template-columns:120px 1fr;gap:6px;font-size:0.74rem;line-height:1.6">
        <div style="color:var(--text-muted)">ID</div><code style="color:var(--accent)">${esc(s.id)}</code>
        <div style="color:var(--text-muted)">Transport</div><div>${esc(s.transport)}</div>
        ${s.transport === 'stdio' ? `
          <div style="color:var(--text-muted)">Command</div><code style="font-size:0.66rem">${esc(s.command || '')} ${(s.args || []).map(esc).join(' ')}</code>
          <div style="color:var(--text-muted)">Env</div><code style="font-size:0.66rem">${esc(envStr)}</code>
        ` : `
          <div style="color:var(--text-muted)">URL</div><code style="font-size:0.66rem">${esc(s.url || '')}</code>
        `}
        <div style="color:var(--text-muted)">Enabled</div><div>${s.enabled ? '✓' : '✕'}</div>
        <div style="color:var(--text-muted)">Description</div><div>${esc(s.description || '')}</div>
      </div>
      <div style="display:flex;gap:6px;margin-top:14px;flex-wrap:wrap">
        <button class="action-btn" data-action="mcp.test" data-id="${esc(s.id)}">Test handshake</button>
        <button class="action-btn" data-action="mcp.discover" data-id="${esc(s.id)}">Discover tools</button>
        <button class="action-btn" data-action="mcp.toggle" data-id="${esc(s.id)}" data-enabled="${!s.enabled}">${s.enabled ? 'Disable' : 'Enable'}</button>
        <button class="action-btn" data-action="mcp.edit" data-id="${esc(s.id)}">Edit</button>
        <button class="action-btn" data-action="mcp.remove" data-id="${esc(s.id)}" style="color:var(--danger);border-color:var(--danger-dim)">Delete</button>
      </div>
      <div id="mcp-detail-tools" style="margin-top:14px">
        <div class="panel-label" style="margin-bottom:6px">Tools (${(s.tools || []).length})</div>
        <div class="mcp-tools-list">
          ${(s.tools || []).map(t => `<div class="mcp-tool">
            <div class="mcp-tool-name">${esc(t.name)}</div>
            <div class="mcp-tool-desc">${esc(t.description || '')}</div>
          </div>`).join('') || '<div style="color:var(--text-muted);font-size:0.66rem">No tools cached. Click "Discover tools" to query the server.</div>'}
        </div>
      </div>
    `;
  }

  async function test(id) {
    try {
      // Net.call (not postJson): result body is read regardless of status, and
      // postJson would add a '{}' body to a body-less POST. retries:0 — live handshake.
      const r = await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}/test`, { retries: 0, init: { method: 'POST', headers: _headers() } });
      const result = (r.data && typeof r.data === 'object') ? r.data : {};
      if (result.reachable) Toast.success('Server reachable', `${result.tools_count} tool(s) advertised`);
      else Toast.danger('Server unreachable', result.error || 'unknown');
      await load();
    } catch (e) { Toast.danger('Test error', e.message); }
  }

  async function discoverTools(id) {
    try {
      // retries:0 — refresh triggers a live tool-discovery query against the server.
      const r = await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}/tools?refresh=true`, { retries: 0, init: { headers: _headers() } });
      if (!r.ok) { Toast.danger('Discover failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      await load();
      _selected = id; renderDetail();
    } catch (e) { Toast.danger('Discover error', e.message); }
  }

  async function toggleEnabled(id, enabled) {
    try {
      await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}`, {
        retries: 0,
        init: {
          method: 'PATCH', headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ enabled }),
        },
      });
      await load();
    } catch (e) { Toast.danger('Toggle error', e.message); }
  }

  async function remove(id) {
    const ok = await Confirm.ask({ title: 'Delete MCP server', body: `Delete MCP server '${id}'?`, okLabel: 'Delete', danger: true });
    if (!ok) return;
    try {
      await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}`, { retries: 0, init: { method: 'DELETE', headers: _headers() } });
      _selected = null;
      await load();
      renderDetail();
    } catch (e) { Toast.danger('Delete error', e.message); }
  }

  // ── Create / Edit modal ─────────────────────────────────────────
  function showCreate() {
    document.getElementById('mcp-edit-title').textContent = 'Register MCP server';
    ['mcp-edit-id','mcp-edit-name','mcp-edit-desc','mcp-edit-command','mcp-edit-args','mcp-edit-env','mcp-edit-url','mcp-edit-headers','mcp-edit-tags']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('mcp-edit-id').disabled = false;
    document.getElementById('mcp-edit-transport').value = 'stdio';
    document.getElementById('mcp-edit-timeout').value = 30;
    _onTransportChange();
    _hideError();
    document.getElementById('mcp-edit-modal').hidden = false;
  }

  function edit(id) {
    const s = _servers.find(x => x.id === id);
    if (!s) return;
    document.getElementById('mcp-edit-title').textContent = `Edit ${s.id}`;
    document.getElementById('mcp-edit-id').value = s.id;
    document.getElementById('mcp-edit-id').disabled = true;
    document.getElementById('mcp-edit-name').value = s.name || '';
    document.getElementById('mcp-edit-desc').value = s.description || '';
    document.getElementById('mcp-edit-transport').value = s.transport;
    document.getElementById('mcp-edit-command').value = s.command || '';
    document.getElementById('mcp-edit-args').value = (s.args || []).join(' ');
    // env / headers are masked on the wire; leave blank so PATCH only sets when user types.
    document.getElementById('mcp-edit-env').value = '';
    document.getElementById('mcp-edit-headers').value = '';
    document.getElementById('mcp-edit-url').value = s.url || '';
    document.getElementById('mcp-edit-timeout').value = s.timeout_seconds || 30;
    document.getElementById('mcp-edit-tags').value = (s.tags || []).join(', ');
    _onTransportChange();
    _hideError();
    document.getElementById('mcp-edit-modal').hidden = false;
  }

  function _onTransportChange() {
    const t = document.getElementById('mcp-edit-transport').value;
    document.getElementById('mcp-edit-stdio-fields').style.display = (t === 'stdio') ? '' : 'none';
    document.getElementById('mcp-edit-http-fields').style.display  = (t === 'stdio') ? 'none' : '';
  }

  function _closeModal() { document.getElementById('mcp-edit-modal').hidden = true; }
  function _hideError()  { const e = document.getElementById('mcp-edit-error'); if (e) { e.hidden = true; e.textContent = ''; } }
  function _showError(m) { const e = document.getElementById('mcp-edit-error'); if (e) { e.textContent = m; e.hidden = false; } }

  function _parseKvLines(text, sep) {
    const out = {};
    (text || '').split(/\r?\n/).forEach(line => {
      const idx = line.indexOf(sep);
      if (idx <= 0) return;
      out[line.slice(0, idx).trim()] = line.slice(idx + sep.length).trim();
    });
    return out;
  }

  async function _submit() {
    _hideError();
    const isEdit = document.getElementById('mcp-edit-id').disabled;
    const id = document.getElementById('mcp-edit-id').value.trim();
    const transport = document.getElementById('mcp-edit-transport').value;
    const body = {
      name: document.getElementById('mcp-edit-name').value.trim(),
      description: document.getElementById('mcp-edit-desc').value.trim(),
      transport,
      timeout_seconds: parseInt(document.getElementById('mcp-edit-timeout').value, 10) || 30,
      tags: document.getElementById('mcp-edit-tags').value.split(',').map(s => s.trim()).filter(Boolean),
    };
    if (transport === 'stdio') {
      body.command = document.getElementById('mcp-edit-command').value.trim();
      body.args = document.getElementById('mcp-edit-args').value.trim().split(/\s+/).filter(Boolean);
      const env = _parseKvLines(document.getElementById('mcp-edit-env').value, '=');
      if (Object.keys(env).length) body.env = env;
    } else {
      body.url = document.getElementById('mcp-edit-url').value.trim();
      const hdrs = _parseKvLines(document.getElementById('mcp-edit-headers').value, ':');
      if (Object.keys(hdrs).length) body.headers = hdrs;
    }

    try {
      let r;
      if (isEdit) {
        r = await Net.call(`/api/mcp/servers/${encodeURIComponent(id)}`, {
          retries: 0,
          init: {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ..._headers() },
            body: JSON.stringify(body),
          },
        });
      } else {
        body.id = id;
        r = await Net.call('/api/mcp/servers', {
          retries: 0,
          init: {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ..._headers() },
            body: JSON.stringify(body),
          },
        });
      }
      if (!r.ok) {
        _showError((r.data && r.data.detail) || r.error);
        return;
      }
      _closeModal();
      await load();
      if (id) select(id);
    } catch (e) { _showError(e.message); }
  }

  // ── Marketplace — browse + one-click register a catalog MCP server ──
  async function browseMarketplace() {
    const modal = document.createElement('div');
    modal.className = 'mcp-mkt-overlay';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.72);z-index:1000;display:flex;align-items:center;justify-content:center';
    const inner = document.createElement('div');
    inner.style.cssText = 'background:var(--bg);border:1px solid var(--border);width:min(760px,95vw);max-height:90vh;display:flex;flex-direction:column;border-radius:8px;overflow:hidden';
    inner.innerHTML = '<div class="model-empty" style="padding:28px">Loading MCP catalog…</div>';
    modal.appendChild(inner);
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    document.body.appendChild(modal);
    try {
      const r = await Net.call('/api/mcp/discover', { init: { headers: _headers() } });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      const d = r.data;
      _catalogItems = d.servers || [];
      const icon = (window.AgentIcons ? AgentIcons.svg('mcp') : '');
      const rows = _catalogItems.map((s, i) => {
        const envReq = (s.env_required || []);
        const reqChip = envReq.length
          ? `<span class="skill-disc-chip available" title="${esc(envReq.map(e => e.key).join(', '))}">needs ${envReq.length} secret${envReq.length === 1 ? '' : 's'}</span>` : '';
        const srcChip = s.marketplace ? '<span class="skill-disc-chip marketplace">remote</span>' : '';
        const action = s.installed
          ? '<span class="skill-disc-chip installed">installed</span>'
          : `<button class="action-btn sm accent" data-action="mcp.mkt-install" data-idx="${i}">Install</button>`;
        return `<div class="gh-skill-row">
          <span class="admin-card-icon admin-card-icon-sm tone-purple" style="flex:0 0 auto">${icon}</span>
          <div class="gh-skill-info">
            <div class="gh-skill-name">${esc(s.name || s.id)} ${srcChip} ${reqChip}</div>
            <div class="gh-skill-desc">${esc(s.description || '')}</div>
            ${s.args_hint ? `<div class="gh-skill-desc" style="color:var(--amber);margin-top:2px">⚙ ${esc(s.args_hint)}</div>` : ''}
          </div>
          <div style="flex:0 0 auto">${action}</div>
        </div>`;
      }).join('');
      inner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;padding:14px 18px;border-bottom:1px solid var(--border)">
          <div style="font-family:var(--mono);font-weight:600;flex:1">MCP Marketplace <span style="color:var(--text-muted);font-weight:400">· ${d.count} server${d.count === 1 ? '' : 's'}</span></div>
          <button class="action-btn xs ghost" data-action="mcp.mkt-close">×</button>
        </div>
        <div style="font-size:0.64rem;color:var(--text-muted);padding:8px 18px 0">Servers run as local processes under your account. Servers needing a path/DSN install with a placeholder — edit the registration afterward. Secrets are collected on install.</div>
        <div class="gh-skills" style="overflow:auto;padding:10px 18px 18px">${rows || '<div class="model-empty">Catalog is empty.</div>'}</div>`;
    } catch (e) {
      inner.innerHTML = `<div class="model-empty" style="color:var(--red);padding:24px">Failed: ${esc(e.message)}</div>`;
    }
  }

  async function _installFromCatalog(entry, btn) {
    // Collect required credentials up front; abort if any are skipped.
    const env = {};
    for (const e of (entry.env_required || [])) {
      const val = prompt(`${entry.name}: enter ${e.key}\n${e.hint || ''}`);
      if (val === null) return;           // operator cancelled
      if (val.trim()) env[e.key] = val.trim();
    }
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      // retries:0 — install registers a server; don't double-register.
      const r = await Net.call(`/api/mcp/discover/${encodeURIComponent(entry.id)}/install`, {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ env }),
        },
      });
      if (!r.ok) throw new Error(r.error || ('HTTP ' + r.status));
      if (btn) { btn.outerHTML = '<span class="skill-disc-chip installed">installed</span>'; }
      if (window.Toast) Toast.success('MCP server registered', `${entry.id} — test the handshake from its detail panel.`);
      await load();
      select(entry.id);
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
      Toast.danger('Install failed', e.message);
    }
  }

  // Refresh when the panel becomes visible.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-mcp') load();
  });

  // Delegated actions — server rows + detail buttons re-render on every
  // select/load; marketplace install resolves its catalog entry from
  // _catalogItems by data-idx (registered inside the module for state
  // access). data-enabled is a "true"/"false" string by dataset contract.
  Actions.click({
    'mcp.select':   el => select(el.dataset.id),
    'mcp.test':     el => test(el.dataset.id),
    'mcp.discover': el => discoverTools(el.dataset.id),
    'mcp.toggle':   el => toggleEnabled(el.dataset.id, el.dataset.enabled === 'true'),
    'mcp.edit':     el => edit(el.dataset.id),
    'mcp.remove':   el => remove(el.dataset.id),
    'mcp.mkt-install': el => {
      const entry = _catalogItems[Number(el.dataset.idx)];
      if (entry) _installFromCatalog(entry, el);
    },
    'mcp.mkt-close': el => { const o = el.closest('.mcp-mkt-overlay'); if (o) o.remove(); }
  });

  return { load, refresh, render, select, test, discoverTools, toggleEnabled, remove,
           showCreate, edit, _onTransportChange, _closeModal, _submit,
           browseMarketplace, _installFromCatalog };
})();
// Export for the static-HTML onclick guard (`if(window.MCPPanel)MCPPanel.showCreate()`):
// without this the Catalog '+ Register' button is a silent no-op.
window.MCPPanel = MCPPanel;

/* Refresh workbenches whenever the composer becomes the active tab. */
(function () {
  const observer = new MutationObserver(() => {
    const cur = document.querySelector('.tab-content.active');
    if (cur && cur.id === 'tab-dashboard') {
      // No-op; ComposerView.init handles the lazy boot. The hook is here
      // so that if any future code calls .classList directly we still pick up.
    }
  });
  const root = document.querySelector('.shell');
  if (root) observer.observe(root, { attributes: true, subtree: true, attributeFilter: ['class'] });
})();

/* ══════════════════════════════════════════════════════════════════
   AGENT GENERATOR — modal that converts a document or pasted text
   into a draft agent, lets the user edit it, run validation cases,
   and save. Backed by /api/agents/generate + /api/agents/{id}/evaluate.
   ══════════════════════════════════════════════════════════════════ */
const AgentGen = (function () {
  let _draft = null;
  let _modal = null;

  function openFromDocument(docId, filename) {
    _ensureModal();
    document.getElementById('ag-mode').value = 'document';
    document.getElementById('ag-document-id').value = docId;
    document.getElementById('ag-filename-readonly').textContent = filename || docId;
    document.getElementById('ag-text-row').style.display = 'none';
    document.getElementById('ag-doc-row').style.display = '';
    _showStep('input');
    _modal.hidden = false;
  }

  function openFromText() {
    _ensureModal();
    document.getElementById('ag-mode').value = 'text';
    document.getElementById('ag-document-id').value = '';
    document.getElementById('ag-text-row').style.display = '';
    document.getElementById('ag-doc-row').style.display = 'none';
    _showStep('input');
    _modal.hidden = false;
  }

  function _ensureModal() {
    if (_modal) return;
    _modal = document.createElement('div');
    _modal.className = 'admin-modal';
    _modal.id = 'agent-gen-modal';
    _modal.hidden = true;
    _modal.innerHTML = `
      <div class="admin-modal-card" style="width:760px;max-width:94vw;max-height:88vh;overflow:auto">
        <h3>Convert document to agent</h3>
        <div class="ag-steps">
          <span class="ag-step" data-ag-step="input">1. Input</span>
          <span class="ag-step" data-ag-step="draft">2. Draft</span>
          <span class="ag-step" data-ag-step="eval">3. Validate</span>
        </div>

        <!-- Step 1: input -->
        <div class="ag-pane" data-ag-pane="input">
          <input type="hidden" id="ag-mode" value="text">
          <div id="ag-doc-row" style="margin:8px 0">
            <label class="admin-modal-label">Source document</label>
            <div style="padding:6px 10px;border:1px solid var(--border);border-radius:3px;font-size:0.75rem;color:var(--text-dim)" id="ag-filename-readonly">—</div>
            <input type="hidden" id="ag-document-id" value="">
          </div>
          <div id="ag-text-row" style="margin:8px 0;display:none">
            <label class="admin-modal-label">Source text (or paste reference content here)</label>
            <textarea id="ag-text-input" rows="8" placeholder="Paste a spec, runbook, or other reference material…"></textarea>
          </div>
          <label class="admin-modal-label">Name hint (optional)</label>
          <input type="text" id="ag-name-hint" placeholder="e.g. XSIAM Rule Reviewer">
          <label class="admin-modal-label">Role hint (optional)</label>
          <select id="ag-role-hint">
            <option value="">— let the LLM decide —</option>
            <option value="reasoning">reasoning</option>
            <option value="coding">coding</option>
            <option value="fast">fast</option>
            <option value="general">general</option>
            <option value="uncensored">uncensored</option>
          </select>
          <div id="ag-error" class="admin-modal-error" hidden></div>
          <div class="admin-modal-actions">
            <button type="button" class="admin-modal-btn" data-action="agentgen.close">Cancel</button>
            <button type="button" class="admin-modal-btn primary" id="ag-generate-btn" data-action="agentgen.generate">Generate draft</button>
          </div>
        </div>

        <!-- Step 2: draft review -->
        <div class="ag-pane" data-ag-pane="draft" hidden>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div><label class="admin-modal-label">Agent ID</label><input type="text" id="ag-draft-id"></div>
            <div><label class="admin-modal-label">Name</label><input type="text" id="ag-draft-name"></div>
            <div><label class="admin-modal-label">Role</label><select id="ag-draft-role">
              <option value="reasoning">reasoning</option>
              <option value="coding">coding</option>
              <option value="fast">fast</option>
              <option value="general">general</option>
              <option value="uncensored">uncensored</option>
            </select></div>
            <div><label class="admin-modal-label">Model (optional)</label><input type="text" id="ag-draft-model" placeholder="deepseek-r1:32b"></div>
          </div>
          <label class="admin-modal-label">Description</label>
          <input type="text" id="ag-draft-desc">
          <label class="admin-modal-label">System prompt</label>
          <textarea id="ag-draft-prompt" rows="10"></textarea>
          <label class="admin-modal-label">Starter prompts (one per line)</label>
          <textarea id="ag-draft-starters" rows="4"></textarea>
          <label class="admin-modal-label">Tags (comma-separated)</label>
          <input type="text" id="ag-draft-tags">
          <div id="ag-draft-error" class="admin-modal-error" hidden></div>
          <div class="admin-modal-actions">
            <button type="button" class="admin-modal-btn" data-action="agentgen.step" data-step="input">← Back</button>
            <button type="button" class="admin-modal-btn" data-action="agentgen.save">Save (no eval)</button>
            <button type="button" class="admin-modal-btn primary" data-action="agentgen.step" data-step="eval">Continue → Validate</button>
          </div>
        </div>

        <!-- Step 3: validation -->
        <div class="ag-pane" data-ag-pane="eval" hidden>
          <div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:8px;line-height:1.5">
            Define a few quick acceptance cases — prompt + expected substring. The draft will be saved
            and then evaluated; results show pass/fail per case.
          </div>
          <div id="ag-cases" style="display:flex;flex-direction:column;gap:6px"></div>
          <button class="action-btn" data-action="agentgen.add-case" style="margin-top:6px">+ Add case</button>
          <div id="ag-eval-results" style="margin-top:14px"></div>
          <div id="ag-eval-error" class="admin-modal-error" hidden></div>
          <div class="admin-modal-actions">
            <button type="button" class="admin-modal-btn" data-action="agentgen.step" data-step="draft">← Back</button>
            <button type="button" class="admin-modal-btn primary" data-action="agentgen.save-eval">Save + Run cases</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(_modal);
  }

  function _showStep(name) {
    _ensureModal();
    _modal.querySelectorAll('.ag-step').forEach(s => s.classList.toggle('active', s.dataset.agStep === name));
    _modal.querySelectorAll('.ag-pane').forEach(p => p.hidden = (p.dataset.agPane !== name));
    if (name === 'eval') AgentGen.addCase(); // seed with one row
  }

  function _hideError(id) { const e = document.getElementById(id); if (e) { e.hidden = true; e.textContent = ''; } }
  function _showError(id, msg) { const e = document.getElementById(id); if (e) { e.textContent = msg; e.hidden = false; } }

  async function generate() {
    _hideError('ag-error');
    const mode = document.getElementById('ag-mode').value;
    const nameHint = document.getElementById('ag-name-hint').value.trim();
    const roleHint = document.getElementById('ag-role-hint').value;
    const body = { name_hint: nameHint || null, role_hint: roleHint || null };
    if (mode === 'document') {
      body.document_id = document.getElementById('ag-document-id').value;
    } else {
      const text = document.getElementById('ag-text-input').value.trim();
      if (!text) { _showError('ag-error', 'Paste some text first.'); return; }
      body.text = text;
    }
    const btn = document.getElementById('ag-generate-btn');
    btn.disabled = true; btn.textContent = 'Generating…';
    try {
      // retries:0 — slow LLM generation must not double-fire.
      const result = await Net.postJson('/api/agents/generate', body, { retries: 0 });
      _draft = result.draft;
      _hydrateDraft(_draft);
      _showStep('draft');
    } catch (e) { _showError('ag-error', e.message); }
    finally { btn.disabled = false; btn.textContent = 'Generate draft'; }
  }

  function _hydrateDraft(d) {
    document.getElementById('ag-draft-id').value = d.id || '';
    document.getElementById('ag-draft-name').value = d.name || '';
    document.getElementById('ag-draft-role').value = d.role || 'reasoning';
    document.getElementById('ag-draft-model').value = d.model || '';
    document.getElementById('ag-draft-desc').value = d.description || '';
    document.getElementById('ag-draft-prompt').value = d.system_prompt || '';
    document.getElementById('ag-draft-starters').value = (d.starters || []).join('\n');
    document.getElementById('ag-draft-tags').value = (d.tags || []).join(', ');
  }

  function _readDraft() {
    if (!_draft) _draft = {};
    _draft.id = document.getElementById('ag-draft-id').value.trim();
    _draft.name = document.getElementById('ag-draft-name').value.trim();
    _draft.role = document.getElementById('ag-draft-role').value;
    _draft.model = document.getElementById('ag-draft-model').value.trim() || null;
    _draft.description = document.getElementById('ag-draft-desc').value.trim();
    _draft.system_prompt = document.getElementById('ag-draft-prompt').value;
    _draft.starters = document.getElementById('ag-draft-starters').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    _draft.tags = document.getElementById('ag-draft-tags').value.split(',').map(s => s.trim()).filter(Boolean);
    // Preserve any context the generator attached.
    if (!_draft.context) _draft.context = [];
    return _draft;
  }

  async function save(closeAfter = true) {
    _hideError('ag-draft-error');
    const draft = _readDraft();
    if (!draft.id || !draft.name || !draft.system_prompt) {
      _showError('ag-draft-error', 'id, name, and system_prompt are required.');
      return false;
    }
    try {
      await Net.postJson('/api/agents/generate/save', { draft, overwrite: true }, { retries: 0 });
      if (closeAfter) {
        close();
        if (typeof loadAgentsTab === 'function') loadAgentsTab();
        if (typeof loadAgentsForSelector === 'function') loadAgentsForSelector();
        Toast.success(`Agent '${draft.id}' saved`);
      }
      return true;
    } catch (e) { _showError('ag-draft-error', e.message); return false; }
  }

  function addCase() {
    const el = document.getElementById('ag-cases');
    if (!el) return;
    const row = document.createElement('div');
    row.className = 'ag-case-row';
    row.innerHTML = `
      <input type="text" class="ag-case-prompt" placeholder="Prompt to send the agent">
      <input type="text" class="ag-case-expected" placeholder="Expected substring (optional)">
      <button class="action-btn" data-action="agentgen.case-remove" style="padding:3px 8px;color:var(--danger);border-color:var(--danger-dim)">✕</button>
    `;
    el.appendChild(row);
  }

  async function saveAndEvaluate() {
    _hideError('ag-eval-error');
    const draft = _readDraft();
    const cases = Array.from(document.querySelectorAll('#ag-cases .ag-case-row'))
      .map(r => ({
        prompt: r.querySelector('.ag-case-prompt').value.trim(),
        expected_contains: r.querySelector('.ag-case-expected').value.trim() || null,
      }))
      .filter(c => c.prompt);
    if (!cases.length) {
      _showError('ag-eval-error', 'Add at least one case.');
      return;
    }
    const ok = await save(false);
    if (!ok) return;
    document.getElementById('ag-eval-results').innerHTML = '<div style="color:var(--text-dim);font-size:0.72rem">Running cases…</div>';
    try {
      // retries:0 — multi-case LLM evaluation must not double-fire.
      const report = await Net.postJson(`/api/agents/${encodeURIComponent(draft.id)}/evaluate`, { cases }, { retries: 0 });
      document.getElementById('ag-eval-results').innerHTML = `
        <div style="font-size:0.72rem;margin-bottom:8px">
          <strong>${report.passed} passed</strong> · <span style="color:var(--danger)">${report.failed} failed</span>
        </div>
        ${(report.cases || []).map(c => `
          <div class="ag-case-result">
            <div style="display:flex;gap:6px;align-items:center;margin-bottom:4px">
              <span class="ag-case-pill ${c.passed ? 'pass' : 'fail'}">${c.passed ? 'PASS' : 'FAIL'}</span>
              <span style="font-family:var(--mono);font-size:0.66rem;color:var(--text-dim)">${c.duration_seconds}s</span>
              <span style="font-size:0.7rem;flex:1">${esc(c.prompt)}</span>
            </div>
            <pre style="margin:0;font-size:0.66rem;background:var(--bg-deep);padding:6px 8px;border-radius:3px;white-space:pre-wrap;max-height:120px;overflow:auto">${esc(c.response)}</pre>
          </div>
        `).join('')}
      `;
    } catch (e) { _showError('ag-eval-error', e.message); }
  }

  function close() {
    if (_modal) _modal.hidden = true;
  }

  // Delegated actions — the modal shell + eval-case rows are all
  // JS-rendered templates. agentgen.save mirrors the old explicit
  // AgentGen.save(false) arg.
  Actions.click({
    'agentgen.close':       () => close(),
    'agentgen.generate':    () => generate(),
    'agentgen.step':        el => _showStep(el.dataset.step),
    'agentgen.save':        () => save(false),
    'agentgen.save-eval':   () => saveAndEvaluate(),
    'agentgen.add-case':    () => addCase(),
    'agentgen.case-remove': el => el.parentElement.remove()
  });

  return { openFromDocument, openFromText, generate, save, saveAndEvaluate, addCase, close, _showStep };
})();

/* ══════════════════════════════════════════════════════════════════
   PROJECT BAR — projects are persistent groupings of workflows,
   agents, MCPs, plugins, documents, and chats. The bar appears at the
   top of the composer and lets you switch context + bundle export.
   ══════════════════════════════════════════════════════════════════ */
const Projects = (function () {
  let _projects = [];
  let _active = null;

  async function load() {
    try {
      _projects = await Net.getJson('/api/projects', { silent: true });
      _renderBar();
    } catch (e) { /* offline-tolerant */ }
  }

  function _renderBar() {
    const sel = document.getElementById('project-select');
    if (!sel) return;
    sel.innerHTML = ['<option value="">— no project context —</option>']
      .concat(_projects.map(p => `<option value="${esc(p.id)}">${esc(p.name)} (${(p.counts.workflows||0)+(p.counts.agents||0)+(p.counts.mcp_servers||0)+(p.counts.documents||0)})</option>`))
      .join('');
    if (_active) sel.value = _active;
  }

  function setActive(id) {
    _active = id;
    window._activeProject = id;
    document.getElementById('project-badge').textContent = id || '—';
  }

  // Slugify a free-form name → safe project ID. Server enforces the
  // same alphanum/_/- shape, this is just a convenience so the user
  // doesn't have to type a slug manually.
  function _slugify(s) {
    return (s || '')
      .toLowerCase()
      .trim()
      .replace(/['"]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 64);
  }

  function showCreate() {
    const modal = document.getElementById('project-create-modal');
    if (!modal) return;
    // Reset fields each open so we don't leak previous attempts.
    ['project-create-name','project-create-id','project-create-desc','project-create-category','project-create-tags'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
    document.getElementById('project-create-error').hidden = true;
    // Auto-derive ID from the name as the user types, but only while
    // the ID field is empty / has the previous auto-value.
    const nameEl = document.getElementById('project-create-name');
    const idEl = document.getElementById('project-create-id');
    nameEl.oninput = () => {
      if (!idEl.dataset.userEdited) idEl.value = _slugify(nameEl.value);
    };
    idEl.oninput = () => { idEl.dataset.userEdited = '1'; };
    modal.hidden = false;
    setTimeout(() => nameEl.focus(), 0);
  }

  function _closeCreate() {
    const modal = document.getElementById('project-create-modal');
    if (modal) modal.hidden = true;
  }

  async function _submitCreate() {
    const errBox = document.getElementById('project-create-error');
    const name = document.getElementById('project-create-name').value.trim();
    let id = document.getElementById('project-create-id').value.trim() || _slugify(name);
    const description = document.getElementById('project-create-desc').value.trim();
    const category = document.getElementById('project-create-category').value.trim();
    const tagsRaw = document.getElementById('project-create-tags').value.trim();
    const tags = tagsRaw ? tagsRaw.split(',').map(t => t.trim()).filter(Boolean) : [];

    if (!name) { errBox.hidden = false; errBox.textContent = 'Name is required.'; return; }
    if (!id) { errBox.hidden = false; errBox.textContent = 'ID could not be derived from the name — set one explicitly.'; return; }
    if (!/^[A-Za-z0-9_-]+$/.test(id)) {
      errBox.hidden = false;
      errBox.textContent = "ID can only contain letters, digits, '_' and '-'.";
      return;
    }
    try {
      const body = { id, name };
      if (description) body.description = description;
      if (category) body.category = category;
      if (tags.length) body.tags = tags;
      const r = await Net.call('/api/projects', {
        retries: 0,
        init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      });
      if (!r.ok) {
        const detail = typeof r.data === 'string' ? r.data : (r.data && (r.data.detail || r.data.error)) || r.error || '';
        errBox.hidden = false;
        errBox.textContent = `Create failed: ${detail}`;
        return;
      }
      _closeCreate();
      await load();
      setActive(id);
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = `Create error: ${e.message}`;
    }
  }

  // Legacy alias: any old call site still hitting `Projects.create()`
  // now opens the modal instead of the old prompt() flow.
  async function create() { showCreate(); }

  async function attachCurrentWorkflow() {
    if (!_active) { Toast.warn('Pick a project first.'); return; }
    const wfId = (document.getElementById('df-wf-id') || {}).value;
    if (!wfId) { Toast.warn('Set a workflow ID first.'); return; }
    try {
      const r = await Net.call(`/api/projects/${encodeURIComponent(_active)}/artifacts/workflows/${encodeURIComponent(wfId)}`, { retries: 0, init: { method: 'POST' } });
      if (!r.ok) { Toast.danger('Attach failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      Toast.success(`Workflow '${wfId}' attached`, `project '${_active}'`);
      await load();
    } catch (e) { Toast.danger('Attach error', e.message); }
  }

  async function exportBundle() {
    if (!_active) { Toast.warn('Pick a project first.'); return; }
    try {
      const r = await Net.call(`/api/projects/${encodeURIComponent(_active)}/export`);
      if (!r.ok) { Toast.danger('Export failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
      const bundle = r.data;
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${_active}.project.json`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) { Toast.danger('Export error', e.message); }
  }

  function importBundle() {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.json';
    inp.onchange = async () => {
      const file = inp.files && inp.files[0];
      if (!file) return;
      const text = await file.text();
      try {
        const bundle = JSON.parse(text);
        const r = await Net.call('/api/projects/import?overwrite=true', {
          retries: 0,
          init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) },
        });
        if (!r.ok) { Toast.danger('Import failed', typeof r.data === 'string' ? r.data : (r.error || '')); return; }
        const result = r.data;
        Toast.success(`Imported project '${result.project_id}'`);
        await load();
        setActive(result.project_id);
      } catch (e) { Toast.danger('Import error', e.message); }
    };
    inp.click();
  }

  return {
    load, setActive, create, attachCurrentWorkflow, exportBundle, importBundle,
    showCreate, _closeCreate, _submitCreate,
  };
})();

/* Operator-journey: adoption ladder + next-best-action nudges.
   Reads only real, derivable signals (chat history, canvas node count, and
   cached run/workflow existence) — honest about state, defensive about
   missing globals. Future stages (pins, fleet) light up as those land. */
(function () {
  var STAGES = [
    { id: 'seed',     label: 'Seed a chat',           hint: 'start a conversation' },
    { id: 'scaffold', label: 'Scaffold a plan',       hint: 'hand it to your agents' },
    { id: 'run',      label: 'Run it',                hint: 'execute the workflow' },
    { id: 'save',     label: 'Save the workflow',     hint: 'keep it for reuse' },
    { id: 'fleet',    label: 'Schedule on the fleet', hint: 'coming in 1.4', future: true },
  ];
  var _async = { runs: false, wfs: false, at: 0, inflight: false };

  function _n(fn, d) { try { return fn(); } catch (e) { return d; } }
  function chatLen()   { return _n(function () { return (typeof chatHistory !== 'undefined' && chatHistory) ? chatHistory.length : 0; }, 0); }
  function nodeCount() { return _n(function () { return (typeof dfNodeData !== 'undefined' && dfNodeData) ? Object.keys(dfNodeData).length : 0; }, 0); }
  function pinCount()  { return _n(function () { return (window._enclavePins && window._enclavePins.length) || 0; }, 0); }

  function refreshAsync() {
    var now = Date.now();
    if (_async.inflight || now - _async.at < 30000) return;
    _async.inflight = true; _async.at = now;
    fetch('/api/workflows/runs?limit=1').then(function (r) { return r.json(); })
      .then(function (d) { _async.runs = Array.isArray(d) ? d.length > 0 : !!(d && d.length); }).catch(function () {})
      .finally(function () {
        fetch('/api/workflows').then(function (r) { return r.json(); })
          .then(function (d) { var a = Array.isArray(d) ? d : (d && d.workflows) || []; _async.wfs = a.length > 0; }).catch(function () {})
          .finally(function () { _async.inflight = false; render(); });
      });
  }

  function computeState() {
    var seed = chatLen() > 0 || pinCount() > 0;
    var scaf = nodeCount() > 0;
    var st = [
      { done: seed,        locked: false },
      { done: scaf,        locked: !seed },
      { done: _async.runs, locked: !scaf },
      { done: _async.wfs,  locked: !scaf },
      { done: false,       locked: true, future: true },
    ];
    for (var i = 0; i < st.length; i++) { if (!st[i].done && !st[i].locked && !st[i].future) { st[i].hot = true; break; } }
    return st;
  }
  function cls(s) { return s.done ? 'done' : s.hot ? 'hot' : s.locked ? 'locked' : ''; }

  function render() {
    var stagesEl = document.getElementById('op-path-stages');
    var countEl = document.getElementById('op-path-count');
    var popEl = document.getElementById('op-path-pop');
    if (!stagesEl) return;
    var st = computeState();
    var done = st.filter(function (s) { return s.done; }).length;
    stagesEl.innerHTML = st.map(function (s, i) {
      return '<span class="op-stage ' + cls(s) + '" title="' + STAGES[i].label + '">' + (s.done ? '✓' : (i + 1)) + '</span>';
    }).join('');
    if (countEl) countEl.textContent = done + '/' + st.length;
    if (popEl) {
      popEl.innerHTML = '<h4>Operator’s path</h4>' + st.map(function (s, i) {
        return '<div class="op-path-row ' + cls(s) + '"><span class="n">' + (s.done ? '✓' : (i + 1)) +
          '</span><span class="lbl">' + STAGES[i].label + '<span class="hint">' + STAGES[i].hint + '</span></span></div>';
      }).join('');
    }
    renderNudges();
  }

  /* next-best-action nudges — calm: at most one shown at a time */
  var NUDGES = [
    { key: 'scaffold', text: 'This conversation is taking shape — hand it to your agents.',
      when: function () { return chatLen() >= 4 && nodeCount() === 0; },
      act: function () { var b = document.querySelector('.bs-dispatch'); if (b) b.scrollIntoView({ block: 'center', behavior: 'smooth' }); } },
    { key: 'run', text: 'Your plan is built — run it.',
      when: function () { return nodeCount() > 0 && !_async.runs; },
      act: function () { if (typeof dfRunWorkflowFromComposer === 'function') dfRunWorkflowFromComposer(); } },
    { key: 'save', text: 'Run it to save this workflow for reuse.',
      when: function () { return nodeCount() > 0 && _async.runs && !_async.wfs; },
      act: function () { if (typeof dfRunWorkflowFromComposer === 'function') dfRunWorkflowFromComposer(); } },
  ];
  var _dismissed = (function () { try { return JSON.parse(localStorage.getItem('enclave.nba.dismissed') || '{}'); } catch (e) { return {}; } })();
  function dismiss(key) {
    _dismissed[key] = 1;
    try { localStorage.setItem('enclave.nba.dismissed', JSON.stringify(_dismissed)); } catch (e) {}
    render();
  }
  function renderNudges() {
    var box = document.getElementById('nba-container');
    if (!box) return;
    var n = null;
    for (var i = 0; i < NUDGES.length; i++) { if (!_dismissed[NUDGES[i].key] && _n(NUDGES[i].when, false)) { n = NUDGES[i]; break; } }
    if (!n) { box.innerHTML = ''; box.removeAttribute('data-nba'); return; }
    if (box.getAttribute('data-nba') === n.key) return; // avoid churn if unchanged
    box.setAttribute('data-nba', n.key);
    box.innerHTML = '<span class="nba-nudge"><span class="nba-go">' + n.text +
      '</span><button class="x" title="Dismiss" aria-label="Dismiss">×</button></span>';
    var go = box.querySelector('.nba-go');
    if (go) go.onclick = function () { _n(n.act, null); };
    var x = box.querySelector('.x');
    if (x) x.onclick = function (e) { e.stopPropagation(); dismiss(n.key); };
  }

  function togglePop(force) {
    var pop = document.getElementById('op-path-pop');
    if (!pop) return;
    pop.classList.toggle('open', force != null ? force : !pop.classList.contains('open'));
  }

  function init() {
    var bar = document.getElementById('op-path-bar');
    if (bar) bar.addEventListener('click', function (e) { if (e.target.closest('.op-path-pop')) return; togglePop(); });
    document.addEventListener('click', function (e) { if (!e.target.closest('#op-path-bar')) togglePop(false); });
    render();
    refreshAsync();
    setInterval(function () { render(); refreshAsync(); }, 4000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  window.OpPath = { refresh: render, togglePop: togglePop, _dismissNudge: dismiss };
})();
/* Pin-as-step: mark chat replies, watch a maturity meter, and convert 2+ pins
   into a runnable DAG via the same composerLoadDefinition path BootSequence
   uses. Each pin → one step; steps chain in pin order; full source
   traceability shown in the scaffold preview. Additive — never touches the
   existing single-thread chat or BootSequence. */
(function () {
  var pins = window._enclavePins = window._enclavePins || [];

  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _text(msgId) {
    var el = document.getElementById(msgId);
    if (!el) return '';
    return (el.innerText || '')
      .replace(/\s+▲\s+▼\s+copy.*$/s, '')
      .replace(/◇\s*pin as step|◆\s*pinned/g, '')
      .replace(/run this with my agents/g, '')
      .trim();
  }
  function _title(text, i) {
    var first = ((text || '').split('\n')[0] || '').trim();
    if (!first) return 'Step ' + (i + 1);
    return first.length > 48 ? first.slice(0, 46) + '…' : first;
  }
  function renumber() { pins.forEach(function (p, i) { p.title = _title(p.text, i); }); }

  function syncButtons() {
    document.querySelectorAll('.msg-pin-btn').forEach(function (b) {
      var on = pins.some(function (p) { return p.msgId === b.getAttribute('data-pin'); });
      b.classList.toggle('pinned', on);
      b.innerHTML = on ? '◆ pinned' : '◇ pin as step';
    });
  }

  function render() {
    var meter = document.getElementById('pins-meter');
    if (!meter) return;
    meter.classList.toggle('show', pins.length > 0);
    var bar = document.getElementById('pm-bar');
    if (bar) {
      var html = '';
      for (var i = 0; i < 5; i++) html += '<span class="pm-seg' + (i < pins.length ? ' on' : '') + '"></span>';
      bar.innerHTML = html;
    }
    var cnt = document.getElementById('pm-count'); if (cnt) cnt.textContent = pins.length;
    var conv = document.getElementById('pm-convert');
    if (conv) {
      conv.disabled = pins.length < 2;
      conv.textContent = pins.length < 2 ? 'Pin 2+ to convert' : ('Convert ' + pins.length + ' → workflow →');
    }
    syncButtons();
  }

  function toggle(msgId, btn) {
    var idx = pins.findIndex(function (p) { return p.msgId === msgId; });
    if (idx >= 0) pins.splice(idx, 1);
    else pins.push({ id: 'pin-' + msgId, msgId: msgId, role: 'reasoning', text: _text(msgId) });
    renumber();
    render();
    if (window.OpPath) window.OpPath.refresh();
  }

  function openScaffold() {
    if (pins.length < 2) return;
    var box = document.getElementById('sm-steps');
    if (box) {
      box.innerHTML = pins.map(function (p, i) {
        return '<div class="sm-step"><span class="sm-n">' + (i + 1) + '</span><div class="sm-body">' +
          '<span class="sm-title">' + _esc(p.title) + '</span><span class="sm-role">' + _esc(p.role) + '</span>' +
          '<span class="sm-src">← pinned from this reply</span>' +
          '<span class="sm-text">' + _esc((p.text || '').slice(0, 180)) + '</span></div></div>';
      }).join('');
    }
    var b = document.getElementById('scaffold-modal-backdrop');
    if (b) b.classList.add('open');
  }

  function convert() {
    var defn = {
      id: 'thread-' + Date.now(),
      name: 'From conversation',
      description: 'Scaffolded from ' + pins.length + ' pinned replies',
      steps: pins.map(function (p, i) {
        return {
          id: 'step-' + (i + 1),
          name: p.title || ('Step ' + (i + 1)),
          role: p.role || 'reasoning',
          system_prompt: p.text || '',
          depends_on: i > 0 ? ['step-' + i] : [],
        };
      }),
    };
    if (window.ScaffoldModal) window.ScaffoldModal.close();
    try {
      if (typeof composerLoadDefinition === 'function') composerLoadDefinition(defn);
      if (typeof ComposerSplit !== 'undefined' && ComposerSplit.setMode) ComposerSplit.setMode('canvas');
    } catch (e) { console.warn('pin-convert failed:', e); }
    if (window.OpPath) window.OpPath.refresh();
  }

  window.Pins = { toggle: toggle, render: render, openScaffold: openScaffold, convert: convert };
  window.ScaffoldModal = {
    close: function () { var b = document.getElementById('scaffold-modal-backdrop'); if (b) b.classList.remove('open'); },
  };
  document.addEventListener('click', function (e) {
    var b = document.getElementById('scaffold-modal-backdrop');
    if (b && e.target === b) b.classList.remove('open');
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render);
  else render();
})();
/* Thread switcher: juggle multiple conversations by snapshotting/restoring
   chat history + rendered messages + pins. Additive — never modifies
   sendMessage or the renderer; snapshots are taken lazily at switch time.
   Now persisted server-side (POST/GET /api/conversations) so threads survive
   reload; best-effort — falls back to in-memory if the server is unreachable. */
(function () {
  var threads = [], activeId = null, _lastSavedLen = -1, _autosave = null;

  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _msgEl() { return document.getElementById('messages'); }
  function _histGet() { try { return (typeof chatHistory !== 'undefined' && chatHistory) ? chatHistory.slice() : []; } catch (e) { return []; } }
  function _histSet(arr) { try { if (typeof chatHistory !== 'undefined' && chatHistory) { chatHistory.length = 0; Array.prototype.push.apply(chatHistory, arr || []); } } catch (e) {} }
  function _pinsGet() { try { return (window._enclavePins || []).slice(); } catch (e) { return []; } }
  function _pinsSet(arr) { try { var p = window._enclavePins = window._enclavePins || []; p.length = 0; Array.prototype.push.apply(p, arr || []); if (window.Pins) window.Pins.render(); } catch (e) {} }
  function _model() { try { return (document.getElementById('model-select') || {}).value || null; } catch (e) { return null; } }

  function _snapshot() {
    var t = threads.find(function (x) { return x.id === activeId; });
    if (!t) return;
    t.history = _histGet();
    var m = _msgEl(); t.messagesHtml = m ? m.innerHTML : '';
    t.pins = _pinsGet();
  }
  function _restore(t) {
    _histSet(t.history);
    var m = _msgEl(); if (m) m.innerHTML = t.messagesHtml || '';
    _pinsSet(t.pins);
    if (window.OpPath) window.OpPath.refresh();
    if (typeof ChatRating !== 'undefined' && ChatRating.rehydrate) { try { ChatRating.rehydrate(); } catch (e) {} }
  }

  // ── Server persistence (best-effort) ───────────────────────────────────
  function _persist(t) {
    if (!t || (!(t.history && t.history.length) && !(t.messagesHtml))) return;
    try {
      fetch('/api/conversations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: t.id, title: t.name, model: _model(),
          messages: t.history || [], html: (t.messagesHtml || '').slice(0, 400000),
          pins: t.pins || [],
        }),
      }).catch(function () {});
    } catch (e) {}
  }
  function save() { _snapshot(); var t = threads.find(function (x) { return x.id === activeId; }); _persist(t); }
  function _autosaveTick() {
    var len = _histGet().length;
    if (len !== _lastSavedLen) { _lastSavedLen = len; if (len > 0) save(); }
  }
  function _remove(id) {
    try { fetch('/api/conversations/' + encodeURIComponent(id), { method: 'DELETE' }).catch(function () {}); } catch (e) {}
  }

  function create() {
    save();
    var t = { id: 't' + Date.now(), name: 'Thread ' + (threads.length + 1), history: [], messagesHtml: '', pins: [] };
    threads.unshift(t);
    activeId = t.id;
    _lastSavedLen = 0;
    _restore(t); // clear the live chat to the empty new thread
    closeMenu(); renderName();
  }
  function pick(id) {
    if (id === activeId) { closeMenu(); return; }
    save();
    var t = threads.find(function (x) { return x.id === id; });
    if (!t) return;
    activeId = t.id;
    closeMenu(); renderName();
    // Lazily hydrate the full transcript from the server if we only hold a summary.
    if (t._loaded === false) {
      fetch('/api/conversations/' + encodeURIComponent(id)).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (full) {
          if (full) { t.history = full.messages || []; t.messagesHtml = full.html || ''; t.pins = full.pins || []; t._loaded = true; }
          _lastSavedLen = (t.history || []).length;
          _restore(t);
        }).catch(function () { _restore(t); });
    } else {
      _lastSavedLen = (t.history || []).length;
      _restore(t);
    }
  }
  function del(id) {
    var idx = threads.findIndex(function (x) { return x.id === id; });
    if (idx < 0) return;
    if (!window.confirm('Delete this thread? This cannot be undone.')) return;
    _remove(id);
    threads.splice(idx, 1);
    if (id === activeId) {
      if (threads.length === 0) { create(); return; }
      activeId = threads[0].id; threads[0]._loaded = threads[0]._loaded === undefined ? true : threads[0]._loaded;
      _restore(threads[0]); renderName();
    }
    renderMenu();
  }
  function rename(id) {
    var t = threads.find(function (x) { return x.id === id; });
    if (!t) return;
    var v = window.prompt('Rename thread', t.name);
    if (v != null && v.trim()) { t.name = v.trim().slice(0, 48); renderName(); renderMenu(); _persist(t); }
  }

  function renderName() {
    var el = document.getElementById('thread-active-name');
    var t = threads.find(function (x) { return x.id === activeId; });
    if (el && t) el.textContent = t.name;
  }
  function renderMenu() {
    var menu = document.getElementById('thread-menu');
    if (!menu) return;
    menu.innerHTML = threads.map(function (t) {
      return '<div class="thread-item' + (t.id === activeId ? ' active' : '') + '" onclick="Threads.pick(\'' + t.id + '\')">' +
        '<span class="ti-name">' + _esc(t.name) + '</span>' +
        '<button type="button" class="ti-rename" title="Rename" onclick="event.stopPropagation();Threads.rename(\'' + t.id + '\')">rename</button>' +
        '<button type="button" class="ti-rename" title="Delete" onclick="event.stopPropagation();Threads.del(\'' + t.id + '\')">del</button></div>';
    }).join('');
  }
  function toggleMenu() {
    var menu = document.getElementById('thread-menu');
    if (!menu) return;
    var open = !menu.classList.contains('open');
    if (open) renderMenu();
    menu.classList.toggle('open', open);
  }
  function closeMenu() { var m = document.getElementById('thread-menu'); if (m) m.classList.remove('open'); }

  function init() {
    // Thread 1 represents the live chat; its snapshot is taken on first switch.
    var live = { id: 't' + Date.now(), name: 'Thread 1', history: [], messagesHtml: '', pins: [], _loaded: true };
    threads = [live];
    activeId = live.id;
    renderName();
    document.addEventListener('click', function (e) { if (!e.target.closest('#thread-bar')) closeMenu(); });
    // Pull any persisted threads in behind the live one (summaries only;
    // transcripts hydrate lazily on pick).
    fetch('/api/conversations').then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.conversations) return;
        data.conversations.forEach(function (s) {
          if (s.id === activeId) return;
          threads.push({ id: s.id, name: s.title || 'Thread', history: [], messagesHtml: '', pins: [], _loaded: false });
        });
      }).catch(function () {});
    // Autosave the live thread so an unswitched conversation still survives reload.
    _autosave = setInterval(_autosaveTick, 15000);
    window.addEventListener('beforeunload', function () { try { save(); } catch (e) {} });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  window.Threads = { create: create, pick: pick, rename: rename, del: del, save: save, toggleMenu: toggleMenu };
})();
/* Model-compare grid + 4-phase install wizard. Both self-contained over the
   real catalog/enrichment/pull endpoints; compare ends in "seed a chat", the
   wizard's land phase verifies-by-conversation. */
(function () {
  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _num(v) { if (v == null) return null; var m = String(v).match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; }

  // ── Compare ────────────────────────────────────────────────────────
  var sel = [], _cat = null, _enr = null;
  async function _catalog() { if (_cat) return _cat; try { var d = await (await fetch('/api/inventory/catalog')).json(); _cat = d.models || d || []; } catch (e) { _cat = []; } return _cat; }
  async function _enrich() { if (_enr) return _enr; try { _enr = await (await fetch('/api/inventory/enrichment')).json(); } catch (e) { _enr = {}; } return _enr; }
  function add(id) { if (sel.indexOf(id) < 0) { if (sel.length >= 3) sel.shift(); sel.push(id); } renderTray(); }
  function remove(id) { sel = sel.filter(function (x) { return x !== id; }); renderTray(); }
  function renderTray() {
    var tray = document.getElementById('cmp-tray'); if (!tray) return;
    tray.classList.toggle('show', sel.length > 0);
    var chips = document.getElementById('cmp-chips');
    if (chips) chips.innerHTML = sel.map(function (id) { return '<span class="cmp-chip">' + _esc(id) + '<span class="x" onclick="Compare.remove(\'' + id + '\')">×</span></span>'; }).join('');
    var go = document.getElementById('cmp-go'); if (go) { go.disabled = sel.length < 2; go.textContent = 'Compare ' + sel.length + ' →'; }
  }
  async function openCompare() {
    if (sel.length < 2) return;
    var cat = await _catalog(), enr = await _enrich();
    var ms = sel.map(function (id) { var m = cat.find(function (x) { return x.id === id || x.ollama === id; }) || { id: id, name: id }; var e = enr[m.id] || enr[m.ollama] || {}; return { m: m, e: e }; });
    var rows = [];
    function push(k, get, numeric) { rows.push({ k: k, vals: ms.map(get), numeric: numeric }); }
    push('params', function (o) { return o.e.params || ''; }, true);
    push('size', function (o) { return o.m.size || ''; }, true);
    push('speed', function (o) { return o.m.speed || ''; }, true);
    push('context', function (o) { return o.m.context || ''; }, true);
    push('license', function (o) { return o.e.license || ''; }, false);
    var bk = {}; ms.forEach(function (o) { Object.keys(o.e.benchmarks || {}).forEach(function (k) { bk[k] = 1; }); });
    Object.keys(bk).forEach(function (k) { push(k, function (o) { return (o.e.benchmarks || {})[k]; }, true); });
    var html = '<table class="cmp-grid"><thead><tr><th></th>' + ms.map(function (o) { return '<th>' + _esc(o.m.name || o.m.id) + '</th>'; }).join('') + '</tr></thead><tbody>';
    rows.forEach(function (r) {
      var nums = r.numeric ? r.vals.map(_num) : [];
      var max = r.numeric ? Math.max.apply(null, nums.filter(function (x) { return x != null; }).concat([-Infinity])) : null;
      var uniqueMax = r.numeric && isFinite(max) && nums.filter(function (x) { return x === max; }).length === 1;
      html += '<tr><td class="k">' + _esc(r.k) + '</td>' + r.vals.map(function (v, i) {
        var win = uniqueMax && nums[i] === max;
        return '<td class="' + (win ? 'win' : '') + '">' + (v == null || v === '' ? '—' : _esc(String(v))) + '</td>';
      }).join('') + '</tr>';
    });
    html += '<tr class="cmp-seed-row"><td></td>' + ms.map(function (o) { var mid = o.m.ollama || o.m.id; return '<td><button class="cmp-seed" onclick="Compare.closeModal();AssetPeek.seedChat(\'' + _esc(mid) + '\')">Seed a chat →</button></td>'; }).join('') + '</tr>';
    html += '</tbody></table>';
    document.getElementById('cmp-grid-mount').innerHTML = html;
    document.getElementById('cmp-modal-backdrop').classList.add('open');
  }
  function closeCompare() { var b = document.getElementById('cmp-modal-backdrop'); if (b) b.classList.remove('open'); }
  window.Compare = { add: add, remove: remove, open: openCompare, closeModal: closeCompare };

  // ── Install wizard (4-phase: source → configure → verify → land) ────
  var PHASES = ['Source', 'Configure', 'Verify', 'Land'];
  var st = { model: '', phase: 0, poll: null };
  function iwOpen(prefill) { st = { model: prefill || '', phase: 0, poll: null }; var b = document.getElementById('iw-backdrop'); if (b) b.classList.add('open'); iwRender(); }
  function iwClose() { if (st.poll) { clearInterval(st.poll); st.poll = null; } var b = document.getElementById('iw-backdrop'); if (b) b.classList.remove('open'); }
  function iwRender() {
    var ph = document.getElementById('iw-phases'), body = document.getElementById('iw-body'), acts = document.getElementById('iw-actions');
    if (!ph) return;
    ph.innerHTML = PHASES.map(function (p, i) {
      var conn = i > 0 ? '<span class="encl-wconn" aria-hidden="true"></span>' : '';
      var c = i < st.phase ? 'done' : (i === st.phase ? 'on' : '');
      return conn + '<span class="encl-wstep ' + c + '"><span class="n">' + (i < st.phase ? '✓' : (i + 1)) + '</span>' + p + '</span>';
    }).join('');
    if (st.phase === 0) {
      body.innerHTML = '<p style="color:var(--text-dim);font-size:var(--text-sm,0.8rem);margin:0 0 10px">Name the model to pull locally (Ollama tag or hf.co path). Only the model download leaves your machine.</p><input type="text" id="iw-model" placeholder="e.g. qwen2.5:7b" value="' + _esc(st.model) + '">';
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="InstallWizard.close()">Cancel</button><button type="button" class="action-btn accent" onclick="InstallWizard.next()">Next →</button>';
    } else if (st.phase === 1) {
      body.innerHTML = '<div style="font-family:var(--mono);font-size:var(--text-sm,0.8rem);color:var(--text)">Source<br><span style="color:var(--accent)">' + _esc(st.model) + '</span></div><p style="color:var(--text-dim);font-size:var(--text-xs,0.7rem);margin-top:10px">Quantization and context are encoded in the tag. The pull runs against your local Ollama daemon.</p>';
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="InstallWizard.back()">← Back</button><button type="button" class="action-btn accent" onclick="InstallWizard.next()">Pull →</button>';
    } else if (st.phase === 2) {
      body.innerHTML = '<div class="iw-prog"><div class="iw-prog-fill" id="iw-fill"></div></div><div class="iw-prog-label" id="iw-label">starting…</div>';
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="InstallWizard.close()">Cancel</button>';
      iwPull();
    } else {
      body.innerHTML = '<div style="font-family:var(--mono);color:var(--accent);font-size:var(--text-sm,0.8rem)">✓ ' + _esc(st.model) + ' installed</div><p style="color:var(--text-dim);font-size:var(--text-xs,0.7rem);margin-top:8px">Verify it the honest way — start a conversation.</p>';
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="InstallWizard.close()">Done</button><button type="button" class="action-btn accent" onclick="InstallWizard.land()">Seed a chat →</button>';
    }
  }
  function iwNext() {
    if (st.phase === 0) { var inp = document.getElementById('iw-model'); st.model = inp ? inp.value.trim() : st.model; if (!st.model) return; }
    st.phase = Math.min(3, st.phase + 1); iwRender();
  }
  function iwBack() { st.phase = Math.max(0, st.phase - 1); iwRender(); }
  function iwPull() {
    fetch('/api/inventory/pull', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: st.model }) }).catch(function () {});
    st.poll = setInterval(async function () {
      var fill = document.getElementById('iw-fill'), label = document.getElementById('iw-label');
      try {
        var d = await (await fetch('/api/inventory/pull-progress/' + encodeURIComponent(st.model))).json();
        var phase = d.status_message || d.status || 'pulling';
        if (d.total > 0 && fill) { var pct = Math.round(d.progress / d.total * 100); fill.style.width = pct + '%'; if (label) label.textContent = phase + ' — ' + pct + '%'; }
        else if (label) label.textContent = phase + '…';
        if (d.status === 'complete' || d.status === 'error') {
          clearInterval(st.poll); st.poll = null;
          if (d.status === 'complete') {
            if (fill) fill.style.width = '100%';
            st.phase = 3; iwRender();
            try { if (typeof catalogLoaded !== 'undefined') catalogLoaded = false; if (typeof loadCatalog === 'function') loadCatalog(); } catch (e) {}
          } else {
            if (label) { label.textContent = '✗ ' + (d.error || 'pull failed'); label.style.color = 'var(--danger,#ff5252)'; }
            var acts = document.getElementById('iw-actions');
            if (acts) acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="InstallWizard.close()">Close</button><button type="button" class="action-btn accent" onclick="InstallWizard.retry()">Retry</button>';
          }
        }
      } catch (e) { clearInterval(st.poll); st.poll = null; }
    }, 800);
  }
  function iwRetry() { st.phase = 2; iwRender(); }
  function iwLand() { var m = st.model; iwClose(); if (window.AssetPeek) AssetPeek.seedChat(m); }
  window.InstallWizard = { open: iwOpen, close: iwClose, next: iwNext, back: iwBack, retry: iwRetry, land: iwLand };

  document.addEventListener('click', function (e) {
    ['cmp-modal-backdrop', 'iw-backdrop'].forEach(function (id) {
      var b = document.getElementById(id);
      if (b && e.target === b) { b.classList.remove('open'); if (id === 'iw-backdrop' && st.poll) { clearInterval(st.poll); st.poll = null; } }
    });
  });
})();
/* Run lens: a scrub timeline + per-step timing plates + an as-executed
   inspector (rendered system prompt / prompt / output, as they actually ran).
   A new view over EXISTING run telemetry (window._lastRunSummary or a fetched
   run) — no new backend. Defensive about which telemetry fields exist. */
(function () {
  var run = null, steps = [], seli = 0;
  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _dur(s) { return Math.max(0, +(s.duration_seconds || 0)); }

  async function open(runOrId) {
    var src = runOrId || window._lastRunSummary;
    if (typeof src === 'string') { try { src = await (await fetch('/api/workflows/runs/' + encodeURIComponent(src))).json(); } catch (e) { src = null; } }
    if (!src) { if (window.Toast) Toast.info('No run', 'Pick or start a run first.'); return; }
    run = src; steps = run.step_results || []; seli = 0;
    if (!steps.length) { if (window.Toast) Toast.info('No steps', 'This run has no recorded steps yet.'); return; }
    renderMeta(); renderScrub(); renderPlates(); renderInspect();
    var b = document.getElementById('rl-backdrop'); if (b) b.classList.add('open');
  }
  function close() { var b = document.getElementById('rl-backdrop'); if (b) b.classList.remove('open'); }
  function select(i) { seli = i; renderScrub(); renderPlates(); renderInspect(); }

  function renderMeta() {
    var el = document.getElementById('rl-run-meta'); if (!el) return;
    var total = steps.reduce(function (a, s) { return a + _dur(s); }, 0);
    el.innerHTML = '<span><b>' + _esc(run.workflow_id || run.name || run.run_id || 'run') + '</b></span>' +
      '<span>status ' + _esc(run.status || '—') + '</span>' +
      '<span>' + steps.length + ' steps</span>' +
      '<span>' + total.toFixed(1) + 's total</span>';
    // Distribution across steps — duration + token ranges (StatRange).
    var rangesEl = document.getElementById('rl-ranges');
    if (rangesEl) {
      var durs = steps.map(_dur).filter(function (d) { return d > 0; });
      var toks = steps.map(function (s) { var t = s.token_count || {}; return t.total_tokens || t.total || 0; }).filter(function (t) { return t > 0; });
      var html = '';
      if (durs.length >= 2) html += enclStatRange({ label: 'step duration', data: durs, unit: 's', floor: 0, color: 'var(--accent)' });
      if (toks.length >= 2) html += enclStatRange({ label: 'tokens / step', data: toks, floor: 0, color: 'var(--accent-2)' });
      rangesEl.innerHTML = html;
    }
  }
  function renderScrub() {
    var el = document.getElementById('rl-scrub'); if (!el) return;
    var max = Math.max.apply(null, steps.map(_dur).concat([0.001]));
    el.innerHTML = steps.map(function (s, i) {
      var w = Math.max(6, (_dur(s) / max) * 100);
      return '<div class="rl-seg ' + _esc(s.status || '') + (i === seli ? ' sel' : '') + '" style="flex-grow:' + w.toFixed(1) +
        '" title="' + _esc(s.step_id) + ' · ' + _dur(s).toFixed(1) + 's" onclick="RunLens.select(' + i + ')">' +
        '<span class="rl-seg-lbl">' + _esc(s.step_id) + '</span></div>';
    }).join('');
  }
  function renderPlates() {
    var el = document.getElementById('rl-plates'); if (!el) return;
    el.innerHTML = steps.map(function (s, i) {
      var tc = s.token_count || {};
      var tok = tc.total_tokens || tc.total || '';
      var pr = (s.pressure_after && s.pressure_after.level) || '';
      return '<div class="rl-plate' + (i === seli ? ' sel' : '') + '" onclick="RunLens.select(' + i + ')">' +
        '<div class="rl-p-name">' + _esc(s.step_id) + '</div>' +
        '<div class="rl-p-meta">' + _dur(s).toFixed(1) + 's' + (tok ? (' · ' + tok + 'tok') : '') + (pr ? (' · ' + _esc(pr)) : '') + '</div></div>';
    }).join('');
  }
  function _block(label, text) { return text ? '<div class="rl-block"><div class="rl-b-label">' + _esc(label) + '</div><pre>' + _esc(text) + '</pre></div>' : ''; }
  function renderInspect() {
    var el = document.getElementById('rl-inspect'); if (!el) return;
    var s = steps[seli]; if (!s) { el.innerHTML = ''; return; }
    var tc = s.token_count || {};
    var output = (run.context && run.context.workspace && run.context.workspace[s.step_id]) || s.output || s.result || '';
    if (output && typeof output === 'object') { try { output = JSON.stringify(output, null, 2); } catch (e) { output = String(output); } }
    el.innerHTML = '<div class="rl-i-kv">' +
      '<span>step <b>' + _esc(s.step_id) + '</b></span>' +
      '<span>' + _esc(s.status || '—') + '</span>' +
      (s.model_used ? '<span>model <b>' + _esc(s.model_used) + '</b></span>' : '') +
      '<span>' + _dur(s).toFixed(1) + 's</span>' +
      ((tc.prompt_tokens != null || tc.total_tokens != null) ? '<span>tok ' + _esc((tc.prompt_tokens || 0) + '+' + (tc.completion_tokens || 0) + '=' + (tc.total_tokens || 0)) + '</span>' : '') +
      '</div>' +
      _block('rendered system prompt', s.rendered_system_prompt) +
      _block('rendered prompt', s.rendered_prompt) +
      _block('output (as executed)', typeof output === 'string' ? output : '') +
      (s.error ? _block('error', s.error) : '');
  }
  document.addEventListener('click', function (e) { var b = document.getElementById('rl-backdrop'); if (b && e.target === b) b.classList.remove('open'); });
  window.RunLens = { open: open, close: close, select: select };
})();
/* Canonical SeedChip helper — returns the design-system key:value seed chip as
   an HTML string (vanilla idiom). Tones: accent / emerald / warm / info /
   neutral; optional ghost (dashed, clickable) + dismiss. Used by the
   research→context→agent flow and any thread-seed header. */
(function () {
  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  var TONE = {
    accent:  '--st:var(--accent);--st-dim:var(--accent-dim);--st-ghost:var(--accent-ghost)',
    emerald: '--st:var(--accent-2-bright);--st-dim:var(--accent-2-dim);--st-ghost:var(--accent-2-ghost)',
    warm:    '--st:var(--accent-warm);--st-dim:var(--accent-warm-dim);--st-ghost:var(--accent-warm-ghost)',
    info:    '--st:var(--info);--st-dim:var(--info-dim);--st-ghost:var(--info-ghost)',
  };
  window.SeedChip = {
    html: function (o) {
      o = o || {};
      var toned = o.tone && o.tone !== 'neutral';
      var style = toned ? (TONE[o.tone] || TONE.accent) : '';
      var cls = 'encl-seedchip' + (toned ? ' accent' : '') + (o.ghost ? ' ghost' : '');
      return '<span class="' + cls + '"' + (style ? ' style="' + style + '"' : '') +
        (o.onclick ? ' onclick="' + o.onclick + '"' : '') + '>' +
        (o.k ? '<span class="k">' + _esc(o.k) + '</span>' : '') +
        '<span>' + _esc(o.v) + '</span>' +
        (o.onRemove ? '<span class="x" onclick="' + o.onRemove + '" aria-label="Remove">×</span>' : '') +
        '</span>';
    },
  };
})();
/* Flow 5 — research → context → agent. A 4-phase wizard that turns the
   existing deep-research output into a reusable agent: the research IS the
   context bundle (carried into the agent via /api/agents/generate
   include_source_as_context), and the agent is verified by seeding a chat —
   "every object is born in a conversation". Reuses WizardStepper + SeedChip +
   AssetPeek.seedChat + the real agent-generate/save endpoints. Defensive. */
(function () {
  var PHASES = ['Research', 'Context', 'Agent', 'Verify'];
  var st = { phase: 0, topic: '', text: '', name: '', role: 'reasoning', draft: null, agentId: null };
  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  function _researchText() {
    var out = document.getElementById('research-output');
    var t = out ? (out.innerText || '').trim() : '';
    return t.slice(0, 8000);
  }
  function _topic() {
    var lr = window._lastResearch;
    if (lr && (lr.topic || lr.query)) return lr.topic || lr.query;
    var inp = document.getElementById('research-topic');
    return inp ? inp.value.trim() : '';
  }
  function _slug(s) { return (s || 'researched').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 32); }

  function open() {
    var text = _researchText();
    if (!text || text.length < 40 || /Enter a topic above/.test(text)) {
      if (window.Toast) Toast.info('No research yet', 'Run a deep dive first, then build an agent from it.');
      return;
    }
    var topic = _topic();
    st = { phase: 0, topic: topic, text: text, name: _slug(topic) + '-agent', role: 'reasoning', draft: null, agentId: null };
    var b = document.getElementById('rc-backdrop'); if (b) b.classList.add('open');
    render();
  }
  function close() { var b = document.getElementById('rc-backdrop'); if (b) b.classList.remove('open'); }

  function _phasesHtml() {
    return PHASES.map(function (p, i) {
      var conn = i > 0 ? '<span class="encl-wconn" aria-hidden="true"></span>' : '';
      var c = i < st.phase ? 'done' : (i === st.phase ? 'on' : '');
      return conn + '<span class="encl-wstep ' + c + '"><span class="n">' + (i < st.phase ? '✓' : (i + 1)) + '</span>' + p + '</span>';
    }).join('');
  }
  function _chips() {
    var sc = window.SeedChip; if (!sc) return '';
    return '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:10px 0">' +
      sc.html({ k: 'topic', v: st.topic || '—', tone: 'accent' }) +
      sc.html({ k: 'role', v: st.role, tone: 'emerald' }) +
      sc.html({ k: 'context', v: Math.round(st.text.length / 1000) + 'k chars', tone: 'info' }) +
      '</div>';
  }

  function render() {
    var ph = document.getElementById('rc-phases'); if (!ph) return;
    ph.innerHTML = _phasesHtml();
    var body = document.getElementById('rc-body'), acts = document.getElementById('rc-actions');
    if (st.phase === 0) {
      body.innerHTML = '<p style="color:var(--text-dim);font-size:var(--text-sm,0.8rem);margin:0 0 8px">This research becomes the agent’s pinned context — every object is born in a conversation.</p>' +
        _chips() + '<div class="rc-preview">' + _esc(st.text.slice(0, 600)) + '…</div>';
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="ResearchFlow.close()">Cancel</button><button type="button" class="action-btn accent" onclick="ResearchFlow.next()">Name the context →</button>';
    } else if (st.phase === 1) {
      body.innerHTML = '<div class="rc-field"><label>Context bundle name</label><input type="text" id="rc-name" value="' + _esc(st.name) + '"></div>' +
        '<div class="rc-field"><label>Agent role</label><select id="rc-role">' +
        ['reasoning', 'coding', 'fast', 'general', 'uncensored'].map(function (r) { return '<option' + (r === st.role ? ' selected' : '') + '>' + r + '</option>'; }).join('') +
        '</select></div>' + _chips();
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="ResearchFlow.back()">← Back</button><button type="button" class="action-btn accent" onclick="ResearchFlow.next()">Generate agent →</button>';
    } else if (st.phase === 2) {
      if (!st.draft) {
        body.innerHTML = '<div class="rc-loading">Distilling the research into an agent…</div>';
        acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="ResearchFlow.close()">Cancel</button>';
        _generate();
      } else {
        body.innerHTML = '<div class="rc-field"><label>Agent name</label><input type="text" id="rc-agent-name" value="' + _esc(st.draft.name || st.name) + '"></div>' +
          '<div class="rc-field"><label>System prompt — distilled from the research, edit freely</label><textarea id="rc-prompt" rows="8">' + _esc(st.draft.system_prompt || st.draft.prompt || '') + '</textarea></div>' +
          '<div style="font-family:var(--mono);font-size:var(--text-2xs,0.6rem);color:var(--text-faint)">model ' + _esc(st.draft.model || 'auto') + ' · role ' + _esc(st.draft.role || st.role) + ' · research pinned as context</div>';
        acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="ResearchFlow.back()">← Back</button><button type="button" class="action-btn accent" onclick="ResearchFlow.save()">Save agent →</button>';
      }
    } else {
      body.innerHTML = '<div style="font-family:var(--mono);color:var(--accent);font-size:var(--text-sm,0.8rem)">✓ ' + _esc((st.draft && st.draft.name) || st.name) + ' created from research</div>' +
        '<p style="color:var(--text-dim);font-size:var(--text-xs,0.7rem);margin-top:8px">Verify it the honest way — start a conversation.</p>';
      acts.innerHTML = '<button type="button" class="action-btn ghost" onclick="ResearchFlow.close()">Done</button><button type="button" class="action-btn accent" onclick="ResearchFlow.verify()">Seed a chat with it →</button>';
    }
  }

  function next() {
    if (st.phase === 1) {
      var n = document.getElementById('rc-name'); if (n && n.value.trim()) st.name = n.value.trim();
      var r = document.getElementById('rc-role'); if (r) st.role = r.value;
    }
    st.phase = Math.min(3, st.phase + 1); render();
  }
  function back() { if (st.phase === 2) st.draft = null; st.phase = Math.max(0, st.phase - 1); render(); }

  function _generate() {
    fetch('/api/agents/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: st.text, name_hint: st.name, role_hint: st.role, include_source_as_context: true }),
    }).then(function (r) { return r.json(); })
      .then(function (d) { st.draft = d || {}; render(); })
      .catch(function (e) { var body = document.getElementById('rc-body'); if (body) body.innerHTML = '<div class="rc-loading" style="color:var(--danger)">Generation failed: ' + _esc(String(e)) + '</div>'; });
  }
  function save() {
    if (!st.draft) return;
    var n = document.getElementById('rc-agent-name'); if (n && n.value.trim()) st.draft.name = n.value.trim();
    var p = document.getElementById('rc-prompt'); if (p) { st.draft.system_prompt = p.value; st.draft.prompt = p.value; }
    fetch('/api/agents/generate/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft: st.draft, overwrite: false }),
    }).then(function (r) { return r.json(); })
      .then(function (d) { st.agentId = (d && d.agent_id) || (st.draft && st.draft.id); st.phase = 3; render(); if (window.Toast) Toast.success('Agent saved', st.draft.name || st.name); })
      .catch(function (e) { if (window.Toast) Toast.danger('Save failed', String(e)); });
  }
  function verify() {
    var id = st.agentId; close();
    if (id && window.AssetPeek) AssetPeek.seedChat(null, id);
    else if (window.Toast) Toast.info('Saved', 'Find the agent in the Agents library.');
  }

  document.addEventListener('click', function (e) { var b = document.getElementById('rc-backdrop'); if (b && e.target === b) b.classList.remove('open'); });
  window.ResearchFlow = { open: open, close: close, next: next, back: back, save: save, verify: verify };
})();


// ── phase-2 legacy-bridge surface (auto-generated) ──
export {
  AgentGen,
  ComposerSplit,
  Projects,
  WorkflowIndex,
  _agentCtxAdd,
  _agentCtxRemove,
  _agentCtxRender,
  _agentCtxSync,
  _agentHistory,
  _agentModalHtml,
  _applyGraphForces,
  _archKvRow,
  _capCard,
  _detailChipsFor,
  _detailMetaFor,
  _dfToggleStopBtn,
  _loadGraphConfig,
  _persistAgentChat,
  _refreshProjectsCount,
  _renderActiveChatPill,
  _renderAgentContextPicker,
  _renderAgentToolsPicker,
  _renderArchError,
  _renderArchPressure,
  _renderExternalProviderShell,
  _renderGraphConfigPanel,
  _renderGraphLegendToggles,
  _renderPreWarmSummary,
  _renderResearchInFlight,
  _restoreAgentChat,
  _saveAgentModal,
  _saveGraphConfig,
  _sendStepMessage,
  _setStripModelCount,
  _stepGraphZoom,
  _stopArchPressurePoll,
  _syncAgentTools,
  _uploadDocumentFile,
  addFact,
  applyRoleAsSystemPrompt,
  chatHistory,
  cleanupStaleSessions,
  clearGraphSelection,
  clearSystemPrompt,
  closeAgentChat,
  closeSession,
  composerClearWithConfirm,
  composerEnterStepEngage,
  composerExitStepEngage,
  composerExportBundle,
  composerLoadById,
  composerLoadByIdAndSwitch,
  composerLoadDefinition,
  composerLoadFromIndex,
  composerNewWorkflow,
  composerSeedAgent,
  composerSwitchBench,
  composerTestStepInChat,
  copyA2ACardUrl,
  deepDiveFromNode,
  deepDiveFromSession,
  deleteAgent,
  deleteDocument,
  deleteFact,
  deleteSession,
  dfAddAnchors,
  dfAddCompanionSkill,
  dfAddCompanionTool,
  dfAddGate,
  dfAddNodeFromAgent,
  dfAddNodeFromImportedStep,
  dfAddNodeFromTemplate,
  dfAddOutput,
  dfAddSkill,
  dfAddTool,
  dfAutoChain,
  dfAutoLayout,
  dfClearConfigPanel,
  dfDeleteNode,
  dfDetachSkill,
  dfDetachTool,
  dfDoImport,
  dfEditor,
  dfExportYaml,
  dfFetchCompanions,
  dfFindNodeIdForStep,
  dfImportBundle,
  dfImportYaml,
  dfInitEditor,
  dfInitPalette,
  dfNextId,
  dfNodeData,
  dfNodeHtml,
  dfOnConnectionCreated,
  dfOnConnectionRemoved,
  dfRefreshAnchors,
  dfRemoveGate,
  dfRemoveOutput,
  dfRemoveSkill,
  dfRemoveTool,
  dfRenderConfigPanel,
  dfRunWorkflow,
  dfRunWorkflowFromComposer,
  dfRunWorkflowLive,
  dfSave,
  dfScheduleAnchorRefresh,
  dfToggleFullscreen,
  dfUpdateDecisionBranch,
  dfUpdateGate,
  dfUpdateNodeData,
  dfZoomIn,
  dfZoomOut,
  dfZoomReset,
  editFact,
  enclGaugeStat,
  enclSparkline,
  enclStatRange,
  enclTrendStat,
  enclUtilChart,
  esc,
  exportResearch,
  exportSession,
  filterCatalog,
  generateFilename,
  generateSessionMarkdown,
  getSystemPromptMessage,
  graphData,
  graphSim,
  hideTooltip,
  highlightNeighborhood,
  initResearch,
  isEmbeddingOnlyModel,
  loadA2ACard,
  loadActiveSessions,
  loadAgentsForSelector,
  loadAgentsTab,
  loadArchInfo,
  loadArchitecturePanel,
  loadCatalog,
  loadCatalogPage,
  loadDiscovery,
  loadDocStats,
  loadDocumentsList,
  loadDocumentsTab,
  loadExternalDiscover,
  loadFacts,
  loadGraphData,
  loadInjectionPreview,
  loadInstalledLocal,
  loadMcpsDiscover,
  loadMemory,
  loadMemoryStats,
  loadMemoryTab,
  loadModels,
  loadPluginsDiscover,
  loadProfiles,
  loadRecentRuns,
  loadRoles,
  loadSearchSettings,
  loadSessionIntoChat,
  loadSessions,
  loadStatus,
  loadSystemPrompt,
  loadWorkbenches,
  loadWorkflowDetail,
  loadWorkflowsTab,
  markSettingsDirty,
  moveTooltip,
  onAgentSelectionChanged,
  onChatModelChanged,
  openAgentChat,
  openAgentChatWithStarter,
  openModelDetail,
  openWorkflowInComposer,
  populateResModelSelect,
  populateSystemPromptRoles,
  previewRole,
  pullModel,
  rebuildGraph,
  refreshArchitectureDetection,
  refreshDiscovery,
  refreshWorkflows,
  reindexDocument,
  reloadProfiles,
  removeLocalModel,
  removeModel,
  renderAgentsWorkbench,
  renderCatalog,
  renderCitations,
  renderContextInspector,
  renderDiscovery,
  renderGraph,
  renderMarkdownBasic,
  renderMcpsWorkbench,
  renderPluginsWorkbench,
  renderProvenanceRail,
  renderResearchResults,
  renderRunsPerfBand,
  renderSkillsWorkbench,
  renderSources,
  renderStepBox,
  renderWorkbenchAuthHint,
  renderWorkbenchError,
  renderWorkflowDag,
  renderWorkflowIndex,
  resetGraphZoom,
  resumeRun,
  reviewModel,
  runDeepDive,
  runWorkflow,
  saveSearchSettings,
  saveSystemPrompt,
  searchDocuments,
  searchMemory,
  selectNode,
  selectNodeById,
  sendAgentMessage,
  sendMessage,
  setDiscFilter,
  setFilter,
  setGauge,
  setWfMode,
  showCreateAgentModal,
  showEditAgentModal,
  showTooltip,
  switchTab,
  tagClass,
  testModel,
  toggleA2ASkills,
  toggleAgentDock,
  toggleComposerWorkstream,
  toggleFact,
  toggleLoadedModelsPopover,
  toggleSearch,
  toggleSessionDetail,
  toggleSettings,
  toggleSystemPrompt,
  unloadModel,
  updateClock,
  updateExportBtn,
  updateResCount,
  updateSeedPlaceholder,
  updateSystemPromptStatus,
  uploadDocument,
  viewRun,
};
