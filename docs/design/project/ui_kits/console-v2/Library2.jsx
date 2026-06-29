/* Enclave Console v2 — Library: unified entity cards, peek panel, compare, install wizard. */

const LIB_TABS = [
  { id: 'models', label: 'Models', wiz: 'model' },
  { id: 'agents', label: 'Agents', wiz: 'agent' },
  { id: 'skills', label: 'Skills', wiz: 'skill' },
  { id: 'plugins', label: 'Plugins · MCP', wiz: 'plugin' },
  { id: 'contexts', label: 'Contexts', wiz: null },
];

function ECard({ e, sel, onPeek }) {
  return <div className={`ecard ${sel ? 'sel' : ''}`} onClick={onPeek}>
    <div className="ehead">
      <Pip status={e.status === 'online' ? 'online' : 'idle'} live={e.status === 'online'} />
      <span className="eid">{e.title || e.id}</span>
      <Badge tone={e.type === 'model' ? 'accent' : e.type === 'agent' ? 'info' : e.type === 'mcp' ? 'warm' : 'neutral'} sq>{e.type}</Badge>
    </div>
    <div className="emeta">{e.meta}</div>
    {e.fits ? <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <Fit k="coding" v={e.fits.coding} /><Fit k="reasoning" v={e.fits.reasoning} /><Fit k="fast" v={e.fits.fast} />
    </div> : e.desc ? <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-dim)' }}>{e.desc}</div> : null}
    <div className="efoot">
      <span className="emeta">{Object.entries(e.usedBy || {}).map(([k, v]) => `${v} ${k}`).join(' · ')}</span>
      <div style={{ flex: 1 }} />
      <ActChip icon="chevron-right">peek</ActChip>
    </div>
  </div>;
}

function PeekPanel({ e, onClose, onSeedChat, onCompare }) {
  const [tab, setTab] = React.useState('overview');
  React.useEffect(() => { window.refreshIcons(); });
  const useRows = Object.entries(e.usedBy || {});
  return <div className="peek" onClick={ev => ev.stopPropagation()}>
    <div className="peek-head">
      <Pip status={e.status === 'online' ? 'online' : 'idle'} live={e.status === 'online'} />
      <span className="eid">{e.title || e.id}</span>
      <Badge tone="accent" sq>{e.type}</Badge>
      <div style={{ flex: 1 }} />
      {e.type === 'model' ? <Btn sm icon={e.loaded ? 'check' : 'download'}>{e.loaded ? 'Loaded' : 'Load'}</Btn> : <Btn sm icon="pen-line">Edit</Btn>}
      <IconBtn icon="x" bare label="Close" onClick={onClose} />
    </div>
    <div className="peek-tabs">
      {['overview', 'usage', 'history', 'raw'].map(t =>
        <span key={t} className={`peek-tab ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>{t}</span>)}
    </div>
    <div className="peek-body">
      {tab === 'overview' ? <React.Fragment>
        <div className="emeta" style={{ fontSize: 'var(--text-sm)' }}>{e.meta}</div>
        {e.desc ? <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-dim)', lineHeight: 1.5 }}>{e.desc}</div> : null}
        {e.fits ? <React.Fragment>
          <MLabel bare>Role fit — measured on this fleet</MLabel>
          <Fit k="coding" v={e.fits.coding} /><Fit k="reasoning" v={e.fits.reasoning} /><Fit k="fast" v={e.fits.fast} />
        </React.Fragment> : null}
        <MLabel bare>Used by</MLabel>
        {useRows.map(([k, v]) => <div key={k} className="userow"><Ico n={TYPE_ICON[k.replace(/s$/, '')] || 'box'} /><span className="n">{v}</span><span>{k}</span></div>)}
      </React.Fragment> : null}
      {tab === 'usage' ? <React.Fragment>
        <MLabel bare>Dependents</MLabel>
        {useRows.length ? useRows.map(([k, v]) => <div key={k} className="userow"><Ico n={TYPE_ICON[k.replace(/s$/, '')] || 'box'} /><span className="n">{v} {k}</span><span>— removing this {e.type} affects them</span></div>) : <div className="emeta">No dependents yet.</div>}
      </React.Fragment> : null}
      {tab === 'history' ? <div className="emeta" style={{ lineHeight: 2 }}>last used 2h ago · 31 invocations this week · added 14d ago</div> : null}
      {tab === 'raw' ? <div className="emeta" style={{ whiteSpace: 'pre', lineHeight: 1.7 }}>{`id: ${e.id}\ntype: ${e.type}\nstatus: ${e.status}\n# full yaml in the repo`}</div> : null}
    </div>
    <div className="peek-foot">
      <Btn variant="primary" sm icon="message-square" onClick={() => onSeedChat(e)}>Test in chat</Btn>
      {e.type === 'model' ? <Btn sm icon="columns-3" onClick={onCompare}>Compare</Btn> : null}
      <div style={{ flex: 1 }} />
      <Btn sm icon="maximize-2">Open full</Btn>
    </div>
  </div>;
}

function CompareBar({ models, onClose, onSeedChat }) {
  const win = models.reduce((a, b) => (a.fits.coding > b.fits.coding ? a : b));
  return <div className="comparebar">
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <MLabel bare>Compare — best for: coding</MLabel>
      <div style={{ flex: 1 }} />
      <IconBtn icon="x" bare label="Close" onClick={onClose} />
    </div>
    <div className="comparegrid">
      {models.map(m => <div key={m.id} className={`comparecol ${m.id === win.id ? 'win' : ''}`}>
        <span className="id">{m.id}{m.id === win.id ? ' ★' : ''}</span>
        <span>{m.loaded ? m.tps + ' tok/s' : 'cold start'}</span>
        <span>{m.size} resident</span>
        <Fit k="coding" v={m.fits.coding} />
        <span>{m.loaded ? 'loaded' : 'on disk'}</span>
      </div>)}
    </div>
    <div style={{ display: 'flex' }}>
      <div style={{ flex: 1 }} />
      <Btn variant="primary" sm icon="zap" onClick={() => onSeedChat(win)}>Seed a chat with {win.id}</Btn>
    </div>
  </div>;
}

function InstallWizard({ type, onClose, onSeedChat }) {
  const W = window.ENCLAVE2.WIZARDS[type];
  const [step, setStep] = React.useState(0);
  const [src, setSrc] = React.useState(0);
  const [verified, setVerified] = React.useState(false);
  React.useEffect(() => { window.refreshIcons(); });
  return <div className="scrim" onClick={onClose}>
    <div className="modal" style={{ width: 'min(640px, calc(100vw - 48px))' }} onClick={e => e.stopPropagation()}>
      <div className="modal-head">
        <Ico n={TYPE_ICON[type]} style={{ width: 16, color: 'var(--accent)' }} />
        <span className="h">Install — new {type}</span>
        <div style={{ flex: 1 }} />
        <IconBtn icon="x" bare label="Close" onClick={onClose} />
      </div>
      <div className="modal-body">
        <WStepper active={step} />
        {step === 0 ? <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {W.sources.map((s, i) => <div key={s} className={`wsource ${src === i ? 'sel' : ''}`} onClick={() => setSrc(i)}>
            <span className="rad" /><span>{s}</span>
            {s.includes('★') ? <Badge tone="accent" sq>the ladder</Badge> : null}
          </div>)}
        </div> : null}
        {step === 1 ? <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {W.fields.map(([k, v]) => <div key={k} className="field" style={{ marginBottom: 0 }}>
            <label>{k}</label><input className="mono" defaultValue={v} />
          </div>)}
        </div> : null}
        {step === 2 ? <div className="vchat">
          <MLabel bare>Verify — talk to it</MLabel>
          <div className="msg user" style={{ alignSelf: 'flex-end' }}><span className="bubble">{W.verifyPrompt}</span></div>
          {verified ? <React.Fragment>
            <div className="msg bot" style={{ maxWidth: '92%' }}><span className="bubble">{W.verifyReply}</span></div>
            <span className="vmeta"><Ico n="check" style={{ width: 13 }} />{W.verifyMeta}</span>
          </React.Fragment> : <Btn variant="primary" sm icon="play" onClick={() => setVerified(true)} style={{ alignSelf: 'flex-start' }}>Send test prompt</Btn>}
        </div> : null}
        {step === 3 ? <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 'var(--text-base)', color: 'var(--text)', lineHeight: 1.5 }}>
            <Ico n="check-circle-2" style={{ width: 15, color: 'var(--success)', verticalAlign: -2, marginRight: 7 }} />Installed. Lands in: {W.lands}
          </div>
          <MLabel bare>Next rung</MLabel>
          <div style={{ display: 'flex', gap: 8 }}>
            <ActChip icon="zap" acc onClick={() => { onClose(); onSeedChat({ id: W.fields[0][1], type }); }}>seed a chat with it</ActChip>
            <ActChip icon="workflow">add to a workflow</ActChip>
          </div>
        </div> : null}
      </div>
      <div className="modal-foot">
        {step > 0 && step < 3 ? <Btn sm onClick={() => setStep(s => s - 1)}>Back</Btn> : null}
        <div style={{ flex: 1 }} />
        {step < 3 ? <Btn variant="primary" sm icon="arrow-right" onClick={() => setStep(s => s + 1)}
          style={step === 2 && !verified ? { opacity: .5 } : null} disabled={step === 2 && !verified}>
          {step === 2 ? 'Finish' : 'Next'}</Btn> :
          <Btn variant="primary" sm onClick={onClose}>Done</Btn>}
      </div>
    </div>
  </div>;
}

function Library2({ onSeedChat, onResearch }) {
  const E = window.ENCLAVE2.ENTITIES;
  const [tab, setTab] = React.useState('models');
  const [peekId, setPeekId] = React.useState(null);
  const [compare, setCompare] = React.useState(false);
  const [wizard, setWizard] = React.useState(null);
  React.useEffect(() => { window.refreshIcons(); });
  const items = E[tab] || [];
  const peek = items.find(e => e.id === peekId) || null;
  const tabDef = LIB_TABS.find(t => t.id === tab);

  return <div className="libwrap" onClick={() => setPeekId(null)}>
    <div className="libscroll">
      <div className="page" style={{ height: 'auto' }}>
        <div className="page-head">
          <div className="h">Library</div>
          <div className="sub">Every entity, one card — peek for depth, push for work.</div>
          <div className="page-head-spacer" />
          {tabDef.wiz ? <Btn variant="primary" icon="plus" onClick={e => { e.stopPropagation(); setWizard(tabDef.wiz); }}>Install {tab.replace(/s$/, '')}</Btn> :
            <Btn variant="primary" icon="telescope" onClick={e => { e.stopPropagation(); onResearch(); }}>Research a context</Btn>}
        </div>
        <div className="toolbar">
          {LIB_TABS.map(t => <Btn key={t.id} sm onClick={e => { e.stopPropagation(); setTab(t.id); setPeekId(null); setCompare(false); }}
            style={t.id === tab ? { borderColor: 'var(--accent-dim)', color: 'var(--accent)', background: 'var(--accent-ghost)' } : null}>{t.label}</Btn>)}
          <div style={{ flex: 1 }} />
          <div className="search"><Ico n="search" /><input placeholder={`Search ${tab}…`} /></div>
        </div>
        <div className="cardgrid">
          {items.map(e => <ECard key={e.id} e={e} sel={peekId === e.id}
            onPeek={ev => { ev.stopPropagation(); setPeekId(e.id); }} />)}
        </div>
      </div>
    </div>
    {peek ? <PeekPanel e={peek} onClose={() => setPeekId(null)} onSeedChat={onSeedChat} onCompare={() => setCompare(true)} /> : null}
    {compare ? <CompareBar models={E.models.filter(m => m.fits).slice(0, 3)} onClose={() => setCompare(false)} onSeedChat={onSeedChat} /> : null}
    {wizard ? <InstallWizard type={wizard} onClose={() => setWizard(null)} onSeedChat={onSeedChat} /> : null}
  </div>;
}

window.Library2 = Library2;
