import React from 'react';

/**
 * Enclave Badge — a small status / category pill. Tinted ghost fill + dim
 * border in the semantic hue. Optional leading dot.
 */

const CSS = `
.encl-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: var(--text-2xs);
  font-weight: 500; letter-spacing: 0.10em; text-transform: uppercase;
  padding: 3px 9px; border-radius: var(--radius-pill);
  border: 1px solid var(--_bd, var(--border)); background: var(--_bg, var(--surface-raised)); color: var(--_fg, var(--text-dim));
  line-height: 1.4; white-space: nowrap;
}
.encl-badge.square { border-radius: var(--radius-xs); }
.encl-badge .encl-badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.encl-badge.t-neutral { --_bg: var(--surface-raised); --_fg: var(--text-dim); --_bd: var(--border-strong); }
.encl-badge.t-accent  { --_bg: var(--accent-ghost);   --_fg: var(--accent);   --_bd: var(--accent-dim); }
.encl-badge.t-success { --_bg: var(--success-ghost);  --_fg: var(--success);  --_bd: var(--success-dim); }
.encl-badge.t-warn    { --_bg: var(--warn-ghost);     --_fg: var(--warn);     --_bd: var(--warn-dim); }
.encl-badge.t-danger  { --_bg: var(--danger-ghost);   --_fg: var(--danger);   --_bd: var(--danger-dim); }
.encl-badge.t-info    { --_bg: var(--info-ghost);     --_fg: var(--info);     --_bd: var(--info-dim); }
.encl-badge.t-warm    { --_bg: var(--accent-warm-ghost); --_fg: var(--accent-warm); --_bd: var(--accent-warm-dim); }
.encl-badge.solid.t-accent { --_bg: var(--accent); --_fg: var(--on-accent); --_bd: var(--accent); }
.encl-badge.solid.t-success { --_bg: var(--success); --_fg: #03160f; --_bd: var(--success); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function Badge({
  children, tone = 'neutral', dot = false, square = false, solid = false, className = '', ...rest
}) {
  useInjected('encl-badge-css', CSS);
  const cls = `encl-badge t-${tone} ${square ? 'square' : ''} ${solid ? 'solid' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  return (
    <span className={cls} {...rest}>
      {dot ? <span className="encl-badge-dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
