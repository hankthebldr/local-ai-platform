# Enclave Product Brainstorm — 2026-05-16

Post-1.0 strategic directions. Not a plan — a menu of distinct bets to argue about.

## Where we actually are

The README sells Enclave as "OpenAI-compatible local LLM with a Mac app." Internally we
shipped much more than that:

- Multi-agent DAG workflow engine (Jinja2 prompts, output parsers, quality gates, checkpoint/resume, 6-hook lifecycle)
- MCP client (`mcp_service.py`) + plugin system with three reference plugins (web-search, RAG, xdm-toolkit)
- Agent-to-agent protocol (`a2a_service.py`) + agent personas (Gems-style)
- Sandboxed tool execution (`sandbox_fs.py`, `tool_executor.py`)
- Knowledge graph (`graph_service.py`) + memory + project workspaces
- 22 services, 16 routers — closer to a "local agentic platform" than a chat client

**The positioning gap:** we're priced as a chatbot and shipped as an agent runtime.
None of our marketing surfaces (README, dashboard, DMG screenshots) show the workflow
engine, MCP, or plugins. The 1.0 narrative undersells what we built.

## Directions to consider

Ordered by my read of strategic fit, not effort.

### 1. Enclave Code — local agentic coder

**Pitch:** Claude Code / Cursor, but the agent runs against your local model on your
hardware. No SaaS, no telemetry, no $200/mo seat. The workflow engine + sandbox FS +
tool_executor + MCP are 70% of the stack already.

**Why it fits:** every piece exists. What's missing is the loop: a CLI/editor surface
that streams tool calls from a local model and applies them via `sandbox_fs.py`. The
multi-agent engine becomes the differentiator vs. Continue/Aider — we can run
"planner → coder → reviewer" as three local agents with different quantizations.

**MVP shape:** `enclave code` CLI that takes a prompt, opens a sandboxed worktree of
the current repo, runs a 3-step DAG (plan/edit/verify), prints diffs. VS Code
extension is v2.

**Risks:** local models are still mediocre at tool use. Need to pick the right
function-calling model (Qwen2.5-Coder 32B, DeepSeek-Coder-V2) and tune prompts hard.
Differential vs. Aider is the multi-agent piece; without it we're a worse Aider.

**Why now:** Claude Code and Cursor have trained users to expect agentic IDEs. The
"local + private" angle is wide open — nobody has shipped a credible offline competitor.

---

### 2. Vertical workflow packs — start with security

**Pitch:** We already shipped XSIAM workflows (data-model-rules, normalization-pipeline,
rule-from-log, bulk-onboarding). Package these as a paid vertical pack — "Enclave for
SOC analysts" — and use the same pattern for legal contract review, medical record
summarization, audit/SOX evidence collection. Each pack = curated workflows + agent
personas + plugin + small RAG corpus.

**Why it fits:** workflows + agents are our actual product. Vertical packs turn the
engine into shippable outcomes for buyers who don't want to author YAML.

**MVP shape:** `enclave packs install xsiam` pulls a versioned bundle of workflows +
agents + plugins. Dashboard shows packs as first-class objects. Sell packs at
$X/seat/month while keeping the engine source-available.

**Risks:** vertical sales motion is slow and consultative. Need a design partner per
vertical. Security pack is the only one we can credibly ship today; others require
hiring or partnerships.

**Why now:** workflow YAML is the most under-marketed thing in the repo. Packs make it
visible and monetizable without changing the core license.

---

### 3. Enclave Teams — minimal multi-user server

**Pitch:** Most "local LLM" tools assume one user. Small teams (5–50 people) in
regulated shops (healthcare, legal, defense, finance) want a shared box. The
ENTERPRISE_DEPLOYMENT_GAPS doc lists exactly what's missing: API key per user, RBAC,
audit log, rate limiting per principal, structured logging, Prometheus.

**Why it fits:** these are mostly known-cost engineering tasks, and the gap doc is
already written. Auth surface exists in `api_key_service.py`; we just haven't put a
team model on top.

**MVP shape:** `users` table, per-user API keys, per-user workspace (we have
`project_service.py`), audit log of completions + tool calls, admin UI for usage. Ship
behind a paid tier; community edition stays single-user.

**Risks:** "enterprise lite" is a crowded grave (look at how Open WebUI is iterating).
We win only if Teams is the obvious upgrade path from the single-user DMG, which
requires marketing investment we may not have.

**Why now:** the Mac DMG creates a natural funnel — solo users who love it want to put
it on a team box. We have no story for that today.

---

### 4. Mobile companion via Tailscale

**Pitch:** iOS/Android app that talks to your Enclave server over a Tailnet. The
killer message: "your phone's AI is your AI, on your hardware." No OpenAI, no Apple
Intelligence, no Gemini — your home server with your data.

**Why it fits:** OpenAI-compatible API means we don't have to invent a protocol. A
small SwiftUI/Compose app pointed at `https://enclave.your-tailnet.ts.net/v1/` ships
in weeks. Voice mode = whisper.cpp on-device transcription → API → local TTS.

**Risks:** mobile dev is its own discipline; app store distribution is a tax. We'd
need to decide if this is open-source, paid, or a loss-leader for Teams.

**Why now:** every chat app on every phone is plumbing user data to a cloud LLM. The
"my AI lives in my house" pitch is differentiated and easy to grasp.

---

### 5. Workflow IDE — visual DAG editor for non-devs

**Pitch:** Today, authoring a workflow means writing YAML by hand. A visual editor
(drag-and-drop nodes, prompt editor with live preview, output parser inspector,
quality-gate config) makes the engine usable by analysts, not just engineers.

**Why it fits:** the nocode-workflow-composer design doc already exists in
`docs/plans/2026-04-09-*`. The dashboard is the natural home. This unlocks (2) above
— vertical packs need authors, and authors need a UI.

**MVP shape:** React Flow canvas → emits the existing YAML → executes through the
existing engine. Read-only "view mode" first, then editable.

**Risks:** building a visual editor is months, not weeks. Easy to over-scope. If the
target user is "SOC analyst," we should validate the demand before building the IDE
vs. just shipping pre-made workflows (option 2).

**Why now:** workflows are our moat. The faster we lower the authoring bar, the more
workflows exist, the more sticky the platform.

---

### 6. Privacy-paranoid prosumer build

**Pitch:** Lean fully into the "no telemetry, no cloud" promise. Encrypted-at-rest
conversation history (libsodium), ephemeral chat mode (RAM-only, no disk), Tor/I2P
support for remote access, signed reproducible builds. Target journalists, activists,
lawyers, researchers in hostile jurisdictions.

**Why it fits:** the uncensored-first model curation + zero telemetry + local-only
narrative already aligns. This is a sharpening, not a pivot.

**Risks:** small market, evangelism-heavy sales, and the threat model is hard to
deliver on credibly (Mac DMG is unsigned today, no reproducible build chain). Easy to
overpromise.

**Why now:** the broader market trend is the wrong direction (every IDE/OS is shipping
cloud AI by default). A small but loud audience would adopt this and become advocates.

---

### 7. Model-comparison lab as the front door

**Pitch:** Reframe the dashboard around "try N models against your prompt in 30
seconds." Side-by-side outputs, latency, tokens/sec, cost-equivalent ($ saved vs.
GPT-4). This is the wedge that gets developers to install Enclave even if they don't
buy the agentic story.

**Why it fits:** `benchmark.py` exists. Multi-model serving exists. We need a UI that
makes comparison feel like the primary product surface, not a CLI afterthought.

**Risks:** this is a feature, not a product. Useful for top-of-funnel but doesn't
itself monetize. Should be ~2 weeks of dashboard work, not a strategic direction on
its own.

**Why now:** developers researching local LLMs cycle through Ollama/LM Studio/Jan
testing models. If our app is the best at that one job, we steal that moment.

---

## My read

If I had to pick one bet: **(1) Enclave Code**. It uses every interesting thing we've
built, the market has been primed by Claude Code/Cursor, and a credible offline
competitor doesn't exist. Vertical packs (2) is the right *commercial* bet but needs
design partners we don't have yet.

The cheapest move with the highest narrative payoff is **(7) model lab as front
door** — a one-sprint dashboard refresh that fixes the "we look like a chatbot"
problem and seeds developer adoption while we decide on the big bet.

Avoid (3) Teams as the next move. The enterprise gaps doc is a tarpit — fixing 60
checkboxes doesn't make a product, and we'd lose 6 months without a differentiated
story.

## Open questions

- Who is the 1.0 user actually? We don't have telemetry (by design) so we're guessing.
  Worth a survey banner on the dashboard before committing to a direction.
- Is this a venture-backed product, a sustainable indie OSS project, or a hardware
  appliance play (sell the BD790i pre-loaded)? Each implies a different bet here.
- Source-available license + paid packs is workable, but we should pick the packs
  before we tune the license.
