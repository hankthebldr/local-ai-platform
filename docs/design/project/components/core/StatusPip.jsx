import React from 'react';

/**
 * Enclave StatusPip — a small status dot. When `live`, it breathes with the
 * teal heartbeat (ds-pip-pulse). The signal that something is alive.
 */

const CSS = `
.encl-pip { display: inline-block; border-radius: 50%; background: var(--_c, var(--text-muted)); flex: none; }
.encl-pip.sz-sm { width: 7px; height: 7px; }
.encl-pip.sz-md { width: 9px; height: 9px; }
.encl-pip.sz-lg { width: 11px; height: 11px; }
.encl-pip.c-online  { --_c: var(--accent); }
.encl-pip.c-success { --_c: var(--success); }
.encl-pip.c-warn    { --_c: var(--warn); }
.encl-pip.c-danger  { --_c: var(--danger); }
.encl-pip.c-info    { --_c: var(--info); }
.encl-pip.c-idle    { --_c: var(--text-muted); }
.encl-pip.live { animation: ds-pip-pulse var(--t-pulse) var(--ease-out) infinite; }
.encl-pip.live.c-success { box-shadow: 0 0 0 0 var(--success-dim); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function StatusPip({ status = 'idle', live = false, size = 'md', className = '', ...rest }) {
  useInjected('encl-pip-css', CSS);
  const colorMap = { online: 'online', running: 'info', success: 'success', warn: 'warn', danger: 'danger', error: 'danger', idle: 'idle' };
  const c = colorMap[status] || 'idle';
  const cls = `encl-pip sz-${size} c-${c} ${live ? 'live' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  return <span className={cls} role="status" {...rest} />;
}
