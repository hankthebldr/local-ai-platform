// research/research-node-rail.js — RX-2 exploratory node rail.
//
// Registers kind:'research-node' INTO the canonical shell/context-node-rail.js.
// It does NOT reimplement rail plumbing — the pane-guard lives once in the
// shared module. This module only owns the research verbs that paint into the
// rail's mount:
//   research.node-read    — read the selected node's content into the rail
//   research.compare-node — POST /compare-node (fresh search opt-in) → sections
//   research.build-upon   — seed a follow-up from this node
//   research.graph-walk   — POST /graph-walk, a resumable per-node comparison
//
// Egress (compare / walk) happens only inside these operator-clicked handlers.

import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Toast } from '../core/ui.js';
import { Actions } from '../shell/actions.js';
import { ContextNodeRail } from '../shell/context-node-rail.js';

export const ResearchNodeRail = (function () {
  const MOUNT_ID = 'research-node-rail';
  let _focus = ''; // the current node's label — the verbs act on this

  function currentFocus() { return _focus; }

  function _nodeText(node) {
    if (!node) return '';
    return String(
      node.preview || node.description || node.summary || node.url || node.label || node.id || ''
    );
  }

  function _md(text) {
    return window.renderMarkdown ? window.renderMarkdown(text || '', { chat: false }) : esc(text || '');
  }

  // The rail render — paints the verb strip + a results slot. Invoked ONLY via
  // ContextNodeRail.activate (single pane-guard) for research-pane nodes.
  function render(node, mount) {
    _focus = String((node && (node.label || node.id)) || '');
    mount.dataset.focus = _focus;
    mount._nodeText = _nodeText(node);
    mount.innerHTML = `
      <div class="rnr-head">EXPLORE · <strong>${esc(_focus.slice(0, 60))}</strong></div>
      <div class="lib-actions-row rnr-verbs">
        <button class="action-btn xs" data-action="research.node-read">Read</button>
        <button class="action-btn xs cyan" data-action="research.compare-node">Compare ↔</button>
        <button class="action-btn xs" data-action="research.build-upon">Build upon</button>
        <button class="action-btn xs ghost" data-action="research.graph-walk"
                title="Walk every node, comparing each — resumable">Walk graph</button>
      </div>
      <div class="rnr-result" id="rnr-result"></div>`;
  }

  function _result() { return document.getElementById('rnr-result'); }
  function _busy(msg) { const r = _result(); if (r) r.innerHTML = `<div class="rnr-busy">${esc(msg)}</div>`; }

  function nodeRead() {
    const mount = document.getElementById(MOUNT_ID);
    const r = _result();
    if (!r) return;
    const text = (mount && mount._nodeText) || '';
    r.innerHTML = text
      ? `<div class="rnr-read synthesis-block">${_md(text)}</div>`
      : '<div class="rnr-empty">No readable content on this node.</div>';
  }

  function _sectionsHtml(sections) {
    const keys = Object.keys(sections || {});
    return keys
      .map(
        (k) =>
          `<div class="rnr-section"><div class="rnr-section-h">${esc(k)}</div>` +
          `<div class="synthesis-block">${_md(sections[k])}</div></div>`
      )
      .join('');
  }

  async function compareNode() {
    if (!_focus) return;
    // Reuse the follow-up web-search opt-in as the egress consent for compare.
    const webEl = document.getElementById('research-followup-web');
    const web_search = !!(webEl && webEl.checked);
    _busy('Comparing…');
    try {
      const resp = await Net.call('/api/research/compare-node', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ focus: _focus, web_search }),
        },
      });
      const data = resp.data && typeof resp.data === 'object' ? resp.data : {};
      if (!resp.ok) throw new Error(data.detail || resp.error || `HTTP ${resp.status}`);
      const r = _result();
      const sectionsHtml = _sectionsHtml(data.sections);
      r.innerHTML = sectionsHtml || `<div class="rnr-read synthesis-block">${_md(data.answer)}</div>`;
    } catch (e) {
      if (window.Toast) Toast.danger('Compare failed', String(e));
      _busy('Compare failed.');
    }
  }

  function buildUpon() {
    if (!_focus) return;
    const input = document.getElementById('research-followup-input');
    if (input) {
      input.value = input.value ? input.value + ' ' + _focus : `Building on "${_focus}": `;
      input.focus();
    }
    if (window.Toast) Toast.info('Build upon', 'Seeded a follow-up from this node.', { ttl: 1500 });
  }

  async function graphWalk() {
    // Seed from the current research graph's node labels (best-effort) then step
    // once. Resumable server-side via the workspace worklist — clicking again
    // advances to the next node.
    let nodes = [];
    try {
      const st = window._graphState;
      const arr = (st && (st.nodes || (st.state && st.state.nodes))) || [];
      nodes = arr.map((n) => n.label || n.id).filter(Boolean).slice(0, 24);
    } catch (_) { /* graph not painted yet — resume any existing walk */ }
    _busy('Walking…');
    try {
      const resp = await Net.call('/api/research/graph-walk', {
        retries: 0,
        init: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nodes }),
        },
      });
      const data = resp.data && typeof resp.data === 'object' ? resp.data : {};
      if (!resp.ok) throw new Error(data.detail || resp.error || `HTTP ${resp.status}`);
      const c = data.counts || {};
      const item = data.item;
      const r = _result();
      const progress =
        `<div class="rnr-walk-progress">walked ${c.done || 0}/${c.total || 0}` +
        (data.complete ? ' · complete' : ` · ${c.pending || 0} pending`) +
        `</div>`;
      const body = item
        ? `<div class="rnr-section-h">${esc(item.label || '')}</div>${_sectionsHtml(data.sections)}`
        : data.complete
          ? '<div class="rnr-empty">Walk complete.</div>'
          : '<div class="rnr-empty">Nothing to walk — build the graph first.</div>';
      const more = item && !data.complete
        ? '<div class="rnr-walk-more">Click <strong>Walk graph</strong> again to advance.</div>'
        : '';
      r.innerHTML = progress + body + more;
    } catch (e) {
      if (window.Toast) Toast.danger('Graph walk failed', String(e));
      _busy('Walk failed.');
    }
  }

  // Register research-node INTO the shared rail. auth:'optional' — reading a
  // node never needs a key; the egress verbs carry their own request-time gate.
  ContextNodeRail.register('research-node', {
    pane: 'research',
    mount: MOUNT_ID,
    render,
    auth: 'optional',
  });

  Actions.click({
    'research.node-read': () => nodeRead(),
    'research.compare-node': () => compareNode(),
    'research.build-upon': () => buildUpon(),
    'research.graph-walk': () => graphWalk(),
  });

  return { render, currentFocus };
})();
