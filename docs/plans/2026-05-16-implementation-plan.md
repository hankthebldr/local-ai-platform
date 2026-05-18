# Enclave 1.1 → 1.2 — Implementation Plan

**Companion to:** `2026-05-16-roadmap-spec.md`
**Date:** 2026-05-16

How the roadmap gets built: team shape, six sprints, what ships per sprint, quality
gates, and the risk register with owners.

## 1. Team shape (assumed)

This plan assumes a small team. Adjust the parallelism if the actual team differs.

| Role | Count | Primary tracks |
|------|-------|----------------|
| Backend engineer (Python) | 1.5 FTE | A1, A2, A4, B1–B6 |
| Frontend engineer (HTML/JS or React) | 1 FTE | A2, A3, A4, C1–C8 |
| Design / PM (combined or split) | 0.5 FTE | UX copy, eval design partner liaison, release coordination |
| Eval / QA (part of backend FTE) | 0.25 FTE | B6, performance tests |

**Critical-path operator:** the backend engineer with 1.5 FTE allocation. The plan
falls apart if that's <1 FTE. If you only have 1 backend FTE total, drop B4
(Enclave Code context modules) into 1.3 — that's the cheapest cut without
gutting the release.

## 2. Phasing — six sprints, ~12 weeks

Each sprint is two weeks. Ship goals are concrete; deliverables list what should
be merged + reviewable at sprint end. Numbering references the workstreams from
the roadmap spec.

### Sprint 1 (weeks 1–2): Foundation core

**Ship goal:** ProvenanceEdge end-to-end with citation rail visible behind a flag.

**Deliverables:**
- [B] A1.M1.0 — data model, SQLite + migrations runner, ContextStore additions,
  `response_id` plumbing through 6 service methods, emission sites #1 (tools)
  and #2 (skills), `/api/provenance/response/{id}` endpoint.
- [B] A1.M1.1 — emission site #3 (RAG), dashboard chat path audit + unification.
- [F] A1.M1.1 (UI) — citation rail component, hooked into chat response render
  behind `ENABLE_PROVENANCE_UI=true`.
- [B] C3 — Ollama-not-running banner: middleware catches the error → structured
  banner payload → frontend renders with action button.
- [B] A5.cli — `enclave doctor` CLI subcommand (checks; no dashboard view yet).
- [F] Resume the A2 shell scaffolding (no content kinds wired yet).

**Quality gate:** provenance perf test passes (1K edges <2s, 100/100ms burst).
Citation rail renders for 10 sample responses. Dogfood by team for 1 week.

**Not in this sprint:** full UI exposure (flag stays off externally). MCP / agent
emission sites. Inventory shell wired to real content kinds.

### Sprint 2 (weeks 3–4): Full provenance + integration UX

**Ship goal:** 1.1.0 release-ready. Citation rail default on. New users can
integrate Enclave with their tools in 60 seconds.

**Deliverables:**
- [B] A1.M1.2 — emission sites #4–#8 (MCP, agent_step, memory, web, auto_context),
  resolver registry, Settings → Privacy panel.
- [F] A1 — citation rail goes default-on; flag retained for opt-out.
- [F] C1 — Integrate tab with copy snippets for VS Code Continue, Cursor, Aider,
  Python (OpenAI SDK + Anthropic SDK), curl.
- [F] C2 — API key UI: create / name / copy-once / list / rotate / revoke.
- [F] A5.ui — `enclave doctor` dashboard panel (same checks as CLI).
- [B] A2 — content inventory shell, parametrized over content kind; ship it
  wired to Skills as the first real content kind.

**Quality gate:** 1.1.0 release candidate cut. Internal sign-off on citation
rail copy and Integrate tab snippets. `enclave doctor` catches every documented
1.0 failure mode (manual checklist).

**Release: 1.1.0 ships at end of sprint 2.**

### Sprint 3 (weeks 5–6): Projects + Enclave Code start

**Ship goal:** Projects exist as a first-class dashboard surface. Enclave Code's
CLI runs `--plan-only` against a real repo.

**Deliverables:**
- [F] A3 — MCP catalog tab built on the A2 shell. Pre-registered MCPs from the
  Enclave Code additions doc (git, github, sequential-thinking, context7) appear
  disabled-by-default with one-click enable.
- [F] A4 — Projects tab built on the A2 shell. CRUD UI. Three templates: Code
  Review, Security Analyst (XSIAM-bundled), Knowledge Base.
- [B] A4 — Project doctor: preflight checks (roles have models, MCPs healthy,
  RAG indexed with project's embedding model).
- [B] B1 — `cli/code.py` REPL scaffold + `code_session.py` worktree lifecycle.
- [B] B2 (partial) — `code.read`, `code.search`, `code.bash` tools (the
  read-only subset).
- [B] B3 (partial) — `workflows/enclave-code.yaml` with `plan` step only.
- [B] B5 — model registry entries for `qwen2.5-coder:32b/14b`, `qwen2.5:14b`,
  `nomic-embed-text` (sync `MODELS.md`).

**Quality gate:** `enclave code --plan-only "describe this repo"` produces a
coherent plan against a real repo. Projects tab can create / list / archive a
project; project doctor flags a deliberately-broken project correctly.

### Sprint 4 (weeks 7–8): Enclave Code completion + UX P1

**Ship goal:** Enclave Code ships as preview. UX delight moments land.

**Deliverables:**
- [B] B2 — full code plugin: `code.write`, `code.apply_patch`, `code.git_status`,
  `code.git_commit`. Sandboxed via `SandboxedFS`.
- [B] B3 — full plan/edit/verify workflow. Approval prompts in REPL.
- [B] B4 — 9 skills in `plugins/code/skills/`, loader extension for
  `triggers: ["*"]`, `code_session.build_initial_context()`, `code_indexer.py`
  (repo-code index only — history + docs deferred to S5).
- [F] C4 — warm landing: setup wizard's final step becomes a "try this" chat
  card.
- [F] C5 — conversation persistence: SQLite-backed conversation store, sidebar
  lists prior threads.
- [F] C6 — response receipts (uses provenance data for cost-equivalent).

**Quality gate:** `enclave code "fix the failing auth test"` runs end-to-end on
a planted bug in this repo. Receipts show cost-equivalent for at least the
3 starter models. Setup → warm landing → first response works without manual
nav.

**Release: 1.1.1 ships at end of sprint 4 (UX P1 bundle); Enclave Code stays
behind a feature flag (`ENABLE_ENCLAVE_CODE=true`).**

### Sprint 5 (weeks 9–10): Polish + scoping + eval

**Ship goal:** Per-project scoping works; eval results in hand.

**Deliverables:**
- [B] B4 — `code_indexer.py` history + docs indexes. `code_memory.py` opt-in.
- [B] B6 — SWE-bench Lite eval harness. First 50-task run on
  `qwen2.5-coder:32b`. Internal regression suite of 20 tasks from this repo.
  Tool-call reliability metrics.
- [B] A4 — per-project scoping rollout for skills, MCPs, RAG corpora. Each
  content type gets a `scope: project_id | "global"` field; defaults to global
  for migration safety.
- [F] C7 — resume cards on dashboard top row.
- [F] C8 — workflows-as-apps surface. Audit all `workflows/*.yaml` for
  user-facing names. Quick Actions card grid.
- [B] Watched folders for the Documents tab (lifecycle review P1).
- [B] Doc audit panel using provenance data ("never cited in 90 days").

**Quality gate:** SWE-bench Lite pass@1 measured and recorded. Per-project
scoping demoed end-to-end (create project, add skill, verify it's not active
in another project). Watched-folder test: add a file to the folder, see it
indexed within 30s.

### Sprint 6 (weeks 11–12): Release hardening

**Ship goal:** 1.2.0 GA.

**Deliverables:**
- Bug bash on Enclave Code (5 internal users do real work for 3 days).
- Documentation pass: README updates, `docs/enclave-code.md`,
  `docs/citation-rail.md`, `docs/projects.md`.
- Release notes from the doc set.
- Final SWE-bench Lite run on the eval-frozen branch.
- DMG smoke build + manual notarization pass.
- Provenance UI flag removed (becomes default behavior).
- Enclave Code feature flag removed (or stays as `--preview` annotation if
  pass@1 < 15%).

**Quality gate (the release bar):**
- O1: citation rail on 100% of chat responses (sampled across 100 turns).
- O2: SWE-bench Lite pass@1 ≥ 15% (Preview) or ≥ 30% (full release).
- O3: `enclave doctor` returns ✓ on a fresh DMG install with no manual
  config.
- O4: Integrate tab snippets verified working with VS Code Continue, Cursor,
  Aider, Python OpenAI SDK, curl.
- O5: Each of skills/MCPs/projects has a working inventory tab; doc audit
  surfaces ≥1 candidate on a populated test repo.
- O6: No new telemetry endpoints (audit pass on `api/routers/`).

**Release: 1.2.0 ships at end of sprint 6.**

## 3. Critical path

```
Sprint 1                Sprint 2                 Sprint 3              Sprint 4
[A1.M1.0+1.1]──────→[A1.M1.2 + C1+C2]──────→[A4 + B1+B2 partial]──→[B2+B3+B4 + C5+C6]
   provenance         full provenance UI      projects + code start    code complete
        │                  │                       │                       │
        │                  │                       │                       │
        ▼                  ▼                       ▼                       ▼
   [C3 + doctor]      [A2 shell]              [A3 MCPs tab]           [C4 warm land]
   error recovery     inventory shell         (uses A2)               (needs C5)

                                              ─────────────────────────────────────
                                                            │
                                                            ▼
                                                       Sprint 5             Sprint 6
                                                  [B6 eval + B4 finish]──→[hardening + release]
                                                  [A4 scoping + C7/C8]    [bug bash]
                                                  [watched + doc audit]   [docs + DMG + sign-off]
```

**The single critical path edge:** A1 → C6. Response receipts depend on
provenance data for cost-equivalent. If A1 slips, C6 slips. Everything else
has at least one re-route.

## 4. Quality gates between sprints

A sprint doesn't end (and the next doesn't start the planned work) until:

1. **Sprint 1 → 2:** provenance perf tests pass + citation rail dogfoods
   internally for ≥1 week with no major regressions reported.
2. **Sprint 2 → 3:** 1.1.0 ships to nightly and an internal user installs the
   nightly DMG cleanly. `enclave doctor` returns ✓.
3. **Sprint 3 → 4:** `enclave code --plan-only` works on this repo, and the
   Projects tab survives a deliberate misconfig (doctor catches it).
4. **Sprint 4 → 5:** end-to-end Enclave Code session resolves a planted bug
   in this repo without manual intervention (≥1 success in 3 attempts —
   reliability is the eval's job, not this gate's).
5. **Sprint 5 → 6:** SWE-bench Lite pass@1 measured. If <15%, decision point:
   ship Preview, defer release, or cut Enclave Code from 1.2.
6. **Sprint 6 → release:** the 6 outcomes checklist above.

If a gate fails, the next sprint starts with the unfinished work as Day 1
priority, and the deferred items list grows by the equivalent amount.

## 5. Eval & test strategy

**Engine tests (continuous):** existing `pytest tests/` continues. New tests
land alongside each module:
- Provenance: SQLite write/read, edge dedup, retention purge, migrations.
- Code plugin: each tool's happy path + a sandbox-violation test.
- Inventory shell: unit tests for the parametrization layer.

**Performance tests (sprint gate):** provenance hot path. One synthetic
benchmark, recorded results in the PR.

**SWE-bench Lite (B6, sprint 5):** 50-task subset. Run on BD790i. Recorded
results: pass@1, mean time-to-solution, % tool-call schema failures, %
patches that apply cleanly.

**Internal regression suite (B6, sprint 5):** 20 tasks pulled from this
repo's git history. Same model. Same metrics. These tasks exercise patterns
we actually care about (vs. SWE-bench's generic Python).

**Manual UX pass (sprint 6):** every shipped UX story from the UX doc gets a
walkthrough by someone who hasn't built it. Issues from this pass get triaged
into 1.2.x patches.

**Acceptance for release:** outcomes O1–O6 from the roadmap spec, each
measurable, each green.

## 6. Risk register (with owners)

Carried from the roadmap spec § 7, with explicit owners and the trigger
condition that activates each mitigation.

| # | Risk | Owner | Mitigation activates when |
|---|------|-------|---------------------------|
| R1 | Coder tool-call reliability too low | Backend lead | Sprint 5 eval shows tool-call validity <80% → switch primary to deepseek-coder-v2:16b; ship as Preview |
| R2 | Provenance overhead breaks latency | Backend lead | Sprint 1 perf test shows >2 ms/edge → switch to memory-buffered batched writes, accept lossier semantics |
| R3 | Inventory shell scope creep | Frontend lead | A3 starts adding parameters > the pinned list → freeze shell, special-case in caller |
| R4 | Workflows-as-apps surfaces broken workflows | Backend | Sprint 5 audit finds a YAML fails validation → hide it, file follow-up |
| R5 | DMG notarization regression | Release / PM | Sprint 6 manual notarization fails → ship unsigned with `xattr` workaround in README (1.0 had this); fix in 1.2.1 |
| R6 | Eval compute exceeds sprint | Eval (backend) | Sprint 5 day 5 shows <50% of tasks complete → run remaining in parallel on MS-01 + BD790i; reduce to 30-task gating subset |
| R7 | `index.html` 9k-line file makes A3/A4 painful | Frontend lead | A3 estimate doubles → ship A3 as a `<iframe>`-loaded standalone page rather than a true tab. UX hit, schedule preserved |
| R8 | Citation rail copy confusion | Design | Internal dogfood (sprint 1) surfaces complaints → A/B with 2 alternates from the decisions doc |

## 7. Decision log

Decisions already made and pinned (do not re-litigate without explicit
re-open):

| # | Decision | Source |
|---|----------|--------|
| D-1 | Enclave Code is the flagship feature for 1.2 | Brainstorm + roadmap |
| D-2 | Three permission profiles for code: readonly / code-default / auto-accept | Enclave Code spec |
| D-3 | Worktree-per-session isolation; never touch user's branch directly | Enclave Code spec |
| D-4 | Three-step DAG (plan/edit/verify), not single-agent loop, as M1 default | Enclave Code spec |
| D-5 | `qwen2.5-coder:32b` is the default coder model | Additions doc + decisions inheritance |
| D-6 | Skills are always-on via `triggers: ["*"]` (loader extension) | Context/skills build-out |
| D-7 | ProvenanceEdge stays flat; `parent_step_id` in metadata for M2 recursive view | Provenance decisions |
| D-8 | SQLite for provenance; JSONL deferred to a CLI export | Provenance decisions |
| D-9 | 90-day default retention | Provenance decisions |
| D-10 | Setup wizard copy: "Show me what shaped each answer (local-only)" | Provenance decisions |
| D-11 | Two-stage feature flag rollout for the citation rail | Provenance decisions |
| D-12 | Inventory shell is one component, parametrized over content kind | Lifecycle review |
| D-13 | Per-project scoping rolls out additively (default global, opt into project) | Lifecycle review |
| D-14 | Defer dashboard SPA refactor; tabs hook into `index.html` | UX stories |
| D-15 | Defer Teams / multi-user / mobile to 1.3+ | Brainstorm |

## 8. Open items requiring user input

These are decisions the roadmap can't make on its own. Before sprint 1
kickoff, confirm:

1. **Team shape.** Is the 1.5 + 1 + 0.5 assumption right? If not, the
   sequencing changes — see §1 fallback (drop B4 if backend <1.5 FTE).
2. **Eval gate.** Roadmap says O2 = ≥30% pass@1 for full release, ≥15% for
   Preview. Is that the right bar, or should it be looser? (Aider's
   published numbers on similar models are in the 20–30% range.)
3. **License posture for Enclave Code.** Source-available like the rest, or
   gated? Flagged in the Enclave Code spec; no decision yet.
4. **Name for Enclave Code.** Spec used the name; we should confirm before
   shipping marketing copy.
5. **Release marketing.** Does 1.2 want a coordinated launch (blog post,
   demo video, HN post) or a quiet ship? Drives sprint 6 day-allocation.
6. **DMG signing.** Will 1.2 finally have a signed/notarized build, or
   continue with the `xattr` workaround?

A 15-minute conversation closes all six.

## 9. What success looks like at week 12

If we hit the plan:

- Enclave 1.2.0 ships with citations on every chat response, an agentic coder
  that works on real bugs, an integration tab people can find in 30 seconds,
  and a project surface that organizes the platform's content around work.
- Brand sharpens from "local chatbot" to "local agentic workspace."
- Three of the seven brainstorm directions get partial delivery (Enclave Code
  fully; vertical packs via workflows-as-apps; prosumer-privacy via provenance
  + clearable ledger).
- Four remain explicitly deferred to 1.3+ (Teams, mobile, workflow IDE,
  prosumer full build), with the brainstorm doc as the canonical record.

If we miss by ~2 weeks: the eval-gated Enclave Code becomes 1.2.1; everything
else ships in 1.2.0 on schedule. No reason to hold the rest of the release
for the coder.

If we miss by ~4 weeks: cut B4 (context modules) and ship Enclave Code with
auto-injected context + skills only (no RAG indexes). The eval will hurt;
ship as Preview honestly.
