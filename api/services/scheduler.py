"""
Workflow Scheduler — Phase 4 (DAG scheduling facade).

Wraps Architecture.schedule_ready() and Architecture.feasible() into a
single entry point that the workflow_engine and the /schedule-preview
router can both call. The actual scheduling logic lives on each arch
impl (api/services/arch_impl/*); this module is responsible for:

  - Computing the ready set at each tick from the DAG's depends_on
  - Threading the per-arch scheduling decisions back to the caller
  - Validate-time feasibility checks for each topological island
  - Producing a structured preview the operator can inspect

Phase 4a (this file) ships the facade + the preview path. Phase 4b
will replace the sequential `for step in steps` loop in workflow_engine
with the scheduler's tick-by-tick output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from ..logging_config import logger
from ..models.workflow_models import AgentStep, WorkflowDefinition


@dataclass
class FeasibilityIssue:
    """A workflow step that the current architecture can't run."""

    step_id: str
    est_size_gb: Optional[float]
    arch_budget_gb: float
    reason: str


@dataclass
class SchedulePreview:
    """The full per-tick schedule the engine would produce on the
    current architecture. Read-only — used by the schedule-preview
    endpoint and Phase 4b's parallel dispatcher."""

    ticks: List[Dict[str, Any]]
    feasibility_issues: List[FeasibilityIssue]
    arch_name: str
    notes: List[str]


class Scheduler:
    """Facade over Architecture.schedule_ready() + .feasible().

    Stateless — safe to instantiate per request. Holds a reference to the
    current Architecture singleton so the scheduler decisions reflect the
    real hardware (NVIDIA single-GPU schedules differently than apple
    unified, etc.).
    """

    # Phase 4.4 — default max times a single step can be deferred before
    # the scheduler raises capacity_starvation. 60 ticks at typical 1s tick
    # cadence is a minute of "this step can't run on this hardware" before
    # the operator gets a clear error rather than an infinite defer.
    DEFAULT_MAX_DEFER_TICKS = 60

    def __init__(
        self, arch: Any = None, max_defer_ticks: int = DEFAULT_MAX_DEFER_TICKS
    ):
        # Lazy default: pull the singleton if no override passed in. When
        # detection didn't run (tests, degraded boots), fall back to
        # UnknownArchitecture so schedule() still returns a usable
        # head-dispatched/rest-deferred decision rather than [] (which
        # the engine would treat as deadlock).
        if arch is None:
            try:
                from .architecture import _get_current

                arch = _get_current()
            except Exception:
                from .architecture import UnknownArchitecture

                arch = UnknownArchitecture()
        self.arch = arch
        self.max_defer_ticks = max_defer_ticks
        # Phase 4.4 — per-step defer counter, keyed by step.id. Incremented
        # every time the arch returns deferred=True for the step; cleared
        # when the step finally dispatches (the engine's responsibility
        # via clear_defer(step_id) — non-strict; counter is best-effort).
        self._defer_counts: Dict[str, int] = {}

    # ── ready-set computation ────────────────────────────────────────────

    def ready_steps(
        self,
        steps: List[AgentStep],
        completed_step_ids: Set[str],
    ) -> List[AgentStep]:
        """Return every step whose depends_on is fully satisfied and that
        hasn't already completed.

        A step with no `depends_on` is ready as soon as it hasn't run.
        Steps with depends_on become ready when every dependency id is in
        `completed_step_ids`.
        """
        ready: List[AgentStep] = []
        for step in steps:
            if step.id in completed_step_ids:
                continue
            deps = step.depends_on or []
            if all(dep in completed_step_ids for dep in deps):
                ready.append(step)
        return ready

    # ── arch delegation ──────────────────────────────────────────────────

    def schedule(self, ready: List[AgentStep]) -> List[Any]:
        """Delegate to the arch impl's `schedule_ready(ready_steps)`.

        Returns ScheduleDecision dataclasses. When no architecture is
        available (detection failed), returns an empty list — Phase 4b's
        execution loop falls back to sequential dispatch in that case.

        Phase 4.4: each decision is post-processed to track defer counts.
        Steps that defer more than `max_defer_ticks` times have their
        decision annotated with `error_code = "capacity_starvation"` and
        `error_message`, so the engine can promote the defer into a
        ClassifiedError-shaped failure rather than letting the workflow
        spin forever on a step that can't fit.
        """
        if self.arch is None:
            logger.debug("Scheduler: no arch; returning empty schedule")
            return []
        decisions = self.arch.schedule_ready(ready)

        # Phase 4.4 — defer accounting
        for d in decisions:
            step_id = getattr(d, "step_id", None)
            if step_id is None:
                continue
            if getattr(d, "deferred", False):
                self._defer_counts[step_id] = self._defer_counts.get(step_id, 0) + 1
                if self._defer_counts[step_id] >= self.max_defer_ticks:
                    # Annotate the decision with starvation. Engine reads
                    # these attributes; existing arch impls don't set them,
                    # so the check is "if any decision has error_code".
                    try:
                        setattr(d, "error_code", "capacity_starvation")
                        setattr(
                            d,
                            "error_message",
                            f"step '{step_id}' deferred {self._defer_counts[step_id]} times "
                            f"(max {self.max_defer_ticks}); arch cannot place it",
                        )
                    except (AttributeError, TypeError):
                        # Some decision types may be frozen dataclasses.
                        # Surface the starvation via logs instead — the
                        # engine still has the defer count to act on.
                        logger.error(
                            f"Scheduler: step '{step_id}' starved after "
                            f"{self._defer_counts[step_id]} defers "
                            f"(arch cannot annotate decision)"
                        )
            else:
                # Step dispatched — reset its defer counter.
                self._defer_counts.pop(step_id, None)
        return decisions

    def clear_defer(self, step_id: str) -> None:
        """Reset the defer counter for a step.

        Engines that pre-empt scheduling decisions (e.g. retry with
        different model) should call this when the step's identity
        effectively resets.
        """
        self._defer_counts.pop(step_id, None)

    @property
    def defer_counts(self) -> Dict[str, int]:
        """Read-only view of the current defer counts. Mainly for telemetry."""
        return dict(self._defer_counts)

    # ── validate-time feasibility ────────────────────────────────────────

    def validate_feasibility(
        self, definition: WorkflowDefinition
    ) -> List[FeasibilityIssue]:
        """For each step in the workflow, ask the arch whether it fits.

        Phase 4a treats each step as its own island (matches the sequential
        engine's reality). When `est_size_gb` is None on every step, returns
        an empty list — feasibility is a no-op until the operator opts in
        with explicit sizes or Phase 4b auto-derives them from MODEL_REGISTRY.
        """
        if self.arch is None:
            return []
        if all(s.est_size_gb is None for s in definition.steps):
            return []
        issues: List[FeasibilityIssue] = []
        for step in definition.steps:
            if step.est_size_gb is None:
                continue
            result = self.arch.feasible([step])
            if not getattr(result, "fits", True):
                issues.append(
                    FeasibilityIssue(
                        step_id=step.id,
                        est_size_gb=step.est_size_gb,
                        arch_budget_gb=getattr(self.arch, "total_memory_gb", 0.0),
                        reason=getattr(result, "reason", "exceeds arch budget"),
                    )
                )
        return issues

    # ── full DAG preview ─────────────────────────────────────────────────

    def preview(self, definition: WorkflowDefinition) -> SchedulePreview:
        """Walk the DAG tick by tick and produce the full schedule the
        engine would run. Stops when no progress is possible (deadlock)
        or all steps are complete.
        """
        completed: Set[str] = set()
        ticks: List[Dict[str, Any]] = []
        notes: List[str] = []
        arch_name = getattr(getattr(self.arch, "name", None), "value", "unknown")

        max_ticks = len(definition.steps) + 1  # one tick per step in worst case
        tick_no = 0
        while len(completed) < len(definition.steps) and tick_no < max_ticks:
            tick_no += 1
            ready = self.ready_steps(definition.steps, completed)
            if not ready:
                notes.append(
                    "deadlock at tick %d: no ready steps remain but %d steps still pending"
                    % (tick_no, len(definition.steps) - len(completed))
                )
                break
            decisions = self.schedule(ready)
            decisions_payload = [_decision_to_dict(d) for d in decisions]
            ticks.append(
                {
                    "tick": tick_no,
                    "ready_step_ids": [s.id for s in ready],
                    "decisions": decisions_payload,
                }
            )
            # Advance: complete every non-deferred step in this tick's
            # decisions. Sequential arch impls return one non-deferred head
            # and defer the rest; multi-GPU may return several at once.
            advanced_any = False
            for d in decisions_payload:
                if not d.get("deferred"):
                    completed.add(d["step_id"])
                    advanced_any = True
            if not advanced_any:
                notes.append(
                    "tick %d: arch deferred every ready step — preview cannot advance"
                    % tick_no
                )
                break

        return SchedulePreview(
            ticks=ticks,
            feasibility_issues=self.validate_feasibility(definition),
            arch_name=arch_name,
            notes=notes,
        )


def _decision_to_dict(d: Any) -> Dict[str, Any]:
    """ScheduleDecision -> plain dict for the API response.

    Tolerates either a dataclass (has __dataclass_fields__) or a Pydantic
    model — the protocol declares ScheduleDecision but each arch impl is
    free to return its own dataclass shape.
    """
    if hasattr(d, "model_dump"):
        return d.model_dump()
    if hasattr(d, "__dict__"):
        return {k: v for k, v in d.__dict__.items() if not k.startswith("_")}
    return {"step_id": getattr(d, "step_id", None)}
