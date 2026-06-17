/* Enclave Console v2 — app shell: topbar nav + views + operator's path. */

function WorkflowsView({ threads, onOpenThread }) {
  const E = window.ENCLAVE2.ENTITIES;
  React.useEffect(() => { window.refreshIcons(); });
  const catTone = { security: 'accent', code: 'info', research: 'warm' };
  const wfThread = id => threads.find(t => t.kind === 'wf' && (t.name === 'pr review loop' ? id === 'pr-review' : t.name.startsWith('xsiam') && id === 'xsiam-normalize'));
  return <div className="page">
    <div className="page-head">
      <div className="h">Workflows</div>
      <div className="sub">Formalized threads. Each one traces back to the conversation that proved it.</div>
      <div className="page-head-spacer" />
      <Btn variant="primary" icon="git-merge">Convert a thread</Btn>
    </div>
    <div className="cardgrid">
      {E.workflows.map(w => {
        const t = wfThread(w.id);
        return <div className="ecard" key={w.id} style={{ cursor: 'default' }}>
          <div className="ehead">
            <Pip status="idle" />
            <span className="eid">{w.title}</span>
            <Badge tone={catTone[w.category] || 'accent'} sq>{w.category}</Badge>
          </div>
          <div className="emeta">{w.meta}</div>
          {t ? <div className="emeta" style={{ color: 'var(--accent)' }}>born from thread: {t.name}</div> : null}
          <div className="efoot">
            <Btn sm icon="play">Run</Btn>
            <div style={{ flex: 1 }} />
            {t ? <Btn sm icon="workflow" onClick={() => onOpenThread(t.id, 'canvas')}>Open canvas</Btn> :
              <ActChip icon="message-square" title="No source thread — imported from YAML">yaml import</ActChip>}
          </div>
        </div>;
      })}
    </div>
  </div>;
}

function RunsView2({ onOpenThread, onInspect, threads }) {
  const D = window.ENCLAVE;
  const [open, setOpen] = React.useState(null);
  React.useEffect(() => { window.refreshIcons(); });
  const barColor = s => s === 'success' ? 'var(--success)' : s === 'error' ? 'var(--danger)' : 'var(--info)';
  const TRACE = ['analyze', 'normalize', 'validate', 'emit'];
  return <div className="page">
    <div className="page-head">
      <div className="h">Runs</div>
      <div className="sub">Every execution — streamed, checkpointed, resumable. Drill into any step.</div>
      <div className="page-head-spacer" />
      <Btn icon="refresh-cw" sm>Refresh</Btn>
    </div>
    <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start', background: 'var(--surface-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '16px 20px', marginBottom: 18, flexWrap: 'wrap' }}>
      <UtilArea series={[{ label: 'cpu', data: window.ENCLAVE2.UTIL.cpu }, { label: 'mem', data: window.ENCLAVE2.UTIL.mem }]} warn={85} />
      <div style={{ width: 1, alignSelf: 'stretch', background: 'var(--border)' }} />
      <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', paddingTop: 4 }}>
        <Trend label="throughput" value="47 tok/s" delta="+12%" data={window.ENCLAVE2.UTIL.tps} />
        <Trend label="avg run" value="0:41" delta="-9s" good={false} data={window.ENCLAVE2.UTIL.dur} color="var(--accent-2)" />
        <Trend label="runs / day" value="11" delta="+3" data={window.ENCLAVE2.UTIL.runs} color="var(--info)" />
      </div>
    </div>
    <div className="runs-list">
      {D.RUNS.map(r => <React.Fragment key={r.id}>
        <div className="run-row" onClick={() => setOpen(open === r.id ? null : r.id)}>
          <Pip status={r.state} />
          <div className="rmain">
            <div className="rwf">{r.wf}</div>
            <div className="rid">{r.id}{r.err ? ' · ' + r.err : ''}</div>
          </div>
          <div className="run-bar"><i style={{ width: Math.round((r.step / r.total) * 100) + '%', background: barColor(r.state) }} /></div>
          <div className="rmeta"><span className="lbl">steps</span>{r.step}/{r.total}</div>
          <div className="rmeta"><span className="lbl">{r.when}</span>{r.dur} · {r.tps} t/s</div>
        </div>
        {open === r.id ? <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '4px 16px 12px 42px', animation: 'ds-fade-in var(--t-med) var(--ease-out)' }}>
          {TRACE.slice(0, r.total).map((s, i) => {
            const st = i < r.step ? 'success' : (r.state === 'error' && i === r.step - 1 ? 'error' : 'idle');
            return <div key={s} className="userow" style={{ background: 'transparent' }}>
              <Pip status={st === 'idle' ? 'idle' : st} />
              <span className="n">{s}</span>
              <span>{st === 'success' ? RUN_LINES2[s] || 'complete' : st === 'error' ? r.err : 'not reached'}</span>
            </div>;
          })}
          <div style={{ display: 'flex', gap: 8, paddingTop: 2 }}>
            <ActChip icon="activity" acc onClick={() => onInspect(r)}>inspect on canvas</ActChip>
            <ActChip icon="message-square" onClick={() => onOpenThread((threads.find(t => t.kind === 'wf') || threads[0]).id, 'chat')}>open source thread</ActChip>
            <ActChip icon="rotate-ccw">resume from checkpoint</ActChip>
          </div>
        </div> : null}
      </React.Fragment>)}
    </div>
  </div>;
}

function PathPop({ onClose, onGo }) {
  const PATH = window.ENCLAVE2.PATH;
  const done = PATH.filter(p => p.done).length;
  return <div className="pathpop" onClick={e => e.stopPropagation()}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <MLabel bare>Operator's path — {done}/{PATH.length}</MLabel>
      <div style={{ flex: 1 }} />
      <IconBtn icon="x" bare label="Close" onClick={onClose} />
    </div>
    {PATH.map((p, i) => <div key={i} className={`pathrow ${p.done ? 'done' : ''} ${p.hot ? 'hot' : ''} ${!p.done && !p.hot ? 'dim' : ''}`}>
      <span className="n">{p.done ? '✓' : i + 1}</span><span>{p.t}</span>
      {p.hot ? <ActChip acc onClick={onGo}>go →</ActChip> : null}
    </div>)}
    <div style={{ fontSize: 'var(--text-2xs)', color: 'var(--text-faint)', lineHeight: 1.5 }}>
      The console surfaces each rung when you're ready for it — never before.
    </div>
  </div>;
}

const NAV2 = [
  { id: 'chats', icon: 'message-square', label: 'Chats' },
  { id: 'workflows', icon: 'workflow', label: 'Workflows' },
  { id: 'library', icon: 'library', label: 'Library' },
  { id: 'runs', icon: 'circle-play', label: 'Runs' },
];

function App2() {
  const D2 = window.ENCLAVE2;
  const [threads, setThreads] = React.useState(() => D2.THREADS.map(t => ({ ...t, msgs: t.msgs.map(m => ({ ...m })), pins: t.pins.map(p => ({ ...p })) })));
  const [activeId, setActiveId] = React.useState('t1');
  const [view, setView] = React.useState('chats');
  const [pathOpen, setPathOpen] = React.useState(false);
  React.useEffect(() => { window.refreshIcons(); });

  function updateThread(id, fn) {
    setThreads(ts => ts.map(t => t.id === id ? (typeof fn === 'function' ? fn(t) : { ...t, ...fn }) : t));
  }
  function createThread(partial) {
    const id = 't' + Date.now();
    setThreads(ts => [{ id, kind: 'chat', converted: false, mode: 'chat', pins: [], nodes: null, edges: null, msgs: [], ...partial }, ...ts]);
    setActiveId(id); setView('chats');
    return id;
  }
  function seedChatWith(e) {
    const isModel = e.type === 'model';
    createThread({
      name: `test: ${e.id}`, kind: 'chat',
      seed: isModel ? { role: e.role || 'general', model: e.id, ctx: null } : { role: e.role || 'reasoning', model: e.model || 'dolphin-mixtral', ctx: null, agent: e.id },
      msgs: [{ who: 'sys', text: `Seeded from the Library — ${e.type}: ${e.id}. Say something to test it.` }],
    });
  }
  function research() {
    createThread({
      name: 'context research', kind: 'chat',
      seed: { role: 'reasoning', model: 'dolphin-mixtral', ctx: null, plugin: 'web-search' },
      msgs: [{ who: 'sys', text: 'Seeded with web-search — findings can be added to a context bundle.' }],
    });
  }
  function openThread(id, mode) {
    updateThread(id, t => ({ ...t, mode: mode || t.mode }));
    setActiveId(id); setView('chats');
  }
  function inspectRun(r) {
    const t = threads.find(x => x.kind === 'wf') || threads[0];
    updateThread(t.id, x => ({ ...x, mode: 'canvas', lensRun: ['run-7f3a', 'run-7e91', 'run-7e44'].includes(r.id) ? r.id : 'run-7e44' }));
    setActiveId(t.id); setView('chats');
  }

  const activeThread = threads.find(t => t.id === activeId) || threads[0];
  const pathDone = D2.PATH.filter(p => p.done).length;

  return <div className="encl2-app" onClick={() => setPathOpen(false)}>
    <div className="topbar">
      <div className="topbar-logo"><Logo size={30} /></div>
      <div className="navtabs">
        {NAV2.map(n => <div key={n.id} className={`navtab ${view === n.id ? 'active' : ''}`} onClick={() => setView(n.id)}>
          <Ico n={n.icon} />{n.label}
          {n.id === 'chats' ? <span className="cnt">{threads.length}</span> : null}
        </div>)}
      </div>
      <div className="proj-pick">
        <Ico n="folder" /><span className="lbl">Q4 Detection Playbooks</span><span className="car">▾</span>
      </div>
      <div className="topbar-spacer" />
      <div className="sysstrip">
        <div className="health"><Pip status="online" live />API</div>
        <div className="health"><Pip status="online" live />Ollama</div>
        <span className="sep" />
        <Metric k="CPU" v="34%" percent={34} />
        <Metric k="MEM" v="18 / 64" percent={28} />
        <span className="sep" />
        <Btn sm icon="signpost" onClick={e => { e.stopPropagation(); setPathOpen(o => !o); }}>Path {pathDone}/5</Btn>
        <IconBtn icon="command" bare label="Shortcuts" />
      </div>
    </div>

    <div className="view" style={{ position: 'relative' }}>
      {view === 'chats' ? (activeThread.mode === 'canvas' ?
        <CanvasMode thread={activeThread} updateThread={updateThread} /> :
        <ChatHome threads={threads} activeId={activeId} setActiveId={setActiveId} updateThread={updateThread} createThread={createThread} />) : null}
      {view === 'workflows' ? <WorkflowsView threads={threads} onOpenThread={openThread} /> : null}
      {view === 'library' ? <Library2 onSeedChat={seedChatWith} onResearch={research} /> : null}
      {view === 'runs' ? <RunsView2 threads={threads} onOpenThread={openThread} onInspect={inspectRun} /> : null}
    </div>

    {pathOpen ? <PathPop onClose={() => setPathOpen(false)} onGo={() => { setPathOpen(false); openThread('t1', 'chat'); }} /> : null}
  </div>;
}

window.App2 = App2;
