/* Enclave Console v2 — chat-led data. Extends window.ENCLAVE (load data.js first). */
(function () {
  const D = window.ENCLAVE;
  if (!D) return; // standalone evaluation guard (e.g. DS compiler sandbox) — this file derives from data.js

  /* Threads — every object is born as a conversation. */
  const THREADS = [
    {
      id: 't1', name: 'xsiam log triage', kind: 'chat', converted: false, mode: 'chat',
      seed: { role: 'reasoning', model: 'dolphin-mixtral', ctx: 'xsiam-docs' },
      msgs: [
        { who: 'sys', text: 'Seeded — reasoning · dolphin-mixtral · ctx: xsiam-docs (142 chunks).' },
        { who: 'user', text: 'Here is a raw CrowdStrike export. Identify the schema and summarize the fields present.' },
        { who: 'bot', text: 'Vendor: CrowdStrike Falcon, FDR format. 38 fields detected — event_simpleName, aid, ComputerName, timestamp (epoch ms), 11 network fields, 9 process fields. Schema is consistent across the batch.', pinned: 'analyze' },
        { who: 'user', text: 'Map those onto the XSIAM data model. Field map only.' },
        { who: 'bot', text: 'Field map drafted: 31/38 fields map cleanly (xdm.source.host ← ComputerName, xdm.event.type ← event_simpleName…). 7 vendor-specific fields need a custom mapping block. Want it as YAML?', pinAs: 'normalize', pinRole: 'coding' },
      ],
      pins: [{ id: 'p1', title: 'analyze', role: 'reasoning', src: 'msg #3' }],
      nodes: null, edges: null,
    },
    {
      id: 't2', name: 'threat intel notes', kind: 'agent', converted: false, mode: 'chat',
      seed: { role: 'reasoning', model: 'dolphin-mixtral', ctx: 'unit42-feed' },
      msgs: [
        { who: 'sys', text: 'Saved as agent xsiam-analyst — role, model, prompt and context pinned.' },
        { who: 'user', text: 'Summarize today\u2019s Unit42 feed against our watchlist.' },
        { who: 'bot', text: '3 overlaps: Scattered Spider TTPs (T1566.004), a new Qakbot loader hash, and infra reuse on 2 watched ASNs. Full notes in the bundle.' },
      ],
      pins: [], nodes: null, edges: null,
    },
    {
      id: 't3', name: 'pr review loop', kind: 'wf', converted: true, mode: 'chat',
      seed: { role: 'coding', model: 'qwen2.5-coder', ctx: null },
      msgs: [
        { who: 'sys', text: 'Converted to workflow — 3 steps scaffolded from this thread.' },
        { who: 'user', text: 'Review PR #214 — the detection rule refactor.' },
        { who: 'bot', text: '▸ lint-pass (qwen2.5-coder) — 2 style nits, no logic issues. ▸ security-review — no injected paths. ▸ summarize — approved with comments.' },
      ],
      pins: [
        { id: 'p1', title: 'lint-pass', role: 'coding', src: 'msg #2' },
        { id: 'p2', title: 'security-review', role: 'reasoning', src: 'msg #2' },
        { id: 'p3', title: 'summarize', role: 'fast', src: 'msg #3' },
      ],
      nodes: [
        { id: 'n1', title: 'lint-pass', role: 'coding', model: 'qwen2.5-coder', x: 40, y: 150, prompt: 'Lint the diff. Style + logic issues, severity-tagged.' },
        { id: 'n2', title: 'security-review', role: 'reasoning', model: 'dolphin-mixtral', x: 300, y: 80, prompt: 'Adversarial review: injection, path traversal, secrets.' },
        { id: 'n3', title: 'summarize', role: 'fast', model: 'llama3.2:3b', x: 560, y: 150, prompt: 'One-paragraph verdict with blocking items first.' },
      ],
      edges: [['n1', 'n2'], ['n1', 'n3'], ['n2', 'n3']],
    },
    {
      id: 't4', name: 'model bake-off', kind: 'chat', converted: false, mode: 'chat',
      seed: { role: 'coding', model: 'qwen2.5-coder', ctx: null },
      msgs: [
        { who: 'user', text: 'Same normalization prompt against qwen2.5-coder and dolphin-mixtral — compare outputs.' },
        { who: 'bot', text: 'qwen2.5-coder: valid YAML, 47 tok/s. dolphin-mixtral: richer field rationale, 12 tok/s. For the normalize step, qwen wins on structure per watt.' },
      ],
      pins: [], nodes: null, edges: null,
    },
  ];

  /* Canned assistant replies for the live chat. */
  const REPLIES = [
    'Validated against the data model: 31 mapped, 7 custom. Two required keys missing on 4% of events — _time and xdm.event.id. I can draft the fallback block.',
    'Done. Custom mapping block drafted for the 7 vendor fields — epoch→RFC3339 on _time, aid→xdm.source.agent.id. Re-validated: 0 dropped.',
    'Batch normalized: 1,284 events, 0 dropped, 38 tok/s sustained. Emitted as NDJSON to workspace.emit.batch.',
  ];

  /* Library entities — one card anatomy for everything. */
  const FITS = {
    'dolphin-mixtral': { coding: 55, reasoning: 88, fast: 20 },
    'qwen2.5-coder': { coding: 90, reasoning: 40, fast: 65 },
    'llama3.2:3b': { coding: 35, reasoning: 25, fast: 95 },
    'nous-hermes2': { coding: 45, reasoning: 70, fast: 25 },
    'yi-34b': { coding: 45, reasoning: 80, fast: 18 },
    'wizardlm-uncensored': { coding: 30, reasoning: 60, fast: 45 },
  };
  const ENTITIES = {
    models: D.MODELS.map(m => ({
      type: 'model', id: m.id, status: m.loaded ? 'online' : 'idle',
      meta: `${m.size} · ${m.quant} · ${m.loaded ? m.tps + ' tok/s' : 'cold'}`,
      fits: FITS[m.id], usedBy: { steps: m.loaded ? 3 : 1, agents: m.loaded ? 2 : 0, workflows: 1 },
      tps: m.tps, size: m.size, loaded: m.loaded, role: m.role,
    })),
    agents: D.AGENTS.map(a => ({
      type: 'agent', id: a.title, status: 'online', meta: `${a.role} · ${a.model}`,
      desc: a.desc, usedBy: { steps: 2, workflows: 1, threads: 3 }, role: a.role, model: a.model,
    })),
    skills: D.SKILLS.map(s => ({
      type: 'skill', id: s.title, status: 'idle', meta: 'auto-injects on trigger',
      desc: s.desc, usedBy: { steps: 1, agents: 1 },
    })),
    plugins: [...D.PLUGINS.map(p => ({ ...p, t: 'plugin' })), ...D.MCPS.map(p => ({ ...p, t: 'mcp' }))].map(p => ({
      type: p.t, id: p.title, status: p.t === 'mcp' ? 'online' : 'idle', meta: p.desc,
      usedBy: { steps: p.t === 'mcp' ? 2 : 1 },
    })),
    contexts: [
      { type: 'context', id: 'xsiam-docs', status: 'online', meta: '7 docs · 142 chunks · graph: 41 nodes', usedBy: { threads: 2, agents: 1, workflows: 1 } },
      { type: 'context', id: 'unit42-feed', status: 'online', meta: 'live feed · 89 chunks', usedBy: { threads: 1, agents: 1 } },
      { type: 'context', id: 'detection-rules-q4', status: 'idle', meta: '3 docs · 56 chunks', usedBy: { workflows: 1 } },
    ],
    workflows: D.WORKFLOWS.map(w => ({
      type: 'workflow', id: w.id, title: w.name, status: 'idle',
      meta: `${w.steps} steps · ${w.runs} runs · ${w.updated}`, usedBy: { runs: w.runs }, category: w.category,
    })),
  };

  /* Unified install wizard — one stepper skeleton, five payloads. */
  const WIZARDS = {
    model: {
      sources: ['Ollama registry', 'Hugging Face URL', 'Local GGUF file'],
      fields: [['name', 'mistral-nemo:12b'], ['quant', 'Q4_K_M (recommended · ~7 GB)'], ['role mapping', 'general'], ['target box', 'ms-01 · 64 GB']],
      verifyPrompt: 'Summarize the XSIAM data model in one paragraph.',
      verifyReply: 'XSIAM\u2019s data model (XDM) normalizes vendor telemetry into a shared schema — xdm.source.*, xdm.event.*, xdm.network.* — so detections are written once against normalized fields rather than per-vendor formats.',
      verifyMeta: '✓ responds · 41 tok/s · 6.8 GB resident',
      lands: 'Library → Models, with role-fit suggestions computed on first runs.',
    },
    agent: {
      sources: ['From a thread ★', 'Blank persona'],
      fields: [['name', 'xsiam-analyst-2'], ['role', 'reasoning'], ['model', 'dolphin-mixtral'], ['context', 'xsiam-docs'], ['system prompt', 'distilled from thread ✎']],
      verifyPrompt: 'Triage: 40 failed logins, then a success from a new ASN.',
      verifyReply: 'Pattern matches credential stuffing → success. Severity: high. Recommend session revoke + ASN block; checking watchlist overlap next.',
      verifyMeta: '✓ persona holds · 12 tok/s',
      lands: 'Palette → Agents, and offered in every seed strip.',
    },
    skill: {
      sources: ['Markdown file', 'From a pinned reply ★'],
      fields: [['name', 'cite-sources'], ['triggers', 'cite, evidence, source'], ['injection', 'append']],
      verifyPrompt: 'Why is this IP flagged? cite sources.',
      verifyReply: 'Flagged for C2 beaconing [1] and ASN reuse [2]. — [1] unit42-feed §3, [2] xsiam-docs/infra.md',
      verifyMeta: '✓ trigger fired · refs appended',
      lands: 'Auto-injects on trigger; listed in Palette → Skills.',
    },
    plugin: {
      sources: ['MCP catalog', 'Server URL'],
      fields: [['name', 'postgres'], ['permissions', 'query (read-only)'], ['env', 'PGHOST · PGUSER · key from vault']],
      verifyPrompt: 'Dry-run: list tables in the warehouse.',
      verifyReply: 'tool_call: postgres.query → 14 tables (events_raw, events_norm, detections, …). Read-only confirmed.',
      verifyMeta: '✓ tool call round-trip · 80 ms',
      lands: 'Callable from any step; listed in Palette → MCPs.',
    },
    workflow: {
      sources: ['From a thread ★', 'YAML import'],
      fields: [['name', 'xsiam-normalize-v2'], ['map steps to models', 'auto-fit (3/4 local)'], ['schedule', 'manual']],
      verifyPrompt: 'Dry run with sample-batch.json.',
      verifyReply: '4/4 steps green on the sample — 212 events normalized, 0 dropped, 0:38 wall clock.',
      verifyMeta: '✓ dry run pass · 0:38',
      lands: 'Workflows + Composer; first run checkpointed.',
    },
  };

  /* Operator's path — the adoption ladder, tracked. */
  const PATH = [
    { t: 'seed your first chat', done: true },
    { t: 'pin a reply as a step', done: true },
    { t: 'save a persona as an agent', done: true },
    { t: 'convert a thread to a workflow', done: false, hot: true },
    { t: 'schedule a run on the fleet', done: false },
  ];

  /* System performance — last hour / last 8 runs (deterministic mock). */
  const UTIL = {
    cpu: [22, 31, 28, 36, 44, 41, 52, 48, 57, 61, 55, 40, 34],
    mem: [38, 38, 41, 48, 48, 59, 64, 64, 73, 81, 81, 76, 69],
    tps: [31, 35, 33, 41, 38, 47, 44, 49, 46, 51, 47, 44, 47],
    dur: [62, 58, 55, 49, 52, 47, 44, 41],
    runs: [3, 5, 4, 7, 6, 9, 8, 11],
  };

  window.ENCLAVE2 = { THREADS, REPLIES, ENTITIES, WIZARDS, PATH, UTIL };
})();
