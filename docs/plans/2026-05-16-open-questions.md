# Open Questions — Consolidated

**Date:** 2026-05-16
**Reads from:** all 12 docs in the `2026-05-16-*` series

Every open decision across today's planning workspace, framed as a real
question with concrete answer choices. My recommendation is shown but is
separable from the question — you can pick any option.

How to read each row:
- **Q**: the question
- **Options**: the actual choices you can pick from
- **Rec**: my recommendation (if any) and one-line reason
- **Default**: what gets shipped if you say nothing

---

## Blocks sprint 1 kickoff

| # | Question | Options |
|---|----------|---------|
| **B1** | How many engineering FTEs work this roadmap, and what's the backend / frontend split? | (free text — answer in FTEs) |
|   | **Rec:** 1.5 BE + 1 FE + 0.5 design/PM. **Default if unanswered:** 1 BE + 1 FE; B4 (Enclave Code context modules) drops to 1.3. |
| **B2** | What SWE-bench Lite pass@1 is the minimum bar for Enclave Code 1.2.0 GA (vs. shipping as Preview)? | A) 15%   B) 20%   C) 25%   D) 30%   E) other (specify) |
|   | **Rec:** C (25%) — Aider's published numbers on similar models are 20–30%. **Default:** D (30%); ship as Preview if missed. |
| **B3** | What license does Enclave Code ship under? | A) Same source-available as the rest of the platform   B) Gated eval license   C) A different OSS license (specify) |
|   | **Rec:** A — consistency with the rest of the platform. **Default:** A. |
| **B4** | What is the user-facing name? | A) Enclave Code   B) enclave dev   C) enclave do   D) enclave work   E) other (specify) |
|   | **Rec:** A — mirroring "Claude Code" helps positioning. **Default:** A. |
| **B5** | Which model is the default for `--role coding`? | A) `qwen2.5-coder:32b`   B) `deepseek-coder-v2:16b`   C) other (specify) |
|   | **Rec:** A; fall back to B during sprint 5 eval if tool-call validity <80%. **Default:** A. |
| **B6** | Default M1 execution mode? | A) Three-step plan/edit/verify DAG   B) Single agent loop with the full toolset |
|   | **Rec:** A — smaller per-step context + model heterogeneity. **Default:** A. |
| **B7** | How does Enclave Code isolate edits from the user's checkout? | A) Worktree per session on `enclave/<id>` branch   B) In-place edits behind a `git stash` boundary |
|   | **Rec:** A — reviewable via `git log enclave/<id> ^main`, never touches the user's branch. **Default:** A. |

**Time to close all 7: ~15 minutes.** B1, B2, B3 are genuinely open; B4–B7
have firm recommendations and are sanity checks.

---

## Strategic — affects 1.3+ positioning

| # | Question | Options |
|---|----------|---------|
| **S1** | How do we discover who the 1.0 user is before committing to a 1.3 direction? | A) Opt-in dashboard survey banner in 1.1.1   B) Interview ~10 known users   C) Skip — commit to a 1.3 direction on instinct   D) Defer the 1.3 commit until we have known users to interview |
|   | **Rec:** A. Cheap (1 day), zero-telemetry, sample bias acknowledged. **Default:** D. |
| **S2** | What is the intended business model going into 1.3? | A) Sustainable indie OSS (sponsorships + support contracts)   B) Venture-backed SaaS + self-hosted   C) Hardware appliance (sell pre-loaded BD790i / MS-01)   D) Vertical packs as paid add-ons (direction #2)   E) Undecided / multiple |
|   | **Rec:** none — this is your call. The pick determines which brainstorm direction we invest in for 1.3. **Default:** E (defer); 1.2 ships independent of this. |
| **S3** | Commit to building the Personal Knowledge pack (Apple Notes + Email/IMAP + Calendar + browser bookmarks) for 1.3? | A) Yes — commit now   B) Yes — but only if S1 confirms a knowledge-worker user base   C) No — defer to 1.4+   D) No — never build it |
|   | **Rec:** B. The bet is strong if confirmed, premature otherwise. **Default:** C. |
| **S4** | Publish our own MCP server in 1.3 so Claude Desktop / Cursor / etc. can consume Enclave skills + RAG? | A) Yes, in 1.3   B) Yes, in 1.4   C) No |
|   | **Rec:** A — small (one router), big distribution upside, doesn't conflict with our agent pitch. **Default:** B. |
| **S5** | Add explicit Apple Intelligence comparison to marketing copy by 1.3 GA? | A) Yes — direct comparison table on the website   B) Yes — implicit positioning only ("always local, your data stays here")   C) No — ignore Apple Intelligence |
|   | **Rec:** B. Direct comparisons age fast and invite Apple's lawyers. **Default:** B. |
| **S6** | How loud is the 1.2.0 GA launch? | A) Coordinated: blog post + demo video + HN post + social   B) Medium: blog post only   C) Quiet ship: release notes + nightly graduation |
|   | **Rec:** A for 1.2.0 (Enclave Code is the headline); B for 1.1.0 + 1.1.1. **Default:** B. |
| **S7** | Ship a "Hospital" project template (air-gap by default, all network MCPs disabled) in 1.3? | A) Yes — speculative   B) Only if a healthcare design partner materializes   C) No |
|   | **Rec:** B. **Default:** B. |

---

## Technical — engineering implementation

| # | Question | Options |
|---|----------|---------|
| **T1** | In `code-default` profile, which tools require per-call approval? | A) Writes + bash only (`code.write`, `code.apply_patch`, `code.bash`)   B) All tools including reads   C) Configurable per tool, no default |
|   | **Rec:** A. Reads/searches don't carry write risk. **Default:** A. |
| **T2** | When the coder's conversation exceeds 32k tokens, what happens? | A) Proactive summarization, with a disable flag   B) Pass-through to the model up to its context limit   C) Hard cap at 32k; refuse longer turns |
|   | **Rec:** A. Local models degrade on long context worse than frontier. **Default:** A. |
| **T3** | Stream the user-visible response in Enclave Code? | A) M1 (1.2)   B) M2 (1.3+) |
|   | **Rec:** B — refactor touches the `ToolExecutor` inner loop; not blocking. **Default:** B. |
| **T4** | Expose `code.*` tools via MCP so non-Enclave clients can use them? | A) Yes in 1.2   B) Yes in 1.3 (pair with S4)   C) Never |
|   | **Rec:** B. **Default:** B. |
| **T5** | When a workflow runs as a sub-workflow of another, where do its provenance edges point? | A) M1: keep flat to its own response_id (current); M2 add parent_response_id   B) M1: add parent_response_id parameter to the engine   C) Never — workflows always run flat |
|   | **Rec:** A. Verify sub-run support exists in `workflow_engine.py` first. **Default:** A. |
| **T6** | Where does the `source_id` → `{label, link, preview}` resolver live? | A) Dict in `api/routers/provenance.py`   B) Method on each source service (`document_service`, `skills`, etc.)   C) New `ResolverService` |
|   | **Rec:** A. Services stay unaware of provenance; router owns the read path. **Default:** A. |
| **T7** | Will 1.2.0 ship a signed/notarized macOS DMG? | A) Yes — signed + notarized   B) Yes — signed only   C) No — continue `xattr` workaround |
|   | **Rec:** A. 1.0 papercut that's lived too long. **Default:** A. |
| **T8** | Run a 1-day eval pass on Whisper variants + Piper voices before 1.3 voice-mode scoping? | A) Yes — schedule for the 1.3 planning window   B) No — accept whisper.cpp base + a default Piper voice without eval   C) Skip voice mode in 1.3 entirely |
|   | **Rec:** A. **Default:** B. |

---

## UX — visual / interaction

| # | Question | Options |
|---|----------|---------|
| **U1** | Where does Integrate live? | A) Admin modal in 1.1.0 → top-level tab in 1.2.0 if engagement warrants   B) Top-level tab from day 1   C) Admin modal only, never a tab |
|   | **Rec:** A. Cheaper to ship, A/B-able. **Default:** A. |
| **U2** | Where does the Skills surface live? | A) Right rail in Skill Lab (contextual)   B) Dedicated Skills tab in BUILD group   C) Admin Skills modal only (no first-class surface) |
|   | **Rec:** A. Cheaper, doesn't crowd the tab bar. **Default:** A. |
| **U3** | Default state of the conversation sidebar on first visit? | A) Collapsed, click chevron to expand   B) Open by default with prior threads visible   C) Hidden entirely until user has 2+ conversations |
|   | **Rec:** A. New users shouldn't face empty history. **Default:** A. |
| **U4** | Default cost-comparison model in response receipts? | A) GPT-4 hardcoded in 1.2.0; user-pickable in 1.2.x   B) User-pickable from day 1 (GPT-4 / GPT-4o / Claude Sonnet / off)   C) Off by default; opt-in via Privacy panel |
|   | **Rec:** A. **Default:** A. |
| **U5** | Show active project in the global breadcrumb across all tabs (not just Composer)? | A) Yes — promote to breadcrumb middle crumb   B) No — keep in Composer project bar only   C) Both — breadcrumb + Composer bar |
|   | **Rec:** A. Surfaces active context everywhere. **Default:** B (no change). |
| **U6** | How visible are `enclave doctor` results in the dashboard? | A) Admin menu item only   B) Admin menu item + header status pip when critical issues exist   C) Always-visible status row at top of dashboard |
|   | **Rec:** B. Pip raises visibility only when needed. **Default:** A. |

---

## Decisions already settled (tracking only — don't re-litigate)

| # | What | Source |
|---|------|--------|
| Z1 | Three permission profiles for Enclave Code: readonly / code-default / auto-accept | enclave-code-spec |
| Z2 | Skills load with `triggers: ["*"]` for always-on (loader extension) | enclave-code-buildout |
| Z3 | ProvenanceEdge stays flat — `response_id` is always the final user-visible response; `parent_step_id` lives in `metadata` | provenance-decisions |
| Z4 | Provenance store: SQLite. JSONL export deferred to a CLI subcommand in M2 | provenance-decisions |
| Z5 | 90-day default retention for provenance ledger | provenance-decisions |
| Z6 | Setup wizard checkbox copy: "Show me what shaped each answer (local-only). Recommended." | provenance-decisions |
| Z7 | Citation rail rollout: M1.0 invisible, M1.1 behind flag, then default on | provenance-decisions |
| Z8 | Inventory shell: one component parametrized over content kind (extends existing `.inv-card`/`.wfi-card` pattern) | content-lifecycle |
| Z9 | Per-project scoping rolls out additively (default global, opt into project) | content-lifecycle |
| Z10 | Defer dashboard SPA refactor of the 9,457-line `index.html` to 1.3+ | ux-stories |
| Z11 | Defer Teams / multi-user / mobile to 1.3+ | brainstorm |
| Z12 | A11y for citation rail: minimum bar — single `aria-expanded` assertion in tests | provenance-decisions |
| Z13 | `enclave provenance export` CLI subcommand: defer to M2 | provenance-decisions |
| Z14 | Response IDs: OpenAI-compat `chatcmpl-...` across both dashboard chat and API | provenance-decisions |
| Z15 | Migrations runner: 50-LOC generic helper, reusable across SQLite-backed services | provenance-decisions |

---

## Operational reminders (not questions — things not to forget)

| # | Item | When |
|---|------|------|
| **O1** | Audit `index.html` chat dock — confirm it calls `/v1/chat/completions` and not a parallel path | Sprint 1 |
| **O2** | Add `metadata.user_facing` + `metadata.summary` to the 3 workflows surfaced as Quick Actions | Sprint 5 |
| **O3** | Verify Qwen adapter regex `qwen` matches `qwen2.5-coder:32b` correctly | Sprint 3 |
| **O4** | Investigate the pre-existing macOS DMG smoke build failure on master | Before sprint 6 release prep |
| **O5** | Address 88 dependabot vulnerabilities on default branch (3 critical, 15 high) | 1.2.0 release hygiene |

---

## Suggested 15-minute conversation

Walk these in order:

1. **B1** team shape — 1 min — drives everything else
2. **B3 / B4 / S6** license + name + launch loudness — 4 min — strategic cluster
3. **B2 / T7** eval bar + DMG signing — 3 min — release-quality cluster
4. **S2** business model — 5 min — biggest strategic question; "still thinking" is a valid answer
5. **U1–U6** UX decisions — 2 min — most are sanity checks

Everything else has a firm recommendation; open them only if you disagree
with the rec.

---

## Where each row comes from

| Doc | Carries |
|-----|---------|
| `2026-05-16-product-brainstorm.md` | S1, S2 + the 7 strategic directions |
| `2026-05-16-enclave-code-spec.md` | B3, B4, B5, B6, B7, T1, T2, T3, T4 |
| `2026-05-16-enclave-code-additions.md` | (model + MCP catalog choices, mostly settled) |
| `2026-05-16-enclave-code-context-skills-buildout.md` | Z2 + skill content |
| `2026-05-16-ux-stories.md` | UX moments framing (U1–U6 derive from here) |
| `2026-05-16-content-lifecycle-review.md` | Z8, Z9 |
| `2026-05-16-provenance-edge-spec.md` | precursor to decisions doc |
| `2026-05-16-provenance-edge-decisions.md` | T5, T6 + Z3–Z7, Z12–Z15 |
| `2026-05-16-roadmap-spec.md` | consolidated scope |
| `2026-05-16-implementation-plan.md` | B1, B2, S6, T7 |
| `2026-05-16-ui-flows.md` | U1–U6 |
| `2026-05-16-adjacent-capabilities.md` | S3, S4, S5, S7, T8 |
