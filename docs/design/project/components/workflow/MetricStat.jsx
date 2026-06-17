import React from 'react';

/**
 * Enclave MetricStat — a compact key/value system metric. Mono caps key,
 * a value in the metric color, optional sub-detail. Used in the system-impact
 * strip (CPU / MEM / Loaded / Version).
 */

const CSS = `
.encl-metric { display: inline-flex; flex-direction: column; gap: 2px; }
.encl-metric.row { flex-direction: row; align-items: baseline; gap: 7px; }
.encl-metric-key { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted); }
.encl-metric-val { font-family: var(--font-mono); font-size: var(--text-base); font-weight: 600; color: var(--_c, var(--text)); line-height: 1.1; }
.encl-metric-sub { font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-faint); }
.encl-metric-bar { height: 3px; background: var(--ink-700); border-radius: var(--radius-pill); overflow: hidden; margin-top: 3px; }
.encl-metric-fill { height: 100%; background: var(--_c, var(--accent)); border-radius: var(--radius-pill); transition: width var(--t-med) var(--ease-out); }
`;

// pick a color by load: calm teal → amber → coral as it climbs
function loadColor(pct) {
  if (pct == null) return 'var(--text)';
  if (pct >= 85) return 'var(--danger)';
  if (pct >= 65) return 'var(--warn)';
  return 'var(--accent)';
}

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

export function MetricStat({
  label, value, sub, percent = null, color, bar = false, row = false, className = '', style = {}, ...rest
}) {
  useInjected('encl-metric-css', CSS);
  const c = color || (percent != null ? loadColor(percent) : 'var(--text)');
  return (
    <div className={`encl-metric ${row ? 'row' : ''} ${className}`.trim()} style={{ ...style, '--_c': c }} {...rest}>
      <span className="encl-metric-key">{label}</span>
      <span className="encl-metric-val">{value}</span>
      {sub ? <span className="encl-metric-sub">{sub}</span> : null}
      {bar && percent != null ? (
        <span className="encl-metric-bar"><span className="encl-metric-fill" style={{ width: Math.min(100, percent) + '%' }} /></span>
      ) : null}
    </div>
  );
}
