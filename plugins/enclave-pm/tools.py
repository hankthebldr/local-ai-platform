"""enclave-pm — chat/workflow plugin tools for the Enclave project board.

Proposals-only. Every mutation these tools make lands in the project's task log
stamped ``origin:"agent"`` + ``state:"proposed"`` via the SAME service surface
the REST plan-ops router calls (``api.routers.projects``). Nothing an agent does
touches the board until the operator accepts the proposal — there is no
silent-mutation path through this plugin.

These are in-process thin wrappers, not HTTP calls: workflow steps and external
agents reach the PM contract through the standard ``plugin_tools_called``
surface without needing a master key or a live socket.
"""

import json as _json


def pm_plan_apply(project_id: str, ops_json) -> dict:
    """Submit a plan-ops array against a project (lands PROPOSED).

    Args:
        project_id: target project id.
        ops_json: a JSON string (or already-parsed list) of plan-ops.

    Returns:
        {proposal_id, ops_accepted, errors, pending_count} — or {"error": ...}.
    """
    from api.routers.projects import ProposalCapError, apply_plan

    try:
        ops = _json.loads(ops_json) if isinstance(ops_json, str) else ops_json
    except (ValueError, TypeError) as exc:
        return {"error": f"ops_json is not valid JSON: {exc}"}
    try:
        return apply_plan(project_id, ops, source={"agent": "enclave-pm"})
    except ProposalCapError as exc:
        return {"error": str(exc), "code": "pending_cap"}
    except ValueError as exc:
        return {"error": str(exc)}


def pm_list_tasks(project_id: str) -> dict:
    """Return the current (accepted) tasks on the project board."""
    from api.routers.projects import _read_tasks

    return {"project_id": project_id, "tasks": _read_tasks(project_id)}


def pm_log_run(project_id: str, run_id: str, label: str = None) -> dict:
    """Record a run ref against a project (origin:"agent")."""
    from api.routers.projects import _append_run_ref

    try:
        return _append_run_ref(
            project_id, run_id=run_id, label=label, origin="agent"
        )
    except ValueError as exc:
        return {"error": str(exc)}
