"""
Workflow Engine — Load, validate, and execute multi-agent workflows

Orchestrates sequential step execution with three-layer context management.
Integrates with ModelResolver for role-based model selection and
StepExecutor for individual step execution with retry logic.
"""

import ast
import json
import os
import re
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


# Whitelist of AST node types allowed in a loop `until.gate` expression after
# dotted refs are substituted out. This keeps gate evaluation from being a
# generic eval() — only comparison/boolean/literal logic survives the walk.
_SAFE_GATE_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.In,
    ast.NotIn,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
)

_GATE_REF_RE = re.compile(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+\b")


def _evaluate_gate(gate_expr: str, context: WorkflowContext) -> bool:
    """Safely evaluate a loop termination gate against the workspace.

    The gate is a small boolean expression. Dotted refs (e.g. `critic.approved`)
    are resolved against the workspace before evaluation; the residual
    expression is parsed with the `ast` module and rejected unless every node
    is in `_SAFE_GATE_NODES`. No attribute access, no function calls, no
    subscripts — just literals, names, comparisons, and boolean composition.

    Returns the boolean result. Raises ValueError on parse/eval failure so the
    caller can surface a clean engine-level error.
    """
    refs = sorted(set(_GATE_REF_RE.findall(gate_expr)))
    ref_to_var: Dict[str, str] = {}
    sub_expr = gate_expr
    for i, ref in enumerate(refs):
        var = f"__gate_{i}"
        ref_to_var[ref] = var
        sub_expr = re.sub(rf"\b{re.escape(ref)}\b", var, sub_expr)

    eval_locals: Dict[str, Any] = {}
    for ref, var in ref_to_var.items():
        eval_locals[var] = context.resolve_input(ref)

    try:
        tree = ast.parse(sub_expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"gate expression has invalid syntax: {e}")

    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_GATE_NODES):
            raise ValueError(
                f"gate expression uses disallowed construct: {type(node).__name__}"
            )

    try:
        return bool(
            eval(
                compile(tree, "<loop-gate>", "eval"), {"__builtins__": {}}, eval_locals
            )
        )
    except Exception as e:
        raise ValueError(f"gate evaluation raised: {e}")


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
                for spec in getattr(hooks_block, "before_step", []) or []:
                    if getattr(spec, "name", None) == "plugin_tool_invoker":
                        store_as = (spec.config or {}).get("store_as")
                        if store_as:
                            available.add(f"{step.id}.{store_as}")

            for input_ref in step.inputs:
                if input_ref not in available:
                    if input_ref.startswith("seed.") and seed_keys is None:
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
                if step.kind in ("a2a", "parallel", "loop"):
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
            return self._execute_parallel_step(step, definition, context, workflow_run)
        if step.kind == "loop":
            return self._execute_loop_step(step, definition, context, workflow_run)
        if step.kind == "a2a":
            return self._execute_a2a_step(step, context)

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
        )

    # ── Composite step executors (kind=parallel, kind=loop) ───────────

    def _dispatch_branches(
        self,
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
            ThreadPoolExecutor up to execution.max_concurrency. Note that
            the daemon-side _LLM_SEMAPHORE serializes Ollama calls when
            MAX_CONCURRENT_LLM=1 — the workflow asks for concurrency, the
            daemon decides whether it can grant it.

          * Sequential (single_model_pseudo_parallel):
            Branches run in declared order, single-threaded. Trade-off:
            no wall-clock parallelism, but the model stays loaded across
            branches and Ollama's prompt cache survives between calls
            (per ~70% latency reduction for prefix-heavy workflows on
            single 30B+ models on CPU — see spec §3.3).

        Returns a {branch_id: StepResult} mapping in both cases. Failures
        are returned as failed StepResults (caller decides what to do).
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        branch_results: Dict[str, StepResult] = {}
        execution_cfg = parent.execution
        max_concurrency = execution_cfg.max_concurrency if execution_cfg else 4

        if mode == "single_model_pseudo_parallel":
            logger.info(
                f"Parallel step '{parent.id}' dispatching "
                f"{len(parent.branches)} branch(es) sequentially "
                f"(mode=single_model_pseudo_parallel)"
            )
            for branch in parent.branches:
                try:
                    res = self._execute_one_step(
                        branch,
                        definition,
                        context,
                        workflow_run,
                        branch_models[branch.id],
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
                    self._execute_one_step,
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

    def _execute_parallel_step(
        self,
        parent: AgentStep,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        workflow_run: WorkflowRun,
    ) -> StepResult:
        """Run a fan-out / gather composite.

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

        When all branches resolve, the gather step runs synchronously and its
        outputs are materialized into the parent's workspace namespace.
        """
        agg = StepResult(
            step_id=parent.id, status="running", started_at=datetime.utcnow()
        )
        execution_cfg = parent.execution
        declared_mode = (
            execution_cfg.mode if execution_cfg else "multi_model_concurrent"
        )
        failure_policy = execution_cfg.failure_policy if execution_cfg else "fail_fast"

        # Pre-resolve a model for each branch. Failures here are workflow-level —
        # we never start any branch if one can't be resolved.
        branch_models: Dict[str, str] = {}
        for branch in parent.branches:
            if branch.kind == "llm":
                try:
                    branch_models[branch.id] = self.resolver.resolve(
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
                # Nested composite branches (rare in phase 1, but the validator
                # already accepts them — recursive _execute_one_step handles it).
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
        # concurrently — surface this so operators don't expect speedup that
        # the deployment can't deliver.
        if effective_mode == "single_model_concurrent":
            try:
                from .ollama_service import MAX_CONCURRENT_LLM

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

        branch_results = self._dispatch_branches(
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

        failed_branches = [
            b for b, r in branch_results.items() if r.status != "completed"
        ]
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
            gather_model = self.resolver.resolve(
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

        gather_res = self._execute_one_step(
            parent.gather, definition, context, workflow_run, gather_model
        )
        agg.token_count["prompt_tokens"] += gather_res.token_count.get(
            "prompt_tokens", 0
        )
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

    def _execute_loop_step(
        self,
        parent: AgentStep,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        workflow_run: WorkflowRun,
    ) -> StepResult:
        """Run a refine-until-good loop.

        Each iteration runs every body step in order. After the body, the
        `until` predicate (a boolean expression over the latest workspace) is
        evaluated. If satisfied the loop terminates and the last body step's
        outputs are positionally mapped onto the parent's declared outputs.
        If max_iterations is hit without satisfaction, on_max_iterations decides
        whether to emit the best-so-far state or fail.
        """
        agg = StepResult(
            step_id=parent.id, status="running", started_at=datetime.utcnow()
        )
        iter_count = 0
        satisfied = False
        last_body_step = parent.body[-1]

        for iteration in range(parent.max_iterations):
            iter_count = iteration + 1
            logger.info(
                f"Loop '{parent.id}' iteration {iter_count}/{parent.max_iterations}"
            )

            for body_step in parent.body:
                # Each body step needs its own model resolution. Composite bodies
                # recurse through _execute_one_step which handles its own resolution.
                if body_step.kind == "llm":
                    try:
                        body_model = self.resolver.resolve(
                            model=body_step.model,
                            role=body_step.role,
                            default_role=definition.defaults.role,
                        )
                    except Exception as e:
                        agg.status = "failed"
                        agg.error = (
                            f"Loop body step '{body_step.id}' model resolution "
                            f"failed on iteration {iter_count}: {e}"
                        )
                        agg.completed_at = datetime.utcnow()
                        agg.duration_seconds = (
                            agg.completed_at - agg.started_at
                        ).total_seconds()
                        logger.error(agg.error)
                        return agg
                else:
                    body_model = ""

                body_res = self._execute_one_step(
                    body_step, definition, context, workflow_run, body_model
                )
                agg.token_count["prompt_tokens"] += body_res.token_count.get(
                    "prompt_tokens", 0
                )
                agg.token_count["completion_tokens"] += body_res.token_count.get(
                    "completion_tokens", 0
                )
                agg.token_count["total_tokens"] = (
                    agg.token_count["prompt_tokens"]
                    + agg.token_count["completion_tokens"]
                )
                agg.model_used = body_res.model_used

                if body_res.status != "completed":
                    agg.status = "failed"
                    agg.error = (
                        f"Loop body step '{body_step.id}' failed on "
                        f"iteration {iter_count}: {body_res.error}"
                    )
                    agg.completed_at = datetime.utcnow()
                    agg.duration_seconds = (
                        agg.completed_at - agg.started_at
                    ).total_seconds()
                    logger.error(agg.error)
                    return agg

            # After the body, evaluate the gate.
            try:
                satisfied = _evaluate_gate(parent.until.gate, context)
            except Exception as e:
                agg.status = "failed"
                agg.error = (
                    f"Loop '{parent.id}' gate evaluation failed on "
                    f"iteration {iter_count}: {e}"
                )
                agg.completed_at = datetime.utcnow()
                agg.duration_seconds = (
                    agg.completed_at - agg.started_at
                ).total_seconds()
                logger.error(agg.error)
                return agg

            if satisfied:
                logger.info(
                    f"Loop '{parent.id}' gate satisfied after iteration {iter_count}"
                )
                break

        # Map the last body step's outputs onto the parent's declared outputs.
        # Validator guarantees every parent output key is produced by the
        # last body step.
        last_ws = context.workspace.get(last_body_step.id, {})
        for parent_key in parent.outputs:
            context.set_workspace(parent.id, parent_key, last_ws.get(parent_key))

        if not satisfied and parent.until.on_max_iterations == "fail":
            agg.status = "failed"
            agg.error = (
                f"Loop '{parent.id}' hit max_iterations={parent.max_iterations} "
                f"without satisfying gate '{parent.until.gate}'"
            )
            agg.completed_at = datetime.utcnow()
            agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
            logger.error(agg.error)
            return agg

        agg.status = "completed"
        agg.completed_at = datetime.utcnow()
        agg.duration_seconds = (agg.completed_at - agg.started_at).total_seconds()
        agg.retries = iter_count - 1  # repurpose: iterations beyond the first
        logger.info(
            f"Loop '{parent.id}' completed in {agg.duration_seconds:.1f}s "
            f"({iter_count} iteration(s){', gate satisfied' if satisfied else ', emit_best'})"
        )
        return agg

    def _execute_a2a_step(
        self,
        step: AgentStep,
        context: WorkflowContext,
    ) -> StepResult:
        """Delegate to an external A2A-protocol agent.

        Flow:
          1. Resolve declared inputs against the workflow context
          2. Fetch the remote AgentCard, validate the skill exists
          3. POST tasks/send, then poll tasks/get until terminal
          4. Map artifacts onto declared outputs and write to workspace

        Returns one StepResult; token counts stay at zero (the remote agent
        owns its own model billing). The step's `model_used` field records
        the remote skill in `agent_url::skill_id` form so operators can see
        which agent ran the step at a glance.
        """
        from .a2a_client import A2AClient, A2AClientError

        result = StepResult(
            step_id=step.id, status="running", started_at=datetime.utcnow()
        )
        result.model_used = f"a2a:{step.skill}@{step.agent_card_url}"

        resolved_inputs = {ref: context.resolve_input(ref) for ref in step.inputs}
        resolved_inputs = {k: v for k, v in resolved_inputs.items() if v is not None}

        logger.info(
            f"A2A step '{step.id}' delegating to skill '{step.skill}' at "
            f"{step.agent_card_url}"
        )

        client = A2AClient()
        try:
            outputs, _task = client.call_skill(
                agent_card_url=step.agent_card_url,
                skill_id=step.skill,
                resolved_inputs=resolved_inputs,
                declared_outputs=step.outputs,
                auth=step.auth,
                timeout=step.timeout,
            )
        except A2AClientError as exc:
            result.status = "failed"
            result.error = str(exc)
            result.completed_at = datetime.utcnow()
            result.duration_seconds = (
                result.completed_at - result.started_at
            ).total_seconds()
            logger.error(f"A2A step '{step.id}' failed: {exc}")
            return result
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error = f"A2A step raised: {exc}"
            result.completed_at = datetime.utcnow()
            result.duration_seconds = (
                result.completed_at - result.started_at
            ).total_seconds()
            logger.exception(f"A2A step '{step.id}' raised")
            return result

        for key, value in outputs.items():
            context.set_workspace(step.id, key, value)

        result.status = "completed"
        result.completed_at = datetime.utcnow()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        logger.info(
            f"A2A step '{step.id}' completed in {result.duration_seconds:.1f}s "
            f"({len([v for v in outputs.values() if v is not None])} of "
            f"{len(step.outputs)} outputs populated)"
        )
        return result

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
