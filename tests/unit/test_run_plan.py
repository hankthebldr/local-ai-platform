from api.models.workflow_models import WorkflowDefinition, WorkflowPlan
from api.services.run_plan import PlanBuilder


def _defn():
    return WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "wf",
            "steps": [
                {
                    "id": "a",
                    "name": "Triage",
                    "system_prompt": "triage",
                    "outputs": ["x"],
                },
                {
                    "id": "b",
                    "name": "Report",
                    "system_prompt": "report",
                    "outputs": ["y"],
                    "depends_on": ["a"],
                },
            ],
        }
    )


def test_baseline_projects_top_level_steps():
    plan = PlanBuilder.baseline_from_definition(_defn())
    assert isinstance(plan, WorkflowPlan)
    assert plan.revision == 1
    assert [(i.id, i.title, i.status, i.origin) for i in plan.items] == [
        ("a", "Triage", "pending", "dag"),
        ("b", "Report", "pending", "dag"),
    ]


def test_mutation_helpers_and_child_add():
    plan = PlanBuilder.baseline_from_definition(_defn())
    PlanBuilder.mark_item(plan, "a", "in_progress", updated_seq=5)
    assert next(i for i in plan.items if i.id == "a").status == "in_progress"
    PlanBuilder.add_child(
        plan,
        parent_id="a",
        item_id="a::w1",
        title="worker-1",
        origin="orchestrator",
        updated_seq=6,
    )
    child = next(i for i in plan.items if i.id == "a::w1")
    assert child.parent_id == "a" and child.origin == "orchestrator"
