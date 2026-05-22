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

    def __init__(self, arch: Any = None):
        # Lazy default: pull the singleton if no override passed in.
        # Tests can inject a mock arch directly.
        if arch is None:
            try:
                from .architecture import _get_current

                arch = _get_current()
            except Exception:
                arch = None
        self.arch = arch

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
        """
        if self.arch is None:
            logger.debug("Scheduler: no arch; returning empty schedule")
            return []
        return self.arch.schedule_ready(ready)

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
