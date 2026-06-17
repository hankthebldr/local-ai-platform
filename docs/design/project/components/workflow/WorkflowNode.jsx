import React from 'react';

/**
 * Enclave WorkflowNode — a single step on the Composer DAG canvas. A compact
 * card with a role-tinted top rule, a title, model + role meta, IO ports, and
 * a run-status pip. The atom of the workflow-first experience.
 */

const CSS = `
.encl-wfnode {
  position: relative; width: 188px;
  background: var(--surface-card); border: 1px solid var(--border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-1);
  font-family: var(--font-sans); cursor: grab;
  transition: transform var(--t-med) var(--ease-out), box-shadow var(--t-med) var(--ease-out), border-color var(--t-med) var(--ease-out);
}
.encl-wfnode:hover { transform: translateY(-2px); box-shadow: var(--elev-2); border-color: var(--accent-dim); }
.encl-wfnode.selected { border-color: transparent; box-shadow: var(--glow-accent); }
.encl-wfnode-rule { height: 3px; border-radius: var(--radius-md) var(--radius-md) 0 0; background: var(--_role, var(--accent)); }
.encl-wfnode-body { padding: 10px 12px 12px; }
.encl-wfnode-top { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; }
.encl-wfnode-role {
  font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase; color: var(--_role, var(--accent));
}
.encl-wfnode-title { font-size: var(--text-base); font-weight: 600; color: var(--text-strong); letter-spacing: -0.01em; line-height: 1.2; }
.encl-wfnode-meta { display: flex; align-items: center; gap: 6px; margin-top: 7px; font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-muted); }
.encl-wfnode-model { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.encl-wfnode-port { position: absolute; top: 50%; width: 11px; height: 11px; border-radius: 50%; background: var(--surface-overlay); border: 1.5px solid var(--border-strong); transform: translateY(-50%); }
.encl-wfnode-port.in { left: -6px; }
.encl-wfnode-port.out { right: -6px; }
.encl-wfnode-port.linked { background: var(--accent); border-color: var(--accent); }
.encl-wfnode-status { margin-left: auto; }
`;

const ROLE_VAR = {
  reasoning: 'var(--node-reasoning)', coding: 'var(--node-coding)', fast: 'var(--node-fast)',
  general: 'var(--node-general)', uncensored: 'var(--node-uncensored)',
};

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function WorkflowNode({
  title = 'step', role = 'general', model = 'auto', status = 'idle',
  selected = false, inPort = true, outPort = true, inLinked = false, outLinked = false,
  className = '', style = {}, children, ...rest
}) {
  useInjected('encl-wfnode-css', CSS);
  const StatusPipLocal = ({ s }) => {
    const map = { running: 'var(--info)', success: 'var(--success)', error: 'var(--danger)', idle: 'var(--text-faint)' };
    return <span style={{ width: 8, height: 8, borderRadius: '50%', background: map[s] || map.idle, display: 'inline-block' }} />;
  };
  return (
    <div className={`encl-wfnode ${selected ? 'selected' : ''} ${className}`.trim()}
         style={{ ...style, '--_role': ROLE_VAR[role] || 'var(--accent)' }} {...rest}>
      <div className="encl-wfnode-rule" />
      {inPort ? <span className={`encl-wfnode-port in ${inLinked ? 'linked' : ''}`} aria-hidden="true" /> : null}
      {outPort ? <span className={`encl-wfnode-port out ${outLinked ? 'linked' : ''}`} aria-hidden="true" /> : null}
      <div className="encl-wfnode-body">
        <div className="encl-wfnode-top">
          <span className="encl-wfnode-role">{role}</span>
          <span className="encl-wfnode-status"><StatusPipLocal s={status} /></span>
        </div>
        <div className="encl-wfnode-title">{title}</div>
        <div className="encl-wfnode-meta">
          <i data-lucide="box" style={{ width: 11, height: 11 }} />
          <span className="encl-wfnode-model">{model}</span>
        </div>
        {children}
      </div>
    </div>
  );
}
