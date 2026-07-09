// library/agents.js — Agent generator/catalog (phase-2 U4 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';
import { Actions } from '../shell/actions.js';

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
