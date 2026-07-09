// workspace-legacy/df-seed-schema.js — Drawflow seed schema (phase-2 U8; df* via window bridge).
import { esc } from '../core/dom.js';
import { Toast } from '../core/ui.js';

export const DfSeedSchema = (function () {
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
