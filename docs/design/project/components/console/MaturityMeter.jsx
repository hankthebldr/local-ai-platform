import React from 'react';

/**
 * Enclave MaturityMeter — the adoption-ladder dots on a thread header.
 * Shows how far a conversation has graduated: seed → shape → chain →
 * formalize → operate.
 */

const CSS = `
.encl-meter { display: inline-flex; align-items: center; gap: 4px; }
.encl-meter i { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--border-strong); display: block; }
.encl-meter i.on { background: var(--accent); border-color: var(--accent); }
.encl-meter i.hot { border-color: var(--accent); box-shadow: var(--glow-accent); }
.encl-meter .lab { font-family: var(--font-mono); font-size: var(--text-2xs); letter-spacing: .1em;
  text-transform: uppercase; color: var(--text-faint); margin-right: 3px; }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

const RUNGS = ['seed', 'shape', 'chain', 'formalize', 'operate'];

export function MaturityMeter({ value, total = 5, hot = false, label, className = '', ...rest }) {
  useInjected('encl-meter-css', CSS);
  return (
    <span className={`encl-meter ${className}`.trim()} title={`maturity ${value}/${total} — next: ${RUNGS[Math.min(value, total - 1)]}`} {...rest}>
      {label ? <span className="lab">{label}</span> : null}
      {Array.from({ length: total }, (_, i) =>
        <i key={i} className={i < value ? 'on' : (hot && i === value ? 'hot' : '')} />)}
    </span>
  );
}
