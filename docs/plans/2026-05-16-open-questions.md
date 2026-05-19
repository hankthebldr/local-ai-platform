# Open Questions — Consolidated

**Date:** 2026-05-16
**Reads from:** all 12 docs in the `2026-05-16-*` series

Every open question and pending decision across today's planning workspace, in
one place. Grouped by who needs to answer and whether it blocks sprint 1
kickoff. Recommendations pinned where I had one.

## Blocks sprint 1 kickoff (decide first)

| # | Question | Source | Recommendation |
|---|----------|--------|----------------|
| **B1** | Team shape: 1.5 backend + 1 frontend + 0.5 design/PM? If lower, drop B4 (Enclave Code context modules) to 1.3. | implementation-plan §8 | Confirm or revise; everything else assumes this |
| **B2** | Eval gate for Enclave Code release: ≥30% pass@1 full / ≥15% Preview? | implementation-plan §8 | These match Aider's published numbers on similar models. Confirm or loosen. |
| **B3** | License posture for Enclave Code (and platform more broadly): source-available like the rest, or gated behind eval license? | enclave-code-spec, implementation-plan §8 | Source-available for consistency unless commercial strategy demands gating |
| **B4** | "Enclave Code" naming — keep, or differentiate from "Claude Code"? | enclave-code-spec, implementation-plan §8 | Keep "Enclave Code"; mirroring Claude Code is intentional and helps positioning |
| **B5** | Default coder model: `qwen2.5-coder:32b` confirmed? | enclave-code-spec | Yes, with `deepseek-coder-v2:16b` as the fallback if eval shows tool-call reliability issues |
| **B6** | Three-step DAG (plan/edit/verify) vs single-agent loop as the M1 default? | enclave-code-spec | Three-step. Justified in the spec by context size + model heterogeneity. |
| **B7** | Worktree-per-session vs in-place editing with stash? | enclave-code-spec | Worktree. Already pinned in the decision log; flagged here so it's not silently undone. |

**Time to close all 7: ~15-minute conversation.** Most have firm
recommendations. The genuinely open ones are B1 (resourcing reality), B2 (eval
bar appetite), B3 (license).

## Strategic / positioning (1.2+ scope)

| # | Question | Source | Recommendation |
|---|----------|--------|----------------|
| **S1** | Who is the 1.0 user actually? We have no telemetry by design. | brainstorm | Add a one-time, opt-in survey banner to the dashboard before committing to a 1.3 direction. Or interview ~10 known users. |
| **S2** | Business model: venture-backed product / sustainable indie OSS / hardware appliance play (sell the BD790i pre-loaded)? | brainstorm | Affects which brainstorm direction (#2 vertical packs vs #3 Teams vs #6 prosumer) becomes the 1.3 strategic bet. Worth a real conversation before sprint 4. |
| **S3** | "Personal Knowledge" pack as the 1.3 commit (Apple Notes + Email + Calendar + bookmarks, one-toggle bundle)? | adjacent | Strong yes — frames Enclave as "your personal data stays personal," sharpens vs. Apple Intelligence and Microsoft Copilot. |
| **S4** | MCP-host posture: should Enclave publish its *own* MCP server so Claude Desktop, Cursor, etc. can use our skills/RAG? | adjacent | Slot at 1.3 with one new router. Strategic upside (distribution); doesn't conflict with the "Enclave is the agent" pitch because both can be true. |
| **S5** | Where Apple Intelligence sits in our marketing positioning? | adjacent | Address directly by 1.3. We win on privacy (always local vs. Apple's hybrid) and capability breadth. Marketing copy needs a direct comparison. |
| **S6** | Release marketing weight for 1.2: coordinated launch (blog + demo video + HN) or quiet ship? | implementation-plan §8 | Affects sprint 6 day allocation. My read: quiet ship 1.1.0 + 1.1.1, coordinated launch for 1.2.0 when Enclave Code is the headline. |
| **S7** | Air-gap mode as default in some project templates (e.g., a "Hospital" template that disables all network MCPs)? | adjacent | Worth checking with any healthcare-adjacent design partners — defer until 1.3 unless one materializes |

## Technical implementation (recommendations pending sign-off)

These are open but have firm recommendations. Sign off to close.

| # | Question | Source | Recommendation |
|---|----------|--------|----------------|
| **T1** | Approval UX in Enclave Code CLI — should `code-default` auto-accept read/search/git-status and only prompt on writes? | enclave-code-spec | Yes. Per-call confirmation on read tools is annoying; the actual risk is writes. |
| **T2** | Long-context strategy for the coder when context > 32k: proactive summarization or rely on the model? | enclave-code-spec | Proactive summarize, with a flag to disable. Local models degrade with long context worse than frontier models. |
| **T3** | Streaming model output during tool calls (currently `ToolExecutor` consumes synchronously)? | enclave-code-spec | M2 work. Streams the *user-visible* response when it's the final turn; tool-call inner loop stays synchronous to keep the engine simple. |
| **T4** | Expose `code.*` tools via MCP so non-Enclave clients (Claude Desktop, Cursor) can use them? | enclave-code-spec | Strong yes for distribution, but defer to v2 — inverts the "Enclave is the agent" pitch in v1 and complicates the security model. Pair with S4. |
| **T5** | Workflow sub-runs nesting in provenance — if workflow A triggers workflow B, B's edges currently point at B's response_id. | provenance-decisions | M2. Add `parent_response_id` parameter when running as a sub-workflow. Verify `workflow_engine.py` first to know if compose-mode even exists. |
| **T6** | Resolver registry shape — `source_id` → `{label, link, preview}` as a dict in the router, or methods on each service? | provenance-decisions | Dict in the router. Services stay unaware of provenance; the router owns the read path. |
| **T7** | DMG signing for 1.2 — sign/notarize or continue `xattr` workaround? | implementation-plan §8 | Sign/notarize for 1.2.0 GA. The `xattr` workaround is a 1.0 papercut that's lived too long. |
| **T8** | Voice model eval for 1.3 — which Whisper variants + Piper voices are credible CPU-only? | adjacent | Run a 1-day eval pass before 1.3 scoping. Whisper base.en + Piper amy-medium are the starting candidates. |

## UX decisions (visual / interaction)

| # | Question | Source | Recommendation |
|---|----------|--------|----------------|
| **U1** | Integrate as admin modal (1.1.0) or top-level tab (1.2.0)? | ui-flows §20 | Modal first; promote to tab in 1.2.0 if engagement warrants. Cheaper to ship and A/B-able. |
| **U2** | Skills surface: right rail in Skill Lab (recommended) or dedicated Skills tab? | ui-flows §20 | Right rail. Contextual to research/skill-authoring; cheaper; doesn't crowd the tab bar. |
| **U3** | Conversation sidebar default state on first visit — open or collapsed? | ui-flows §20 | Collapsed by default with a click-to-expand chevron. New users shouldn't be confronted with empty history. |
| **U4** | Cost comparison default — GPT-4 hardcoded or user-pickable from day 1? | ui-flows §20 | GPT-4 hardcoded in 1.2; user-pickable (GPT-4o / Claude Sonnet / off) in 1.2.x. Privacy panel toggle ships day 1. |
| **U5** | Active project in the breadcrumb's middle crumb across all tabs, vs. only inside the Composer's project bar? | ui-flows §20 | Promote to breadcrumb. Surfaces the active context everywhere, not just in Composer. |
| **U6** | `enclave doctor` as admin menu item only, or also a status pip in the global header (red dot = critical issue)? | ui-flows §20 | Both. Admin menu item stays for "I want to look at this now"; header pip raises visibility for the cases where the user needs to know. |

## Settled — tracking only

Already decided in earlier docs; listed so they don't get re-litigated.

| # | Decision (settled) | Source |
|---|--------------------|--------|
| Z1 | Three permission profiles for Enclave Code: readonly / code-default / auto-accept | enclave-code-spec |
| Z2 | Skills loaded with `triggers: ["*"]` for always-on (loader extension) | enclave-code-buildout |
| Z3 | ProvenanceEdge stays flat (`response_id` always points to user-visible response); `parent_step_id` lives in `metadata` for future recursive views | provenance-decisions |
| Z4 | SQLite for provenance store; JSONL export deferred to a CLI subcommand in M2 | provenance-decisions |
| Z5 | 90-day default retention for provenance | provenance-decisions |
| Z6 | Setup wizard checkbox copy: "Show me what shaped each answer (local-only). Recommended." | provenance-decisions |
| Z7 | Two-stage feature flag rollout for citation rail (M1.0 invisible, M1.1 dogfood flag, then default on) | provenance-decisions |
| Z8 | Inventory shell is one component parametrized over content kind | content-lifecycle |
| Z9 | Per-project scoping rolls out additively (default global, opt into project) | content-lifecycle |
| Z10 | Defer dashboard SPA refactor of the 9,457-line `index.html` | ux-stories, implementation-plan |
| Z11 | Defer Teams / multi-user / mobile to 1.3+ | brainstorm |
| Z12 | A11y for citation rail: minimal — single `aria-expanded` assertion in tests | provenance-decisions |
| Z13 | `enclave provenance export` CLI subcommand: defer to M2 | provenance-decisions |
| Z14 | Default response_id format: OpenAI-compat `chatcmpl-...` across both dashboard chat and OpenAI-compat API | provenance-decisions |
| Z15 | Migrations runner: 50-LOC generic helper in `api/services/migrations/runner.py`, reusable across services | provenance-decisions |

## Operational tracking (not decisions, just things not to forget)

| # | Item | When it matters |
|---|------|-----------------|
| **O1** | Dashboard chat path audit — confirm `index.html` chat dock calls `/v1/chat/completions` and not a parallel endpoint | Sprint 1 (provenance plumbing) |
| **O2** | Workflow YAML metadata pass — add `metadata.user_facing` + `metadata.summary` to the 3 workflows surfaced as Quick Actions | Sprint 5 |
| **O3** | Verify Qwen adapter applies to `qwen2.5-coder:32b` (the regex `qwen` matches it today) | Sprint 3 (Enclave Code start) |
| **O4** | DMG smoke build is failing on master — verify pre-existing and unrelated to docs-only PRs | Before sprint 6 release prep |
| **O5** | The 88 dependabot vulnerabilities on the default branch (3 critical, 15 high) | Address as part of 1.2.0 release hygiene |

## Suggested 15-minute conversation agenda

If we can get one short meeting before sprint 1 kickoff, work through these in
order:

1. **B1** team shape — 1 minute. Tell me what's real, I'll adjust the plan.
2. **B3 + B4 + S6** license + name + marketing — 4 minutes. Cluster of strategic
   product decisions that affect copy and positioning across multiple sprints.
3. **B2 + T7** eval bar + DMG signing — 3 minutes. Release-quality decisions.
4. **S2** business model — 5 minutes. The biggest strategic question; affects
   what we build in 1.3. Honestly OK if this stays "thinking about it."
5. **U1–U6** — 2 minutes. Most have firm recommendations; confirm or veto.

Everything else (T1–T8, S1, S3–S5, S7) has a firm recommendation pinned and
can move forward in the background of the conversation. Open them only if
you disagree with the recommendation.

## Where to read more on each

| Doc | Key decisions it carries |
|-----|--------------------------|
| `2026-05-16-product-brainstorm.md` | S1, S2 + the 7 strategic directions context |
| `2026-05-16-enclave-code-spec.md` | B3–B7, T1–T4 |
| `2026-05-16-enclave-code-additions.md` | (model + MCP catalog choices) |
| `2026-05-16-enclave-code-context-skills-buildout.md` | Z2 + skill content |
| `2026-05-16-ux-stories.md` | (UX moments framing for U1–U6) |
| `2026-05-16-content-lifecycle-review.md` | Z8, Z9 |
| `2026-05-16-provenance-edge-spec.md` | (precursor to decisions doc) |
| `2026-05-16-provenance-edge-decisions.md` | T5, T6 + Z3–Z7, Z12–Z15 |
| `2026-05-16-roadmap-spec.md` | (consolidated scope) |
| `2026-05-16-implementation-plan.md` | B1–B2, S6, T7 |
| `2026-05-16-ui-flows.md` | U1–U6 |
| `2026-05-16-adjacent-capabilities.md` | S3–S5, S7, T8 |
