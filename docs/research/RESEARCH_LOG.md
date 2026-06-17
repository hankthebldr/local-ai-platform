# Research workflow run log

Running list of deep-research workflow runs: status, where each stopped, and what's still outstanding. Update this file whenever a research workflow is launched, stopped, or resumed.

## 2026-06-12 — Inference engine landscape (1.5.x pluggable engines)

- **Report:** [2026-06-12-inference-engine-landscape.md](./2026-06-12-inference-engine-landscape.md)
- **Run ID:** `wf_2d8a96db-968` · original task `wmrlijzd3` · resume task `wtysd9s1m`
- **Status:** STOPPED (operator call, token conservation). Original run completed Scope/Search/Fetch/Extract; died at session limit mid-Verify (~8 of 25 claims got 0 votes) and before Synthesize. Resume was launched 2026-06-12 then stopped before spending.
- **Where it stopped:** 5 angles → 21 sources → 96 claims extracted → 25 sent to verify → **7 confirmed, 11 genuinely refuted (0-3), 7 killed on abstain (verifiers never ran)**. Synthesis never ran — report above was synthesized by the main loop from the confirmed claims.
- **Outstanding (unverified-claim backlog for a future targeted run):**
  - vLLM default ~90% VRAM pre-allocation → multi-model swap fit on 24GB GPU
  - vLLM GGUF path status (experimental vs production)
  - TGI archived/maintenance-mode March 2026
  - RTX 3090 single-user + 8/16-user concurrency inversion benchmark table
  - M4 Pro Q4_K_M throughput figures
  - vLLM macOS support status (source-build only, no Metal?)
- **Resume note:** journal resume (`resumeFromRunId`) is same-session only; session `5bc88359-b3c3-40da-83be-9c3d341d6dca`. Script: `~/.claude/projects/-home-henry-Github-local-ai-platform/5bc88359-b3c3-40da-83be-9c3d341d6dca/workflows/scripts/deep-research-wf_2d8a96db-968.js`. Raw output (ephemeral, /tmp): `tasks/wmrlijzd3.output`. From a new session, cheaper to run a small targeted verify pass on the backlog above than to re-run the full harness.

## 2026-06-12 — Chat-led workflow UX prior art (feat/chat-led-composer)

- **Report:** [2026-06-12-chat-led-workflow-ux-prior-art.md](./2026-06-12-chat-led-workflow-ux-prior-art.md)
- **Run ID:** `wf_74fb0e62-c58` · original task `wvei1a8v3` · resume task `wdafu0b86`
- **Status:** STOPPED (operator call, token conservation). Same shape as above: completed through Extract, died mid-Verify (9 of 25 claims got 0 votes) and before Synthesize. Resume launched then stopped before spending.
- **Where it stopped:** 5 angles → 21 sources → 103 claims extracted → 25 sent to verify → **16 confirmed (all 3-0), 9 killed on abstain (verifiers never ran — none genuinely refuted)**. Synthesis never ran — report above was synthesized by the main loop from the confirmed claims.
- **Outstanding (unverified-claim backlog for a future targeted run):**
  - n8n AI Workflow Builder: canvas-state→chat round-trip (full workflow + mock execution data sent to LLM each turn); "Execute and refine" loop
  - Cursor Plan Mode: hybrid explicit/inferred promotion; Markdown plan artifact
  - PromptChainer (arXiv 2203.06566): inter-step data transformation + multi-granularity debugging as core authoring pain points
  - Low-code LLM: whether canvas→executor round-trip is one-directional/lossy
  - Never reached verification at all: Zapier Copilot/Central, Lindy, Gumloop, Dust, Relevance AI, Voiceflow, LangGraph Studio (claims extracted but ranked below top-25 cut)
- **Resume note:** same-session-only journal, session `5bc88359-b3c3-40da-83be-9c3d341d6dca`. Script: `.../workflows/scripts/deep-research-wf_74fb0e62-c58.js`. Raw output (ephemeral, /tmp): `tasks/wvei1a8v3.output`.

## Conventions

- One section per research question; newest first within a dated batch.
- Record: report path, run/task IDs, status (RUNNING / COMPLETED / STOPPED / DEGRADED), pipeline stage reached, confirmed/refuted/abstained split, and the unverified-claim backlog.
- "Killed on abstain" ≠ refuted: those claims were never checked and stay on the backlog.
