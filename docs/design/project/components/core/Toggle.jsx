import React from 'react';

/**
 * Enclave Toggle — a compact switch. Teal track when on. Optional inline
 * label. Controlled (checked + onChange) or uncontrolled (defaultChecked).
 */

const CSS = `
.encl-toggle { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; user-select: none; }
.encl-toggle.disabled { opacity: 0.5; cursor: not-allowed; }
.encl-toggle-track {
  position: relative; flex: none; width: 34px; height: 19px;
  background: var(--ink-700); border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill); transition: background var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out);
}
.encl-toggle-thumb {
  position: absolute; top: 1.5px; left: 1.5px; width: 14px; height: 14px;
  background: var(--text-dim); border-radius: 50%;
  transition: transform var(--t-fast) var(--ease-snap), background var(--t-fast) var(--ease-out);
}
.encl-toggle.on .encl-toggle-track { background: var(--accent); border-color: var(--accent); }
.encl-toggle.on .encl-toggle-thumb { transform: translateX(15px); background: var(--on-accent); }
.encl-toggle-label { font-family: var(--font-sans); font-size: var(--text-sm); color: var(--text); }
.encl-toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.encl-toggle:focus-within .encl-toggle-track { box-shadow: 0 0 0 3px var(--accent-ghost); }
.encl-toggle.sz-sm .encl-toggle-track { width: 28px; height: 16px; }
.encl-toggle.sz-sm .encl-toggle-thumb { width: 11px; height: 11px; }
.encl-toggle.sz-sm.on .encl-toggle-thumb { transform: translateX(12px); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function Toggle({
  checked, defaultChecked, onChange, label, size = 'md', disabled = false, className = '', ...rest
}) {
  useInjected('encl-toggle-css', CSS);
  const isControlled = checked !== undefined;
  const [internal, setInternal] = React.useState(!!defaultChecked);
  const on = isControlled ? checked : internal;
  const handle = (e) => { if (!isControlled) setInternal(e.target.checked); onChange && onChange(e); };
  return (
    <label className={`encl-toggle sz-${size} ${on ? 'on' : ''} ${disabled ? 'disabled' : ''} ${className}`.replace(/\s+/g, ' ').trim()}>
      <span className="encl-toggle-track"><span className="encl-toggle-thumb" /></span>
      <input type="checkbox" checked={on} onChange={handle} disabled={disabled} {...rest} />
      {label ? <span className="encl-toggle-label">{label}</span> : null}
    </label>
  );
}
