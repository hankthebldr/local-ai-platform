import React from 'react';

/**
 * Enclave Input — a labelled text field. Mono label above, dark inset field,
 * teal focus ring. Works as text / password / number / search.
 */

const CSS = `
.encl-field { display: flex; flex-direction: column; gap: 5px; }
.encl-field-label {
  font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted);
}
.encl-field-label .req { color: var(--accent); margin-left: 3px; }
.encl-input-wrap { position: relative; display: flex; align-items: center; }
.encl-input-wrap .encl-input-ico { position: absolute; left: 10px; display: inline-flex; color: var(--text-muted); pointer-events: none; }
.encl-input-wrap .encl-input-ico svg { width: 14px; height: 14px; stroke-width: 1.8; }
.encl-input {
  width: 100%; font-family: var(--font-sans); font-size: var(--text-base);
  color: var(--text); background: var(--surface-inset);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 8px 11px; transition: border-color var(--t-fast) var(--ease-out), box-shadow var(--t-fast) var(--ease-out);
}
.encl-input.has-ico { padding-left: 30px; }
.encl-input::placeholder { color: var(--text-faint); }
.encl-input:hover:not(:disabled):not(:focus) { border-color: var(--border-strong); }
.encl-input:focus { outline: none; border-color: var(--accent-dim); box-shadow: 0 0 0 3px var(--accent-ghost); }
.encl-input:disabled { opacity: 0.5; cursor: not-allowed; }
.encl-input.invalid { border-color: var(--danger-dim); }
.encl-input.invalid:focus { box-shadow: 0 0 0 3px var(--danger-ghost); }
.encl-field-hint { font-size: var(--text-sm); color: var(--text-faint); }
.encl-field-hint.error { color: var(--danger); }
.encl-input.mono { font-family: var(--font-mono); font-size: var(--text-sm); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function Input({
  label, hint, error, icon = null, required = false, mono = false,
  className = '', id, ...rest
}) {
  useInjected('encl-input-css', CSS);
  const fid = id || (label ? 'in-' + String(label).toLowerCase().replace(/\s+/g, '-') : undefined);
  return (
    <div className="encl-field">
      {label ? <label className="encl-field-label" htmlFor={fid}>{label}{required ? <span className="req">*</span> : null}</label> : null}
      <div className="encl-input-wrap">
        {icon ? <span className="encl-input-ico" aria-hidden="true">{icon}</span> : null}
        <input id={fid} className={`encl-input ${icon ? 'has-ico' : ''} ${mono ? 'mono' : ''} ${error ? 'invalid' : ''} ${className}`.replace(/\s+/g, ' ').trim()} {...rest} />
      </div>
      {error ? <span className="encl-field-hint error">{error}</span> : hint ? <span className="encl-field-hint">{hint}</span> : null}
    </div>
  );
}
