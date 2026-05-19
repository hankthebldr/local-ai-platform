# Enclave Code — Spec

**Status:** Draft
**Date:** 2026-05-16
**Brainstorm context:** `docs/plans/2026-05-16-product-brainstorm.md` (direction #1)
**Owners:** TBD

## TL;DR

A local agentic coder. The user runs `enclave code` in a repo, types a task in natural
language, and a planner/coder/verifier multi-agent loop edits files, runs tests, and
shows diffs — all powered by a local model on the user's hardware. No cloud, no
telemetry, no per-seat subscription.

## Goals

1. **First-credible-offline alternative** to Claude Code / Cursor / Aider for users who
   can't or won't ship code to a hosted LLM. Privacy is the wedge, not novelty.
2. **Reuse what 1.0 shipped.** ~70% of the stack already exists: `ToolExecutor`,
   `SandboxedFS`, plugin system, workflow engine, model adapters, project workspaces.
   Enclave Code is mostly *composition*, not new infrastructure.
3. **Multi-agent by default.** Single-loop tool use is a baseline; the engine's DAG
   support lets us run planner → coder → verifier as three distinct passes with
   different models, temperatures, and prompts. This is the differentiator vs. Aider.
4. **CLI-first.** Ship a usable terminal experience in M1. Editor extensions are M3.

## Non-goals (for v1)

- VS Code / JetBrains plugins (M3).
- Multi-repo / monorepo orchestration beyond a single git worktree.
- Cloud-managed sessions, team sharing, or web UI.
- Fine-tuning a custom coder model. We *select* models; we don't train them.
- Replacing Claude Code or Cursor for users who are happy with cloud LLMs.

## User-facing surface

### M1 commands

```
enclave code                              # interactive REPL in $CWD
enclave code "fix the failing auth test"  # one-shot task in $CWD
enclave code --plan-only "<task>"         # plan, don't edit
enclave code --model qwen2.5-coder:32b    # override model selection
enclave code --profile readonly           # use a restricted permission profile
enclave code resume <session-id>          # resume a checkpointed session
enclave code sessions                     # list sessions
enclave code diff                         # show diff vs HEAD for current session
```

### REPL flow

```
$ enclave code
Enclave Code · qwen2.5-coder:32b · profile: code-default · session: 7f2a91
Worktree: /tmp/enclave/sessions/7f2a91 (branch: enclave/7f2a91 from main)

> fix the failing auth test

[planner] Reading the failing test and the module under test…
  ↳ read api/tests/test_auth.py (124 lines)
  ↳ read api/services/api_key_service.py (87 lines)
  ↳ bash: pytest api/tests/test_auth.py -x  (exit 1)

[planner] Plan:
  1. The test expects `rotate_key()` to return the new key string;
     current impl returns None.
  2. Update api/services/api_key_service.py:rotate_key to return new_key.
  3. Re-run the test.

Apply plan? [Y/n/edit] y

[coder] Editing api/services/api_key_service.py…
  ↳ apply_patch (1 hunk, +1 −1)

[verifier] Running pytest api/tests/test_auth.py…
  ↳ bash: pytest -x  (exit 0, 1 passed)

✓ Task complete. Session 7f2a91 has 1 commit on enclave/7f2a91.
  Review: enclave code diff
  Merge:  enclave code merge 7f2a91   (creates a commit on your branch)
```

### Permission UX

Three tiers, modeled on Claude Code:

| Tier | Reads (`code.read`, `code.search`) | Writes (`code.write`, `code.apply_patch`) | Shell (`code.bash`) |
|------|------------------------------------|-------------------------------------------|---------------------|
| `readonly`     | auto         | denied                  | denied            |
| `code-default` | auto         | per-call confirmation   | per-call confirm  |
| `auto-accept`  | auto         | auto                    | auto (allowlist)  |

Profile is selected with `--profile`, defaults to `code-default`, and is persisted
per session. Switching mid-session re-prompts.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ cli/code.py  ←  the only new top-level user surface         │
└──────────────────┬──────────────────────────────────────────┘
                   │ calls
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ api/services/code_session.py  (NEW, ~300 LOC)               │
│ - worktree lifecycle (git worktree add/remove)              │
│ - per-session SandboxedFS rooted at the worktree            │
│ - session record (id, branch, profile, model, checkpoint)   │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌──────────────────┐  ┌──────────────────────────────────────┐
│ WorkflowEngine   │  │ ToolExecutor                         │
│ (existing)       │  │ (existing — inner loop per agent)    │
│                  │  │                                      │
│ workflows/       │  │ uses PluginService → "code" plugin   │
│ enclave-code.    │  │ uses SandboxedFS (worktree root)     │
│ yaml (NEW)       │  │                                      │
└──────────────────┘  └──────────────────────────────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────────┐
                       │ plugins/code/  (NEW)              │
                       │ - read, write, apply_patch        │
                       │ - search (ripgrep wrapper)        │
                       │ - bash (sandboxed shell)          │
                       │ - git_status, git_diff, git_commit│
                       └───────────────────────────────────┘
```

### What's new

| Component                          | Lines (est.) | Notes |
|------------------------------------|-------------|-------|
| `cli/code.py`                      | ~400        | Rich REPL, streaming tool-call rendering, approval prompts |
| `api/services/code_session.py`     | ~300        | worktree lifecycle, session persistence, checkpoint hook |
| `api/services/code_diff_renderer.py`| ~150       | unified-diff coloring, hunk-level approval |
| `plugins/code/plugin.yaml` + 7 tools | ~600       | code-specific tools below |
| `workflows/enclave-code.yaml`      | ~200        | plan / edit / verify DAG |
| `agents/coder.yaml`, `planner.yaml`, `verifier.yaml` | ~120 | agent personas |
| `api/routers/code.py`              | ~150        | REST endpoints for IDE integration (M3) |
| Tests                              | ~800        | unit + integration with a tiny Qwen model |

Total new code: ~2,700 LOC. Roughly 4–6 engineer-weeks for a credible M1.

### What's reused (no new code, just composition)

- `ToolExecutor` runs the iterative tool-calling loop per agent step. It already
  records every tool call to `ContextStore`, enforces profiles via
  `ProfileService.filter_tools`, and supports a `sandbox` kwarg passed through
  `PluginService.call_tool(..., sandbox=...)`.
- `SandboxedFS` enforces path-traversal protection and per-extension allowlists. We
  point it at the worktree root and inherit the safety properties.
- `WorkflowEngine` + `StepExecutor` give us DAG execution, Jinja2 prompt rendering,
  output parsers, quality gates, checkpoint/resume, and 6-hook lifecycle. Enclave
  Code is a workflow consumer — no engine changes needed for M1.
- `ModelAdapter` registry handles per-family prompt/param tweaks (e.g., the `qwen`
  adapter already enforces `format: json` and a temperature floor). We add a coder
  adapter for `qwen2.5-coder` / `deepseek-coder-v2` if needed.
- `ApiKeyService`, `ProjectService`, `SessionManager` for session bookkeeping.

## Agent loop

Two loops nested:

### Inner loop — one agent making tool calls

The existing `ToolExecutor.execute(...)`. Up to `max_iterations` (default 10) of
`ollama.chat → tool_calls → execute → feed results back`. Already implemented
(`api/services/tool_executor.py:41-131`). No changes.

### Outer loop — multi-agent DAG

A new workflow `workflows/enclave-code.yaml`:

```yaml
id: enclave-code
name: "Enclave Code"
version: "1.0"

defaults:
  role: coding
  retries: 1
  timeout: 300

steps:
  - id: plan
    name: "Plan"
    role: reasoning            # smaller, faster model (qwen2.5:14b)
    depends_on: []
    inputs: [seed.task, seed.worktree_summary]
    system_prompt: |
      You are a senior engineer. Read just enough of the codebase to write a
      concrete, numbered plan. Do NOT edit files. End with: "Apply this plan? Y/N"
    tools: [code.read, code.search, code.bash]   # read-only subset
    output_parser:
      format: structured
      schema: { plan: list[string], files_touched: list[string] }

  - id: edit
    name: "Edit"
    role: coding               # the workhorse (qwen2.5-coder:32b)
    depends_on: [plan]
    inputs: [plan.plan, plan.files_touched]
    system_prompt: |
      Execute the approved plan. Use code.apply_patch for edits. Do not run tests —
      the verifier handles that. If you cannot complete a step, stop and explain why.
    tools: [code.read, code.search, code.write, code.apply_patch]
    quality_gates:
      - name: "diff_not_empty"
        operator: not_empty
        field: diff

  - id: verify
    name: "Verify"
    role: reasoning
    depends_on: [edit]
    inputs: [edit.diff, plan.plan]
    system_prompt: |
      Run the project's tests for the touched files. If they fail, summarize the
      first failure and stop — do not edit. The user decides whether to re-plan.
    tools: [code.bash, code.read]    # no writes
    output_parser:
      format: structured
      schema: { passed: boolean, summary: string, failures: list[object] }
```

Why three steps and not one big agent loop:
- **Smaller context per step.** Plan reads a few files; edit reads the patch target;
  verify reads test output. A single agent loop bloats context as the conversation
  grows, which local models handle worse than frontier models.
- **Model heterogeneity.** Plan + verify can run on a small reasoning model
  (qwen2.5:14b, ~25 t/s on CPU). Edit needs the coder model (qwen2.5-coder:32b,
  ~10 t/s). This is faster than running the big model for everything.
- **Hookable.** The 6-hook lifecycle already exists; we hook `step_complete` to
  render diffs, request approval, and snapshot state for `resume`.

For users who want one-shot behavior, `--single-agent` collapses to a single
`ToolExecutor.execute` call with the full toolset.

## The "code" plugin

New plugin at `plugins/code/`. Manifest follows the existing `plugins/rag/plugin.yaml`
shape; tools opt into sandboxing via the `__sandbox` kwarg pattern already used
elsewhere.

| Tool             | Args                                       | Notes |
|------------------|--------------------------------------------|-------|
| `code.read`      | `path: str, range?: [int,int]`             | Reads through `SandboxedFS`. Range supports partial reads for long files. |
| `code.search`    | `pattern: str, glob?: str, max_results?: int` | Shells out to `rg --json` inside the worktree. |
| `code.write`     | `path: str, content: str`                  | Overwrite. Requires approval in `code-default`. |
| `code.apply_patch` | `patch: str` (unified diff)              | Atomic multi-file edit. Preferred over `write`. |
| `code.bash`      | `cmd: str, timeout?: int`                  | Runs in worktree. Allowlist enforced by profile (`pytest`, `npm test`, `cargo`, `go`, `make`, `git status`, `git diff`). |
| `code.git_status`| `()`                                       | Read-only convenience. |
| `code.git_commit`| `message: str, files?: list[str]`          | Commits to the session branch. Never touches user's branch. |

`code.bash` is the riskiest tool. M1 ships with:
- An allowlist of executable names (configurable per profile).
- Hard timeout (default 30s, max 300s).
- Network egress disabled by default — implemented via `unshare -n` on Linux,
  documented as a known gap on macOS for M1 (the platform's seatbelt profile is the
  M2 fix).
- Output truncated at 10 KB and tee'd to the session log.

## Session and worktree model

Every `enclave code` invocation creates or resumes a session:

```
~/.enclave/sessions/<session-id>/
  ├── meta.json              # model, profile, branch, started_at, parent_branch
  ├── transcript.jsonl       # message + tool-call log (the ContextStore record)
  ├── checkpoint.json        # WorkflowEngine checkpoint for resume
  └── worktree/              # git worktree, branch = enclave/<session-id>
```

`SandboxedFS` is rooted at `worktree/`. The user's main checkout is *never* touched
until they explicitly run `enclave code merge <session-id>`, which fast-forwards or
cherry-picks the session branch onto their current branch.

Implications:
- Concurrent sessions are isolated (different worktrees, different branches).
- Aborting (`Ctrl-C`) leaves the worktree intact for inspection; `enclave code rm
  <session-id>` cleans up.
- The "what did the agent actually do?" question is answered by `git log
  enclave/<id> ^main` — a familiar primitive.

## Model selection

Default model selection is role-based via the existing `model_resolver.py`:

| Role        | Default model               | Why |
|-------------|-----------------------------|-----|
| `reasoning` | `qwen2.5:14b` (Q4_K_M)      | Fast (~25 t/s), competent at planning, supports tools |
| `coding`    | `qwen2.5-coder:32b` (Q4_K_M)| Best open coder model that fits in 24 GB RAM with context |
| `fallback`  | `llama3.2:3b`               | When RAM is tight; planner-only role |

The user can override with `--model` or per-role config. The model adapter registry
already handles per-family quirks; we add a `qwen2.5-coder` adapter only if eval shows
it needs different params from generic `qwen`.

**Hard truth:** tool-calling reliability on local models is worse than Claude/GPT-4.
Mitigations:
- Constrain tool count (≤7) — `ToolExecutor` schemas stay small.
- Validate every tool call against the JSON schema before execution; reject malformed
  calls with a retry message rather than executing best-guess args.
- Prefer `code.apply_patch` over multiple `code.write` calls — single tool call,
  atomic, easier to validate.
- The verifier step catches "the model wrote something that doesn't compile."

## Failure modes & how we handle them

| Mode                              | Detection                          | Response |
|-----------------------------------|------------------------------------|----------|
| Tool args fail schema validation  | `PluginService.call_tool` raises   | Return error to model; retry same step (up to 3) |
| Model loops without progress      | Same tool call 3x in a row         | Stop loop, escalate to user |
| `code.bash` exceeds timeout       | Process killed by `code.bash`      | Truncate output, return error to model |
| Patch fails to apply              | `code.apply_patch` returns error   | Feed error back; coder retries |
| Verifier fails                    | `verify.passed == false`           | Stop. Show failure to user. Offer to re-plan. |
| Sandbox violation                 | `SandboxedFS.SandboxViolation`     | Hard fail; log; surface to user |
| Disk quota                        | `SandboxedFS.SandboxQuotaExceeded` | Hard fail; ask user to clean up |

## Evaluation

We need a credible benchmark before shipping. Proposal:

1. **SWE-bench Lite (subset, 50 tasks).** Run plan/edit/verify against
   `qwen2.5-coder:32b`. Track pass@1 and time-to-solution. Compare to Aider's
   published numbers on the same model.
2. **Internal regression suite.** 20 tasks pulled from this repo's own git history
   ("fix bug X", "add endpoint Y", "rename Z"). These exercise patterns we actually
   care about.
3. **Toolcall reliability.** % of tool calls with valid schema, % of patches that
   apply cleanly. Goal: ≥90% on both for the M1 model.

If pass@1 is < 15% on SWE-bench Lite we should ship as **"Enclave Code (Preview)"**
and be honest in marketing — local-model tool use is still rough.

## Phasing

### M1 — CLI MVP (4–6 weeks)

- `cli/code.py`, `code_session.py`, the `code` plugin, `enclave-code.yaml` workflow.
- Permission profiles: `readonly`, `code-default`, `auto-accept`.
- Worktree-based session isolation, `resume`, `merge`, `rm`.
- Evaluation harness + initial SWE-bench Lite numbers.
- Documentation: README section, `docs/enclave-code.md` quickstart.

**Ship criteria:** can fix a real bug in this repo end-to-end without supervision in
`auto-accept` mode on `qwen2.5-coder:32b`.

### M2 — Polish (4 weeks)

- macOS seatbelt profile for `code.bash` network isolation.
- Streaming the model's reasoning during the inner loop (currently we only show
  completed tool calls).
- Hunk-level approval for diffs, not just file-level.
- Cost meter (tokens, time, $-equivalent vs. GPT-4 / Claude).
- Workflow templates: `--workflow refactor`, `--workflow test-only`,
  `--workflow review-pr` (consumes a GitHub PR diff).

### M3 — Editor integration (8 weeks)

- VS Code extension. Talks to `api/routers/code.py` (the existing API process).
- Inline diff approval in the editor.
- Continue-from-cursor: select code, "Enclave Code: explain / refactor / test".
- JetBrains plugin: nice to have, owned by community contribution if possible.

## Open questions

1. **Approval UX in the CLI.** Per-call confirmation is annoying. Should
   `code-default` auto-accept the first read/search/git-status tool calls and only
   prompt on writes? Probably yes — needs spec.
2. **MCP exposure.** Should `code.*` tools also be exposed via MCP so a non-Enclave
   client (Claude Desktop, Cursor with MCP) can use them? Strong yes for distribution,
   but it inverts the "Enclave is the agent" pitch. Likely a v2 decision.
3. **Streaming model output during tool calls.** Ollama supports streaming, but
   `ToolExecutor` currently consumes the response synchronously. Refactor is small
   but touches the inner loop.
4. **Long-context strategy.** `qwen2.5-coder:32b` supports 128k context but eats RAM
   linearly. Should we proactively summarize the conversation when context > 32k, or
   rely on the model? Recommend: summarize, with a feature flag to disable.
5. **License posture.** Is Enclave Code source-available like the rest of the
   platform, or do we gate it behind the same evaluation license? Either is defensible
   but we should decide before launch.
6. **Naming.** "Enclave Code" mirrors "Claude Code" intentionally. Acceptable, or
   does legal/positioning want differentiation? Alternatives: `enclave dev`,
   `enclave do`, `enclave work`.

## Decisions needed before M1 kickoff

- [ ] Confirm `qwen2.5-coder:32b` as the default coder model. (Alternative:
      `deepseek-coder-v2:16b` — smaller, fits 16 GB RAM, but weaker on agentic
      benchmarks in our internal trials.)
- [ ] Approve the worktree-per-session model vs. in-place editing with stash.
- [ ] Approve the three-step DAG vs. a single big agent loop as the M1 default.
- [ ] Decide on license posture (open vs. gated).
- [ ] Name: "Enclave Code" or alternative.
