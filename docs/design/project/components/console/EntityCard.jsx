import React from 'react';

/**
 * Enclave EntityCard — the unified drill-down card. One anatomy for every
 * entity type: status pip + mono id + type badge, a mono meta line, optional
 * role-fit bars, and a dependents footer. Click opens the peek panel.
 */

const CSS = `
.encl-ecard { background: var(--surface-card); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 14px 15px; cursor: pointer; display: flex; flex-direction: column; gap: 9px;
  transition: border-color var(--t-med) var(--ease-out), transform var(--t-med) var(--ease-out), box-shadow var(--t-med) var(--ease-out); }
.encl-ecard:hover { border-color: var(--accent-dim); transform: translateY(-2px); box-shadow: var(--elev-2); }
.encl-ecard.selected { border-color: var(--accent-dim); box-shadow: var(--glow-accent); }
.encl-ecard-head { display: flex; align-items: center; gap: 8px; }
.encl-ecard-pip { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); flex: none; }
.encl-ecard-pip.online { background: var(--accent); }
.encl-ecard-pip.error { background: var(--danger); }
.encl-ecard-id { font-family: var(--font-mono); font-size: var(--text-sm); font-weight: 600; color: var(--text-strong);
  flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.encl-ecard-type { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500; letter-spacing: .1em;
  text-transform: uppercase; padding: 3px 8px; border-radius: var(--radius-xs); border: 1px solid var(--accent-dim);
  background: var(--accent-ghost); color: var(--accent); white-space: nowrap; }
.encl-ecard-meta { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-muted); }
.encl-ecard-desc { font-size: var(--text-sm); color: var(--text-dim); line-height: 1.45; }
.encl-ecard-fits { display: flex; flex-direction: column; gap: 5px; }
.encl-ecard-fit { display: flex; align-items: center; gap: 8px; }
.encl-ecard-fit .k { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); width: 56px;
  flex: none; letter-spacing: .08em; text-transform: uppercase; }
.encl-ecard-fit .bar { flex: 1; height: 4px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; }
.encl-ecard-fit .bar i { display: block; height: 100%; background: var(--accent); border-radius: var(--radius-pill); }
.encl-ecard-fit .v { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-dim); width: 26px; text-align: right; }
.encl-ecard-foot { display: flex; align-items: center; gap: 7px; margin-top: auto; padding-top: 9px; border-top: 1px solid var(--border-faint); }
.encl-ecard-used { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-muted); flex: 1; min-width: 0; }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function EntityCard({ id, type = 'model', status = 'idle', meta, desc, fits, usedBy, selected, actions, className = '', ...rest }) {
  useInjected('encl-ecard-css', CSS);
  return (
    <div className={`encl-ecard ${selected ? 'selected' : ''} ${className}`.trim()} {...rest}>
      <div className="encl-ecard-head">
        <span className={`encl-ecard-pip ${status}`} aria-hidden="true" />
        <span className="encl-ecard-id">{id}</span>
        <span className="encl-ecard-type">{type}</span>
      </div>
      {meta ? <div className="encl-ecard-meta">{meta}</div> : null}
      {desc ? <div className="encl-ecard-desc">{desc}</div> : null}
      {fits ? <div className="encl-ecard-fits">
        {Object.entries(fits).map(([k, v]) => <div key={k} className="encl-ecard-fit">
          <span className="k">{k}</span>
          <span className="bar"><i style={{ width: Math.min(100, v) + '%' }} /></span>
          <span className="v">{v}</span>
        </div>)}
      </div> : null}
      {(usedBy || actions) ? <div className="encl-ecard-foot">
        {usedBy ? <span className="encl-ecard-used">{usedBy}</span> : <span style={{ flex: 1 }} />}
        {actions}
      </div> : null}
    </div>
  );
}
