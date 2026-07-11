// library/agents.js — Agent generator/catalog (phase-2 U4 carve) + the
// AgentsPanel LibraryShell adapter (MS-5: the Agents tab migrated onto the
// uniform master/detail grammar the other six Library kinds share).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { LibraryShell } from './shell.js';

export const AgentGen = (function () {
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


// ── AgentsPanel — the Agents tab on the LibraryShell (MS-5) ────────────────
//
// Grammar-only migration: the bespoke agent card grid + inline chat panel are
// replaced by the shared two-pane shell (uniform `.lib-row` list, subnav
// detail). auth:'none' — /api/agents is an unguarded read. The chat lives in
// a `chat` detail subnav slot; the existing main.js chat lifecycle
// (openAgentChat / sendAgentMessage / closeAgentChat / persist / restore)
// is REUSED verbatim against the same element ids — this module only renders
// the skeleton those functions populate, and drives selection/subnav focus.
// No backend change, no TestPane/provenance/re-sync (frozen engine — Library
// f/u #2). No new window globals: the chat verbs call the pre-existing globals
// main.js already bridges (openAgentChat, showEditAgentModal, deleteAgent,
// showCreateAgentModal, sendAgentMessage, closeAgentChat, AssetPeek).
//
// NOTE (finding #40 — CatalogPage agent-tile dedup): DEFERRED. The Admin →
// Catalog → Agents section still renders the legacy read-only tile grid
// (models.js `_renderAgentsList`, its own `agents.chat/edit/delete`); that
// surface has no shell and is a browse-only preview. Folding it onto the shell
// is left to a Library follow-up so this unit stays grammar-only for the tab.
export const AgentsPanel = (function () {
  let _agents = [];

  function _agent(id) { return _agents.find(a => a.id === id) || null; }
  function _selected() { return (LibraryShell.state('agent') || {}).selected; }
  function _oneLine(text, max) {
    const t = String(text || '').replace(/\s+/g, ' ').trim();
    const cap = max || 90;
    return t.length > cap ? t.slice(0, cap - 1) + '…' : t;
  }

  const adapter = LibraryShell.register({
    kind: 'agent',
    tabId: 'agents',
    countBadgeId: 'agents-count',
    listElId: 'agents-list',
    detailElId: 'agents-detail',
    labelElId: 'agents-detail-label',
    rowClass: 'agent-card',
    auth: 'none',                       // /api/agents is an unguarded read
    title: 'Agents',
    emptyText: 'No agents yet — + New Agent to author one.',
    emptyDetailLabel: '// SELECT AN AGENT',
    emptyDetailText: 'Select an agent on the left to read its persona and starters, or chat with it in the detail pane.',
    sectionOrder: ['overview', 'chat'],
    sectionLabels: { overview: 'Overview', chat: 'Chat' },

    async load() {
      const r = await LibraryShell.fetch('agent', '/api/agents');
      if (!r.ok) throw new Error(`Load failed (${r.status})`);
      _agents = Array.isArray(r.data) ? r.data : [];
    },

    list() {
      return _agents.map(a => {
        const chips = [];
        if (a.role) chips.push({ label: a.role, cls: 'tag-role' });
        if (a.model) chips.push({ label: a.model, cls: 'tag-model' });
        const blocks = ['model'];
        if (a.context && a.context.length) blocks.push('context');
        if (a.tools && a.tools.length) blocks.push('tools');
        return {
          id: a.id,
          title: a.name || a.id,
          meta: _oneLine(a.description) || (a.role ? 'Role · ' + a.role : ''),
          icon: (window.AgentIcons ? AgentIcons.resolve(a) : 'general'),
          tags: (a.tags || []),
          chips,
          blocks,
        };
      });
    },

    detail(id) {
      return {
        sections: {
          overview: (el) => _renderOverview(el, id),
          // A plain HTML STRING (not a fn) so the shell mounts it
          // SYNCHRONOUSLY — openAgentChat (which focuses this slot then
          // populates it in the same tick) needs #agent-chat-panel to exist
          // the instant focusChat returns. Function-sections mount on a
          // microtask, which would race the populate.
          chat: _CHAT_SKELETON,
        },
      };
    },

    // Chat / Edit / Deep dive / Delete — delegated ids read data-id (the shell
    // stamps it on each action button); delete routes through the shell's
    // lib.action Confirm gate is NOT used here so we keep the single
    // deleteAgent() Confirm (no double prompt).
    actions() {
      return [
        { action: 'agents.chat-open', label: 'Chat', verb: 'test', accent: true },
        { action: 'agents.edit-open', label: 'Edit', verb: 'edit' },
        { action: 'agents.peek', label: 'Deep dive', verb: 'test' },
        { action: 'agents.remove', label: 'Delete', verb: 'delete', danger: true },
      ];
    },
  });

  // ── Detail: overview ────────────────────────────────────────────────
  function _kvGrid(rows) {
    return `<div style="display:grid;grid-template-columns:96px 1fr;gap:6px 12px;font-size:0.72rem;margin-bottom:10px">
      ${rows.map(([k, v]) => `<div style="color:var(--text-muted)">${esc(k)}</div><div>${v}</div>`).join('')}
    </div>`;
  }

  function _renderOverview(el, id) {
    const a = _agent(id);
    if (!a) { el.innerHTML = '<div class="model-empty">Agent not found — Refresh.</div>'; return; }
    const tags = (a.tags || []).map(t => `<span class="lib-chip">${esc(t)}</span>`).join(' ') || '—';
    const starters = (a.starters || []).map(s =>
      `<button type="button" class="action-btn sm" style="margin:2px 4px 2px 0"
         data-action="agents.starter-open" data-starter="${esc(s)}">↗ ${esc(_oneLine(s, 60))}</button>`).join('')
      || '<span style="color:var(--text-muted)">none declared</span>';
    el.innerHTML = `
      ${_kvGrid([
        ['Role', a.role ? `<code>${esc(a.role)}</code>` : '<span style="color:var(--text-muted)">—</span>'],
        ['Model', a.model ? `<code>${esc(a.model)}</code>` : '<span style="color:var(--text-muted)">role default</span>'],
        ['Temperature', esc(String(a.temperature != null ? a.temperature : 0.7))],
        ['Tags', tags],
        ['Tools', `${(a.tools || []).length} bound`],
        ['Context', `${(a.context || []).length} source${(a.context || []).length === 1 ? '' : 's'}`],
      ])}
      ${a.description ? `<div style="font-size:0.74rem;margin-bottom:10px">${esc(a.description)}</div>` : ''}
      <div style="font-size:0.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px">System prompt</div>
      <pre class="prompts-body" style="max-height:220px;white-space:pre-wrap">${esc(a.system_prompt || '(none)')}</pre>
      <div style="font-size:0.6rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin:10px 0 4px">Conversation starters</div>
      <div>${starters}</div>`;
  }

  // ── Detail: chat slot ───────────────────────────────────────────────
  // Static skeleton (exact ids reused by main.js). openAgentChat() fills the
  // header + greeting; sendAgentMessage/closeAgentChat/_restoreAgentChat
  // operate on these same ids. Kept id-independent so it can be a synchronous
  // string section (see detail()).
  const _CHAT_SKELETON = `
    <div id="agent-chat-panel" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;">
      <div style="background:var(--bg-panel);padding:10px 14px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border);">
        <span id="agent-chat-icon" class="agent-chat-icon-block"></span>
        <strong id="agent-chat-name" style="color:var(--text);font-size:0.9rem;flex:1"></strong>
        <span id="agent-chat-model" style="font-size:0.72rem;color:var(--text-muted);"></span>
        <button data-action="agents.chat-close" title="Close chat"
          style="background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:1rem;">&times;</button>
      </div>
      <div id="agent-chat-messages" style="padding:14px;min-height:200px;max-height:400px;overflow-y:auto;font-size:0.82rem;display:flex;flex-direction:column;gap:10px;"></div>
      <div style="padding:10px;border-top:1px solid var(--border);display:flex;gap:8px;">
        <input type="text" id="agent-chat-input" aria-label="Message the agent" placeholder="Message the agent…"
          data-action="agents.chat-input"
          style="flex:1;background:var(--bg-panel);border:1px solid var(--border);color:var(--text);padding:7px 10px;border-radius:4px;font-family:var(--mono);font-size:0.82rem;">
        <button data-action="agents.chat-send"
          style="background:var(--accent);color:var(--bg-deep);border:none;padding:7px 16px;border-radius:4px;cursor:pointer;font-weight:600;font-size:0.8rem;">Send</button>
      </div>
    </div>`;

  // ── Panel API + focus helper ────────────────────────────────────────
  function load() { return LibraryShell.reload('agent'); }

  // Bring the shell to this agent's Chat slot so #agent-chat-panel exists.
  // Synchronous: the skeleton is in the DOM by the time this returns, so the
  // caller (openAgentChat) can populate it immediately. Idempotent when the
  // agent is already selected on the Chat subnav.
  function focusChat(id) {
    const st = LibraryShell.state('agent');
    if (!st) return;
    if (st.selected === id && st.subnav === 'chat' && document.getElementById('agent-chat-panel')) return;
    if (st.selected !== id) LibraryShell.select('agent', id);
    st.subnav = 'chat';
    delete st.rendered['chat'];
    LibraryShell.setSubnav('agent', 'chat');
  }

  // ── Delegated actions (agents.* — detail + toolbar) ─────────────────
  // The row select rides the shell's default `lib.select`; these are the
  // detail action row + panel-label toolbar + chat-slot verbs. Each resolves
  // the target from the shell selection (or the button's data-id).
  Actions.click({
    'agents.new': () => { if (window.showCreateAgentModal) showCreateAgentModal(); },
    'agents.refresh': () => load(),
    'agents.chat-open': el => { const id = (el && el.dataset.id) || _selected(); if (id && window.openAgentChat) openAgentChat(id); },
    'agents.edit-open': el => { const id = (el && el.dataset.id) || _selected(); if (id && window.showEditAgentModal) showEditAgentModal(id); },
    'agents.peek': el => { const id = (el && el.dataset.id) || _selected(); if (id && window.AssetPeek) AssetPeek.open('agent', id); },
    'agents.remove': el => { const id = (el && el.dataset.id) || _selected(); if (id && window.deleteAgent) deleteAgent(id); },
    'agents.starter-open': el => { const id = _selected(); if (id && window.openAgentChatWithStarter) openAgentChatWithStarter(id, el.dataset.starter); },
    'agents.chat-send': () => { if (window.sendAgentMessage) sendAgentMessage(); },
    'agents.chat-close': () => { if (window.closeAgentChat) closeAgentChat(); },
  });
  // Enter-to-send in the chat input (replaces the retired inline onkeydown).
  Actions.on('keydown', {
    'agents.chat-input': (el, e) => {
      if (e.key !== 'Enter' || e.shiftKey) return;
      e.preventDefault();
      if (window.sendAgentMessage) sendAgentMessage();
    },
  });

  return { load, focusChat, adapter };
})();
