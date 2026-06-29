import React from 'react';

/**
 * Enclave IconButton — a square, icon-only control for toolbars and canvas
 * chrome (zoom, fullscreen, close, dock). Quiet by default; teal on hover.
 */

const CSS = `
.encl-iconbtn {
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--surface-card); color: var(--text-dim);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer;
  transition: transform var(--t-fast) var(--ease-out),
              background-color var(--t-fast) var(--ease-out),
              border-color var(--t-fast) var(--ease-out),
              color var(--t-fast) var(--ease-out);
}
.encl-iconbtn:hover:not(:disabled) { color: var(--accent); border-color: var(--accent-dim); background: var(--surface-raised); }
.encl-iconbtn:active:not(:disabled) { transform: scale(0.94); }
.encl-iconbtn:disabled { opacity: 0.4; cursor: not-allowed; }
.encl-iconbtn.active { color: var(--accent); border-color: var(--accent-dim); background: var(--accent-ghost); }
.encl-iconbtn.bare { background: transparent; border-color: transparent; }
.encl-iconbtn.bare:hover:not(:disabled) { background: var(--surface-raised); }
.encl-iconbtn svg { width: 1.05em; height: 1.05em; stroke-width: 1.85; }
.encl-iconbtn.sz-sm { width: 26px; height: 26px; font-size: 13px; }
.encl-iconbtn.sz-md { width: 32px; height: 32px; font-size: 15px; }
.encl-iconbtn.sz-lg { width: 38px; height: 38px; font-size: 17px; }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function IconButton({
  children, label, size = 'md', active = false, bare = false,
  disabled = false, className = '', ...rest
}) {
  useInjected('encl-iconbtn-css', CSS);
  const cls = `encl-iconbtn sz-${size} ${active ? 'active' : ''} ${bare ? 'bare' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  return (
    <button type="button" className={cls} aria-label={label} title={label} disabled={disabled} {...rest}>
      {children}
    </button>
  );
}
