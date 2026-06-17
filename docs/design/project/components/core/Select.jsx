import React from 'react';

/**
 * Enclave Select — a labelled dropdown matching the Input styling, with a
 * custom caret. Native <select> under the hood for accessibility.
 */

const CSS = `
.encl-select-field { display: flex; flex-direction: column; gap: 5px; }
.encl-select-label {
  font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted);
}
.encl-select-wrap { position: relative; display: flex; align-items: center; }
.encl-select {
  width: 100%; appearance: none; -webkit-appearance: none;
  font-family: var(--font-sans); font-size: var(--text-base); color: var(--text);
  background: var(--surface-inset); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 8px 30px 8px 11px; cursor: pointer;
  transition: border-color var(--t-fast) var(--ease-out), box-shadow var(--t-fast) var(--ease-out);
}
.encl-select:hover:not(:disabled):not(:focus) { border-color: var(--border-strong); }
.encl-select:focus { outline: none; border-color: var(--accent-dim); box-shadow: 0 0 0 3px var(--accent-ghost); }
.encl-select:disabled { opacity: 0.5; cursor: not-allowed; }
.encl-select-caret { position: absolute; right: 11px; color: var(--text-muted); pointer-events: none; font-size: 10px; }
.encl-select option { background: var(--surface-overlay); color: var(--text); }
.encl-select.mono { font-family: var(--font-mono); font-size: var(--text-sm); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function Select({ label, options = [], children, mono = false, className = '', id, ...rest }) {
  useInjected('encl-select-css', CSS);
  const fid = id || (label ? 'sel-' + String(label).toLowerCase().replace(/\s+/g, '-') : undefined);
  return (
    <div className="encl-select-field">
      {label ? <label className="encl-select-label" htmlFor={fid}>{label}</label> : null}
      <div className="encl-select-wrap">
        <select id={fid} className={`encl-select ${mono ? 'mono' : ''} ${className}`.replace(/\s+/g, ' ').trim()} {...rest}>
          {children || options.map((o) => {
            const val = typeof o === 'string' ? o : o.value;
            const lbl = typeof o === 'string' ? o : o.label;
            return <option key={val} value={val}>{lbl}</option>;
          })}
        </select>
        <span className="encl-select-caret" aria-hidden="true">▾</span>
      </div>
    </div>
  );
}
