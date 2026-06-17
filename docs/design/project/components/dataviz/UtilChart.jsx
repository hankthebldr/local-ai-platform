import React from 'react';

/**
 * Enclave UtilChart — resource utilization / throughput over time. A calm
 * area chart: warm-charcoal ground, hairline grid at 0/50/100, mono axis
 * labels, up to three series, an optional dashed warn threshold.
 */

const CSS = `
.encl-util { display: flex; flex-direction: column; gap: 8px; }
.encl-util-legend { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.encl-util-key { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: var(--text-2xs); color: var(--text-dim); }
.encl-util-key .d { width: 7px; height: 7px; border-radius: 50%; background: var(--kc); }
.encl-util-key .v { color: var(--text); font-weight: 600; }
.encl-util-key .u { color: var(--text-faint); }
.encl-util svg text { font-family: var(--font-mono); font-size: 9px; fill: var(--text-faint); }
`;

function useInjected(id, css) {
  React.useEffect(() => {
    if (document.getElementById(id)) return;
    const el = document.createElement('style');
    el.id = id; el.textContent = css; document.head.appendChild(el);
  }, [id, css]);
}

const SERIES_COLORS = ['var(--accent)', 'var(--accent-2)', 'var(--info)'];

export function UtilChart({ series = [], width = 560, height = 150, max = 100, unit = '%', xlabels = ['-60m', '-30m', 'now'], warn, className = '', ...rest }) {
  useInjected('encl-util-css', CSS);
  const m = { t: 8, r: 38, b: 16, l: 6 };
  const pw = width - m.l - m.r, ph = height - m.t - m.b;
  const y = v => m.t + ph * (1 - Math.min(v, max) / max);
  const path = data => data.map((v, i) =>
    `${(m.l + (i / Math.max(1, data.length - 1)) * pw).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return (
    <div className={`encl-util ${className}`.trim()} {...rest}>
      <div className="encl-util-legend">
        {series.map((s, i) => {
          const c = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
          return <span key={s.label} className="encl-util-key" style={{ '--kc': c }}>
            <span className="d" /><span>{s.label}</span>
            <span className="v">{s.data[s.data.length - 1]}<span className="u">{unit}</span></span>
          </span>;
        })}
      </div>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={series.map(s => s.label).join(', ') + ' over time'}>
        {[0, 50, 100].map(g => g <= max ? <g key={g}>
          <line x1={m.l} x2={m.l + pw} y1={y(g * max / 100)} y2={y(g * max / 100)} stroke="var(--border)" strokeWidth="1" />
          <text x={m.l + pw + 5} y={y(g * max / 100) + 3}>{Math.round(g * max / 100)}{unit}</text>
        </g> : null)}
        {warn != null ? <g>
          <line x1={m.l} x2={m.l + pw} y1={y(warn)} y2={y(warn)} stroke="var(--warn)" strokeWidth="1" strokeDasharray="4 4" opacity="0.8" />
          <text x={m.l + pw + 5} y={y(warn) + 3} style={{ fill: 'var(--warn)' }}>{warn}{unit}</text>
        </g> : null}
        {series.map((s, i) => {
          const c = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
          const line = path(s.data);
          return <g key={s.label}>
            <polygon points={`${m.l},${m.t + ph} ${line} ${m.l + pw},${m.t + ph}`} fill={c} opacity="0.08" />
            <polyline points={line} fill="none" stroke={c} strokeWidth="1.6" strokeLinejoin="round" />
          </g>;
        })}
        {xlabels.map((xl, i) => <text key={i} y={height - 3}
          x={m.l + (i / Math.max(1, xlabels.length - 1)) * pw}
          textAnchor={i === 0 ? 'start' : i === xlabels.length - 1 ? 'end' : 'middle'}>{xl}</text>)}
      </svg>
    </div>
  );
}
