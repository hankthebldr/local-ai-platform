import React from 'react';

/**
 * Enclave Button — the primary action control.
 * Self-contained: references design tokens via CSS custom properties and
 * injects its own stylesheet once (so :hover / :active / :focus work).
 */

const CSS = `
.encl-btn {
  --_bg: transparent; --_fg: var(--text); --_bd: var(--border);
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  font-family: var(--font-mono); font-weight: 500; letter-spacing: 0.04em;
  white-space: nowrap; cursor: pointer; user-select: none;
  border: 1px solid var(--_bd); background: var(--_bg); color: var(--_fg);
  border-radius: var(--radius-sm);
  transition: transform var(--t-fast) var(--ease-out),
              background-color var(--t-fast) var(--ease-out),
              border-color var(--t-fast) var(--ease-out),
              color var(--t-fast) var(--ease-out),
              box-shadow var(--t-fast) var(--ease-out);
}
.encl-btn:hover:not(:disabled) { transform: translateY(-1px); }
.encl-btn:active:not(:disabled) { transform: translateY(0.5px); }
.encl-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.encl-btn .encl-btn-ico { display: inline-flex; }
.encl-btn .encl-btn-ico svg { width: 1em; height: 1em; stroke-width: 1.85; }

/* sizes */
.encl-btn.sz-sm { font-size: var(--text-2xs); padding: 5px 10px; }
.encl-btn.sz-md { font-size: var(--text-xs);  padding: 7px 14px; }
.encl-btn.sz-lg { font-size: var(--text-sm);  padding: 10px 20px; }

/* variants */
.encl-btn.v-primary { --_bg: var(--accent); --_fg: var(--on-accent); --_bd: var(--accent); }
.encl-btn.v-primary:hover:not(:disabled) { --_bg: var(--accent-bright); --_bd: var(--accent-bright); box-shadow: var(--glow-accent); }

.encl-btn.v-secondary { --_bg: var(--accent-2-ghost); --_fg: var(--accent-2-bright); --_bd: var(--accent-2-dim); }
.encl-btn.v-secondary:hover:not(:disabled) { --_bg: var(--accent-2); --_fg: var(--on-accent-2); --_bd: var(--accent-2); }

.encl-btn.v-ghost { --_bg: transparent; --_fg: var(--text-dim); --_bd: var(--border); }
.encl-btn.v-ghost:hover:not(:disabled) { --_bg: var(--surface-raised); --_fg: var(--text); --_bd: var(--border-strong); }

.encl-btn.v-warm { --_bg: var(--accent-warm-ghost); --_fg: var(--accent-warm); --_bd: var(--accent-warm-dim); }
.encl-btn.v-warm:hover:not(:disabled) { --_bg: var(--accent-warm); --_fg: #1a0d04; --_bd: var(--accent-warm); }

.encl-btn.v-danger { --_bg: var(--danger-ghost); --_fg: var(--danger); --_bd: var(--danger-dim); }
.encl-btn.v-danger:hover:not(:disabled) { --_bg: var(--danger); --_fg: #1a0605; --_bd: var(--danger); }

.encl-btn-spin { width: 1em; height: 1em; border-radius: 50%;
  border: 1.5px solid currentColor; border-top-color: transparent;
  animation: encl-btn-spin 0.7s linear infinite; }
@keyframes encl-btn-spin { to { transform: rotate(360deg); } }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css;
    document.head.appendChild(el);
  }, [id, css]);
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  icon = null,
  loading = false,
  disabled = false,
  type = 'button',
  className = '',
  ...rest
}) {
  useInjected('encl-btn-css', CSS);
  const cls = `encl-btn v-${variant} sz-${size} ${className}`.trim();
  return (
    <button type={type} className={cls} disabled={disabled || loading} {...rest}>
      {loading
        ? <span className="encl-btn-spin" aria-hidden="true" />
        : icon ? <span className="encl-btn-ico" aria-hidden="true">{icon}</span> : null}
      {children}
    </button>
  );
}
