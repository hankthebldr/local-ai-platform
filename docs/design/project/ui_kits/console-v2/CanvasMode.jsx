/* Enclave Console v2 — in-shell canvas pivot (the Composer, re-entered from a thread). */

function CanvasMode({ thread, updateThread }) {
  const D = window.ENCLAVE;
  const [selId, setSelId] = React.useState((thread.nodes && thread.nodes[0] || {}).id || null);
  const [tab, setTab] = React.useState('roles');
  const [zoom, setZoom] = React.useState(1);
  const [run, setRun] = React.useState({ active: false, done: false, status: {} });
  const [tests, setTests] = React.useState({});
  const [input, setInput] = React.useState('');
  const timers = React.useRef([]);
  React.useEffect(() => { window.refreshIcons(); });
  React.useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const nodes = thread.nodes || [];
  const edges = thread.edges || [];
  const sel = nodes.find(n => n.id === selId);
  const paletteItems = { roles: D.ROLES, agents: D.AGENTS, skills: D.SKILLS, plugins: D.PLUGINS, mcps: D.MCPS }[tab] || D.ROLES;
  const prevNode = sel ? (edges.filter(e => e[1] === sel.id).map(e => nodes.find(n => n.id === e[0]))[0] || null) : null;

  function patchNodes(fn) { updateThread(thread.id, t => ({ ...t, nodes: fn(t.nodes || []) })); }

  function addNode(item) {
    const isRole = ['reasoning', 'coding', 'fast', 'general', 'uncensored'].includes(item.kind);
    const role = isRole ? item.kind : (item.role || 'general');
    const id = 'n' + Math.floor(Math.random() * 1e6);
    const maxX = Math.max(...nodes.map(n => n.x), 0);
    const node = { id, title: item.title, role, model: item.model || (D.MODELS.find(m => m.role === role) || {}).id || 'auto',
      x: maxX + 260, y: 150, prompt: item.desc || 'Describe what this step should do.' };
    updateThread(thread.id, t => {
      const last = (t.nodes || [])[t.nodes.length - 1];
      return { ...t, nodes: [...(t.nodes || []), node], edges: last ? [...(t.edges || []), [last.id, id]] : (t.edges || []) };
    });
    setSelId(id);
  }

  function testStep() {
    if (!sel) return;
    setTests(ts => ({ ...ts, [sel.id]: { state: 'running' } }));
    timers.current.push(setTimeout(() => {
      setTests(ts => ({ ...ts, [sel.id]: {
        state: 'done',
        out: RUN_LINES2[sel.title] || 'step complete — output conforms to the prompt contract.',
        meta: `✓ ${(D.MODELS.find(m => m.id === sel.model) || { tps: 30 }).tps} tok/s · 1.2s · fixture: ${prevNode ? prevNode.title + ' output' : 'thread message #2'}`,
      } }));
    }, 900));
  }

  function startRun() {
    timers.current.forEach(clearTimeout); timers.current = [];
    setRun({ active: true, done: false, status: {} });
    updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'user', text: 'Run the workflow on the latest export.' }] }));
    let acc = 0;
    nodes.forEach(node => {
      timers.current.push(setTimeout(() => setRun(r => ({ ...r, status: { ...r.status, [node.id]: 'running' } })), acc += 250));
      timers.current.push(setTimeout(() => {
        setRun(r => ({ ...r, status: { ...r.status, [node.id]: 'success' } }));
        updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'bot', text: `▸ ${node.title} (${node.model}) — ${RUN_LINES2[node.title] || 'step complete.'}` }] }));
      }, acc += 850));
    });
    timers.current.push(setTimeout(() => {
      setRun(r => ({ ...r, active: false, done: true }));
      updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'bot', text: '✓ Workflow complete — checkpointed as run-' + Math.floor(Math.random() * 8999 + 1000) + '.' }] }));
    }, acc += 300));
  }

  function send() {
    const text = input.trim(); if (!text) return;
    setInput('');
    updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'user', text }] }));
    setTimeout(() => updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'bot', text: window.ENCLAVE2.REPLIES[(t.msgs.length) % window.ENCLAVE2.REPLIES.length] }] })), 700);
  }

  const doneCount = Object.values(run.status).filter(s => s === 'success').length;
  const test = sel ? tests[sel.id] : null;

  return <div className="composer">
    <div className="wf-header">
      <div className="pivot">
        <button onClick={() => updateThread(thread.id, t => ({ ...t, mode: 'chat' }))}><Ico n="message-square" />Chat</button>
        <button className="on"><Ico n="workflow" />Canvas</button>
      </div>
      <div>
        <div className="wf-id">scaffolded from thread</div>
        <div className="wf-name">{thread.name}</div>
      </div>
      <Badge tone="success" sq>workflow</Badge>
      <div className="wf-header-spacer" />
      {(run.active || run.done) ? <div className="wf-runchip" style={{ '--rc': run.active ? 'var(--info)' : 'var(--success)' }}>
        <Pip status={run.active ? 'running' : 'success'} live={run.active} />
        <span className="lab">{run.active ? 'running' : 'complete'}</span>
        <span className="bar"><i style={{ width: Math.round((doneCount / Math.max(1, nodes.length)) * 100) + '%' }} /></span>
        <span className="cnt">{doneCount}/{nodes.length}</span>
      </div> : null}
      <Btn icon="file-down" sm>Export YAML</Btn>
      <Btn variant="primary" icon="play" onClick={startRun}>Run</Btn>
    </div>

    <div className="composer-body">
      <div className="palette">
        <div className="palette-tabs">
          {['roles', 'agents', 'skills', 'plugins', 'mcps'].map(t =>
            <div key={t} className={`palette-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t}</div>)}
        </div>
        <div className="palette-hint">{PALETTE_HINT2[tab]}</div>
        <div className="palette-list">
          {paletteItems.map((it, i) => <RoleChip key={i} item={it} onAdd={addNode} />)}
        </div>
      </div>

      <div className="canvas-wrap" onClick={() => setSelId(null)}>
        <div className="canvas-ctrls" onClick={e => e.stopPropagation()}>
          <IconBtn icon="minus" label="Zoom out" onClick={() => setZoom(z => Math.max(0.6, +(z - 0.1).toFixed(2)))} />
          <span className="canvas-zoom">{Math.round(zoom * 100)}%</span>
          <IconBtn icon="plus" label="Zoom in" onClick={() => setZoom(z => Math.min(1.4, +(z + 0.1).toFixed(2)))} />
          <IconBtn icon="rotate-ccw" label="Reset" onClick={() => setZoom(1)} />
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
          {nodes.map(n => <Node key={n.id} node={n} selected={n.id === selId} status={run.status[n.id]}
            inLinked={edges.some(e => e[1] === n.id)} outLinked={edges.some(e => e[0] === n.id)}
            onSelect={setSelId} />)}
        </div>
      </div>

      <div className="inspector" onClick={e => e.stopPropagation()}>
        {sel ? <React.Fragment>
          <div className="insp-sec">
            <MLabel>Step — {sel.title}</MLabel>
            <div className="field"><label>Title</label>
              <input className="mono" value={sel.title} onChange={e => patchNodes(ns => ns.map(n => n.id === sel.id ? { ...n, title: e.target.value } : n))} /></div>
            <div className="field"><label>Model</label>
              <select className="mono" value={sel.model} onChange={e => patchNodes(ns => ns.map(n => n.id === sel.id ? { ...n, model: e.target.value } : n))}>
                {D.MODELS.map(m => <option key={m.id} value={m.id}>{m.id} · {m.tps} tok/s</option>)}
              </select></div>
            <div className="field"><label>Prompt</label>
              <textarea className="mono" value={sel.prompt} onChange={e => patchNodes(ns => ns.map(n => n.id === sel.id ? { ...n, prompt: e.target.value } : n))} /></div>
            <div className="attach-row">
              <SeedChip k="role" v={sel.role} />
              {thread.seed.ctx ? <SeedChip k="ctx" v={thread.seed.ctx} acc /> : null}
            </div>
          </div>
          <div className="insp-sec">
            <MLabel>Test step</MLabel>
            <div className="testbench">
              <div className="fx"><Ico n="corner-down-right" />input ← {prevNode ? `${prevNode.title} output` : 'thread message'} · last run</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Btn variant="primary" sm icon="play" onClick={testStep}>{test && test.state === 'running' ? 'Testing…' : 'Test this step only'}</Btn>
              </div>
              {test && test.state === 'done' ? <div className="testresult">
                <span className="meta">{test.meta}</span>
                <span className="out">{test.out}</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <ActChip icon="pin" acc>pin as expectation</ActChip>
                  <ActChip icon="repeat">swap model</ActChip>
                </div>
              </div> : null}
            </div>
          </div>
        </React.Fragment> : <div className="insp-empty"><Ico n="mouse-pointer-click" /><div className="t">Select a step to edit and test it.</div></div>}
      </div>
    </div>

    <div className="dock">
      <div className="dock-head">
        <Pip status="online" live />
        <MLabel bare>{thread.name} — test surface</MLabel>
        <span className="sub">same thread, docked</span>
        <div className="dock-head-spacer" />
        <span className="sub">{thread.msgs.length} messages</span>
      </div>
      <div className="dock-body">
        <div className="dock-msgs">
          {thread.msgs.slice(-6).map((m, i) => m.who === 'sys' ?
            <div key={i} className="msg sys"><div className="bubble">{m.text}</div></div> :
            <div key={i} className={`msg ${m.who === 'user' ? 'user' : 'bot'}`}>
              <span className="who">{m.who === 'user' ? 'you' : 'agent'}</span>
              <span className="bubble">{m.text}</span>
            </div>)}
        </div>
        <div className="dock-input">
          <input placeholder="Exercise the workflow with the conversation that built it…" value={input}
            onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') send(); }} />
          <Btn variant="primary" icon="zap" onClick={send}>Send</Btn>
        </div>
      </div>
    </div>
  </div>;
}

window.CanvasMode = CanvasMode;
