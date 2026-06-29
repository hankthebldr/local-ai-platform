import React from 'react';

/**
 * Enclave RoleChip — a draggable palette item (role / agent / skill / plugin).
 * Drag onto the Composer canvas to add a step. Role-tinted left marker, a
 * mono title, and an optional one-line description.
 */

const CSS = `
.encl-rolechip {
  display: flex; align-items: center; gap: 10px;
  background: var(--surface-card); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 9px 11px; cursor: grab;
  transition: transform var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out);
}
.encl-rolechip:hover { transform: translateX(2px); border-color: var(--accent-dim); background: var(--surface-raised); }
.encl-rolechip:active { cursor: grabbing; }
.encl-rolechip-mark { flex: none; width: 4px; align-self: stretch; border-radius: var(--radius-pill); background: var(--_tint, var(--accent)); }
.encl-rolechip-ico { flex: none; display: inline-flex; color: var(--_tint, var(--accent)); }
.encl-rolechip-ico svg { width: 15px; height: 15px; stroke-width: 1.8; }
.encl-rolechip-text { min-width: 0; flex: 1; }
.encl-rolechip-title { font-family: var(--font-mono); font-size: var(--text-sm); font-weight: 500; color: var(--text); letter-spacing: 0.02em; }
.encl-rolechip-desc { font-family: var(--font-sans); font-size: var(--text-2xs); color: var(--text-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.encl-rolechip-grip { flex: none; color: var(--text-faint); font-size: 11px; letter-spacing: -2px; }
`;

const TINT = {
  reasoning: 'var(--node-reasoning)', coding: 'var(--node-coding)', fast: 'var(--node-fast)',
  general: 'var(--node-general)', uncensored: 'var(--node-uncensored)',
  agent: 'var(--accent)', skill: 'var(--accent-2)', plugin: 'var(--info)', mcp: 'var(--accent-warm)',
};

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function RoleChip({ title, desc, kind = 'reasoning', icon = null, grip = true, className = '', style = {}, ...rest }) {
  useInjected('encl-rolechip-css', CSS);
  return (
    <div className={`encl-rolechip ${className}`.trim()} draggable style={{ ...style, '--_tint': TINT[kind] || 'var(--accent)' }} {...rest}>
      <span className="encl-rolechip-mark" aria-hidden="true" />
      {icon ? <span className="encl-rolechip-ico" aria-hidden="true">{icon}</span> : null}
      <span className="encl-rolechip-text">
        <span className="encl-rolechip-title">{title}</span>
        {desc ? <span className="encl-rolechip-desc">{desc}</span> : null}
      </span>
      {grip ? <span className="encl-rolechip-grip" aria-hidden="true">⋮⋮</span> : null}
    </div>
  );
}
