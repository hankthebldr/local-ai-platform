# Autonomous Orchestration & Infinity Runs — Design (Subsystem C)

**Status:** Design complete (two grounded multi-agent passes + adversarial critique = CONDITIONAL GO; all open mechanisms resolved) · **Date:** 2026-06-29
**Companion to:** [composer-dominant workspace design](2026-06-28-composer-dominant-workspace-design.md) (A+B). This is **C** — the backend engine + the flagship autonomous-research application. B's Runs view surfaces C.
**Grounding:** multi-agent design+critique workflow over the real codebase (run `wf_bab02ddd-d5f`), verified against git.

## Headline finding: C is ~85% already built

The autonomous "infinity run" engine the operator described **already exists on `master`** as merged workflow step kinds. C is therefore **wiring + a few surgical fixes**, not engine-building.

| Capability the operator asked for | Already exists | Where |
|---|---|---|
| Unbounded loop with guardrails | `kind:ralph` — repeats a `body` until `goal_gate` / `halt_file` / `max_iterations` / `max_wall_seconds` (default 28800 = 8h) / `max_total_tokens` / `max_consecutive_failures` | `api/services/engine_executors/ralph.py` (246 ln); `RalphHalt`/`RalphSpec` `api/models/workflow_models.py:265` |
| Parallel multi-agent fan-out | `kind:parallel` — ThreadPoolExecutor, `max_concurrency`, 4 modes (`multi_model_concurrent`, `single_model_concurrent`, `single_model_pseudo_parallel`, `sharded`), `fail_fast`/`continue_on_partial` | `engine_executors/parallel.py` (532 ln) |
| Durable RECORD | `kind:consolidate` + `MemoryStore.append_with_dedup` | `engine_executors/consolidate.py`, `memory_store.py` |
| Checkpoint / resume | `_checkpoint` after every step (atomic tmp+rename); `_reap_orphan_runs` at boot; resume by journaled-iteration count | `workflow_engine.py` |
| Operator stop | `halt_file` (brake) + `request_cancel`/`_should_cancel`; HITL `pending_gate` | `ralph.py`, `workflow_engine.py` |

**Sequencing is clear:** these landed weeks ago (commits #105 `consolidate`, #106 `ralph`, #108 `sharded`, #110 `prefix-lock`, #114 engine split; `workflow_models.py` last #165, 2026-06-05). **No phase-gate collision** — C's engine edits are safe on `master` now. (The critic's "wait for #94/#96/#98" was reasoning from CLAUDE.md's stale roadmap text.)

## What an "infinity run" is

A normal **background workflow run** (`workflows.py:run_workflow_async`) whose root step is `kind:ralph`, body =

```
identify → [parallel research fan-out] → enrich → record(vault) → index
```

looped until the novelty gate goes dry or a guardrail trips. **No new run infrastructure, no `/infinity` endpoint** — it's a YAML template (`workflows/autonomous-research.yaml`) run through the existing async path.

## Required changes (small, surgical)

### Data model — extend `RalphHalt` / `RalphSpec` (`workflow_models.py:265`)
- `max_consecutive_dry: int = 2` — pause/stop after N iterations with **zero novel findings** (loop-until-dry).
- `max_vault_notes_per_run: int` — **hard cap** on notes written (a misconfig must not flood the live vault; novelty is best-effort).
- A pinned **single model for the whole body** (avoid per-iteration cold-load thrash).
- **Dropped (over-engineering, per critique):** a new `NoveltyLedger` service. `MemoryStore.append_with_dedup` already does on-disk dedup; "dry" = the record step wrote **zero novel blocks**. Track `dry_streak` as a loop-local int, mirroring the existing `consecutive_failures` pattern in `ralph.py`.

### Must-fix bugs/risks the critique caught (grounded, non-optional)
1. **Vault-write path is broken as first proposed → RESOLVED: filesystem-direct.** `ConsolidateSpec.target` is `Literal['playbook','semantic','episodic']` and `memory_store._safe_name()` strips `/`, so consolidate **cannot** target `_research/_projects`. **Decision (gap-fill verified): a new `api/services/vault_writer.py`** writing atomic (tmp+`os.replace`) YAML-frontmatter notes under `ENCLAVE_VAULT_DIR` (dev default `/Users/henry/hr-vault-main-pa`; the vault has `_research/`+`_projects/`). Slug **only the filename**, never the subdir; validate the full target with `Path(target).resolve().is_relative_to(vault_root)` and whitelist the top-level subdir to `{_research,_projects}`; **fail loud** if `ENCLAVE_VAULT_DIR` is unset/absent (never silently fall back to `./data`). Invoked as a new `kind:record` body step (consolidate is LLM-distill-then-store; record is store-already-produced-research). **MCP path rejected**: vault-os isn't in the app's MCP registry (the app reads only its own `~/.enclave/mcp/servers.json`, never Claude's), and `mcp-obsidian` needs the Obsidian desktop app + REST plugin running — unacceptable for an 8h headless run. After write, index via `DocumentService.upload` **with doc_id-per-vault-path tracking** (delete+upload on re-record) — `upload` mints a fresh doc_id each call, so naive re-record duplicates Chroma entries and poisons the RAG read-back loop.
2. **Cancel bug.** `ralph.py`'s inner `while True` never calls `engine._should_cancel`, so operator `/cancel` won't land until the entire (up to 8h) ralph step returns. `halt_file` works mid-loop; cancel does not. **Add a `_should_cancel` check to ralph's halt block.**
3. **Orphan reaper vs long-runners.** `_reap_orphan_runs` marks runs FAILED after ~30 min with no step-result; a long ralph iteration emits none, so it can kill a healthy 8h run. **Add a long-runner flag or per-iteration heartbeat** the reaper respects.
4. **Enrich-in-place safety (highest blast radius) — quarantine, NOT a gate.** Create + enrich-in-place is authorized, but an LLM rewriting real `hr-vault-main-pa` notes unattended is the most dangerous behavior. **The `pending_gate` approach is verified non-functional here:** `pending_gate` only acts at the top-level tick dispatcher (`workflow_engine.py:929-980`); a record step runs *inside* ralph's `while True` via `_execute_one_step`, and `ralph.py:123` would miscount an `awaiting_approval` result as a *failed iteration*. **So quarantine is the ONLY headless-safe mechanism:** new note → write to target; **any existing path → write to `_research/_staging/<slug>.md`** and let the operator review/promote manually (no 3am approver exists). Default writes target `_research`/`_projects`.
5b. **`max_vault_notes_per_run` must survive resume.** Enforce against an **on-disk / journaled** note count, not a loop-local int — `ralph.py:65-67` re-zeros loop-locals on every resume, so a crash-resume loop could blow past the cap across restarts.
6b. **Absolute paths mandatory in the template.** Pin `MEMORY_DATA_DIR`, `journal_path`, and `ENCLAVE_VAULT_DIR` to absolute deployment-user-layer paths — the `./data` default is cwd-relative, so a cwd change between launch and resume silently re-runs the loop from zero.
5. **Enrich needs a read path** — `consolidate.py` only writes. The chosen vault writer must support read-existing-then-rewrite.
6. **Concurrency is illusory by default.** `MAX_CONCURRENT_LLM=1` serializes the parallel fan-out at the daemon semaphore; `multi_model_concurrent` adds cold-load thrash (10s 7B / 90s 34B on CPU). **Default the research body to `single_model_pseudo_parallel` with one pinned model**, or document `OLLAMA_NUM_PARALLEL>1` + `MAX_CONCURRENT_LLM>1` as a prerequisite.

## Resource envelope (single 48GB M4 Pro, CPU-first)
- Engine-tick scheduling is **sequential** on `apple_unified` (`schedule_ready` returns head + deferred). Real fan-out lives **inside** the `kind:parallel` body, bounded by `max_concurrency` **and** the `MAX_CONCURRENT_LLM` daemon semaphore.
- Realistic throughput is ~one agent at a time unless Ollama parallelism is raised; pin one model for the body; `max_wall_seconds` (8h) + `max_total_tokens` + `max_vault_notes_per_run` are the real backstops.

## Resolved by gap-fill (`wf_73491e72-c87`) + critique CONDITIONAL-GO

**Build now (v1, in dependency order):**
1. **Reaper long-runner protection** (lands on master independently): add a `long_runner` flag on `WorkflowRun` (or a `last_heartbeat` ralph bumps each journal append) and have `_reap_orphan_runs` (`workflow_engine.py:219`) honor it — else a healthy 8h run with no step-result for 30 min is marked FAILED.
2. **Ralph cancel fix** + regression test (`ralph.py:71-93` add `_should_cancel` check).
3. **`vault_writer.py`** (filesystem-direct, per must-fix #1) + `kind:record` body step; quarantine-only enrich; RAG dedup; resume-safe note cap.
4. **`RalphHalt` extensions**: `max_consecutive_dry` (dry = record wrote zero novel blocks, via `append_with_dedup`), `max_vault_notes_per_run`, pinned single model. **No `NoveltyLedger`.**
5. **`workflows/autonomous-research.yaml`** — `kind:ralph` root → `identify → kind:parallel research (single_model_pseudo_parallel, one pinned model) → enrich → record(vault) → index`. Absolute paths. `dry_streak` is a **halt** condition (operator re-runs), **not** a new pausable ralph state (avoids a state-machine rewrite).
6. **Engine integration tests** (extend `tests/integration/test_ralph_step.py`): cancel-lands-fast, durable cross-process resume, vault round-trip to a tmp vault, `max_vault_notes` cap, quarantine-on-existing, dry-streak halt. Pin tiny budgets + `pytest-timeout`; set `asyncio_mode=auto`.

**Deep-runs view — DEPENDENCY-GATED (defer):** the SSE event substrate (`run_event.py`/`run_event_bus.py`/`run_plan.py`) lives only on `feat/run-event-substrate`, **not master**, and ralph/parallel emit nothing mid-loop. Sequence: merge the substrate → add a ~50-line ralph/parallel emit-extension (`iteration.*`/`budget.tick`/`vault.write`/`heartbeat`) → then the UI. **v1 ships a journal-poll fallback panel only** (poll `GET /runs/{id}` + a small journal-tail endpoint → iteration count, tokens, goal status). The full per-agent-lanes / burn-down-gauge UI waits for the substrate and real concurrency (pin-one-model means lanes are premature on a default `MAX_CONCURRENT_LLM=1` box).

**Concurrency reality:** `MAX_CONCURRENT_LLM=1` serializes the parallel body at the daemon semaphore; pin one model + `single_model_pseudo_parallel`. Don't ship UI implying concurrency the appliance doesn't deliver.

## Decision for the operator
The **deep-runs view** needs `feat/run-event-substrate` on master. Two paths: **(a)** merge that branch first, then build the rich live view; or **(b)** ship the journal-poll MVP panel now and add the rich view after the branch merges. Recommend (b) for momentum — it's independent of the branch and delivers 90% of the operator value (iteration/tokens/goal/notes-written).

## Out of scope
- Fleet-level (cross-host) budgets — defer to 1.4.x.
- Embedding-based near-dup detection — defer (per-finding embedding call competes for the single LLM semaphore on CPU).
- New `paused_dry` run status — reuse `awaiting_approval` semantics or terminate-success on dry.
