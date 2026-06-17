/* Enclave Console v2 — shared atoms (window-exported). Reuses v1 primitives. */

function SeedChip({ k, v, acc, ghost, onClick }) {
  return <span className={`seedchip ${acc ? 'acc' : ''} ${ghost ? 'ghost' : ''}`} onClick={onClick}>
    {k ? <span className="k">{k}</span> : null}<span>{v}</span>
  </span>;
}

function Meter({ value, total = 5, hot }) {
  return <span className="rmeter" title={`maturity ${value}/${total}`}>
    {Array.from({ length: total }, (_, i) =>
      <i key={i} className={i < value ? 'on' : (hot && i === value ? 'hot' : '')} />)}
  </span>;
}

function ActChip({ icon, acc, children, onClick, title }) {
  return <span className={`actchip ${acc ? 'acc' : ''}`} onClick={onClick} title={title}>
    {icon ? <Ico n={icon} /> : null}{children}
  </span>;
}

const W_PHASES = ['source', 'configure', 'verify', 'land'];
function WStepper({ active }) {
  return <div className="wsteps">
    {W_PHASES.map((p, i) => <React.Fragment key={p}>
      {i > 0 ? <span className="wconn" /> : null}
      <span className={`wstep ${i < active ? 'done' : ''} ${i === active ? 'on' : ''}`}>
        <span className="n">{i < active ? '✓' : i + 1}</span>{p}
      </span>
    </React.Fragment>)}
  </div>;
}

function MiniNode({ title, role, dash }) {
  return <div className={`minimode ${dash ? 'dash' : ''}`} style={{ '--nr': `var(--node-${role})` }}>
    <div className="rule" /><div className="b"><div className="r">{role}</div><div className="t">{title}</div></div>
  </div>;
}

function Fit({ k, v }) {
  return <div className="efit">
    <span className="k">{k}</span>
    <span className="bar"><i style={{ width: v + '%' }} /></span>
    <span className="v">{v}</span>
  </div>;
}

const TYPE_ICON = {
  model: 'box', agent: 'bot', skill: 'scissors', plugin: 'plug', mcp: 'server',
  context: 'database', workflow: 'workflow', run: 'circle-play', chat: 'message-square',
};
const KIND_TONE = { chat: 'accent', agent: 'info', wf: 'success' };

const PALETTE_HINT2 = {
  roles: 'Click to add a step with the role\u2019s best-fit local model.',
  agents: 'Saved personas — role + model + prompt + pinned context.',
  skills: 'Markdown prompts that auto-inject on trigger keywords.',
  plugins: 'External tools callable from steps.',
  mcps: 'MCP servers — tools over the Model Context Protocol.',
};
const RUN_LINES2 = {
  'analyze': 'schema identified — CrowdStrike FDR, 38 fields.',
  'normalize': 'field map applied — 31 mapped, 7 custom.',
  'validate': 'required keys present on 100% of events.',
  'emit': 'NDJSON batch written to workspace.emit.batch.',
  'lint-pass': '2 style nits, no logic issues.',
  'security-review': 'no injected paths, no secrets in diff.',
  'summarize': 'verdict: approve with comments.',
};

/* ── Kit-local data viz (cosmetic mirrors of the DS dataviz atoms) ── */
function sparkPts(data, w, h) {
  const hi = Math.max(...data, 1), lo = Math.min(...data, 0), span = hi - lo || 1;
  return data.map((v, i) => [2 + (i / Math.max(1, data.length - 1)) * (w - 4), 2 + (h - 4) * (1 - (v - lo) / span)]);
}
function Spark({ data, width = 110, height = 24, color = 'var(--accent)' }) {
  const pts = sparkPts(data, width, height);
  const line = pts.map(p => p.map(n => +n.toFixed(1)).join(',')).join(' ');
  const last = pts[pts.length - 1];
  return <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
    <polygon points={`2,${height - 2} ${line} ${width - 2},${height - 2}`} fill={color} opacity="0.1" />
    <polyline points={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <circle cx={last[0]} cy={last[1]} r="2" fill={color} />
  </svg>;
}
function Trend({ label, value, delta, good = true, data, color = 'var(--accent)' }) {
  const down = delta && delta.startsWith('-');
  const col = !delta ? 'var(--text-faint)' : (down ? !good : good) ? 'var(--success)' : 'var(--accent-warm)';
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-2xs)', fontWeight: 500, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>{label}</span>
    <span style={{ display: 'flex', alignItems: 'baseline', gap: 8, whiteSpace: 'nowrap' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--text-strong)', lineHeight: 1.1 }}>{value}</span>
      {delta ? <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-2xs)', fontWeight: 600, color: col }}>{down ? '▾' : '▴'} {delta.replace(/^-/, '')}</span> : null}
    </span>
    {data ? <Spark data={data} color={color} /> : null}
  </div>;
}
function UtilArea({ series, width = 460, height = 130, max = 100, unit = '%', warn, xlabels = ['-60m', '-30m', 'now'] }) {
  const m = { t: 8, r: 36, b: 16, l: 6 };
  const pw = width - m.l - m.r, ph = height - m.t - m.b;
  const colors = ['var(--accent)', 'var(--accent-2)', 'var(--info)'];
  const y = v => m.t + ph * (1 - Math.min(v, max) / max);
  const path = data => data.map((v, i) => `${(m.l + (i / Math.max(1, data.length - 1)) * pw).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
    <div style={{ display: 'flex', gap: 16, fontFamily: 'var(--font-mono)', fontSize: 'var(--text-2xs)', color: 'var(--text-dim)' }}>
      {series.map((s, i) => <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: colors[i] }} />{s.label}
        <b style={{ color: 'var(--text)' }}>{s.data[s.data.length - 1]}{unit}</b>
      </span>)}
    </div>
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>
      {[0, 50, 100].map(g => <g key={g}>
        <line x1={m.l} x2={m.l + pw} y1={y(g * max / 100)} y2={y(g * max / 100)} stroke="var(--border)" strokeWidth="1" />
        <text x={m.l + pw + 5} y={y(g * max / 100) + 3} fill="var(--text-faint)">{Math.round(g * max / 100)}{unit}</text>
      </g>)}
      {warn != null ? <g>
        <line x1={m.l} x2={m.l + pw} y1={y(warn)} y2={y(warn)} stroke="var(--warn)" strokeWidth="1" strokeDasharray="4 4" opacity="0.8" />
        <text x={m.l + pw + 5} y={y(warn) + 3} fill="var(--warn)">{warn}{unit}</text>
      </g> : null}
      {series.map((s, i) => <g key={s.label}>
        <polygon points={`${m.l},${m.t + ph} ${path(s.data)} ${m.l + pw},${m.t + ph}`} fill={colors[i]} opacity="0.08" />
        <polyline points={path(s.data)} fill="none" stroke={colors[i]} strokeWidth="1.6" strokeLinejoin="round" />
      </g>)}
      {xlabels.map((xl, i) => <text key={i} y={height - 3} x={m.l + (i / Math.max(1, xlabels.length - 1)) * pw} fill="var(--text-faint)"
        textAnchor={i === 0 ? 'start' : i === xlabels.length - 1 ? 'end' : 'middle'}>{xl}</text>)}
    </svg>
  </div>;
}

Object.assign(window, { SeedChip, Meter, ActChip, WStepper, MiniNode, Fit, TYPE_ICON, KIND_TONE, PALETTE_HINT2, RUN_LINES2, W_PHASES, Spark, Trend, UtilArea });
