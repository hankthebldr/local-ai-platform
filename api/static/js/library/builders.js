// library/builders.js — Skills + Workflow builders (phase-2 U8 straggler).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';

export const SkillsBuilder = (function () {
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

export const WorkflowBuilder = (function () {
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
