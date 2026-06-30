"""Build and emit WorkflowPlan snapshots. The plan is a projection over the
event log: the current plan is the last plan.updated event (reconstruct_from_log)."""

from typing import Optional

from ..models.run_event import EventType
from ..models.workflow_models import PlanItem, WorkflowDefinition, WorkflowPlan


class PlanBuilder:
    @staticmethod
    def baseline_from_definition(definition: WorkflowDefinition) -> WorkflowPlan:
        items = [
            PlanItem(
                id=s.id,
                title=s.name or s.id,
                status="pending",
                origin="dag",
                step_ref=s.id,
            )
            for s in definition.steps
        ]
        return WorkflowPlan(goal=definition.id, revision=1, items=items)

    @staticmethod
    def mark_item(
        plan: WorkflowPlan, item_id: str, status: str, updated_seq: int
    ) -> None:
        for item in plan.items:
            if item.id == item_id:
                item.status = status  # type: ignore[assignment]
                item.updated_seq = updated_seq
                return

    @staticmethod
    def add_child(
        plan: WorkflowPlan,
        parent_id: str,
        item_id: str,
        title: str,
        origin: str,
        updated_seq: int,
        detail: Optional[str] = None,
    ) -> None:
        if any(i.id == item_id for i in plan.items):
            return
        plan.items.append(
            PlanItem(
                id=item_id,
                title=title,
                status="in_progress",
                origin=origin,  # type: ignore[arg-type]
                parent_id=parent_id,
                detail=detail,
                updated_seq=updated_seq,
            )
        )

    @staticmethod
    def emit(bus, run_id: str, plan: WorkflowPlan, step_id: Optional[str] = None):
        """Bump revision and publish a full plan.updated snapshot."""
        plan.revision += 1
        return bus.publish(
            run_id,
            EventType.PLAN_UPDATED,
            {"revision": plan.revision, "plan": plan.model_dump(mode="json")},
            step_id=step_id,
        )

    @staticmethod
    def reconstruct_from_log(bus, run_id: str) -> Optional[WorkflowPlan]:
        last = None
        for ev in bus.read_log(run_id):
            if ev.type == EventType.PLAN_UPDATED:
                last = ev
        if last is None:
            return None
        return WorkflowPlan.model_validate(last.data["plan"])
