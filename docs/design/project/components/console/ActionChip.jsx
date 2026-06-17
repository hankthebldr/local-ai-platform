import React from 'react';

/**
 * Enclave ActionChip — a small mono action/suggestion chip. Two jobs:
 * hover actions on chat messages ("pin as step") and next-best-action
 * nudges above the composer ("convert to a workflow?").
 */

const CSS = `
.encl-actchip { display: inline-flex; align-items: center; gap: 5px; font-family: var(--font-mono);
  font-size: var(--text-2xs); letter-spacing: .04em; padding: 3px 9px; border-radius: var(--radius-pill);
  border: 1px solid var(--border); background: var(--surface-card); color: var(--text-muted); cursor: pointer;
  white-space: nowrap; transition: color var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out); }
.encl-actchip svg { width: 11px; height: 11px; stroke-width: 1.8; }
.encl-actchip:hover { color: var(--accent); border-color: var(--accent-dim); }
.encl-actchip.accent { color: var(--accent); border-color: var(--accent-dim); background: var(--accent-ghost); }
.encl-actchip.accent:hover { background: var(--accent); color: var(--on-accent); }
.encl-actchip.lg { font-size: var(--text-xs); padding: 5px 12px; }
.encl-actchip .x { color: var(--text-faint); margin-left: 2px; }
.encl-actchip .x:hover { color: var(--danger); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function ActionChip({ icon = null, accent = false, lg = false, onDismiss, children, className = '', ...rest }) {
  useInjected('encl-actchip-css', CSS);
  return (
    <span className={`encl-actchip ${accent ? 'accent' : ''} ${lg ? 'lg' : ''} ${className}`.trim()} {...rest}>
      {icon}
      {children}
      {onDismiss ? <span className="x" onClick={(e) => { e.stopPropagation(); onDismiss(e); }} aria-label="Dismiss">×</span> : null}
    </span>
  );
}
