import React from 'react';

/**
 * Enclave Sparkline — a tiny inline time-series. The default unit of data
 * visualization in this system: trends live next to the number they explain,
 * not on a dashboard page.
 */

export function Sparkline({ data = [], width = 120, height = 28, color = 'var(--accent)', fill = true, strokeWidth = 1.5, dot = true, max, min, className = '', ...rest }) {
  const hi = max != null ? max : Math.max(...data, 1);
  const lo = min != null ? min : Math.min(...data, 0);
  const span = hi - lo || 1;
  const pad = 2;
  const pw = width - pad * 2, ph = height - pad * 2;
  const pts = data.map((v, i) => [
    pad + (i / Math.max(1, data.length - 1)) * pw,
    pad + ph * (1 - (v - lo) / span),
  ]);
  const line = pts.map(p => p.map(n => +n.toFixed(1)).join(',')).join(' ');
  const area = `${pad},${pad + ph} ${line} ${pad + pw},${pad + ph}`;
  const last = pts[pts.length - 1];
  return (
    <svg className={className} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" {...rest}>
      {fill ? <polygon points={area} fill={color} opacity="0.10" /> : null}
      <polyline points={line} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
      {dot && last ? <circle cx={last[0]} cy={last[1]} r="2" fill={color} /> : null}
    </svg>
  );
}
