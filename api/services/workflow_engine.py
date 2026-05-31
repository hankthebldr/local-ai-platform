"""
Workflow Engine — Load, validate, and execute multi-agent workflows

Orchestrates sequential step execution with three-layer context management.
Integrates with ModelResolver for role-based model selection and
StepExecutor for individual step execution with retry logic.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from ..logging_config import logger
from ..exceptions import WorkflowValidationError
from ..models.workflow_models import (
    AgentStep,
    PreWarmEvent,
    RunTelemetrySummary,
    StepResult,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowRun,
)
from .model_resolver import ModelResolver
from .step_executor import StepExecutor
from .ollama_service import OllamaService
from .hook_bus import HookBus
from .prompt_composer import PromptComposer

# Default data directory for workflow run persistence
DATA_DIR = os.getenv("WORKFLOW_DATA_DIR", "./data/workflows")


# Threshold (ms) at which a step's load_duration is counted as a "cold load"
# rather than warm reuse. ~100ms is a generous bar — true warm reuse is <50ms
# on every arch; values between 50-100ms are typically warm w/ small overhead.
_COLD_LOAD_THRESHOLD_MS = 100.0


# Back-compat re-export: the gate evaluator and its constants moved to
# engine_executors/loop.py (it's used by both kind=loop and kind=ralph). The
# old test suite imports `_evaluate_gate` from this module, so we re-export
# under the legacy name. `noqa: F401` — these are intentional re-exports.
from .engine_executors.loop import (  # noqa: F401
    _GATE_REF_RE,
    _SAFE_GATE_NODES,
    evaluate_gate as _evaluate_gate,
)


def _aggregate_telemetry(
    step_results: List[StepResult],
    pre_warm_events: Optional[List[PreWarmEvent]] = None,
) -> Optional[RunTelemetrySummary]:
    """Roll up per-step Phase-2 + Phase-5b telemetry into a per-run summary.

    Returns None when no step has telemetry populated — preserves the
    "no observability data" signal rather than reporting all zeros.
    """
    has_step_telemetry = any(
        r.load_duration_ms is not None or r.eval_duration_ms is not None
        for r in step_results
    )
    # Phase 5b — a run can have pre_warm telemetry even when steps don't
    # (e.g. stub-Ollama tests, or a run that crashed before any step
    # returned Ollama timing). Don't suppress the summary in that case.
    has_pre_warm_telemetry = bool(pre_warm_events)
    if not has_step_telemetry and not has_pre_warm_telemetry:
        return None

    summary = RunTelemetrySummary()
    for r in step_results:
        if r.load_duration_ms is not None:
            if r.load_duration_ms >= _COLD_LOAD_THRESHOLD_MS:
                summary.total_cold_load_ms += r.load_duration_ms
                summary.cold_load_count += 1
            else:
                summary.warm_step_count += 1
        if r.eval_duration_ms is not None:
            summary.total_eval_ms += r.eval_duration_ms
        if r.prompt_eval_duration_ms is not None:
            summary.total_prompt_eval_ms += r.prompt_eval_duration_ms
        if summary.arch_name is None and r.arch_name is not None:
            summary.arch_name = r.arch_name

    # Phase 5b — pre-warm aggregation. Hit/miss is set on each event by
    # _resolve_pre_warm_hits before this function is called.
    for event in pre_warm_events or []:
        summary.pre_warm_count += 1
        if event.hit is True:
            summary.pre_warm_hits += 1
        elif event.hit is False:
            summary.pre_warm_misses += 1
        if event.load_duration_ms is not None:
            summary.total_pre_warm_load_ms += event.load_duration_ms

    return summary


def _strict_validation() -> bool:
    """Phase 5 — when set, extension warnings (unreachable MCP, missing-skill
    plugin) are promoted to validation errors that block the run."""
    return os.getenv("STRICT_VALIDATION", "").lower() in ("1", "true", "yes")


def _resolve_pre_warm_hits(workflow_run: WorkflowRun) -> None:
    """Phase 5b — walk pre_warm_events and decide hit/miss against step_results.

    A pre-warm "hits" when the first downstream step that uses the pre-warmed
    model:
      1. Started AFTER the pre-warm was dispatched (timing-correct), AND
      2. Has load_duration_ms < _COLD_LOAD_THRESHOLD_MS (Ollama reports warm).

    A "miss" means we fired the pre-warm but the consuming step still paid
    a cold load — Ollama evicted between pre-warm and consumption, or the
    pre-warm itself failed. hit=None means we never found a consuming step
    (rare; would mean the workflow short-circuited before reaching the next
    tick).
    """
    for event in workflow_run.pre_warm_events:
        if event.error is not None:
            event.hit = False
            continue
        # Find the first step_result that uses this model AND started after
        # the pre-warm dispatched. step_results is in completion order, not
        # start order, but the `started_at` field is reliable here.
        candidates = [
            r
            for r in workflow_run.step_results
            if r.model_used == event.model
            and r.started_at is not None
            and r.started_at >= event.dispatched_at
        ]
        if not candidates:
            event.hit = None
            continue
        # Pick the earliest-started — the pre-warm's intended consumer.
        consumer = min(candidates, key=lambda r: r.started_at)
        event.hit_step_id = consumer.step_id
        if consumer.load_duration_ms is None:
            event.hit = None
        else:
            event.hit = consumer.load_duration_ms < _COLD_LOAD_THRESHOLD_MS


class WorkflowEngine:
    """
    Central orchestrator for multi-agent workflows.

    Phases:
    1. Load — parse YAML into WorkflowDefinition
    2. Validate — check I/O wiring, model availability
    3. Execute — run steps sequentially, manage context
    4. Persist — save run results to disk
    """

    def __init__(self, ollama_service: OllamaService):
        self.ollama = ollama_service
        self.resolver = ModelResolver(ollama_service)
        # Prompt composer
        project_root = Path(__file__).resolve().parents[2]
        self.composer = PromptComposer(
            roles_dir=project_root / "prompts" / "roles",
            templates_dir=project_root / "prompts" / "templates",
        )
        # Memory store for kind=consolidate steps + $memory.* accessors.
        # Lazy import keeps the module load order tolerant; the store itself
        # is stateless beyond its base dir.
        from .memory_store import MemoryStore

        self.memory = MemoryStore()
        # Hook bus default is built per-step in _build_step_bus()
        self._project_root = project_root
        # Cancel set — run_ids that have received a cancel request. The
        # execution loop checks this between steps; in-flight LLM calls
        # complete normally (cooperative cancel, not pre-emptive). This
        # is a process-local set, so a multi-worker uvicorn deployment
        # needs to honour cancels via the persisted run.status field
        # instead — the loop checks both.
        self._cancel_set: set = set()
        # Phase 5 — pre-warm in-flight tracker. Keyed by resolved model name;
        # the daemon worker thread clears its entry on completion. Lock guards
        # the set against the tick loop firing duplicate pre-warms.
        import threading as _threading

        self._pre_warm_lock = _threading.Lock()
        self._pre_warm_inflight: set = set()
        # Phase 5 (MCP & Skills) — most recent extension pre-flight result.
        # Stored after each ``validate()`` call so the router can surface
        # warnings (registered-but-unreachable MCPs, missing-skill plugin)
        # alongside the success response.
        self._last_extension_result = None
        # Phase 2b (MCP & Skills) — co-scheduler's last output stashed for
        # the validate endpoint to surface optimization recommendations.
        self._last_co_scheduling_result = None
        # Phase 5.4 — page-cache recency window for warm_eviction_candidate
        # decisions on UnifiedArchitecture. Models evicted within this many
        # seconds are flagged as still-mmap-able. 5 min is the documented
        # macOS page-cache "soft" lifetime; aggressive workloads can override.
        self._page_cache_recency_seconds = 300.0
        # Startup reaper — orphaned runs from a previous crash/restart
        # get marked as failed so the UI's poller can stop chasing them.
        # Idempotent: subsequent boots are no-ops because the targets
        # are now in a terminal state.
        try:
            n = self._reap_orphan_runs()
            if n:
                logger.info(
                    "Reaped %s orphan workflow run(s) marked running from prior boot.",
                    n,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Orphan-run reaper failed: %s", exc)

    def _reap_orphan_runs(self, stale_minutes: int = 30) -> int:
        """Mark abandoned 'running' runs as failed.

        Scans every ``data/workflows/<run_id>/run.json`` checkpoint.
        A run qualifies as orphaned when:

          - status is running OR queued
          - no completed_at
          - last touch (newest of step.completed_at, step.started_at,
            run.started_at) is older than ``stale_minutes``

        Writes ``status=failed`` and a descriptive error onto the
        checkpoint. Returns the number of runs reaped.

        Called exactly once per process boot from __init__. After the
        first scan, normal engine pathways (step completion, cancel,
        resume) drive every status transition.
        """
        import json as _json
        from datetime import datetime, timezone

        runs_dir = self._project_root / "data" / "workflows"
        if not runs_dir.is_dir():
            return 0

        cutoff_s = stale_minutes * 60
        now = datetime.now(timezone.utc).timestamp()
        reaped = 0
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            cp = run_dir / "run.json"
            if not cp.exists():
                continue
            try:
                with open(cp) as f:
                    data = _json.load(f)
            except Exception:
                continue

            status = (data.get("status") or "").lower()
            if status not in {"running", "queued"} or data.get("completed_at"):
                continue

            # Collect all known timestamps; treat the newest as last touch.
            stamps: list = []
            started_at = data.get("started_at")
            if started_at:
                stamps.append(started_at)
            for s in data.get("step_results") or []:
                if not isinstance(s, dict):
                    continue
                for k in ("completed_at", "started_at"):
                    v = s.get(k)
                    if v:
                        stamps.append(v)

            def _to_ts(v):
                try:
                    return datetime.fromisoformat(
                        str(v).replace("Z", "+00:00")
                    ).timestamp()
                except (TypeError, ValueError):
                    return 0

            newest = max((_to_ts(v) for v in stamps), default=0)
            if not newest or (now - newest) <= cutoff_s:
                continue

            # Mark failed in place.
            data["status"] = "failed"
            data["completed_at"] = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
            existing_err = data.get("error") or ""
            data["error"] = (
                "Engine was restarted while this run was in progress; "
                "no step results were produced for "
                f"{stale_minutes}+ minutes. Marked failed at boot."
                + (f" Prior error: {existing_err}" if existing_err else "")
            )
            try:
                tmp = cp.with_suffix(".json.tmp")
                tmp.write_text(_json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(cp)
                reaped += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Could not write reaped run.json for %s: %s",
                    run_dir.name,
                    exc,
                )
        return reaped

    def request_cancel(self, run_id: str) -> bool:
        """Mark a run for cancellation. Returns True if newly added."""
        if not run_id:
            return False
        if run_id in self._cancel_set:
            return False
        self._cancel_set.add(run_id)
        return True

    def _should_cancel(self, run_id: str) -> bool:
        """Cancel check — honors process-local set OR persisted status."""
        if run_id in self._cancel_set:
            return True
        # Cross-worker channel: a sibling worker may have written
        # status="canceled" to the run.json checkpoint.
        try:
            cp = self._project_root / "data" / "workflows" / run_id / "run.json"
            if cp.exists():
                import json as _json

                with open(cp) as f:
                    d = _json.load(f)
                return (d.get("status") or "").lower() == "canceled"
        except Exception:
            pass
        return False

    # ── Load Phase ─────────────────────────────────────────────────────

    def load(self, yaml_path: str) -> WorkflowDefinition:
        """Load a workflow definition from a YAML file"""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {yaml_path}")

        with open(path) as f:
            raw = yaml.safe_load(f)

        try:
            definition = WorkflowDefinition(**raw)
        except Exception as e:
            raise WorkflowValidationError(f"Invalid workflow YAML: {e}")

        logger.info(
            f"Loaded workflow '{definition.id}' ({len(definition.steps)} steps)"
        )
        return definition

    def load_from_dict(self, data: Dict[str, Any]) -> WorkflowDefinition:
        """Load a workflow definition from a dictionary (for API usage)"""
        try:
            return WorkflowDefinition(**data)
        except Exception as e:
            raise WorkflowValidationError(f"Invalid workflow definition: {e}")

    # ── Validate Phase ─────────────────────────────────────────────────

    def validate(
        self,
        definition: WorkflowDefinition,
        seed_keys: Optional[List[str]] = None,
    ) -> None:
        """
        Validate workflow I/O wiring.

        Checks that every step's declared inputs can be traced to:
        - A seed key
        - A prior step's declared output
        - A shared key produced by a prior step

        Raises WorkflowValidationError if validation fails.
        """
        available_outputs: Set[str] = set()

        # Seed keys are available from the start
        if seed_keys:
            for key in seed_keys:
                available_outputs.add(f"seed.{key}")

        errors = []

        def _validate_step(step, available: Set[str]) -> None:
            """Validate one step recursively.

            `available` is the set of `<namespace>.<key>` strings the step is
            allowed to reference as inputs. For composite kinds, child steps
            inherit the parent's available set plus whatever earlier
            children/branches have produced.
            """
            hooks_block = getattr(step, "hooks", None)
            if hooks_block is not None:
                # Both plugin_tool_invoker and mcp_tool_invoker write to
                # workspace[step.id][store_as] before input resolution, so
                # references to <step_id>.<store_as> resolve cleanly.
                for spec in getattr(hooks_block, "before_step", []) or []:
                    if getattr(spec, "name", None) in (
                        "plugin_tool_invoker",
                        "mcp_tool_invoker",
                    ):
                        store_as = (spec.config or {}).get("store_as")
                        if store_as:
                            available.add(f"{step.id}.{store_as}")

            for input_ref in step.inputs:
                if input_ref not in available:
                    if input_ref.startswith("seed.") and seed_keys is None:
                        continue
                    # $memory.* refs read from the durable memory store, not
                    # from a prior step — always considered available. A
                    # first run against an empty store reads "".
                    if input_ref.startswith("$memory."):
                        continue
                    # $shards / $shards.* are populated by the engine for a
                    # sharded gather step; always available (→ [] otherwise).
                    if input_ref == "$shards" or input_ref.startswith("$shards."):
                        continue
                    errors.append(
                        f"Step '{step.id}' input '{input_ref}' has no producer. "
                        f"Available: {sorted(available)}"
                    )

            if step.kind == "parallel":
                # Each branch sees: parent's available set + sibling branches'
                # outputs produced before it. Branches without depends_on are
                # treated as DAG-parallel and only see seed/external inputs.
                branch_available = set(available)
                is_sharded = (
                    step.execution is not None and step.execution.mode == "sharded"
                )
                if is_sharded:
                    # The engine seeds each persona clone with the shard fields,
                    # so the persona may reference them even when seed_keys is set.
                    branch_available.update(
                        ("seed.shard", "seed.shard_index", "seed.shard_count")
                    )
                for branch in step.branches or []:
                    _validate_step(branch, branch_available)
                    for k in branch.outputs:
                        branch_available.add(f"{branch.id}.{k}")
                # Gather sees the parent's `available` plus all branches.
                _validate_step(step.gather, branch_available)
            elif step.kind == "loop":
                # Body sees parent available + the loop's own declared inputs
                # (already in `available` via the parent's input declaration)
                # plus prior body steps' outputs. Each body step's outputs are
                # registered for downstream body steps in the same iteration.
                body_available = set(available)
                for body_step in step.body or []:
                    _validate_step(body_step, body_available)
                    for k in body_step.outputs:
                        body_available.add(f"{body_step.id}.{k}")

            for output_key in step.outputs:
                available.add(f"{step.id}.{output_key}")

        for step in definition.steps:
            _validate_step(step, available_outputs)

        # Check for duplicate step IDs (recursive: branches and body steps must
        # not collide with top-level ids or with each other).
        def _collect_ids(step) -> List[str]:
            ids = [step.id]
            for child in step.branches or []:
                ids.extend(_collect_ids(child))
            if step.gather is not None:
                ids.extend(_collect_ids(step.gather))
            for child in step.body or []:
                ids.extend(_collect_ids(child))
            return ids

        all_ids: List[str] = []
        for step in definition.steps:
            all_ids.extend(_collect_ids(step))
        dupes = [sid for sid in set(all_ids) if all_ids.count(sid) > 1]
        if dupes:
            errors.append(f"Duplicate step IDs (including nested): {sorted(dupes)}")

        # Phase 4 — arch-aware feasibility. No-op when no step has est_size_gb
        # set (preserves the pre-Phase-4 acceptance surface). Failures here
        # are real workflow problems: a step asks for more memory than the
        # current architecture can give it.
        try:
            from .scheduler import Scheduler

            issues = Scheduler().validate_feasibility(definition)
            for issue in issues:
                errors.append(
                    f"step '{issue.step_id}' requests "
                    f"{issue.est_size_gb} GB but arch budget is "
                    f"{issue.arch_budget_gb:.1f} GB ({issue.reason})"
                )
        except Exception as e:
            # Scheduler/arch failures must not block workflow validation —
            # surface as a debug log and continue.
            logger.debug(f"Scheduler feasibility skipped: {e}")

        # Phase 5 — extension pre-flight. Walk tools/skills/required_* and
        # surface plugin/MCP gaps before the operator hits run. Errors
        # block; warnings are non-fatal unless STRICT_VALIDATION=true. A
        # bare workflow (no tools/skills/required_*) is a complete no-op.
        try:
            from .extension_preflight import check_workflow

            ext = check_workflow(definition)
            for line in ext.flatten_errors():
                errors.append(line)
            if ext.has_warnings and _strict_validation():
                for w in ext.plugin_warnings + ext.mcp_warnings + ext.skill_warnings:
                    errors.append(
                        f"[strict] {w.get('code', 'warning')}: "
                        + ", ".join(
                            f"{k}={v}"
                            for k, v in w.items()
                            if k != "code" and v is not None
                        )
                    )
            self._last_extension_result = ext  # for the validate endpoint
        except Exception as e:
            # Extension pre-flight must never crash validation — fail soft
            # the same way the scheduler check does.
            logger.debug(f"Extension pre-flight skipped: {e}")

        # Phase 2b — resource-maximization compiler pass. Walks per-step
        # pressure (model footprint + MCP RSS estimate) against the
        # arch / deployment budget; emits optimization recommendations
        # under the workflow's co_scheduling_policy. Always fail-soft.
        try:
            from .co_scheduler import apply_co_scheduling_policy

            cs = apply_co_scheduling_policy(
                definition,
                policy=definition.defaults.co_scheduling_policy,
            )
            self._last_co_scheduling_result = cs
            for line in cs.errors:
                errors.append(line)
            # warn_strict warnings get promoted only when STRICT_VALIDATION is
            # also on — keeps the policy hierarchy: reject > strict > recommend.
            if cs.warnings and _strict_validation():
                for w in cs.warnings:
                    errors.append(w)
        except Exception as e:
            logger.debug(f"co-scheduler skipped: {e}")

        if errors:
            raise WorkflowValidationError(
                f"Workflow '{definition.id}' has {len(errors)} validation error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        logger.info(f"Workflow '{definition.id}' validated successfully")

    # ── Execute Phase ──────────────────────────────────────────────────

    def run(
        self,
        definition: WorkflowDefinition,
        seed: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> WorkflowRun:
        """
        Execute a workflow end-to-end.

        Creates a WorkflowRun, iterates through steps sequentially,
        and returns the completed (or failed) run. The run is checkpointed
        to disk after each step so a crash mid-run leaves a resumable
        snapshot — see resume().

        Pass `run_id` to force a specific run identifier (used by the
        async run endpoint so the caller can pre-publish the polling
        URL before the engine starts work).
        """
        context = WorkflowContext(seed=seed)
        context.attach_memory(self.memory)
        kwargs = {
            "workflow_id": definition.id,
            "context": context,
            "started_at": datetime.utcnow(),
        }
        if run_id:
            kwargs["run_id"] = run_id
        workflow_run = WorkflowRun(**kwargs)
        workflow_run.status = "running"

        logger.info(
            f"Starting workflow '{definition.id}' run={workflow_run.run_id} "
            f"({len(definition.steps)} steps)"
        )

        # Initial checkpoint so the run is discoverable mid-flight.
        self._checkpoint(workflow_run)

        try:
            self._execute_steps(workflow_run, definition, context, definition.steps)
            # Final terminal persist (full artifacts + summary). _persist_run
            # itself drains the MCP runner pool before serializing.
            self._persist_run(workflow_run, definition)
        except Exception:
            # Defensive: if anything escapes _execute_steps before _persist_run
            # runs, the pool's runners would leak. Drain them here; the drain
            # is idempotent so this is harmless when _persist_run already ran.
            self._safe_drain_mcp_pool(workflow_run)
            raise
        return workflow_run

    def resume(
        self,
        run_id: str,
        definition: Optional[WorkflowDefinition] = None,
    ) -> WorkflowRun:
        """
        Resume a previously-checkpointed run.

        - If status is terminal (completed/failed/canceled), re-hydrate
          and return without re-running anything.
        - If status is "running" (server crashed mid-run), pick up at the
          first step that doesn't have a "completed" StepResult.

        Pass `definition` if the workflow YAML has changed since the run
        started; otherwise the engine reloads from `workflows/<workflow_id>.yaml`.

        Raises ValueError if the run isn't found.
        """
        raw = self.get_run(run_id)
        if raw is None:
            raise ValueError(f"run not found: {run_id}")

        workflow_run = WorkflowRun.model_validate(raw)
        if workflow_run.status in {"completed", "failed", "canceled"}:
            return workflow_run
        # The rehydrated context lost its (non-serialized) memory handle —
        # reattach so $memory.* inputs and consolidate steps work on resume.
        workflow_run.context.attach_memory(self.memory)

        if definition is None:
            definition = self.load(f"./workflows/{workflow_run.workflow_id}.yaml")

        completed_ids = {
            r.step_id for r in workflow_run.step_results if r.status == "completed"
        }
        # Drop any non-completed step_results so the loop produces a clean
        # tail (a "running" or "failed" intermediate gets re-executed).
        workflow_run.step_results = [
            r for r in workflow_run.step_results if r.status == "completed"
        ]
        remaining = [s for s in definition.steps if s.id not in completed_ids]

        logger.info(
            f"Resuming workflow run={run_id}: "
            f"{len(completed_ids)} step(s) already done, {len(remaining)} remaining"
        )
        workflow_run.status = "running"
        self._checkpoint(workflow_run)

        try:
            self._execute_steps(
                workflow_run, definition, workflow_run.context, remaining
            )
            self._persist_run(workflow_run, definition)
        except Exception:
            self._safe_drain_mcp_pool(workflow_run)
            raise
        return workflow_run

    def _execute_steps(
        self,
        workflow_run: WorkflowRun,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        steps: List[AgentStep],
    ) -> None:
        """
        Phase 4b — scheduler-driven execution.

        Replaces the YAML-order sequential loop with tick-based dispatch:
          1. Compute the ready set (steps whose `depends_on` are satisfied).
          2. Ask `arch.schedule_ready()` which to dispatch vs defer.
          3. Run all non-deferred steps in the tick concurrently via a
             ThreadPoolExecutor. Concurrency is bounded by the arch's
             schedule (single-GPU/unified return head + deferred rest, so
             the tick has one runner — same as pre-Phase-4b behavior).
          4. Wait for the tick to drain. On any failure, mark the run
             failed but let in-flight steps in the same tick finish first
             (their work is already paid; partial output is still useful).

        Workflows without `depends_on` declarations behave identically to
        the pre-Phase-4b loop because their arch's schedule_ready returns
        "head, deferred rest" — only one step dispatches per tick.

        Concurrency safety:
          - Step output isolation: each step writes to its own
            `workspace[step_id]` slot — different threads touch different
            dict keys.
          - State mutation: `workflow_run.step_results.append`,
            `self._checkpoint(...)`, and `workflow_run.status` mutations
            are guarded by `state_lock`.
          - Ollama serialization: OllamaService._LLM_SEMAPHORE keeps LLM
            calls serialized at the network layer regardless of how many
            threads the engine dispatches.
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .scheduler import Scheduler

        scheduler = Scheduler()
        state_lock = threading.Lock()

        # Resume-aware: every step_results entry from a prior partial run
        # contributes to completed_ids. Steps in the current dispatch list
        # but already completed (via resume) are skipped.
        completed_ids: Set[str] = {
            r.step_id for r in workflow_run.step_results if r.status == "completed"
        }
        # Steps we haven't yet completed AND that are in this execute call's
        # scope (the resume() path passes only `remaining`).
        scope_ids = {s.id for s in steps}
        all_steps = steps + [
            s
            for s in definition.steps
            if s.id not in scope_ids and s.id in completed_ids
        ]
        # Above: include already-completed steps from the full definition
        # so that scheduler.ready_steps() can correctly see their depends_on
        # as satisfied. Without this, a resumed workflow's downstream step
        # would never become "ready" because the engine wouldn't know its
        # depends_on were already met.

        # Resume-aware: prefer the model used by the last completed
        # step so a mid-workflow restart doesn't spuriously log a swap.
        previous_model: Optional[str] = next(
            (
                r.model_used
                for r in reversed(workflow_run.step_results)
                if r.status == "completed" and r.model_used
            ),
            None,
        )

        while True:
            # Cooperative cancel point — checked at every tick boundary.
            # In-flight LLM calls in the current tick always complete.
            if self._should_cancel(workflow_run.run_id):
                with state_lock:
                    workflow_run.status = "canceled"
                    workflow_run.completed_at = datetime.utcnow()
                    workflow_run.error = "Run canceled by operator"
                    self._checkpoint(workflow_run)
                self._cancel_set.discard(workflow_run.run_id)
                logger.info(f"Workflow '{definition.id}' canceled at tick boundary")
                return

            ready = [
                s
                for s in scheduler.ready_steps(all_steps, completed_ids)
                if s.id in scope_ids
            ]
            if not ready:
                break  # all scope steps complete (or deadlock — checked below)

            decisions = scheduler.schedule(ready)
            dispatch_ids = {
                d.step_id for d in decisions if not getattr(d, "deferred", False)
            }
            if not dispatch_ids:
                with state_lock:
                    workflow_run.status = "failed"
                    workflow_run.error = f"Scheduler deadlock: arch deferred all {len(ready)} ready steps"
                    workflow_run.completed_at = datetime.utcnow()
                    _resolve_pre_warm_hits(workflow_run)
                    workflow_run.telemetry_summary = _aggregate_telemetry(
                        workflow_run.step_results,
                        workflow_run.pre_warm_events,
                    )
                    self._checkpoint(workflow_run)
                logger.error(
                    f"Workflow '{definition.id}' deadlocked: arch deferred all ready steps"
                )
                return

            dispatch_steps = [s for s in ready if s.id in dispatch_ids]

            # Pre-resolve models for every step we're about to dispatch.
            # Failures here are workflow-level (no point dispatching anything
            # in this tick if one model can't be resolved).
            resolved_models: Dict[str, str] = {}
            resolution_failed_step: Optional[AgentStep] = None
            resolution_error: Optional[str] = None
            for step in dispatch_steps:
                # a2a steps delegate to remote agents and don't need a local
                # model resolved. The composite executors (parallel/loop)
                # resolve their own children's models internally, so the
                # placeholder here is unused. Skip resolution to avoid
                # erroring on a2a-only workflows where no local models exist.
                if step.kind in (
                    "a2a",
                    "parallel",
                    "loop",
                    "orchestrator",
                    "consolidate",
                    "ralph",
                ):
                    resolved_models[step.id] = ""
                    continue
                try:
                    resolved_models[step.id] = self.resolver.resolve(
                        model=step.model,
                        role=step.role,
                        default_role=definition.defaults.role,
                    )
                except Exception as e:
                    resolution_failed_step = step
                    resolution_error = str(e)
                    break

            if resolution_failed_step is not None:
                fail_result = StepResult(
                    step_id=resolution_failed_step.id,
                    status="failed",
                    error=f"Model resolution failed: {resolution_error}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
                with state_lock:
                    workflow_run.step_results.append(fail_result)
                    workflow_run.status = "failed"
                    workflow_run.error = f"Step '{resolution_failed_step.id}' failed: model resolution error"
                    workflow_run.completed_at = datetime.utcnow()
                    _resolve_pre_warm_hits(workflow_run)
                    workflow_run.telemetry_summary = _aggregate_telemetry(
                        workflow_run.step_results,
                        workflow_run.pre_warm_events,
                    )
                    self._checkpoint(workflow_run)
                logger.error(
                    f"Workflow failed at step '{resolution_failed_step.id}': "
                    f"{resolution_error}"
                )
                return

            # Model-swap log only when the tick is a single step (the swap
            # signal is meaningless when multiple models run concurrently).
            if len(dispatch_steps) == 1 and previous_model:
                new_model = resolved_models[dispatch_steps[0].id]
                if previous_model != new_model:
                    logger.info(
                        "Step '%s' triggers model swap: '%s' → '%s' "
                        "(expect unload+reload cost; group same-model steps to amortize).",
                        dispatch_steps[0].id,
                        previous_model,
                        new_model,
                    )

            tick_label = ",".join(s.id for s in dispatch_steps)
            logger.info(
                f"Executing tick [{tick_label}] ({len(dispatch_steps)} step"
                f"{'s' if len(dispatch_steps) != 1 else ''} concurrent)"
            )

            # Dispatch the tick. ThreadPoolExecutor.max_workers caps at
            # len(dispatch_steps) — no benefit to spinning more threads
            # than steps.
            with ThreadPoolExecutor(
                max_workers=len(dispatch_steps),
                thread_name_prefix=f"wf-{workflow_run.run_id[:8]}",
            ) as ex:
                futures = {
                    ex.submit(
                        self._execute_one_step,
                        step,
                        definition,
                        context,
                        workflow_run,
                        resolved_models[step.id],
                    ): step
                    for step in dispatch_steps
                }
                # Phase 5 — kick off pre-warms for the next tick's models
                # NOW, while the current tick's LLM calls are in flight.
                # Fire-and-forget; arch.transition_plan gates safety.
                # Phase 5b — workflow_run + defaults threaded through for
                # event emission and disable_pre_warm opt-out.
                self._fire_pre_warms_for_next_tick(
                    all_steps=all_steps,
                    scope_ids=scope_ids,
                    completed_ids=completed_ids,
                    current_dispatch_steps=dispatch_steps,
                    resolved_models=resolved_models,
                    workflow_run=workflow_run,
                    defaults=definition.defaults,
                )
                for future in as_completed(futures):
                    step = futures[future]
                    try:
                        step_result = future.result()
                    except Exception as e:
                        # _execute_one_step has its own try/except; reaching
                        # here means something deeply unexpected happened.
                        step_result = StepResult(
                            step_id=step.id,
                            status="failed",
                            error=f"Step executor raised: {e}",
                            started_at=datetime.utcnow(),
                            completed_at=datetime.utcnow(),
                        )
                    with state_lock:
                        workflow_run.step_results.append(step_result)
                        self._checkpoint(workflow_run)
                        if step_result.status == "completed":
                            completed_ids.add(step_result.step_id)
                            previous_model = step_result.model_used

            # Tick fully drained. If anything in it failed, stop the run.
            tick_id_set = {s.id for s in dispatch_steps}
            tick_failures = [
                r
                for r in workflow_run.step_results
                if r.step_id in tick_id_set and r.status == "failed"
            ]
            if tick_failures:
                first = tick_failures[0]
                with state_lock:
                    workflow_run.status = "failed"
                    workflow_run.error = (
                        f"Step '{first.step_id}' failed after {first.retries + 1} attempts: "
                        f"{first.error}"
                    )
                    workflow_run.completed_at = datetime.utcnow()
                    _resolve_pre_warm_hits(workflow_run)
                    workflow_run.telemetry_summary = _aggregate_telemetry(
                        workflow_run.step_results,
                        workflow_run.pre_warm_events,
                    )
                    self._checkpoint(workflow_run)
                logger.error(
                    f"Workflow '{definition.id}' failed at step '{first.step_id}'"
                )
                return

        # All scope steps succeeded.
        workflow_run.status = "completed"
        workflow_run.completed_at = datetime.utcnow()
        # Phase 5b — brief wait for in-flight pre-warms so their timing
        # makes it into the run's telemetry. Capped at 500ms — beyond that,
        # the pre-warm is genuinely slow and the operator's better off
        # seeing "completed_at=None" than waiting longer for the report.
        self._wait_for_pre_warms(timeout_ms=500)
        _resolve_pre_warm_hits(workflow_run)
        workflow_run.telemetry_summary = _aggregate_telemetry(
            workflow_run.step_results,
            workflow_run.pre_warm_events,
        )
        total_duration = sum(r.duration_seconds or 0 for r in workflow_run.step_results)
        total_tokens = sum(
            r.token_count.get("total_tokens", 0) for r in workflow_run.step_results
        )
        cold_load_summary = ""
        if (
            workflow_run.telemetry_summary
            and workflow_run.telemetry_summary.cold_load_count > 0
        ):
            cold_load_summary = (
                f", {workflow_run.telemetry_summary.cold_load_count} cold-load"
                f" ({workflow_run.telemetry_summary.total_cold_load_ms / 1000:.1f}s)"
            )
        logger.info(
            f"Workflow '{definition.id}' completed in {total_duration:.1f}s "
            f"({total_tokens} total tokens{cold_load_summary})"
        )

    def _wait_for_pre_warms(self, timeout_ms: int = 500) -> None:
        """Phase 5b — poll the in-flight pre-warm set until empty or timeout.

        Pre-warm worker threads are daemons; they don't block workflow exit.
        But for telemetry accuracy at run-completion, we briefly wait so
        events get their load_duration_ms populated. Capped to avoid
        stalling a fast workflow behind a slow Ollama load.
        """
        import time

        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            with self._pre_warm_lock:
                if not self._pre_warm_inflight:
                    return
            time.sleep(0.02)  # 20 ms poll interval

    def _recently_evicted_models(self, workflow_run: WorkflowRun) -> List[str]:
        """Phase 5.4 — return model names completed within the recency window.

        Walks workflow_run.step_results and returns the unique resolved
        model names whose `completed_at` is within
        `self._page_cache_recency_seconds` of now. Used by
        UnifiedArchitecture.transition_plan to mark `warm_eviction_candidate`
        plans when the next-step's model is likely still in page cache.

        Quiet on missing data — returns [] if step_results is empty or no
        steps have timestamps yet. Order is irrelevant; caller checks
        membership, not position.
        """
        now = datetime.utcnow()
        window = self._page_cache_recency_seconds
        models: Set[str] = set()
        for r in getattr(workflow_run, "step_results", []) or []:
            completed = getattr(r, "completed_at", None)
            model = getattr(r, "model_used", None)
            if not completed or not model:
                continue
            try:
                age = (now - completed).total_seconds()
            except TypeError:
                continue
            if 0 <= age <= window:
                models.add(model)
        return sorted(models)

    def _fire_pre_warms_for_next_tick(
        self,
        all_steps: List[AgentStep],
        scope_ids: Set[str],
        completed_ids: Set[str],
        current_dispatch_steps: List[AgentStep],
        resolved_models: Dict[str, str],
        workflow_run: WorkflowRun,
        defaults: Any,
    ) -> None:
        """Phase 5 — fire background pre-warms for the next tick's models.

        Called after the current tick's LLM calls are dispatched but
        before `as_completed` waits. Looks ahead in the DAG: steps whose
        dependencies are in (completed_ids ∪ current_dispatch_ids) are
        the "next likely tick". For each unique model in that set that
        isn't also in the current dispatch:
          - Ask arch.transition_plan(prev, next) whether pre-warm is safe.
            On NVIDIA single with bandwidth contention the plan says no;
            on unified (page cache) and NVIDIA multi (free GPU) it says yes.
          - If safe AND we haven't already kicked off a pre-warm for this
            model, fire ollama.pre_warm() in a daemon thread.

        Phase 5b: records each dispatch as a PreWarmEvent on the run for
        post-completion hit/miss resolution; honors defaults.disable_pre_warm.

        Fire-and-forget: pre-warm threads are daemons. If the workflow
        completes faster than the pre-warm, the wasted work is bounded
        (one model load).
        """
        import threading

        # Phase 5b — workflow-level opt-out. Operators can disable pre-warm
        # entirely via YAML `defaults.disable_pre_warm: true` (e.g. cold-cache
        # benchmarks, GPU-pressure-sensitive runs).
        if getattr(defaults, "disable_pre_warm", None) is True:
            return

        try:
            from .architecture import _get_current as _get_arch

            arch = _get_arch()
        except Exception:
            return

        current_dispatch_ids = {s.id for s in current_dispatch_steps}
        current_dispatch_models = {
            resolved_models.get(s.id) for s in current_dispatch_steps
        }

        # Find steps that would be ready as soon as the current tick completes.
        next_ready: List[AgentStep] = []
        for s in all_steps:
            if s.id not in scope_ids:
                continue
            if s.id in completed_ids or s.id in current_dispatch_ids:
                continue
            deps = s.depends_on or []
            if all(d in completed_ids or d in current_dispatch_ids for d in deps):
                next_ready.append(s)
        if not next_ready:
            return

        # Pick a stable "previous" anchor for transition_plan. Any step in
        # the current tick works — the plan is about whether the boundary
        # *type* (same-model vs swap) supports pre-warm, not about a
        # specific from-to pair.
        prev_anchor = current_dispatch_steps[0]

        # Phase 1: build the unique to-warm set within this call.
        # Two next-tick steps using the same model dedupe to ONE pre-warm.
        # Without this, fast pre_warm completion could clear the in-flight
        # set between two per-step checks and double-fire.
        to_warm: List[tuple] = []  # (model_name, anchor_next_step)
        seen_models: set = set()
        for next_step in next_ready:
            try:
                next_model = self.resolver.resolve(
                    model=next_step.model,
                    role=next_step.role,
                    default_role=None,
                )
            except Exception:
                continue
            if next_model in current_dispatch_models or next_model in seen_models:
                continue
            seen_models.add(next_model)
            to_warm.append((next_model, next_step))

        # Phase 2: gate each model through arch + in-flight set, then fire.
        for next_model, next_step in to_warm:
            # Skip if a previous tick's pre-warm for this model is still alive.
            with self._pre_warm_lock:
                if next_model in self._pre_warm_inflight:
                    continue

            # Ask the arch whether pre-warm is safe at this boundary.
            # Phase 5.4: pass recently_evicted so UnifiedArchitecture can
            # flag warm_eviction_candidate when the next model was unloaded
            # within the page-cache recency window (still mmap-able cheaply).
            # NVIDIA arches ignore the kwarg (no equivalent cache concept).
            recently_evicted = self._recently_evicted_models(workflow_run)
            try:
                try:
                    plan = arch.transition_plan(
                        prev_anchor, next_step, recently_evicted=recently_evicted
                    )
                except TypeError:
                    # Older arch impls don't accept recently_evicted yet.
                    plan = arch.transition_plan(prev_anchor, next_step)
            except Exception:
                continue
            if not getattr(plan, "pre_warm_next", False):
                continue
            if getattr(plan, "warm_eviction_candidate", False):
                # Page-cache hit expected — log but still fire pre-warm.
                # The pre-warm itself is the trigger that re-mmaps the
                # weights; skipping it would defeat the optimization.
                logger.debug(
                    f"Pre-warm of '{next_model}' is a warm-eviction candidate "
                    "(recent page-cache hit expected)"
                )

            # Mark in-flight; the worker clears it on completion.
            with self._pre_warm_lock:
                self._pre_warm_inflight.add(next_model)

            # Phase 5b — record the dispatch on the run BEFORE firing the
            # thread so the event is checkpoint-visible even if the engine
            # exits before the worker returns. target_gpu_hint is advisory
            # only (Ollama auto-places; per-request GPU pin is not in the
            # /api/generate surface).
            target_gpu = getattr(plan, "pre_warm_target_gpu", None)
            event = PreWarmEvent(
                model=next_model,
                dispatched_at=datetime.utcnow(),
                target_gpu_hint=target_gpu,
            )
            with self._pre_warm_lock:
                workflow_run.pre_warm_events.append(event)

            def _worker(model_to_warm: str, event_ref: PreWarmEvent):
                try:
                    result = self.ollama.pre_warm(model_to_warm)
                    with self._pre_warm_lock:
                        event_ref.completed_at = datetime.utcnow()
                        event_ref.load_duration_ms = result.get("load_duration_ms")
                except Exception as e:
                    logger.warning(f"Pre-warm of '{model_to_warm}' failed: {e}")
                    with self._pre_warm_lock:
                        event_ref.completed_at = datetime.utcnow()
                        event_ref.error = str(e)
                finally:
                    with self._pre_warm_lock:
                        self._pre_warm_inflight.discard(model_to_warm)

            t = threading.Thread(
                target=_worker,
                args=(next_model, event),
                name=f"prewarm-{next_model[:24]}",
                daemon=True,
            )
            t.start()
            logger.info(
                f"Pre-warm dispatched: model='{next_model}' "
                f"(for next-tick step '{next_step.id}')"
            )

    def _execute_one_step(
        self,
        step: AgentStep,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        workflow_run: WorkflowRun,
        resolved_model: str,
        prefix_locked: bool = False,
    ) -> StepResult:
        """Run a single step end-to-end. Extracted from _execute_steps for
        Phase 4b so it can be submitted to a ThreadPoolExecutor.

        Dispatches on `step.kind`:
          * llm      — single LLM call via StepExecutor
          * parallel — fan out to branches + run gather (composite)
          * loop     — run body repeatedly until predicate satisfied
                       or max_iterations reached (composite)
          * a2a      — delegate to an external A2A-protocol agent

        Composite kinds recursively call this method for their children. The
        composite returns ONE aggregated StepResult that summarizes the whole
        sub-tree; per-child telemetry lives in the workspace artifacts on disk.

        Builds the step-scoped hook bus and a fresh StepExecutor (executors
        are cheap; sharing one across threads would risk contaminating
        per-attempt state in retry_with_feedback). Errors propagate to the
        future; the caller synthesizes a failed StepResult.
        """
        if step.kind == "parallel":
            from .engine_executors import parallel as _parallel

            return _parallel.execute(self, step, definition, context, workflow_run)
        if step.kind == "loop":
            from .engine_executors import loop as _loop

            return _loop.execute(self, step, definition, context, workflow_run)
        if step.kind == "a2a":
            from .engine_executors import a2a as _a2a

            return _a2a.execute(self, step, context)
        if step.kind == "orchestrator":
            from .engine_executors import orchestrator as _orchestrator

            return _orchestrator.execute(self, step, definition, context, workflow_run)
        if step.kind == "consolidate":
            from .engine_executors import consolidate as _consolidate

            return _consolidate.execute(self, step, definition, context)
        if step.kind == "ralph":
            from .engine_executors import ralph as _ralph

            return _ralph.execute(self, step, definition, context, workflow_run)

        # kind == "llm" — the default
        step_bus = self._build_step_bus(step)
        step_executor = StepExecutor(
            ollama_service=self.ollama,
            composer=self.composer,
            hook_bus=step_bus,
            model_resolver=self.resolver,
        )
        return step_executor.execute(
            step=step,
            workflow=definition,
            context=context,
            resolved_model=resolved_model,
            defaults=definition.defaults,
            workflow_run=workflow_run,
            prefix_locked=prefix_locked,
        )

    # ── Hook Bus Assembly ──────────────────────────────────────────────

    def _build_step_bus(self, step) -> HookBus:
        """Return a fresh HookBus with default hooks + step-scoped json_schema + YAML-declared hooks."""
        from api.hooks.builtins.token_budget import TokenBudgetHook
        from api.hooks.builtins.output_logger import OutputLoggerHook
        from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
        from api.hooks.builtins.refusal_detector import RefusalDetectorHook
        from api.hooks.builtins.json_schema import JsonSchemaHook

        bus = HookBus()
        # Default hooks
        bus.register(TokenBudgetHook(max_prompt_tokens=3500, reserve_for_output=1024))
        bus.register(OutputLoggerHook(include_prompt=False))
        bus.register(RetryWithFeedbackHook(max_attempts=2, include_example=True))
        bus.register(RefusalDetectorHook(patterns=[], use_family_defaults=True))
        # Step-scoped json_schema (requires output_schema)
        if getattr(step, "output_schema", None):
            bus.register(JsonSchemaHook(schema=step.output_schema, strip_fences=True))
        # YAML-declared per-step hook overrides — safe access (may not be present on v1 steps)
        hooks_block = getattr(step, "hooks", None)
        if hooks_block is not None:
            for stage_name in (
                "before_step",
                "transform_prompt",
                "after_step",
                "validate_output",
                "on_failure",
            ):
                for spec in getattr(hooks_block, stage_name, []) or []:
                    bus.register(self._instantiate_hook(spec, stage_name))
        # Custom hooks auto-discovered from api/hooks/custom/
        custom_dir = self._project_root / "api" / "hooks" / "custom"
        if custom_dir.is_dir():
            bus.discover_and_register(custom_dir, source="custom")
        return bus

    def _instantiate_hook(self, spec, stage):
        """Map a YAML HookSpec into a concrete built-in hook instance."""
        from api.hooks.builtins.json_schema import JsonSchemaHook
        from api.hooks.builtins.refusal_detector import RefusalDetectorHook
        from api.hooks.builtins.retry_with_feedback import RetryWithFeedbackHook
        from api.hooks.builtins.token_budget import TokenBudgetHook
        from api.hooks.builtins.output_logger import OutputLoggerHook
        from api.hooks.builtins.few_shot_injector import FewShotInjectorHook
        from api.hooks.builtins.plugin_tool_invoker import PluginToolInvokerHook
        from api.hooks.builtins.mcp_tool_invoker import MCPToolInvokerHook
        from api.hooks.builtins.analyse_xql_gate import AnalyseXqlGateHook

        factory = {
            "json_schema": JsonSchemaHook,
            "refusal_detector": RefusalDetectorHook,
            "retry_with_feedback": RetryWithFeedbackHook,
            "token_budget": TokenBudgetHook,
            "output_logger": OutputLoggerHook,
            "few_shot_injector": FewShotInjectorHook,
            "plugin_tool_invoker": PluginToolInvokerHook,
            "mcp_tool_invoker": MCPToolInvokerHook,
            "analyse_xql_gate": AnalyseXqlGateHook,
        }.get(spec.name)
        if factory is None:
            raise ValueError(f"Unknown built-in hook: {spec.name}")
        return factory(**spec.config)

    # ── Persist Phase ──────────────────────────────────────────────────

    def _safe_drain_mcp_pool(self, run: WorkflowRun) -> None:
        """Idempotent MCP pool drain. Used by the execute/resume safety
        try/finally to guarantee no warm runners leak when an exception
        escapes ``_execute_steps`` before ``_persist_run`` could drain
        them. ``_persist_run`` calls this same drain at the top, so on
        the normal path this is a cheap no-op (pool returns ``[]`` once
        already drained)."""
        try:
            from .mcp_runner_pool import get_mcp_runner_pool

            pool = get_mcp_runner_pool()
            stats = pool.release_workflow(run.run_id)
            if stats:
                existing = run.mcp_runners or []
                existing_keys = {(s.server_id, s.started_at) for s in existing}
                for s in stats:
                    if (s.server_id, s.started_at) not in existing_keys:
                        existing.append(s)
                run.mcp_runners = existing
        except Exception as e:  # noqa: BLE001
            logger.debug(f"MCP pool safety drain skipped: {e}")

    def _checkpoint(self, run: WorkflowRun) -> None:
        """
        Atomically write the current run.json. Cheap path used after every
        step — only the run state, not artifacts or markdown summary.

        Atomicity matters: a crash during write could otherwise leave a
        truncated run.json that fails to parse on resume. We write to
        run.json.tmp and rename, which is atomic on POSIX.
        """
        run_dir = Path(DATA_DIR) / run.run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = run_dir / "run.json.tmp"
            final_path = run_dir / "run.json"
            with open(tmp_path, "w") as f:
                json.dump(run.model_dump(mode="json"), f, indent=2, default=str)
            os.replace(tmp_path, final_path)
        except OSError as e:
            logger.warning(f"Checkpoint failed for run {run.run_id}: {e}")

    def _persist_run(self, run: WorkflowRun, definition: WorkflowDefinition) -> None:
        """Terminal persist: run.json + per-step artifact JSONs + summary.md."""
        # Phase 2 → 4 (MCP & Skills) — drain any warm MCP runners this run
        # spawned. Subprocesses get terminated and reaped; the returned stats
        # records land on workflow_run.mcp_runners so the aggregation below
        # surfaces them on the dashboard. Idempotent for runs that didn't
        # acquire any runners (the helper returns silently).
        self._safe_drain_mcp_pool(run)

        # Phase 4 (MCP & Skills) — roll per-step extension counts into the
        # run-level totals before we serialize. Idempotent; cheap; runs on
        # every terminal persist (success or failure) so the UI always has
        # a populated rollup to render.
        try:
            from ..models.workflow_models import aggregate_extension_stats

            aggregate_extension_stats(run)
        except Exception as e:  # noqa: BLE001 - never block persist on a rollup error
            logger.debug(f"extension stats rollup skipped: {e}")

        run_dir = Path(DATA_DIR) / run.run_id
        artifacts_dir = run_dir / "artifacts"

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(exist_ok=True)

            # Atomic run.json — same pattern as _checkpoint.
            tmp_path = run_dir / "run.json.tmp"
            run_path = run_dir / "run.json"
            with open(tmp_path, "w") as f:
                json.dump(run.model_dump(mode="json"), f, indent=2, default=str)
            os.replace(tmp_path, run_path)

            for step in definition.steps:
                step_data = run.context.workspace.get(step.id, {})
                if step_data:
                    artifact_path = artifacts_dir / f"{step.id}.json"
                    with open(artifact_path, "w") as f:
                        json.dump(step_data, f, indent=2, default=str)

            summary_path = run_dir / "summary.md"
            with open(summary_path, "w") as f:
                f.write(self._generate_summary(run, definition))

            logger.info(f"Run persisted to {run_dir}")

        except Exception as e:
            logger.error(f"Failed to persist run {run.run_id}: {e}")

    def _generate_summary(
        self, run: WorkflowRun, definition: WorkflowDefinition
    ) -> str:
        """Generate a markdown summary of a workflow run"""
        lines = [
            f"# Workflow Run: {definition.name}",
            "",
            f"- **Run ID**: {run.run_id}",
            f"- **Workflow**: {definition.id} v{definition.version or '0.0'}",
            f"- **Status**: {run.status}",
            f"- **Started**: {run.started_at}",
            f"- **Completed**: {run.completed_at}",
            "",
            "## Steps",
            "",
        ]

        for result in run.step_results:
            step_def = next(
                (s for s in definition.steps if s.id == result.step_id), None
            )
            status_icon = "+" if result.status == "completed" else "x"
            lines.append(
                f"### [{status_icon}] {result.step_id}"
                f"{f' -- {step_def.name}' if step_def else ''}"
            )
            lines.append(f"- Model: {result.model_used}")
            lines.append(
                f"- Duration: {result.duration_seconds:.1f}s"
                if result.duration_seconds
                else "- Duration: N/A"
            )
            lines.append(f"- Tokens: {result.token_count.get('total_tokens', 0)}")
            if result.error:
                lines.append(f"- Error: {result.error}")
            lines.append("")

        if run.error:
            lines.extend(["## Error", "", run.error, ""])

        return "\n".join(lines)

    # ── Utilities ──────────────────────────────────────────────────────

    def list_workflows(self, workflows_dir: str = "./workflows") -> List[Dict]:
        """List all available workflow definitions.

        Scans:
          1. The public workflow directory (workflows_dir / $WORKFLOWS_DIR).
          2. An optional PRIVATE OVERLAY at workflows-private/ (or
             $WORKFLOWS_PRIVATE_DIR). Private definitions can shadow
             public ones with the same id; the private one wins.

        The private overlay is gitignored by default — it's where the
        operator stages high-value, methodology-heavy YAMLs that
        shouldn't ship in the source-available repo. The engine treats
        the two dirs identically once loaded.
        """
        by_id: Dict[str, Dict] = {}

        def _scan(dir_str: str, source_label: str):
            path = Path(dir_str)
            if not path.exists():
                return
            for f in sorted(path.glob("*.yaml")):
                try:
                    defn = self.load(str(f))
                    by_id[defn.id] = {
                        "id": defn.id,
                        "name": defn.name,
                        "description": defn.description,
                        "version": defn.version,
                        "steps": len(defn.steps),
                        "file": str(f),
                        "source": source_label,
                    }
                except Exception as e:
                    logger.warning(f"Skipping invalid workflow {f}: {e}")

        _scan(workflows_dir, "public")
        # Private overlay wins on id collisions.
        private_dir = os.getenv("WORKFLOWS_PRIVATE_DIR", "./workflows-private")
        _scan(private_dir, "private")

        return sorted(by_id.values(), key=lambda w: w.get("id", ""))

    def resolve_workflow_path(
        self,
        workflow_id: str,
        workflows_dir: str = "./workflows",
    ) -> Optional[str]:
        """Return the on-disk path for a workflow id, preferring the
        private overlay over the public directory. None when missing."""
        private_dir = os.getenv("WORKFLOWS_PRIVATE_DIR", "./workflows-private")
        for d in (private_dir, workflows_dir):
            candidate = Path(d) / f"{workflow_id}.yaml"
            if candidate.exists():
                return str(candidate)
        return None

    def get_run(self, run_id: str) -> Optional[Dict]:
        """Load a persisted workflow run by ID"""
        run_path = Path(DATA_DIR) / run_id / "run.json"
        if not run_path.exists():
            return None
        with open(run_path) as f:
            return json.load(f)

    def list_runs(self, limit: int = 20) -> List[Dict]:
        """List recent workflow runs"""
        data_path = Path(DATA_DIR)
        if not data_path.exists():
            return []

        runs = []
        for run_dir in sorted(data_path.iterdir(), reverse=True):
            if run_dir.is_dir():
                run_file = run_dir / "run.json"
                if run_file.exists():
                    try:
                        with open(run_file) as f:
                            data = json.load(f)
                        runs.append(
                            {
                                "run_id": data.get("run_id"),
                                "workflow_id": data.get("workflow_id"),
                                "status": data.get("status"),
                                "started_at": data.get("started_at"),
                                "completed_at": data.get("completed_at"),
                            }
                        )
                    except Exception:
                        pass
            if len(runs) >= limit:
                break

        return runs
