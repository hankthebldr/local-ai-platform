// workspace-legacy/agent-tuning.js — legacy agent tuning (phase-2 U7). df* via window bridge.
import { Toast } from '../core/ui.js';

export const AgentTuning = (function () {
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
