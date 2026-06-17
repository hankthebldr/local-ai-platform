import React from 'react';

/**
 * Enclave FitBar — a labeled 0-100 fit/score bar. Used for model role-fit,
 * benchmark scores, and capacity readouts in peek panels and compare views.
 */

const CSS = `
.encl-fitbar { display: flex; align-items: center; gap: 8px; }
.encl-fitbar .k { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); width: 56px;
  flex: none; letter-spacing: .08em; text-transform: uppercase; }
.encl-fitbar .bar { flex: 1; height: 4px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; min-width: 40px; }
.encl-fitbar .bar i { display: block; height: 100%; background: var(--fb, var(--accent)); border-radius: var(--radius-pill);
  transition: width var(--t-med) var(--ease-out); }
.encl-fitbar .v { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-dim); width: 26px; text-align: right; }
.encl-fitbar .hint { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function FitBar({ label, value, hint, color, showValue = true, className = '', ...rest }) {
  useInjected('encl-fitbar-css', CSS);
  return (
    <div className={`encl-fitbar ${className}`.trim()} style={color ? { '--fb': color } : undefined} {...rest}>
      <span className="k">{label}</span>
      <span className="bar"><i style={{ width: Math.min(100, Math.max(0, value)) + '%' }} /></span>
      {showValue ? <span className="v">{value}</span> : null}
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}
