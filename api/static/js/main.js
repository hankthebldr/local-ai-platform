// Enclave UI — module entry (phase-2 U1 flip).
// The former inline monolith <script> (index.html 2420-18154) + the 7
// component <script id=enclave-*-js> blocks, concatenated VERBATIM into one
// module. Vendored libs stay classic-defer globals; alias them into module
// scope so the moved code's bare references keep resolving.
const { Drawflow, d3, dagre, jsyaml } = window;

// core/ modules (phase-2 U2 carve). Imported for module scope so the bare
// esc()/renderMarkdown()/renderMarkdownBasic() call-sites keep resolving; still
// window-bridged via shell/legacy-bridge.js (esc, renderMarkdownBasic) below.
import { esc, escAttr, safeUrl, renderMarkdown, renderMarkdownBasic } from './core/dom.js';
import { enclSparkline, enclTrendStat, enclUtilChart, enclGaugeStat, enclStatRange } from './core/charts.js';
import { Net } from './core/net.js';
import { Theme } from './core/theme.js';
import { Toast, Confirm, EmptyState, ErrorPanel, Skeleton } from './core/ui.js';
import { Shortcuts } from './core/shortcuts.js';
import { Heartbeat } from './core/heartbeat.js';
import { Actions } from './shell/actions.js';
import { NextActions } from './shell/next-actions.js';
import { initRouter } from './shell/router.js';
import { AssetPeek } from './library/asset-peek.js';
import { SkillsPanel } from './library/skills.js';
import { PluginsPanel } from './library/plugins.js';
import { Kanban } from './library/kanban.js';
import { WorkflowIndex } from './library/workflow-index.js';
import { AgentGen, AgentsPanel } from './library/agents.js';
import { CatalogPage, CatalogModelsShare } from './library/models.js';
import { ModelsPanel } from './library/models-panel.js';
import { LibraryShell } from './library/shell.js';
import { LibraryWizard } from './library/wizard.js';
import { MCPPanel } from './library/mcp.js';
import { PromptsLibrary } from './library/prompts.js';
import { TasksPanel } from './library/tasks.js';
import { PatternsPanel } from './library/patterns.js';
import { TestPane } from './library/test-pane.js';
import { RunsTab } from './runs/runs-tab.js';
import { WorkflowMemory } from './runs/workflow-memory.js';
import { ResearchArtifacts } from './runs/research-artifacts.js';
// RX-2 — the canonical shared node-rail (this spec owns it; Operate U14
// consumes) + the research consumers registered into it. Side-effect imports:
// each self-wires its data-actions and (for the rail) registers its kind.
import { ContextNodeRail } from './shell/context-node-rail.js';
import { ResearchNodeRail } from './research/research-node-rail.js';
import { ResearchStore } from './research/research-store.js';
import { AdminMenu } from './admin/menu.js';
import { AdminAuth } from './admin/auth.js';
import { ApiKeysPanel } from './admin/api-keys.js';
import { CloudPanel } from './admin/cloud.js';
// Side-effect import (LB0-U2): SourcesPanel wires itself via Actions
// data-actions + the adminPanelActivated listener — no window global,
// no inline handlers, so no bridge assign below.
import './admin/sources.js';
import { ExportsPanel } from './admin/exports.js';
import { ComposerWorkstream } from './workspace-legacy/composer-workstream.js';
import { AgentTuning } from './workspace-legacy/agent-tuning.js';
import { ChatRating } from './workspace-legacy/chat-rating.js';
import { ComposerSplit } from './workspace-legacy/composer-split.js';
import { BootSequence } from './workspace-legacy/boot-sequence.js';
import { ComposerView } from './workspace-legacy/composer-view.js';
import { ChatView } from './workspace-legacy/chat-view.js';
import { ContextView } from './runs/context-view.js';
import { DfSeedSchema } from './workspace-legacy/df-seed-schema.js';
import { Projects } from './shell/projects.js';
import { SkillsBuilder, WorkflowBuilder } from './library/builders.js';
import { ExtDiscover, SkillsDiscover } from './library/discover.js';
// LB3-U2 — ONE skills normalizer feeds both the Library shell and the
// Composer Skills bench; the drag payload constants live there too.
import { flattenSkills, skillKey, SKILL_DRAG_MIME } from './library/skills-data.js';
// Preserve early window availability (these were direct window.* assigns).
window.renderMarkdown = renderMarkdown;
window.SkillsBuilder = SkillsBuilder;
window.WorkflowBuilder = WorkflowBuilder;
window.ExtDiscover = ExtDiscover;
window.SkillsDiscover = SkillsDiscover;
window.DfSeedSchema = DfSeedSchema;
window.ComposerWorkstream = ComposerWorkstream;
window.AgentTuning = AgentTuning;
window.ChatRating = ChatRating;
window.BootSequence = BootSequence;
window.RunsTab = RunsTab;
window.WorkflowMemory = WorkflowMemory;
window.ResearchArtifacts = ResearchArtifacts;
window.Actions = Actions;
window.AssetPeek = AssetPeek;
window.CatalogPage = CatalogPage;
window.CatalogModelsShare = CatalogModelsShare;
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
window.AdminMenu = AdminMenu;
window.AdminAuth = AdminAuth;
window.ApiKeysPanel = ApiKeysPanel;
window.CloudPanel = CloudPanel;
window.ExportsPanel = ExportsPanel;


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
  // Legacy 'documents' routes (the retired Context tab: old links,
  // #/documents deep links, the g-c shortcut) land on Research — the
  // RAG + deep-research + Role-Library surface was promoted into
  // #tab-research (S3). Same pre-lookup remap pattern as 'discover'.
  if (name === 'documents') name = 'research';
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
  if (name === 'chat') ChatView.init();
  // Workflow Index no longer needs to refresh Kanban — the panel
  // moved to the Projects tab. Keep WorkflowIndex.load on its own.
  if (name === 'workflow-index') { WorkflowIndex.load(); }
  // Prompts library (roles + templates CRUD + render). Refresh on every
  // visit since prompts/{roles,templates}/ may have changed on disk.
  if (name === 'prompts' && window.PromptsLibrary) { PromptsLibrary.load(); }
  // Tasks library (LB6) — agentic task schemas on the shell. Mount once,
  // reload after; the discovery read serves the persisted digest only.
  // Imported binding (no window global) — same posture as ModelsPanel.
  if (name === 'tasks') { try { TasksPanel.activate(); } catch (_) {} }
  // Patterns library (PT-1) — pattern presets on the shell. Mount once, reload
  // after. Imported binding (no window global), same posture as TasksPanel.
  if (name === 'patterns') { try { PatternsPanel.activate(); } catch (_) {} }
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
    // Park the shared legacy inventory DOM back in the hidden holder
    // (LB4-U2/F2) so the Catalog-page relocation keeps working while
    // #models-shell stays the single visible models surface. The shell's
    // own /api/inventory/catalog read (ModelsPanel.activate) is this tab's
    // ONE inventory fetch — loadCatalog now runs only for the Catalog page.
    if (window.CatalogModelsShare) CatalogModelsShare.showInModelsTab();
    ModelsPanel.activate();
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
  // (Legacy 'discover' + 'documents' redirects now live at the top of
  // this function — they have to run before the panel lookup to work.)
  // Research (S3): the promoted Build tab hosts the knowledge graph +
  // deep research + the RAG document surface + the Role Library. The
  // 'documents' remap above funnels every legacy Context entry here.
  if (name === 'research') {
    initResearch();
    // Role Library (C14) — statically authored in #tab-research; keep
    // it fresh on every visit since prompts/roles/ may have changed.
    if (typeof loadRoles === 'function') {
      try { loadRoles(); } catch (_) {}
    }
    // RAG documents list + stats (moved from the retired Context tab).
    if (typeof loadDocumentsTab === 'function') {
      try { loadDocumentsTab(); } catch (_) {}
    }
  }
  // Context (S4): run/provenance observability under Operate — the
  // run-filtered view of the one /api/graph build + the /api/context
  // session store. ContextView keeps its OWN load flag, so the
  // researchLoaded single-shot guard can't starve this pane (R3).
  if (name === 'context') ContextView.init();
  if (name === 'workflows') {
    // Legacy loader still runs (writes to the hidden mounts under
    // the Catalog page so refreshWorkflows + loadWorkflowDetail
    // don't NPE). The Catalog counts loader is what actually
    // populates the visible surface.
    if (typeof loadWorkflowsTab === 'function') { try { loadWorkflowsTab(); } catch (_) {} }
    if (typeof loadCatalogPage === 'function') { try { loadCatalogPage(); } catch (_) {} }
  }
  if (name === 'agents') loadAgentsTab();

  // Promoted admin panels (Plugins / Skills / MCP / Cloud / Exports) were
  // moved out of the dropdown but still register their data-load handlers
  // on the `adminPanelActivated` event. Re-emit that event from switchTab
  // so first-class top-level entry to those tabs triggers the same load
  // path the dropdown route used to fire.
  // Standalone Skills tab — the LibraryShell adapter's own Discovered
  // side-tab now OWNS discovery on this tab (its load() reads
  // /api/skills/discover). The legacy relocate-in + SkillsDiscover.load()
  // was a SECOND discovery surface stacked above the shell list — the
  // double-discovery MS-4 collapses. We deliberately no longer relocate the
  // panel here; #skills-tab-discover-mount stays in the DOM (only-add) but
  // empty on admin-skills. Catalog's showInCatalog() relocation is untouched
  // (the Catalog page has no shell), so that discovery home is unchanged.
  if (name === 'admin-plugins' || name === 'admin-skills' || name === 'admin-mcp'
      || name === 'admin-cloud' || name === 'admin-exports' || name === 'admin-keys'
      || name === 'admin-sources') {
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

// data-action nav (S0+): new tab buttons carry data-action="switch-tab"
// + data-tab-target instead of inline onclick. Registered ONCE here —
// future phases add buttons, not handlers.
Actions.click({ 'switch-tab': (el) => switchTab(el.dataset.tabTarget || el.dataset.tab, el) });

// CP-1b: no-models onboarding banner. Shown when the /v1/models read comes
// back empty; hidden the moment a model loads. Operator-dismissible for the
// session (sessionStorage) so it doesn't nag mid-work, but re-appears next
// boot until a model is actually pulled.
function syncNoModelsBanner(hasModels) {
  const b = document.getElementById('no-models-banner');
  if (!b) return;
  let dismissed = false;
  try { dismissed = sessionStorage.getItem('enclave.noModelsDismissed') === '1'; } catch (_) {}
  b.hidden = hasModels || dismissed;
}
window.syncNoModelsBanner = syncNoModelsBanner;

// CP-1b: the empty-canvas overlay carries a 3-step first-run checklist. It's
// only visible while the canvas has no real steps, so step 2 (add steps) and
// step 3 (run) are always "todo" in that window — but step 1 (start a chat /
// pin a reply) is a real signal we CAN reflect live, so a returning operator
// sees "you've already started". Called from ComposerView.updateCanvasEmptyState.
function renderComposerEmptyChecklist() {
  const ol = document.getElementById('composer-empty-checklist');
  if (!ol) return;
  let started = false;
  try {
    started = (typeof chatHistory !== 'undefined' && chatHistory && chatHistory.length > 0)
      || ((window._enclavePins || []).length > 0);
  } catch (_) {}
  const li1 = ol.querySelector('li[data-step="1"]');
  if (li1) {
    li1.classList.toggle('done', started);
    const mark = li1.querySelector('.cec-mark');
    if (mark) mark.textContent = started ? '✓' : '○';
  }
}
window.renderComposerEmptyChecklist = renderComposerEmptyChecklist;
Actions.click({ 'banner.dismiss-no-models': () => {
  try { sessionStorage.setItem('enclave.noModelsDismissed', '1'); } catch (_) {}
  const b = document.getElementById('no-models-banner');
  if (b) b.hidden = true;
} });

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
    // S1: the Promote (.bs-dispatch) / Pin (.msg-pin-btn) affordances moved
    // to #tab-chat with the dock, so the disable class must land on the
    // dock too — the .composer-split scope alone no longer reaches them.
    const _dock = document.getElementById('agent-chat-dock');
    if (_dock) _dock.classList.toggle('ollama-down', _ollamaDown);

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

    // The /v1/models fetch has completed and parsed (empty OR populated).
    // The zero-model run preflight keys off this so it only blocks a run
    // when we've CONFIRMED there are no chat models — not during the async
    // gap before this first fetch resolves (which would false-block a run
    // kicked off immediately after boot).
    window._modelsFetched = true;

    if (models.length === 0) {
      container.innerHTML = '<div class="model-empty">No models. Run: ollama pull dolphin3</div>';
      try { syncNoModelsBanner(false); } catch (_) {}  // CP-1b
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
    try { syncNoModelsBanner(chatModels.length > 0); } catch (_) {}  // CP-1b
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
          return `<a class="citation" href="${safeUrl(sources[idx].url)}" target="_blank" rel="noopener" title="${escAttr(sources[idx].title)}">[${num}]</a>`;
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
      <a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></span>
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

/* ── S2 CHAT LAUNCH CONFIG (Config Header + pivots) ─────────────────
   The Chat tab is the LAUNCHPAD: the Config Header above #messages
   composes a launch state — agent · model · role→system prompt ·
   web-search (all pre-existing controls, moved) plus net-new
   tools/skills, MCP, and context-document selections — and the pivots
   carry that composed state into the supporting workflows:

     Save as agent      → POST /api/agents           (agent library)
     → Composer step    → dfAddNodeFromAgent append  (canvas, no wipe)
     → Research         → POST /api/feedback/artifacts

   Strictly additive: sendMessage() and the frozen engine are untouched;
   the selections only influence the pivots (e.g. Save-as-agent persists
   them onto the AgentDefinition as tools/context sources). Module-scoped
   (no new window global); all wiring is data-action delegation. */
const ChatLaunch = (function () {
  const state = { tools: [], mcp: [], context: [] };  // selected rows per kind
  const cache = {};                                    // kind → fetched payload
  let openKind = null;

  const KINDS = {
    tools: {
      label: 'Plugin tools & skills',
      url: '/api/plugins',
      empty: 'No plugin tools discovered — install plugins from the Library.',
      rows(data) {
        const plugins = Array.isArray(data) ? data : ((data && data.plugins) || []);
        const out = [];
        for (const p of plugins) {
          for (const t of (p.tools || [])) {
            out.push({
              key: p.id + '::' + t.id,
              name: (p.name || p.id) + ' · ' + (t.name || t.id),
              meta: t.description || '',
              ref: { plugin_id: p.id, tool_id: t.id },
            });
          }
        }
        return out;
      },
    },
    mcp: {
      label: 'MCP servers',
      url: '/api/mcp/servers',
      empty: 'No MCP servers registered — add one under Library › MCP.',
      rows(data) {
        const servers = Array.isArray(data) ? data : ((data && data.servers) || []);
        return servers.map(s => ({
          key: s.id,
          name: s.name || s.id,
          meta: s.description || s.transport || '',
          ref: { mcp_server: s.id, tool_id: '*' },
        }));
      },
    },
    context: {
      label: 'Context documents',
      url: '/api/documents',
      empty: 'No documents ingested yet — upload under Context.',
      rows(data) {
        const docs = Array.isArray(data) ? data : ((data && data.documents) || []);
        return docs.map(d => ({
          key: d.id,
          name: d.filename || d.id,
          meta: d.status || '',
          ref: { doc_id: d.id, filename: d.filename || d.id },
        }));
      },
    },
  };

  function _pop() { return document.getElementById('chat-picker-pop'); }

  async function openPicker(kind) {
    const pop = _pop();
    if (!pop || !KINDS[kind]) return;
    if (openKind === kind && !pop.hidden) { close(); return; }  // second click toggles
    openKind = kind;
    pop.hidden = false;
    pop.innerHTML = '<div class="ccfg-pop-empty">loading…</div>';
    let rows;
    try {
      if (!cache[kind]) cache[kind] = await Net.getJson(KINDS[kind].url, { silent: true });
      rows = KINDS[kind].rows(cache[kind]);
    } catch (e) {
      pop.innerHTML = `<div class="ccfg-pop-empty" style="color:var(--red)">Failed to load: ${esc(e.message)}</div>`;
      return;
    }
    const selected = new Set(state[kind].map(r => r.key));
    const body = rows.length
      ? rows.map(r => `
        <label class="ccfg-pop-row">
          <input type="checkbox" data-action="chat.picker-item" data-kind="${esc(kind)}" data-key="${esc(r.key)}"${selected.has(r.key) ? ' checked' : ''}>
          <span class="ccfg-pop-name">${esc(r.name)}</span>
          ${r.meta ? `<span class="ccfg-pop-meta">${esc(r.meta)}</span>` : ''}
        </label>`).join('')
      : `<div class="ccfg-pop-empty">${esc(KINDS[kind].empty)}</div>`;
    pop.innerHTML = `
      <div class="ccfg-pop-head">
        <span>${esc(KINDS[kind].label)}</span>
        <button type="button" class="strip-models-pop-close" data-action="chat.picker-close" aria-label="Close">&times;</button>
      </div>
      <div class="ccfg-pop-body">${body}</div>`;
  }

  function toggleItem(el) {
    const kind = el.dataset.kind;
    const key = el.dataset.key;
    if (!KINDS[kind]) return;
    const rows = KINDS[kind].rows(cache[kind] || []);
    const row = rows.find(r => r.key === key);
    const kept = state[kind].filter(r => r.key !== key);
    if (el.checked && row) kept.push(row);
    state[kind] = kept;
    updateCounts();
  }

  function updateCounts() {
    for (const kind of Object.keys(KINDS)) {
      const n = state[kind].length;
      const badge = document.getElementById('chat-count-' + kind);
      if (badge) badge.textContent = n ? String(n) : '';
      const btn = document.getElementById('chat-pick-' + kind);
      if (btn) btn.classList.toggle('has-sel', n > 0);
    }
  }

  function close() {
    const pop = _pop();
    if (pop) { pop.hidden = true; pop.innerHTML = ''; }
    openKind = null;
  }

  function selections() {
    return { tools: state.tools.slice(), mcp: state.mcp.slice(), context: state.context.slice() };
  }

  return { openPicker, toggleItem, close, selections };
})();

// Pivot 1 — persist the composed launch state as a reusable agent.
// Web-search / plugin-tool / MCP selections land as AgentTool entries;
// context-document selections land as ContextSource entries. Returns the
// new agent id (null on cancel/failure) so chatSendToComposer can chain.
async function chatSaveAsAgent() {
  const name = window.prompt('Save this chat config as an agent — name:', '');
  if (name == null || !name.trim()) return null;
  const id = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (!id) { Toast.warn('Invalid name', 'Use letters or digits.'); return null; }
  const modelSel = document.getElementById('model-select');
  const model = (modelSel && modelSel.value && modelSel.value !== 'loading…') ? modelSel.value : null;
  const sysTa = document.getElementById('system-prompt');
  const system_prompt = (sysTa && sysTa.value.trim()) || `You are ${name.trim()}.`;
  const sel = ChatLaunch.selections();
  const tools = [];
  if (webSearchEnabled) tools.push({ type: 'web_search' });
  for (const t of sel.tools) tools.push({ plugin_id: t.ref.plugin_id, tool_id: t.ref.tool_id });
  for (const s of sel.mcp) tools.push({ mcp_server: s.ref.mcp_server, tool_id: s.ref.tool_id || '*' });
  const context = sel.context.map(d => ({
    type: 'text',
    value: `Grounding document (RAG store): "${d.ref.filename}" — document id ${d.ref.doc_id}. `
         + `Full content retrievable via GET /api/documents/${d.ref.doc_id}.`,
    label: d.ref.filename,
  }));
  const defn = {
    id,
    name: name.trim(),
    description: 'Saved from the Chat launchpad',
    model,
    system_prompt,
    tools,
    context,
    tags: ['chat-launchpad'],
  };
  let r = await Net.call('/api/agents', {
    retries: 0,
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(defn),
    },
  });
  // GP-2 commit 5: an id collision (409) previously dead-ended as "Save failed".
  // Offer to update the existing agent in place via PUT — the operator asked to
  // save this config under a name that's already taken, and overwriting is the
  // obvious intent once confirmed.
  if (r.status === 409) {
    const overwrite = await Confirm.ask({
      title: 'Agent exists',
      body: `An agent "${id}" already exists. Update it with this chat config?`,
      okLabel: 'Update',
    });
    if (!overwrite) return null;
    r = await Net.call(`/api/agents/${encodeURIComponent(id)}`, {
      retries: 0,
      init: {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(defn),
      },
    });
  }
  if (!r.ok) {
    const detail = (r.data && (r.data.detail || (r.data.error && r.data.error.message))) || `HTTP ${r.status}`;
    Toast.danger('Save failed', String(detail));
    return null;
  }
  Toast.success('Agent saved', id);
  // Refresh the selector and scope the chat to the new agent so the
  // launchpad state visibly becomes the active persona.
  try { await loadAgentsForSelector(); } catch (_) {}
  const agentSel = document.getElementById('agent-select');
  if (agentSel) {
    agentSel.value = id;
    if (agentSel.value === id) onAgentSelectionChanged();
  }
  return id;
}

// Pivot 2 — append this agent onto the Composer canvas as a step.
// composerAddAgentAtCenter switches to the Composer tab itself and
// APPENDS via dfAutoChain — it never clears the canvas, so an
// in-progress DAG survives the pivot. An unsaved config becomes an
// agent first (launchpad flow), then lands as a step.
async function chatSendToComposer() {
  const agentSel = document.getElementById('agent-select');
  let agentId = agentSel ? agentSel.value : '';
  if (!agentId) {
    Toast.info('No agent selected', 'Saving the current config as an agent first…');
    agentId = await chatSaveAsAgent();
    if (!agentId) return;
  }
  await composerAddAgentAtCenter(agentId);
}

// Pivot 3 — capture the latest exchange as a durable Research artifact
// (POST /api/feedback/artifacts; server best-effort ingests into RAG).
async function chatSendToResearch() {
  let lastAssistant = null;
  let lastUser = null;
  for (let i = chatMetadata.length - 1; i >= 0; i--) {
    const m = chatMetadata[i];
    if (!lastAssistant && m.role === 'assistant') { lastAssistant = m; continue; }
    if (lastAssistant && m.role === 'user') { lastUser = m; break; }
  }
  if (!lastAssistant) {
    Toast.info('Nothing to capture', 'Get an assistant reply first — the latest answer is what pivots to Research.');
    return;
  }
  const title = String((lastUser && lastUser.content) || lastAssistant.content).slice(0, 120);
  const payload = {
    source: 'chat',
    title,
    body: lastAssistant.content,
    tags: ['chat', 'launchpad'],
    context: {
      agent: window._chatAgent || null,
      model: lastAssistant.model || null,
      web_search: !!lastAssistant.web_search,
    },
  };
  const r = await Net.call('/api/feedback/artifacts', {
    retries: 0,
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  });
  if (!r.ok) { Toast.danger('Capture failed', `HTTP ${r.status}`); return; }
  const art = (r.data && typeof r.data === 'object') ? r.data : {};
  Toast.success('Sent to Research', `Artifact ${art.id || 'saved'}${art.rag_ingested ? ' · RAG-ingested' : ''}`);
}

// Config-header wiring — registered ONCE, data-action delegation only.
Actions.click({
  'chat.pick-tools': () => ChatLaunch.openPicker('tools'),
  'chat.pick-mcp': () => ChatLaunch.openPicker('mcp'),
  'chat.pick-context': () => ChatLaunch.openPicker('context'),
  'chat.picker-close': () => ChatLaunch.close(),
  'chat.save-agent': () => { chatSaveAsAgent(); },
  'chat.to-composer': () => { chatSendToComposer(); },
  'chat.to-research': () => { chatSendToResearch(); },
});
Actions.change({ 'chat.picker-item': el => ChatLaunch.toggleItem(el) });

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
          // LB1-U2 — the UI finally sends explicit sampling params. Node
          // overrides win; the fallbacks mirror the server defaults so the
          // behavior of untouched nodes is unchanged.
          temperature: stepData.temperature != null ? Number(stepData.temperature) : 0.7,
          max_tokens: stepData.max_tokens != null ? Number(stepData.max_tokens) : 2048,
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

// CP-1a: the test-step endpoint (/api/workflows/test-step) only accepts a
// single llm step — a seed or a composite (parallel/loop/ralph) 400s. This
// predicate is the single source of truth for BOTH the render-time control
// guard (hide "test in chat" for un-testable kinds) and the click-time bail.
function _composerStepIsTestable(data) {
  return !!data && !data.is_seed && !(data.kind && data.kind !== 'llm');
}

// Reflect testability on the popup's "test in chat" control so the operator
// never clicks a control that will 400. Called from dfRenderConfigPanel and
// dfRenderSeedConfig on every node select.
function _composerSyncTestBtn(data) {
  const btn = document.getElementById('df-config-test-btn');
  if (btn) btn.hidden = !_composerStepIsTestable(data);
}

// Explicit "test in chat" — engage the selected step, SWITCH TO THE CHAT TAB
// (the control was a dead end from the Composer tab — the focused input was
// off-screen), AND focus the chat input so the operator can immediately type a
// message and see only this step's reply (routes to /api/workflows/test-step
// via the sendMessage step-engage branch).
function composerTestStepInChat() {
  const nodeId = (typeof dfSelectedNodeId !== 'undefined' && dfSelectedNodeId != null)
    ? dfSelectedNodeId : window._composerEngagedNodeId;
  if (nodeId == null) return;
  // Render-guarded above, but re-assert at click time: a seed/composite step
  // has no single-step test path and would 400.
  const data = (typeof dfNodeData !== 'undefined' && dfNodeData) ? dfNodeData[nodeId] : null;
  if (!_composerStepIsTestable(data)) {
    if (window.Toast) Toast.info('Not testable in chat', 'Seed and composite (parallel / loop / ralph) steps have no single-step test — run the whole workflow instead.');
    return;
  }
  composerEnterStepEngage(nodeId);
  try { if (typeof switchTab === 'function') switchTab('chat'); } catch (_) {}
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

// ── Skills Builder ───────────────────────────────────────────────────
// Authoring modal for a new skill. Posts to /api/skills/create which
// writes the markdown body to plugins/<plugin>/skills/<id>.md and
// registers it in the plugin's manifest.

// WorkflowBuilder — the New-Workflow wizard. Same modal grammar as the
// Skill / Agent creators (validated slug id + name + defaults), but instead
// of POSTing a complete record it seeds the composer's identity fields and
// drops the operator on a blank canvas to build the step DAG (a workflow
// isn't complete until it has steps; Save/Run persist it from there).

// DfSeedSchema — the START anchor's seed-input editor. Edits the global
// dfSeedSchema ([{key, description}]); on save it redraws the anchors and the
// schema persists to context.inputs via dfExportYaml.

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
      <a href="${safeUrl(p.homepage || '#')}" target="_blank" rel="noopener"
         onclick="event.stopPropagation()"
         class="ext-prov-link" title="Open the upstream homepage">↗</a>
    </summary>
    <div class="ext-prov-body" id="ext-prov-body-${esc(p.source)}">
      <div class="model-empty">Click to fetch from ${esc(p.name)}…</div>
    </div>
  </details>`;
}


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
    // Shared action ids (only-add): the legacy catalog grid keeps its
    // handlers byte-identical; buttons born inside the Models library shell
    // carry data-shell="models" and route into ModelsPanel (LB4-U2) — remove
    // there Confirm-gates + reloads the shell, pull renders the shell-side
    // progress line, test opens the LB1 TestPane model adapter.
    'models.remove':       el => {
      if (el.dataset.shell === 'models') {
        ModelsPanel.remove(el.dataset.id).then(done => { if (done) catalogLoaded = false; });
      } else removeModel(el.dataset.model);
    },
    'models.test':         el => el.dataset.shell === 'models'
                                   ? ModelsPanel.test(el.dataset.id)
                                   : testModel(el.dataset.model),
    'models.review':       el => reviewModel(el.dataset.repo),
    'models.pull':         el => {
      if (el.dataset.shell === 'models') {
        ModelsPanel.pull(el.dataset.modelId, el.dataset.model)
          .then(done => { if (done) catalogLoaded = false; });
      } else pullModel(el.dataset.model, el.dataset.modelId);
    },
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

// ── S4 graph fork (P4/G4) ──────────────────────────────────────────
// ONE /api/graph build renders TWO filtered views by node type:
//   research — the knowledge graph (session/topic/source/agent) in the
//              Research tab's #graph-svg (id preserved — runs-tab and
//              the Research chrome pin it);
//   context  — the run/provenance graph (workflow_run/response + their
//              grounding sources) in the Context tab's OWN
//              #context-graph-svg.
// Cross-type edges are assigned PER-EDGE: any edge touching a
// run/provenance node belongs to Context (its foreign endpoint rides
// along as an anchor); everything else stays in Research. Each pane
// keeps its own zoom/sim/selection state in _graphPaneState — the
// legacy window._graphState / window.graphSim / window._graphZoomBehavior
// names stay mirrored to the RESEARCH pane so the existing inline chrome
// and parity surface keep resolving unchanged.
const _GRAPH_PANES = {
  research: {
    svgId: 'graph-svg',
    detailId: 'session-detail',
    emptyMsg: 'No sessions exported yet. Export a chat to build the graph.',
  },
  context: {
    svgId: 'context-graph-svg',
    detailId: 'context-detail',
    emptyMsg: 'No workflow runs or provenance recorded yet. Run a workflow to build the run graph.',
  },
};
const _GRAPH_CONTEXT_NODE_TYPES = new Set(['workflow_run', 'response']);
// Grounding satellites (RAG chunks, web sources, skills, tools) belong to
// whichever pane owns their edges — they ride along as anchors instead of
// littering the other pane as isolated dots.
const _GRAPH_SATELLITE_NODE_TYPES = new Set(['chunk', 'skill', 'tool', 'source']);
const _graphPaneState = { research: {}, context: {} };
let _selectedGraphPane = 'research';

function graphPaneView(data, paneKey) {
  // Filter the single /api/graph dataset down to one pane's view.
  // Ownership: an edge is Context's iff either endpoint is a
  // run/provenance node; a node is in a pane if its type is one of the
  // pane's primaries OR it anchors one of the pane's owned edges.
  if (!data || !data.nodes) return data;
  const pane = paneKey || 'research';
  const wantCtx = pane === 'context';
  const typeById = new Map(data.nodes.map(n => [n.id, n.type]));
  const isCtxNode = id => _GRAPH_CONTEXT_NODE_TYPES.has(typeById.get(id));
  const keep = new Set();
  data.nodes.forEach(n => {
    if (_GRAPH_SATELLITE_NODE_TYPES.has(n.type)) return; // edge-pulled only
    if (_GRAPH_CONTEXT_NODE_TYPES.has(n.type) === wantCtx) keep.add(n.id);
  });
  const links = [];
  (data.links || []).forEach(l => {
    const s = typeof l.source === 'object' ? l.source.id : l.source;
    const t = typeof l.target === 'object' ? l.target.id : l.target;
    if ((isCtxNode(s) || isCtxNode(t)) !== wantCtx) return;
    keep.add(s); keep.add(t);
    links.push(l);
  });
  return Object.assign({}, data, {
    nodes: data.nodes.filter(n => keep.has(n.id)),
    links,
  });
}

// Re-render every pane that has painted at least once (the svg carries a
// data-rendered stamp set by renderGraph — a DOM flag, not a global).
// Config-panel / legend-toggle changes route through here so both views
// stay in sync off the one cached dataset.
function _rerenderGraphPanes() {
  if (!window.graphData) return;
  renderGraph(window.graphData);
  const ctxSvg = document.getElementById('context-graph-svg');
  if (ctxSvg && ctxSvg.dataset.rendered === '1') renderGraph(window.graphData, 'context');
}

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
    // RX-1 — keep the session reading surface alive across tab switches.
    if (window._researchSession) {
      try { renderResearchSession(window._researchSession); } catch (_) {}
    }
    return;
  }
  researchLoaded = true;
  loadGraphData();
  populateResModelSelect();
  // RX-1 — follow-up input: Enter sends, Shift+Enter newlines. Wired here
  // (not inline) to honor the no-new-inline-handlers rule.
  const fuInput = document.getElementById('research-followup-input');
  if (fuInput && !fuInput._rxBound) {
    fuInput._rxBound = true;
    fuInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitResearchFollowup();
      }
    });
  }
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
    // The dataset reaches window.graphData through the legacy bridge's
    // LIVE getter on the module binding — assigning window.graphData
    // directly here THREW (getter-only property, strict mode) and
    // killed every render since the phase-2 split. One fetch feeds
    // BOTH panes — _rerenderGraphPanes repaints the Context run-graph
    // too once it has mounted (S4 fork).
    _rerenderGraphPanes();
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

function resetGraphZoom(paneKey) {
  // No-arg call = Research (the inline chrome there passes nothing);
  // the Context chrome passes 'context' via its data-action handlers.
  const pane = _graphPaneState[paneKey || 'research'] || {};
  if (!pane.sim || !pane.zoom) return;
  const svg = d3.select('#' + _GRAPH_PANES[paneKey || 'research'].svgId);
  svg.transition().duration(400).call(
    pane.zoom.transform,
    d3.zoomIdentity
  );
}
// Manual +/- zoom — bound to explicit buttons. Mouse-wheel zoom on
// the graph is disabled (it was capturing page scroll); these are
// the only way to change zoom programmatically along with the
// reset button.
function graphZoomIn(paneKey)  { _stepGraphZoom(1.3, paneKey); }
function graphZoomOut(paneKey) { _stepGraphZoom(1 / 1.3, paneKey); }
function _stepGraphZoom(factor, paneKey) {
  const pane = _graphPaneState[paneKey || 'research'] || {};
  if (!pane.zoom) return;
  const svg = d3.select('#' + _GRAPH_PANES[paneKey || 'research'].svgId);
  svg.transition().duration(200).call(
    pane.zoom.scaleBy, factor
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
  _rerenderGraphPanes();
}
function resetGraphLinkFilter() {
  window.graphConfig.linkKinds = new Set();
  _rerenderGraphPanes();
}
function setGraphSizingMode(mode) {
  window.graphConfig.sizingMode = mode;
  _saveGraphConfig();
  _rerenderGraphPanes();
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
    _rerenderGraphPanes();
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
  const cfg = window.graphConfig;
  // Both pane simulations (S4 fork) pick up the shared force config.
  Object.keys(_graphPaneState).forEach(k => {
    const sim = _graphPaneState[k].sim;
    if (!sim) return;
    const linkF = sim.force('link');
    const chargeF = sim.force('charge');
    if (linkF)   linkF.distance(cfg.linkDistance).strength(cfg.linkStrength);
    if (chargeF) chargeF.strength(cfg.charge);
    // forceCenter doesn't have its own strength; emulate via a forceX/forceY
    // gravity term if needed. For simplicity nudge alpha so the existing
    // center force re-engages.
    sim.alpha(0.4).restart();
  });
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
  _rerenderGraphPanes();
}

window.toggleGraphConfigPanel  = toggleGraphConfigPanel;
window.setGraphConfigValue     = setGraphConfigValue;
window.resetGraphConfigDefaults = resetGraphConfigDefaults;

function renderGraph(data, paneKey) {
  // S4 fork: default pane is 'research' so every legacy call site keeps
  // rendering the knowledge view into #graph-svg unchanged; the Context
  // tab renders the run/provenance view via renderGraph(data, 'context').
  const pane = _GRAPH_PANES[paneKey] ? paneKey : 'research';
  const paneCfg = _GRAPH_PANES[pane];
  const svgEl = document.getElementById(paneCfg.svgId);
  if (!svgEl) return;
  // The stamp marks this pane as painted — _rerenderGraphPanes uses it
  // (a DOM flag, not a window global) to keep both views in sync.
  svgEl.dataset.rendered = '1';
  data = graphPaneView(data, pane);
  const W = svgEl.clientWidth || 600;
  const H = svgEl.clientHeight || 400;

  d3.select('#' + paneCfg.svgId).selectAll('*').remove();

  if (!data || !data.nodes || data.nodes.length === 0) {
    d3.select('#' + paneCfg.svgId).append('text')
      .attr('x', W / 2).attr('y', H / 2)
      .attr('text-anchor', 'middle')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('font-size', '12px')
      .attr('fill', '#556677')
      .text(paneCfg.emptyMsg);
    return;
  }

  const svg = d3.select('#' + paneCfg.svgId);
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
  // .scaleBy / .transform against it. Stored per pane so it survives
  // across renderGraph() invocations; the legacy window name mirrors
  // the research pane (existing chrome + parity surface).
  _graphPaneState[pane].zoom = zoom;
  if (pane === 'research') window._graphZoomBehavior = zoom;

  const nodeColor = (d) => {
    if (d.type === 'session')      return 'var(--cyan)';
    if (d.type === 'topic')        return 'var(--amber)';
    if (d.type === 'source')       return 'var(--purple)';
    if (d.type === 'agent')        return 'var(--accent)';
    if (d.type === 'workflow_run') return 'var(--cyan)';
    // Provenance node types (Context pane, S4 fork).
    if (d.type === 'response')     return 'var(--amber)';
    if (d.type === 'chunk')        return 'var(--purple)';
    if (d.type === 'skill')        return 'var(--accent)';
    if (d.type === 'tool')         return 'var(--accent)';
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
  // we filter the working links array. The chip legend + link-kind
  // filter are Research chrome — the Context pane carries its own
  // static legend, and its (few) provenance link kinds are never
  // silently hidden by the Research filter selection.
  if (pane === 'research') _renderGraphLegendToggles(data);

  const nodes = data.nodes.map(d => ({ ...d }));
  const links = data.links.map(d => ({ ...d }))
    .filter(l => pane !== 'research' || _linkVisible(l));

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
  _graphPaneState[pane].sim = sim;
  if (pane === 'research') {
    // The detail-expand handler reads window.graphSim to nudge the
    // force-center on viewport resize — that resolves through the
    // bridge's LIVE getter on this module binding (assigning
    // window.graphSim directly throws: getter-only, strict mode).
    graphSim = sim;
  }

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
    .on('click', (e, d) => { e.stopPropagation(); selectNode(d, pane); });

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

  // Stash live d3 selections + indexes for the click handler — per pane;
  // the legacy window name mirrors the research pane.
  const state = {
    nodeSel: node, linkSel: link, labelSel: label,
    nodeById, neighborMap, linkPairs,
  };
  _graphPaneState[pane].state = state;
  if (pane === 'research') window._graphState = state;

  // Deselect on background click
  svg.on('click', () => clearGraphSelection(pane));
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
  // Re-render the current selection so the expand state takes effect
  // (in whichever pane the selection lives — S4 fork).
  if (window.selectedNode) selectNode(window.selectedNode, _selectedGraphPane);
}
window.toggleConnGroupExpand = toggleConnGroupExpand;

function clearGraphSelection(paneKey) {
  const pane = _GRAPH_PANES[paneKey] ? paneKey : 'research';
  selectedNode = null;
  const panel = document.getElementById(_GRAPH_PANES[pane].detailId);
  if (panel) {
    panel.classList.remove('open');
    // Also drop the expand state — otherwise the panel stays large
    // and empty when the user clicks away. (Expand chrome is a
    // Research-pane feature.)
    if (pane === 'research' && panel.classList.contains('is-expanded')) {
      toggleSessionDetailExpand(false);
    }
  }
  const st = _graphPaneState[pane].state;
  if (!st) return;
  st.nodeSel.attr('fill-opacity', 0.85).attr('stroke-width', 1.5).attr('stroke-opacity', 0.4);
  st.linkSel.attr('stroke-opacity', 1);
  st.labelSel.attr('fill-opacity', 1);
}

function highlightNeighborhood(d, paneKey) {
  const st = _graphPaneState[_GRAPH_PANES[paneKey] ? paneKey : 'research'].state;
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
  } else if (d.type === 'workflow_run') {
    html += `<div class="tt-meta">Run · ${d.status || ''}${d.tokens ? ` · ${d.tokens} tok` : ''}</div>`;
  } else if (d.type === 'response') {
    html += `<div class="tt-meta">Response · ${d.model || ''}</div>`;
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

function selectNode(d, paneKey) {
  // S4 fork: each pane writes into its OWN detail panel — Research keeps
  // the session-detail-* ids; the Context pane mirrors the structure
  // under context-detail-*. No-arg calls stay Research (back-compat).
  const pane = _GRAPH_PANES[paneKey] ? paneKey : 'research';
  const did = _GRAPH_PANES[pane].detailId;
  selectedNode = d;
  window.selectedNode = d;  // expose so re-render helpers can re-call selectNode
  _selectedGraphPane = pane;
  const panel = document.getElementById(did);
  if (!panel) return;
  panel.classList.add('open');
  highlightNeighborhood(d, pane);

  // ── Kind chip + title (every node type) ────────────────────────
  const chip = document.getElementById(did + '-kind');
  if (chip) {
    chip.textContent = d.type || 'node';
    chip.className = `detail-kind-chip kind-${esc(d.type || 'node')}`;
  }
  document.getElementById(did + '-title').textContent =
    d.label || d.filename || d.id;
  document.getElementById(did + '-meta').textContent =
    _detailMetaFor(d);

  // Topics chips reused for whichever node type has list-y data:
  //   session.topics, topic siblings, source citations.
  const topicsEl = document.getElementById(did + '-topics');
  topicsEl.innerHTML = _detailChipsFor(d);

  // Preview body (only sessions have a transcript preview).
  const previewEl = document.getElementById(did + '-preview');
  if (d.type === 'session') {
    previewEl.textContent = (d.preview || '').slice(0, 300)
      .replace(/^#+[^\n]*\n?/gm, '').trim();
  } else if (d.type === 'topic') {
    previewEl.textContent = `Topic surfaces across ${d.session_count || 0} session${(d.session_count || 0) === 1 ? '' : 's'}. Click a connected node to drill in.`;
  } else if (d.type === 'source') {
    previewEl.innerHTML = d.url
      ? `<a href="${safeUrl(d.url)}" target="_blank" rel="noopener" style="color:var(--cyan);text-decoration:underline">${esc(d.url.slice(0, 80))}${d.url.length > 80 ? '…' : ''}</a>`
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
  const connEl = document.getElementById(did + '-connections');
  const st = _graphPaneState[pane].state;
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
                          data-action="graph.node-select" data-pane="${esc(pane)}"
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
  const actEl = document.getElementById(did + '-actions');
  if (actEl) {
    if (d.type === 'workflow_run' || d.type === 'response') {
      // Run/provenance nodes (Context pane): pivot to the Runs surface
      // where the full step detail + context trace live.
      actEl.innerHTML =
        `<button class="action-btn" data-action="graph.open-runs" style="font-size:0.65rem;padding:4px 10px">Open Runs</button>`;
    } else if (d.type === 'session') {
      actEl.innerHTML =
        `<button class="action-btn" data-action="graph.session-chat" style="font-size:0.65rem;padding:4px 10px">Open in Chat</button>
         <button class="action-btn" data-action="graph.session-deep-dive" style="font-size:0.65rem;padding:4px 10px;border-color:var(--amber);color:var(--amber)">Deep Dive</button>`;
    } else if (d.type === 'topic') {
      actEl.innerHTML =
        `<button class="action-btn" data-action="graph.node-deep-dive" style="font-size:0.65rem;padding:4px 10px;border-color:var(--amber);color:var(--amber)">Deep Dive on Topic</button>`;
    } else if (d.type === 'source') {
      actEl.innerHTML = d.url
        ? `<a class="action-btn" target="_blank" rel="noopener" href="${safeUrl(d.url)}" style="font-size:0.65rem;padding:4px 10px;text-decoration:none;display:inline-block">Open Source ↗</a>`
        : '';
    } else {
      actEl.innerHTML = '';
    }
  }

  // RX-2 — drive the exploratory node rail through the shared pane-guard. The
  // guard (declared once in shell/context-node-rail.js) only paints the
  // research rail for research-pane selections; a context-pane selection is
  // rejected, so a click in one surface never drives the other's rail.
  try { ContextNodeRail.activate('research-node', d, pane); } catch (_) {}
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
  if (d.type === 'workflow_run') {
    return ['Run', d.status, d.duration ? `${d.duration}s` : null,
      d.tokens ? `${d.tokens} tok` : null].filter(Boolean).join(' · ');
  }
  if (d.type === 'response') {
    return ['Response', d.model, d.edge_count ? `${d.edge_count} grounding edge${d.edge_count === 1 ? '' : 's'}` : null]
      .filter(Boolean).join(' · ');
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
// the picked neighbor so you can hop session → topic → session. Pane-
// aware (S4): rows carry data-pane so the hop stays inside its graph.
function selectNodeById(id, paneKey) {
  const pane = _GRAPH_PANES[paneKey] ? paneKey : 'research';
  const st = _graphPaneState[pane].state;
  if (!st) return;
  const target = st.nodeById.get(id);
  if (!target) return;
  selectNode(target, pane);
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
  'graph.node-select':       el => selectNodeById(el.dataset.nodeId, el.dataset.pane),
  'graph.conn-group':        el => toggleConnGroupExpand(el.dataset.kind),
  'graph.session-chat':      () => loadSessionIntoChat(),
  'graph.session-deep-dive': () => deepDiveFromSession(),
  'graph.node-deep-dive':    () => deepDiveFromNode(),
  // Context pane (S4): run/response detail pivot + the pane's own graph
  // chrome — data-action only (no inline handlers on new markup).
  'graph.open-runs':         () => switchTab('runs'),
  'ctxgraph.rebuild':        () => rebuildGraph(),
  'ctxgraph.zoom-in':        () => graphZoomIn('context'),
  'ctxgraph.zoom-out':       () => graphZoomOut('context'),
  'ctxgraph.zoom-reset':     () => resetGraphZoom('context')
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
          `<a class="res-source-chip" href="${safeUrl(s.url || '#')}" target="_blank" rel="noopener">${esc(s.title || s.url || '(untitled)').slice(0, 80)}</a>`
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
          <span class="thinking-step-actions">
            <button class="action-btn xs cyan" data-action="research.capture" data-idx="${payloadIdx}">+ Capture as artifact</button>
          </span>
        </summary>
        <div class="thinking-step-body">
          <div class="thinking-step-context">${ctxPreview ? esc(ctxPreview) + (sec.context && sec.context.length > 320 ? '…' : '') : '<em style="color:var(--text-muted)">no context gathered</em>'}</div>
          <div class="thinking-step-sources">${srcHtml}</div>
        </div>
      </details>
    `;
  }).join('');

  // RX-2 — every source is actionable: save it as a durable store note
  // (RAG-indexed) or drop a [[source:<slug>]] cite into the follow-up. Rows use
  // data-action delegation (no inline handlers); the slug is derived to match
  // the server's slug so a cite resolves to the saved note.
  const sourceRows = (data.sources || []).map(s => {
    const url = s.url || '';
    const title = s.title || url || '(untitled)';
    const slug = _researchSlug(title || url);
    return `
      <div class="research-source-row">
        <a class="res-source-chip" href="${safeUrl(url || '#')}" target="_blank" rel="noopener" title="${escAttr(title)}">${esc(title.slice(0, 80))}</a>
        <div class="lib-actions-row">
          <button class="action-btn xs" data-action="research.save-source" data-title="${escAttr(title)}" data-url="${escAttr(url)}" data-slug="${escAttr(slug)}">Save to store</button>
          <button class="action-btn xs ghost" data-action="research.cite" data-slug="${escAttr(slug)}">Cite</button>
        </div>
      </div>`;
  }).join('');

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
    <div class="lib-actions-row research-synth-actions" style="margin-top:10px">
      <button class="action-btn xs accent" data-action="research.promote-artifact" data-idx="${synthIdx}">Promote to artifact</button>
      <button class="action-btn xs" data-action="research.save-source" data-kind="synthesis">Save to store</button>
      <button class="action-btn xs ghost" data-action="research.cite" data-slug="${esc(_researchSlug('Synthesis: ' + (data.topic || 'untitled')))}">Cite</button>
    </div>
    ${sourceRows ? `<div style="margin-top:12px;font-size:0.62rem;color:var(--text-muted);margin-bottom:6px">ALL SOURCES</div><div class="res-source-rows">${sourceRows}</div>` : ''}
    <div class="research-actions" style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="action-btn accent" data-action="research.capture" data-idx="${synthIdx}">+ Capture synthesis as artifact</button>
      <button class="action-btn cyan" data-action="research.library">View captured artifacts</button>
      <button class="action-btn" data-action="research.export">Export as MD</button>
    </div>
  `;

  // RX-1 — when the deep-dive minted a session, open the conversational
  // reading surface seeded with this synthesis as turn 0. Additive: the legacy
  // #research-output above is untouched.
  if (data.session_id) {
    try {
      renderResearchSession({
        id: data.session_id,
        topic: data.topic,
        model: data.model,
        source_ids: (data.sources || []).map(s => s && s.url).filter(Boolean),
        turns: [{
          kind: 'synthesis',
          question: data.topic,
          answer: data.synthesis || '',
          sources: data.sources || [],
          web_search: true,
        }],
      });
    } catch (e) { /* reading surface is additive — never break results */ }
  }

  // Store for export AND for tab-switch rehydration.
  window._lastResearch = data;
}

/* ── RX-1: stateful research session (thread + reading surface) ──────────
   The two-column session view. LEFT: a thread of turns + a sticky follow-up
   input. RIGHT: a full-width reading surface where the synthesis and each
   follow-up answer render as markdown reading cards. Egress is operator-
   initiated only (the follow-up 'web search' opt-in, OFF by default). */

function _researchTurnLabel(turn, idx) {
  if (turn.kind === 'synthesis') return 'SYNTHESIS';
  return 'FOLLOW-UP ' + idx;
}

// One turn as a compact thread bubble (question + answer preview).
function _researchThreadTurnHtml(turn, idx) {
  const q = turn.kind === 'synthesis'
    ? (turn.question || '')
    : (turn.question || '');
  const answerPreview = String(turn.answer || '').slice(0, 260);
  const more = String(turn.answer || '').length > 260 ? '…' : '';
  const web = turn.web_search
    ? '<span class="research-turn-flag" title="operator-initiated web search">web</span>'
    : '';
  const grounded = turn.grounded
    ? '<span class="research-turn-flag grounded" title="grounded on your local knowledge store">grounded</span>'
    : '';
  return `
    <div class="research-turn" data-idx="${idx}">
      <div class="research-turn-head">
        <span class="research-turn-label">${_researchTurnLabel(turn, idx)}</span>
        ${web}${grounded}
      </div>
      ${q ? `<div class="research-turn-q">${esc(q)}</div>` : ''}
      <div class="research-turn-a">${esc(answerPreview)}${more}</div>
    </div>`;
}

// One turn as a full-width reading card on the surface (markdown, no letterbox).
function _researchReadingCardHtml(turn, idx) {
  const body = window.renderMarkdown
    ? window.renderMarkdown(turn.answer || '', { chat: false })
    : esc(turn.answer || '');
  const srcs = (turn.sources || []).map(s => {
    if (!s) return '';
    if (s.kind === 'rag') {
      return `<span class="res-source-chip rag" title="local knowledge · score ${esc(String(s.score ?? ''))}">${esc(s.title || s.doc_id || 'local')}</span>`;
    }
    const url = s.url || '#';
    return `<a class="res-source-chip" href="${safeUrl(url)}" target="_blank" rel="noopener">${esc((s.title || url || '').slice(0, 80))}</a>`;
  }).join('');
  const heading = turn.kind === 'synthesis'
    ? esc(turn.question || 'Synthesis')
    : esc(turn.question || 'Follow-up');
  return `
    <div class="research-reading-card ${turn.kind === 'synthesis' ? 'synthesis' : ''}" data-idx="${idx}">
      <div class="research-reading-head">
        <span class="research-reading-kind">${_researchTurnLabel(turn, idx)}</span>
        <span class="research-reading-q">${heading}</span>
      </div>
      <div class="research-reading-body synthesis-block">${body}</div>
      ${srcs ? `<div class="research-reading-sources res-sources">${srcs}</div>` : ''}
    </div>`;
}

// Render (or re-render) the whole session view from a session object.
function renderResearchSession(session) {
  if (!session || !session.id) return;
  window._researchSession = session;
  const wrap = document.getElementById('research-session');
  const thread = document.getElementById('research-thread');
  const surface = document.getElementById('research-surface');
  if (!wrap || !thread || !surface) return;
  const turns = session.turns || [];
  thread.innerHTML = turns.map((t, i) => _researchThreadTurnHtml(t, i)).join('')
    || '<div class="research-empty" style="padding:20px">No turns yet.</div>';
  surface.innerHTML = turns.map((t, i) => _researchReadingCardHtml(t, i)).join('');
  wrap.hidden = false;
  // Keep the newest turn in view in both columns.
  thread.scrollTop = thread.scrollHeight;
}

// Append a single freshly-answered follow-up turn to both columns without a
// full re-render (keeps scroll + avoids re-parsing the synthesis markdown).
function _appendResearchTurn(turn) {
  const session = window._researchSession;
  if (!session) return;
  session.turns = session.turns || [];
  const idx = session.turns.length;
  session.turns.push(turn);
  const thread = document.getElementById('research-thread');
  const surface = document.getElementById('research-surface');
  if (thread) {
    thread.insertAdjacentHTML('beforeend', _researchThreadTurnHtml(turn, idx));
    thread.scrollTop = thread.scrollHeight;
  }
  if (surface) {
    surface.insertAdjacentHTML('beforeend', _researchReadingCardHtml(turn, idx));
    const card = surface.lastElementChild;
    if (card && card.scrollIntoView) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// Submit the follow-up: POST /api/research/followup, append the answered turn.
async function submitResearchFollowup() {
  const session = window._researchSession;
  const input = document.getElementById('research-followup-input');
  const btn = document.getElementById('research-followup-btn');
  const webEl = document.getElementById('research-followup-web');
  if (!session || !input) return;
  const question = input.value.trim();
  if (!question) return;
  const web_search = !!(webEl && webEl.checked);

  if (btn) { btn.disabled = true; btn.textContent = 'Thinking…'; }
  try {
    // retries:0 — a follow-up runs a local model (and maybe a web search); a
    // 504-retry would double-answer.
    const resp = await Net.call('/api/research/followup', {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.id, question, web_search }),
      },
    });
    const data = (resp.data && typeof resp.data === 'object') ? resp.data : {};
    if (!resp.ok) throw new Error(data.detail || resp.error || `HTTP ${resp.status}`);
    _appendResearchTurn({
      kind: 'followup',
      question,
      answer: data.answer || '',
      sources: data.sources || [],
      web_search: !!data.web_search,
      grounded: !!data.grounded,
    });
    input.value = '';
    if (webEl) webEl.checked = false;
  } catch (e) {
    if (window.Toast) window.Toast.danger('Follow-up failed', String(e));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Ask'; }
  }
}

Actions.click({ 'research.followup': () => submitResearchFollowup() });

/* ── RX-2: actionable results — save to the Obsidian-like store + cite ────────
   Each source/result row can be promoted (captured artifact), saved as a
   durable RAG-indexed markdown note in the shared `research` workspace, or
   cited as a [[source:<slug>]] wikilink into the follow-up input. All egress
   is operator-initiated (a save writes local; nothing leaves the box). */

// Frontend slug — mirrors the server's _derive_slug so a cite token resolves to
// the note a save writes (same normalization on both sides).
function _researchSlug(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'note';
}

async function researchSaveSource(el) {
  let title;
  let content;
  let url = el.dataset.url || null;
  let slug = el.dataset.slug || '';
  if (el.dataset.kind === 'synthesis') {
    const d = window._lastResearch || {};
    title = 'Synthesis: ' + (d.topic || 'untitled');
    content = d.synthesis || '';
    url = null;
    slug = _researchSlug(title);
  } else {
    title = el.dataset.title || 'source';
    content = (url ? 'source: ' + url + '\n\n' : '') + title;
  }
  if (!slug) slug = _researchSlug(title);
  const prev = el.textContent;
  el.disabled = true;
  el.textContent = 'Saving…';
  try {
    const resp = await Net.call('/api/research/save-source', {
      retries: 0,
      init: {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, url, slug, tags: ['research'] }),
      },
    });
    const data = (resp.data && typeof resp.data === 'object') ? resp.data : {};
    if (!resp.ok) throw new Error(data.detail || resp.error || `HTTP ${resp.status}`);
    if (window.Toast) {
      window.Toast.success('Saved to store', data.path + (data.rag_ingested ? ' · indexed' : ''), { ttl: 2500 });
    }
    el.textContent = 'Saved ✓';
    setTimeout(() => { el.disabled = false; el.textContent = prev; }, 1500);
  } catch (e) {
    if (window.Toast) window.Toast.danger('Save failed', String(e));
    el.disabled = false;
    el.textContent = prev;
  }
}

function researchCite(el) {
  const slug = el.dataset.slug || '';
  if (!slug) return;
  const input = document.getElementById('research-followup-input');
  const token = `[[source:${slug}]]`;
  if (input) {
    input.value = input.value ? input.value.replace(/\s*$/, '') + ' ' + token + ' ' : token + ' ';
    input.focus();
  }
  if (window.Toast) window.Toast.info('Cite', `Inserted ${token}`, { ttl: 1200 });
}

// Store subnav — Explore (graph + research) vs Store (the browsable note tree).
// Toggling `store-active` hides every explore sibling via CSS (only-add: one
// class + one rule) so no existing markup is restructured.
function switchResearchView(view) {
  const tab = document.getElementById('tab-research');
  if (!tab) return;
  const isStore = view === 'store';
  tab.classList.toggle('store-active', isStore);
  tab.querySelectorAll('.research-subnav-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.view === view));
  if (isStore) { try { ResearchStore.load(); } catch (_) {} }
}

Actions.click({
  'research.save-source': (el) => researchSaveSource(el),
  'research.cite': (el) => researchCite(el),
  'research.subnav': (el) => switchResearchView(el.dataset.view),
});

// ── Research artifact capture ────────────────────────────────────────────
// Wraps POST /api/feedback/artifacts. Each click captures the finding as
// a durable record (and best-effort RAG-ingests it server-side so the
// artifact becomes semantically searchable in the Research tab).


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
    // S0: chat lives in its own tab — landing on the Composer tab IS the
    // canvas reveal (the retired canvas-mode pivot is subsumed).
    if (typeof switchTab === 'function') switchTab('dashboard');
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

// IA shuffle (S3): the Context-tab relocator is GONE. #tab-research now
// statically owns the knowledge graph + deep research + the RAG document
// surface + the Role Library (see index.html) — no boot-time DOM moves,
// and #wf-roles-list / #wf-role-preview resolve directly to the visible
// Research mounts (the old id-promotion trick is retired; the Catalog's
// hidden anchors are statically named wf-roles-list-legacy /
// wf-role-preview-legacy).
document.addEventListener('DOMContentLoaded', () => {
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

  // (S3: the Role-Library boot builder that used to live here is gone —
  // the panel is statically authored inside #tab-research and refreshed
  // by switchTab's research branch via loadRoles().)
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

// Drag-and-drop wiring for the Documents drop zone (now in #tab-research).
// Mirrors the visual state class `.is-dragging` so the zone highlights
// under the cursor.
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

// ── DR-1: durable draft identity + WAL ──────────────────────────────
// A draft is the lossless canvas snapshot (dfEditor.export() + dfNodeData +
// dfNextId + dfSeedSchema + meta) keyed by a client-minted draft_id — distinct
// from the published workflow_id. The id is minted SYNCHRONOUSLY at canvas-
// dirty t0 (before any autosave) so a crash mid-first-edit still reconciles to
// one identity. Persisted to a localStorage WAL (crash-safe, sync) + debounced
// to the server (POST /api/composer/drafts).
let _dfActiveDraftId = null;     // the draft currently being edited (or null)
let _dfDraftDirty = false;       // unsaved canvas changes since last flush
let _dfDraftFlushTimer = null;   // debounced server/WAL flush handle
let _dfRestoring = false;        // suppress dirty marks while restore rebuilds
let _dfLoading = false;          // suppress dirty marks while a SAVED wf loads
let _dfDraftPublishing = false;  // suppress dirty marks during publish-freeze
let _dfBootRestoreDone = false;  // boot reconciliation runs once per session
// Set synchronously at module load: if a WAL draft exists we must SUPPRESS the
// boot seed (dfEnsureSeedNode bails) until dfBootRestoreDraft() rebuilds the
// real canvas — otherwise the auto-spawned seed races the restored one.
let _dfDraftQueued = false;
const _DF_WAL_KEY = 'enclave.composer.draft.wal';
const _DF_FLUSH_MS = 4000;
try { _dfDraftQueued = !!_dfWalRead(); } catch (_) { _dfDraftQueued = false; }

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

// ── BU4: Pattern presets (deployment topologies) ────────────────────
// A PATTERN is the shape work executes in — every card maps onto the
// engine's closed 8-kind vocabulary. SIMPLE = one node emitting one
// engine kind; COMPLEX = a pre-wired, editable sub-DAG scaffold.
//
// SINGLE SOURCE OF TRUTH — tests/test_pattern_presets.py parses the
// strict-JSON block between the String.raw backticks below and
// round-trips every preset's `steps` through the frozen
// WorkflowDefinition model (api/models/workflow_models.py). Keep it
// strict JSON: no comments, no trailing commas, no backticks, no ${.
// String.raw so the \" escapes inside prompt strings survive for both
// JSON.parse here and json.loads in the pytest.
const dfPatternTemplatesJson = String.raw`
[
  {
    "key": "llm_step",
    "name": "LLM step",
    "complexity": "SIMPLE",
    "kind": "llm",
    "desc": "One model call — the atomic unit. Exactly one prompt in, text out.",
    "steps": [
      {
        "id": "llm_step",
        "name": "LLM Step",
        "kind": "llm",
        "role": "general",
        "system_prompt": "You are a capable assistant. Complete the task described by your inputs and reply with the result.",
        "inputs": ["seed.query"],
        "outputs": ["text"]
      }
    ]
  },
  {
    "key": "orchestrator",
    "name": "Orchestrator (dynamic)",
    "complexity": "SIMPLE",
    "kind": "orchestrator",
    "desc": "A lead agent plans and spawns workers from a catalog at run time. Ships with one pre-filled worker; worker inputs are always seed.* refs.",
    "steps": [
      {
        "id": "orchestrator",
        "name": "Orchestrator",
        "kind": "orchestrator",
        "role": "reasoning",
        "inputs": ["seed.query"],
        "outputs": ["result"],
        "planner": {
          "role_inline": "You are the lead agent. Decompose the goal, spawn workers from the catalog, and integrate their results.",
          "task": "Plan the work, dispatch workers, and emit the complete directive once the goal is met.",
          "constraints": ["Spawn the fewest workers that cover the goal."]
        },
        "workers": {
          "worker": {
            "id": "worker",
            "name": "Worker",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are a focused worker agent. Complete the assigned sub-task and reply with your findings.",
            "inputs": ["seed.task"],
            "outputs": ["findings"]
          }
        }
      }
    ]
  },
  {
    "key": "remote_agent",
    "name": "Remote agent",
    "complexity": "SIMPLE",
    "kind": "a2a",
    "desc": "Delegate to an external A2A-protocol agent by agent card + skill. The remote agent owns its own model and prompt.",
    "steps": [
      {
        "id": "remote_agent",
        "name": "Remote Agent",
        "kind": "a2a",
        "agent_card_url": "http://localhost:9100/.well-known/agent.json",
        "skill": "answer",
        "inputs": ["seed.query"],
        "outputs": ["result"]
      }
    ]
  },
  {
    "key": "consolidate_learn",
    "name": "Consolidate (learn)",
    "complexity": "SIMPLE",
    "kind": "consolidate",
    "desc": "Distill upstream outputs into durable cross-run memory (playbook, semantic, or episodic store).",
    "steps": [
      {
        "id": "consolidate_learn",
        "name": "Consolidate",
        "kind": "consolidate",
        "inputs": [],
        "outputs": ["lessons"],
        "consolidate": {
          "target": "playbook",
          "target_name": "workflow-lessons",
          "system_prompt": "Distill the inputs into concise, durable lessons worth keeping in the playbook."
        }
      }
    ]
  },
  {
    "key": "code_sandbox",
    "name": "Code sandbox",
    "complexity": "SIMPLE",
    "kind": "code",
    "desc": "Run Python in the sandboxed executor. Inline source — edit the code in the config panel.",
    "steps": [
      {
        "id": "code_sandbox",
        "name": "Code Sandbox",
        "kind": "code",
        "outputs": ["result"],
        "code": {
          "language": "python",
          "source": "inline",
          "code": "print('hello from the sandbox')"
        }
      }
    ]
  },
  {
    "key": "ralph_loop",
    "name": "Ralph loop",
    "complexity": "COMPLEX",
    "kind": "ralph",
    "desc": "Autonomous plan → execute → verify → consolidate loop with a journal and halt rails. Pick a budget preset before dropping — long-running raises the caps for overnight automation.",
    "budget_presets": {
      "standard": { "max_iterations": 25, "max_wall_seconds": 3600, "max_total_tokens": 1000000, "max_consecutive_failures": 3 },
      "long_running": { "max_iterations": 200, "max_wall_seconds": 28800, "max_total_tokens": 5000000, "max_consecutive_failures": 5 }
    },
    "steps": [
      {
        "id": "ralph",
        "name": "Ralph Loop",
        "kind": "ralph",
        "inputs": ["seed.query"],
        "outputs": ["progress"],
        "ralph": {
          "journal_path": "data/ralph/composer-journal.jsonl",
          "halt": {
            "max_iterations": 25,
            "max_wall_seconds": 3600,
            "max_total_tokens": 1000000,
            "max_consecutive_failures": 3,
            "goal_gate": "verify.approved == True"
          }
        },
        "body": [
          {
            "id": "plan",
            "name": "Plan",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are the planner. Read the goal and the playbook lessons, then emit this iteration's plan as an ordered list of concrete actions.",
            "inputs": ["seed.query", "$memory.playbook.workflow-lessons"],
            "outputs": ["plan"]
          },
          {
            "id": "execute",
            "name": "Execute",
            "kind": "llm",
            "role": "general",
            "system_prompt": "You are the executor. Carry out the plan and report exactly what you produced.",
            "inputs": ["plan.plan"],
            "outputs": ["work"]
          },
          {
            "id": "verify",
            "name": "Verify",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are the verifier. Check the work against the goal. Emit JSON: {\"approved\": true|false, \"progress\": \"<one-line status>\"}.",
            "inputs": ["plan.plan", "execute.work"],
            "outputs": ["approved", "progress"]
          },
          {
            "id": "consolidate",
            "name": "Consolidate",
            "kind": "consolidate",
            "inputs": ["verify.progress"],
            "outputs": ["lessons"],
            "consolidate": {
              "target": "playbook",
              "target_name": "workflow-lessons",
              "system_prompt": "Record what worked and what failed this iteration as short playbook lessons."
            }
          }
        ]
      }
    ]
  },
  {
    "key": "research_fanout",
    "name": "Research fan-out",
    "complexity": "COMPLEX",
    "kind": "parallel",
    "desc": "Index splits the question into angles, three subagents research in parallel, gather synthesizes one report. Gather's outputs mirror the parent's contract exactly.",
    "steps": [
      {
        "id": "index",
        "name": "Index",
        "kind": "llm",
        "role": "reasoning",
        "system_prompt": "Break the research question into three distinct, non-overlapping angles. Emit JSON: {\"angles\": [\"<angle 1>\", \"<angle 2>\", \"<angle 3>\"]}.",
        "inputs": ["seed.query"],
        "outputs": ["angles"]
      },
      {
        "id": "fan_out",
        "name": "Research Fan-out",
        "kind": "parallel",
        "depends_on": ["index"],
        "outputs": ["report"],
        "execution": { "mode": "auto", "failure_policy": "continue_on_partial" },
        "branches": [
          {
            "id": "researcher_1",
            "name": "Researcher 1",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are research subagent 1. Take the first angle from the index and research it thoroughly.",
            "inputs": ["index.angles"],
            "outputs": ["findings"]
          },
          {
            "id": "researcher_2",
            "name": "Researcher 2",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are research subagent 2. Take the second angle from the index and research it thoroughly.",
            "inputs": ["index.angles"],
            "outputs": ["findings"]
          },
          {
            "id": "researcher_3",
            "name": "Researcher 3",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are research subagent 3. Take the third angle from the index and research it thoroughly.",
            "inputs": ["index.angles"],
            "outputs": ["findings"]
          }
        ],
        "gather": {
          "id": "gather",
          "name": "Gather",
          "kind": "llm",
          "role": "reasoning",
          "system_prompt": "Synthesize the three researchers' findings into one coherent report.",
          "inputs": ["researcher_1.findings", "researcher_2.findings", "researcher_3.findings"],
          "outputs": ["report"]
        }
      }
    ]
  },
  {
    "key": "tdd_loop",
    "name": "TDD loop",
    "complexity": "COMPLEX",
    "kind": "loop",
    "desc": "Write → test (sandboxed) → critic, repeated until the critic approves. The critic is the last body step and produces every loop output.",
    "steps": [
      {
        "id": "tdd",
        "name": "TDD Loop",
        "kind": "loop",
        "inputs": ["seed.query"],
        "outputs": ["code", "approved"],
        "max_iterations": 5,
        "until": { "type": "gate", "gate": "critic.approved == True" },
        "body": [
          {
            "id": "write",
            "name": "Write",
            "kind": "llm",
            "role": "coding",
            "system_prompt": "You are the implementer. Write or revise the code to satisfy the requirements and fix any prior test failures.",
            "inputs": ["seed.query"],
            "outputs": ["code"]
          },
          {
            "id": "test",
            "name": "Test",
            "kind": "code",
            "inputs": ["write.code"],
            "outputs": ["test_output"],
            "code": {
              "language": "python",
              "source": "inline",
              "code": "print('replace with the test harness for this loop')"
            }
          },
          {
            "id": "critic",
            "name": "Critic",
            "kind": "llm",
            "role": "reasoning",
            "system_prompt": "You are the critic. Review the code against the test output. Emit JSON: {\"approved\": true|false, \"code\": \"<the final code>\"}.",
            "inputs": ["write.code", "test.test_output"],
            "outputs": ["code", "approved"]
          }
        ]
      }
    ]
  }
]
`;
const dfPatternTemplates = JSON.parse(dfPatternTemplatesJson);
// Ralph card's budget-preset toggle state (standard | long_running) —
// applied to ralph.halt on the NEXT drop. Module-scoped, no window global.
let dfRalphBudgetPreset = 'standard';

// S1 (G5 quarantine): legacy Catalog runner mode toggle. The compose/run
// chrome it drove (#wf-mode-run, #wf-mode-compose, #wf-composer-controls,
// #wf-composer) left the DOM when the Composer became the sole authoring
// surface — only #wf-runner-controls / #wf-detail survive as hidden ID
// anchors inside #catalog-legacy-mounts. Null-guard every anchor so the
// surviving callers (dfRunWorkflow's post-save pivot at ~5901 and the
// window bridge) degrade to a no-op against absent chrome instead of a
// TypeError that would abort the Composer "Run ▶" path mid-flight.
function setWfMode(mode) {
  const $id = (id) => document.getElementById(id);
  const modeRun = $id('wf-mode-run');
  if (modeRun) modeRun.classList.toggle('active', mode === 'run');
  const modeCompose = $id('wf-mode-compose');
  if (modeCompose) modeCompose.classList.toggle('active', mode === 'compose');
  const runnerControls = $id('wf-runner-controls');
  if (runnerControls) runnerControls.style.display = mode === 'run' ? 'flex' : 'none';
  const composerControls = $id('wf-composer-controls');
  if (composerControls) composerControls.style.display = mode === 'compose' ? 'flex' : 'none';
  const wfComposer = $id('wf-composer');
  if (wfComposer) wfComposer.style.display = mode === 'compose' ? 'block' : 'none';
  const detail = $id('wf-detail');
  if (detail) detail.style.display = mode === 'run' ? detail.dataset.wasVisible || 'none' : 'none';
  if (mode === 'compose') { dfInitEditor(); dfInitPalette(); dfInitPatterns(); }
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
  // DR-1: a real spawn dirties the draft (import()'s addNodeImport does NOT
  // dispatch nodeCreated, so restore never self-triggers this).
  dfEditor.on('nodeCreated', () => { try { dfMarkDraftDirty(); } catch (_) {} });
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
    try { dfMarkDraftDirty(); } catch (_) {}
  });
  dfEditor.on('connectionCreated', (conn) => { dfOnConnectionCreated(conn); if (!_dfAnchorBusy) dfScheduleAnchorRefresh(); try { dfMarkDraftDirty(); } catch (_) {} });
  dfEditor.on('connectionRemoved', (conn) => { dfOnConnectionRemoved(conn); if (!_dfAnchorBusy) dfScheduleAnchorRefresh(); try { dfMarkDraftDirty(); } catch (_) {} });

  container.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; });
  container.addEventListener('drop', (e) => {
    e.preventDefault();
    // MS-2: whatever branch a drop dispatches into, clear the empty-state
    // overlay at the drop-handler tail so a freshly dropped step is never
    // left painted-over by the "Compose a workflow" guide. finally() runs on
    // every early-return path below; the update is real-step-gated + guarded.
    try {
    const rect = container.getBoundingClientRect();
    const canvasX = (e.clientX - rect.left - dfEditor.precanvas.getBoundingClientRect().left + rect.left);
    const canvasY = (e.clientY - rect.top  - dfEditor.precanvas.getBoundingClientRect().top  + rect.top);
    // Templates take priority — they're the cheapest spawn.
    const tmplKey = e.dataTransfer.getData('application/df-template');
    if (tmplKey) {
      dfAddNodeFromTemplate(tmplKey, canvasX, canvasY);
      return;
    }
    // Library task cards (LB6): their own MIME routes to
    // dfAddNodeFromLibraryTask (dfStepTemplates + the df-template path are
    // untouched). Additive branch — a missing key is a no-op.
    const libTaskKey = e.dataTransfer.getData('application/df-library-task');
    if (libTaskKey) {
      dfAddNodeFromLibraryTask(TasksPanel.libraryTask(libTaskKey), canvasX, canvasY);
      return;
    }
    // Pattern cards (BU4): SIMPLE spawns one kinded node; COMPLEX routes
    // through dfScaffoldPattern for the pre-wired sub-DAG.
    const patternKey = e.dataTransfer.getData('application/df-pattern');
    if (patternKey) {
      dfAddPatternFromTemplate(patternKey, canvasX, canvasY);
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
    } finally {
      try { ComposerView.updateCanvasEmptyState(); } catch (_) {}
    }
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
  // MS-2: click-to-add lands the node asynchronously (agent fetch) — refresh
  // the empty-state overlay once it's registered so the guide clears.
  try { ComposerView.updateCanvasEmptyState(); } catch (_) {}
  if (window.Toast) Toast.info('Added agent', agentId, { ttl: 1400 });
}
window.composerAddAgentAtCenter = composerAddAgentAtCenter;

// Map an agent's AgentTool[] to the canonical step ToolRef string form the
// YAML emitter (main.js ~8961) and every data.tools consumer read:
//   plugin tool → "<plugin_id>.<tool_id>"
//   MCP tool    → "mcp:<server_id>.<tool_id>"
// Built-in `type` tools (web_search/workflow/code_exec) are agent-only — there
// is no step-level ToolRef for them — so they're dropped rather than emitted
// as a bogus `plugin: "web_search"`. Defensive against string / partial entries.
function _dfAgentToolsToRefs(tools) {
  if (!Array.isArray(tools)) return [];
  const out = [];
  for (const t of tools) {
    if (typeof t === 'string') { out.push(t); continue; }
    if (!t || typeof t !== 'object') continue;
    if (t.mcp_server && t.tool_id) { out.push(`mcp:${t.mcp_server}.${t.tool_id}`); continue; }
    if (t.plugin_id && t.tool_id) { out.push(`${t.plugin_id}.${t.tool_id}`); continue; }
    // `type`-only built-ins have no step ToolRef → skip (not misencoded).
  }
  return out;
}

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
      // GP-2 commit 5: a fork must carry the agent's TOOLS, context, and
      // sampling knobs — before this the step dropped them, so a forked
      // "researcher with web_search + a plugin tool at temp 0.2" became a
      // bare llm step. Map each AgentTool → the canonical ToolRef string form
      // the emitter + every consumer read (`mcp:server.tool` / `plugin.tool`);
      // built-in `type` tools (web_search/workflow/code_exec) have no step-
      // level ToolRef representation, so they're dropped (not misencoded).
      tools: _dfAgentToolsToRefs(a.tools),
      // Carried for fork fidelity + the config panel; ContextSource list.
      context: Array.isArray(a.context) ? a.context.map(c => ({ ...c })) : [],
      temperature: a.temperature != null ? a.temperature : '',
      max_tokens: a.max_tokens != null ? a.max_tokens : '',
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
  // BU7: wipe the segmented strip + the Logs-pane signal line so a fresh
  // edit/run starts from a clean slate.
  const segs = document.getElementById('df-run-progress-segments');
  if (segs) segs.innerHTML = '';
  const signals = document.getElementById('ws-logs-signals');
  if (signals) { signals.hidden = true; signals.innerHTML = ''; }
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

// ── BU7: segmented per-step bar + actionable run signals ────────────
// Both are painted ONLY from dfApplyRunState — the run chip and the
// Logs-pane signal line have exactly one writer (the poller never
// touches them directly).

// Segment class for one planned step, mirroring the node status classes:
// green (completed) / red (failed) / pulse (running) / amber (skipped or
// deferred). Unreported steps read amber on a terminal run (they never
// got to run) and neutral/queued while the run is still alive.
function _dfSegClass(st, terminal) {
  if (st === 'completed') return 'seg-completed';
  if (st === 'failed' || st === 'error') return 'seg-failed';
  if (st === 'running') return 'seg-running';
  if (st === 'skipped' || st === 'deferred') return 'seg-skipped';
  return terminal ? 'seg-skipped' : 'seg-queued';
}

function _dfPaintRunSegments(segClasses) {
  const strip = document.getElementById('df-run-progress-segments');
  if (!strip) return;
  strip.innerHTML = (segClasses || []).map(c => `<span class="df-run-seg ${c}"></span>`).join('');
}

// First line of an error, hard-capped so a chip stays one line.
function _dfShortError(err) {
  const line = String(err || '').split('\n')[0].trim();
  return line.length > 72 ? line.slice(0, 72) + '…' : line;
}

// Issues = actionable-but-not-red conditions:
//   - an unresolved seed.<key> reference (engine: "input 'seed.x' has no
//     producer") — the chip routes to the SEED node's config;
//   - ralph/loop non-convergence: the step completed by exhausting its
//     iteration cap without the goal gate firing. Detectable because both
//     executors repurpose StepResult.retries as iterations-beyond-first,
//     so retries+1 >= the node's configured max_iterations means the cap
//     halted the loop, not the gate. (A loop that FAILED on its cap
//     already surfaces as a red chip carrying the engine's error.)
function _dfCollectRunIssues(run, resultById) {
  const issues = [];
  const seenSeedRefs = new Set();
  const scanSeed = (text, sourceStep) => {
    if (!text || !/no producer|unresolved|missing/i.test(text)) return;
    (String(text).match(/\bseed\.[A-Za-z0-9_]+/g) || []).forEach(ref => {
      if (seenSeedRefs.has(ref)) return;
      seenSeedRefs.add(ref);
      issues.push({
        stepId: sourceStep || '',
        seed: true,
        label: (sourceStep ? 'step ' + sourceStep + ': ' : '') + ref + ' unresolved',
        title: 'Unresolved seed input — opens the seed node config',
      });
    });
  };
  resultById.forEach((r, stepId) => { if (r && r.error) scanSeed(r.error, stepId); });
  scanSeed(run.error, '');

  resultById.forEach((r, stepId) => {
    if (!r || r.status !== 'completed') return;
    const dfId = dfFindNodeIdForStep(stepId);
    const data = dfId != null ? dfNodeData[dfId] : null;
    if (!data) return;
    const cap = data.kind === 'ralph'
      ? (data.ralph && data.ralph.halt && data.ralph.halt.max_iterations)
      : data.kind === 'loop' ? data.max_iterations : null;
    if (!cap) return;
    if ((r.retries || 0) + 1 >= cap) {
      issues.push({
        stepId,
        seed: false,
        label: `step ${stepId}: max_iterations (${cap}) reached without goal_gate`,
        title: 'Loop ran to its iteration cap without converging — opens the step config',
      });
    }
  });
  return issues;
}

// Paint the Logs-pane header signal line: 'N green · red (step X: err) ·
// issue (…)'. Green/amber chips are counters; each red/issue chip is a
// logs.focus-step button carrying data-step-id (+ data-seed for issues
// that route to the seed node).
function _dfRenderRunSignals(run, planned, status, resultById) {
  const host = document.getElementById('ws-logs-signals');
  if (!host) return;
  if (!run || !(planned || []).length) { host.hidden = true; host.innerHTML = ''; return; }
  let green = 0, amber = 0;
  const reds = [];
  planned.forEach(stepId => {
    if (!stepId) return;
    const st = status.get(stepId);
    if (st === 'completed') green += 1;
    else if (st === 'skipped' || st === 'deferred') amber += 1;
    else if (st === 'failed' || st === 'error') {
      const r = resultById.get(stepId) || {};
      reds.push({ stepId, error: _dfShortError(r.error || 'failed') });
    }
  });
  const issues = _dfCollectRunIssues(run, resultById);
  const chips = [`<span class="ws-signal-chip sig-green">${green} green</span>`];
  if (amber) chips.push(`<span class="ws-signal-chip sig-amber">${amber} skipped</span>`);
  reds.forEach(r => chips.push(
    `<button type="button" class="ws-signal-chip sig-red" data-action="logs.focus-step"
             data-step-id="${esc(r.stepId)}" title="Focus this step's config">red (step ${esc(r.stepId)}: ${esc(r.error)})</button>`));
  issues.forEach(i => chips.push(
    `<button type="button" class="ws-signal-chip sig-issue" data-action="logs.focus-step"
             data-step-id="${esc(i.stepId)}"${i.seed ? ' data-seed="1"' : ''} title="${esc(i.title)}">issue (${esc(i.label)})</button>`));
  host.innerHTML = chips.join('');
  host.hidden = false;
}

// Signal-chip click target: resolve the canvas node for a step id (seed-
// sourced issues resolve to the seed node instead — the critic fix that
// closes the edit-seed→run→watch→refine loop), render its config and
// select it. Mirrors the nodeSelected contract without touching the
// single-click path.
function dfFocusStepFromSignal(stepId, toSeed) {
  const dfId = toSeed ? dfFindSeedNodeId() : dfFindNodeIdForStep(stepId);
  if (dfId == null || !dfNodeData[dfId]) {
    if (window.Toast) Toast.info('Step not on canvas', stepId || 'seed');
    return;
  }
  dfSelectedNodeId = dfId;
  dfRenderConfigPanel(dfId);
  if (window.ComposerWorkstream) {
    try {
      const data = dfNodeData[dfId];
      ComposerWorkstream.focusStep((data && (data.id || data.name)) || dfId);
    } catch (_) {}
  }
  const el = document.getElementById('node-' + dfId);
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
}

function dfApplyRunState(run) {
  if (!run) { dfClearRunState(); return; }
  const results = Array.isArray(run.step_results) ? run.step_results : [];
  // Build a step_id → status map. Steps without a result entry are
  // implicitly queued (the engine hasn't started them yet).
  const status = new Map();
  results.forEach(r => { if (r && r.step_id) status.set(r.step_id, r.status || ''); });
  // BU7: full result per step — the signal line needs errors + retries,
  // not just the status string.
  const resultById = new Map();
  results.forEach(r => { if (r && r.step_id) resultById.set(r.step_id, r); });

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
    // CH-1: keep the id so the floating chip's composer.open-active-run can
    // re-open the finished run after a reload; drop the *live* flag only.
    try { if (run.run_id) localStorage.setItem('enclave.composer.activeRun', run.run_id); } catch (_) {}
  } else {
    window._composerActiveRunId = run.run_id || window._composerActiveRunId || null;
    // CH-1: persist so #df-run-progress → composer.open-active-run survives a reload.
    try {
      if (window._composerActiveRunId) localStorage.setItem('enclave.composer.activeRun', window._composerActiveRunId);
    } catch (_) {}
    _dfToggleStopBtn(true);
  }

  let completed = 0;
  let total = 0;
  let currentLabel = '';
  const segClasses = [];  // BU7: one entry per planned step, in order

  // Tag every known canvas node.
  (planned || []).forEach(stepId => {
    if (!stepId) return;
    total += 1;
    const st = status.get(stepId);
    segClasses.push(_dfSegClass(st, terminalRunStatus));
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

  // BU7: segmented strip + Logs-pane signal line — painted before the
  // chip's early returns so terminal runs keep both current.
  _dfPaintRunSegments(segClasses);
  _dfRenderRunSignals(run, planned, status, resultById);

  // CH-1: the iteration-chaining "what next" strip. Mount the next-action
  // chips on the terminal + gate states (persist-until-next-event); clear it
  // while a run is mid-flight so a freshly-started run never shows the
  // previous run's chips. The failing-step id routes the 'Fix failing step'
  // chip straight to the canvas node that broke.
  try {
    const _naStatus = String(run.status || '').toLowerCase();
    const _firstFailed = (results.find(r =>
      r && ['failed', 'error'].includes(String(r.status || '').toLowerCase())) || {}).step_id || '';
    const _naCtx = {
      runId: run.run_id || window._composerActiveRunId || '',
      workflowId: run.workflow_id || (document.getElementById('df-wf-id') || {}).value || '',
      stepId: _firstFailed,
    };
    if (_naStatus === 'awaiting_approval') NextActions.render('run.awaiting_gate', _naCtx);
    else if (terminalRunStatus && _naStatus === 'completed') NextActions.render('run.finished.ok', _naCtx);
    else if (terminalRunStatus && ['failed', 'error'].includes(_naStatus)) NextActions.render('run.finished.failed', _naCtx);
    else NextActions.clear();
  } catch (_) {}

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
    // CP-1b: first-success handoff — the FIRST time this operator lands a
    // completed run, nudge them toward the durable next step (Save → reuse).
    // Fires once, ever (localStorage-gated); the persistent NextActions strip
    // above owns the ongoing chaining affordances.
    try {
      if (localStorage.getItem('enclave.firstRunDone') !== '1') {
        localStorage.setItem('enclave.firstRunDone', '1');
        if (window.Toast) Toast.success('First run complete', 'Save this workflow to reuse it — then schedule or run it again anytime.', { ttl: 6000 });
      }
    } catch (_) {}
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
  // The Patterns bench boots alongside the Task palette (its own
  // idempotence guard) so both ComposerView.init and setWfMode cover it.
  dfInitPatterns();
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
    // BU5 — hover inspection: the bottom inspector shows the Task's
    // instructions + the engine kind it compiles to. Wired through the
    // Actions router (mouseover) — no click behavior is registered for
    // this action, so drag/drop semantics are untouched.
    item.dataset.action = 'bench.inspect-template';
    item.dataset.templateKey = tmpl.key;
    palette.appendChild(item);
  });
  // LB6 — append operator library tasks under a "Library" divider AFTER the
  // 13 statics (deduped, statics win). Fail-soft: any error leaves the
  // palette byte-identical. dfStepTemplates is NEVER mutated.
  try { TasksPanel.fetchComposerTasks(); } catch (_) {}
}

// LB6 — spawn a canvas node from a library task schema. Mirrors
// dfAddNodeFromTemplate's node-data body but registers via the
// dfAddPatternNode seam (the established "register without a dfStepTemplates
// lookup" precedent) — dfStepTemplates stays frozen. Save/restore is
// untouched: the node carries a dfRoleColors-vocabulary `role`, so the
// existing role-scan restore resolves it to the same-role static or `custom`.
function dfAddNodeFromLibraryTask(schema, x, y) {
  if (!schema || !dfEditor) return;
  const data = {
    id: (schema.key || 'task') + '_' + (++dfNextId),
    name: schema.name,
    role: schema.role,
    persona: schema.persona,
    system_prompt: schema.prompt,
    outputs: [...(schema.outputs && schema.outputs.length ? schema.outputs : ['result'])],
    output_format: schema.format || 'raw',
    quality_gates: [],
    inputs: [],
    is_decision: !!schema.is_decision,
  };
  const nodeId = dfAddPatternNode(data, x, y);
  dfSelectedNodeId = nodeId;
  dfRenderConfigPanel(nodeId);
  dfAutoChain(nodeId);
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();
  return nodeId;
}

// Click-to-add fallback for library task cards (drag-and-drop is finicky
// across zoom/trackpad — the agent-card path had the same issue). Spawns the
// task at the visible canvas center; `tasks.send-to-composer` rides this.
async function dfSendTaskToComposer(taskId) {
  const schema = TasksPanel.mapById(taskId);
  if (!schema) { if (window.Toast) Toast.warn('Task not found', taskId, { ttl: 1600 }); return; }
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
  const canvas = document.getElementById('drawflow-canvas');
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const precanvas = dfEditor.precanvas || canvas;
  const pre = precanvas.getBoundingClientRect();
  const zoom = (typeof dfEditor.zoom === 'number') ? dfEditor.zoom : 1;
  const canvasX = (rect.left + rect.width / 2 - pre.left) / zoom;
  const canvasY = (rect.top + rect.height / 2 - pre.top) / zoom;
  const jitter = (Math.random() - 0.5) * 60;
  dfAddNodeFromLibraryTask(schema, canvasX + jitter, canvasY + jitter);
  if (window.Toast) Toast.info('Added task', taskId, { ttl: 1400 });
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

// ── BU4: Patterns bench + scaffolds ─────────────────────────────────
// Cards render from dfPatternTemplates into #patterns-palette and drag
// with MIME application/df-pattern (drop branch in dfInitEditor).
function dfInitPatterns() {
  dfInitGuidance();  // BU8d card boots with the bench (own idempotence guard)
  const palette = document.getElementById('patterns-palette');
  if (!palette || palette.dataset.initialized) return;
  palette.dataset.initialized = '1';
  palette.innerHTML = dfPatternTemplates.map(tpl => {
    const badge = `<span class="df-pattern-badge ${tpl.complexity === 'COMPLEX' ? 'complex' : 'simple'}">${esc(tpl.complexity)}</span>`;
    // Ralph ships ONE card with a budget-preset toggle (standard vs
    // long-running automation) instead of a duplicate card.
    const budgetToggle = tpl.budget_presets
      ? `<span class="df-pattern-presets" title="Budget preset stamped onto the halt caps on the next drop">${
          Object.keys(tpl.budget_presets).map(p =>
            `<button type="button" class="df-pattern-preset-btn${p === dfRalphBudgetPreset ? ' active' : ''}"
              data-action="pattern.budget-preset" data-preset="${esc(p)}">${esc(p.replace('_', '-'))}</button>`).join('')
        }</span>`
      : '';
    return `
      <div class="df-palette-item df-pattern-card" draggable="true"
           data-action="bench.inspect-pattern" data-drag-mime="application/df-pattern" data-drag-value="${esc(tpl.key)}"
           data-inspect-key="${esc(tpl.key)}"
           data-pattern="${esc(tpl.key)}" title="${esc(tpl.name)} — ${esc(tpl.desc)}">
        <span class="df-palette-titleblock">
          <span class="df-palette-label">${esc(tpl.name)} ${badge}</span>
          <span class="df-pattern-desc">${esc(tpl.desc)}</span>
          ${budgetToggle}
        </span>
      </div>`;
  }).join('');
  // PT-1 — append operator library patterns under a "Library" divider AFTER
  // the 8 statics (deduped, statics win). Fail-soft: any error leaves the
  // bench byte-identical. dfPatternTemplates is NEVER mutated.
  try { fetchComposerPatterns(); } catch (_) {}
}

// Budget-preset toggle on the Ralph card. Module-scoped state; repaints
// every toggle button so the active choice reads across re-renders.
Actions.click({
  'pattern.budget-preset': el => {
    dfRalphBudgetPreset = el.dataset.preset === 'long_running' ? 'long_running' : 'standard';
    document.querySelectorAll('.df-pattern-preset-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.preset === dfRalphBudgetPreset));
  }
});

// ── PT-1: Patterns drill-down + first-class Patterns library kind ─────────
// Operator patterns ride their OWN Map + the shared application/df-pattern
// MIME; the 8-entry dfPatternTemplates statics array stays FROZEN.
// dfResolvePattern consults the statics FIRST, then the user layer
// (fail-soft) — an unknown key resolves to null and the drop/scaffold no-ops.
const dfUserPatterns = new Map();  // key(=user pattern id) -> template-shaped record

function dfResolvePattern(key) {
  return dfPatternTemplates.find(t => t.key === key)
      || dfUserPatterns.get(key)
      || null;
}

// Read-only drill-down of a pattern's structure — node list + ASCII wiring +
// the config defaults an operator needs before dropping (ralph halt/budget,
// loop until-gate, seed.* inputs, provenance). Pure HTML string so ONE
// renderer serves both the bench inspector (painted into #df-config-panel)
// and the Patterns library overview. Never throws on a malformed record.
function dfRenderPatternStructure(tpl) {
  if (!tpl) return '<div class="model-empty">No pattern selected.</div>';
  const steps = Array.isArray(tpl.steps) ? tpl.steps : [];
  const complexity = tpl.complexity
    || (steps.some(s => s && s.kind && s.kind !== 'llm') ? 'COMPLEX' : 'SIMPLE');
  const seedRefs = new Set();
  const cfg = [];
  const asciiLines = [];
  const glyph = last => (last ? '└─' : '├─');

  const collect = (s) => {
    if (!s) return;
    (s.inputs || []).forEach(r => { if (String(r).startsWith('seed.')) seedRefs.add(String(r)); });
    if (s.kind === 'ralph' && s.ralph) {
      const halt = s.ralph.halt || {};
      if (halt.goal_gate) cfg.push(['halt gate', halt.goal_gate]);
      const caps = ['max_iterations', 'max_wall_seconds', 'max_total_tokens', 'max_consecutive_failures']
        .filter(k => halt[k] != null).map(k => `${k}=${halt[k]}`);
      if (caps.length) cfg.push(['ralph halt', caps.join(', ')]);
      if (s.ralph.journal_path) cfg.push(['journal', s.ralph.journal_path]);
    }
    if (s.kind === 'loop') {
      if (s.until && s.until.gate) cfg.push(['until gate', s.until.gate]);
      if (s.max_iterations) cfg.push(['max iterations', String(s.max_iterations)]);
    }
    if (s.kind === 'parallel' && s.execution) {
      cfg.push(['fan-out', `${s.execution.mode || 'auto'} · ${s.execution.failure_policy || 'fail_fast'}`]);
    }
    if (s.kind === 'consolidate' && s.consolidate) {
      cfg.push(['consolidate', `${s.consolidate.target || '?'} · ${s.consolidate.target_name || ''}`.trim()]);
    }
    if (s.kind === 'code' && s.code) cfg.push(['code', `${s.code.language || 'python'} · ${s.code.source || 'inline'}`]);
    if (s.kind === 'a2a' && s.agent_card_url) cfg.push(['a2a card', s.agent_card_url]);
    (s.body || []).forEach(collect);
    (s.branches || []).forEach(collect);
    if (s.gather) collect(s.gather);
    Object.values(s.workers || {}).forEach(collect);
  };

  const walkAscii = (s, prefix, last) => {
    if (!s) return;
    asciiLines.push(`${prefix}${glyph(last)} ${s.id || '?'}  ·  ${s.kind || 'llm'}`);
    const childPrefix = prefix + (last ? '    ' : '│   ');
    const kids = [];
    (s.body || []).forEach(c => kids.push(c));
    (s.branches || []).forEach(c => kids.push(c));
    if (s.gather) kids.push(s.gather);
    Object.values(s.workers || {}).forEach(w => kids.push(w));
    kids.forEach((c, i) => walkAscii(c, childPrefix, i === kids.length - 1));
  };

  if (tpl.budget_presets) {
    Object.keys(tpl.budget_presets).forEach(p => {
      const caps = tpl.budget_presets[p] || {};
      cfg.push([`budget: ${p}`, Object.entries(caps).map(([k, v]) => `${k}=${v}`).join(', ')]);
    });
  }
  steps.forEach(collect);
  asciiLines.push('seed');
  steps.forEach((s, i) => walkAscii(s, ' ', i === steps.length - 1));

  const badge = `<span class="df-pattern-badge ${complexity === 'COMPLEX' ? 'complex' : 'simple'}">${esc(complexity)}</span>`;
  const cfgHtml = cfg.length ? `
    <div class="prompts-render-label" style="margin-top:12px">// CONFIG DEFAULTS</div>
    <div style="display:grid;grid-template-columns:130px 1fr;gap:4px 12px;font-size:0.64rem">
      ${cfg.map(([k, v]) => `<div style="color:var(--text-muted)">${esc(k)}</div><div style="word-break:break-word"><code>${esc(String(v))}</code></div>`).join('')}
    </div>` : '';
  const seedHtml = seedRefs.size ? `
    <div class="prompts-render-label" style="margin-top:12px">// SEED INPUTS</div>
    <div style="display:flex;flex-wrap:wrap;gap:4px">${[...seedRefs].map(r => `<span class="df-tag">${esc(r)}</span>`).join('')}</div>` : '';

  return `
    <div style="display:flex;align-items:baseline;gap:8px;padding:4px 0 8px">
      <strong style="font-size:0.74rem;color:var(--text)">${esc(tpl.name || tpl.key || tpl.id || 'pattern')}</strong>
      ${badge}
      <span class="workbench-item-pill">kind: ${esc(tpl.kind || 'llm')}</span>
    </div>
    ${tpl.desc ? `<div style="font-size:0.66rem;color:var(--text-muted);margin-bottom:8px">${esc(tpl.desc)}</div>` : ''}
    <div class="prompts-render-label">// STRUCTURE (${steps.length} top-level step${steps.length === 1 ? '' : 's'})</div>
    <pre class="prompts-render-pre" style="white-space:pre;font-size:0.66rem;line-height:1.5;background:var(--bg-alt,rgba(0,0,0,0.2));padding:8px;border:1px solid var(--border);overflow:auto;max-height:280px">${esc(asciiLines.join('\n'))}</pre>
    ${cfgHtml}
    ${seedHtml}`;
}

// Append operator library patterns to #patterns-palette under a "Library"
// divider AFTER the 8 statics (deduped, statics win). Fail-soft: any error —
// network, 404 (patterns router absent), empty list — leaves the bench
// byte-identical. Idempotent (guards on the divider); pass {force:true} to
// rebuild after a save. Populates dfUserPatterns so drops/inspection resolve.
async function fetchComposerPatterns(opts) {
  opts = opts || {};
  const palette = document.getElementById('patterns-palette');
  if (!palette) return;
  const existingDivider = palette.querySelector('[data-lib-divider]');
  if (existingDivider && !opts.force) return;
  let rows = [];
  try {
    const r = await Net.call('/api/patterns', { silent: true, retries: 0 });
    if (!r.ok) return;                        // fail-soft — bench untouched
    rows = (r.data || []).filter(p => p && p.source === 'user');
  } catch (_) { return; }
  // Rebuild path: drop any prior library rows + divider first (statics stay).
  if (existingDivider) existingDivider.remove();
  palette.querySelectorAll('.df-pattern-lib').forEach(el => el.remove());
  dfUserPatterns.clear();
  if (!rows.length) return;                   // nothing to add → identical bench
  const frag = document.createDocumentFragment();
  rows.forEach(p => {
    const rec = {
      key: p.id, name: p.name || p.id, complexity: p.complexity || 'SIMPLE',
      kind: p.kind || 'llm', desc: p.desc || '', steps: p.steps || [],
      budget_presets: p.budget_presets || null,
    };
    dfUserPatterns.set(rec.key, rec);
    frag.appendChild(_dfUserPatternCard(rec));
  });
  const divider = document.createElement('div');
  divider.className = 'df-palette-divider';
  divider.setAttribute('data-lib-divider', '1');
  divider.style.cssText = 'margin:10px 4px 4px;padding-top:8px;border-top:1px solid var(--border);' +
    'font-family:var(--mono);font-size:0.58rem;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-muted)';
  divider.textContent = 'Library';
  palette.appendChild(divider);
  palette.appendChild(frag);
}

function _dfUserPatternCard(rec) {
  const badge = `<span class="df-pattern-badge ${rec.complexity === 'COMPLEX' ? 'complex' : 'simple'}">${esc(rec.complexity)}</span>`;
  const item = document.createElement('div');
  item.className = 'df-palette-item df-pattern-card df-pattern-lib';
  item.draggable = true;
  // Library pattern cards carry the SAME inspect+drag grammar as the statics.
  item.dataset.action = 'bench.inspect-pattern';
  item.dataset.dragMime = 'application/df-pattern';
  item.dataset.dragValue = rec.key;
  item.dataset.pattern = rec.key;
  item.dataset.inspectKey = rec.key;
  item.title = `${rec.name} — ${rec.desc || ''}`;
  item.innerHTML = `
    <span class="df-palette-titleblock">
      <span class="df-palette-label">${esc(rec.name)} ${badge}</span>
      <span class="df-pattern-desc">${esc(rec.desc || '')}</span>
    </span>`;
  return item;
}

// composer.save-as-pattern — collect the current canvas' top-level steps via
// _dfCleanStep (seed + sub-DAG proxies excluded), Confirm, and POST to the
// Patterns library. The saved pattern joins the bench under "Library".
async function dfSaveCanvasAsPattern() {
  if (typeof dfEditor === 'undefined' || !dfEditor) {
    Toast.warn('Canvas not ready', 'Open the Composer first'); return;
  }
  const steps = [];
  try {
    const homeData = dfEditor.export().drawflow.Home.data;
    Object.keys(homeData).map(Number).forEach(nid => {
      const data = dfNodeData[nid];
      if (!data || data.is_seed || data._sub_of != null) return;
      const step = _dfCleanStep(data);
      if (step) steps.push(step);
    });
  } catch (_) { Toast.danger('Save failed', 'Could not read the canvas'); return; }
  if (!steps.length) { Toast.warn('Nothing to save', 'Add at least one step to the canvas'); return; }
  const rawId = (document.getElementById('df-wf-id') ? document.getElementById('df-wf-id').value : '') || '';
  let id = rawId.trim().replace(/[^A-Za-z0-9_-]/g, '_').replace(/^[^A-Za-z0-9]+/, '').slice(0, 80);
  if (!id) id = 'pattern_' + Date.now().toString(36);
  const name = (document.getElementById('df-wf-name') ? document.getElementById('df-wf-name').value : '').trim() || id;
  const composite = steps.some(s => ['ralph', 'loop', 'parallel', 'orchestrator'].indexOf(s.kind) !== -1);
  const complexity = composite ? 'COMPLEX' : 'SIMPLE';
  const kind = (steps[steps.length - 1] && steps[steps.length - 1].kind) || 'llm';
  const ok = await Confirm.ask({
    title: 'Save canvas as pattern',
    body: `Save the current canvas (${steps.length} step${steps.length === 1 ? '' : 's'}) as reusable pattern "${id}"? It joins the Patterns library and the Composer bench.`,
    okLabel: 'Save',
  });
  if (!ok) return;
  const headers = { 'Content-Type': 'application/json' };
  try { if (window.AdminAuth && AdminAuth.authHeaders) Object.assign(headers, AdminAuth.authHeaders()); } catch (_) {}
  try {
    const r = await Net.call('/api/patterns', {
      retries: 0,
      init: { method: 'POST', headers, body: JSON.stringify({ id, name, complexity, kind, desc: '', steps, tags: [] }) },
    });
    if (!r.ok) { Toast.danger('Save failed', (r.data && r.data.detail) || r.error || `HTTP ${r.status}`); return; }
    Toast.success('Pattern saved', id);
    try { await fetchComposerPatterns({ force: true }); } catch (_) {}
    try { PatternsPanel.load(); } catch (_) {}
  } catch (e) { Toast.danger('Save failed', e.message); }
}

Actions.click({ 'composer.save-as-pattern': () => dfSaveCanvasAsPattern() });

// Library "Send to Composer" — scaffold a pattern (static or user) onto the
// canvas at its visible center. Mirrors dfSendTaskToComposer: switch to the
// Composer, ensure the editor + user-pattern resolution are ready, then
// scaffold (SIMPLE routes to dfAddPatternFromTemplate internally).
async function dfSendPatternToComposer(patternId) {
  if (!patternId) return;
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
  try { await fetchComposerPatterns({ force: true }); } catch (_) {}  // resolve user patterns
  if (!dfResolvePattern(patternId)) {
    if (window.Toast) Toast.warn('Pattern not found', patternId, { ttl: 1600 });
    return;
  }
  const canvas = document.getElementById('drawflow-canvas');
  const rect = canvas ? canvas.getBoundingClientRect() : { left: 0, top: 0, width: 800, height: 500 };
  const precanvas = dfEditor.precanvas || canvas;
  const pre = precanvas ? precanvas.getBoundingClientRect() : { left: 0, top: 0 };
  const zoom = (typeof dfEditor.zoom === 'number') ? dfEditor.zoom : 1;
  const cx = (rect.left + rect.width / 2 - pre.left) / zoom;
  const cy = (rect.top + rect.height / 2 - pre.top) / zoom;
  dfScaffoldPattern(patternId, cx, cy);
  if (window.Toast) Toast.info('Added pattern', patternId, { ttl: 1400 });
}

// Decorate an engine-schema preset step into canvas node data: the UI
// fields dfNodeHtml/dfRenderConfigPanel expect, plus the pattern
// provenance (data.pattern / data.complexity) and — for sub-DAG editing
// proxies — the parent linkage the composite serializer keys off.
// MUTATES the given step object on purpose: a proxy node's data IS the
// parent's nested body/branch/gather entry, so leaf edits serialize.
function _dfDecoratePatternNodeData(step, tpl, parentNid, subRole) {
  step.name = step.name || step.id;
  step.role = step.role || 'general';
  step.inputs = step.inputs || [];
  step.outputs = (step.outputs && step.outputs.length) ? step.outputs : ['result'];
  if (!step.system_prompt) step.system_prompt = '';
  step.output_format = 'raw';
  step.quality_gates = [];
  step.persona = (window.AgentIcons ? AgentIcons.resolve({ role: step.role, name: step.name }) : 'general');
  step.pattern = tpl.key;
  step.complexity = tpl.complexity;
  if (parentNid != null) { step._sub_of = parentNid; step._sub_role = subRole; }
  return step;
}

// Shared spawn for pattern nodes (composite parents + sub-DAG proxies).
// Mirrors dfAddNodeFromTemplate's registration without the dfStepTemplates
// lookup; selection/wiring stays with the callers.
function dfAddPatternNode(data, x, y) {
  const nodeId = dfEditor.addNode(data.id, 1, 1, x, y, data.id, {}, dfNodeHtml(data));
  dfNodeData[nodeId] = data;
  const wrap = document.getElementById('node-' + nodeId);
  if (wrap) {
    if (data._sub_of != null) wrap.classList.add('is-pattern-sub');
    if (data.kind && data.kind !== 'llm') wrap.classList.add('is-pattern-composite');
  }
  return nodeId;
}

// SIMPLE pattern drop → one node stamping data.kind + its kind config
// block. COMPLEX keys route through dfScaffoldPattern.
function dfAddPatternFromTemplate(patternKey, x, y) {
  const tpl = dfResolvePattern(patternKey);
  if (!tpl || !dfEditor) return;
  if (tpl.complexity === 'COMPLEX') return dfScaffoldPattern(patternKey, x, y);
  const step = JSON.parse(JSON.stringify(tpl.steps[0]));
  step.id = step.id + '_' + (++dfNextId);
  const nodeId = dfAddPatternNode(_dfDecoratePatternNodeData(step, tpl), x, y);
  dfSelectedNodeId = nodeId;
  dfRenderConfigPanel(nodeId);
  dfAutoChain(nodeId);  // native wire onto the current tail (seed included)
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();
  return nodeId;
}

// COMPLEX pattern drop → the preset's pre-wired, editable sub-DAG.
// Top-level steps become canvas nodes; a composite's body/branches/gather
// entries ALSO become canvas nodes (placeholder personas per the
// composition rule) whose data objects are the SAME nested objects the
// parent serializes — editing a leaf edits the emitted nested step.
function dfScaffoldPattern(patternKey, x, y) {
  const tpl = dfResolvePattern(patternKey);
  if (!tpl || !dfEditor) return;
  if (tpl.complexity !== 'COMPLEX') return dfAddPatternFromTemplate(patternKey, x, y);
  const steps = JSON.parse(JSON.stringify(tpl.steps));
  // Top-level ids get the same uniqueness suffix other spawns use; nested
  // body/branch/gather ids stay preset-scoped (the engine namespaces them
  // under the parent). Rewrite cross-references to the renamed ids.
  const suffix = '_' + (++dfNextId);
  const rename = {};
  steps.forEach(s => { rename[s.id] = s.id + suffix; });
  const rewrite = (s) => {
    if (!s) return;
    if (Array.isArray(s.inputs)) s.inputs = s.inputs.map(ref => {
      const head = String(ref).split('.')[0];
      return rename[head] ? rename[head] + String(ref).slice(head.length) : ref;
    });
    if (Array.isArray(s.depends_on)) s.depends_on = s.depends_on.map(d => rename[d] || d);
    (s.body || []).forEach(rewrite);
    (s.branches || []).forEach(rewrite);
    rewrite(s.gather);
    Object.values(s.workers || {}).forEach(rewrite);
  };
  steps.forEach(s => { s.id = rename[s.id]; rewrite(s); });
  // Ralph's budget-preset toggle (standard / long-running) stamps the
  // selected caps onto the halt block — one card, two presets.
  if (tpl.budget_presets) {
    const caps = tpl.budget_presets[dfRalphBudgetPreset] || tpl.budget_presets.standard;
    steps.forEach(s => { if (s.kind === 'ralph' && s.ralph) s.ralph.halt = Object.assign({}, s.ralph.halt || {}, caps); });
  }

  const nodeIdByStep = {};
  let firstNid = null;
  let cursorX = x;
  steps.forEach(step => {
    const nid = dfAddPatternNode(_dfDecoratePatternNodeData(step, tpl), cursorX, y);
    nodeIdByStep[step.id] = nid;
    if (firstNid == null) {
      firstNid = nid;
      dfAutoChain(nid);  // chain the scaffold's head onto the current tail
    }
    const childX = cursorX + 240;
    // Sequential body chain (ralph / loop): parent → first → … → last.
    if (Array.isArray(step.body)) {
      let prev = nid;
      step.body.forEach((c, i) => {
        const cnid = dfAddPatternNode(_dfDecoratePatternNodeData(c, tpl, nid, 'body'), childX + i * 240, y + 180);
        try { dfEditor.addConnection(prev, cnid, 'output_1', 'input_1'); } catch (_) {}
        prev = cnid;
      });
      cursorX = childX + step.body.length * 240;
    }
    // Parallel fan: parent → every branch → gather.
    if (Array.isArray(step.branches)) {
      const branchNids = step.branches.map((c, i) =>
        dfAddPatternNode(_dfDecoratePatternNodeData(c, tpl, nid, 'branch'), childX, y - 160 + i * 160));
      branchNids.forEach(bnid => { try { dfEditor.addConnection(nid, bnid, 'output_1', 'input_1'); } catch (_) {} });
      if (step.gather) {
        const gnid = dfAddPatternNode(_dfDecoratePatternNodeData(step.gather, tpl, nid, 'gather'), childX + 250, y);
        branchNids.forEach(bnid => { try { dfEditor.addConnection(bnid, gnid, 'output_1', 'input_1'); } catch (_) {} });
        cursorX = childX + 500;
      }
    }
    cursorX += 280;
  });
  // Wire the preset's declared top-level deps (e.g. index → fan-out).
  steps.forEach(step => (step.depends_on || []).forEach(dep => {
    const src = nodeIdByStep[dep], dst = nodeIdByStep[step.id];
    if (src != null && dst != null) { try { dfEditor.addConnection(src, dst, 'output_1', 'input_1'); } catch (_) {} }
  }));
  if (firstNid != null) {
    dfSelectedNodeId = firstNid;
    dfRenderConfigPanel(firstNid);
  }
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();
  return firstNid;
}

// GP-1a (P0-2): decorate a LOADED composite step (or one of its nested body/
// branch/gather/worker entries) into canvas node data. Mirrors
// _dfDecoratePatternNodeData but WITHOUT the Patterns-bench template provenance
// (data.pattern/complexity) — a loaded step wasn't scaffolded from a bench card.
// Fills the UI fields dfNodeHtml/dfRenderConfigPanel bind to while PRESERVING
// kind + the nested composite config, and stamps the _sub_of/_sub_role proxy
// linkage the composite serializer (_dfCleanStep / dfExportYaml) keys off.
function _dfDecorateLoadedComposite(step, parentNid, subRole) {
  step.name = step.name || step.id;
  step.role = step.role || 'general';
  step.inputs = Array.isArray(step.inputs) ? step.inputs : [];
  step.outputs = (Array.isArray(step.outputs) && step.outputs.length) ? step.outputs : ['result'];
  // a2a steps carry no prompt; every other kind renders with an (often empty)
  // system_prompt so the node card + config panel have a field to bind. Accept
  // the v2 structured prompt as a fallback, same as the plain-load path.
  if (step.kind !== 'a2a' && step.system_prompt == null) {
    step.system_prompt = (step.prompt && (step.prompt.task || step.prompt.role_inline)) || '';
  }
  step.output_format = (step.output_parser && step.output_parser.format) || step.output_format || 'raw';
  step.quality_gates = Array.isArray(step.quality_gates) ? step.quality_gates : [];
  step.persona = step.persona ||
    (window.AgentIcons ? AgentIcons.resolve({ role: step.role, name: step.name }) : 'general');
  if (parentNid != null) { step._sub_of = parentNid; step._sub_role = subRole; }
  return step;
}

// GP-1a (P0-2): the inverse of dfScaffoldPattern for a SAVED composite step.
// dfScaffoldPattern builds a composite sub-DAG from a Patterns-bench TEMPLATE;
// this rebuilds the identical wired sub-DAG from a loaded step definition (real
// ids, no suffix-rename, no budget re-stamp — the stored step already carries
// its resolved kind config). The parent node's data IS the serialized step
// (_dfCleanStep reads src.body/branches/gather/workers straight off it) and the
// child proxies share those SAME nested objects, so a leaf edit round-trips and
// the children (carrying _sub_of) never re-serialize as top-level steps. Returns
// the parent node id so composerLoadDefinition can wire depends_on via idMap.
function dfHydrateCompositeStep(step, x, y) {
  if (!dfEditor || !step) return null;
  const parent = _dfDecorateLoadedComposite(step);
  const nid = dfAddPatternNode(parent, x, y);
  const childX = x + 240;
  // Sequential body chain (ralph / loop): parent → first → … → last.
  if (Array.isArray(parent.body) && parent.body.length) {
    let prev = nid;
    parent.body.forEach((c, i) => {
      const cnid = dfAddPatternNode(_dfDecorateLoadedComposite(c, nid, 'body'), childX + i * 240, y + 180);
      try { dfEditor.addConnection(prev, cnid, 'output_1', 'input_1'); } catch (_) {}
      prev = cnid;
    });
  }
  // Parallel fan-out: parent → every branch → gather.
  if (Array.isArray(parent.branches) && parent.branches.length) {
    const branchNids = parent.branches.map((c, i) =>
      dfAddPatternNode(_dfDecorateLoadedComposite(c, nid, 'branch'), childX, y - 160 + i * 160));
    branchNids.forEach(bnid => { try { dfEditor.addConnection(nid, bnid, 'output_1', 'input_1'); } catch (_) {} });
    if (parent.gather) {
      const gnid = dfAddPatternNode(_dfDecorateLoadedComposite(parent.gather, nid, 'gather'), childX + 250, y);
      branchNids.forEach(bnid => { try { dfEditor.addConnection(bnid, gnid, 'output_1', 'input_1'); } catch (_) {} });
    }
  }
  // Orchestrator: parent → each named worker (workers is an id→step map).
  if (parent.workers && typeof parent.workers === 'object' && !Array.isArray(parent.workers)) {
    Object.keys(parent.workers).forEach((k, i) => {
      const wnid = dfAddPatternNode(_dfDecorateLoadedComposite(parent.workers[k], nid, 'worker'), childX, y + 160 + i * 150);
      try { dfEditor.addConnection(nid, wnid, 'output_1', 'input_1'); } catch (_) {}
    });
  }
  return nid;
}

function dfNodeHtml(data) {
  // Seed nodes render as the START-pill grammar, not a step card. Branching
  // here keeps every repaint path (dfUpdateNodeData's apply) seed-aware.
  if (data.is_seed) return dfSeedNodeHtml(data);
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
    <div class="df-node-body${data.is_decision ? ' is-decision' : ''}" style="--role-color:${color}" data-persona="${esc(persona)}" data-action="composer.edit-node">
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

// ── Editable seed node ──────────────────────────────────────────────
// The seed is a REAL canvas node (registered in dfNodeData) that owns the
// user query + the declared input schema. It is NOT an engine step:
// dfExportYaml folds its schema into context.inputs, its outgoing edges
// become seed.<key> inputs on the target steps (never depends_on), and its
// query feeds the dfRunWorkflowLive seed payload. Exactly one seed exists
// per canvas; dfEnsureSeedNode auto-spawns it on an empty compose canvas.

function dfFindSeedNodeId() {
  for (const nid of Object.keys(dfNodeData)) {
    const d = dfNodeData[nid];
    if (d && d.is_seed) return Number(nid);
  }
  return null;
}

function dfSeedNodeHtml(data) {
  const keys = (data.seed_schema || []).map(s => s && s.key).filter(Boolean);
  const chips = (keys.length ? keys : ['—']).map(k => `<span>${esc(k)}</span>`).join('');
  // One-line query preview so the operator reads the workflow's intent
  // straight off the canvas; empty state nudges toward the dblclick edit.
  const queryLine = (data.query || '').trim()
    ? `<div class="df-seed-query" title="${esc(data.query)}">${esc(data.query)}</div>`
    : `<div class="df-seed-query is-empty">double-click to set the query</div>`;
  // Reuses the START anchor's visual grammar (.wf-anchor-start pill) so the
  // canvas reads the same — but this pill is live: dblclick opens its config.
  return `<div class="wf-anchor wf-anchor-start df-seed-node" data-action="composer.edit-node" title="Seed — the workflow's starting input. Double-click to edit the query + inputs.">
    <div class="wf-anchor-label">▶ SEED</div>
    <div class="wf-anchor-sub">query + inputs</div>
    ${queryLine}
    <div class="wf-anchor-keys">${chips}</div></div>`;
}

function dfAddSeedNode(x, y) {
  if (!dfEditor) return null;
  // Exactly-one-seed guard — re-entry hands back the existing node.
  const existing = dfFindSeedNodeId();
  if (existing != null) return existing;
  // Inherit the declared schema (Library round-trip via dfSeedSchema);
  // a fresh canvas starts with the canonical single `query` input.
  const schema = (Array.isArray(dfSeedSchema) && dfSeedSchema.length)
    ? dfSeedSchema.map(s => ({ key: s.key, description: s.description || '' }))
    : [{ key: 'query', description: 'What should this workflow do?' }];
  const data = {
    id: 'seed',
    name: 'Seed',
    is_seed: true,
    query: '',
    seed_schema: schema,
    outputs: schema.map(s => s.key),  // → connections emit seed.<key> refs
    inputs: [],
  };
  const nodeId = dfEditor.addNode('__seed__', 0, 1, x, y, '__seed__', {}, dfSeedNodeHtml(data));
  dfNodeData[nodeId] = data;
  // Keep the mirror in sync (dfExportYaml + the DfSeedSchema modal read it).
  dfSeedSchema = schema.map(s => ({ key: s.key, description: s.description }));
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();
  // MS-2: refresh the canvas state so the spine primes on the seed while the
  // overlay stays up (a seed alone is not a real step — see updateCanvasEmptyState).
  try { ComposerView.updateCanvasEmptyState(); } catch (_) {}
  return nodeId;
}

// Idempotent auto-spawn: an EMPTY compose canvas always offers the seed as
// its starting point. No-op when any node (seed included) already exists,
// so loaded workflows keep their decorative __start__ ghost untouched.
function dfEnsureSeedNode() {
  if (!dfEditor) return;
  // DR-1: while a draft is queued for restore, suppress the boot seed — the
  // restored snapshot carries its OWN seed and an auto-spawn here would race
  // it (two seeds). dfBootRestoreDraft() clears the flag once it has rebuilt.
  if (_dfDraftQueued) return;
  if (dfFindSeedNodeId() != null) return;
  if (Object.keys(dfNodeData).length) return;
  dfAddSeedNode(40, 200);
}

/* ══════════════════════════════════════════════════════════════════
   DR-1 — DURABLE DRAFT STORE (identity · snapshot · restore · In-Progress)
   A workflow is crystallized conversation; an in-progress workflow must
   STICK across reloads. The snapshot is opaque + lossless (dfEditor.export()
   round-trips ports/connections/composite _sub_of proxies + positions — proven
   by the DR-1 import() prototype); dfNodeData/dfNextId/dfSeedSchema are parallel
   module state restored by direct assignment (import() never touches them).
   ══════════════════════════════════════════════════════════════════ */

function _dfMintDraftId() {
  // uuid4 hex (32 chars), no dashes — matches the store's id charset.
  try {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '');
  } catch (_) { /* fall through */ }
  return 'd' + Date.now().toString(16) + Math.random().toString(16).slice(2, 10);
}

function _dfRealStepCount() {
  return Object.keys(dfNodeData || {})
    .filter(k => dfNodeData[k] && !dfNodeData[k].is_seed).length;
}

function _dfMetaField(id) { const el = document.getElementById(id); return el ? el.value : ''; }

// Opaque snapshot. export() OWNS zoom/pan/positions — we do NOT double-store a
// separate view transform (critique-resolution #17).
function dfBuildSnapshot() {
  let ex = null;
  try { ex = dfEditor ? JSON.parse(JSON.stringify(dfEditor.export())) : null; } catch (_) { ex = null; }
  return {
    export: ex,
    nodeData: JSON.parse(JSON.stringify(dfNodeData || {})),
    nextId: dfNextId,
    seedSchema: JSON.parse(JSON.stringify(dfSeedSchema || [])),
    meta: {
      id: _dfMetaField('df-wf-id'),
      name: _dfMetaField('df-wf-name'),
      description: _dfMetaField('df-wf-desc'),
      role: _dfMetaField('df-wf-role'),
      category: _dfMetaField('df-wf-category'),
    },
  };
}

// Post-restore invariant: EXACTLY ONE seed. The snapshot always carries the
// seed node; if a stray boot seed slipped in, drop the extras.
function _dfEnforceSingleSeed() {
  const seeds = Object.keys(dfNodeData || {}).filter(k => dfNodeData[k] && dfNodeData[k].is_seed);
  for (let i = 1; i < seeds.length; i++) {
    const nid = seeds[i];
    try { dfEditor.removeNodeId('node-' + nid); } catch (_) {}
    delete dfNodeData[nid];
  }
  return Object.keys(dfNodeData || {}).filter(k => dfNodeData[k] && dfNodeData[k].is_seed).length;
}

// Restore a snapshot LOSSLESSLY. Hard-clear canvas + dfNodeData + reset dfNextId
// BEFORE import (collision bindings), re-invoke anchor rebuild AFTER, assert one
// seed. Returns true on success.
function dfRestoreSnapshot(blob) {
  if (!blob || !blob.export) return false;
  _dfRestoring = true;
  try {
    if (typeof dfInitEditor === 'function' && !dfEditor) dfInitEditor();
    if (!dfEditor) return false;
    dfEditor.clear();
    dfNodeData = {};
    dfSelectedNodeId = null;
    dfNextId = (typeof blob.nextId === 'number') ? blob.nextId : 0;  // BEFORE import
    dfEditor.import(blob.export, false);  // rebuild graph; suppress import event
    dfNodeData = JSON.parse(JSON.stringify(blob.nodeData || {}));
    dfSeedSchema = JSON.parse(JSON.stringify(blob.seedSchema || []));
    const m = blob.meta || {};
    [['df-wf-id', m.id], ['df-wf-name', m.name], ['df-wf-desc', m.description],
     ['df-wf-role', m.role], ['df-wf-category', m.category]].forEach(([id, v]) => {
      const el = document.getElementById(id); if (el && v != null) el.value = v;
    });
    const descEl = document.getElementById('df-wf-desc');
    if (descEl) { try { descEl.dispatchEvent(new Event('input')); } catch (_) {} }
    _dfEnforceSingleSeed();
    if (typeof dfRefreshAnchors === 'function') dfRefreshAnchors();  // reconcile begin/end
    try { ComposerView.updateCanvasEmptyState(); } catch (_) {}
    return true;
  } catch (e) {
    console.warn('draft restore failed', e);
    return false;
  } finally {
    _dfRestoring = false;
  }
}

// ── WAL (localStorage, synchronous, crash-safe) ─────────────────────
function _dfWalRead() {
  try { const raw = localStorage.getItem(_DF_WAL_KEY); return raw ? JSON.parse(raw) : null; }
  catch (_) { return null; }
}
function _dfWalWrite(rec) {
  try { localStorage.setItem(_DF_WAL_KEY, JSON.stringify(rec)); } catch (_) {}
}
function _dfWalClear() {
  try { localStorage.removeItem(_DF_WAL_KEY); } catch (_) {}
}

// Mint identity at dirty-t0, mark dirty, schedule a debounced flush. No-ops
// while restoring / publishing / anchor-refreshing, and until the canvas holds
// a REAL step (a bare boot seed is not worth a draft).
function dfMarkDraftDirty() {
  if (_dfRestoring || _dfLoading || _dfDraftPublishing || _dfAnchorBusy) return;
  if (_dfRealStepCount() === 0) return;
  if (!_dfActiveDraftId) _dfActiveDraftId = _dfMintDraftId();  // synchronous t0
  _dfDraftDirty = true;
  clearTimeout(_dfDraftFlushTimer);
  _dfDraftFlushTimer = setTimeout(() => { dfFlushDraft(); }, _DF_FLUSH_MS);
}

function _dfDraftName() {
  const nm = (_dfMetaField('df-wf-name') || '').trim();
  const wid = (_dfMetaField('df-wf-id') || '').trim();
  return nm || wid || 'Untitled workflow';
}

// Flush the current snapshot to the WAL (first — crash-safe) then to the
// server (best-effort). Called by the debounce timer + beforeunload.
async function dfFlushDraft() {
  if (!_dfActiveDraftId || !_dfDraftDirty) return;
  const snap = dfBuildSnapshot();
  const rec = {
    draft_id: _dfActiveDraftId,
    name: _dfDraftName(),
    workflow_id: (_dfMetaField('df-wf-id') || '').trim() || null,
    step_count: _dfRealStepCount(),
    blob: snap,
    updated_at: Date.now() / 1000,
  };
  _dfWalWrite(rec);        // WAL first — survives a crash before the POST lands
  _dfDraftDirty = false;
  try {
    await Net.postJson('/api/composer/drafts', {
      draft_id: rec.draft_id, blob: snap, name: rec.name,
      workflow_id: rec.workflow_id, step_count: rec.step_count,
    }, { silent: true, retries: 0 });
  } catch (_) { /* WAL already holds it; next flush retries the server */ }
  try { if (_dfInProgressActive()) dfRefreshInProgress(); } catch (_) {}
}

// Boot reconciliation — runs once when the Composer first mounts. Reconcile the
// WAL against the server draft (newer updated_at wins) and restore it, then
// clear the boot-seed suppression flag. On the no-draft path this is a
// byte-for-byte no-op (the boot seed spawns exactly as before).
async function dfBootRestoreDraft() {
  if (_dfBootRestoreDone) { return; }
  _dfBootRestoreDone = true;
  const wal = _dfWalRead();
  if (!wal || !wal.draft_id) { _dfDraftQueued = false; return; }
  let rec = wal;
  try {
    const r = await Net.call('/api/composer/drafts/' + encodeURIComponent(wal.draft_id),
      { silent: true, retries: 0 });
    if (r.ok && r.data && (r.data.updated_at || 0) > (wal.updated_at || 0)) rec = r.data;
  } catch (_) { /* offline / not-yet-synced — the WAL copy wins */ }
  if (!rec || rec.published || !rec.blob || !rec.blob.export) {
    _dfDraftQueued = false;
    try { if (dfEditor && !Object.keys(dfNodeData).length) dfEnsureSeedNode(); } catch (_) {}
    return;
  }
  _dfActiveDraftId = rec.draft_id;
  const ok = dfRestoreSnapshot(rec.blob);
  _dfDraftQueued = false;
  if (!ok) {
    try { dfEnsureSeedNode(); } catch (_) {}
    return;
  }
  // Reconcile WAL -> server: the pre-reload flush may have been dropped (offline
  // or rate-limited during the boot burst), leaving the server behind the WAL.
  // Best-effort upsert AFTER the boot request burst subsides so the In-Progress
  // list reflects the restored draft. Delayed to dodge the cold-boot 429 window.
  setTimeout(() => {
    Net.postJson('/api/composer/drafts', {
      draft_id: rec.draft_id, blob: rec.blob, name: rec.name || _dfDraftName(),
      workflow_id: rec.workflow_id || null, step_count: rec.step_count || _dfRealStepCount(),
    }, { silent: true, retries: 0 }).catch(() => {});
  }, 2500);
  if (window.Toast) Toast.info('Draft restored', _dfDraftName() + ' — resumed where you left off', { ttl: 2600 });
}

// Publish-freeze: on a successful Save the draft's identity collapses into the
// saved workflow_id. Freeze/DELETE the draft so there is no dual mutable
// identity; the In-Progress row disappears. Edit-in-Composer of the published
// workflow loads the SAVED definition, never a post-publish draft blob.
async function dfPublishFreezeDraft(workflowId) {
  if (!_dfActiveDraftId) return;
  const id = _dfActiveDraftId;
  _dfDraftPublishing = true;
  clearTimeout(_dfDraftFlushTimer);
  _dfActiveDraftId = null;
  _dfDraftDirty = false;
  _dfWalClear();
  try {
    await Net.call('/api/composer/drafts/' + encodeURIComponent(id),
      { silent: true, retries: 0, init: { method: 'DELETE' } });
  } catch (_) { /* best-effort — the local identity is already released */ }
  _dfDraftPublishing = false;
  try { if (_dfInProgressActive()) dfRefreshInProgress(); } catch (_) {}
}

// ── In-Progress workstream pane (5th tab) ───────────────────────────
function _dfInProgressActive() {
  const t = document.querySelector('.workstream-tab[data-ws="in-progress"].active');
  return !!t;
}

function _dfRelTime(ts) {
  if (!ts) return '';
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (secs < 60) return 'just now';
  if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
  if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
  return Math.floor(secs / 86400) + 'd ago';
}

function _dfDraftRowHtml(d) {
  const active = d.draft_id === _dfActiveDraftId;
  const dirty = active && _dfDraftDirty;
  const status = (d.last_run_status || '').toLowerCase();
  const dotClass = status === 'completed' ? 'ok' : status === 'failed' ? 'fail'
    : status ? 'pending' : 'idle';
  const meta = dirty ? '<span class="df-draft-dirty">● unsaved</span>'
    : 'saved ' + esc(_dfRelTime(d.updated_at));
  return `<div class="df-draft-row${active ? ' active' : ''}" data-draft-id="${esc(d.draft_id)}">
    <span class="df-draft-run-dot df-draft-run-${dotClass}" title="last run: ${esc(status || 'none')}"></span>
    <button type="button" class="df-draft-open" data-action="drafts.open" data-draft-id="${esc(d.draft_id)}"
            title="Open this draft on the canvas">
      <span class="df-draft-name">${esc(d.name || 'Untitled workflow')}</span>
      <span class="df-draft-sub">${esc(d.step_count || 0)} step${d.step_count === 1 ? '' : 's'} · ${meta}</span>
    </button>
    <span style="flex:1"></span>
    <button type="button" class="action-btn xs ghost" data-action="drafts.rename" data-draft-id="${esc(d.draft_id)}" title="Rename">✎</button>
    <button type="button" class="action-btn xs ghost" data-action="drafts.duplicate" data-draft-id="${esc(d.draft_id)}" title="Duplicate">⎘</button>
    <button type="button" class="action-btn xs ghost" data-action="drafts.delete" data-draft-id="${esc(d.draft_id)}" title="Delete">×</button>
  </div>`;
}

async function dfRefreshInProgress() {
  const body = document.getElementById('ws-inprogress-body');
  if (!body) return;
  const r = await Net.call('/api/composer/drafts', { silent: true, retries: 0 });
  const rows = (r.ok && Array.isArray(r.data)) ? r.data : [];
  const meta = document.getElementById('ws-inprogress-meta');
  if (meta) meta.textContent = rows.length ? String(rows.length) : '—';
  if (!rows.length) {
    EmptyState.render(body, {
      title: 'No drafts in progress',
      detail: 'Start composing on the canvas — your work autosaves here and survives a reload. Publish with Save to graduate a draft into a workflow.',
      glyph: '✎',
    });
    return;
  }
  body.innerHTML = `<div class="df-draft-list">${rows.map(_dfDraftRowHtml).join('')}</div>`;
}

async function dfDraftOpen(id) {
  if (!id) return;
  const r = await Net.call('/api/composer/drafts/' + encodeURIComponent(id), { silent: true, retries: 0 });
  if (!r.ok || !r.data || !r.data.blob) { Toast.danger('Open failed', 'Draft could not be loaded'); return; }
  if (typeof switchTab === 'function') { try { switchTab('dashboard'); } catch (_) {} }
  if (typeof ComposerView !== 'undefined' && ComposerView.init) { try { ComposerView.init(); } catch (_) {} }
  _dfActiveDraftId = id;
  _dfDraftDirty = false;
  const ok = dfRestoreSnapshot(r.data.blob);
  if (ok) {
    _dfWalWrite({ draft_id: id, name: r.data.name, workflow_id: r.data.workflow_id,
                  step_count: r.data.step_count, blob: r.data.blob, updated_at: r.data.updated_at });
    dfRefreshInProgress();
  }
}

function dfDraftRename(id) {
  const row = document.querySelector('.df-draft-row[data-draft-id="' + id + '"]');
  const nameEl = row && row.querySelector('.df-draft-name');
  if (!nameEl) return;
  const current = nameEl.textContent || '';
  // Inline rename — no native prompt() (CP-1 keeps the shell prompt-free).
  const input = document.createElement('input');
  input.type = 'text'; input.value = current; input.className = 'df-draft-rename-input';
  input.setAttribute('data-draft-id', id);
  nameEl.replaceWith(input);
  input.focus(); input.select();
  const commit = async () => {
    const val = (input.value || '').trim();
    if (val && val !== current) {
      await Net.call('/api/composer/drafts/' + encodeURIComponent(id), {
        silent: true, retries: 0,
        init: { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: val }) },
      });
    }
    dfRefreshInProgress();
  };
  input.addEventListener('blur', commit, { once: true });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { e.preventDefault(); input.value = current; input.blur(); }
  });
}

async function dfDraftDuplicate(id) {
  const r = await Net.call('/api/composer/drafts/' + encodeURIComponent(id), { silent: true, retries: 0 });
  if (!r.ok || !r.data || !r.data.blob) { Toast.danger('Duplicate failed'); return; }
  const newId = _dfMintDraftId();
  await Net.postJson('/api/composer/drafts', {
    draft_id: newId, blob: r.data.blob, name: (r.data.name || 'Untitled') + ' copy',
    workflow_id: null, step_count: r.data.step_count,
  }, { silent: true, retries: 0 });
  Toast.info('Draft duplicated', (r.data.name || 'Untitled') + ' copy', { ttl: 1800 });
  dfRefreshInProgress();
}

function dfDraftDelete(id) {
  Confirm.ask({
    title: 'Delete draft?',
    body: 'This removes the in-progress draft. Published workflows are unaffected.',
    okLabel: 'Delete', danger: true,
  }).then(async (ok) => {
    if (!ok) return;
    await Net.call('/api/composer/drafts/' + encodeURIComponent(id),
      { silent: true, retries: 0, init: { method: 'DELETE' } });
    if (id === _dfActiveDraftId) {
      _dfActiveDraftId = null; _dfDraftDirty = false; _dfWalClear();
    }
    dfRefreshInProgress();
  });
}

function dfDraftNew() {
  // Release the current identity and start a blank canvas; the next real edit
  // mints a fresh draft_id at t0.
  _dfActiveDraftId = null; _dfDraftDirty = false; _dfWalClear();
  clearTimeout(_dfDraftFlushTimer);
  if (typeof switchTab === 'function') { try { switchTab('dashboard'); } catch (_) {} }
  if (typeof composerNewWorkflow === 'function') composerNewWorkflow();
  dfRefreshInProgress();
}

// Delegated actions for the In-Progress pane (data-action, no inline handlers).
Actions.click({
  'drafts.open':      el => dfDraftOpen(el.dataset.draftId),
  'drafts.rename':    el => dfDraftRename(el.dataset.draftId),
  'drafts.duplicate': el => dfDraftDuplicate(el.dataset.draftId),
  'drafts.delete':    el => dfDraftDelete(el.dataset.draftId),
  'drafts.new':       () => dfDraftNew(),
});

// Cross-module bridge (composer-view.js boot hook + composer-workstream.js
// pane switch call these as window globals). Direct window assignment mirrors
// the existing composerAddAgentAtCenter pattern — no legacy-bridge edit needed.
window.dfBootRestoreDraft = dfBootRestoreDraft;
window.dfRefreshInProgress = dfRefreshInProgress;

// Flush the WAL synchronously before the tab closes so a reload never loses the
// last few seconds of edits (the server flush is debounced; the WAL is not).
if (!window._dfDraftUnloadBound) {
  window._dfDraftUnloadBound = true;
  window.addEventListener('beforeunload', (e) => {
    let dirty = false;
    try {
      dirty = !!_dfDraftDirty;
      if (_dfActiveDraftId && _dfDraftDirty) {
        const snap = dfBuildSnapshot();
        _dfWalWrite({
          draft_id: _dfActiveDraftId, name: _dfDraftName(),
          workflow_id: (_dfMetaField('df-wf-id') || '').trim() || null,
          step_count: _dfRealStepCount(), blob: snap, updated_at: Date.now() / 1000,
        });
      }
    } catch (_) {}
    // CP-1c: power-user guard — if the canvas has unsaved edits, ask before
    // navigating away. The WAL flush above already persisted them to the draft
    // store (restore is lossless), so this is a belt-and-suspenders confirm,
    // not the last line of defense.
    if (dirty) { e.preventDefault(); e.returnValue = ''; return ''; }
  });
}

// ── Loop safety rails (kind:ralph / kind:loop) ──────────────────────
// "Safety rails" section for composite loop nodes: the ralph halt budget
// (RalphHalt caps + halt_file + goal_gate) or the loop termination fields
// (max_iterations + until.gate + on_max_iterations). Values are read
// straight from the pattern-preset blocks already sitting in dfNodeData
// (ralph.halt / until), and edits land back in the same nested objects so
// the composite serializer (_dfCleanStep) emits them unchanged.

// Lightweight client-side mirror of the evaluate_gate grammar in
// api/services/engine_executors/loop.py: dotted refs, bare names and
// literals combined with ==, !=, >, >=, <, <=, in, not in, and/or/not,
// unary +/- and list/tuple/set brackets. No calls, subscripts, or
// arithmetic — same whitelist the engine's AST walk enforces. Returns
// { ok } or { ok:false, hint } for the inline hint.
function dfValidateGateExpr(expr, required) {
  const src = String(expr || '').trim();
  if (!src) return required ? { ok: false, hint: 'kind:loop requires an until gate expression' } : { ok: true };
  const re = /\s*(?:(==|!=|>=|<=|>|<)|([()\[\]{},])|([+\-])|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\d+(?:\.\d+)?)|([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))/y;
  const toks = [];
  let i = 0;
  while (i < src.length) {
    re.lastIndex = i;
    const m = re.exec(src);
    if (!m) {
      const rest = src.slice(i).trim();
      if (!rest) break;
      return { ok: false, hint: `unexpected character "${rest[0]}" — only comparisons, and/or/not, in, literals and dotted refs` };
    }
    i = re.lastIndex;
    if (m[1]) toks.push({ t: 'cmp', v: m[1] });
    else if (m[2]) toks.push({ t: 'punct', v: m[2] });
    else if (m[3]) toks.push({ t: 'sign', v: m[3] });
    else if (m[4] || m[5]) toks.push({ t: 'val', v: m[4] || m[5] });
    else {
      const w = m[6];
      toks.push(w === 'and' || w === 'or' || w === 'in' || w === 'not' ? { t: w, v: w } : { t: 'val', v: w });
    }
  }
  const OPEN = { '(': ')', '[': ']', '{': '}' };
  const stack = [];
  let expectValue = true;
  for (let k = 0; k < toks.length; k++) {
    const tok = toks[k];
    if (expectValue) {
      if (tok.t === 'val') { expectValue = false; continue; }
      if (tok.t === 'not' || tok.t === 'sign') continue;
      if (tok.t === 'punct' && OPEN[tok.v]) { stack.push(OPEN[tok.v]); continue; }
      if (tok.t === 'punct' && (tok.v === ')' || tok.v === ']' || tok.v === '}')) {
        // empty collection literal, e.g. [] — only directly after its opener
        const prev = toks[k - 1];
        if (stack.length && stack[stack.length - 1] === tok.v && prev && prev.t === 'punct' && OPEN[prev.v] === tok.v) {
          stack.pop(); expectValue = false; continue;
        }
        return { ok: false, hint: 'unbalanced brackets' };
      }
      return { ok: false, hint: `expected a value before "${tok.v}"` };
    }
    // operator position (a value just completed)
    if (tok.t === 'cmp' || tok.t === 'and' || tok.t === 'or' || tok.t === 'in') { expectValue = true; continue; }
    if (tok.t === 'not') {
      if (toks[k + 1] && toks[k + 1].t === 'in') { k++; expectValue = true; continue; }
      return { ok: false, hint: '"not" after a value only works as "not in"' };
    }
    if (tok.t === 'sign') return { ok: false, hint: 'arithmetic operators are not allowed in a gate' };
    if (tok.t === 'punct') {
      if (tok.v === ',') {
        if (!stack.length) return { ok: false, hint: 'comma outside a list/tuple' };
        expectValue = true; continue;
      }
      if (tok.v === '(') return { ok: false, hint: 'function calls are not allowed in a gate' };
      if (tok.v === '[') return { ok: false, hint: 'subscripts are not allowed in a gate' };
      if (tok.v === '{') return { ok: false, hint: 'expected an operator before "{"' };
      if (stack.pop() !== tok.v) return { ok: false, hint: 'unbalanced brackets' };
      continue;
    }
    return { ok: false, hint: `expected an operator before "${tok.v}"` };
  }
  if (expectValue) return { ok: false, hint: 'expression is incomplete' };
  if (stack.length) return { ok: false, hint: 'unbalanced brackets' };
  return { ok: true };
}

// Section HTML for dfRenderConfigPanel — '' for every non-loop kind so
// the existing panel is untouched. Placeholders show the engine-model
// defaults (RalphHalt / AgentStep) when a preset value is absent.
function dfSafetyRailsHtml(nodeId, data) {
  if (data.kind !== 'ralph' && data.kind !== 'loop') return '';
  const num = (rail, label, val, ph) => `
    <div><label class="df-config-label">${label}</label>
      <input type="number" min="1" value="${val != null ? val : ''}" class="chat-input" style="font-size:0.66rem;padding:4px 8px" placeholder="${ph}"
        data-action="composer.ralph-rail-edit" data-rail="${rail}" /></div>`;
  const gate = (rail, label, val, required, note) => {
    const chk = dfValidateGateExpr(val, required);
    return `
    <div class="df-rail-gate" style="margin-top:6px">
      <label class="df-config-label">${label}</label>
      <input type="text" value="${esc(val || '')}" class="chat-input" style="font-size:0.66rem;padding:4px 8px" placeholder="verify.approved == True" spellcheck="false"
        data-action="composer.ralph-rail-edit" data-rail="${rail}" />
      <div class="df-rail-gate-hint" style="font-size:0.52rem;color:var(--red);margin-top:3px${chk.ok ? ';display:none' : ''}">${chk.ok ? '' : '⚠ ' + esc(chk.hint)}</div>
      <div style="font-size:0.5rem;color:var(--text-muted);margin-top:3px;letter-spacing:0.04em">${note}</div>
    </div>`;
  };
  let body;
  if (data.kind === 'ralph') {
    const halt = (data.ralph && data.ralph.halt) || {};
    body = `
        <div><label class="df-config-label">Halt file (host path)</label>
          <input type="text" value="${esc(halt.halt_file || '')}" class="chat-input" style="font-size:0.66rem;padding:4px 8px" placeholder="data/ralph/HALT"
            data-action="composer.ralph-rail-edit" data-rail="halt_file" /></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px">
          ${num('max_iterations', 'Max iterations', halt.max_iterations, '50')}
          ${num('max_wall_seconds', 'Max wall seconds', halt.max_wall_seconds, '28800')}
          ${num('max_total_tokens', 'Max total tokens', halt.max_total_tokens, '5000000')}
          ${num('max_consecutive_failures', 'Max consec. failures', halt.max_consecutive_failures, '3')}
        </div>
        ${gate('goal_gate', 'Goal gate', halt.goal_gate || '', false, 'Optional — empty runs to the hard caps. Dotted refs + ==, !=, &lt;, &gt;, in, and/or/not, e.g. <code>verify.approved == True</code>.')}
        <div style="font-size:0.5rem;color:var(--text-muted);margin-top:6px;letter-spacing:0.04em;line-height:1.5">
          The halt file stops the loop at the next <b>iteration boundary</b> — but only once the file is
          created on the <b>host</b> filesystem; nothing in this UI creates it. The live in-UI brake is
          ◼ Stop (<code>POST /api/workflows/runs/{run_id}/cancel</code>), which halts after the current step.
        </div>`;
  } else {
    const until = data.until || {};
    body = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
          ${num('max_iterations', 'Max iterations', data.max_iterations, '5')}
          <div><label class="df-config-label">On max iterations</label>
            <select class="model-select" style="font-size:0.66rem;padding:3px 6px;width:100%" data-action="composer.ralph-rail-edit" data-rail="on_max_iterations">
              <option value="emit_best"${(until.on_max_iterations || 'emit_best') === 'emit_best' ? ' selected' : ''}>emit_best</option>
              <option value="fail"${until.on_max_iterations === 'fail' ? ' selected' : ''}>fail</option>
            </select></div>
        </div>
        ${gate('gate', 'Until gate', until.gate || '', true, 'The loop repeats until this is true. Dotted refs + ==, !=, &lt;, &gt;, in, and/or/not, e.g. <code>critic.approved == True</code>.')}
        <div style="font-size:0.5rem;color:var(--text-muted);margin-top:6px;letter-spacing:0.04em;line-height:1.5">
          These rails fire at the next <b>iteration boundary</b>. The live in-UI brake is ◼ Stop
          (<code>POST /api/workflows/runs/{run_id}/cancel</code>), which halts after the current step.
        </div>`;
  }
  return `
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--amber,#e0b341);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Safety rails</div>${body}
      </div>`;
}

// Rail edits write into the nested ralph.halt / until blocks (creating
// them when a hand-built node lacks the preset), then route through
// dfUpdateNodeData for the usual canvas repaint + commit re-render.
// Gate fields additionally repaint their inline hint on every keystroke.
function dfRalphRailEdit(el, e) {
  const root = el.closest('[data-node-id]');
  const nodeId = root ? Number(root.dataset.nodeId) : NaN;
  const data = dfNodeData[nodeId];
  if (!data) return;
  const rail = el.dataset.rail;
  const opts = e && e.type === 'input' ? { live: true } : { commit: true };
  if (rail === 'goal_gate' || rail === 'gate') {
    const chk = dfValidateGateExpr(el.value, rail === 'gate');
    const box = el.closest('.df-rail-gate');
    const hint = box && box.querySelector('.df-rail-gate-hint');
    if (hint) {
      hint.style.display = chk.ok ? 'none' : 'block';
      hint.textContent = chk.ok ? '' : '⚠ ' + chk.hint;
    }
  }
  if (data.kind === 'ralph') {
    data.ralph = data.ralph || {};
    const halt = data.ralph.halt = data.ralph.halt || {};
    if (rail === 'halt_file' || rail === 'goal_gate') {
      const v = el.value.trim();
      if (v) halt[rail] = v; else delete halt[rail];  // both Optional on RalphHalt
    } else {
      const n = parseInt(el.value, 10);
      if (!Number.isFinite(n) || n < 1) return;  // keep the prior cap mid-edit
      halt[rail] = n;
    }
    dfUpdateNodeData(nodeId, 'ralph', data.ralph, opts);
  } else if (data.kind === 'loop') {
    if (rail === 'max_iterations') {
      const n = parseInt(el.value, 10);
      if (!Number.isFinite(n) || n < 1) return;
      dfUpdateNodeData(nodeId, 'max_iterations', n, opts);
    } else {
      const until = data.until = data.until || { type: 'gate', gate: '' };
      if (rail === 'gate') until.gate = el.value.trim();
      else if (rail === 'on_max_iterations') until.on_max_iterations = el.value;
      dfUpdateNodeData(nodeId, 'until', until, opts);
    }
  }
}
Actions.input({ 'composer.ralph-rail-edit': dfRalphRailEdit });
Actions.change({ 'composer.ralph-rail-edit': dfRalphRailEdit });

// ── BU8b: Loop wrap ─────────────────────────────────────────────────
// Toolbar affordance: wrap the CURRENT canvas workflow into a kind:ralph
// autonomous loop. Every real top-level step (sub-DAG proxies fold into
// their composite parent via _dfCleanStep, never duplicated) becomes a
// body step of ONE new ralph parent — the same nested-body semantics the
// BU4 ralph scaffold spawns — pre-filled with the preset journal_path +
// the active budget-preset halt caps, then the parent's Safety rails
// config (BU8a) opens so the operator immediately sees the budgets.
// goal_gate is deliberately NOT pre-filled: the wrapped body has no
// verify step to reference, so the operator declares one in the rails.
// (Schedule/recurring-cron is CUT from v1 — no host-side scheduler
// backend exists; see the composer revamp design spec.)
async function dfLoopWrapWorkflow() {
  if (!dfEditor) return;
  let home = {};
  try { home = dfEditor.export().drawflow.Home.data || {}; } catch (_) { return; }
  // Real steps only — the seed survives the wrap (it feeds the loop), and
  // proxies serialize inside their composite parent, never as body steps.
  const topIds = Object.keys(dfNodeData).map(Number).filter(nid => {
    const d = dfNodeData[nid];
    return d && !d.is_seed && d._sub_of == null;
  });
  if (!topIds.length) {
    Toast.warn('Add steps first', 'Loop wrap needs at least one step on the canvas.');
    return;
  }
  const ok = await Confirm.ask({
    title: 'Wrap in Ralph loop',
    body: `Restructure the canvas: the current ${topIds.length} step${topIds.length === 1 ? '' : 's'} become the body of one autonomous ralph loop, repeated until a halt rail fires. Wiring is preserved inside the body; the loop's budgets open for review.`,
    okLabel: 'Wrap'
  });
  if (!ok) return;
  const tpl = dfPatternTemplates.find(t => t.key === 'ralph_loop');
  if (!tpl) return;
  // Body steps = the cleaned engine-schema dicts (built BEFORE any node
  // removal mutates dfNodeData), with the canvas edges preserved as
  // body-level depends_on — the ralph executor runs the body in list
  // order; the deps keep the wiring readable and re-drawable below.
  const body = topIds.map(nid => {
    const step = _dfCleanStep(dfNodeData[nid]);
    const deps = [];
    const info = home[nid];
    if (info && info.inputs) Object.values(info.inputs).forEach(inp => (inp.connections || []).forEach(conn => {
      let src = dfNodeData[parseInt(conn.node)];
      if (src && src._sub_of != null) src = dfNodeData[src._sub_of];
      if (src && !src.is_seed && src.id !== step.id && !deps.includes(src.id)) deps.push(src.id);
    }));
    delete step.depends_on;                       // canvas edges are the truth
    if (deps.length) step.depends_on = deps;
    return step;
  });
  // Parent contract (frozen RalphSpec semantics): outputs come from the
  // body's terminal steps, so every declared output is produced by SOME
  // body step — the kind:ralph output invariant, by construction.
  const depended = new Set(body.flatMap(s => s.depends_on || []));
  const terminals = body.filter(s => !depended.has(s.id));
  let outputs = [...new Set(terminals.flatMap(s => s.outputs || []))];
  if (!outputs.length) outputs = [...new Set(body.flatMap(s => s.outputs || []))];
  const caps = (tpl.budget_presets && (tpl.budget_presets[dfRalphBudgetPreset] || tpl.budget_presets.standard)) || {};
  const presetRalph = (tpl.steps && tpl.steps[0] && tpl.steps[0].ralph) || {};
  const parent = {
    id: 'ralph_wrap_' + (++dfNextId),
    name: 'Ralph Loop',
    kind: 'ralph',
    inputs: [],   // the seed edge below re-pushes seed.* refs (dfOnConnectionCreated)
    outputs,
    ralph: {
      journal_path: presetRalph.journal_path || 'data/ralph/composer-journal.jsonl',
      halt: Object.assign({}, caps)
    },
    body
  };
  // Remove every wrapped node — their data now lives nested in parent.body.
  // Sub-DAG proxies go too (their parent's clean step already carries the
  // nested copy); only the seed pill stays on the canvas.
  Object.keys(dfNodeData).map(Number).forEach(nid => {
    const d = dfNodeData[nid];
    if (d && !d.is_seed) { try { dfEditor.removeNodeId('node-' + nid); } catch (_) {} }
  });
  // Spawn parent + body proxies with the scaffold's linkage: the proxies'
  // data objects ARE parent.body entries, so leaf edits serialize.
  const parentNid = dfAddPatternNode(_dfDecoratePatternNodeData(parent, tpl), 260, 160);
  dfAutoChain(parentNid);                         // seed (the only tail left) → parent
  const nidByStep = {};
  parent.body.forEach((c, i) => {
    nidByStep[c.id] = dfAddPatternNode(_dfDecoratePatternNodeData(c, tpl, parentNid, 'body'), 520 + i * 240, 340);
  });
  // Re-draw the original wiring inside the body: parent → root steps,
  // then each preserved depends_on edge between siblings.
  parent.body.forEach(c => {
    const deps = c.depends_on || [];
    if (!deps.length) {
      try { dfEditor.addConnection(parentNid, nidByStep[c.id], 'output_1', 'input_1'); } catch (_) {}
      return;
    }
    deps.forEach(d => {
      if (nidByStep[d] != null) { try { dfEditor.addConnection(nidByStep[d], nidByStep[c.id], 'output_1', 'input_1'); } catch (_) {} }
    });
  });
  dfSelectedNodeId = parentNid;
  dfRenderConfigPanel(parentNid);                 // renders the BU8a Safety rails section
  openStepConfigPopup();                          // guaranteed open, even when docked
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();
  Toast.success('Wrapped in Ralph loop', `${body.length} step${body.length === 1 ? '' : 's'} → loop body · budgets in Safety rails`);
}
Actions.click({ 'composer.loop-wrap': () => { dfLoopWrapWorkflow(); } });

/* ── BU8c: feasibility signal band ──────────────────────────────────
   Paints #composer-signal-band from GET /api/workflows/{id}/schedule-preview:
     green   — no feasibility_issues, no blocking notes
     red     — feasibility_issues present (steps that can't fit the arch)
     issue   — preview notes report deadlock / every-step-deferred
     unknown — computed LOCALLY: some run step in dfNodeData has no
               est_size_gb. The scheduler skips size-less steps, so a
               clean payload only earns green when sizes are declared —
               never fake green.
   Refreshed on demand (composer.schedule-preview-refresh) and after a
   successful dfSave(). The preview reads the SAVED yaml, so without a
   workflow id the band stays muted ("save to check feasibility"). */
function dfSignalBandPaint(state, text, title) {
  const band  = document.getElementById('composer-signal-band');
  const label = document.getElementById('composer-signal-text');
  if (!band || !label) return;
  band.dataset.state = state;
  label.textContent = text;
  band.title = title || text;
}

// True when any run step on the canvas lacks est_size_gb. Same set the
// scheduler's feasibility pass walks: top-level steps only — seed pills
// and sub-DAG proxies (their data nests inside the parent body) don't
// carry their own schedule slot.
function dfSignalBandSizesMissing() {
  return Object.keys(dfNodeData || {}).some(nid => {
    const d = dfNodeData[nid];
    if (!d || d.is_seed || d._sub_of != null) return false;
    return d.est_size_gb == null || d.est_size_gb === '';
  });
}

async function dfRefreshSignalBand() {
  const wfId = (document.getElementById('df-wf-id') || {}).value;
  if (!wfId) { dfSignalBandPaint('unsaved', 'save to check feasibility'); return; }
  dfSignalBandPaint('checking', 'checking feasibility…');
  const resp = await Net.call(
    '/api/workflows/' + encodeURIComponent(wfId) + '/schedule-preview',
    { retries: 0, silent: true }
  );
  if (!resp.ok) {
    // 404 = nothing saved under this id yet; anything else = preview down.
    if (resp.status === 404) dfSignalBandPaint('unsaved', 'save to check feasibility');
    else dfSignalBandPaint('issue', 'preview unavailable', String(resp.error || ('HTTP ' + resp.status)));
    return;
  }
  const p      = resp.data || {};
  const issues = p.feasibility_issues || [];
  const notes  = p.notes || [];
  if (issues.length) {
    const items = issues.map(i =>
      i.step_id + ': ' + (i.reason || (i.est_size_gb + ' GB > ' + i.arch_budget_gb + ' GB budget')));
    dfSignalBandPaint('red', 'infeasible — ' + items.join(' · '), items.join('\n'));
    return;
  }
  if (notes.length) {
    dfSignalBandPaint('issue', 'issue — ' + notes.join(' · '), notes.join('\n'));
    return;
  }
  if (dfSignalBandSizesMissing()) {
    dfSignalBandPaint('unknown', 'unknown — set model sizes for a real feasibility check',
      'The preview reports no issues, but steps without est_size_gb are skipped — this is not a real green.');
    return;
  }
  const ticks = (p.ticks || []).length;
  dfSignalBandPaint('green',
    'feasible on ' + (p.arch_name || 'this arch') + ' · ' + ticks + ' tick' + (ticks === 1 ? '' : 's'));
}
Actions.click({ 'composer.schedule-preview-refresh': () => { dfRefreshSignalBand(); } });

/* ── BU8d: guidance — starter suggestions + best-practice card ──────
   Three affordances for the new operator:
     (a) pattern-card tooltips — title attrs already render from
         dfPatternTemplates desc in dfInitPatterns;
     (b) "suggest a starter" — a compact chooser (empty-state CTA + a
         toolbar button share one Actions registration) whose pick
         instantiates a COMPLETE runnable shape in one click: seed with
         an example query + the pattern's full pre-wired scaffold.
         Reuses dfAddSeedNode + dfScaffoldPattern — no parallel
         scaffold logic;
     (c) a dismissible best-practice card in the left rail, rendered
         from the static dfWorkflowTips list, dismissal persisted to
         localStorage. */

// Starters pair a COMPLEX pattern with an example seed query. The
// scaffold topology, personas and halt/until presets all come from
// dfPatternTemplates — this list only adds the seed text.
const dfStarterWorkflows = [
  {
    pattern: 'ralph_loop',
    name: 'Ralph autonomous loop',
    example: 'Refactor the report module: split parsing, rendering and writing into separate functions, keeping behaviour identical.'
  },
  {
    pattern: 'tdd_loop',
    name: 'TDD-driven build',
    example: 'Write a Python function slugify(text) that lowercases, strips punctuation, and joins words with hyphens.'
  },
  {
    pattern: 'research_fanout',
    name: 'Research fan-out',
    example: 'What are the trade-offs between GGUF quantization levels (Q4_K_M vs Q5_K_M vs Q8_0) for local CPU inference?'
  }
];

// Static best-practice tips for the dismissible guidance card.
const dfWorkflowTips = [
  'Give ralph a goal_gate — without one, only the budget caps stop the loop.',
  'Cap max_iterations — every loop needs a worst-case budget.',
  "gather.outputs must equal the parent's outputs — the fan-out contract.",
  'The seed feeds step one — keep it editable and specific.'
];

// Chooser items render lazily on first open (dfPatternTemplates supplies
// the topology desc so the chooser copy can't drift from the cards).
function dfToggleStarterChooser(force) {
  const chooser = document.getElementById('df-starter-chooser');
  if (!chooser) return;
  const show = force != null ? force : chooser.hidden;
  if (show && !chooser.dataset.initialized) {
    chooser.dataset.initialized = '1';
    const list = document.getElementById('df-starter-chooser-list');
    if (list) list.innerHTML = dfStarterWorkflows.map(st => {
      const tpl = dfPatternTemplates.find(t => t.key === st.pattern) || {};
      return `<button type="button" class="df-starter-item" data-action="composer.starter-pick" data-starter="${esc(st.pattern)}"
          title="${esc(st.name)} — ${esc(tpl.desc || '')}">
        <span class="df-palette-label">${esc(st.name)}</span>
        <span class="df-pattern-desc">${esc(tpl.desc || '')}</span>
        <span class="df-starter-example">e.g. ${esc(st.example)}</span>
      </button>`;
    }).join('');
  }
  chooser.hidden = !show;
}

// One-click starter: the seed pill (stamped with the example query when
// the operator hasn't typed one) + the pattern's full best-practice
// scaffold. dfScaffoldPattern's dfAutoChain wires seed → scaffold head,
// so the result is a complete runnable shape — edit the seed, then Run.
function dfInstantiateStarter(patternKey) {
  const starter = dfStarterWorkflows.find(s => s.pattern === patternKey);
  if (!starter) return;
  dfInitEditor();  // idempotent — boots the canvas if it hasn't mounted yet
  if (!dfEditor) return;
  const seedNid = dfAddSeedNode(40, 200);  // exactly-once: reuses an existing seed
  const seed = seedNid != null ? dfNodeData[seedNid] : null;
  if (seed && !(seed.query || '').trim()) {
    dfUpdateNodeData(seedNid, 'query', starter.example);  // repaint the pill
  }
  dfScaffoldPattern(patternKey, 320, 200);
  try { ComposerView.updateCanvasEmptyState(); } catch (_) {}
  Toast.success('Starter ready', starter.name + ' — edit the seed query, then Run ▶');
}

// Best-practice card boot: render the tips once, then honor a persisted
// dismissal (card hidden, reopen chip shown) before first paint.
const DF_BP_DISMISS_KEY = 'enclave.composer.tipsDismissed';
function dfInitGuidance() {
  const card = document.getElementById('composer-bp-card');
  if (!card || card.dataset.initialized) return;
  card.dataset.initialized = '1';
  const list = document.getElementById('composer-bp-list');
  if (list) list.innerHTML = dfWorkflowTips.map(t => `<li>${esc(t)}</li>`).join('');
  let dismissed = false;
  try { dismissed = localStorage.getItem(DF_BP_DISMISS_KEY) === '1'; } catch (_) {}
  card.hidden = dismissed;
  const reopen = document.getElementById('composer-bp-reopen');
  if (reopen) reopen.hidden = !dismissed;
}

Actions.click({
  'composer.suggest-starter': () => dfToggleStarterChooser(),
  'composer.starter-pick': el => {
    dfToggleStarterChooser(false);
    dfInstantiateStarter(el.dataset.starter);
  },
  // One registration toggles both ways: the card's ✕ dismisses (persisted),
  // the reopen chip restores (dismissal cleared).
  'composer.best-practice': () => {
    const card = document.getElementById('composer-bp-card');
    if (!card) return;
    const dismiss = !card.hidden;
    card.hidden = dismiss;
    const reopen = document.getElementById('composer-bp-reopen');
    if (reopen) reopen.hidden = !dismiss;
    try {
      if (dismiss) localStorage.setItem(DF_BP_DISMISS_KEY, '1');
      else localStorage.removeItem(DF_BP_DISMISS_KEY);
    } catch (_) { /* localStorage disabled — session-only toggle */ }
  }
});

function dfRenderConfigPanel(nodeId) {
  const data = dfNodeData[nodeId];
  // Two target surfaces share one HTML body: the popup (primary, auto-
  // opens on node select) and the workstream tab (dock fallback).
  const panel = document.getElementById('df-config-panel');
  const popupBody = document.getElementById('df-config-popup-body');
  const popupTitle = document.getElementById('df-config-popup-title');
  const title = document.getElementById('df-config-title');
  if (!data || (!panel && !popupBody)) return;
  // CP-1a: keep the popup's "test in chat" control honest — visible only for
  // llm steps that the single-step test endpoint actually accepts.
  _composerSyncTestBtn(data);
  // Seed nodes get their own config surface (query + input schema) instead
  // of the step identity/prompt/gates form.
  if (data.is_seed) return dfRenderSeedConfig(nodeId);
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
        ${!(data.kind && data.kind !== 'llm') ? `<div style="margin-top:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px">
          <div><label class="df-config-label">Temperature</label>
            <input type="number" min="0" max="2" step="0.05"
              value="${data.temperature != null && data.temperature !== '' ? esc(String(data.temperature)) : ''}"
              placeholder="default" class="chat-input" style="font-size:0.68rem;padding:4px 8px"
              data-action="df.node-field" data-field="temperature"
              title="Per-step sampling temperature. Blank inherits the workflow default." /></div>
          <div><label class="df-config-label">Max tokens</label>
            <input type="number" min="1" step="128"
              value="${data.max_tokens != null && data.max_tokens !== '' ? esc(String(data.max_tokens)) : ''}"
              placeholder="default" class="chat-input" style="font-size:0.68rem;padding:4px 8px"
              data-action="df.node-field" data-field="max_tokens"
              title="Per-step max output tokens. Blank inherits the workflow default." /></div>
        </div>` : ''}
        ${data._from_agent ? `<div class="df-provenance-chip">forked from agent <code>${esc(data._from_agent)}</code></div>` : ''}
        ${data._from_prompt ? `<div class="df-provenance-chip">prompt <code>${esc(data._from_prompt)}</code></div>` : ''}
      </div>
      ${dfSafetyRailsHtml(nodeId, data)}
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Prompt</div>
        ${!(data.kind && data.kind !== 'llm') ? `<div style="display:flex;gap:4px;margin-bottom:6px">
          <select class="model-select" style="font-size:0.64rem;padding:3px 6px;width:100%"
                  data-action="prompt.pick-config"
                  title="Inline a saved prompt as this step's system prompt — a point-in-time snapshot, not a live reference.">
            <option value="">Attach a saved prompt…</option>
            ${(_benchPrompts || []).map(p => `<option value="${esc(p.kind + ':' + p.id)}">${esc(p.name || p.id)} · ${esc(p.kind)}</option>`).join('')}
          </select>
        </div>` : ''}
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
        <div style="display:flex;gap:4px;margin-bottom:8px"><input type="text" id="df-new-tool-${nodeId}" class="chat-input" style="font-size:0.64rem;padding:3px 6px" placeholder="plugin.tool or mcp:server.tool" data-action="df.add-tool-key" data-node-id="${nodeId}" /><button class="action-btn" style="font-size:0.56rem;padding:2px 8px" onclick="dfAddTool(${nodeId})">Add</button></div>
        <label class="df-config-label">Skills</label>
        <div id="df-skills-${nodeId}" style="display:flex;flex-wrap:wrap;gap:4px;margin:2px 0 6px">${(data.skills||[]).map((s,i)=>`<span class="df-tag">${esc(typeof s==='string'?s:(s.id||s.name||JSON.stringify(s)))}<span class="df-tag-remove" onclick="dfRemoveSkill(${nodeId},${i})">✕</span></span>`).join('') || '<span style="font-size:0.56rem;color:var(--text-faint)">none</span>'}</div>
        <div style="display:flex;gap:4px"><input type="text" id="df-new-skill-${nodeId}" class="chat-input" style="font-size:0.64rem;padding:3px 6px" placeholder="skill-id" data-action="df.add-skill-key" data-node-id="${nodeId}" /><button class="action-btn" style="font-size:0.56rem;padding:2px 8px" onclick="dfAddSkill(${nodeId})">Add</button></div>
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
  // DR-1: a committed step-config edit dirties the draft (live-edit ticks are
  // debounced by the flush timer, so per-keystroke marks are cheap).
  if (opts.commit) { try { dfMarkDraftDirty(); } catch (_) {} }

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
  const nodeField = (el, e) => {
    const nid = nodeIdOf(el);
    // PB-1 — a manual edit of the system prompt breaks the saved-prompt link,
    // so the provenance chip must not keep claiming the (now-diverged) source.
    if (el.dataset.field === 'system_prompt' && dfNodeData[nid] && dfNodeData[nid]._from_prompt) {
      delete dfNodeData[nid]._from_prompt;
    }
    dfUpdateNodeData(nid, el.dataset.field, el.value, fieldOpts(e));
  };
  const branch    = (el, e) => dfUpdateDecisionBranch(nodeIdOf(el), Number(el.dataset.idx), el.value, fieldOpts(e));
  Actions.input({ 'df.node-field': nodeField, 'df.branch': branch });
  Actions.change({
    'df.node-field': nodeField,
    'df.branch': branch,
    'df.node-set':    el => dfUpdateNodeData(nodeIdOf(el), el.dataset.field, el.value),
    'df.gate-update': el => dfUpdateGate(nodeIdOf(el), Number(el.dataset.idx), el.dataset.field, el.value),
    // PB-1 — node-config prompt picker: inline the chosen saved prompt via the
    // same dfAttachPromptToNode seam the bench drag uses; reset to placeholder.
    'prompt.pick-config': el => {
      const val = el.value;
      if (!val) return;
      dfAttachPromptToNode(nodeIdOf(el), val);
      el.value = '';
    }
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

// ── Seed config surface (dfRenderConfigPanel's is_seed branch) ──────
// Query textarea + key/description schema rows, written to the same two
// targets as the step form (popup primary, workstream dock fallback).
// Edits commit on "Save seed" (composer.seed-save) so mid-typing repaints
// can't steal focus; rows are DOM-only until saved.
function _dfSeedCfgRowHtml(key, desc, val) {
  // P0-6: each schema row carries a VALUE input so operators can supply the
  // seed value for a loaded workflow (dfRunWorkflowLive reads data.seed_values).
  return `<div class="df-seed-cfg-row" style="display:flex;gap:4px;margin-bottom:4px;align-items:center">
      <input type="text" class="chat-input df-seed-cfg-key" placeholder="query" value="${esc(key || '')}" style="font-size:0.64rem;padding:3px 6px;flex:0 0 92px" autocomplete="off" />
      <input type="text" class="chat-input df-seed-cfg-desc" placeholder="what this input is" value="${esc(desc || '')}" style="font-size:0.64rem;padding:3px 6px;flex:1" autocomplete="off" />
      <input type="text" class="chat-input df-seed-cfg-val" placeholder="value (optional)" value="${esc(val || '')}" style="font-size:0.64rem;padding:3px 6px;flex:0 0 120px" autocomplete="off" />
      <button type="button" class="btn-unstyled df-tag-remove" aria-label="Remove input" data-action="composer.seed-remove-key">✕</button>
    </div>`;
}

function dfRenderSeedConfig(nodeId) {
  const data = dfNodeData[nodeId];
  const panel = document.getElementById('df-config-panel');
  const popupBody = document.getElementById('df-config-popup-body');
  const popupTitle = document.getElementById('df-config-popup-title');
  const title = document.getElementById('df-config-title');
  if (!data || (!panel && !popupBody)) return;
  _composerSyncTestBtn(data);  // CP-1a: seed steps aren't testable in chat
  if (title) title.textContent = 'seed';
  if (popupTitle) popupTitle.textContent = 'Seed — workflow input';
  const vals = data.seed_values || {};
  const rows = ((data.seed_schema && data.seed_schema.length) ? data.seed_schema : [{ key: '', description: '' }])
    .map(s => _dfSeedCfgRowHtml(s.key, s.description, vals[s.key])).join('');
  const html = `
    <div style="display:flex;flex-direction:column;gap:0" data-node-id="${nodeId}">
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Query</div>
        <textarea class="chat-input df-seed-cfg-query" style="min-height:80px;font-size:0.66rem;resize:vertical"
          placeholder="What should this workflow do?">${esc(data.query || '')}</textarea>
      </div>
      <div style="padding:8px 0;border-bottom:1px solid var(--border)">
        <div style="font-size:0.56rem;color:var(--cyan);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;font-weight:600">Inputs <span style="color:var(--text-muted);letter-spacing:0.06em">(seed schema)</span></div>
        <div class="df-seed-cfg-rows">${rows}</div>
        <button class="action-btn" style="font-size:0.56rem;padding:2px 8px;margin-top:4px" data-action="composer.seed-add-key">+ Input</button>
        <div style="font-size:0.5rem;color:var(--text-muted);margin-top:6px;letter-spacing:0.04em">
          Steps reference these as <code style="color:var(--accent)">seed.&lt;key&gt;</code>; keys persist as the workflow's <code>context.inputs</code>. Values are supplied per run (not saved).
        </div>
      </div>
      <div style="padding:8px 0">
        <button class="action-btn accent" style="font-size:0.56rem;padding:2px 10px" data-action="composer.seed-save">Save seed</button>
      </div>
    </div>`;
  if (panel)     panel.innerHTML     = html;
  if (popupBody) popupBody.innerHTML = html;
  // Same auto-open contract as the step form.
  if (!window._stepConfigDocked) openStepConfigPopup();
}

// Commit the seed-config surface: query + schema rows → dfNodeData, with
// dfSeedSchema kept as the synced mirror (dfExportYaml + the DfSeedSchema
// modal read it). Also re-syncs seed.<key> refs on steps already wired from
// the seed so a renamed key can't strand stale inputs.
function dfSaveSeedConfig(nodeId, root) {
  const data = dfNodeData[nodeId];
  if (!data || !data.is_seed || !root) return;
  const q = root.querySelector('.df-seed-cfg-query');
  if (q) data.query = q.value;
  const schema = [];
  const seedValues = {};
  root.querySelectorAll('.df-seed-cfg-row').forEach(row => {
    const rawKey = (row.querySelector('.df-seed-cfg-key') || {}).value || '';
    const desc = (row.querySelector('.df-seed-cfg-desc') || {}).value || '';
    const val = (row.querySelector('.df-seed-cfg-val') || {}).value || '';
    // Same seed-ref-safe normalization the DfSeedSchema modal applies.
    const key = rawKey.trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
    if (key && !schema.some(s => s.key === key)) {
      schema.push({ key, description: desc.trim() });
      // P0-6: a supplied per-key VALUE feeds the run payload (dfRunWorkflowLive).
      if (val.trim()) seedValues[key] = val.trim();
    }
  });
  if (!schema.length) schema.push({ key: 'query', description: '' });
  data.seed_schema = schema;
  data.seed_values = seedValues;
  data.outputs = schema.map(s => s.key);
  dfSeedSchema = schema.map(s => ({ key: s.key, description: s.description }));
  try {
    const home = dfEditor.export().drawflow.Home.data;
    const outs = (home[nodeId] && home[nodeId].outputs) || {};
    Object.values(outs).forEach(out => (out.connections || []).forEach(c => {
      const to = dfNodeData[parseInt(c.node)];
      if (!to) return;
      to.inputs = (to.inputs || []).filter(ref => !(typeof ref === 'string' && ref.startsWith('seed.')));
      schema.forEach(s => { const ref = 'seed.' + s.key; if (!to.inputs.includes(ref)) to.inputs.push(ref); });
    }));
  } catch (_) {}
  dfUpdateNodeData(nodeId, 'query', data.query);  // repaint the canvas pill
  dfRenderSeedConfig(nodeId);
  if (!_dfAnchorBusy) dfScheduleAnchorRefresh();  // key chips feed the anchors
  if (window.Toast) Toast.success('Seed saved', schema.map(s => s.key).join(', '));
}

// Delegated actions: seed schema editing + the unified dblclick-to-edit.
// Node BODIES carry data-action="composer.edit-node" (dfNodeHtml and
// dfSeedNodeHtml alike); dblclick resolves the drawflow id from the node
// wrapper and opens the config surface for ALL nodes, seed included.
// Single-click nodeSelected behaviour is untouched (parity).
(function () {
  const rootOf = el => el.closest('[data-node-id]');
  Actions.on('dblclick', {
    'composer.edit-node': el => {
      const host = el.closest('.drawflow-node');
      if (!host) return;
      const nodeId = parseInt(String(host.id).replace('node-', ''), 10);
      if (isNaN(nodeId) || !dfNodeData[nodeId]) return;
      dfRenderConfigPanel(nodeId);
      openStepConfigPopup();  // guaranteed open, even when docked
    }
  });
  Actions.click({
    'composer.seed-add-key': el => {
      const root = rootOf(el);
      const rows = root && root.querySelector('.df-seed-cfg-rows');
      if (rows) rows.insertAdjacentHTML('beforeend', _dfSeedCfgRowHtml('', ''));
    },
    'composer.seed-remove-key': el => {
      const row = el.closest('.df-seed-cfg-row');
      if (row) row.remove();
    },
    'composer.seed-save': el => {
      const root = rootOf(el);
      if (root) dfSaveSeedConfig(Number(root.dataset.nodeId), root);
    }
  });
})();

function dfOnConnectionCreated(conn) {
  const fromId = parseInt(conn.output_id), toId = parseInt(conn.input_id);
  const from = dfNodeData[fromId], to = dfNodeData[toId];
  if (from && to) {
    // BU4 scaffold wiring: a composite parent's edge into its OWN sub-DAG
    // proxy is visual topology only — the nested steps already carry their
    // preset input refs, and a parent's outputs are never its children's
    // inputs. Sibling proxy edges (write→test, branch→gather) still push
    // refs and dedup against the preset via the includes() check below.
    if (to._sub_of != null && to._sub_of === fromId) return;
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
  // A REAL seed node supersedes the decorative __start__ ghost — it brackets
  // the flow itself. It never counts as a root/terminal step either (its
  // outputs are seed keys, not deliverables).
  const hasSeedNode = Object.keys(dfNodeData || {}).some(k => dfNodeData[k] && dfNodeData[k].is_seed);
  rootSteps = rootSteps.filter(s => !(s && s.is_seed));
  terminalSteps = terminalSteps.filter(s => !(s && s.is_seed));
  const deliverable = [...new Set(terminalSteps.flatMap(s => Array.isArray(s.outputs) ? s.outputs : []))];
  const keyChips = arr => (arr.length ? arr : ['—']).map(k => `<span>${esc(k)}</span>`).join('');
  try {
    if (!hasSeedNode) {
      // START carries an inline edit affordance → opens the seed-schema editor.
      const startHtml = `<div class="wf-anchor wf-anchor-start">`
        + `<div class="wf-anchor-label">▶ START`
        + `<span class="wf-anchor-edit" title="Edit the workflow's seed inputs" onclick="event.stopPropagation();DfSeedSchema.open()">✎</span>`
        + `</div>`
        + `<div class="wf-anchor-sub">seed input</div>`
        + `<div class="wf-anchor-keys">${keyChips(seedKeys)}</div></div>`;
      const startId = dfEditor.addNode('__start__', 0, 1, 40, 200, '__start__', {}, startHtml);
      rootSteps.forEach(s => { const t = idMap[s && s.id]; if (t != null) { try { dfEditor.addConnection(startId, t, 'output_1', 'input_1'); } catch (_) {} } });
    }
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
    // An empty compose canvas always carries the editable seed node
    // (idempotent — no-op when any node exists, so loads are untouched).
    try { dfEnsureSeedNode(); } catch (_) {}
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
      steps.push({ id: d.id, inputs: d.inputs || [], outputs: d.outputs || [], depends_on: deps, is_seed: !!d.is_seed });
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

// ── BU4: composite-kind serializer helpers ──────────────────────────
// Strip a canvas node's data down to the engine-schema step dict,
// recursively for body/branches/gather/workers. Emission is keyed off
// data.kind with cross-field exclusivity: only kind=llm may carry
// system_prompt/prompt at step level; kind=a2a never carries model/role
// (the remote agent owns both). UI decoration (persona, output_format,
// quality_gates, pattern provenance, _sub_* linkage) never leaks out.
function _dfCleanStep(src) {
  if (!src) return null;
  const kind = src.kind || 'llm';
  const out = { id: src.id, name: src.name || src.id };
  if (kind !== 'llm') out.kind = kind;
  if (kind !== 'a2a') {
    if (src.role) out.role = src.role;
    if (src.model) out.model = src.model;
  }
  if (kind === 'llm') {
    if (src.prompt) out.prompt = src.prompt;
    else if (src.system_prompt) out.system_prompt = src.system_prompt;
  }
  if (Array.isArray(src.inputs) && src.inputs.length) out.inputs = src.inputs.slice();
  out.outputs = (src.outputs || []).slice();
  if (Array.isArray(src.depends_on) && src.depends_on.length) out.depends_on = src.depends_on.slice();
  if (kind === 'parallel') {
    if (src.execution) out.execution = src.execution;
    out.branches = (src.branches || []).map(_dfCleanStep);
    if (src.gather) out.gather = _dfCleanStep(src.gather);
  }
  if (kind === 'loop') {
    out.body = (src.body || []).map(_dfCleanStep);
    if (src.until) out.until = src.until;
    if (src.max_iterations) out.max_iterations = src.max_iterations;
  }
  if (kind === 'ralph') {
    if (src.ralph) out.ralph = src.ralph;
    out.body = (src.body || []).map(_dfCleanStep);
  }
  if (kind === 'a2a') {
    if (src.agent_card_url) out.agent_card_url = src.agent_card_url;
    if (src.skill) out.skill = src.skill;
    if (src.auth) out.auth = src.auth;
    if (src.streaming) out.streaming = true;
    if (src.timeout) out.timeout = src.timeout;
  }
  if (kind === 'orchestrator') {
    if (src.planner) out.planner = src.planner;
    if (src.workers) {
      out.workers = {};
      Object.keys(src.workers).forEach(k => { out.workers[k] = _dfCleanStep(src.workers[k]); });
    }
    if (src.budget) out.budget = src.budget;
  }
  if (kind === 'consolidate' && src.consolidate) out.consolidate = src.consolidate;
  if (kind === 'code' && src.code) out.code = src.code;
  return out;
}

// One `- ` sequence item of `steps:` for a composite (kind != llm) node.
// jsyaml.dump handles the arbitrary nesting (ralph body, parallel
// branches/gather, orchestrator workers) far more safely than the
// hand-concatenated llm emitter in dfExportYaml.
function _dfCompositeStepYaml(data, deps) {
  const step = _dfCleanStep(data);
  delete step.depends_on;                       // canvas edges are the truth
  if (deps && deps.length) step.depends_on = deps.slice();
  let dumped = '';
  try { dumped = jsyaml.dump(step, { indent: 2, lineWidth: 100, noRefs: true }); }
  catch (_) { dumped = JSON.stringify(step); }  // JSON is valid YAML flow
  const lines = dumped.replace(/\n+$/, '').split('\n');
  return '  - ' + lines[0] + '\n' + lines.slice(1).map(l => '    ' + l).join('\n') + '\n\n';
}

// Pure canvas → YAML string. NO panel side-effect (doesn't touch
// #df-yaml-panel / #df-yaml-output), so it's safe to call for a LIVE run
// build without flashing the export panel open. dfExportYaml() wraps this
// and adds the panel paint; dfBuildWorkflowDefinition() parses it back to a
// definition dict so a Run › live sends the CANVAS the operator is looking
// at, not a stale saved copy (P0-1). Returns undefined when the editor
// isn't up yet (mirrors the old dfExportYaml early-return contract).
function dfComposeYamlString() {
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
  // Persist the declared seed schema as context.inputs so the input contract
  // round-trips (read back in composerLoadById). The editable seed node's
  // schema wins when one is on the canvas; dfSeedSchema is its synced mirror
  // and still covers seed-less canvases (legacy load path).
  const seedNode = nodeIds.map(nid => dfNodeData[nid]).find(d => d && d.is_seed);
  const seedInputs = (seedNode && Array.isArray(seedNode.seed_schema) && seedNode.seed_schema.length)
    ? seedNode.seed_schema : dfSeedSchema;
  if (Array.isArray(seedInputs) && seedInputs.length) {
    yaml += `\ncontext:\n  inputs:\n`;
    seedInputs.forEach(s => {
      if (!s || !s.key) return;
      yaml += `    - key: ${s.key}\n`;
      if (s.description) yaml += `      description: "${String(s.description).replace(/"/g, '\\"')}"\n`;
    });
  }
  yaml += `\ndefaults:\n  role: ${wfRole}\n  temperature: 0.7\n  max_tokens: 4096\n  retries: 2\n  retry_delay: 5\n\nsteps:\n`;

  nodeIds.forEach(nid => {
    const data = dfNodeData[nid];
    if (!data) return;
    // The seed is not an engine step — it compiled to context.inputs above,
    // and its edges live on as the targets' seed.<key> input refs.
    if (data.is_seed) return;
    // Sub-DAG editing proxies (BU4 pattern scaffolds) serialize NESTED
    // inside their composite parent, never as top-level steps.
    if (data._sub_of != null) return;
    const nodeInfo = homeData[nid];
    const deps = [];
    // A seed source never becomes depends_on — the connection already
    // serialized as seed.<key> inputs (dfOnConnectionCreated). An edge from
    // a sub-DAG proxy resolves to its composite PARENT's id: nested step
    // outputs aren't addressable at the top level.
    if (nodeInfo.inputs) Object.values(nodeInfo.inputs).forEach(inp => (inp.connections||[]).forEach(conn => {
      let src = dfNodeData[parseInt(conn.node)];
      if (src && src._sub_of != null) src = dfNodeData[src._sub_of];
      if (src && !src.is_seed && !deps.includes(src.id) && src.id !== data.id) deps.push(src.id);
    }));
    // Composite kinds (BU4) emit via the kind-keyed serializer: per-kind
    // config blocks, never a step-level prompt.
    if (data.kind && data.kind !== 'llm') {
      yaml += _dfCompositeStepYaml(data, deps);
      return;
    }
    yaml += `  - id: ${data.id}\n    name: "${data.name}"\n    role: ${data.role}\n`;
    // P0-4: a per-step model pin (data.model) must survive save→reload. The
    // engine reads AgentStep.model directly; emitting it keeps the pin from
    // silently collapsing back to the role-based resolver on the next load.
    if (data.model) yaml += `    model: ${data.model}\n`;
    yaml += `    system_prompt: |\n`;
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
    // P0-4: per-step sampling overrides ride in StepConfig — the engine reads
    // step.config.temperature/max_tokens and falls back to the workflow
    // defaults when unset. Emit only the fields the operator actually pinned so
    // an untouched step keeps inheriting the defaults (and round-trips clean).
    const _tRaw = data.temperature, _mRaw = data.max_tokens;
    const _t = (_tRaw === '' || _tRaw == null) ? null : Number(_tRaw);
    const _m = (_mRaw === '' || _mRaw == null) ? null : Number(_mRaw);
    const _hasT = _t != null && !Number.isNaN(_t);
    const _hasM = _m != null && !Number.isNaN(_m);
    if (_hasT || _hasM) {
      yaml += `    config:\n`;
      if (_hasT) yaml += `      temperature: ${_t}\n`;
      if (_hasM) yaml += `      max_tokens: ${_m}\n`;
    }
    yaml += `\n`;
  });

  return yaml;
}

// Back-compat wrapper: the historical Export-YAML button + every existing
// caller expects the panel to paint. Compose the string, then apply the
// side-effect. Returns the same yaml string as before.
function dfExportYaml() {
  const yaml = dfComposeYamlString();
  if (yaml == null) return yaml;
  const panel = document.getElementById('df-yaml-panel');
  const out = document.getElementById('df-yaml-output');
  if (panel) panel.style.display = 'block';
  if (out) out.textContent = yaml;
  return yaml;
}

// Live-canvas definition dict for Run › live (P0-1). Parses the side-effect-
// free YAML string so the run payload is the canvas exactly as it stands —
// no save required. Returns null when the canvas can't compose (no editor).
function dfBuildWorkflowDefinition() {
  const yaml = dfComposeYamlString();
  if (!yaml) return null;
  return jsyaml.load(yaml);
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
      // CP-1b: mark that THIS operator has authored + saved a workflow from the
      // console. The op-path "Save the workflow" stage reads this flag instead
      // of "any workflow exists on disk" — a fresh install ships OOB workflows,
      // so the disk check gave a false ✓ on a virgin install.
      try { localStorage.setItem('enclave.authoredWorkflow', '1'); } catch (_) {}
      // CH-1: chain forward — a saved workflow's natural next hops are run + schedule.
      try {
        NextActions.render('save.ok', {
          workflowId: result.workflow_id || (definition && definition.id) || '',
        });
      } catch (_) {}
      if (typeof refreshWorkflows === 'function') refreshWorkflows();
      // BU8c: the saved yaml is what schedule-preview reads — re-check.
      try { dfRefreshSignalBand(); } catch (_) {}
      // DR-1: publish collapses the draft identity into the saved workflow_id.
      // Freeze/delete the draft so there is no dual mutable identity.
      try { await dfPublishFreezeDraft(result.workflow_id || (definition && definition.id)); } catch (_) {}
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
// MS-5: the Agents tab is migrated onto the LibraryShell (AgentsPanel adapter
// in library/agents.js). The chat lifecycle below is REUSED verbatim against
// the same element ids, but the chat panel now lives in the shell's detail
// `chat` slot — openAgentChat first focuses that slot (mounts the skeleton)
// then populates it. A pending-starter latch carries a starter chip click
// through the async populate without racing the greeting.
let _activeAgentId = null;
let _agentHistory = [];
let _pendingStarter = null;

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
    // MS-5: the chat slot lives in the shell detail pane — focus it first so
    // the panel skeleton (below) exists to repaint into.
    try { AgentsPanel.focusChat(_activeAgentId); } catch (_) {}
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

// MS-5: the Agents tab is the LibraryShell now — loadAgentsTab delegates to
// the AgentsPanel adapter (list rows + subnav detail) and then restores any
// persisted chat into the detail chat slot.
async function loadAgentsTab() {
  try {
    await AgentsPanel.load();
  } catch (_) { /* the shell renders its own error panel */ }
  _restoreAgentChat();
}

async function openAgentChat(agentId) {
  // Bring the shell to this agent's Chat slot so the panel skeleton exists,
  // THEN populate it. The slot is a static STRING section, so focusChat mounts
  // it SYNCHRONOUSLY — #agent-chat-panel is in the DOM the instant this
  // returns (no recursion: the slot renderer never calls back here).
  try { AgentsPanel.focusChat(agentId); } catch (_) {}
  if (!document.getElementById('agent-chat-panel')) return;
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
      Chat with <strong style="color:var(--accent)">${esc(agent.name)}</strong> — type a message below
    </div>`;
  document.getElementById('agent-chat-panel').style.display = 'block';
  document.getElementById('agent-chat-input').focus();
  // A starter chip click latched _pendingStarter — send it now that the
  // greeting is painted (avoids clobbering the sent message).
  if (_pendingStarter) {
    const s = _pendingStarter;
    _pendingStarter = null;
    const inp = document.getElementById('agent-chat-input');
    if (inp) { inp.value = s; sendAgentMessage(); }
  }
}

function openAgentChatWithStarter(agentId, starter) {
  // Latch the starter; openAgentChat consumes it after the greeting renders.
  _pendingStarter = starter;
  openAgentChat(agentId);
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
    // GP-2 commit 5: keep the composer's #agent-select fork dropdown in sync —
    // a deleted agent must not linger as a selectable fork source.
    try { loadAgentsForSelector(); } catch (_) {}
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
    // GP-2 commit 5: refresh the composer's #agent-select so a create/rename
    // is immediately available (and a stale label is dropped) as a fork source.
    try { loadAgentsForSelector(); } catch (_) {}
  } catch(e) {
    showErr('Request failed: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = isEdit ? 'Save changes' : 'Create agent'; }
  }
}

// ── AdminMenu ─────────────────────────────────────────────────────────────

// ── AdminAuth ─────────────────────────────────────────────────────────────
// Persists the operator's license key in localStorage so it survives
// reloads and tab close. Legacy installs that stored under the old
// sessionStorage key are migrated forward on first read.

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

// Delegated actions for the workstream Active Run pane — its head row is
// re-rendered on every poll tick during live runs.
Actions.click({
  'ws.clear-run':    () => ComposerWorkstream.clearRun(),
  'ws.run-collapse': () => ComposerWorkstream.toggleRunCollapse(),
  // BU6 — the 4th (Logs) workstream tab is Actions-wired; the legacy
  // three tabs keep their inline onclicks as pre-existing debt.
  'ws.switch':            el => ComposerWorkstream.switch(el.dataset.wsTarget || 'logs', el),
  // Per-step Input/Output expanders inside the Logs pane.
  'wslogs.output-toggle': el => ComposerWorkstream.toggleLogExpand(el),
  // BU7 — signal chips: focus the offending step's config. Issues whose
  // source is an unresolved seed.<key> input carry data-seed="1" and
  // route to the SEED node's config instead.
  'logs.focus-step':      el => dfFocusStepFromSignal(el.dataset.stepId, el.dataset.seed === '1')
});

// ── CH-1: iteration-chaining pivots ───────────────────────────────────────
// The floating run-progress chip re-opens the active run; the loaded-workflow
// last-run chip opens that workflow's scoped History; the NextActions strip's
// next.* chips are the "what next" hops. next.schedule/next.promote route to
// the Operate plane (U8 / U11+U14) — honest toasts until Operate builds them.
Actions.click({
  'composer.open-active-run': () => composerOpenActiveRun(),
  'ws.history-open': el => {
    const wfId = el.dataset.wfId || '';
    const runId = el.dataset.runId || '';
    switchTab('runs');
    setTimeout(() => {
      try {
        Promise.resolve(RunsTab.load()).then(() => { if (runId) RunsTab.select(runId); });
      } catch (_) {}
    }, 150);
  },
  // NextActions strip verbs. Chips carry data-run-id / data-wf-id / data-step-id.
  'next.fix-step': el => {
    const stepId = el.dataset.stepId || (NextActions.ctx() || {}).stepId || '';
    const wfId = el.dataset.wfId || (NextActions.ctx() || {}).workflowId || '';
    // Already on the canvas for the failed run — just focus the failing node.
    // If we're not on that workflow's canvas, load it first via the runs pivot.
    const onCanvas = stepId && dfFindNodeIdForStep(stepId) != null;
    if (onCanvas) { dfFocusStepFromSignal(stepId, false); switchTab('dashboard'); }
    else if (wfId && window.RunsTab) RunsTab.openInComposer(wfId, stepId);
    else if (stepId) { switchTab('dashboard'); setTimeout(() => dfFocusStepFromSignal(stepId, false), 200); }
  },
  'next.resume': el => {
    const runId = el.dataset.runId || (NextActions.ctx() || {}).runId || '';
    if (!runId) { if (window.Toast) Toast.warn('No run', 'No failed run to resume.'); return; }
    switchTab('runs');
    setTimeout(() => {
      try { Promise.resolve(RunsTab.load()).then(() => { RunsTab.select(runId); setTimeout(() => RunsTab.resumeCurrent(), 200); }); } catch (_) {}
    }, 150);
  },
  'next.run': () => dfRunWorkflowLive(),
  'next.save': () => dfSave(),
  'next.rerun': el => {
    const runId = el.dataset.runId || (NextActions.ctx() || {}).runId || '';
    if (runId) {
      switchTab('runs');
      setTimeout(() => { try { Promise.resolve(RunsTab.load()).then(() => { RunsTab.select(runId); setTimeout(() => RunsTab.rerunCurrent(), 200); }); } catch (_) {} }, 150);
    } else { dfRunWorkflowLive(); }
  },
  'next.review-gate': el => {
    const runId = el.dataset.runId || (NextActions.ctx() || {}).runId || '';
    switchTab('runs');
    if (runId) setTimeout(() => { try { Promise.resolve(RunsTab.load()).then(() => RunsTab.select(runId)); } catch (_) {} }, 150);
  },
  'next.schedule': () => {
    if (window.Toast) Toast.info('Scheduling', 'Recurring runs land with the Operate plane (scheduler, U8).');
  },
  'next.promote': () => {
    if (window.Toast) Toast.info('Promote', 'Promoting a run into a workspace lands with the Operate plane (U11 / U14).');
  },
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

// ── ExportsPanel ──────────────────────────────────────────────────────────

/* ══════════════════════════════════════════════════════════════════
   COMPOSER VIEW — the Composer is now the Dashboard. This module
   bootstraps the drawflow canvas, palette, workbenches, agent chat
   wiring, and the import/export-bundle plumbing.
   ══════════════════════════════════════════════════════════════════ */

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

/* ── CP-1c: composer-scoped power-user keys ──────────────────────────
   Active ONLY while the Composer (dashboard) tab is showing and focus is
   not in a text field. The handler bails when another listener already
   consumed the event (defaultPrevented) — the cheap modal-stack guard so
   an open popup's own keys win. Bindings:
     1..7      → switch palette bench (Task/Agents/Skills/Plugins/MCPs/
                 Patterns/Prompts, the on-screen bench order)
     [  /  ]   → cycle the bottom workstream panes
     Ctrl/⌘-S  → save the workflow (fires regardless of focus; save is safe)
   The `g`-prefixed tab keymap + Cmd-K palette live in core/shortcuts.js
   (Operate U1 owns that map) and are intentionally NOT touched here. */
const _COMPOSER_BENCH_ORDER = ['steps', 'agents', 'skills', 'plugins', 'mcps', 'patterns', 'prompts'];
function _composerTabActive() {
  const t = document.getElementById('tab-dashboard');
  return !!(t && t.classList.contains('active'));
}
function _isTextField(el) {
  if (!el) return false;
  const tag = (el.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable;
}
function _composerCycleWorkstream(dir) {
  const tabs = [...document.querySelectorAll('.workstream-tab')].filter(b => b.offsetParent !== null);
  if (!tabs.length) return;
  let idx = tabs.findIndex(b => b.classList.contains('active'));
  if (idx < 0) idx = 0;
  const next = tabs[(idx + dir + tabs.length) % tabs.length];
  const target = next && (next.dataset.wsTarget || next.dataset.ws);
  if (target && window.ComposerWorkstream) ComposerWorkstream.switch(target, next);
}
if (!window._composerKeysBound) {
  window._composerKeysBound = true;
  document.addEventListener('keydown', (e) => {
    // Ctrl/⌘-S — save from anywhere on the composer.
    if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
      if (_composerTabActive()) { e.preventDefault(); try { dfSave(); } catch (_) {} }
      return;
    }
    if (e.defaultPrevented) return;                       // modal-stack guard
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (!_composerTabActive() || _isTextField(e.target)) return;
    if (e.key >= '1' && e.key <= '7') {
      const bench = _COMPOSER_BENCH_ORDER[Number(e.key) - 1];
      if (bench) { e.preventDefault(); composerSwitchBench(bench); }
      return;
    }
    if (e.key === '[') { e.preventDefault(); _composerCycleWorkstream(-1); return; }
    if (e.key === ']') { e.preventDefault(); _composerCycleWorkstream(1); return; }
  });
}

// CP-1c: migrated the tool/skill add-inputs' inline onkeydown (Enter → add)
// to delegated data-action keydown handlers — no inline on* in the config
// panel template. The Add buttons keep their onclick (pre-existing debt).
Actions.on('keydown', {
  'df.add-tool-key':  (el, e) => { if (e.key === 'Enter') { e.preventDefault(); dfAddTool(Number(el.dataset.nodeId)); } },
  'df.add-skill-key': (el, e) => { if (e.key === 'Enter') { e.preventDefault(); dfAddSkill(Number(el.dataset.nodeId)); } },
});

/* ── Workbench loaders ──────────────────────────────────────────── */

// BU5 — bench inspection caches. The polymorphic bottom inspector needs
// the RESOLVED objects behind the bench cards; loadWorkbenches() fills
// these module-scoped caches and the hover/focus handlers further down
// resolve ids → objects here, handing the object to
// ComposerWorkstream.inspect*() — no cross-module state, no globals.
let _benchAgents = [];
// PB-1 — the Prompts bench cache. Holds the merged (oob+user) role/template
// summaries the 7th bench renders + drag-attaches; hooks are excluded (they
// are engine presets, not composable system prompts). The hover-inspector
// resolves cards back to these records in _benchCapResolve.
let _benchPrompts = [];
// Drag MIME for the Prompts bench (parity with SKILL_DRAG_MIME). Value is
// `<kind>:<id>`; the drop handler + node-config picker both key off it.
const PROMPT_DRAG_MIME = 'application/df-prompt';
const _benchCaps = { plugins: [], mcps: [] };

// CP-1a: an unauthenticated bench read returns 401 — show the "sign in via
// Admin" hint rather than a bare "HTTP 401" error string. Any other non-ok
// status stays an ErrorPanel-style message. One helper, five call sites.
function _renderWorkbenchStatus(id, status) {
  if (status === 401 || status === 403) renderWorkbenchAuthHint(id);
  else renderWorkbenchError(id, `HTTP ${status}`);
}

async function loadWorkbenches() {
  // Auth is handled globally by the monkey-patched window.fetch (installed
  // alongside the Auth module). Each pane fails independently so one
  // failing endpoint doesn't blank the whole sidebar.
  // CP-1a: paint a loading skeleton so the panes read as "working" rather
  // than "empty" during the fetch.
  try {
    ['bench-skills-list', 'bench-plugins-list', 'bench-mcps-list', 'bench-agents-list', 'bench-prompts-list']
      .forEach(id => { const el = document.getElementById(id); if (el && window.Skeleton) Skeleton.fill(el, 3); });
  } catch (_) {}

  // Plugins (powers both Skills and Plugins panes)
  try {
    const r = await Net.call('/api/plugins');
    if (r.ok) {
      const plugins = r.data;
      _benchCaps.plugins = plugins || [];  // BU5: inspector resolves cards here
      renderSkillsWorkbench(plugins);
      renderPluginsWorkbench(plugins);
    } else {
      _renderWorkbenchStatus('bench-skills-list', r.status);
      _renderWorkbenchStatus('bench-plugins-list', r.status);
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
      _benchCaps.mcps = servers || [];  // BU5: inspector resolves cards here
      renderMcpsWorkbench(servers);
    } else {
      _renderWorkbenchStatus('bench-mcps-list', r.status);
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
      _benchAgents = agents || [];  // BU5: inspector resolves cards here
      renderAgentsWorkbench(agents);
    } else {
      _renderWorkbenchStatus('bench-agents-list', r.status);
    }
  } catch (e) {
    renderWorkbenchError('bench-agents-list', e.message);
  }

  // Prompts (PB-1) — the saved role/template library. Reads are open (no
  // master key); hooks are filtered client-side. Populates the bench cards
  // AND the node-config prompt picker's option list (both read _benchPrompts).
  try {
    const r = await Net.call('/api/prompts');
    if (r.ok) {
      _benchPrompts = (r.data || []).filter(p => p && p.kind !== 'hook');
      renderPromptsWorkbench(_benchPrompts);
    } else {
      _renderWorkbenchStatus('bench-prompts-list', r.status);
    }
  } catch (e) {
    renderWorkbenchError('bench-prompts-list', e.message);
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
    prompt:     _S('<rect x="4" y="4" width="16" height="13" rx="2"/><path d="M8 9h8M8 12.5h5"/><path d="M8 17l-2.5 3v-3"/>'),
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
    prompt:      'accent',
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
  // opts: { iconKey, title, subtitle, pill, pillKind, drag, descId, body,
  //         inspect }
  // - drag: { mime, value } to make the card draggable, or null
  // - pillKind: '', 'warn', 'dim'
  // - inspect: { kind, id } — BU5 bottom-inspector hookup. Draggable cards
  //   keep data-action="bench.drag" (the inspect handlers piggyback on it);
  //   non-draggable cards get data-action="bench.inspect-cap" instead.
  const iconSvg = (window.AgentIcons ? AgentIcons.svg(opts.iconKey) : '');
  const tone    = (window.AgentIcons ? AgentIcons.tone(opts.iconKey) : 'accent');
  const draggable = opts.drag
    ? `draggable="true" data-action="bench.drag" data-drag-mime="${esc(opts.drag.mime)}" data-drag-value="${esc(opts.drag.value)}"`
    : '';
  const inspect = opts.inspect
    ? `${opts.drag ? '' : 'data-action="bench.inspect-cap"'} data-cap-kind="${esc(opts.inspect.kind)}" data-cap-id="${esc(opts.inspect.id)}"`
    : '';
  const pillCls = opts.pillKind ? `workbench-item-pill ${opts.pillKind}` : 'workbench-item-pill';
  return `<div class="workbench-item agent-card cap-card cap-${esc(opts.iconKey)}" ${draggable} ${inspect} ${opts.title ? `title="${esc(opts.titleAttr || opts.title)}"` : ''}>
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
  // LB3-U2 — the bench renders the SAME flattened records as the Skills
  // library shell (library/skills-data.js). Drag-attach payload unchanged:
  // mime application/df-skill, value <plugin>::<skill> (skillKey).
  const items = flattenSkills(plugins);
  if (!items.length) {
    el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">No skills yet. Drop a skill .md file into plugins/&lt;plugin&gt;/skills/.</div>';
    return;
  }
  el.innerHTML = items.map(it => {
    const key = skillKey(it.plugin_id, it.skill_id);
    const triggers = (it.triggers || []).map(t => t.keyword).filter(Boolean).slice(0, 3).join(', ');
    return _capCard({
      iconKey: 'skill',
      title: it.name,
      subtitle: it.description,
      pill: 'skill',
      drag: { mime: SKILL_DRAG_MIME, value: key },
      inspect: { kind: 'skill', id: key },
      titleAttr: 'Drag onto a step to attach this skill manually',
      body: `<div class="cap-card-foot">
        <code class="cap-card-id">${esc(key)}</code>
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
      inspect: { kind: 'plugin', id: p.id },
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
      inspect: { kind: 'mcp', id: s.id },
      body: toolRows,
    });
  }).join('');
}

// PB-1 — Prompts bench. Saved roles/templates render as draggable cap-cards
// sharing the agent-card grammar. Drag payload: mime application/df-prompt,
// value `<kind>:<id>` (e.g. `role:python_developer`). Dropping onto an LLM
// step inlines the RESOLVED prompt body into data.system_prompt as a
// point-in-time snapshot (dfAttachPromptToNode) — never a live role_ref.
function renderPromptsWorkbench(prompts) {
  const el = document.getElementById('bench-prompts-list');
  if (!el) return;
  if (!prompts || !prompts.length) {
    el.innerHTML = '<div class="model-empty" style="font-size:0.62rem">No saved prompts yet. Author one under Library → Prompts.</div>';
    return;
  }
  el.innerHTML = prompts.map(p => {
    const val = `${p.kind}:${p.id}`;
    const tok = p.token_estimate ? `<span class="cap-card-meta">~${esc(String(p.token_estimate))} tok</span>` : '';
    return _capCard({
      iconKey: 'prompt',
      title: p.name || p.id,
      subtitle: p.summary || '',
      pill: p.kind,
      pillKind: p.provenance === 'user' ? '' : 'dim',
      drag: { mime: PROMPT_DRAG_MIME, value: val },
      inspect: { kind: 'prompt', id: val },
      titleAttr: 'Drag onto an LLM step to inline this prompt as its system prompt',
      body: `<div class="cap-card-foot">
        <code class="cap-card-id">${esc(p.id)}</code>
        ${tok}
      </div>`,
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
    'bench.add-agent': benchDrag,  // agent cards: click adds, drag still works
    'bench.inspect-pattern': benchDrag  // PT-1 pattern cards: hover inspects, drag scaffolds
  });
  Actions.click({
    'bench.add-agent': el => composerAddAgentAtCenter(el.dataset.agentId),
    // Tab switcher for data-action-wired bench tabs (the legacy five keep
    // their inline onclicks; new benches wire through here).
    'bench.switch': el => composerSwitchBench(el.dataset.bench, el)
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

// ── BU5: polymorphic bottom inspector — bench hover/focus wiring ────
// Hover (or keyboard focus) on a bench card resolves the card back to
// its cached object (_benchAgents / _benchCaps above) and hands it to
// ComposerWorkstream.inspect*() for a read-only render in the bottom
// Step Config pane. Debounced on value-change so mouseover churn across
// a card's children doesn't repaint; click stays composerAddAgentAtCenter
// for agent cards (parity) and drag semantics are untouched everywhere.
let _benchInspectTimer = null;
let _benchInspectKey = '';
let _benchInspectGen = 0;

function _benchInspectDebounced(key, render) {
  // Inspection only makes sense while the Composer (tab-dashboard) is on
  // screen — _capCard markup is reused by the System page and must not
  // mutate the hidden workstream from there.
  const tab = document.getElementById('tab-dashboard');
  if (!tab || !tab.classList.contains('active')) return;
  // Value-change gate: mouseover re-fires for every child crossing — skip
  // while the same card's inspection is already painted. focusStep()
  // clears the data-inspect-kind stamp on node selection, re-arming this.
  const meta = document.getElementById('ws-step-meta');
  if (key === _benchInspectKey && meta && meta.hasAttribute('data-inspect-kind')) return;
  clearTimeout(_benchInspectTimer);
  const gen = ++_benchInspectGen;
  _benchInspectTimer = setTimeout(async () => {
    if (gen !== _benchInspectGen) return;  // superseded by a later hover / node click
    _benchInspectKey = key;
    try { await render(gen); } catch (_) { /* inspector is best-effort */ }
  }, 120);
}

// Agents list objects omit system_prompt/tools/context — enrich from the
// detail endpoint once per agent and merge back into the cache so the
// inspector can honor "model + tools + context" without refetching.
async function _benchAgentResolved(agentId) {
  const cached = _benchAgents.find(x => x.id === agentId);
  if (cached && cached._detail) return cached;
  try {
    const r = await Net.call(`/api/agents/${encodeURIComponent(agentId)}`, { silent: true });
    if (r.ok && r.data) {
      const full = Object.assign({}, cached || {}, r.data, { _detail: true });
      const idx = _benchAgents.findIndex(x => x.id === agentId);
      if (idx >= 0) _benchAgents[idx] = full; else _benchAgents.push(full);
      return full;
    }
  } catch (_) { /* fall through to the (thinner) list object */ }
  return cached || null;
}

// Resolve a hovered capability element to its cached object. Card-level
// data-cap-* attrs cover skill/plugin/MCP cards; the nested tool rows
// only carry a drag payload, so fall back to parsing the MIME + value.
function _benchCapResolve(el) {
  const kind = el.dataset.capKind;
  if (kind === 'plugin') {
    const p = _benchCaps.plugins.find(x => x.id === el.dataset.capId);
    return p ? { kind: 'plugin', plugin: p } : null;
  }
  if (kind === 'mcp') {
    const s = _benchCaps.mcps.find(x => x.id === el.dataset.capId);
    return s ? { kind: 'mcp', server: s } : null;
  }
  if (kind === 'prompt' || el.dataset.dragMime === PROMPT_DRAG_MIME) {
    const val = el.dataset.capId || el.dataset.dragValue || '';
    const p = _benchPrompts.find(x => `${x.kind}:${x.id}` === val);
    return p ? { kind: 'prompt', prompt: p } : null;
  }
  if (kind === 'skill' || el.dataset.dragMime === 'application/df-skill') {
    const [pluginId, skillId] = (el.dataset.capId || el.dataset.dragValue || '').split('::');
    const p = _benchCaps.plugins.find(x => x.id === pluginId);
    const s = p && (p.skills || []).find(x => x.id === skillId);
    return s ? { kind: 'skill', pluginId, skill: s } : null;
  }
  if (el.dataset.dragMime === 'application/df-tool') {
    const ref = el.dataset.dragValue || '';
    const cut = ref.indexOf('__');
    const p = _benchCaps.plugins.find(x => x.id === ref.slice(0, cut));
    const t = p && (p.tools || []).find(x => x.id === ref.slice(cut + 2));
    return t ? { kind: 'plugin', plugin: p, tool: t } : null;
  }
  if (el.dataset.dragMime === 'application/df-mcp') {
    const [serverId, toolName] = (el.dataset.dragValue || '').split('::');
    const s = _benchCaps.mcps.find(x => x.id === serverId);
    const t = s && (s.tools || []).find(x => x.name === toolName);
    return s ? { kind: 'mcp', server: s, tool: t || null } : null;
  }
  return null;
}

(function () {
  const inspectAgentCard = el => {
    const agentId = el.dataset.agentId;
    if (!agentId) return;
    _benchInspectDebounced('agent:' + agentId, async (gen) => {
      const a = await _benchAgentResolved(agentId);
      if (gen !== _benchInspectGen || !a) return;  // stale by the time the fetch landed
      ComposerWorkstream.inspectAgent(a);
    });
  };
  const inspectTemplateCard = el => {
    const tpl = dfStepTemplates.find(t => t.key === el.dataset.templateKey);
    if (!tpl) return;
    _benchInspectDebounced('template:' + tpl.key, () => ComposerWorkstream.inspectTemplate(tpl));
  };
  const inspectCapCard = el => {
    const cap = _benchCapResolve(el);
    if (!cap) return;  // e.g. a pattern card sharing bench.drag — not a capability
    const key = 'cap:' + (el.dataset.capId || el.dataset.dragValue || '');
    _benchInspectDebounced(key, () => ComposerWorkstream.inspectCapability(cap));
  };
  // LB6 — library task cards hover-inspect from the dfLibraryTemplates Map
  // (its OWN action id; the static bench.inspect-template handler is
  // untouched). Feeds the same ComposerWorkstream.inspectTemplate inspector.
  const inspectLibraryTaskCard = el => {
    const rec = TasksPanel.libraryTask(el.dataset.taskId);
    if (!rec) return;
    _benchInspectDebounced('libtask:' + rec.key, () => ComposerWorkstream.inspectTemplate(rec));
  };
  // PT-1 — pattern cards (statics + Library rows) drill down into a read-only
  // structure view painted into #df-config-panel (node-selection still wins).
  const inspectPatternCard = el => {
    const key = el.dataset.inspectKey || el.dataset.dragValue || el.dataset.pattern;
    const tpl = dfResolvePattern(key);
    if (!tpl) return;
    _benchInspectDebounced('pattern:' + key, () =>
      ComposerWorkstream.inspectPattern({
        title: tpl.name || tpl.key || key,
        html: dfRenderPatternStructure(tpl),
      }));
  };
  Actions.on('mouseover', {
    'bench.add-agent':       inspectAgentCard,   // hover inspects; click still adds (parity)
    'bench.inspect-template': inspectTemplateCard,
    'bench.inspect-library-task': inspectLibraryTaskCard,
    'bench.inspect-pattern': inspectPatternCard, // PT-1 pattern drill-down
    'bench.inspect-cap':     inspectCapCard,     // plugin / MCP cards (not draggable)
    'bench.drag':            inspectCapCard      // skill cards + nested tool rows
  });
  // tasks.send-to-composer lives here (needs the canvas internals) — the
  // click-to-add twin of the library-task drag path.
  Actions.click({
    'tasks.send-to-composer': el => dfSendTaskToComposer(el.dataset.id),
  });
  Actions.on('focusin', {
    'bench.add-agent': inspectAgentCard          // agent cards are tabbable (role=button)
  });
  Actions.click({
    // Cap cards have no click-to-add, so click also inspects (spec: +click).
    'bench.inspect-cap': inspectCapCard,
    'bench.drag':        inspectCapCard,
    // A single click on a canvas node must beat any lingering inspector
    // content. Selection CHANGES already repaint via nodeSelected; this
    // covers re-clicking the already-selected node (drawflow doesn't
    // re-fire nodeSelected) and cancels any in-flight inspect debounce.
    // Single-click selection behavior itself is untouched.
    'composer.edit-node': el => {
      _benchInspectGen++;
      clearTimeout(_benchInspectTimer);
      const meta = document.getElementById('ws-step-meta');
      if (!meta || !meta.hasAttribute('data-inspect-kind')) return;
      const host = el.closest('.drawflow-node');
      if (!host) return;
      const nodeId = parseInt(String(host.id).replace('node-', ''), 10);
      if (isNaN(nodeId) || !dfNodeData[nodeId]) return;
      dfRenderConfigPanel(nodeId);
      const data = dfNodeData[nodeId];
      ComposerWorkstream.focusStep((data && (data.id || data.name)) || nodeId);
    }
  });
})();

// ── Skills Discover ──────────────────────────────────────────────────────
// Skills Lab counterpart to the Models tab's HuggingFace discover. Backed
// by the curated catalog at /api/skills/discover; install drops the skill
// body into a chosen plugin and registers it in the manifest.

/* ── Drag-to-node handlers: attach a workbench item to a node ────── */
(function wireWorkbenchDropHandlers() {
  document.addEventListener('drop', (e) => {
    const canvas = document.getElementById('drawflow-canvas');
    if (!canvas || !canvas.contains(e.target)) return;
    const skillRef  = e.dataTransfer.getData('application/df-skill');
    const toolRef   = e.dataTransfer.getData('application/df-tool');
    const mcpRef    = e.dataTransfer.getData('application/df-mcp');
    const promptRef = e.dataTransfer.getData(PROMPT_DRAG_MIME);
    if (!skillRef && !toolRef && !mcpRef && !promptRef) return;
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
    // PB-1 — a saved prompt inlines into system_prompt (its own attach seam +
    // llm-only guard); it never touches skills/tools, so branch out early.
    if (promptRef) { dfAttachPromptToNode(nodeId, promptRef); return; }
    data.skills = data.skills || [];
    data.tools  = data.tools  || [];
    if (skillRef) { if (!data.skills.includes(skillRef)) data.skills.push(skillRef); }
    // P0-5: store tool refs in the CANONICAL dotted form ToolRef requires
    // (`<owner>.<member>`) so Save/Run don't 422 and every consumer + the YAML
    // emitter mcp branch read one representation. Plugin bench drags arrive as
    // `<plugin_id>__<tool_id>`; MCP drags as `<server_id>::<tool_name>` — both
    // previously stored non-dotted (plugin `pid__tid`, mcp `mcp__srv__tool`)
    // and 422'd on the very next Save.
    if (toolRef)  {
      const i = toolRef.indexOf('__');
      const ref = i >= 0 ? `${toolRef.slice(0, i)}.${toolRef.slice(i + 2)}` : toolRef;
      if (!data.tools.find(t => (typeof t === 'string' ? t : t.id) === ref)) data.tools.push(ref);
    }
    if (mcpRef)   {
      const [serverId, toolName] = mcpRef.split('::');
      const ref = `mcp:${serverId}.${toolName}`;
      if (!data.tools.find(t => (typeof t === 'string' ? t : t.id) === ref)) data.tools.push(ref);
    }
    // Re-render the canvas node so the newly attached skill/tool/MCP
    // shows up as a chip + refresh the config panel if it's open.
    if (typeof dfUpdateNodeData === 'function') {
      dfUpdateNodeData(nodeId, 'skills', data.skills, { commit: true });
    }
  }, true);
})();

// PB-1 — attach a saved prompt to a step as its system prompt.
// promptRef is `<kind>:<id>` (role/template). We inline the RESOLVED body as
// a point-in-time snapshot into data.system_prompt (identical to the Agents
// fork, which copies a.system_prompt) — NOT a live role_ref, so the step
// never re-resolves against the layered prompt library at run time and edits
// stay local. data._from_prompt records provenance for the config-panel chip;
// a manual textarea edit clears it (see the df.node-field handler). Guarded to
// LLM steps only: seed + composite (ralph/loop/parallel) nodes have no
// system-prompt slot, so a drop there toasts and bails. Shared by the bench
// drag-drop path AND the node-config prompt picker.
async function dfAttachPromptToNode(nodeId, promptRef) {
  const data = dfNodeData[nodeId];
  if (!data) return;
  // llm-only: seed nodes render their own config; composite kinds carry a
  // nested sub-DAG, not a prompt (mirror the is-pattern-composite test).
  if (data.is_seed || (data.kind && data.kind !== 'llm')) {
    Toast.warn('Prompts attach to LLM steps only',
      'Seed and composite (loop / parallel / ralph) steps have no system prompt.');
    return;
  }
  const sep = String(promptRef).indexOf(':');
  if (sep < 0) return;
  const kind = promptRef.slice(0, sep);
  const pid = promptRef.slice(sep + 1);
  if (kind === 'hook') {
    Toast.warn('Hooks are not system prompts', 'Attach a role or template instead.');
    return;
  }
  try {
    const r = await Net.call(`/api/prompts/${encodeURIComponent(kind)}/${encodeURIComponent(pid)}`);
    if (!r.ok) { Toast.danger(`Could not load prompt '${pid}'`, `HTTP ${r.status}`); return; }
    const body = (r.data && r.data.body) || '';
    data._from_prompt = `${kind}:${pid}`;
    // commit:true repaints the canvas card + (if selected) re-renders the
    // config panel, so the provenance chip + textarea reflect the snapshot.
    dfUpdateNodeData(nodeId, 'system_prompt', body, { commit: true });
    Toast.success('Prompt attached', `${pid} inlined as the system prompt for ${data.id}.`);
  } catch (e) {
    Toast.danger('Attach failed', e.message);
  }
}

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

// ── BootSequence ──────────────────────────────────────────────────────
// The flagship "Promote": hand a chat answer to the operator's LOCAL agents.
// Act 1 (affordance) lives in .msg-actions; this module owns Act 2 (the
// self-typing "compile log" plan card) and Act 3 (the reveal as the dormant
// spine ignites into a live DAG). It calls the local /api/composer endpoints
// to capture a spec + scaffold a definition, then primes the spine through the
// shared composerLoadDefinition() — the same path that loads a saved workflow.

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
  // DR-1: reset the draft identity so loading/scaffolding a different workflow
  // doesn't keep flushing to the previous draft_id. The next real edit mints a
  // fresh draft at t0. (Boot-restore + dfDraftOpen set the id AFTER their own
  // canvas rebuild, which does NOT route through here — so restore is safe.)
  if (!_dfRestoring) {
    _dfActiveDraftId = null; _dfDraftDirty = false;
    clearTimeout(_dfDraftFlushTimer);
  }
  ['df-wf-id', 'df-wf-name', 'df-wf-desc'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  const yamlPanel = document.getElementById('df-yaml-panel');
  if (yamlPanel) yamlPanel.style.display = 'none';
  // CH-1: a fresh/blank workflow must not inherit the previous workflow's run
  // overlay or its "what next" chips. Always stop any live poller; on an
  // explicit new/clear (NOT a mid-load rebuild) also tear down the run pane +
  // cancel a still-live run so nothing bleeds across workflows.
  try {
    if (window.ComposerWorkstream) {
      ComposerWorkstream.stopPolling();
      if (!_dfLoading && !_dfRestoring) ComposerWorkstream.clearRun();
    }
  } catch (_) {}
  try { NextActions.clear(); } catch (_) {}
  const lrChip = document.getElementById('composer-last-run-chip');
  if (lrChip) { lrChip.hidden = true; lrChip.innerHTML = ''; }
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
    // CH-1: round-trip pivot — surface the loaded workflow's last-run health
    // chip (opens its scoped History). Best-effort, read-only GET; a workflow
    // with no runs simply hides the chip.
    try { dfShowLastRunHealth(wfId); } catch (_) {}
  } catch (e) { Toast.danger('Load error', e.message); }
}

// CH-1: paint the last-run health chip for a loaded workflow. Reads the
// workflow-scoped run index (GET /api/workflows/{id}/runs) — the CH-1
// read-model seam — takes the newest run, and shows a status dot + a History
// button that opens the Runs tab scoped to that run. Read-only; no egress
// beyond this operator-initiated load. Silent no-op when the chip mount or
// the run index is unavailable.
async function dfShowLastRunHealth(wfId) {
  const chip = document.getElementById('composer-last-run-chip');
  if (!chip || !wfId) return;
  try {
    const r = await Net.call(
      `/api/workflows/${encodeURIComponent(wfId)}/runs?limit=1`,
      { silent: true, retries: 0 }
    );
    const runs = (r.ok && r.data && Array.isArray(r.data.runs)) ? r.data.runs : [];
    if (!runs.length) { chip.hidden = true; chip.innerHTML = ''; return; }
    const last = runs[0];
    const st = String(last.status || '').toLowerCase();
    const tone = st === 'completed' ? 'ok'
      : (st === 'failed' || st === 'error') ? 'fail'
      : (st === 'running' || st === 'queued') ? 'live' : 'neutral';
    chip.className = 'composer-last-run-chip ' + tone;
    chip.innerHTML =
      `<span class="lrc-dot" aria-hidden="true"></span>` +
      `<span class="lrc-label">last run: ${esc(st || '—')}</span>` +
      `<button type="button" class="lrc-history" data-action="ws.history-open"` +
      ` data-wf-id="${esc(wfId)}" data-run-id="${esc(last.run_id || '')}"` +
      ` title="Open run history for this workflow">History →</button>`;
    chip.hidden = false;
  } catch (_) { chip.hidden = true; chip.innerHTML = ''; }
}

// CH-1: reopen the active/last composer run from the floating progress chip.
// The run id survives a reload via localStorage (dfApplyRunState persists it),
// so clicking the chip after F5 re-attaches the live poller / re-opens the run
// in the Runs tab. Falls back to the last run summary when no live id is held.
function composerOpenActiveRun() {
  let runId = window._composerActiveRunId
    || (window._lastRunSummary && window._lastRunSummary.run_id) || '';
  if (!runId) {
    try { runId = localStorage.getItem('enclave.composer.activeRun') || ''; } catch (_) {}
  }
  if (!runId) {
    if (window.Toast) Toast.info('No active run', 'Start a run to watch it here.');
    return;
  }
  // Re-attach the live workstream poller (idempotent — it clears any prior
  // interval) so an in-flight run keeps updating; a terminal run just paints
  // its final state once.
  try {
    if (window.ComposerWorkstream) ComposerWorkstream.startPolling(runId);
  } catch (_) {}
}

// Load a workflow-definition OBJECT directly onto the canvas. Shared by
// composerLoadById's fetch path and the chat-led BootSequence scaffold, so a
// scaffolded plan primes the spine through exactly the same code that loads a
// saved workflow. Places step nodes, wires depends_on (or infers a linear
// chain), restores the seed schema, draws START/END anchors, and lays out.
function composerLoadDefinition(defn) {
  defn = defn || {};
  // DR-1: placing a SAVED definition's nodes must not auto-mint a draft — a
  // load is not an edit. The operator's first real change after load starts
  // the draft. (Manual bench composition does NOT route through here.)
  _dfLoading = true;
  // GP-1a (P0-2): composite step kinds (parallel/loop/ralph/orchestrator/…) now
  // HYDRATE into their wired sub-DAG on load (dfHydrateCompositeStep below), so
  // editing a saved/published composite is no longer a silent flatten — Save
  // re-serializes the nested body/branches/gather unchanged. (This retires the
  // Gate-C "Composite steps load flat" warning; the DR-1 first-edit path is now
  // safe for composites.)
  try {
    // Centralized reveal (S0): loading a definition is a canvas-intent
    // action, so the Composer tab takes the stage — and it must do so
    // BEFORE drawflow lays out nodes, so the canvas is visible + sized
    // (Pins.convert / BootSequence now arrive from the separate Chat tab,
    // where #tab-dashboard is display:none). Replaces the retired
    // ComposerSplit canvas-mode pivot at every caller.
    if (typeof switchTab === 'function') { try { switchTab('dashboard'); } catch (_) {} }
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
      const x = 80 + (i % 4) * 220;
      const y = 60 + Math.floor(i / 4) * 140;
      // GP-1a (P0-2): a composite kind rebuilds its wired sub-DAG (parent +
      // body/branch/gather/worker proxies) via the scaffold-inverse rather than
      // collapsing to one plain llm node. Deep-copy the step first so the
      // canvas owns its nested objects (the parent-data ⇄ child-proxy
      // shared-reference contract dfScaffoldPattern relies on), then register
      // only the parent in idMap — proxies are nested, never top-level deps.
      if (step && step.kind && step.kind !== 'llm') {
        const compNid = dfHydrateCompositeStep(JSON.parse(JSON.stringify(step)), x, y);
        if (compNid != null) idMap[step.id] = compNid;
        return;
      }
      const tmplKey = (step.role && dfStepTemplates.find(t => t.role === step.role)) ? step.role : 'custom';
      const tmpl = dfStepTemplates.find(t => t.key === tmplKey) || dfStepTemplates.find(t => t.key === 'custom');
      // No auto-chain on load — the definition's depends_on drives wiring.
      const nodeId = dfAddNodeFromTemplate(tmpl.key, x, y, { autoChain: false });
      if (nodeId != null) {
        const d = dfNodeData[nodeId];
        d.id = step.id || d.id;
        d.name = step.name || d.name;
        d.role = step.role || d.role;
        // P0-4: restore the per-step model pin + sampling overrides so a loaded
        // workflow round-trips them (they re-emit via the llm branch above).
        if (step.model) d.model = step.model;
        if (step.config && step.config.temperature != null) d.temperature = step.config.temperature;
        if (step.config && step.config.max_tokens != null) d.max_tokens = step.config.max_tokens;
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
    // P0-6: recreate a LIVE, editable seed node (not the decorative __start__
    // ghost) whenever the loaded workflow declares OR references seed inputs,
    // so the operator can supply per-key seed VALUES for a loaded workflow
    // (dfRenderSeedConfig grows value inputs; dfRunWorkflowLive reads them).
    // dfAddSeedNode inherits the just-restored dfSeedSchema; dfAddAnchors then
    // sees a real seed and skips __start__, drawing only END.
    try {
      const inferredSeed = allSteps.flatMap(s => (s.inputs || [])
        .filter(i => typeof i === 'string' && i.startsWith('seed.')).map(i => i.slice(5)));
      const haveKey = new Set((dfSeedSchema || []).map(s => s.key));
      inferredSeed.forEach(k => { if (k && !haveKey.has(k)) { dfSeedSchema.push({ key: k, description: '' }); haveKey.add(k); } });
      if (dfSeedSchema.length && typeof dfAddSeedNode === 'function' && dfFindSeedNodeId() == null) {
        dfAddSeedNode(40, 200);
      }
    } catch (_) {}
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
    // (The reveal happens at the top of this function — switchTab('dashboard')
    // before node spawn — replacing the old tail-end canvas-mode pivot.)
  } catch (e) { Toast.danger('Load error', e.message); }
  finally { _dfLoading = false; }  // DR-1: re-arm dirty-marking for real edits
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
  // The auto-spawned seed doesn't count as a step — a canvas holding only
  // the seed is still an empty workflow.
  const realStepCount = Object.keys(window.dfNodeData || {})
    .filter(k => !(window.dfNodeData[k] && window.dfNodeData[k].is_seed)).length;
  if (realStepCount === 0) {
    if (window.Toast) Toast.warn('Empty workflow', 'Add at least one step to the canvas before running.');
    return;
  }
  // CP-1b: zero-model preflight — a run needs at least one loaded chat model,
  // or every llm step fails at the engine. Fail early with a pull hint rather
  // than kicking off a run that's doomed to error on the first step.
  if (window._modelsFetched && !(window._chatModels && window._chatModels.length)) {
    if (window.Toast) Toast.warn('No models loaded', 'Pull a chat model first (e.g. `ollama pull llama3.2:3b`), then run.');
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
  // The canvas seed node's query feeds the run payload (primary schema key);
  // the #wf-seed textarea above stays working as the fallback/extra-keys path.
  try {
    const sd = Object.keys(dfNodeData || {}).map(k => dfNodeData[k]).find(d => d && d.is_seed);
    if (sd && (sd.query || '').trim()) {
      const primary = (sd.seed_schema && sd.seed_schema[0] && sd.seed_schema[0].key) || 'query';
      seed[primary] = sd.query.trim();
    }
    // P0-6: per-key seed VALUES the operator typed into the seed config override
    // the primary/query mapping and fill the rest of the declared schema.
    if (sd && sd.seed_values && typeof sd.seed_values === 'object') {
      Object.entries(sd.seed_values).forEach(([k, v]) => {
        if (k && v != null && String(v).trim() !== '') seed[k] = v;
      });
    }
  } catch (_) {}

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
  const okStop = await Confirm.ask({
    title: 'Stop this run?',
    body: 'The engine halts at the next step boundary; the in-flight step finishes first.',
    okLabel: 'Stop run', cancelLabel: 'Keep running', danger: true,
  });
  if (!okStop) return;
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
    // CH-1 round-trip pivot: open the current run's workflow on the canvas,
    // focused on the failing step, so the operator can fix → save → resume.
    'runs.open-in-composer': el => RunsTab.openInComposer(el.dataset.wfId || '', el.dataset.stepId || ''),
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

function renderWorkflowIndex() { WorkflowIndex && WorkflowIndex.refresh && document.getElementById('wfi-grid') && (function(){
  // Re-render with current cache by triggering a refresh of the chip filter.
  const ev = new Event('input');
  document.getElementById('wfi-search').dispatchEvent(ev);
})(); }

/* ══════════════════════════════════════════════════════════════════
   MCP ADMIN PANEL — register / inspect / test / invoke MCP servers.
   ══════════════════════════════════════════════════════════════════ */
// Export for the static-HTML onclick guard (`if(window.MCPPanel)MCPPanel.showCreate()`):
// without this the Catalog '+ Register' button is a silent no-op.
window.MCPPanel = MCPPanel;
window.PromptsLibrary = PromptsLibrary;

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

/* ══════════════════════════════════════════════════════════════════
   PROJECT BAR — projects are persistent groupings of workflows,
   agents, MCPs, plugins, documents, and chats. The bar appears at the
   top of the composer and lets you switch context + bundle export.
   ══════════════════════════════════════════════════════════════════ */

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

  // CP-1b: the "Save the workflow" stage is DONE only when this operator has
  // actually authored + saved one from the console (dfSave sets the flag) —
  // NOT merely because the install ships OOB workflows on disk (_async.wfs),
  // which gave every virgin install a false ✓.
  function authoredWf() { try { return localStorage.getItem('enclave.authoredWorkflow') === '1'; } catch (e) { return false; } }

  function computeState() {
    var seed = chatLen() > 0 || pinCount() > 0;
    var scaf = nodeCount() > 0;
    var st = [
      { done: seed,          locked: false },
      { done: scaf,          locked: !seed },
      { done: _async.runs,   locked: !scaf },
      { done: authoredWf(),  locked: !scaf },
      { done: false,         locked: true, future: true },
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
      // composerLoadDefinition switches to the Composer tab itself (S0
      // reveal-centralization) — the DAG lands on a visible canvas.
      if (typeof composerLoadDefinition === 'function') composerLoadDefinition(defn);
      else if (typeof switchTab === 'function') switchTab('dashboard');
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
  async function del(id) {
    var idx = threads.findIndex(function (x) { return x.id === id; });
    if (idx < 0) return;
    var ok = window.Confirm
      ? await Confirm.ask({ title: 'Delete this thread?', body: 'This cannot be undone.', okLabel: 'Delete', danger: true })
      : window.confirm('Delete this thread? This cannot be undone.');
    if (!ok) return;
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
    // GP-2 commit 5: /api/agents/generate returns an AgentGenerationResult
    // envelope {draft, warnings, ...} — the draft is the `.draft` field, NOT
    // the whole body. The old `st.draft = d` treated the envelope as the draft,
    // so st.draft.name / .system_prompt were undefined and the editor rendered
    // blank. Also honor res.ok: on a 4xx/5xx the body is an error object, not a
    // draft, so surface it instead of silently binding it as the draft.
    fetch('/api/agents/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: st.text, name_hint: st.name, role_hint: st.role, include_source_as_context: true }),
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
    })
      .then(function (res) {
        if (!res.ok) {
          var detail = (res.d && (res.d.detail || (res.d.error && res.d.error.message))) || ('HTTP ' + res.status);
          throw new Error(detail);
        }
        st.draft = (res.d && res.d.draft) || {};
        render();
      })
      .catch(function (e) { var body = document.getElementById('rc-body'); if (body) body.innerHTML = '<div class="rc-loading" style="color:var(--danger)">Generation failed: ' + _esc(String(e && e.message || e)) + '</div>'; });
  }
  function save() {
    if (!st.draft) return;
    var n = document.getElementById('rc-agent-name'); if (n && n.value.trim()) st.draft.name = n.value.trim();
    var p = document.getElementById('rc-prompt'); if (p) { st.draft.system_prompt = p.value; st.draft.prompt = p.value; }
    fetch('/api/agents/generate/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft: st.draft, overwrite: false }),
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
    })
      .then(function (res) {
        if (!res.ok) {
          var detail = (res.d && (res.d.detail || (res.d.error && res.d.error.message))) || ('HTTP ' + res.status);
          throw new Error(detail);
        }
        st.agentId = (res.d && res.d.agent_id) || (st.draft && st.draft.id); st.phase = 3; render();
        if (window.Toast) Toast.success('Agent saved', st.draft.name || st.name);
      })
      .catch(function (e) { if (window.Toast) Toast.danger('Save failed', String(e && e.message || e)); });
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
  NextActions,
  PatternsPanel,
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
  composerOpenActiveRun,
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
  dfAddPatternFromTemplate,
  dfAddSkill,
  dfAddTool,
  dfAttachPromptToNode,
  dfAutoChain,
  dfAutoLayout,
  dfBuildWorkflowDefinition,
  dfComposeYamlString,
  dfClearConfigPanel,
  dfDeleteNode,
  dfDetachSkill,
  dfDetachTool,
  dfDoImport,
  dfEditor,
  dfExportYaml,
  dfFetchCompanions,
  dfFindNodeIdForStep,
  dfFocusStepFromSignal,
  dfImportBundle,
  dfImportYaml,
  dfInitEditor,
  dfInitPalette,
  dfInitPatterns,
  dfNextId,
  dfNodeData,
  dfNodeHtml,
  dfOnConnectionCreated,
  dfOnConnectionRemoved,
  dfPatternTemplates,
  dfRefreshAnchors,
  dfRemoveGate,
  dfRemoveOutput,
  dfRemoveSkill,
  dfRemoveTool,
  dfRenderConfigPanel,
  dfRenderPatternStructure,
  dfResolvePattern,
  dfRunWorkflow,
  dfRunWorkflowFromComposer,
  dfRunWorkflowLive,
  dfSave,
  dfSaveCanvasAsPattern,
  dfShowLastRunHealth,
  dfScaffoldPattern,
  dfSendPatternToComposer,
  fetchComposerPatterns,
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
  renderPromptsWorkbench,
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
