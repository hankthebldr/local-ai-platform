"""
kind=parallel executor — fan-out / gather composite.

Mode selection (`execution.mode`):
  - auto                          → engine picks based on branch model set
  - multi_model_concurrent        → ThreadPoolExecutor; heterogeneous branches
  - single_model_concurrent       → ThreadPoolExecutor; all branches must
                                    resolve to the same model name.
                                    Surfaces a warning when MAX_CONCURRENT_LLM=1
                                    (the daemon semaphore serializes anyway).
  - single_model_pseudo_parallel  → sequential dispatch in declared order;
                                    all branches must resolve to the same
                                    model. Keeps the prompt cache warm
                                    between branches.
  - sharded                       → one persona × N input shards; the engine
                                    clones the persona per shard, runs them
                                    sequentially, and the gather step reads
                                    all shard results via `$shards`.

When all branches resolve, the gather step runs synchronously and its outputs
are materialized into the parent's workspace namespace.
"""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, TYPE_CHECKING

from ...logging_config import logger
from ...models.workflow_models import (
    AgentStep,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from ..sharders import shard as _shard

if TYPE_CHECKING:
    from ..workflow_engine import WorkflowEngine


# ── Branch dispatch — concurrent vs sequential ────────────────────────────


def _dispatch_branches(
    engine: "WorkflowEngine",
    parent: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
    branch_models: Dict[str, str],
    mode: str,
) -> Dict[str, StepResult]:
    """Run a parallel step's branches per the resolved execution mode.

    Two dispatch shapes:

      * Concurrent (multi_model_concurrent, single_model_concurrent):
        ThreadPoolExecutor up to execution.max_concurrency. Note that the
        daemon-side _LLM_SEMAPHORE serializes Ollama calls when
        MAX_CONCURRENT_LLM=1 — the workflow asks for concurrency, the
        daemon decides whether it can grant it.

      * Sequential (single_model_pseudo_parallel):
        Branches run in declared order, single-threaded. Trade-off: no
        wall-clock parallelism, but the model stays loaded across branches
        and Ollama's prompt cache survives between calls (~70% latency
        reduction for prefix-heavy workflows on single 30B+ models on CPU
        — see spec §3.3).

    Returns {branch_id: StepResult} in both cases. Failures are returned as
    failed StepResults (caller decides what to do).
    """
    branch_results: Dict[str, StepResult] = {}
    execution_cfg = parent.execution
    max_concurrency = execution_cfg.max_concurrency if execution_cfg else 4
    # prefix_lock only matters in pseudo-parallel mode (the concurrent modes
    # don't share KV state between calls, so a byte-stable prefix can't earn
    # a cache hit). The validator already rejects prefix_lock=True for the
    # wrong modes.
    prefix_locked = bool(
        execution_cfg
        and execution_cfg.prefix_lock
        and mode == "single_model_pseudo_parallel"
    )

    if mode == "single_model_pseudo_parallel":
        logger.info(
            f"Parallel step '{parent.id}' dispatching "
            f"{len(parent.branches)} branch(es) sequentially "
            f"(mode=single_model_pseudo_parallel, prefix_lock={prefix_locked})"
        )
        for branch in parent.branches:
            try:
                res = engine._execute_one_step(
                    branch,
                    definition,
                    context,
                    workflow_run,
                    branch_models[branch.id],
                    prefix_locked=prefix_locked,
                )
            except Exception as e:
                res = StepResult(
                    step_id=branch.id,
                    status="failed",
                    error=f"Branch raised: {e}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
            branch_results[branch.id] = res
        return branch_results

    # Concurrent dispatch (multi_model_concurrent or single_model_concurrent).
    lock = threading.Lock()
    logger.info(
        f"Parallel step '{parent.id}' dispatching "
        f"{len(parent.branches)} branch(es) concurrently (mode={mode}, "
        f"max_concurrency={max_concurrency})"
    )
    with ThreadPoolExecutor(
        max_workers=min(max_concurrency, len(parent.branches)),
        thread_name_prefix=f"par-{parent.id[:16]}",
    ) as ex:
        futures = {
            ex.submit(
                engine._execute_one_step,
                branch,
                definition,
                context,
                workflow_run,
                branch_models[branch.id],
            ): branch
            for branch in parent.branches
        }
        for fut in as_completed(futures):
            branch = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = StepResult(
                    step_id=branch.id,
                    status="failed",
                    error=f"Branch raised: {e}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
            with lock:
                branch_results[branch.id] = res
    return branch_results


# ── kind=parallel executor ────────────────────────────────────────────────


def execute(
    engine: "WorkflowEngine",
    parent: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
) -> StepResult:
    """Run a kind=parallel step."""
    agg = StepResult(step_id=parent.id, status="running", started_at=datetime.utcnow())
    execution_cfg = parent.execution
    declared_mode = execution_cfg.mode if execution_cfg else "multi_model_concurrent"
    failure_policy = execution_cfg.failure_policy if execution_cfg else "fail_fast"

    # Sharded mode generates its branches at runtime from one persona + a
    # sharded input — a distinct enough path to handle separately.
    if declared_mode == "sharded":
        return _execute_sharded(engine, parent, definition, context, workflow_run)

    # Pre-resolve a model for each branch. Failures here are workflow-level —
    # we never start any branch if one can't be resolved.
    branch_models: Dict[str, str] = {}
    for branch in parent.branches:
        if branch.kind == "llm":
            try:
                branch_models[branch.id] = engine.resolver.resolve(
                    model=branch.model,
                    role=branch.role,
                    default_role=definition.defaults.role,
                )
            except Exception as e:
                agg.status = "failed"
                agg.error = (
                    f"Parallel branch '{branch.id}' model resolution failed: {e}"
                )
                agg.completed_at = datetime.utcnow()
                agg.duration_seconds = (
                    agg.completed_at - agg.started_at
                ).total_seconds()
                logger.error(agg.error)
                return agg
        else:
            # Nested composite branches — recursive _execute_one_step handles it.
            branch_models[branch.id] = ""

    # Resolve `auto` mode + enforce same-model invariant for single-model modes.
    unique_models = {m for m in branch_models.values() if m}
    effective_mode = declared_mode
    if declared_mode == "auto":
        effective_mode = (
            "single_model_pseudo_parallel"
            if len(unique_models) <= 1
            else "multi_model_concurrent"
        )
        logger.info(
            f"Parallel step '{parent.id}' mode=auto resolved to "
            f"'{effective_mode}' ({len(unique_models)} unique model(s) "
            f"across {len(parent.branches)} branch(es))"
        )

    if (
        effective_mode
        in (
            "single_model_concurrent",
            "single_model_pseudo_parallel",
        )
        and len(unique_models) > 1
    ):
        agg.status = "failed"
        agg.error = (
            f"Parallel step '{parent.id}' declared mode='{effective_mode}' "
            f"but branches resolved to {len(unique_models)} different "
            f"models: {sorted(unique_models)}. Switch to "
            f"'multi_model_concurrent' or pin all branches to the same model."
        )
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    # single_model_concurrent on a single-slot daemon won't actually run
    # concurrently — surface this so operators don't expect speedup that the
    # deployment can't deliver.
    if effective_mode == "single_model_concurrent":
        try:
            from ..ollama_service import MAX_CONCURRENT_LLM

            if MAX_CONCURRENT_LLM == 1:
                logger.warning(
                    f"Parallel step '{parent.id}' mode=single_model_concurrent "
                    f"but MAX_CONCURRENT_LLM=1 — daemon semaphore will "
                    f"serialize branches. Either set MAX_CONCURRENT_LLM>1 "
                    f"(requires OLLAMA_NUM_PARALLEL>1 on the daemon) or "
                    f"switch to single_model_pseudo_parallel for explicit "
                    f"sequential dispatch."
                )
        except Exception:
            pass

    branch_results = _dispatch_branches(
        engine,
        parent=parent,
        definition=definition,
        context=context,
        workflow_run=workflow_run,
        branch_models=branch_models,
        mode=effective_mode,
    )

    # Roll up token counts + durations into the composite result.
    total_prompt = sum(
        r.token_count.get("prompt_tokens", 0) for r in branch_results.values()
    )
    total_completion = sum(
        r.token_count.get("completion_tokens", 0) for r in branch_results.values()
    )
    agg.token_count = {
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
    }

    failed_branches = [b for b, r in branch_results.items() if r.status != "completed"]
    if failed_branches and failure_policy == "fail_fast":
        agg.status = "failed"
        agg.error = (
            f"Parallel step '{parent.id}' aborted: "
            f"{len(failed_branches)} branch(es) failed "
            f"({', '.join(failed_branches)}) under fail_fast policy"
        )
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg
    if failed_branches:
        logger.warning(
            f"Parallel step '{parent.id}' continuing with "
            f"{len(failed_branches)} failed branch(es) under "
            f"continue_on_partial policy: {failed_branches}"
        )

    # Run gather synchronously. Gather is always llm-kind (validator).
    try:
        gather_model = engine.resolver.resolve(
            model=parent.gather.model,
            role=parent.gather.role,
            default_role=definition.defaults.role,
        )
    except Exception as e:
        agg.status = "failed"
        agg.error = f"Gather model resolution failed: {e}"
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    gather_res = engine._execute_one_step(
        parent.gather, definition, context, workflow_run, gather_model
    )
    agg.token_count["prompt_tokens"] += gather_res.token_count.get("prompt_tokens", 0)
    agg.token_count["completion_tokens"] += gather_res.token_count.get(
        "completion_tokens", 0
    )
    agg.token_count["total_tokens"] = (
        agg.token_count["prompt_tokens"] + agg.token_count["completion_tokens"]
    )
    agg.model_used = gather_res.model_used

    if gather_res.status != "completed":
        agg.status = "failed"
        agg.error = f"Gather step '{parent.gather.id}' failed: {gather_res.error}"
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    # Materialize the parent's outputs from gather's workspace. Validator
    # guarantees gather.outputs == parent.outputs (set equality).
    gather_ws = context.workspace.get(parent.gather.id, {})
    for key in parent.outputs:
        context.set_workspace(parent.id, key, gather_ws.get(key))

    agg.status = "completed"
    agg.completed_at = datetime.utcnow()
    agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
    logger.info(
        f"Parallel step '{parent.id}' completed in "
        f"{agg.duration_seconds:.1f}s ({len(branch_results)} branches + gather)"
    )
    return agg


# ── Sharded (mode=sharded) ────────────────────────────────────────────────


def _execute_sharded(
    engine: "WorkflowEngine",
    parent: AgentStep,
    definition: WorkflowDefinition,
    context: WorkflowContext,
    workflow_run: WorkflowRun,
) -> StepResult:
    """Run a sharded parallel composite (mode=sharded).

    One persona (the single declared branch) is cloned per shard of the
    resolved `shard_input`. Each clone runs sequentially (single-model) in a
    child context seeded with its shard, then the gather step synthesizes all
    shard outputs via the `$shards` accessor. Sequential dispatch keeps the
    model loaded across shards (prompt-cache reuse) and avoids concurrent
    writes to the shared workspace.
    """
    agg = StepResult(step_id=parent.id, status="running", started_at=datetime.utcnow())
    cfg = parent.execution
    persona = parent.branches[0]

    # Resolve + shard the input.
    raw = context.resolve_input(cfg.shard_input)
    shards = _shard(
        cfg.sharder, raw, shard_size=cfg.shard_size, max_shards=cfg.max_shards
    )
    if not shards:
        agg.status = "failed"
        agg.error = (
            f"Sharded step '{parent.id}': shard_input '{cfg.shard_input}' "
            f"resolved to no shards (value was {raw!r:.80})"
        )
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    # Resolve the persona's model once (all shards share it).
    persona_model = ""
    if persona.kind == "llm":
        try:
            persona_model = engine.resolver.resolve(
                model=persona.model,
                role=persona.role,
                default_role=definition.defaults.role,
            )
        except Exception as e:
            agg.status = "failed"
            agg.error = f"Sharded persona model resolution failed: {e}"
            agg.completed_at = datetime.utcnow()
            agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
            logger.error(agg.error)
            return agg

    logger.info(
        f"Sharded step '{parent.id}': '{cfg.sharder}' split "
        f"'{cfg.shard_input}' into {len(shards)} shard(s); cloning persona "
        f"'{persona.id}' per shard (sequential)"
    )

    shard_results: List[Dict[str, Any]] = []
    failures: List[str] = []
    for i, shard_value in enumerate(shards):
        clone = copy.deepcopy(persona)
        clone.id = f"{parent.id}__{persona.id}_shard{i}"
        # Child context: parent seed + shard fields, sharing the live
        # workspace/shared/memory so the persona can still read prior steps.
        child = WorkflowContext(
            seed={
                **context.seed,
                "shard": shard_value,
                "shard_index": i,
                "shard_count": len(shards),
            },
            workspace=context.workspace,
            shared=context.shared,
        )
        if context._memory is not None:
            child.attach_memory(context._memory)

        try:
            res = engine._execute_one_step(
                clone, definition, child, workflow_run, persona_model
            )
        except Exception as e:  # noqa: BLE001
            res = StepResult(
                step_id=clone.id,
                status="failed",
                error=f"Shard {i} raised: {e}",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )

        agg.token_count["prompt_tokens"] += res.token_count.get("prompt_tokens", 0)
        agg.token_count["completion_tokens"] += res.token_count.get(
            "completion_tokens", 0
        )
        agg.model_used = res.model_used

        # Read from the CHILD context: Pydantic copies the workspace dict on
        # construction, so the persona's writes land in `child`, not the
        # parent. Each shard's outputs become one entry in the $shards list.
        if res.status == "completed":
            shard_results.append(dict(child.workspace.get(clone.id, {})))
        else:
            failures.append(f"shard {i}: {res.error}")
            shard_results.append({"_shard_failed": True, "_error": res.error})

    agg.token_count["total_tokens"] = (
        agg.token_count["prompt_tokens"] + agg.token_count["completion_tokens"]
    )

    if failures and cfg.failure_policy == "fail_fast":
        agg.status = "failed"
        agg.error = (
            f"Sharded step '{parent.id}' aborted: {len(failures)} shard(s) "
            f"failed under fail_fast policy ({failures[0]})"
        )
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg
    if failures:
        logger.warning(
            f"Sharded step '{parent.id}' continuing with {len(failures)} "
            f"failed shard(s) under continue_on_partial policy"
        )

    # Run gather with $shards populated.
    try:
        gather_model = engine.resolver.resolve(
            model=parent.gather.model,
            role=parent.gather.role,
            default_role=definition.defaults.role,
        )
    except Exception as e:
        agg.status = "failed"
        agg.error = f"Sharded gather model resolution failed: {e}"
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    context.set_shards(shard_results)
    try:
        gather_res = engine._execute_one_step(
            parent.gather, definition, context, workflow_run, gather_model
        )
    finally:
        context.set_shards(None)

    agg.token_count["prompt_tokens"] += gather_res.token_count.get("prompt_tokens", 0)
    agg.token_count["completion_tokens"] += gather_res.token_count.get(
        "completion_tokens", 0
    )
    agg.token_count["total_tokens"] = (
        agg.token_count["prompt_tokens"] + agg.token_count["completion_tokens"]
    )
    agg.model_used = gather_res.model_used

    if gather_res.status != "completed":
        agg.status = "failed"
        agg.error = f"Sharded gather '{parent.gather.id}' failed: {gather_res.error}"
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        logger.error(agg.error)
        return agg

    gather_ws = context.workspace.get(parent.gather.id, {})
    for key in parent.outputs:
        context.set_workspace(parent.id, key, gather_ws.get(key))

    agg.status = "completed"
    agg.completed_at = datetime.utcnow()
    agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
    logger.info(
        f"Sharded step '{parent.id}' completed in {agg.duration_seconds:.1f}s "
        f"({len(shards)} shard(s) + gather)"
    )
    return agg
