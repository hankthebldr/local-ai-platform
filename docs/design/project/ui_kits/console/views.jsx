/* Enclave Console — secondary views + app shell. */

function RunsView() {
  const D = window.ENCLAVE;
  React.useEffect(() => { window.refreshIcons(); });
  const barColor = s => s === 'success' ? 'var(--success)' : s === 'error' ? 'var(--danger)' : 'var(--info)';
  return <div className="page">
    <div className="page-head">
      <div className="h">Runs</div>
      <div className="sub">Every workflow execution — streamed, checkpointed, resumable.</div>
      <div className="page-head-spacer" />
      <Btn icon="refresh-cw" sm>Refresh</Btn>
    </div>
    <div className="toolbar">
      <div className="search"><Ico n="search" /><input placeholder="Filter runs…" /></div>
      <Btn sm>All states</Btn><Btn sm>Last 24h</Btn>
    </div>
    <div className="runs-list">
      {D.RUNS.map(r => <div className="run-row" key={r.id}>
        <Pip status={r.state} live={false} />
        <div className="rmain">
          <div className="rwf">{r.wf}</div>
          <div className="rid">{r.id}{r.err ? ' · ' + r.err : ''}</div>
        </div>
        <div className="run-bar"><i style={{ width: Math.round((r.step / r.total) * 100) + '%', background: barColor(r.state) }} /></div>
        <div className="rmeta"><span className="lbl">steps</span>{r.step}/{r.total}</div>
        <div className="rmeta"><span className="lbl">{r.when}</span>{r.dur} · {r.tps} t/s</div>
      </div>)}
    </div>
  </div>;
}

function LibraryView({ onOpen }) {
  const D = window.ENCLAVE;
  React.useEffect(() => { window.refreshIcons(); });
  const catTone = { security: 'accent', code: 'info', research: 'warm' };
  return <div className="page">
    <div className="page-head">
      <div className="h">Library</div>
      <div className="sub">Saved workflows. Open one into the Composer.</div>
      <div className="page-head-spacer" />
      <Btn variant="primary" icon="plus">New Workflow</Btn>
    </div>
    <div className="toolbar">
      <div className="search"><Ico n="search" /><input placeholder="Search workflows…" /></div>
      <Btn sm icon="filter">security</Btn>
    </div>
    <div className="cardgrid">
      {D.WORKFLOWS.map(w => <div className="gcard" key={w.id} onClick={onOpen}>
        <div className="gtop">
          <div className="gico"><Ico n="workflow" /></div>
          <div><div className="gname">{w.name}</div></div>
        </div>
        <div className="gmeta"><span><b>{w.steps}</b> steps</span><span><b>{w.runs}</b> runs</span><span>{w.updated}</span></div>
        <div className="gfoot">
          <Badge tone={catTone[w.category] || 'accent'} sq>{w.category}</Badge>
          <div style={{ flex: 1 }} />
          <Btn sm icon="play">Run</Btn>
        </div>
      </div>)}
    </div>
  </div>;
}

function ModelsView() {
  const D = window.ENCLAVE;
  React.useEffect(() => { window.refreshIcons(); });
  return <div className="page">
    <div className="page-head">
      <div className="h">Models</div>
      <div className="sub">Local GGUF models via Ollama. Q4_K_M default.</div>
      <div className="page-head-spacer" />
      <Btn variant="primary" icon="download">Pull Model</Btn>
    </div>
    <table className="modeltable">
      <thead><tr>
        <th>Model</th><th>Role</th><th>Quant</th><th className="r">Size</th><th className="r">Throughput</th><th className="r">Status</th>
      </tr></thead>
      <tbody>
        {D.MODELS.map(m => <tr key={m.id}>
          <td className="mid">{m.id}</td>
          <td><Badge tone="accent" sq>{m.role}</Badge></td>
          <td className="num">{m.quant}</td>
          <td className="r num">{m.size}</td>
          <td className="r num">{m.tps} t/s</td>
          <td className="r">{m.loaded ? <Badge tone="success" dot>loaded</Badge> : <Badge tone="neutral">on disk</Badge>}</td>
        </tr>)}
      </tbody>
    </table>
  </div>;
}

function ContextView() {
  React.useEffect(() => { window.refreshIcons(); });
  const docs = [
    { n: 'crowdstrike-falcon-schema.md', m: '12 KB · indexed' },
    { n: 'xsiam-data-model.pdf', m: '340 KB · indexed' },
    { n: 'detection-rules-q4.yaml', m: '8 KB · indexed' },
    { n: 'incident-7f3a-export.json', m: '1.2 MB · indexed' },
  ];
  return <div className="page">
    <div className="page-head">
      <div className="h">Context</div>
      <div className="sub">Documents and the knowledge graph your workflows draw on (RAG).</div>
      <div className="page-head-spacer" />
      <Btn variant="primary" icon="upload">Add Document</Btn>
    </div>
    <div className="ctx-grid">
      <div>
        <MLabel>Documents</MLabel>
        <div style={{ marginTop: 12 }}>
          {docs.map((d, i) => <div className="doc-row" key={i}>
            <Ico n="file-text" /><span className="dn">{d.n}</span><span className="dm">{d.m}</span>
          </div>)}
        </div>
      </div>
      <div>
        <MLabel>Knowledge Graph</MLabel>
        <div className="graph-box" style={{ marginTop: 12 }}>
          <img src="../../assets/illustrations/art-rag.svg" alt="knowledge graph" style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.9 }} />
        </div>
      </div>
    </div>
  </div>;
}

/* ── App shell: rail + topbar + router ─────────────────────────────── */
const NAV = [
  { id: 'compose', icon: 'workflow', label: 'Compose' },
  { id: 'runs', icon: 'circle-play', label: 'Runs' },
  { id: 'library', icon: 'library', label: 'Library' },
  { id: 'context', icon: 'database', label: 'Context' },
  { id: 'models', icon: 'boxes', label: 'Models' },
];

function App() {
  const [view, setView] = React.useState('compose');
  React.useEffect(() => { window.refreshIcons(); });

  return <div className="encl-app">
    <div className="rail">
      <div className="rail-logo"><Logo size={40} /></div>
      {NAV.map(n => <div key={n.id} className={`rail-item ${view === n.id ? 'active' : ''}`} onClick={() => setView(n.id)}>
        <Ico n={n.icon} /><span>{n.label}</span>
      </div>)}
      <div className="rail-spacer" />
      <div className="rail-item"><Ico n="settings" /><span>Settings</span></div>
    </div>

    <div className="topbar">
      <div className="topbar-title">
        <span className="nm">{NAV.find(n => n.id === view).label}</span>
        <span className="ctx">enclave · sovereign appliance</span>
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
        <Metric k="Loaded" v="3" />
        <span className="sep" />
        <IconBtn icon="moon" bare label="Theme" />
        <IconBtn icon="command" bare label="Shortcuts" />
      </div>
    </div>

    <div className="view">
      {view === 'compose' ? <Composer /> :
       view === 'runs' ? <RunsView /> :
       view === 'library' ? <LibraryView onOpen={() => setView('compose')} /> :
       view === 'context' ? <ContextView /> :
       view === 'models' ? <ModelsView /> : null}
    </div>
  </div>;
}

window.App = App;
