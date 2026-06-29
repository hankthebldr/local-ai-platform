/* Enclave Console v2 — in-shell canvas pivot (the Composer, re-entered from a thread).
   Two lenses on one canvas: Design (edit the structure) and Run (inspect a
   recorded run — scrub timeline, metadata plates, recorded-step inspector). */

const NODE_W = 188, NODE_H = 78;

/* Deterministic per-run, per-node metrics (mock — stands in for checkpoint data). */
function runMeta(runId, nodes) {
  const h = s => { let x = 7; for (const c of s) x = (x * 31 + c.charCodeAt(0)) % 997; return x; };
  const BASE = { reasoning: 14, coding: 8, fast: 3, general: 9, uncensored: 7 };
  return nodes.map(n => {
    const jit = (h(runId + n.id) % 60) / 10 - 3;
    const dur = Math.max(1.8, (BASE[n.role] || 8) + jit);
    const m = (window.ENCLAVE.MODELS.find(x => x.id === n.model) || { tps: 30 });
    const tps = Math.max(4, m.tps + (h(n.id + runId) % 9) - 4);
    return { dur: +dur.toFixed(1), tps };
  });
}

function fmtClock(s) { const m = Math.floor(s / 60); return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`; }

function CanvasMode({ thread, updateThread }) {
  const D = window.ENCLAVE;
  const nodes = thread.nodes || [];
  const edges = thread.edges || [];

  /* Recent runs of this workflow (mock; failIdx pins the error to a step). */
  const RUNS = React.useMemo(() => [
    { id: 'run-7f3a', when: '2m ago', state: 'success' },
    { id: 'run-7e91', when: '18m ago', state: 'success' },
    { id: 'run-7e44', when: '1h ago', state: 'error', failIdx: Math.min(2, Math.max(0, nodes.length - 2)), err: 'contract violated — missing required key `_time`' },
  ], [nodes.length]);

  const [selId, setSelId] = React.useState((nodes[0] || {}).id || null);
  const [tab, setTab] = React.useState('roles');
  const [zoom, setZoom] = React.useState(1);
  const [run, setRun] = React.useState({ active: false, done: false, status: {} });
  const [tests, setTests] = React.useState({});
  const [input, setInput] = React.useState('');
  const [lens, setLens] = React.useState(thread.lensRun ? 'run' : 'design');
  const [runId, setRunId] = React.useState(thread.lensRun || RUNS[0].id);
  const [scrub, setScrub] = React.useState(null); // null = derive default
  const timers = React.useRef([]);
  React.useEffect(() => { window.refreshIcons(); });
  React.useEffect(() => () => timers.current.forEach(clearTimeout), []);

  /* Arriving from the Runs view ("inspect on canvas") while already mounted. */
  React.useEffect(() => {
    if (thread.lensRun) {
      setLens('run'); setRunId(thread.lensRun); setScrub(null);
      updateThread(thread.id, t => ({ ...t, lensRun: null }));
    }
  }, [thread.lensRun]);

  const sel = nodes.find(n => n.id === selId);
  const selIdx = nodes.findIndex(n => n.id === selId);
  const paletteItems = { roles: D.ROLES, agents: D.AGENTS, skills: D.SKILLS, plugins: D.PLUGINS, mcps: D.MCPS }[tab] || D.ROLES;
  const prevNode = sel ? (edges.filter(e => e[1] === sel.id).map(e => nodes.find(n => n.id === e[0]))[0] || null) : null;

  /* ── Run lens derivations ── */
  const curRun = RUNS.find(r => r.id === runId) || RUNS[0];
  const meta = React.useMemo(() => runMeta(curRun.id, nodes), [curRun.id, nodes]);
  const isErr = curRun.state === 'error';
  const lastIdx = isErr ? curRun.failIdx : nodes.length; // n = complete
  const pos = scrub == null ? lastIdx : Math.min(scrub, lastIdx);
  const wall = meta.slice(0, isErr ? curRun.failIdx + 1 : meta.length).reduce((a, m) => a + m.dur, 0);

  const runStatus = {};
  if (lens === 'run') nodes.forEach((n, i) => {
    runStatus[n.id] = i < pos ? 'success' : (i === pos && pos < nodes.length) ? (isErr && i === curRun.failIdx ? 'error' : 'running') : undefined;
  });
  const liveStatus = lens === 'run' ? runStatus : run.status;

  function playRun() {
    timers.current.forEach(clearTimeout); timers.current = [];
    setScrub(0);
    for (let k = 1; k <= lastIdx; k++) timers.current.push(setTimeout(() => setScrub(k), k * 650));
  }

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
    setLens('design');
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
      updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'bot', text: '✓ Workflow complete — checkpointed as run-7f3a.' }] }));
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
      <div className="pivot" style={{ marginLeft: 6 }}>
        <button className={lens === 'design' ? 'on' : ''} onClick={() => setLens('design')}><Ico n="pen-line" />Design</button>
        <button className={lens === 'run' ? 'on' : ''} onClick={() => { setLens('run'); setScrub(null); }}><Ico n="activity" />Run lens</button>
      </div>
      <div className="wf-header-spacer" />
      {lens === 'design' && (run.active || run.done) ? <div className="wf-runchip" style={{ '--rc': run.active ? 'var(--info)' : 'var(--success)' }}>
        <Pip status={run.active ? 'running' : 'success'} live={run.active} />
        <span className="lab">{run.active ? 'running' : 'complete'}</span>
        <span className="bar"><i style={{ width: Math.round((doneCount / Math.max(1, nodes.length)) * 100) + '%' }} /></span>
        <span className="cnt">{doneCount}/{nodes.length}</span>
      </div> : null}
      {lens === 'design' && run.done ? <ActChip icon="activity" acc onClick={() => { setLens('run'); setRunId('run-7f3a'); setScrub(null); }}>inspect this run →</ActChip> : null}
      {lens === 'run' ? <span className="runlens-meta">{curRun.id} · {isErr ? `failed at ${nodes[curRun.failIdx] ? nodes[curRun.failIdx].title : 'step'}` : 'complete'} · {fmtClock(wall)}</span> : null}
      <Btn icon="file-down" sm>Export YAML</Btn>
      {lens === 'design' ? <Btn variant="primary" icon="play" onClick={startRun}>Run</Btn> :
        <Btn variant="primary" icon="rotate-ccw" sm onClick={startRun}>Re-run</Btn>}
    </div>

    <div className="composer-body">
      {lens === 'design' ? <div className="palette">
        <div className="palette-tabs">
          {['roles', 'agents', 'skills', 'plugins', 'mcps'].map(t =>
            <div key={t} className={`palette-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t}</div>)}
        </div>
        <div className="palette-hint">{PALETTE_HINT2[tab]}</div>
        <div className="palette-list">
          {paletteItems.map((it, i) => <RoleChip key={i} item={it} onAdd={addNode} />)}
        </div>
      </div> : <div className="runrail">
        <div className="runrail-head"><MLabel bare>Recent runs</MLabel></div>
        <div className="runrail-hint">Pick a run to paint it onto the canvas. Segments are sized by wall-clock share.</div>
        <div className="runrail-list">
          {RUNS.map(r => {
            const m = runMeta(r.id, nodes);
            const tot = m.reduce((a, x) => a + x.dur, 0) || 1;
            return <div key={r.id} className={`runcard ${r.id === runId ? 'on' : ''}`} onClick={() => { setRunId(r.id); setScrub(null); }}>
              <div className="top"><Pip status={r.state} /><span className="rid">{r.id}</span><span className="rwhen">{r.when}</span></div>
              <div className="segbar">
                {nodes.map((n, i) => <i key={n.id} style={{ width: (m[i].dur / tot * 100) + '%',
                  background: r.state === 'error' && i === r.failIdx ? 'var(--danger)' : r.state === 'error' && i > r.failIdx ? 'var(--ink-700)' : 'var(--accent-2)' }} />)}
              </div>
            </div>;
          })}
        </div>
        <div className="runrail-foot">Inspecting is non-destructive — the structure stays editable in the Design lens.</div>
      </div>}

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
              const sa = liveStatus[a], sb = liveStatus[b];
              const flowing = (lens === 'run' || run.active) && sa === 'success' && (sb === 'running' || sb === 'error');
              const done = sa === 'success' && sb === 'success';
              return <path key={i} d={edgePath(na, nb)} className={flowing ? 'flow' : done ? 'done' : ''} />;
            })}
          </svg>
          {nodes.map(n => <Node key={n.id} node={n} selected={n.id === selId} status={liveStatus[n.id]}
            inLinked={edges.some(e => e[1] === n.id)} outLinked={edges.some(e => e[0] === n.id)}
            onSelect={setSelId} />)}
          {lens === 'run' ? nodes.map((n, i) => {
            const executed = i < pos || (isErr && i === curRun.failIdx && pos >= curRun.failIdx);
            if (!executed) return null;
            const bad = isErr && i === curRun.failIdx;
            return <div key={'p' + n.id} className={`nodeplate ${bad ? 'err' : ''}`} style={{ left: n.x, top: n.y + NODE_H + 6 }}>
              <span>{meta[i].dur}s</span><span>{meta[i].tps} tok/s</span>{bad ? <span>✕ contract</span> : null}
            </div>;
          }) : null}
        </div>

        {lens === 'run' ? <div className="scrubber" onClick={e => e.stopPropagation()}>
          <div className="scrub-head">
            <IconBtn icon="play" label="Replay run" onClick={playRun} />
            <span className="scrub-lab">{pos >= nodes.length ? 'complete' : `step ${pos + 1}/${nodes.length} — ${nodes[pos] ? nodes[pos].title : ''}`}</span>
            <div style={{ flex: 1 }} />
            {isErr ? <ActChip icon="zap" acc onClick={() => { setScrub(curRun.failIdx); setSelId(nodes[curRun.failIdx] && nodes[curRun.failIdx].id); }}>jump to failure</ActChip> : null}
            <span className="scrub-lab">{fmtClock(wall)} wall</span>
          </div>
          <div className="scrub-bar">
            {nodes.map((n, i) => {
              const w = (meta[i].dur / (meta.reduce((a, m) => a + m.dur, 0) || 1)) * 100;
              const cls = isErr && i === curRun.failIdx ? 'err' : i < pos ? 'done' : i === pos ? 'cur' : '';
              const reach = !isErr || i <= curRun.failIdx;
              return <div key={n.id} className={`scrub-seg ${cls} ${reach ? '' : 'dead'}`} style={{ width: w + '%' }}
                onClick={() => { if (reach) { setScrub(i); setSelId(n.id); } }} title={`${n.title} · ${meta[i].dur}s`}>
                <span className="lb">{n.title} · {meta[i].dur}s</span>
              </div>;
            })}
          </div>
        </div> : null}
      </div>

      <div className="inspector" onClick={e => e.stopPropagation()}>
        {lens === 'run' && sel ? <React.Fragment>
          <div className="insp-sec">
            <MLabel>Recorded — {sel.title}</MLabel>
            <div className="runkv">
              <span className="k">run</span><span className="v">{curRun.id}</span>
              <span className="k">status</span><span className="v" style={{ color: isErr && selIdx === curRun.failIdx ? 'var(--danger)' : selIdx < pos ? 'var(--success)' : 'var(--text-dim)' }}>
                {isErr && selIdx === curRun.failIdx ? 'error' : selIdx < pos ? 'success' : selIdx === pos ? 'running' : 'not reached'}</span>
              <span className="k">duration</span><span className="v">{meta[selIdx] ? meta[selIdx].dur + 's' : '—'}</span>
              <span className="k">throughput</span><span className="v">{meta[selIdx] ? meta[selIdx].tps + ' tok/s' : '—'}</span>
              <span className="k">model</span><span className="v">{sel.model}</span>
            </div>
          </div>
          <div className="insp-sec">
            <MLabel>As executed</MLabel>
            <div className="asexec">
              <div className="px">{sel.prompt}</div>
              <div className="inj">+ injected: {thread.seed.ctx ? `ctx ${thread.seed.ctx} · ` : ''}skill json-strict</div>
            </div>
            {isErr && selIdx === curRun.failIdx ? <div className="runerr">{curRun.err}<br />Violated on edge {nodes[selIdx - 1] ? nodes[selIdx - 1].title : 'input'} → {sel.title}.</div> :
              selIdx < pos ? <div className="testresult" style={{ marginTop: 8 }}>
                <span className="meta">output</span>
                <span className="out">{RUN_LINES2[sel.title] || 'step complete — output archived in the checkpoint.'}</span>
              </div> : null}
            <div className="attach-row" style={{ marginTop: 10 }}>
              <ActChip icon="pin" acc>pin output as fixture</ActChip>
              <ActChip icon="message-square" onClick={() => updateThread(thread.id, t => ({ ...t, mode: 'chat' }))}>open thread here</ActChip>
              <ActChip icon="rotate-ccw">re-run from this step</ActChip>
            </div>
          </div>
        </React.Fragment> : sel ? <React.Fragment>
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
        </React.Fragment> : <div className="insp-empty"><Ico n="mouse-pointer-click" /><div className="t">{lens === 'run' ? 'Select a step — or a timeline segment — to read the recorded execution.' : 'Select a step to edit and test it.'}</div></div>}
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
