# Autonomous Orchestration & Infinity Runs — Design (Subsystem C)

**Status:** Draft (engine + critique settled; vault-write mechanism / runs-view / testing pending gap-fill workflow) · **Date:** 2026-06-29
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
1. **Vault-write path is broken as first proposed.** `ConsolidateSpec.target` is `Literal['playbook','semantic','episodic']` and `memory_store._safe_name()` strips `/`, so consolidate **cannot** target `_research/_projects`. A **new vault writer is required** — *mechanism decision pending the gap-fill workflow* (direct filesystem write to the vault dir with Obsidian frontmatter, vs the obsidian/vault-os MCP tools via `mcp_tool_invoker`). Leaning filesystem-direct for atomicity/simplicity; MCP if correct frontmatter/MOC routing proves necessary.
2. **Cancel bug.** `ralph.py`'s inner `while True` never calls `engine._should_cancel`, so operator `/cancel` won't land until the entire (up to 8h) ralph step returns. `halt_file` works mid-loop; cancel does not. **Add a `_should_cancel` check to ralph's halt block.**
3. **Orphan reaper vs long-runners.** `_reap_orphan_runs` marks runs FAILED after ~30 min with no step-result; a long ralph iteration emits none, so it can kill a healthy 8h run. **Add a long-runner flag or per-iteration heartbeat** the reaper respects.
4. **Enrich-in-place safety (highest blast radius).** Create + enrich-in-place is authorized, but an LLM rewriting real `hr-vault-main-pa` notes with no diff/approval gate is the single most dangerous behavior. **New/enriched notes go to a quarantine/staging area, or require an approval gate before overwriting any human-authored note.** Default writes target `_research`/`_projects`.
5. **Enrich needs a read path** — `consolidate.py` only writes. The chosen vault writer must support read-existing-then-rewrite.
6. **Concurrency is illusory by default.** `MAX_CONCURRENT_LLM=1` serializes the parallel fan-out at the daemon semaphore; `multi_model_concurrent` adds cold-load thrash (10s 7B / 90s 34B on CPU). **Default the research body to `single_model_pseudo_parallel` with one pinned model**, or document `OLLAMA_NUM_PARALLEL>1` + `MAX_CONCURRENT_LLM>1` as a prerequisite.

## Resource envelope (single 48GB M4 Pro, CPU-first)
- Engine-tick scheduling is **sequential** on `apple_unified` (`schedule_ready` returns head + deferred). Real fan-out lives **inside** the `kind:parallel` body, bounded by `max_concurrency` **and** the `MAX_CONCURRENT_LLM` daemon semaphore.
- Realistic throughput is ~one agent at a time unless Ollama parallelism is raised; pin one model for the body; `max_wall_seconds` (8h) + `max_total_tokens` + `max_vault_notes_per_run` are the real backstops.

## Pending the gap-fill workflow (`wf_73491e72-c87`)
- **Vault-write mechanism** — filesystem-direct vs MCP vault tools (resolve + implement-ready detail).
- **Deep-runs view** — per-agent lanes, budget burn-down, dry-streak/novelty, vault-write log, resume state (builds on `feat/run-event-substrate`).
- **Testing/CI strategy** — parity harness, per-module JS unit tests (no build step), engine integration tests (budgets, dry-streak pause, durable resume, cancel-mid-loop), CI matrix.
- The concrete `workflows/autonomous-research.yaml`.

## Out of scope
- Fleet-level (cross-host) budgets — defer to 1.4.x.
- Embedding-based near-dup detection — defer (per-finding embedding call competes for the single LLM semaphore on CPU).
- New `paused_dry` run status — reuse `awaiting_approval` semantics or terminate-success on dry.
