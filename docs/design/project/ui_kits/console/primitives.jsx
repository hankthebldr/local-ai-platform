/* Enclave Console — cosmetic primitives (self-contained; window-exported). */
/* Ico is React-safe: the lucide SVG lives inside a wrapper span whose children
   React never reconciles, so lucide.createIcons() mutation can't crash React. */
const Ico = ({ n, style, ...p }) => {
  const ref = React.useRef(null);
  React.useEffect(() => {
    const el = ref.current; if (!el) return;
    el.innerHTML = '<i data-lucide="' + n + '"></i>';
    if (window.lucide) window.lucide.createIcons();
    const svg = el.querySelector('svg');
    if (svg && style && style.width) {
      svg.setAttribute('width', parseInt(style.width, 10));
      svg.setAttribute('height', parseInt(style.height || style.width, 10));
    }
  }, [n]);
  return <span ref={ref} style={{ display: 'inline-flex', alignItems: 'center', ...style }} {...p} />;
};

function refreshIcons() { if (window.lucide) window.lucide.createIcons(); }

function Btn({ variant, sm, icon, children, ...p }) {
  return <button className={`btn ${variant || ''} ${sm ? 'sm' : ''}`} {...p}>
    {icon ? <Ico n={icon} /> : null}{children}
  </button>;
}

function IconBtn({ icon, active, bare, label, ...p }) {
  return <button className={`iconbtn ${active ? 'active' : ''} ${bare ? 'bare' : ''}`} title={label} aria-label={label} {...p}>
    {typeof icon === 'string' ? <Ico n={icon} /> : icon}
  </button>;
}

function Badge({ tone, dot, sq, children }) {
  return <span className={`badge ${tone || ''} ${sq ? 'sq' : ''}`}>{dot ? <span className="d" /> : null}{children}</span>;
}

function Pip({ status, live }) { return <span className={`pip ${status || 'idle'} ${live ? 'live' : ''}`} />; }

function MLabel({ children, bare }) { return <span className={`mlabel ${bare ? 'bare' : ''}`}>{children}</span>; }

function Metric({ k, v, percent, color }) {
  const c = color || (percent == null ? 'var(--text)' : percent >= 85 ? 'var(--danger)' : percent >= 65 ? 'var(--warn)' : 'var(--accent)');
  return <div className="metric" style={{ '--mc': c }}>
    <span className="k">{k}</span>
    <span className="v">{v}</span>
    {percent != null ? <span className="bar"><i style={{ width: Math.min(100, percent) + '%' }} /></span> : null}
  </div>;
}

function Logo({ size = 40 }) {
  return <img src="../../assets/logo/enclave-mark-teal.svg" width={size} height={size} alt="Enclave" />;
}

function RoleChip({ item, onAdd }) {
  return <div className={`rolechip tint-${item.kind}`} draggable onClick={() => onAdd && onAdd(item)} title="Click to add to canvas">
    <span className="mk" />
    {item.icon ? <span className="ic"><Ico n={item.icon} /></span> : null}
    <span className="tx">
      <span className="tt">{item.title}</span>
      <span className="dd">{item.desc}</span>
    </span>
    <span className="gp">⋮⋮</span>
  </div>;
}

const ROLE_STATUS_GLYPH = { idle: '', running: '', success: '', error: '' };

function Node({ node, selected, status, inLinked, outLinked, onSelect, hideOut }) {
  return <div className={`node nr-${node.role} ${selected ? 'selected' : ''} ${status || ''}`}
    style={{ left: node.x, top: node.y }} onClick={(e) => { e.stopPropagation(); onSelect(node.id); }}>
    <div className="rule" />
    <span className={`port in ${inLinked ? 'linked' : ''}`} />
    {!hideOut ? <span className={`port out ${outLinked ? 'linked' : ''}`} /> : null}
    <div className="nbody">
      <div className="ntop">
        <span className="nrole">{node.role}</span>
        <span className="nstat"><Pip status={status === 'running' ? 'running' : status === 'success' ? 'success' : status === 'error' ? 'error' : 'idle'} live={status === 'running'} /></span>
      </div>
      <div className="ntitle">{node.title}</div>
      <div className="nmeta"><Ico n="box" /><span className="mdl">{node.model}</span></div>
    </div>
  </div>;
}

/* Cubic bezier edge between two node boxes (right port -> left port). */
function edgePath(a, b, W = 188, H = 78) {
  const x1 = a.x + W, y1 = a.y + H / 2;
  const x2 = b.x, y2 = b.y + H / 2;
  const dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

Object.assign(window, { Ico, refreshIcons, Btn, IconBtn, Badge, Pip, MLabel, Metric, Logo, RoleChip, Node, edgePath });
