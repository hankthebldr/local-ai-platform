// library/workflow-index.js — Workflows catalog (phase-2 U4 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, ErrorPanel, Skeleton } from '../core/ui.js';

export const WorkflowIndex = (function () {
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
