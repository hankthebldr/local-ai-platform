# Enclave 1.1 → 1.2 Roadmap — Spec

**Status:** Draft for sign-off
**Date:** 2026-05-16
**Supersedes individual planning docs as the canonical source of scope.**

This is the consolidating document for the work specced in the
`2026-05-16-*` series. Read this first; the per-area specs are
referenced where deeper detail lives.

## 1. Vision

After 1.0, Enclave is "OpenAI-compatible local LLM with a Mac app." That
positioning undersells what shipped: a workflow engine, MCP client,
plugin system, A2A, sandboxed tool execution, knowledge graph,
projects. We're priced as a chatbot and built as an agent runtime.

**The 1.1 → 1.2 thesis:** turn that gap into the product. Make Enclave
the *credible local agentic workspace* — one where the user can author
content, run multi-agent work over it, and see exactly what the model
used to produce each answer. All local, no telemetry, no per-seat
subscription.

Three workstreams achieve this:

- **A. Foundation** — content lifecycle infrastructure (`ProvenanceEdge`,
  per-project scoping, content inventory shell, citations).
- **B. Enclave Code** — flagship agentic feature; proves the multi-agent
  story is real and ships a use case people pay for elsewhere.
- **C. UX Polish** — first-touch + recovery moments that convert curious
  users into power users.

## 2. Outcomes (success criteria)

Measurable at the 1.2 release:

| # | Outcome | Measure |
|---|---------|---------|
| O1 | Every chat response shows what shaped it | 100% of responses have a citation rail when provenance is enabled; ≤5% of rails show "no sources tracked" |
| O2 | Local agentic coding is credible | `enclave code` resolves ≥30% of SWE-bench Lite tasks at pass@1 on `qwen2.5-coder:32b`; ≥1 internal team member uses it for real work weekly |
| O3 | First-error abandonment drops | `enclave doctor` exists; "Ollama not running" surfaces a recovery button; ≤3 user-reported "didn't know what to do" reports per week post-1.2 |
| O4 | Integration paths are obvious | Integrate tab exists; copy-paste snippets for VS Code Continue / Cursor / Aider / Python / curl ship with the dashboard; ≥1 community-contributed integration recipe |
| O5 | Content is curatable, not just usable | Skills, MCPs, projects each have an inventory tab; doc audit surfaces "never cited"; per-project scoping works for at least 3 content types |
| O6 | Privacy positioning stays sharp | Zero telemetry endpoints added; provenance ledger fully local + clearable; setup wizard checkbox copy follows the user-centric pattern from the decisions doc |

A 1.2 that doesn't deliver O1, O2, and O3 is not a release.

## 3. Scope

### In scope

**A — Foundation:**
- `ProvenanceEdge` data model + SQLite persistence + 8 emission sites
- Citation rail UI on chat responses
- Shared content inventory shell (one component, parametrized by content kind)
- Skills tab, MCP catalog tab, Projects tab built on the shell
- Per-project scoping for skills, MCPs, RAG corpora
- Project templates: Code Review, Security Analyst, Knowledge Base
- `enclave doctor` CLI + dashboard panel

**B — Enclave Code:**
- `cli/code.py` REPL + one-shot modes
- 3-step plan/edit/verify workflow (`workflows/enclave-code.yaml`)
- `plugins/code/` with read/write/apply_patch/search/bash/git tools
- Three permission profiles (readonly, code-default, auto-accept)
- Worktree-per-session isolation
- 9 behavioral skills (M1)
- `code_session.py` auto-injected context (~5K tokens)
- Three lazy session-scoped RAG indexes (code, history, docs)
- SWE-bench Lite eval harness + baseline numbers

**C — UX Polish:**
- Integrate tab with copy-paste snippets
- API key creation UI (full lifecycle)
- Ollama-not-running banner with recovery action
- Warm landing after setup wizard
- Conversation persistence
- Response receipts (tokens, time, cost-equivalent)
- "Continue this conversation" / "Re-run this workflow" resume cards
- Workflows-as-apps surface (friendly names for existing XSIAM workflows)

### Out of scope (deferred)

From the brainstorm directions:
- **Direction 2** (Vertical workflow packs as a commercial product) — needs
  design partners we don't have. Workflows-as-apps in 1.2 prepares the
  surface but doesn't monetize.
- **Direction 3** (Enclave Teams / enterprise multi-user) — deliberately
  parked per the brainstorm.
- **Direction 4** (Mobile companion via Tailscale) — defer to 1.3.
- **Direction 5** (Workflow IDE / visual editor) — defer; the nocode-composer
  design exists from April but lower priority than the lifecycle UX.
- **Direction 6** (Privacy-paranoid prosumer build) — sharpened messaging in
  1.2 (provenance, no telemetry) is the down-payment; full build deferred.

From the UX stories:
- Dashboard refactor (9,457-line `index.html` → component split). Tech debt,
  not a UX win.
- Open WebUI replacement.
- Generic onboarding tour.

From the lifecycle review:
- Generic CMS surfaces.
- Multi-user content sharing.
- Auto-curation by AI.

From the Enclave Code spec:
- VS Code / JetBrains extension (deferred to M3 after 1.2).
- Cross-repo / monorepo workspace context.
- Fine-tuning a custom coder model.

## 4. Workstreams

### A. Foundation

**A1. ProvenanceEdge** (canonical: `2026-05-16-provenance-edge-spec.md` +
`2026-05-16-provenance-edge-decisions.md`)
- Data model + migrations runner + 8 emission sites + 6 query endpoints
- 7 engineer-days, 3 phases (M1.0 / M1.1 / M1.2)
- Closes outcomes O1, contributes to O5

**A2. Content inventory shell** (canonical: §"Cross-cutting patterns / D" in
`2026-05-16-content-lifecycle-review.md`)
- Generic React/vanilla shell for list/detail/install/toggle of any content
  kind. Mirrors existing Inventory (models) + Workflow Index UI.
- Reusable across A3, A4.

**A3. Skills + MCPs tabs**
- Skills tab: browse, enable, inspect, diff (depends on A2).
- MCP catalog tab: browse curated MCPs, install, health rail, per-project
  scope (depends on A2).

**A4. Projects UI**
- Projects tab on the dashboard (depends on A2).
- 3 templates (Code Review, Security Analyst, Knowledge Base).
- Project doctor (preflight checks).
- Per-project scoping rollout for skills/MCPs/RAG.

**A5. `enclave doctor`**
- CLI subcommand + dashboard panel.
- Checks: Ollama reachable, disk, RAM headroom, API auth configured, CORS
  not wildcard if non-local, model registry vs. installed drift.
- Closes outcome O3.

### B. Enclave Code

**B1. CLI + session model** (canonical: `2026-05-16-enclave-code-spec.md`)
- `cli/code.py` REPL, `code_session.py`, worktree-per-session.

**B2. Code plugin** (canonical: `§"The 'code' plugin"` in the spec)
- 7 tools: read, search, write, apply_patch, bash, git_status, git_commit.
- Sandboxed via existing `SandboxedFS`.

**B3. Workflow + agents**
- `workflows/enclave-code.yaml` (plan/edit/verify).
- Three agent personas in `agents/`.

**B4. Skills + context** (canonical:
`2026-05-16-enclave-code-context-skills-buildout.md`)
- 9 behavioral skills in `plugins/code/skills/`.
- Loader extension: `triggers: ["*"]` for always-on.
- `code_session.build_initial_context()`.
- `code_indexer.py` with three indexes.
- Opt-in `code_memory.py`.

**B5. Model registry additions** (canonical:
`2026-05-16-enclave-code-additions.md`)
- 5 new entries: `qwen2.5-coder:32b/14b/7b`, `qwen2.5:14b`,
  `nomic-embed-text`. Pre-register 4 MCPs.

**B6. Eval harness**
- SWE-bench Lite subset (50 tasks).
- Internal regression suite (20 tasks from this repo's history).
- Tool-call reliability metrics.
- Closes outcome O2 (gate the release on it).

### C. UX Polish

**C1. Integrate tab** (UX P0)
- New tab on dashboard.
- Code blocks with copy buttons for VS Code Continue, Cursor, Aider,
  Python, curl. Pre-filled with the user's host and a freshly-created key.
- Closes outcome O4.

**C2. API key UI** (UX P0)
- Settings → API Keys: create, name, copy-once, list with last-used, rotate,
  revoke. Surfaces the full lifecycle that already exists in the backend.

**C3. Ollama-not-running banner** (UX P0)
- Middleware-level error → friendly banner with "Start Ollama" button (DMG)
  or `docker compose start ollama` hint (Docker).

**C4. Warm landing** (UX P1)
- Setup wizard's final step is a chat card pre-filled with "What can you do?"
- One-click send, response streams in. Dashboard reachable but not the
  landing.

**C5. Conversation persistence** (UX P1)
- SQLite-backed conversation store. Sidebar lists prior threads.

**C6. Response receipts** (UX P1)
- Small dim footer under each response: tokens, time, "≈ $X on GPT-4."
- Pairs naturally with the citation rail.

**C7. Resume cards** (UX P1)
- Dashboard top row: "Continue this conversation" / "Re-run this workflow" /
  "Last 5 things you did."

**C8. Workflows-as-apps** (UX P1)
- Metadata pass on existing workflow YAMLs (`user_facing_name`,
  `inputs_schema`).
- Quick Actions card grid on the dashboard. "Generate XSIAM rules from a log
  sample" instead of "Run xsiam-data-model-rules.yaml."

## 5. Cross-workstream dependencies

```
A1 (Provenance) ──────┬──→ C1 (Integrate) ── independent ── C2, C3, C4
                      │                                         │
                      ├──→ A3 (Skills/MCPs tabs) ─→ A4 (Projects UI)
                      │       (uses citation rail data)            │
                      │                                            │
                      └──→ C6 (Receipts) ─ uses provenance for cost
                                                                   │
A2 (Inventory shell) ─┴─→ A3, A4 (consume the shell)               │
                                                                   │
B1 (CLI/session) ──→ B2 (Code plugin) ──→ B3 (Workflow) ──→ B6 (Eval)
                                            │
                                            └─→ B4 (Skills/context)
                                                       │
B5 (Models/MCPs) ─ independent, can preload at any time┘

C5 (Persistence) ─ feeds C7 (Resume cards) and unlocks C4 (warm landing has
                   somewhere to land)
C8 (Workflows-as-apps) ─ independent
```

**Critical path:** A1 → C6 → B6 (provenance must ship before receipts can
reference cost; eval must ship before B is GA).

**Parallelizable bundles:** {A1 + B1 + C1} can start day 1. {A2 + B2 + C2}
follows once A1's contracts stabilize.

## 6. Non-functional requirements

| NFR | Requirement |
|-----|-------------|
| Privacy | Zero new telemetry endpoints. Every new data model has a local-only constraint baked into its design (provenance) or is inherent (skills, projects). |
| Performance | Provenance emission ≤1 ms/edge on hot path (§"Performance" in provenance spec). Enclave Code first-token latency ≤2 s on `qwen2.5-coder:32b` on the MS-01 reference box. |
| Backwards compat | All API additions are additive. No breaking changes to `/v1/*` (OpenAI compat) or `/api/*` (internal). |
| Backwards compat (data) | Existing `data/` layout untouched. New stores (`data/provenance.sqlite`, `~/.enclave/sessions/`) are additive. |
| Migration | Provenance schema uses the migrations runner (specced in decisions doc). All schema changes go through it. |
| Observability | Internal Prometheus counters for provenance writes, drops, retention purges, Enclave Code session creation/completion. No metrics leave the box. |
| Documentation | Each shipped workstream has a docs section in README + a dedicated `docs/` page. Roadmap completion includes the doc pass. |

## 7. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Local coder model tool-call reliability too low for credible Enclave Code | High | Show-stopper for O2 | Eval gates the release. If pass@1 < 15% on SWE-bench Lite, ship as "Preview" with honest framing; do not block on hitting 30% if quality is otherwise good. |
| R2 | ProvenanceEdge hot-path overhead breaks chat latency | Medium | Visible regression | Performance tests in M1.0 (1K edges in <2s, burst 100/100ms). Drop-on-backpressure design protects the engine. |
| R3 | Inventory shell scope-creep — every content type wants special-case UI | Medium | Slips A3/A4 | Pin the shell's parameter list before starting A3. Special cases get added on top as separate components, not by extending the shell. |
| R4 | Workflows-as-apps reveals broken workflows we'd shipped | Low | Embarrassing | Audit pass on all `workflows/*.yaml` before surfacing them. Hide any that fail validation. |
| R5 | DMG signing / notarization regression during 1.2 release | Medium | Mac users blocked | The macOS smoke build in CI catches binary regressions; sign/notarize is still manual. Track as a pre-existing 1.0 gap; do not let it block 1.2. |
| R6 | Eval compute time exceeds sprint budget | Medium | Slips B6 | SWE-bench Lite subset (50 tasks) is the gating set; full 300-task runs are post-1.2. Run on the BD790i flagship, not CI runners. |
| R7 | The 9,457-line `index.html` makes the new tabs (A3/A4) painful to add | High | Slows C-track | Inventory shell ships as a self-contained component file; tabs in `index.html` get a single `<div id="...">` placeholder and a script tag. Defer the full SPA refactor. |
| R8 | Citation rail copy / framing causes user confusion | Low | Slows O1 reception | Decisions doc pins the copy. Internal dogfood for 2 weeks behind the flag before default-on. |

## 8. Versioning and release targets

| Version | Contents | Target |
|---------|----------|--------|
| 1.1.0 | Workstream A complete (foundation) + C P0 items (C1–C3) | Sprint 2 end |
| 1.1.1 | A4 + C P1 items (C4–C7) | Sprint 3 end |
| 1.2.0-preview | All of A + C + Enclave Code as opt-in feature flag | Sprint 4 end |
| 1.2.0 | Full release with B6 eval signed off; flag removed | Sprint 6 end |

## 9. References

Each workstream's authoritative design doc:

| Workstream | Doc |
|-----------|-----|
| Vision context | `2026-05-16-product-brainstorm.md` |
| A1 (Provenance) | `2026-05-16-provenance-edge-spec.md` + `2026-05-16-provenance-edge-decisions.md` |
| A2–A5 (Lifecycle, Inventory, Projects) | `2026-05-16-content-lifecycle-review.md` |
| B1–B3, B5 (Enclave Code core) | `2026-05-16-enclave-code-spec.md` + `2026-05-16-enclave-code-additions.md` |
| B4 (Code skills + context) | `2026-05-16-enclave-code-context-skills-buildout.md` |
| C-track UX | `2026-05-16-ux-stories.md` |

Implementation sequencing lives in the companion plan:
`2026-05-16-implementation-plan.md`.
