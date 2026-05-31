"""
Extension pre-flight — validate-time plugin / MCP / skill reachability.

The workflow validator (``WorkflowEngine.validate``) walks every leaf step
recursively (top-level + parallel branches + loop body + ralph body +
orchestrator workers + parallel gather) and feeds each into ``check_step``.
The workflow-level ``required_plugins`` and ``required_mcps`` are checked
once via ``check_workflow``.

Result shape
------------
Each check emits dicts with a stable ``code`` so the UI and run records can
group failures. ``ExtensionPreflightResult.merge`` combines results
across the recursive walk. ``has_errors`` / ``has_warnings`` drive whether
``WorkflowEngine.validate`` raises.

The lenient/strict toggle is the ``STRICT_VALIDATION`` env var (consumed by
the caller, not the checker — we always report warnings vs. errors
separately and let the caller decide).
"""

from __future__ import annotations

from typing import Iterable, List

from pydantic import BaseModel, Field

from ..models.workflow_models import AgentStep, WorkflowDefinition


class ExtensionPreflightResult(BaseModel):
    """Accumulated extension-validation findings.

    Errors block the run; warnings surface in the validate response and
    only block when ``STRICT_VALIDATION=true``.
    """

    plugin_errors: List[dict] = Field(default_factory=list)
    plugin_warnings: List[dict] = Field(default_factory=list)
    mcp_errors: List[dict] = Field(default_factory=list)
    mcp_warnings: List[dict] = Field(default_factory=list)
    skill_warnings: List[dict] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.plugin_errors or self.mcp_errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.plugin_warnings or self.mcp_warnings or self.skill_warnings)

    def merge(self, other: "ExtensionPreflightResult") -> None:
        self.plugin_errors.extend(other.plugin_errors)
        self.plugin_warnings.extend(other.plugin_warnings)
        self.mcp_errors.extend(other.mcp_errors)
        self.mcp_warnings.extend(other.mcp_warnings)
        self.skill_warnings.extend(other.skill_warnings)

    def flatten_errors(self) -> List[str]:
        """Human-readable error lines for WorkflowValidationError messages."""
        out: List[str] = []
        for e in self.plugin_errors:
            out.append(
                f"plugin {e['code']}: {e.get('plugin_id', '?')}"
                + (f".{e['tool']}" if e.get("tool") else "")
                + (f" (step {e['step_id']})" if e.get("step_id") else "")
            )
        for e in self.mcp_errors:
            out.append(
                f"mcp {e['code']}: {e.get('server_id', '?')}"
                + (f".{e['tool']}" if e.get("tool") else "")
                + (f" (step {e['step_id']})" if e.get("step_id") else "")
            )
        return out


def _split_dotted(ref: str) -> tuple[str, str]:
    """Split ``"<owner>.<member>"``. Caller has already verified the form
    (Pydantic validator on ToolRef + checks in this module)."""
    owner, _, member = ref.partition(".")
    return owner, member


# ── Step iteration: walk every leaf recursively ────────────────────────


def _leaf_steps(step: AgentStep) -> Iterable[AgentStep]:
    """Yield every concrete step the validator should inspect.

    Composite kinds (parallel / loop / orchestrator / ralph) don't carry
    tools/skills of their own — their *children* do. We yield the parent
    too (for archetype validation; tools/skills lists are typically empty
    on the parent), then recurse into branches, body, gather, workers.
    """
    yield step
    for branch in step.branches or []:
        yield from _leaf_steps(branch)
    if step.gather is not None:
        yield from _leaf_steps(step.gather)
    for body_step in step.body or []:
        yield from _leaf_steps(body_step)
    for worker in (step.workers or {}).values():
        yield from _leaf_steps(worker)


# ── Workflow-level checks ──────────────────────────────────────────────


def check_workflow(
    workflow: WorkflowDefinition,
    plugin_service=None,
    mcp_service=None,
) -> ExtensionPreflightResult:
    """Top-level: required_plugins / required_mcps + per-step walk."""
    result = ExtensionPreflightResult()
    plugin_service = plugin_service or _default_plugin_service()
    mcp_service = mcp_service or _default_mcp_service()

    defaults = workflow.defaults
    for pid in defaults.required_plugins:
        if not _plugin_present(plugin_service, pid):
            result.plugin_errors.append(
                {"code": "plugin_missing", "plugin_id": pid, "scope": "workflow"}
            )

    for sid in defaults.required_mcps:
        if not _mcp_registered(mcp_service, sid):
            result.mcp_errors.append(
                {"code": "mcp_not_registered", "server_id": sid, "scope": "workflow"}
            )
        elif not _mcp_reachable(mcp_service, sid):
            result.mcp_warnings.append(
                {"code": "mcp_unreachable", "server_id": sid, "scope": "workflow"}
            )

    for top in workflow.steps:
        for leaf in _leaf_steps(top):
            result.merge(check_step(leaf, plugin_service, mcp_service))

    return result


# ── Per-step checks ────────────────────────────────────────────────────


def check_step(
    step: AgentStep,
    plugin_service=None,
    mcp_service=None,
) -> ExtensionPreflightResult:
    """Verify each declared tool/skill on the step resolves."""
    result = ExtensionPreflightResult()
    plugin_service = plugin_service or _default_plugin_service()
    mcp_service = mcp_service or _default_mcp_service()

    for tool in step.tools:
        if tool.plugin:
            pid, tname = _split_dotted(tool.plugin)
            if not _plugin_present(plugin_service, pid):
                result.plugin_errors.append(
                    {
                        "code": "plugin_missing",
                        "plugin_id": pid,
                        "tool": tname,
                        "step_id": step.id,
                    }
                )
            elif not _plugin_has_tool(plugin_service, pid, tname):
                result.plugin_errors.append(
                    {
                        "code": "plugin_tool_not_found",
                        "plugin_id": pid,
                        "tool": tname,
                        "step_id": step.id,
                    }
                )
        if tool.mcp:
            sid, tname = _split_dotted(tool.mcp)
            if not _mcp_registered(mcp_service, sid):
                result.mcp_errors.append(
                    {
                        "code": "mcp_not_registered",
                        "server_id": sid,
                        "tool": tname,
                        "step_id": step.id,
                    }
                )
            elif not _mcp_has_tool(mcp_service, sid, tname):
                # tool-not-found is an error: a step that declared a missing
                # tool would 100% fail at runtime, no operator value in
                # leaving it as a warning.
                result.mcp_errors.append(
                    {
                        "code": "mcp_tool_not_found",
                        "server_id": sid,
                        "tool": tname,
                        "step_id": step.id,
                    }
                )

    for skill_ref in step.skills:
        if "." not in skill_ref:
            result.skill_warnings.append(
                {
                    "code": "skill_ref_malformed",
                    "skill_ref": skill_ref,
                    "step_id": step.id,
                    "message": "expected '<plugin_id>.<skill_id>'",
                }
            )
            continue
        pid, skid = _split_dotted(skill_ref)
        if not _plugin_present(plugin_service, pid):
            # Skills are softer than tools — a missing plugin only earns a
            # warning here, since the workflow may degrade gracefully when
            # no skill matches at runtime.
            result.skill_warnings.append(
                {
                    "code": "skill_plugin_missing",
                    "plugin_id": pid,
                    "skill_id": skid,
                    "step_id": step.id,
                }
            )
        elif not _plugin_has_skill(plugin_service, pid, skid):
            result.skill_warnings.append(
                {
                    "code": "skill_not_found",
                    "plugin_id": pid,
                    "skill_id": skid,
                    "step_id": step.id,
                }
            )

    return result


# ── Service adapters (late-imported to avoid circulars in tests) ───────


def _default_plugin_service():
    from .plugin_service import PluginService

    svc = PluginService()
    svc.scan_plugins()
    return svc


def _default_mcp_service():
    from .mcp_service import get_mcp_service

    return get_mcp_service()


def _plugin_present(plugin_service, plugin_id: str) -> bool:
    """True if the plugin is discovered in either layer."""
    has = getattr(plugin_service, "has_plugin", None)
    if has is not None:
        return bool(has(plugin_id))
    # Backwards-compat fallback: walk list_plugins().
    return any(p.get("id") == plugin_id for p in plugin_service.list_plugins())


def _plugin_has_tool(plugin_service, plugin_id: str, tool_id: str) -> bool:
    has = getattr(plugin_service, "has_tool", None)
    if has is not None:
        return bool(has(plugin_id, tool_id))
    return False


def _plugin_has_skill(plugin_service, plugin_id: str, skill_id: str) -> bool:
    has = getattr(plugin_service, "has_skill", None)
    if has is not None:
        return bool(has(plugin_id, skill_id))
    return False


def _mcp_registered(mcp_service, server_id: str) -> bool:
    has = getattr(mcp_service, "has_server", None)
    if has is not None:
        return bool(has(server_id))
    return mcp_service.get_server(server_id) is not None


def _mcp_reachable(mcp_service, server_id: str) -> bool:
    """Lenient: failure to handshake is a warning, not an error.

    Production deployments often have MCPs that aren't running until a step
    needs them; we don't want validate to refuse a workflow just because
    nobody's started the MCP yet. The pool will spawn it at acquire time.
    """
    is_reach = getattr(mcp_service, "is_reachable", None)
    if is_reach is None:
        return True  # can't tell; assume reachable
    try:
        return bool(is_reach(server_id))
    except Exception:  # noqa: BLE001
        return False


def _mcp_has_tool(mcp_service, server_id: str, tool_name: str) -> bool:
    """Verify the MCP exposes ``tool_name``. Requires a successful handshake
    against the server to populate the tools cache; if the server is
    unreachable we can't refute the tool's existence — return True so the
    operator sees the reachability warning instead of a phantom missing-tool
    error."""
    has = getattr(mcp_service, "has_tool", None)
    if has is None:
        return True
    if not _mcp_reachable(mcp_service, server_id):
        return True
    return bool(has(server_id, tool_name))
