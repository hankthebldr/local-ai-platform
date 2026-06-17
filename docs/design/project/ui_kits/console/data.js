/* Enclave Console — mock data for the workflow-first UI kit.
   Plain JS; sets window.ENCLAVE. No backend; everything is fake. */
(function () {
  const MODELS = [
    { id: 'dolphin-mixtral', size: '26 GB', quant: 'Q4_K_M', tps: 12, role: 'reasoning', loaded: true },
    { id: 'qwen2.5-coder',   size: '4.7 GB', quant: 'Q4_K_M', tps: 47, role: 'coding', loaded: true },
    { id: 'llama3.2:3b',     size: '2.0 GB', quant: 'Q4_K_M', tps: 92, role: 'fast', loaded: true },
    { id: 'nous-hermes2',    size: '26 GB', quant: 'Q5_K_M', tps: 11, role: 'general', loaded: false },
    { id: 'yi-34b',          size: '20 GB', quant: 'Q3_K_M', tps: 14, role: 'reasoning', loaded: false },
    { id: 'wizardlm-uncensored', size: '7.4 GB', quant: 'Q4_K_M', tps: 38, role: 'uncensored', loaded: false },
  ];

  const ROLES = [
    { kind: 'reasoning', title: 'reasoning', desc: 'Deep analysis · 34B class', icon: 'brain' },
    { kind: 'coding',    title: 'coding',    desc: 'Code gen + review', icon: 'code' },
    { kind: 'fast',      title: 'fast',      desc: 'Low-latency triage', icon: 'zap' },
    { kind: 'general',   title: 'general',   desc: 'Balanced default', icon: 'circle' },
    { kind: 'uncensored', title: 'uncensored', desc: 'Unfiltered persona', icon: 'shield-off' },
  ];

  const AGENTS = [
    { kind: 'agent', title: 'xsiam-analyst', desc: 'Security triage persona', icon: 'bot', role: 'reasoning', model: 'dolphin-mixtral' },
    { kind: 'agent', title: 'normalizer',    desc: 'Maps logs to data model', icon: 'bot', role: 'coding', model: 'qwen2.5-coder' },
    { kind: 'agent', title: 'red-teamer',    desc: 'Adversarial probing', icon: 'bot', role: 'uncensored', model: 'wizardlm-uncensored' },
  ];

  const SKILLS = [
    { kind: 'skill', title: 'concise-writer', desc: 'Tightens prose on trigger', icon: 'scissors' },
    { kind: 'skill', title: 'cite-sources',   desc: 'Appends evidence refs', icon: 'quote' },
    { kind: 'skill', title: 'json-strict',    desc: 'Forces valid JSON out', icon: 'braces' },
  ];

  const PLUGINS = [
    { kind: 'plugin', title: 'web-search', desc: 'DuckDuckGo / SearXNG', icon: 'globe' },
    { kind: 'plugin', title: 'python-exec', desc: 'Sandboxed code run', icon: 'terminal' },
  ];

  const MCPS = [
    { kind: 'mcp', title: 'filesystem', desc: 'read / write tools', icon: 'folder' },
    { kind: 'mcp', title: 'postgres',   desc: 'query the warehouse', icon: 'database' },
  ];

  // Sample workflow: a DAG laid out on the canvas (x,y in canvas px).
  const WORKFLOW = {
    id: 'xsiam-normalize',
    name: 'XSIAM Log Normalization',
    category: 'security',
    role: 'general',
    desc: 'Ingest raw vendor logs, map to the XSIAM data model, validate, and emit normalized events.',
    nodes: [
      { id: 'n1', title: 'analyze',  role: 'reasoning', model: 'dolphin-mixtral', x: 40,  y: 150, prompt: 'Identify the log schema and vendor. Summarize fields present.' },
      { id: 'n2', title: 'normalize', role: 'coding',   model: 'qwen2.5-coder',   x: 300, y: 80,  prompt: 'Map each source field to the XSIAM data model. Output a field map.' },
      { id: 'n3', title: 'validate', role: 'fast',      model: 'llama3.2:3b',     x: 300, y: 250, prompt: 'Check the field map for required keys. Flag gaps.' },
      { id: 'n4', title: 'emit',     role: 'general',   model: 'nous-hermes2',    x: 560, y: 165, prompt: 'Render the normalized event batch as NDJSON.' },
    ],
    edges: [ ['n1','n2'], ['n1','n3'], ['n2','n4'], ['n3','n4'] ],
  };

  const RUNS = [
    { id: 'run-7f3a', wf: 'XSIAM Log Normalization', state: 'success', step: 4, total: 4, when: '2m ago', dur: '0:41', tps: 38 },
    { id: 'run-7e91', wf: 'Threat Intel Enrichment', state: 'success', step: 6, total: 6, when: '18m ago', dur: '1:12', tps: 41 },
    { id: 'run-7e44', wf: 'XSIAM Log Normalization', state: 'error',   step: 3, total: 4, when: '1h ago',  dur: '0:22', tps: 35, err: 'validate: missing required key `_time`' },
    { id: 'run-7d10', wf: 'PR Review Pipeline',      state: 'success', step: 3, total: 3, when: '3h ago',  dur: '0:55', tps: 47 },
    { id: 'run-7c88', wf: 'Detection Rule Drafting', state: 'success', step: 5, total: 5, when: 'yesterday', dur: '2:03', tps: 12 },
  ];

  const WORKFLOWS = [
    { id: 'xsiam-normalize', name: 'XSIAM Log Normalization', category: 'security', steps: 4, runs: 31, updated: '2m ago' },
    { id: 'ti-enrich',       name: 'Threat Intel Enrichment', category: 'security', steps: 6, runs: 19, updated: '18m ago' },
    { id: 'pr-review',       name: 'PR Review Pipeline',      category: 'code',     steps: 3, runs: 64, updated: '3h ago' },
    { id: 'detect-draft',    name: 'Detection Rule Drafting', category: 'security', steps: 5, runs: 8,  updated: 'yesterday' },
    { id: 'doc-synth',       name: 'Doc Synthesis',          category: 'research', steps: 4, runs: 12, updated: '2d ago' },
    { id: 'incident-sum',    name: 'Incident Summarizer',    category: 'security', steps: 2, runs: 27, updated: '4d ago' },
  ];

  window.ENCLAVE = { MODELS, ROLES, AGENTS, SKILLS, PLUGINS, MCPS, WORKFLOW, RUNS, WORKFLOWS };
})();
