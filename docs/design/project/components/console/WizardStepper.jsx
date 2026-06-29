import React from 'react';

/**
 * Enclave WizardStepper — the unified install wizard's phase header.
 * One skeleton for every object type: source → configure → verify → land.
 */

const CSS = `
.encl-wsteps { display: flex; align-items: center; gap: 8px; }
.encl-wstep { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: var(--text-2xs);
  letter-spacing: .1em; text-transform: uppercase; color: var(--text-faint); white-space: nowrap; }
.encl-wstep .n { width: 20px; height: 20px; border-radius: 50%; border: 1.5px solid var(--border-strong); display: inline-flex;
  align-items: center; justify-content: center; font-size: 10px; flex: none; }
.encl-wstep.done { color: var(--text-dim); }
.encl-wstep.done .n { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.encl-wstep.on { color: var(--accent); }
.encl-wstep.on .n { border-color: var(--accent); color: var(--accent); box-shadow: var(--glow-accent); }
.encl-wconn { flex: 1; height: 1px; background: var(--border); min-width: 14px; }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

const DEFAULT_PHASES = ['source', 'configure', 'verify', 'land'];

export function WizardStepper({ phases = DEFAULT_PHASES, active = 0, className = '', ...rest }) {
  useInjected('encl-wsteps-css', CSS);
  return (
    <div className={`encl-wsteps ${className}`.trim()} {...rest}>
      {phases.map((p, i) => (
        <React.Fragment key={p}>
          {i > 0 ? <span className="encl-wconn" aria-hidden="true" /> : null}
          <span className={`encl-wstep ${i < active ? 'done' : ''} ${i === active ? 'on' : ''}`}>
            <span className="n">{i < active ? '✓' : i + 1}</span>{p}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
}
