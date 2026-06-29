import React from 'react';

/**
 * Enclave Panel — the signature framed container. A bordered surface with
 * optional corner registration ticks (top-right + bottom-left) and a
 * caps-tracked mono label header. The blueprint frame around everything.
 */

const CSS = `
.encl-panel {
  position: relative;
  background: var(--surface-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--_pad, 16px);
}
.encl-panel.translucent { background: var(--surface-panel); backdrop-filter: blur(var(--blur-panel)); -webkit-backdrop-filter: blur(var(--blur-panel)); }
.encl-panel.flush { border-radius: 0; }
.encl-panel.active { border-color: transparent; box-shadow: var(--glow-accent); }
.encl-panel-corner { position: absolute; width: 9px; height: 9px; pointer-events: none; }
.encl-panel-corner.tr { top: -1px; right: -1px; border-top: 1.5px solid var(--accent); border-right: 1.5px solid var(--accent); }
.encl-panel-corner.bl { bottom: -1px; left: -1px; border-bottom: 1.5px solid var(--accent); border-left: 1.5px solid var(--accent); }
.encl-panel-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.encl-panel-label {
  font-family: var(--font-mono); font-size: var(--text-xs); font-weight: 500;
  letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-muted);
}
.encl-panel-label::before { content: ""; display: inline-block; width: 14px; height: 1px; background: var(--accent); margin-right: 8px; vertical-align: middle; }
.encl-panel-head-extra { margin-left: auto; display: flex; align-items: center; gap: 6px; }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function Panel({
  children, label, headerExtra = null, ticks = true, translucent = false,
  flush = false, active = false, pad, className = '', style = {}, ...rest
}) {
  useInjected('encl-panel-css', CSS);
  const cls = `encl-panel ${translucent ? 'translucent' : ''} ${flush ? 'flush' : ''} ${active ? 'active' : ''} ${className}`.replace(/\s+/g, ' ').trim();
  const st = pad != null ? { ...style, '--_pad': typeof pad === 'number' ? pad + 'px' : pad } : style;
  return (
    <div className={cls} style={st} {...rest}>
      {ticks ? <><span className="encl-panel-corner tr" aria-hidden="true" /><span className="encl-panel-corner bl" aria-hidden="true" /></> : null}
      {(label || headerExtra) ? (
        <div className="encl-panel-head">
          {label ? <span className="encl-panel-label">{label}</span> : <span />}
          {headerExtra ? <span className="encl-panel-head-extra">{headerExtra}</span> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}
