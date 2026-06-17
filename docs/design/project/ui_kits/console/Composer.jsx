/* Enclave Console — Composer view (the workflow-first home). */
function Composer({ sys }) {
  const D = window.ENCLAVE;
  const [nodes, setNodes] = React.useState(D.WORKFLOW.nodes.map(n => ({ ...n })));
  const [edges, setEdges] = React.useState(D.WORKFLOW.edges.map(e => e.slice()));
  const [selId, setSelId] = React.useState('n2');
  const [tab, setTab] = React.useState('roles');
  const [zoom, setZoom] = React.useState(1);
  const [run, setRun] = React.useState({ active: false, done: false, idx: -1, status: {} });
  const [dockOpen, setDockOpen] = React.useState(true);
  const [msgs, setMsgs] = React.useState([
    { who: 'sys', text: 'Composer ready. The canvas above is the design surface — this chat runs the agents you build.' },
  ]);
  const timers = React.useRef([]);

  React.useEffect(() => { window.refreshIcons(); });
  React.useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const order = ['n1', 'n2', 'n3', 'n4'].filter(id => nodes.some(n => n.id === id));
  const sel = nodes.find(n => n.id === selId);

  const paletteItems = {
    roles: D.ROLES, agents: D.AGENTS, skills: D.SKILLS, plugins: D.PLUGINS, mcps: D.MCPS,
  }[tab] || D.ROLES;

  function addNode(item) {
    const isRole = ['reasoning','coding','fast','general','uncensored'].includes(item.kind);
    const role = isRole ? item.kind : (item.role || 'general');
    const id = 'n' + (nodes.length + 1 + Math.floor(Math.random() * 100));
    const maxX = Math.max(...nodes.map(n => n.x), 0);
    const node = { id, title: item.title, role, model: item.model || (D.MODELS.find(m => m.role === role) || {}).id || 'auto',
      x: maxX + 30, y: 150, prompt: item.desc || 'Describe what this step should do.' };
    setNodes(ns => [...ns, node]);
    const last = order[order.length - 1];
    if (last) setEdges(es => [...es, [last, id]]);
    setSelId(id);
  }

  function startRun() {
    timers.current.forEach(clearTimeout); timers.current = [];
    setRun({ active: true, done: false, idx: 0, status: {} });
    setMsgs(m => [...m, { who: 'user', text: 'Run the workflow on the latest CrowdStrike export.' }]);
    let t = 0;
    order.forEach((id, i) => {
      const node = nodes.find(n => n.id === id);
      timers.current.push(setTimeout(() => {
        setRun(r => ({ ...r, idx: i, status: { ...r.status, [id]: 'running' } }));
      }, t += 200));
      timers.current.push(setTimeout(() => {
        setRun(r => ({ ...r, status: { ...r.status, [id]: 'success' } }));
        setMsgs(m => [...m, { who: 'bot', text: `▸ ${node.title} (${node.model}) — ${RUN_LINES[node.title] || 'step complete.'}` }]);
      }, t += 900));
    });
    timers.current.push(setTimeout(() => {
      setRun(r => ({ ...r, active: false, done: true, idx: order.length }));
      setMsgs(m => [...m, { who: 'bot', text: '✓ Workflow complete — 1,284 events normalized, 0 dropped. Emitted to workspace.emit.batch.' }]);
    }, t += 300));
  }

  const runState = run.active ? 'running' : run.done ? 'success' : 'idle';
  const curNode = order[run.idx] ? nodes.find(n => n.id === order[run.idx]) : null;
  const doneCount = Object.values(run.status).filter(s => s === 'success').length;

  return (
    <div className="composer">
      {/* workflow header */}
      <div className="wf-header">
        <div>
          <div className="wf-id">{D.WORKFLOW.id}</div>
          <div className="wf-name">{D.WORKFLOW.name}</div>
        </div>
        <div className="wf-desc">{D.WORKFLOW.desc}</div>
        <div className="wf-header-spacer" />
        {(run.active || run.done) ? (
          <div className="wf-runchip" style={{ '--rc': run.active ? 'var(--info)' : 'var(--success)' }}>
            <Pip status={run.active ? 'running' : 'success'} live={run.active} />
            <span className="lab">{run.active ? 'running' : 'complete'}</span>
            {curNode && run.active ? <span className="cur">{curNode.title}</span> : null}
            <span className="bar"><i style={{ width: Math.round((doneCount / order.length) * 100) + '%' }} /></span>
            <span className="cnt">{doneCount}/{order.length}</span>
          </div>
        ) : null}
        <Btn icon="folder-open" sm>Load</Btn>
        <Btn icon="file-down" sm>Export YAML</Btn>
        <Btn variant="primary" icon="play" onClick={startRun}>Run</Btn>
      </div>

      {/* 3-col body */}
      <div className="composer-body">
        {/* palette */}
        <div className="palette">
          <div className="palette-tabs">
            {['roles','agents','skills','plugins','mcps'].map(t =>
              <div key={t} className={`palette-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t}</div>)}
          </div>
          <div className="palette-hint">{PALETTE_HINT[tab]}</div>
          <div className="palette-list">
            {paletteItems.map((it, i) => <RoleChip key={i} item={it} onAdd={addNode} />)}
          </div>
        </div>

        {/* canvas */}
        <div className="canvas-wrap" onClick={() => setSelId(null)}>
          <div className="canvas-ctrls" onClick={e => e.stopPropagation()}>
            <IconBtn icon="minus" label="Zoom out" onClick={() => setZoom(z => Math.max(0.6, +(z - 0.1).toFixed(2)))} />
            <span className="canvas-zoom">{Math.round(zoom * 100)}%</span>
            <IconBtn icon="plus" label="Zoom in" onClick={() => setZoom(z => Math.min(1.4, +(z + 0.1).toFixed(2)))} />
            <IconBtn icon="rotate-ccw" label="Reset" onClick={() => setZoom(1)} />
            <IconBtn icon="maximize" label="Fullscreen" />
          </div>
          <div className="canvas-stage" style={{ transform: `scale(${zoom})` }}>
            <svg className="canvas-edges">
              {edges.map(([a, b], i) => {
                const na = nodes.find(n => n.id === a), nb = nodes.find(n => n.id === b);
                if (!na || !nb) return null;
                const flowing = run.active && run.status[a] === 'success' && run.status[b] === 'running';
                const done = run.status[a] === 'success' && run.status[b] === 'success';
                return <path key={i} d={edgePath(na, nb)} className={flowing ? 'flow' : done ? 'done' : ''} />;
              })}
            </svg>
            {nodes.map(n => {
              const inLinked = edges.some(e => e[1] === n.id);
              const outLinked = edges.some(e => e[0] === n.id);
              return <Node key={n.id} node={n} selected={selId === n.id} status={run.status[n.id]}
                inLinked={inLinked} outLinked={outLinked} hideOut={!outLinked && n.id === 'n4'} onSelect={setSelId} />;
            })}
          </div>
        </div>

        {/* inspector */}
        <div className="inspector">
          {sel ? <StepConfig node={sel} models={D.MODELS}
            onChange={(k, v) => setNodes(ns => ns.map(n => n.id === sel.id ? { ...n, [k]: v } : n))} />
            : <WorkflowMeta wf={D.WORKFLOW} count={nodes.length} />}
        </div>
      </div>

      {/* dock */}
      <div className={`dock ${dockOpen ? '' : 'collapsed'}`}>
        <div className="dock-head">
          <MLabel>Agent Chat</MLabel>
          <span className="sub">workflow interaction surface</span>
          <div className="dock-head-spacer" />
          <select className="ctl" style={{ width: 160, fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', background: 'var(--surface-card)', border: '1px solid var(--border)', color: 'var(--text-dim)', borderRadius: 'var(--radius-sm)', padding: '5px 8px' }} defaultValue="xsiam-analyst">
            <option>— no agent —</option>
            <option>xsiam-analyst</option>
            <option>normalizer</option>
          </select>
          <IconBtn icon={dockOpen ? 'chevron-down' : 'chevron-up'} bare label="Toggle dock" onClick={() => setDockOpen(o => !o)} />
        </div>
        <div className="dock-body">
          <div className="dock-msgs" ref={el => { if (el) el.scrollTop = el.scrollHeight; }}>
            {msgs.map((m, i) => <div key={i} className={`msg ${m.who}`}>
              {m.who !== 'sys' ? <span className="who">{m.who === 'user' ? 'you' : 'agent'}</span> : null}
              <span className="bubble">{m.text}</span>
            </div>)}
          </div>
          <div className="dock-input">
            <input placeholder="Message the workflow agents…" onKeyDown={e => {
              if (e.key === 'Enter' && e.target.value.trim()) {
                const v = e.target.value; e.target.value = '';
                setMsgs(m => [...m, { who: 'user', text: v }, { who: 'bot', text: 'Queued against the active agent. (demo)' }]);
              }
            }} />
            <Btn variant="primary" icon="send">Send</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

const PALETTE_HINT = {
  roles: 'Drag a role onto the canvas to add a step. (Click to add here.)',
  agents: 'Agents spawn a step pre-configured with role, model, and system prompt.',
  skills: 'Skills auto-attach to steps when their triggers match. Drag to pin.',
  plugins: 'Plugin tools become callable from any step.',
  mcps: 'MCP servers expose external tools to steps.',
};
const RUN_LINES = {
  analyze: 'detected CrowdStrike Falcon schema, 42 fields.',
  normalize: 'mapped 42 → 38 XSIAM fields, 4 dropped as vendor-specific.',
  validate: 'all required keys present (_time, _vendor, event_id).',
  emit: 'rendered NDJSON batch.',
};

function StepConfig({ node, models, onChange }) {
  return <div>
    <div className="insp-sec">
      <MLabel>Step Config</MLabel>
      <div className="field"><label>Step ID</label><input className="mono" value={node.id} readOnly /></div>
      <div className="field"><label>Title</label><input value={node.title} onChange={e => onChange('title', e.target.value)} /></div>
      <div className="field"><label>Role</label>
        <select value={node.role} onChange={e => onChange('role', e.target.value)}>
          {['reasoning','coding','fast','general','uncensored'].map(r => <option key={r}>{r}</option>)}
        </select>
      </div>
      <div className="field"><label>Model</label>
        <select className="mono" value={node.model} onChange={e => onChange('model', e.target.value)}>
          <option value="auto">auto (resolve by role)</option>
          {models.map(m => <option key={m.id} value={m.id}>{m.id}</option>)}
        </select>
      </div>
    </div>
    <div className="insp-sec">
      <MLabel>Prompt</MLabel>
      <div className="field"><textarea value={node.prompt} onChange={e => onChange('prompt', e.target.value)} /></div>
    </div>
    <div className="insp-sec">
      <MLabel>Attached</MLabel>
      <div className="attach-row">
        <Badge tone="accent" sq>cite-sources</Badge>
        <Badge tone="info" sq>web-search</Badge>
        <Btn sm icon="plus">attach</Btn>
      </div>
    </div>
  </div>;
}

function WorkflowMeta({ wf, count }) {
  return <div>
    <div className="insp-sec">
      <MLabel>Workflow</MLabel>
      <div className="field"><label>ID</label><input className="mono" defaultValue={wf.id} /></div>
      <div className="field"><label>Name</label><input defaultValue={wf.name} /></div>
      <div className="field"><label>Default Role</label>
        <select defaultValue={wf.role}>{['reasoning','coding','fast','general','uncensored'].map(r => <option key={r}>{r}</option>)}</select>
      </div>
      <div className="field"><label>Category</label>
        <select defaultValue={wf.category}>{['general','security','devops','data','code','research'].map(r => <option key={r}>{r}</option>)}</select>
      </div>
      <div className="field"><label>Description</label><textarea defaultValue={wf.desc} /></div>
    </div>
    <div className="insp-sec">
      <div className="insp-empty">
        <Ico n="mouse-pointer-click" />
        <div className="t">{count} steps · select a node to edit its config</div>
      </div>
    </div>
  </div>;
}

window.Composer = Composer;
