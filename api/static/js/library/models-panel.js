// library/models-panel.js — Models library master-detail panel (LB4-U2).
//
// #models-shell on tab-inventory is THE single visible models surface: the
// pre-shell catalog surface (#inv-stats/#inv-grid/.inv-toolbar + hardware
// panel) parks in the hidden #inv-legacy-holder (ids unchanged) so the
// Catalog-page relocation and the Admin Catalog keep binding (F2), while the
// Models tab renders grouped Installed / Available / Discovered rows via the
// LB0 row contract — fit dot (load-fit class straight from the /catalog fit
// payload), runner badge (ollama/vllm), task-tag chips. #inv-count is fed by
// the adapter's countBadgeId.
//
// Detail: Summary (with the inline tag editor → PATCH tags), Weights
// architecture (registry fields joined with the filtered model_info from
// GET /api/inventory/model/{name}; the vLLM/NVFP4 branch degrades to
// registry/catalog fields so the flagship view is never empty), Performance
// (per detected arch class from api/config/model_meta.json via /enrichment),
// Hardware fit (score + per-pool breakdown, labeled load-fit), Relations
// (workflows + agents), Recommended prompts (GET /api/prompts/recommend?model=
// with the per-factor breakdown + a LibraryShell.open jump into Prompts),
// and Test — the LB1 TestPane model adapter (Warm renders disabled-with-reason
// on vLLM-pinned runners).
//
// PRIVACY: adapter.load reads /api/inventory/catalog only. It NEVER touches
// /api/inventory/discover — that read path can still fetch when its cache is
// stale (pre-existing TTL-on-read, follow-up #15), so HF discovery data fills
// exclusively via the operator's visible ⟳ Discover button, which fires the
// master-key POST /api/inventory/discover/refresh first.
//
// Wiring: no inline handlers, no new window globals. models.select /
// edit-tags / intent / refresh-discover register here; models.pull / remove /
// review / test keep their main.js registrations (only-add — the legacy
// catalog grid still uses them) with a data-shell="models" branch routing
// shell-origin clicks to this panel. Mutating POSTs are retries:0; Remove is
// Confirm-gated.
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast, Confirm } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';
import { TestPane } from './test-pane.js';

export const ModelsPanel = (function () {
  let _models = [];        // /api/inventory/catalog models
  let _hardware = {};      // /api/inventory/catalog hardware block
  let _discovered = [];    // HF discovery rows — filled ONLY by ⟳ Discover
  let _discoveredAt = null;
  let _recRank = {};       // model id -> {rank, score} for the active intent
  let _intent = '';
  let _enrichment = null;  // /api/inventory/enrichment cache (benchmarks + model_meta)
  let _arch = null;        // /api/system/architecture cache
  let _detailCache = {};   // served name -> /api/inventory/model/{name} payload
  let _editingTags = false;
  let _mounted = false;
  let _pulling = null;     // served name currently pulling (one at a time)

  const DISC_PREFIX = 'hf::';

  function _headers() { return LibraryShell.headers('model'); }
  function _selected() { return (LibraryShell.state('model') || {}).selected; }
  function _item(id) { return _models.find(m => m.id === id) || null; }
  function _isDisc(id) { return !!id && id.indexOf(DISC_PREFIX) === 0; }
  function _discRecord(id) {
    const rid = (id || '').slice(DISC_PREFIX.length);
    return _discovered.find(d => d.repo_id === rid) || null;
  }
  function _servedName(m) { return m.ollama || m.id; }
  function _runner(m) {
    return m.runner || (m.installed_info && m.installed_info.backend) || 'ollama';
  }
  // {name:path} routes take raw slashes; encode per segment so ':' etc.
  // survive while '/' keeps its path meaning (nvidia/Qwen3-8B-NVFP4).
  function _pathName(name) {
    return String(name).split('/').map(encodeURIComponent).join('/');
  }
  function _oneLine(text, cap) {
    const t = String(text || '').replace(/\s+/g, ' ').trim();
    const max = cap || 96;
    return t.length > max ? t.slice(0, max - 1) + '…' : t;
  }
  function _fitTitle(fit) {
    const cls = String((fit && fit.class) || 'unknown');
    if (!fit || fit.required_gb == null || fit.budget_gb == null) return `load-fit: ${cls}`;
    return `load-fit: ${cls} — needs ~${fit.required_gb}GB of ${fit.budget_gb}GB (${fit.basis || 'detected budget'})`;
  }

  // ── Row builders (LB0 row contract) ──────────────────────────────────
  function _row(m) {
    const fit = m.fit || {};
    const cls = String(fit.class || 'unknown');
    const taskTags = m.task_tags || [];
    const chips = taskTags.slice(0, 3).map(t => ({ label: t }));
    if (taskTags.length > 3) chips.push({ label: `+${taskTags.length - 3}`, cls: 'more' });
    const badges = [{ label: _runner(m), cls: `models-runner runner-${esc(_runner(m))}` }];
    const rec = _recRank[m.id];
    if (rec) badges.push({ label: `★#${rec.rank} · ${rec.score}`, cls: 'models-rec-hit' });
    return {
      id: m.id,
      title: m.name,
      meta: `${m.size || '?'} · ctx ${m.context || '—'}`,
      group: m.installed ? 'Installed' : 'Available',
      provenance: (m.tags || []).includes('extra') ? 'user' : 'oob',
      blocks: ['model'],
      tags: (m.tags || []).concat(taskTags),
      // Fit dot — class comes STRAIGHT from the /catalog fit payload
      // (good/tight/no-fit/unknown), so the dot can never drift from it.
      dot: { cls: `fit-${esc(cls)}`, title: _fitTitle(fit) },
      chips,
      badges,
    };
  }

  function _discRow(d) {
    return {
      id: DISC_PREFIX + d.repo_id,
      title: d.name || d.repo_id,
      meta: `${d.estimated_size_gb ? `~${d.estimated_size_gb}GB` : '?'} · ${d.author || '?'}`,
      group: 'Discovered',
      provenance: 'user',
      blocks: ['model'],
      tags: (d.tags || []).concat(d.repo_id),
      badges: [
        { label: 'huggingface', cls: 'models-runner runner-hf' },
        ...(d.has_gguf ? [{ label: 'gguf', cls: 'models-gguf' }] : []),
      ],
    };
  }

  // ── LibraryShell adapter ─────────────────────────────────────────────
  const adapter = LibraryShell.register({
    kind: 'model',
    tabId: 'inventory',
    countBadgeId: 'inv-count',
    auth: 'optional',                 // reads open; writes carry merged AdminAuth headers
    selectAction: 'models.select',
    title: 'Models',
    emptyText: 'Catalog empty — is the API reachable?',
    emptyDetailLabel: '// SELECT A MODEL',
    emptyDetailText: 'Select a model on the left for weights architecture, performance expectations, hardware fit, relations, and recommended prompts — or run it in the Test tab.',
    // Spec section order: Summary, Weights, Performance, Hardware fit,
    // Relations, Recommended prompts (+ Test).
    sectionOrder: ['overview', 'weights', 'performance', 'fit', 'relations', 'prompts', 'test'],
    sectionLabels: {
      weights: 'Weights',
      performance: 'Performance',
      fit: 'Hardware fit',
      prompts: 'Recommended prompts',
    },

    async load() {
      // The tab's ONE inventory read (F2: no double fetch). Deliberately NO
      // discover-route read here — see the module header (follow-up #15).
      const r = await LibraryShell.fetch('model', '/api/inventory/catalog');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _models = (r.data && r.data.models) || [];
      _hardware = (r.data && r.data.hardware) || {};
      _detailCache = {};
    },

    list() {
      const rows = [];
      _models.filter(m => m.installed).forEach(m => rows.push(_row(m)));
      _models.filter(m => !m.installed).forEach(m => rows.push(_row(m)));
      _discovered.forEach(d => rows.push(_discRow(d)));
      return rows;
    },

    detail(id) {
      if (_isDisc(id)) {
        return { sections: { overview: (el) => _renderDiscOverview(el, id) } };
      }
      return {
        sections: {
          overview: (el) => _renderOverview(el, id),
          weights: (el) => _renderWeights(el, id),
          performance: (el) => _renderPerformance(el, id),
          fit: (el) => _renderFit(el, id),
          relations: (el) => _renderRelations(el, id),
          prompts: (el) => _renderPrompts(el, id),
        },
      };
    },

    // Test subnav slot — the LB1 TestPane model adapter. ctx.backend='vllm'
    // makes the Warm button render disabled-with-reason (pinned weights load
    // at server start), never a dead control on the flagship NVFP4 models.
    testPane(id) {
      return (el) => {
        if (_isDisc(id)) {
          el.innerHTML = '<div class="model-empty">Pull this model first — the tester runs installed models only.</div>';
          return;
        }
        const m = _item(id);
        if (!m) { el.innerHTML = '<div class="model-empty">Model not found — refresh.</div>'; return; }
        if (!m.installed) {
          el.innerHTML = '<div class="model-empty">Not installed — Pull it first, then run it here.</div>';
          return;
        }
        return TestPane.mount('model', _servedName(m), el, {
          backend: _runner(m) === 'vllm' ? 'vllm' : '',
        });
      };
    },

    actions(id) {
      if (_isDisc(id)) {
        const d = _discRecord(id);
        if (!d) return [];
        const acts = [];
        if (d.has_gguf) {
          acts.push({
            action: 'models.pull', label: 'Pull', verb: 'install', accent: true,
            data: { shell: 'models', model: 'hf.co/' + d.repo_id },
          });
        }
        acts.push({
          action: 'models.review', label: 'Review', verb: 'edit',
          data: { repo: d.repo_id },
        });
        return acts;
      }
      if (_editingTags) {
        return [
          { action: 'models.tags-save', label: 'Save tags', verb: 'edit', accent: true, data: { shell: 'models' } },
          { action: 'models.tags-cancel', label: 'Cancel', verb: 'edit', data: { shell: 'models' } },
        ];
      }
      const m = _item(id);
      if (!m) return [];
      const acts = [];
      if (m.installed) {
        acts.push({
          action: 'models.test', label: 'Test', verb: 'test', accent: true,
          data: { shell: 'models', model: _servedName(m) },
        });
      } else {
        const target = m.ollama || (m.gguf ? 'hf.co/' + m.gguf : '');
        acts.push({
          action: 'models.pull', label: _pulling === target ? 'Pulling…' : 'Pull',
          verb: 'install', accent: true, enabled: !!target && !_pulling,
          reason: !target ? 'no pullable source (registry entry has neither an Ollama tag nor a GGUF repo)'
            : (_pulling ? `already pulling ${_pulling}` : undefined),
          data: { shell: 'models', model: target, 'model-id': m.id },
        });
      }
      const repo = m.huggingface || m.gguf;
      if (repo) {
        acts.push({ action: 'models.review', label: 'Review', verb: 'edit', data: { repo } });
      }
      acts.push({ action: 'models.edit-tags', label: 'Edit tags', verb: 'edit', data: { shell: 'models' } });
      if (m.installed) {
        const vllm = _runner(m) === 'vllm';
        acts.push({
          action: 'models.remove', label: 'Remove', verb: 'delete', danger: true,
          enabled: !vllm,
          reason: vllm ? 'vLLM-served — weights are compose-managed, not Ollama-removable' : undefined,
          data: { shell: 'models', model: _servedName(m) },
        });
      }
      return acts;
    },
  });

  // ── Detail sections ───────────────────────────────────────────────────

  function _kvGrid(rows) {
    return `<div style="display:grid;grid-template-columns:110px 1fr;gap:6px 12px;font-size:0.72rem;margin-bottom:10px">
      ${rows.map(([k, v]) => `<div style="color:var(--text-muted)">${esc(k)}</div><div>${v}</div>`).join('')}
    </div>`;
  }

  function _tagChips(tags, cls) {
    return (tags || []).map(t => `<span class="${cls || 'lib-chip'}">${esc(t)}</span>`).join(' ')
      || '<span style="color:var(--text-muted)">—</span>';
  }

  function _renderOverview(el, id) {
    const m = _item(id);
    if (!m) { el.innerHTML = '<div class="model-empty">Model not found — refresh.</div>'; return; }
    const taskTags = m.task_tags || [];
    const tagsCell = _editingTags
      ? `<input type="text" id="models-tags-input" class="search-input" style="width:100%"
           aria-label="Task tags (comma-separated)" value="${esc(taskTags.join(', '))}"
           placeholder="fast_extract, code_gen, …">
         <div style="font-size:0.6rem;color:var(--text-muted);margin-top:3px">
           comma-separated · saved as operator overrides (data/config/model_tags.json) via PATCH — master-key gated</div>`
      : _tagChips(taskTags);
    el.innerHTML = _kvGrid([
      ['Model id', `<code>${esc(m.id)}</code>`],
      ['Served as', `<code>${esc(_servedName(m))}</code>`],
      ['Runner', `<span class="lib-badge models-runner runner-${esc(_runner(m))}">${esc(_runner(m))}</span>`],
      ['Size', esc(m.size || '?')],
      ['Speed', esc(typeof m.speed === 'string' ? m.speed : '—') + ' <span style="color:var(--text-muted)">(this hardware profile)</span>'],
      ['Context', esc(m.context || '—')],
      ['Tags', _tagChips(m.tags)],
      ['Task tags', tagsCell],
      ['Description', esc(m.description || '(none)')],
    ]);
  }

  // Weights architecture — registry intrinsic fields joined with the
  // FILTERED model_info from GET /api/inventory/model/{name}. The vLLM /
  // not-installed branch degrades to registry+catalog fields so the view is
  // never empty (the flagship NVFP4 case).
  async function _renderWeights(el, id) {
    const m = _item(id);
    if (!m) { el.innerHTML = '<div class="model-empty">Model not found.</div>'; return; }
    const base = [
      ['Family', esc(m.arch_family || '—')],
      ['Params', m.params_b ? esc(`${m.params_b}B`) : '—'],
      ['Quantization', esc(m.quant || (m.installed_info && m.installed_info.details && m.installed_info.details.quantization_level) || '—')],
      ['Context window', m.context_tokens ? `${Number(m.context_tokens).toLocaleString()} tok` : esc(m.context || '—')],
      ['Weights size', m.size_gb ? esc(`${m.size_gb}GB`) : esc(m.size || '—')],
      ['Min arch', esc(m.min_arch || 'any')],
    ];
    let extra = '';
    if (m.installed) {
      const d = await _detail(m);
      const details = (d && d.details) || {};
      const mi = (d && d.model_info) || {};
      const rows = [];
      if (details.family) rows.push(['Backend family', esc(String(details.family))]);
      if (details.quantization_level) rows.push(['Backend quant', esc(String(details.quantization_level))]);
      if (details.parameter_size) rows.push(['Backend params', esc(String(details.parameter_size))]);
      Object.keys(mi).forEach(k => rows.push([k, esc(String(mi[k]))]));
      if (rows.length) {
        extra = `
          <div style="font-size:0.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin:8px 0 4px">
            model_info (${esc((d && d.backend) || 'backend')})</div>
          ${_kvGrid(rows)}`;
      } else if (d && d.note) {
        extra = `<div style="font-size:0.62rem;color:var(--text-muted)">${esc(d.note)} Registry fields above are authoritative.</div>`;
      }
    }
    el.innerHTML = `${_kvGrid(base)}${extra}`;
  }

  // Performance — per DETECTED arch class from the curated
  // api/config/model_meta.json sidecar (merged into /enrichment under
  // model_meta), plus any curated benchmark block for this model id.
  async function _renderPerformance(el, id) {
    const m = _item(id);
    if (!m) { el.innerHTML = '<div class="model-empty">Model not found.</div>'; return; }
    const [enr, arch] = await Promise.all([_enrich(), _archInfo()]);
    const archName = (arch && arch.name) || 'unknown';
    const meta = (enr && enr.model_meta) || {};
    const cls = (meta.arch_class_perf || {})[archName];
    const bench = (enr && enr[m.id]) || null;
    const rowsHtml = cls && Array.isArray(cls.expectations)
      ? `<table class="models-perf-table"><thead><tr><th>size class</th><th>tok/s</th><th>example</th></tr></thead><tbody>
          ${cls.expectations.map(x => `<tr><td>${esc(x.size_class || '—')}</td><td>${esc(x.tok_s || '—')}</td><td>${esc(x.example || '')}</td></tr>`).join('')}
        </tbody></table>`
      : '<div class="model-empty">No curated expectations for this architecture class yet.</div>';
    const roleFit = bench && bench.role_fit
      ? _kvGrid([['Role fit', Object.entries(bench.role_fit)
          .map(([r, v]) => `<span class="lib-chip">${esc(r)} ${esc(String(v))}</span>`).join(' ')]])
      : '';
    el.innerHTML = `
      ${_kvGrid([
        ['Arch class', `<code>${esc(archName)}</code>${cls ? ` — ${esc(cls.label || '')}` : ''}`],
        ['Registry speed', esc(typeof m.speed === 'string' ? m.speed : '—')],
      ])}
      ${cls && cls.notes ? `<div style="font-size:0.62rem;color:var(--text-muted);margin-bottom:8px">${esc(cls.notes)}</div>` : ''}
      ${rowsHtml}
      ${roleFit}
      <div style="font-size:0.6rem;color:var(--text-muted);margin-top:8px">
        Curated expectations (api/config/model_meta.json) — order-of-magnitude, not a benchmark run.</div>`;
  }

  // Hardware fit — score + per-pool breakdown, honestly labeled LOAD-fit.
  async function _renderFit(el, id) {
    const m = _item(id);
    if (!m) { el.innerHTML = '<div class="model-empty">Model not found.</div>'; return; }
    const fit = m.fit || {};
    const cls = String(fit.class || 'unknown');
    const arch = await _archInfo();
    const pools = (arch && arch.per_pool_gb) || [];
    const pct = (fit.required_gb && fit.budget_gb)
      ? Math.min(100, Math.round((fit.required_gb / fit.budget_gb) * 100)) : null;
    const bar = pct != null
      ? `<div class="models-fit-bar"><div class="models-fit-fill fit-${esc(cls)}" style="width:${pct}%"></div></div>
         <div style="font-size:0.62rem;color:var(--text-muted)">~${esc(String(fit.required_gb))}GB required (weights + KV headroom) of ${esc(String(fit.budget_gb))}GB budget — ${pct}%</div>`
      : '';
    el.innerHTML = `
      ${_kvGrid([
        ['Load-fit', `<span class="lib-dot fit-${esc(cls)}" style="display:inline-block;vertical-align:middle;margin-right:6px"></span><strong>${esc(cls)}</strong>${fit.score != null ? ` · score ${esc(String(fit.score))}` : ''}`],
        ['Budget basis', esc(fit.basis || '—')],
        ['Memory pools', pools.length
          ? pools.map((p, i) => `<span class="lib-chip">pool ${i}: ${esc(String(p))}GB</span>`).join(' ')
          : esc(`host RAM ${_hardware.max_model_ram_gb || '?'}GB usable for models`)],
        ['Hardware', esc(`${_hardware.name || 'unknown'} — ${_hardware.ram_gb || '?'}GB RAM`)],
      ])}
      ${bar}
      <div style="font-size:0.6rem;color:var(--text-muted);margin-top:8px">
        Load-fit is a can-it-load hint, not a runtime guarantee — KV pressure at long context can still evict.</div>`;
  }

  async function _renderRelations(el, id) {
    const m = _item(id);
    if (!m) { el.innerHTML = '<div class="model-empty">Model not found.</div>'; return; }
    if (!m.installed) {
      el.innerHTML = '<div class="model-empty">Relations resolve for installed models (workflow + agent scans reference served names).</div>';
      return;
    }
    const d = await _detail(m);
    const wf = ((d && d.workflows) || []).map(w =>
      `<li><code>${esc(w.id || w)}</code>${w.name ? ` — ${esc(w.name)}` : ''}</li>`).join('')
      || '<li style="color:var(--text-muted)">no workflows reference this model</li>';
    const ag = ((d && d.agents) || []).map(a =>
      `<li><code>${esc(a.id || a)}</code>${a.name ? ` — ${esc(a.name)}` : ''}</li>`).join('')
      || '<li style="color:var(--text-muted)">no agents pin this model</li>';
    el.innerHTML = _kvGrid([
      ['Workflows', `<ul style="margin:0;padding-left:14px">${wf}</ul>`],
      ['Agents', `<ul style="margin:0;padding-left:14px">${ag}</ul>`],
    ]);
  }

  // Recommended prompts — the LB2-U2 deterministic scorer, model-side.
  // Per-factor breakdown rendered inline; the ↗ jump rides LibraryShell.open.
  async function _renderPrompts(el, id) {
    const m = _item(id);
    if (!m) { el.innerHTML = '<div class="model-empty">Model not found.</div>'; return; }
    const served = _servedName(m);
    const r = await Net.call(`/api/prompts/recommend?model=${encodeURIComponent(served)}`, { silent: true });
    if (!r.ok) {
      el.innerHTML = `<div class="model-empty" style="color:var(--danger)">Recommender failed: ${esc(r.error || `HTTP ${r.status}`)}</div>`;
      return;
    }
    const results = (r.data && r.data.results) || [];
    if (!results.length) {
      el.innerHTML = '<div class="model-empty">No installed prompts scored for this model yet — tag prompts (model_fit) in the Prompts library.</div>';
      return;
    }
    el.innerHTML = `
      <div style="font-size:0.62rem;color:var(--text-muted);margin-bottom:6px">
        Deterministic scorer — prompts ranked for <code>${esc(served)}</code>; every factor shown, nothing hidden.</div>
      ${results.map(x => {
        const f = x.factors || {};
        const tt = f.task_tags || {};
        const mf = f.model_fit || {};
        const sf = f.size_fit || {};
        return `<div class="models-prompt-row">
          <div class="models-prompt-head">
            <span class="lib-badge">${esc(x.kind || 'prompt')}</span>
            <strong>${esc(x.name || x.id)}</strong>
            <span class="models-prompt-score">score ${esc(String(x.score))}</span>
            <button type="button" class="action-btn xs" data-action="models.open-prompt"
              data-prompt="${esc(`${x.kind}/${x.id}`)}" title="Open in the Prompts library">↗ open</button>
          </div>
          <div class="models-prompt-factors">
            <span class="lib-chip" title="task-keyword overlap">tags ${esc(String(tt.score != null ? tt.score : '—'))}${(tt.matched || []).length ? ` (${esc(tt.matched.join(', '))})` : ''}</span>
            <span class="lib-chip" title="declared model_fit vs this model's role classes">model_fit ${esc(String(mf.score != null ? mf.score : '—'))}${(mf.matched || []).length ? ` (${esc(mf.matched.join(', '))})` : ''}</span>
            <span class="lib-chip" title="token estimate vs context window (approximate, never a gate)">size ${esc(String(sf.score != null ? sf.score : '—'))}${sf.token_estimate ? ` (~${esc(String(sf.token_estimate))} tok / ${esc(String(sf.context_tokens || '?'))})` : ''}</span>
          </div>
        </div>`;
      }).join('')}`;
  }

  function _renderDiscOverview(el, id) {
    const d = _discRecord(id);
    if (!d) { el.innerHTML = '<div class="model-empty">Not in the current scan — hit ⟳ Discover.</div>'; return; }
    el.innerHTML = _kvGrid([
      ['Repo', `<code>${esc(d.repo_id)}</code>`],
      ['Author', esc(d.author || '—') + (d.is_trusted_author ? ' <span class="lib-chip">trusted</span>' : '')],
      ['Est. size', d.estimated_size_gb ? esc(`~${d.estimated_size_gb}GB`) : '—'],
      ['Context', d.context_window ? esc(`${Number(d.context_window).toLocaleString()} tok`) : '—'],
      ['GGUF', d.has_gguf ? 'available — pullable via <code>hf.co/</code>' : 'not detected'],
      ['Tags', _tagChips(d.tags)],
      ['Scanned', esc(_discoveredAt ? new Date(_discoveredAt).toLocaleString() : '—')],
    ]) + '<div style="font-size:0.6rem;color:var(--text-muted)">Discovered via the operator-triggered HuggingFace scan — nothing fetches on tab activation.</div>';
  }

  // ── Backing fetches (cached; local reads only) ────────────────────────
  async function _detail(m) {
    const key = _servedName(m);
    if (_detailCache[key]) return _detailCache[key];
    const r = await LibraryShell.fetch('model', `/api/inventory/model/${_pathName(key)}`);
    if (r.ok && r.data) _detailCache[key] = r.data;
    return _detailCache[key] || null;
  }
  async function _enrich() {
    if (_enrichment) return _enrichment;
    try {
      const r = await Net.call('/api/inventory/enrichment', { silent: true });
      if (r.ok && r.data && typeof r.data === 'object') _enrichment = r.data;
    } catch (_) { /* stays null */ }
    return _enrichment || {};
  }
  async function _archInfo() {
    if (_arch) return _arch;
    try {
      const r = await Net.call('/api/system/architecture', { silent: true });
      if (r.ok && r.data) _arch = r.data.arch || r.data.architecture || null;
    } catch (_) { /* stays null */ }
    return _arch;
  }

  // ── Panel API ─────────────────────────────────────────────────────────
  // Mount once on first Models-tab activation, reload after — switchTab
  // calls this instead of loadCatalog (the legacy loader now runs only for
  // the Catalog page), so tab entry performs exactly ONE inventory fetch.
  function activate() {
    if (!_mounted) {
      _mounted = true;
      return LibraryShell.mount('model', 'models-shell');
    }
    return LibraryShell.reload('model');
  }

  function select(id) {
    _editingTags = false;
    LibraryShell.select('model', id);
  }

  function test(id) {
    const target = id || _selected();
    if (!target) return;
    if (target !== _selected()) select(target);
    LibraryShell.setSubnav('model', 'test');
  }

  // ── Inline tag editor → PATCH /api/inventory/model/{name}/tags ───────
  function editTags(id) {
    const target = id || _selected();
    if (!target || _isDisc(target)) return;
    if (target !== _selected()) LibraryShell.select('model', target);
    _editingTags = true;
    LibraryShell.setSubnav('model', 'overview');
    LibraryShell.renderDetail('model');
  }

  function cancelTags() {
    _editingTags = false;
    LibraryShell.renderDetail('model');
  }

  async function saveTags(id) {
    const m = _item(id || _selected());
    const inp = document.getElementById('models-tags-input');
    if (!m || !inp) return;
    const tags = inp.value.split(',').map(t => t.trim()).filter(Boolean);
    try {
      // retries:0 — settings write; never double-apply.
      const r = await Net.call(`/api/inventory/model/${_pathName(m.id)}/tags`, {
        retries: 0,
        init: {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ tags }),
        },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : (r.error || `HTTP ${r.status}`);
        Toast.danger('Tags save failed', detail);
        return;
      }
      _editingTags = false;
      Toast.success('Task tags saved', `${m.id} → [${tags.join(', ') || 'cleared'}]`);
      await LibraryShell.reload('model');
    } catch (e) { Toast.danger('Tags save failed', e.message); }
  }

  // ── Pull / remove (shell-side flows; same endpoints as the legacy grid,
  //    retries:0, Confirm on remove) ─────────────────────────────────────
  function _progressLine() { return document.getElementById('models-pull-progress'); }

  async function pull(id, model) {
    const m = id ? _item(id) : null;
    const target = model || (m ? (m.ollama || (m.gguf ? 'hf.co/' + m.gguf : '')) : '');
    if (!target || _pulling) return false;
    _pulling = target;
    LibraryShell.renderDetail('model');
    const line = _progressLine();
    if (line) { line.hidden = false; line.textContent = `▸ pulling ${target} — starting…`; }
    const mb = b => (b / 1e6).toFixed(0);
    try {
      // retries:0 MANDATORY — a retried POST would double-trigger a multi-GB pull.
      await Net.postJson('/api/inventory/pull', { model: target }, { retries: 0 });
    } catch (e) {
      if (line) line.textContent = `✗ pull failed: ${e.message}`;
      _pulling = null;
      LibraryShell.renderDetail('model');
      return false;
    }
    return new Promise(resolve => {
      const poll = setInterval(async () => {
        try {
          const d = await Net.getJson(
            `/api/inventory/pull-progress/${encodeURIComponent(target)}`,
            { silent: true, retries: 0 });
          const phase = d.status_message || d.status || 'pulling';
          if (line) {
            line.textContent = (d.total > 0)
              ? `▸ ${target}: ${phase} — ${Math.round((d.progress / d.total) * 100)}% (${mb(d.progress)} / ${mb(d.total)} MB)`
              : `▸ ${target}: ${phase}…`;
          }
          if (d.status === 'complete' || d.status === 'error') {
            clearInterval(poll);
            _pulling = null;
            if (d.status === 'complete') {
              if (line) line.textContent = `✓ ${target} installed`;
              Toast.success('Model pulled', target);
              if (typeof window.loadInstalledLocal === 'function') { try { window.loadInstalledLocal(); } catch (_) {} }
              await LibraryShell.reload('model');
              resolve(true);
            } else {
              if (line) line.textContent = `✗ ${target}: ${d.error || 'pull failed'}`;
              Toast.danger('Pull failed', d.error || target);
              LibraryShell.renderDetail('model');
              resolve(false);
            }
          }
        } catch (e) {
          clearInterval(poll);
          _pulling = null;
          if (line) line.textContent = `✗ ${target}: ${e.message}`;
          LibraryShell.renderDetail('model');
          resolve(false);
        }
      }, 800);
    });
  }

  async function remove(id) {
    const m = _item(id || _selected());
    if (!m) return false;
    const name = _servedName(m);
    const ok = await Confirm.ask({
      title: 'Remove model',
      body: `Remove model "${name}"? This deletes the model files from disk.`,
      okLabel: 'Remove', danger: true,
    });
    if (!ok) return false;
    try {
      // retries:0 — destructive remove; never double-fire.
      const r = await Net.call('/api/inventory/remove', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ..._headers() },
          body: JSON.stringify({ model: name }),
        },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : (r.error || `HTTP ${r.status}`);
        Toast.danger('Remove failed', detail);
        return false;
      }
      Toast.success('Model removed', name);
      if (typeof window.loadInstalledLocal === 'function') { try { window.loadInstalledLocal(); } catch (_) {} }
      await LibraryShell.reload('model');
      return true;
    } catch (e) { Toast.danger('Remove failed', e.message); return false; }
  }

  // ── Intent recommender (deterministic, instant, explainable) ─────────
  async function setIntent(intent) {
    _intent = intent || '';
    _recRank = {};
    const strip = document.getElementById('models-rec-strip');
    if (!_intent) {
      if (strip) { strip.hidden = true; strip.innerHTML = ''; }
      LibraryShell.renderRows('model');
      return;
    }
    if (strip) { strip.hidden = false; strip.innerHTML = '<div class="model-empty">Ranking…</div>'; }
    const r = await Net.call(`/api/inventory/recommendations?intent=${encodeURIComponent(_intent)}`, { silent: true });
    if (!r.ok) {
      if (strip) strip.innerHTML = `<div class="model-empty" style="color:var(--danger)">Recommendations failed: ${esc(r.error || `HTTP ${r.status}`)}</div>`;
      return;
    }
    const results = (r.data && r.data.results) || [];
    results.forEach((x, i) => { _recRank[x.id] = { rank: i + 1, score: x.score }; });
    if (strip) {
      const role = (r.data && r.data.role) || '?';
      strip.innerHTML = `
        <div class="models-rec-head">// intent <code>${esc(_intent)}</code> → role <code>${esc(role)}</code> — role_fit × fit-class, top ${Math.min(5, results.length)}</div>
        ${results.slice(0, 5).map((x, i) => {
          const rf = (x.factors && x.factors.role_fit) || {};
          const fc = (x.factors && x.factors.fit_class) || {};
          const pull = (!x.installed && x.pull && x.pull.model)
            ? `<button type="button" class="action-btn xs accent" data-action="models.pull"
                 data-shell="models" data-model="${esc(x.pull.model)}" data-model-id="${esc(x.id)}">Pull</button>`
            : (x.installed ? '<span class="lib-chip">installed</span>' : '<span class="lib-chip">no pull source</span>');
          return `<div class="models-rec-row">
            <span class="models-rec-rank">#${i + 1}</span>
            <button type="button" class="btn-unstyled models-rec-name" data-action="models.select"
              data-kind="model" data-id="${esc(x.id)}">${esc(x.name)}</button>
            <span class="lib-chip" title="role_fit source: ${esc(rf.source || '?')}${rf.task_tag_boost ? ' + task-tag boost' : ''}">role_fit ${esc(String(rf.value != null ? rf.value : '?'))}</span>
            <span class="lib-chip" title="load-fit multiplier">${esc(fc.class || '?')} ×${esc(String(fc.multiplier != null ? fc.multiplier : '?'))}</span>
            <span class="models-prompt-score">score ${esc(String(x.score))}</span>
            ${pull}
          </div>`;
        }).join('')}`;
    }
    LibraryShell.renderRows('model');
  }

  // ── Operator-triggered HF discovery refresh ───────────────────────────
  // The ONLY place this panel reaches the discovery routes: the master-key
  // POST .../discover/refresh is the egress trigger; the follow-up read
  // serves the refreshed cache (GET /discover still carries pre-existing
  // TTL-on-read semantics — follow-up #15 — but here it only ever runs on
  // this visible button, never on tab activation or adapter load).
  async function refreshDiscover() {
    const btn = document.getElementById('models-refresh-discover');
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
    try {
      const r = await Net.call('/api/inventory/discover/refresh', {
        retries: 0,
        init: { method: 'POST', headers: _headers() },
      });
      if (!r.ok) {
        const detail = (r.data && r.data.detail) ? r.data.detail : (r.error || `HTTP ${r.status}`);
        Toast.danger('Discovery refresh failed', detail);
        return;
      }
      const d = await Net.getJson('/api/inventory/discover', { retries: 0 });
      _discovered = d.models || [];
      _discoveredAt = d.timestamp || null;
      LibraryShell.renderSidebar('model');
      Toast.success('HF discovery refreshed', `${_discovered.length} models in scan`);
    } catch (e) {
      Toast.danger('Discovery refresh failed', e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '⟳ Discover'; }
    }
  }

  // ── Delegated actions ─────────────────────────────────────────────────
  // models.pull / models.remove / models.review / models.test stay
  // registered in main.js (the legacy catalog grid owns those ids); its
  // handlers route data-shell="models" clicks back into this panel.
  Actions.click({
    'models.select': el => select(el.dataset.id),
    'models.edit-tags': el => editTags(el.dataset.id),
    'models.tags-save': el => saveTags(el.dataset.id),
    'models.tags-cancel': () => cancelTags(),
    'models.refresh-discover': () => refreshDiscover(),
    // Installed-Locally memory-residency panel refresh — migrated off inline
    // onclick (MS-4); bridges the existing main.js loader (no new global).
    'models.refresh-local': () => {
      if (typeof window.loadInstalledLocal === 'function') {
        try { window.loadInstalledLocal(); } catch (_) {}
      }
    },
    'models.open-prompt': el => LibraryShell.open('prompt', el.dataset.prompt),
  });
  Actions.change({
    'models.intent': el => setIntent(el.value || ''),
  });

  return { activate, select, test, pull, remove, editTags, saveTags, cancelTags,
           setIntent, refreshDiscover, adapter };
})();
