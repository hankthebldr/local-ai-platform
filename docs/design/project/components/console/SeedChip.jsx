import React from 'react';

/**
 * Enclave SeedChip — a key:value chip describing a thread's seed (role, model,
 * context, plugin, agent). Lives in thread headers and the chat composer.
 */

const CSS = `
.encl-seedchip { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono);
  font-size: var(--text-2xs); padding: 3px 9px; border: 1px solid var(--border); border-radius: var(--radius-pill);
  background: var(--surface-card); color: var(--text-dim); white-space: nowrap; }
.encl-seedchip .k { color: var(--text-faint); letter-spacing: .08em; text-transform: uppercase; }
.encl-seedchip.accent { border-color: var(--accent-dim); color: var(--accent); background: var(--accent-ghost); }
.encl-seedchip.ghost { border-style: dashed; background: transparent; color: var(--text-faint); cursor: pointer; }
.encl-seedchip.ghost:hover { color: var(--text-dim); border-color: var(--border-strong); }
.encl-seedchip .x { cursor: pointer; color: var(--text-faint); margin-left: 1px; }
.encl-seedchip .x:hover { color: var(--danger); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function SeedChip({ k, v, tone = 'neutral', ghost = false, onRemove, className = '', ...rest }) {
  useInjected('encl-seedchip-css', CSS);
  return (
    <span className={`encl-seedchip ${tone === 'accent' ? 'accent' : ''} ${ghost ? 'ghost' : ''} ${className}`.trim()} {...rest}>
      {k ? <span className="k">{k}</span> : null}
      <span>{v}</span>
      {onRemove ? <span className="x" onClick={onRemove} aria-label="Remove">×</span> : null}
    </span>
  );
}
