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


def _aggregate_telemetry(
    step_results: List[StepResult],
) -> Optional[RunTelemetrySummary]:
    """Roll up per-step Phase-2 telemetry into a per-run summary.

    Returns None when no step has telemetry populated — preserves the
    "no observability data" signal rather than reporting all zeros.
    """
    has_any_telemetry = any(
        r.load_duration_ms is not None or r.eval_duration_ms is not None
        for r in step_results
    )
    if not has_any_telemetry:
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
    return summary


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
        # Hook bus default is built per-step in _build_step_bus()
        self._project_root = project_root
        # Cancel set — run_ids that have received a cancel request. The
        # execution loop checks this between steps; in-flight LLM calls
        # complete normally (cooperative cancel, not pre-emptive). This
        # is a process-local set, so a multi-worker uvicorn deployment
        # needs to honour cancels via the persisted run.status field
        # instead — the loop checks both.
        self._cancel_set: set = set()
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

        for step in definition.steps:
            # Hook-provided virtual inputs: a before_step plugin_tool_invoker
            # writes its result to `<step.id>.<store_as>`, which the step is
            # then allowed to reference as one of its own inputs.
            hooks_block = getattr(step, "hooks", None)
            if hooks_block is not None:
                for spec in getattr(hooks_block, "before_step", []) or []:
                    if getattr(spec, "name", None) == "plugin_tool_invoker":
                        store_as = (spec.config or {}).get("store_as")
                        if store_as:
                            available_outputs.add(f"{step.id}.{store_as}")

            # Check all inputs are available
            for input_ref in step.inputs:
                if input_ref not in available_outputs:
                    # Allow seed.* references even if we don't know exact keys
                    if input_ref.startswith("seed.") and seed_keys is None:
                        continue
                    errors.append(
                        f"Step '{step.id}' input '{input_ref}' has no producer. "
                        f"Available: {sorted(available_outputs)}"
                    )

            # Register this step's outputs as available
            for output_key in step.outputs:
                available_outputs.add(f"{step.id}.{output_key}")

        # Check for duplicate step IDs
        step_ids = [s.id for s in definition.steps]
        dupes = [sid for sid in step_ids if step_ids.count(sid) > 1]
        if dupes:
            errors.append(f"Duplicate step IDs: {set(dupes)}")

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

        self._execute_steps(workflow_run, definition, context, definition.steps)

        # Final terminal persist (full artifacts + summary).
        self._persist_run(workflow_run, definition)
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

        self._execute_steps(workflow_run, definition, workflow_run.context, remaining)

        self._persist_run(workflow_run, definition)
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
                    workflow_run.telemetry_summary = _aggregate_telemetry(
                        workflow_run.step_results
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
                    workflow_run.telemetry_summary = _aggregate_telemetry(
                        workflow_run.step_results
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
                    workflow_run.telemetry_summary = _aggregate_telemetry(
                        workflow_run.step_results
                    )
                    self._checkpoint(workflow_run)
                logger.error(
                    f"Workflow '{definition.id}' failed at step '{first.step_id}'"
                )
                return

        # All scope steps succeeded.
        workflow_run.status = "completed"
        workflow_run.completed_at = datetime.utcnow()
        workflow_run.telemetry_summary = _aggregate_telemetry(workflow_run.step_results)
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

    def _execute_one_step(
        self,
        step: AgentStep,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        workflow_run: WorkflowRun,
        resolved_model: str,
    ) -> StepResult:
        """Run a single step end-to-end. Extracted from _execute_steps for
        Phase 4b so it can be submitted to a ThreadPoolExecutor.

        Builds the step-scoped hook bus and a fresh StepExecutor (executors
        are cheap; sharing one across threads would risk contaminating
        per-attempt state in retry_with_feedback). Errors propagate to the
        future; the caller synthesizes a failed StepResult.
        """
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
        from api.hooks.builtins.analyse_xql_gate import AnalyseXqlGateHook

        factory = {
            "json_schema": JsonSchemaHook,
            "refusal_detector": RefusalDetectorHook,
            "retry_with_feedback": RetryWithFeedbackHook,
            "token_budget": TokenBudgetHook,
            "output_logger": OutputLoggerHook,
            "few_shot_injector": FewShotInjectorHook,
            "plugin_tool_invoker": PluginToolInvokerHook,
            "analyse_xql_gate": AnalyseXqlGateHook,
        }.get(spec.name)
        if factory is None:
            raise ValueError(f"Unknown built-in hook: {spec.name}")
        return factory(**spec.config)

    # ── Persist Phase ──────────────────────────────────────────────────

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
