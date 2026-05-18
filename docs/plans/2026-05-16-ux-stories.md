# Enclave UX Review — Where to Build Delightful User Stories

**Date:** 2026-05-16
**Scope:** Current 1.0 surfaces — Mac DMG / Docker / source install, dashboard SPA,
CLI tools (chat / query / workflow), API keys, workflows, recovery paths.

## Assessment

The platform is **intent-rich and discovery-poor**. The setup wizard is genuinely
elegant; `run.sh` output is scannable; the dashboard header is thoughtfully styled;
CLI tools respect Unix conventions. None of that compounds into a delightful arc,
though — users who reach the dashboard are mostly oriented, but those hitting errors,
needing to integrate with their tools, or looking for the value receipt (privacy,
cost) get nothing back.

The thesis of this doc: stop adding features for a while and engineer **signature
moments** at the 6 inflection points of the user journey. The infrastructure is
already there; what's missing is the framing, the copy, and 5–10 hours of UX polish
per moment.

## Six moments to engineer

```
   1            2            3            4            5            6
download → first model → first chat → first integ → second use → first error
   ↓            ↓            ↓             ↓             ↓             ↓
[opens DMG] [picks model] [types prompt] [in their IDE] [next day]  [ollama crash]
```

Today, moments 1–2 are good. Moments 3–6 are where the delight gap lives.

---

## Moment 1 — Download → DMG opens (already good)

The wizard is solid (`api/static/setup.html` + `api/routers/setup.py`). The few
remaining stories:

**Story 1.1 — Hardware-aware defaults**
*As a user opening the DMG on my M4 Pro 48GB, I want the wizard to pre-select a model
that fits comfortably (~30% of RAM), not the same three defaults everyone sees.*
- Today: wizard shows fixed dolphin3:8b / qwen2.5:14b / deepseek-r1:32b.
- Tomorrow: probe `sysctl hw.memsize` and CPU on first paint; mark the recommended
  card with a "fits your Mac" pip. Show the others without a recommendation badge.
- Evidence of value: removes the only real cognitive load in the wizard.

**Story 1.2 — Honest preflight**
*As a user with 30GB free disk, I want the installer to tell me before download that
the model I picked needs 25GB and I'll have 5GB left.*
- Today: `setup/install.sh` shows warnings only and proceeds anyway.
- Tomorrow: hard block at <2× model size remaining; offer the next-smaller variant.

---

## Moment 2 — First model running (good, one delight gap)

**Story 2.1 — Land warm, not cold**
*When the wizard finishes, I want to land on a screen that says "try this" with a
prompt already filled in, not on a dashboard that assumes I know what to do.*
- Today: setup → dashboard. No breadcrumb, no "you just installed X."
- Tomorrow: setup's last step is a chat card — pre-filled with "What can you do?",
  one-click send, response streams in. Dashboard is reachable but not the landing.
- Why this matters: first-token-streaming is **the** moment a user becomes a fan of
  local LLMs. Most never see it because they have to navigate to find chat.

---

## Moment 3 — First chat (mediocre today)

**Story 3.1 — Conversation persistence**
*As a user, I want to close Enclave, come back tomorrow, and find my conversations
where I left them.*
- Today: `cli/chat.py` history is in-memory; dashboard chat persistence is unclear
  from the audit (likely localStorage at best).
- Tomorrow: SQLite-backed conversation store. Sidebar lists yesterday's threads.
- Effort: ~1 day. `session_manager.py` exists; just needs a chat-specific table.

**Story 3.2 — Mid-conversation model switch**
*I'm chatting with a small model, hit a hard question, and want to send just this
next turn to a 32B model — without restarting the conversation.*
- Today: model is set per-conversation in OpenAI-compat API; switching means a new
  thread.
- Tomorrow: model selector in the message composer; "this turn only" toggle.

**Story 3.3 — Receipts**
*After each response I want to see: tokens, time, "≈ $0.04 on GPT-4."*
- Today: nothing.
- Tomorrow: small dim footer under each response. The "≈ on GPT-4" line is the
  delight — it reinforces the privacy/cost story without nagging.

**Story 3.4 — Streaming is visible**
*As I type and send, I want to see tokens appear word-by-word, not a 4-second wait
then a wall of text.*
- The API streams; need to verify the dashboard chat consumes the SSE stream and not
  the buffered endpoint.

---

## Moment 4 — First integration (the biggest opportunity)

This is the moment that converts a curious user into a power user. It is currently
**invisible**.

**Story 4.1 — Drop-in switch, one paste**
*As a developer using OpenAI from Python, I want to switch to Enclave by pasting one
snippet I copy from the dashboard.*
- Today: user has to know the API is OpenAI-compatible and find `localhost:8000/v1`
  somewhere.
- Tomorrow: dashboard has an "Integrate" tab. Big code block with a copy button:
  ```python
  from openai import OpenAI
  client = OpenAI(base_url="http://localhost:8000/v1", api_key="sk-enclave-...")
  ```
  Pre-filled with their machine's hostname when they ask "From another machine?",
  pre-filled with a freshly-created API key when they ask "I need auth."
- Below: ready-to-copy snippets for VS Code Continue, Cursor, Aider, Obsidian's
  Smart Connections, the Anthropic SDK pointed at the same endpoint (where
  compatible), `curl` for shell users.
- Effort: ~1 day of UI work + writing the snippets.

**Story 4.2 — API key in two clicks**
*I want to make a key, name it "My VS Code", copy it, and paste it into Continue's
config.*
- Today: no UI. Master key concept is undocumented. `api/routers/api_keys.py` only
  accepts master-key auth.
- Tomorrow: Settings → API Keys → "+ New key" → modal asks name and scopes (default:
  "chat + completions") → key is shown once with a copy button and a warning. List
  shows last-used timestamp and "this key was used by X.X.X.X 2 minutes ago."
- Pair with 4.1: the snippet in the Integrate tab can deep-link "Create a key for
  this integration."

**Story 4.3 — "Where is this server reachable?"**
*I want to know my Enclave's URL on my home network so my phone can use it.*
- Today: not shown. User has to know to look up their IP.
- Tomorrow: Settings → Network shows: `localhost` + `192.168.x.x` + Tailscale name
  if `tailscale status` parses. Copy-button next to each. A "scan QR code" for
  mobile.

---

## Moment 5 — Second use (lost / found)

**Story 5.1 — Resume where I left off**
*I open Enclave the next day. I see my last conversation, my last workflow run, and
the model that's already loaded.*
- Today: starts blank.
- Tomorrow: dashboard top row shows three cards — "Continue this conversation" /
  "Re-run this workflow" / "Last 5 things you did."
- Effort: ~1 day. Existing context_store + session_manager have the data.

**Story 5.2 — Workflows feel like apps**
*I want to run a workflow without writing YAML, without knowing it's a workflow.*
- Today: workflows are file-on-disk + dashboard list. Authoring is YAML.
- Tomorrow: workflows surface as "Quick Actions" with friendly names. The XSIAM
  workflows already ship → "Generate XSIAM rules from a log sample" is the user
  story, not "Run xsiam-data-model-rules.yaml."
- Effort: metadata pass on existing workflow YAMLs (`metadata.user_facing_name`,
  `inputs_schema`), plus a card grid on the dashboard. ~2 days.

**Story 5.3 — Resume a failed workflow**
*Workflow failed at step 4. I want to fix the prompt and resume from 4, not redo
1–3.*
- Today: checkpoint/resume exists in the engine. CLI has `--resume`. Dashboard?
  Audit didn't confirm.
- Tomorrow: failed step in the run timeline is clickable → opens the step editor →
  "Resume from here" button. The engine work is done; expose it.

---

## Moment 6 — First error (currently brutal)

**Story 6.1 — Ollama isn't running**
*Instead of "Ollama service is not responding," I want "Ollama isn't running" + a
"Start Ollama" button.*
- Today: 503 with cryptic body.
- Tomorrow: middleware catches `OllamaConnectionError`, dashboard shows a banner
  with the button. CLI prints `enclave doctor` next-step. The DMG version can
  literally start Ollama; the Docker version can `docker compose start ollama`.

**Story 6.2 — Out of RAM is explained**
*If I try to load a 70B model on a 16GB box, I want Enclave to tell me before the
crash, not after.*
- Today: Ollama dies, dashboard pip goes gray, no message.
- Tomorrow: model picker greys out models that exceed available RAM with a tooltip
  ("Needs ~50GB. You have 16GB free.") Hardware probe from Story 1.1 reused.

**Story 6.3 — Failed download is resumable**
*If my model pull dies at 60%, I want to resume the next time I click, not start
over.*
- Today: setup wizard shows the error string from Ollama.
- Tomorrow: detect partial blob, offer "Resume" vs. "Restart". Ollama supports
  resumption natively; we just need to expose it.

**Story 6.4 — `enclave doctor`**
*One command that checks everything and prints what to fix.*
- Today: doesn't exist.
- Tomorrow: a CLI subcommand + a dashboard page that checks: Ollama reachable, disk
  space, RAM headroom, API auth configured, CORS not wildcard if non-local,
  registry vs. installed-models drift. Each row: ✓ / ⚠ / ✗ with the fix command.
- This single feature replaces dozens of forum questions.

---

## Two cross-cutting "signature moments"

**Story X.1 — The Privacy Ledger**
*A small persistent number on the dashboard: "12,438 prompts. 0 left your
machine."*
- Cheap to build (count completions). Reinforces the entire product thesis on every
  page load.

**Story X.2 — The Cost Ledger**
*"You've saved an estimated $84 vs. GPT-4 this month."*
- Optional toggle. Some users will love it; others will find it gauche. Off by
  default.

---

## Prioritization

| Priority | Stories | Why |
|----------|---------|-----|
| **P0** — Ship next sprint | 4.1 (Integrate tab), 4.2 (API key UI), 6.1 (Ollama-not-running banner), 6.4 (`enclave doctor`) | These four convert curious users into power users and prevent abandonment on first error. ~1 week of work. |
| **P1** — Next month | 2.1 (warm landing), 3.1 (persistence), 3.3 (receipts), 5.1 (resume cards) | Each one is a small delight that compounds across daily use. |
| **P2** — Polish pass | 1.1 (hardware-aware defaults), 5.2 (workflows-as-apps), 6.2 (RAM gating), X.1 (privacy ledger) | After the core arc is sealed. |
| **P3** — When natural | 3.2 (mid-convo model switch), 5.3 (workflow resume in UI), 4.3 (network discovery), 6.3 (resumable downloads), X.2 (cost ledger) | Each is a delight but not urgent. |

## What we are explicitly not doing

- **Redesigning the dashboard.** The 9,457-line `index.html` is real tech debt, but
  splitting it is a refactor, not a UX win. Park it.
- **Replacing Open WebUI.** Docker users have it; let it be the chat client for that
  path. The dashboard's chat is a "good enough" alternative for DMG users.
- **Generic onboarding tour.** Tours are tab-and-click rituals nobody completes. The
  warm-landing card (2.1) is the entire tour, done well.
- **Walls of help text.** Every story above is engineered into the moment, not
  documented as a separate help page.

## Estimated effort

The P0 bundle (4.1 + 4.2 + 6.1 + 6.4) is ~1 engineer-week. Each P1 story is ~1–2
days. The whole list is shippable in a ~6-week UX sprint — comparable to the
Enclave Code M1 spec, and arguably a better use of that time if we're prioritizing
adoption over feature breadth.
