import React from 'react';

/**
 * Enclave TrendStat — a metric with memory: mono label, big mono value,
 * a delta against the previous period, and a sparkline of how it got here.
 * The upgrade path from MetricStat when "now" isn't enough.
 */

const CSS = `
.encl-trend { display: flex; flex-direction: column; gap: 4px; }
.encl-trend-k { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 500; letter-spacing: .14em; text-transform: uppercase; color: var(--text-muted); }
.encl-trend-row { display: flex; align-items: baseline; gap: 8px; white-space: nowrap; }
.encl-trend-v { font-family: var(--font-mono); font-size: var(--text-lg); font-weight: 600; color: var(--text-strong); line-height: 1.1; }
.encl-trend-d { font-family: var(--font-mono); font-size: var(--text-2xs); font-weight: 600; }
.encl-trend-d.up { color: var(--success); }
.encl-trend-d.down { color: var(--accent-warm); }
.encl-trend-d.flat { color: var(--text-faint); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

function spark(data, width, height, color) {
  const hi = Math.max(...data, 1), lo = Math.min(...data, 0), span = hi - lo || 1;
  const pts = data.map((v, i) => [2 + (i / Math.max(1, data.length - 1)) * (width - 4), 2 + (height - 4) * (1 - (v - lo) / span)]);
  const line = pts.map(p => p.map(n => +n.toFixed(1)).join(',')).join(' ');
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polygon points={`2,${height - 2} ${line} ${width - 2},${height - 2}`} fill={color} opacity="0.10" />
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2" fill={color} />
    </svg>
  );
}

export function TrendStat({ label, value, delta, deltaGood = true, data, color = 'var(--accent)', sparkWidth = 110, className = '', ...rest }) {
  useInjected('encl-trend-css', CSS);
  const dir = !delta ? 'flat' : (delta.startsWith('-') ? (deltaGood ? 'down' : 'up') : (deltaGood ? 'up' : 'down'));
  return (
    <div className={`encl-trend ${className}`.trim()} {...rest}>
      <span className="encl-trend-k">{label}</span>
      <span className="encl-trend-row">
        <span className="encl-trend-v">{value}</span>
        {delta ? <span className={`encl-trend-d ${dir}`}>{delta.startsWith('-') ? '▾' : '▴'} {delta.replace(/^-/, '')}</span> : null}
      </span>
      {data ? spark(data, sparkWidth, 24, color) : null}
    </div>
  );
}
