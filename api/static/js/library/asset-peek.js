// library/asset-peek.js — asset deep-dive peek panel (phase-2 U4 carve).
import { esc } from '../core/dom.js';

export const AssetPeek = (function () {
  let _enrichment = null;   // lazy, cached for the session
  let _catalog = null;

  async function _getEnrichment() {
    if (_enrichment) return _enrichment;
    try { _enrichment = await (await fetch('/api/inventory/enrichment')).json(); }
    catch (_) { _enrichment = {}; }
    return _enrichment;
  }
  async function _getCatalog() {
    if (_catalog) return _catalog;
    try {
      const d = await (await fetch('/api/inventory/catalog')).json();
      _catalog = d.models || d || [];
    } catch (_) { _catalog = []; }
    return _catalog;
  }

  function _fitRow(label, val, warm) {
    return `<div class="peek-fit-row">
      <span class="peek-fit-k">${esc(label)}</span>
      <span class="peek-fit-bar${warm ? ' warm' : ''}"><i style="width:${Math.max(2, Math.min(100, val))}%"></i></span>
      <span class="peek-fit-v">${val}</span>
    </div>`;
  }

  function _kv(pairs) {
    return `<div class="peek-kv">` + pairs
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `<span class="k">${esc(k)}</span><span class="v">${esc(String(v))}</span>`)
      .join('') + `</div>`;
  }

  function _section(label, html) {
    return html ? `<div class="peek-section"><div class="peek-section-label">${esc(label)}</div>${html}</div>` : '';
  }

  function _show(kind, title, id, bodyHtml, actionsHtml) {
    document.getElementById('peek-kind').textContent = kind;
    document.getElementById('peek-title').textContent = title;
    document.getElementById('peek-id').textContent = id;
    document.getElementById('peek-body').innerHTML = bodyHtml;
    document.getElementById('peek-actions').innerHTML = actionsHtml || '';
    document.getElementById('asset-peek').classList.add('open');
    document.getElementById('asset-peek-backdrop').classList.add('open');
  }

  function close() {
    document.getElementById('asset-peek').classList.remove('open');
    document.getElementById('asset-peek-backdrop').classList.remove('open');
  }

  // "Seed a chat" — the design's terminal action: every deep dive can end
  // in a conversation. Switches to the Composer, scopes the picker, and
  // focuses the prompt (optionally pre-filled).
  function seedChat(modelId, agentId, starter) {
    close();
    const tabBtn = document.querySelector('[data-tab="dashboard"]');
    if (typeof switchTab === 'function') switchTab('dashboard', tabBtn);
    if (agentId) {
      const sel = document.getElementById('agent-select');
      if (sel) { sel.value = agentId; try { onAgentSelectionChanged(); } catch (_) {} }
    } else if (modelId) {
      const sel = document.getElementById('model-select');
      if (sel && [...sel.options].some(o => o.value === modelId)) sel.value = modelId;
    }
    const p = document.getElementById('prompt');
    if (p) { if (starter) p.value = starter; p.focus(); }
  }

  async function openModel(id) {
    const [cat, enr] = await Promise.all([_getCatalog(), _getEnrichment()]);
    const m = cat.find(x => x.id === id || x.ollama === id);
    if (!m) return;
    const e = enr[m.id] || enr[m.ollama] || {};
    const b = e.benchmarks || {};
    const benchHtml = Object.keys(b).length
      ? Object.entries(b).map(([k, v]) => _fitRow(k, v)).join('') +
        `<div class="peek-foot-note">${esc(e.basis || '')} · approximate published evals — see data/discovery/model_benchmarks.json</div>`
      : `<div class="peek-foot-note">No credible published benchmarks for this variant — absence is honest, not an oversight.${e.notes ? '' : ''}</div>`;
    const fit = e.role_fit || {};
    const fitHtml = Object.keys(fit).length
      ? Object.entries(fit).map(([k, v]) => _fitRow(k, v, true)).join('')
      : '';
    const body =
      _section('about', `<div class="peek-about">${esc(m.description || '')}${e.notes ? '\n\n' + esc(e.notes) : ''}</div>`) +
      _section('specs', _kv([
        ['params', e.params], ['size', m.size], ['speed', m.speed], ['context', m.context],
        ['family', e.family], ['license', e.license],
        ['source', m.ollama ? 'ollama: ' + m.ollama : (m.gguf ? 'hf.co/' + m.gguf : '—')],
        ['fits this host', m.fits_ram === false ? 'NO — exceeds RAM budget' : 'yes'],
      ])) +
      _section('benchmarks', benchHtml) +
      (fitHtml ? _section('role fit', fitHtml) : '');
    const pullTarget = m.ollama || (m.gguf ? 'hf.co/' + m.gguf : '');
    const actions = (m.installed
        ? `<button class="action-btn accent" onclick="AssetPeek.seedChat('${esc(m.ollama || m.id)}')">Seed a chat →</button>`
        : (pullTarget ? `<button class="action-btn accent pull" onclick="AssetPeek.close();pullModel('${esc(pullTarget)}', '${esc(m.id)}')">Pull model</button>` +
            `<button class="action-btn ghost" onclick="AssetPeek.close();InstallWizard.open('${esc(pullTarget)}')">Guided install</button>` : '')) +
      `<button class="action-btn ghost" onclick="Compare.add('${esc(m.id)}')">+ Compare</button>` +
      ((m.huggingface || m.gguf) ? `<button class="action-btn ghost" onclick="reviewModel('${esc(m.huggingface || m.gguf)}')">Review source</button>` : '');
    _show('model', m.name, m.id, body, actions);
  }

  async function openAgent(id) {
    let agents = [];
    try { agents = await (await fetch('/api/agents')).json(); } catch (_) {}
    const a = (agents || []).find(x => x.id === id);
    if (!a) return;
    const starters = (a.starters || []).map(s =>
      `<button class="peek-starter" onclick="AssetPeek.seedChat(null, '${esc(a.id)}', '${esc(String(s).replace(/'/g, "\\'"))}')">${esc(s)}</button>`).join('');
    const body =
      _section('about', `<div class="peek-about">${esc(a.description || '')}</div>`) +
      _section('binding', _kv([
        ['model', a.model], ['role', a.role], ['tags', (a.tags || []).join(' · ')], ['file', a.file],
      ])) +
      _section('conversation starters', starters || '<div class="peek-foot-note">none declared</div>');
    const actions = `<button class="action-btn accent" onclick="AssetPeek.seedChat(null, '${esc(a.id)}')">Chat with agent →</button>` +
      `<button class="action-btn ghost" onclick="AssetPeek.close();showEditAgentModal('${esc(a.id)}')">Edit</button>`;
    _show('agent', a.name, a.id + (a.model ? ' · ' + a.model : ''), body, actions);
  }

  async function openPlugin(id) {
    let plugins = [];
    try { plugins = await (await fetch('/api/plugins')).json(); } catch (_) {}
    const p = (plugins || []).find(x => x.id === id);
    if (!p) return;
    const tools = (p.tools || []).map(t =>
      `<div class="peek-list-item"><span class="n">⚙ ${esc(t.id || t.name || '')}</span><span class="d">${esc(t.description || '')}</span></div>`).join('');
    const skills = (p.skills || []).map(s =>
      `<div class="peek-list-item"><span class="n">⚡ ${esc(s.id || s.name || '')}</span><span class="d">${esc(s.description || (s.triggers || []).join(', '))}</span></div>`).join('');
    const body =
      _section('about', `<div class="peek-about">${esc(p.description || '')}</div>`) +
      _section('identity', _kv([['version', p.version], ['author', p.author], ['path', p.path]])) +
      _section('tools', tools || '<div class="peek-foot-note">no tools</div>') +
      _section('skills', skills || '<div class="peek-foot-note">no skills</div>');
    _show('plugin', p.name, p.id, body, '');
  }

  function open(kind, id) {
    if (kind === 'model') return openModel(id);
    if (kind === 'agent') return openAgent(id);
    if (kind === 'plugin') return openPlugin(id);
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('asset-peek')?.classList.contains('open')) close();
  });

  return { open, close, seedChat };
})();
