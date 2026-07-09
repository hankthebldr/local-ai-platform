// runs/workflow-memory.js — workflow memory panel (phase-2 U5 carve).
import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Actions } from '../shell/actions.js';

export const WorkflowMemory = (function () {
  const TARGETS = [
    { kind: 'playbooks', list_id: 'wm-playbooks-list', count_id: 'wm-playbooks-count', read_path: 'playbooks' },
    { kind: 'semantic',  list_id: 'wm-semantic-list',  count_id: 'wm-semantic-count',  read_path: 'semantic'  },
    { kind: 'episodic',  list_id: 'wm-episodic-list',  count_id: 'wm-episodic-count',  read_path: 'episodic'  },
  ];

  async function refresh() {
    for (const t of TARGETS) {
      const listEl = document.getElementById(t.list_id);
      const countEl = document.getElementById(t.count_id);
      if (!listEl) continue;
      try {
        const resp = await Net.call(`/api/workflows/memory/${t.kind}`, {
          init: { headers: typeof getAuthHeaders === 'function' ? getAuthHeaders() : {} },
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = resp.data;
        const items = data[t.kind] || [];
        if (countEl) countEl.textContent = items.length;
        if (!items.length) {
          listEl.innerHTML = `<div class="wm-empty">No ${t.kind} written yet — run a workflow with a <code>kind: consolidate</code> step.</div>`;
          continue;
        }
        listEl.innerHTML = items.map(it => {
          const meta = (t.kind === 'episodic')
            ? `${it.record_count} rec${it.record_count !== 1 ? 's' : ''}`
            : `${(it.size_bytes || 0).toLocaleString()} B`;
          return `<button type="button" class="btn-unstyled wm-item" style="width:100%" data-action="wm.open" data-kind="${esc(t.kind)}" data-name="${esc(it.name)}">
            <span class="wm-item-name">${esc(it.name)}</span>
            <span class="wm-item-meta">${esc(meta)}</span>
          </button>`;
        }).join('');
      } catch (e) {
        listEl.innerHTML = `<div class="wm-empty">Failed: ${esc(String(e))}</div>`;
        if (countEl) countEl.textContent = '!';
      }
    }
  }

  async function open(kind, name) {
    const label = document.getElementById('wm-detail-label');
    const body = document.getElementById('wm-detail-body');
    const detail = document.getElementById('wm-detail');
    if (!detail || !label || !body) return;
    label.textContent = `${kind}: ${name}`;
    body.textContent = 'Loading…';
    detail.hidden = false;
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    try {
      const resp = await Net.call(`/api/workflows/memory/${kind}/${encodeURIComponent(name)}`, {
        init: { headers: typeof getAuthHeaders === 'function' ? getAuthHeaders() : {} },
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = resp.data;
      if (kind === 'episodic') {
        // Render the recency log as a readable digest.
        const lines = (data.records || []).map(r =>
          `### ${r.timestamp || '?'} (run ${r.run_id || '?'})\n${r.content || ''}`
        );
        body.textContent = lines.join('\n\n') || '(empty)';
      } else {
        body.textContent = data.body || '(empty)';
      }
    } catch (e) {
      body.textContent = 'Failed to load: ' + String(e);
    }
  }

  function closeDetail() {
    const detail = document.getElementById('wm-detail');
    if (detail) detail.hidden = true;
  }

  // Delegated action — the three store lists re-render on every refresh.
  Actions.click({ 'wm.open': el => open(el.dataset.kind, el.dataset.name) });

  return { refresh, open, closeDetail };
})();
