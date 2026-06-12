import React from 'react';

/**
 * Enclave RunStatus — a workflow-run progress strip. A status pip + label, a
 * step counter, and a thin progress bar. Used on the canvas run chip and in
 * the Runs list.
 */

const CSS = `
.encl-runstatus {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono); font-size: var(--text-xs);
  background: var(--surface-panel); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 7px 11px; backdrop-filter: blur(var(--blur-panel));
}
.encl-runstatus-pip { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--_c); }
.encl-runstatus.running .encl-runstatus-pip { animation: ds-pip-pulse var(--t-pulse) var(--ease-out) infinite; }
.encl-runstatus-label { color: var(--_c); letter-spacing: 0.06em; text-transform: uppercase; font-weight: 600; }
.encl-runstatus-current { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }
.encl-runstatus-count { color: var(--text-muted); margin-left: auto; flex: none; }
.encl-runstatus-bar { position: relative; flex: 1; min-width: 60px; height: 4px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; }
.encl-runstatus-fill { position: absolute; inset: 0 auto 0 0; background: var(--_c); border-radius: var(--radius-pill); transition: width var(--t-med) var(--ease-out); }
`;

const STATE = {
  running: { c: 'var(--info)', label: 'running' },
  success: { c: 'var(--success)', label: 'complete' },
  error:   { c: 'var(--danger)', label: 'failed' },
  queued:  { c: 'var(--text-muted)', label: 'queued' },
  idle:    { c: 'var(--text-faint)', label: 'idle' },
};

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function RunStatus({ state = 'running', current = '', step = 0, total = 0, showBar = true, className = '', style = {}, ...rest }) {
  useInjected('encl-runstatus-css', CSS);
  const s = STATE[state] || STATE.idle;
  const pct = total > 0 ? Math.round((step / total) * 100) : (state === 'success' ? 100 : 0);
  return (
    <div className={`encl-runstatus ${state} ${className}`.trim()} style={{ ...style, '--_c': s.c }} role="status" aria-live="polite" {...rest}>
      <span className="encl-runstatus-pip" aria-hidden="true" />
      <span className="encl-runstatus-label">{s.label}</span>
      {current ? <span className="encl-runstatus-current">{current}</span> : null}
      {showBar ? <span className="encl-runstatus-bar"><span className="encl-runstatus-fill" style={{ width: pct + '%' }} /></span> : null}
      {total > 0 ? <span className="encl-runstatus-count">{step}/{total}</span> : null}
    </div>
  );
}
