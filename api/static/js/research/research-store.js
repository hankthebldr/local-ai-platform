// research/research-store.js — RX-2 Obsidian-like store browser.
//
// The shared `research` workspace IS the store: sessions/ (RX-1 MOCs),
// sources/ (saved research results), notes/ (compare + graph-walk reports).
// This module lists it as a file tree — reusing the LB3 `.skills-tree` grammar
// — with a markdown preview. Read-only: only GET reads, no egress. Writes go
// through the operator-triggered research.save-source / compare / walk handlers.

import { esc } from '../core/dom.js';
import { Net } from '../core/net.js';
import { Actions } from '../shell/actions.js';

export const ResearchStore = (function () {
  const WORKSPACE = 'research';

  // Build a nested {dirs, files} tree from posix relative paths.
  function _treeFromPaths(paths) {
    const root = { dirs: Object.create(null), files: [] };
    (paths || []).forEach((p) => {
      const parts = String(p).split('/');
      let node = root;
      for (let i = 0; i < parts.length - 1; i++) {
        const seg = parts[i];
        node.dirs[seg] = node.dirs[seg] || { dirs: Object.create(null), files: [] };
        node = node.dirs[seg];
      }
      node.files.push({ name: parts[parts.length - 1], path: p });
    });
    return root;
  }

  function _treeHtml(node, depth) {
    let html = '';
    Object.keys(node.dirs).sort().forEach((name) => {
      html += `<div class="skills-tree-dir" style="padding-left:${depth * 12}px">▾ ${esc(name)}/</div>`;
      html += _treeHtml(node.dirs[name], depth + 1);
    });
    node.files
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((f) => {
        html +=
          `<button type="button" class="btn-unstyled skills-tree-file" ` +
          `style="padding-left:${depth * 12}px" data-action="research.store-open" ` +
          `data-path="${esc(f.path)}">${esc(f.name)}</button>`;
      });
    return html;
  }

  async function load() {
    const treeEl = document.getElementById('research-store-tree');
    if (!treeEl) return;
    treeEl.innerHTML =
      '<div class="skeleton skeleton-line long"></div><div class="skeleton skeleton-line short"></div>';
    try {
      const d = await Net.getJson(`/api/workspaces/${WORKSPACE}/files`, { silent: true });
      const files = (d && d.files) || [];
      const md = files.filter((p) => /\.md$/i.test(p) && !p.startsWith('.enclave/'));
      if (!md.length) {
        treeEl.innerHTML =
          '<div class="rnr-empty" style="padding:14px">No notes yet. Save a source or run research to fill the store.</div>';
        return;
      }
      treeEl.innerHTML = `<div class="skills-tree">${_treeHtml(_treeFromPaths(md), 0)}</div>`;
    } catch (e) {
      treeEl.innerHTML = `<div class="rnr-empty" style="color:var(--red);padding:14px">Store unavailable: ${esc(String(e))}</div>`;
    }
  }

  async function open(path) {
    const prev = document.getElementById('research-store-preview');
    if (!prev || !path) return;
    prev.innerHTML = '<div class="skeleton skeleton-line long"></div>';
    try {
      const d = await Net.getJson(
        `/api/workspaces/${WORKSPACE}/file?path=${encodeURIComponent(path)}`,
        { silent: true }
      );
      const content = (d && d.content) || '';
      const rendered = window.renderMarkdown ? window.renderMarkdown(content, { chat: false }) : esc(content);
      prev.innerHTML =
        `<div class="skills-tree-meta"><code>${esc(path)}</code></div>` +
        `<div class="synthesis-block">${rendered}</div>`;
    } catch (e) {
      prev.innerHTML = `<div class="rnr-empty" style="color:var(--red)">Failed to read ${esc(path)}: ${esc(String(e))}</div>`;
    }
  }

  Actions.click({
    'research.store-refresh': () => load(),
    'research.store-open': (el) => open(el.dataset.path),
  });

  return { load, open };
})();
