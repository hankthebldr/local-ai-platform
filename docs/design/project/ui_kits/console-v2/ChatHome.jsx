/* Enclave Console v2 — chat home (threads rail | thread | structure rail). */

function ThreadRail({ threads, activeId, onPick, onNew }) {
  return <div className="threads">
    <div className="threads-head"><MLabel bare>Threads</MLabel><Btn sm icon="plus" onClick={onNew}>New</Btn></div>
    <div className="threads-list">
      {threads.map(t => <div key={t.id} className={`thr ${t.id === activeId ? 'active' : ''}`} onClick={() => onPick(t.id)}>
        <Pip status={t.id === activeId ? 'online' : 'idle'} />
        <span className="tx">
          <span className="tn">{t.name}</span>
          <span className="ts">{t.seed.role} · {t.seed.model}</span>
        </span>
        <Badge tone={KIND_TONE[t.kind]} sq>{t.kind}</Badge>
      </div>)}
    </div>
  </div>;
}

function ChatMsg({ m, i, onPin }) {
  if (m.who === 'sys') return <div className="msg sys"><div className="bubble">{m.text}</div></div>;
  return <div className={`msgwrap ${m.who}`}>
    <div className={`msg ${m.who === 'user' ? 'user' : 'bot'}`}>
      <span className="who">{m.who === 'user' ? 'you' : 'agent'}</span>
      <span className="bubble">{m.text}</span>
    </div>
    {m.pinned ? <span className="pinmark"><Ico n="pin" />pinned as step · {m.pinned}</span> :
      m.who === 'bot' ? <div className="acts">
        <ActChip icon="pin" acc onClick={() => onPin(i)}>pin as step</ActChip>
        <ActChip icon="scissors">save as skill</ActChip>
        <ActChip icon="git-branch">branch</ActChip>
      </div> : null}
  </div>;
}

function ScaffoldModal({ thread, onClose, onConfirm }) {
  const steps = [...thread.pins, { id: 'inf', title: 'validate', role: 'fast', src: 'suggested', dash: true }];
  return <div className="scrim" onClick={onClose}>
    <div className="modal" onClick={e => e.stopPropagation()}>
      <div className="modal-head">
        <Ico n="git-merge" style={{ width: 16, color: 'var(--accent)' }} />
        <span className="h">Convert "{thread.name}" to a workflow</span>
        <div style={{ flex: 1 }} />
        <IconBtn icon="x" bare label="Close" onClick={onClose} />
      </div>
      <div className="modal-body">
        <MLabel bare>Scaffold preview — derived from this thread</MLabel>
        <div className="scaffold">
          <div className="scaffold-dag">
            {steps.map((s, i) => <React.Fragment key={s.id}>
              {i > 0 ? <span className="dagarrow"><Ico n="arrow-right" style={{ width: 15 }} /></span> : null}
              <MiniNode title={s.title} role={s.role} dash={s.dash} />
            </React.Fragment>)}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            <MLabel bare>Traceability</MLabel>
            {steps.map(s => <div key={s.id} className={`tracerow ${s.dash ? 'dash' : ''}`}>
              <span className="t">{s.title}</span><span className="s">← {s.src}{s.dash ? '' : ' · pinned'}</span>
            </div>)}
          </div>
        </div>
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          Role, model, context and prompts are inherited from the seed and the pinned replies — nothing re-entered.
          The thread stays attached as the test surface.
        </div>
      </div>
      <div className="modal-foot">
        <Btn onClick={onClose}>Keep chatting instead</Btn>
        <div style={{ flex: 1 }} />
        <Btn variant="primary" icon="layout-dashboard" onClick={onConfirm}>Edit on canvas</Btn>
      </div>
    </div>
  </div>;
}

function ChatHome({ threads, activeId, setActiveId, updateThread, createThread }) {
  const D2 = window.ENCLAVE2;
  const thread = threads.find(t => t.id === activeId) || threads[0];
  const [input, setInput] = React.useState('');
  const [scaffold, setScaffold] = React.useState(false);
  const endRef = React.useRef(null);
  React.useEffect(() => { window.refreshIcons(); });
  React.useEffect(() => {
    const el = endRef.current; if (el && el.parentElement) { el.parentElement.scrollTop = el.parentElement.scrollHeight; }
  }, [thread.msgs.length, activeId]);

  const pins = thread.pins;
  const maturity = Math.min(5, 1 + pins.length + (thread.converted ? 1 : 0) + (thread.kind === 'agent' ? 1 : 0));

  function pinMsg(i) {
    const m = thread.msgs[i];
    const title = m.pinAs || `step-${pins.length + 1}`;
    const role = m.pinRole || thread.seed.role;
    updateThread(thread.id, t => ({
      ...t,
      msgs: t.msgs.map((mm, ii) => ii === i ? { ...mm, pinned: title } : mm),
      pins: [...t.pins, { id: 'p' + (t.pins.length + 1), title, role, src: `msg #${i + 1}` }],
    }));
  }

  function send() {
    const text = input.trim(); if (!text) return;
    setInput('');
    const ri = thread.ri || 0;
    updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'user', text }], ri: ri + 1 }));
    setTimeout(() => {
      updateThread(thread.id, t => ({ ...t, msgs: [...t.msgs, { who: 'bot', text: D2.REPLIES[ri % D2.REPLIES.length] }] }));
    }, 700);
  }

  function confirmConvert() {
    setScaffold(false);
    const steps = [...pins, { title: 'validate', role: 'fast' }];
    const nodes = steps.map((s, i) => ({
      id: 'n' + (i + 1), title: s.title, role: s.role,
      model: (window.ENCLAVE.MODELS.find(m => m.role === s.role) || {}).id || 'auto',
      x: 40 + i * 260, y: i % 2 ? 80 : 170,
      prompt: `Derived from ${s.src || 'thread'} — refine as needed.`,
    }));
    const edges = nodes.slice(1).map((n, i) => [nodes[i].id, n.id]);
    updateThread(thread.id, t => ({
      ...t, converted: true, kind: 'wf', mode: 'canvas', nodes, edges,
      msgs: [...t.msgs, { who: 'sys', text: `Converted to workflow — ${nodes.length} steps scaffolded from this thread.` }],
    }));
  }

  function researchCtx() {
    createThread({
      name: 'xsiam dm research', kind: 'chat',
      seed: { role: 'reasoning', model: 'dolphin-mixtral', ctx: null, plugin: 'web-search' },
      msgs: [
        { who: 'sys', text: 'Seeded with web-search — findings can be added to a context bundle.' },
        { who: 'user', text: 'Build me context on the XSIAM data model — fields, mappings, gotchas.' },
      ],
    });
  }

  return <div className="chathome">
    <ThreadRail threads={threads} activeId={thread.id} onPick={setActiveId}
      onNew={() => createThread({ name: 'untitled thread', kind: 'chat', seed: { role: 'general', model: 'nous-hermes2', ctx: null }, msgs: [{ who: 'sys', text: 'Seeded — general · nous-hermes2. Attach context or pick a role to tune the seed.' }] })} />

    <div className="chatpane">
      <div className="chat-head">
        <span className="nm">{thread.name}</span>
        <SeedChip k="role" v={thread.seed.role} />
        <SeedChip k="model" v={thread.seed.model} />
        {thread.seed.plugin ? <SeedChip k="plugin" v={thread.seed.plugin} acc /> : null}
        {thread.seed.ctx ? <SeedChip k="ctx" v={thread.seed.ctx} acc /> : <SeedChip ghost v="+ context" />}
        <span className="chat-head-spacer" />
        <Meter value={maturity} hot={pins.length >= 2 && !thread.converted} />
        <div className="pivot">
          <button className="on"><Ico n="message-square" />Chat</button>
          <button disabled={!thread.converted} title={thread.converted ? 'Open the workflow canvas' : 'Convert first — pin 2+ steps'}
            onClick={() => updateThread(thread.id, t => ({ ...t, mode: 'canvas' }))}><Ico n="workflow" />Canvas</button>
        </div>
        {pins.length >= 2 && !thread.converted ? <Btn variant="primary" sm icon="git-merge" onClick={() => setScaffold(true)}>Convert</Btn> : null}
      </div>

      <div className="chat-msgs">
        <div className="inner">
          {thread.msgs.map((m, i) => <ChatMsg key={i} m={m} i={i} onPin={pinMsg} />)}
          <div ref={endRef} />
        </div>
      </div>

      <div className="nba">
        {pins.length >= 2 && !thread.converted ?
          <ActChip icon="git-merge" acc onClick={() => setScaffold(true)}>you've pinned {pins.length} steps — convert to a workflow?</ActChip> : null}
        {!thread.seed.ctx && !thread.seed.plugin ?
          <ActChip icon="telescope" onClick={researchCtx}>no context attached — research it?</ActChip> : null}
        {thread.kind === 'chat' && thread.msgs.length > 4 && !thread.converted ?
          <ActChip icon="bot">save this persona as an agent?</ActChip> : null}
      </div>

      <div className="chatbox">
        <div className="inner">
          <input placeholder={`Message ${thread.seed.model}…`} value={input}
            onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') send(); }} />
          <div className="chips">
            <SeedChip ghost v="+ context" />
            <SeedChip ghost v="agent ▾" />
            <div style={{ flex: 1 }} />
            <Btn variant="primary" sm icon="zap" onClick={send}>Send</Btn>
          </div>
        </div>
      </div>
    </div>

    <div className="struct">
      <div className="struct-head"><MLabel bare>Structure</MLabel></div>
      <div className="struct-hint">Pin replies to grow the workflow draft. Each step keeps a trace back to its message.</div>
      <div className="struct-list">
        {pins.map((p, i) => <div key={p.id} className="stepcard">
          <div className="top"><span className="n">{i + 1}</span><span className="t">{p.title}</span><Badge tone="accent" sq>{p.role}</Badge></div>
          <span className="src">← {p.src} · pinned ✓</span>
        </div>)}
        <div className="stepcard ghost"><div className="top"><span className="n">+</span><span className="t">add a step…</span></div></div>
      </div>
      <div className="struct-foot">
        {thread.converted ?
          <Btn variant="primary" icon="workflow" onClick={() => updateThread(thread.id, t => ({ ...t, mode: 'canvas' }))}>Open canvas</Btn> :
          <Btn variant={pins.length >= 2 ? 'primary' : ''} icon="git-merge" disabled={pins.length < 2}
            style={pins.length < 2 ? { opacity: .5, cursor: 'not-allowed' } : null}
            onClick={() => pins.length >= 2 && setScaffold(true)}>Convert to workflow</Btn>}
        <span className="hint">{thread.converted ? 'Converted — the canvas is one pivot away.' : pins.length < 2 ? `Pin ${2 - pins.length} more ${pins.length === 1 ? 'reply' : 'replies'} to unlock conversion.` : 'Scaffolds a DAG you can refine on the canvas.'}</span>
      </div>
    </div>

    {scaffold ? <ScaffoldModal thread={thread} onClose={() => setScaffold(false)} onConfirm={confirmConvert} /> : null}
  </div>;
}

window.ChatHome = ChatHome;
