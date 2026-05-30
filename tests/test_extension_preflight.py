"""Phase 5 — declarative pre-flight: tools[] / skills[] / required_*.

Coverage:
  - ToolRef requires exactly one of plugin/mcp, in dotted form
  - WorkflowDefaults defaults: required_plugins/required_mcps/skill_injection
  - check_workflow: walks every leaf step
  - check_step: tool/skill resolution; missing plugin/MCP → error,
    missing skill → warning, unreachable MCP → warning
  - workflow_engine.validate raises on extension errors; STRICT promotes
    warnings to errors
"""

from __future__ import annotations

from typing import Set

import pytest

from api.models.workflow_models import (
    AgentStep,
    ToolRef,
    WorkflowDefaults,
    WorkflowDefinition,
)
from api.services.extension_preflight import (
    ExtensionPreflightResult,
    check_step,
    check_workflow,
)

# ── Lightweight fakes for the two services ────────────────────────────


class FakePluginService:
    def __init__(self, plugins=None):
        # plugins = {plugin_id: {"tools": {tool_id}, "skills": {skill_id}}}
        self._plugins = plugins or {}

    def has_plugin(self, plugin_id):
        return plugin_id in self._plugins

    def has_tool(self, plugin_id, tool_id):
        return tool_id in self._plugins.get(plugin_id, {}).get("tools", set())

    def has_skill(self, plugin_id, skill_id):
        return skill_id in self._plugins.get(plugin_id, {}).get("skills", set())

    def list_plugins(self):
        return [{"id": pid} for pid in self._plugins]


class FakeMCPService:
    def __init__(self, servers=None, unreachable=None):
        # servers = {server_id: {"tools": {tool_name}}}
        self._servers = servers or {}
        self._unreachable: Set[str] = set(unreachable or ())

    def has_server(self, server_id):
        return server_id in self._servers

    def is_reachable(self, server_id):
        return server_id in self._servers and server_id not in self._unreachable

    def has_tool(self, server_id, tool_name):
        return tool_name in self._servers.get(server_id, {}).get("tools", set())


def _llm_step(step_id="s", **kw) -> AgentStep:
    return AgentStep(
        id=step_id,
        name=step_id,
        system_prompt="test",
        outputs=["out"],
        **kw,
    )


# ── ToolRef ───────────────────────────────────────────────────────────


def test_tool_ref_requires_exactly_one_kind():
    with pytest.raises(ValueError, match="exactly one of 'plugin' or 'mcp'"):
        ToolRef()
    with pytest.raises(ValueError, match="only one of 'plugin' or 'mcp'"):
        ToolRef(plugin="a.b", mcp="c.d")


def test_tool_ref_requires_dotted_form():
    with pytest.raises(ValueError, match="<id>.<member>"):
        ToolRef(plugin="missing-dot")
    with pytest.raises(ValueError, match="<id>.<member>"):
        ToolRef(mcp=".leading-dot")
    with pytest.raises(ValueError, match="<id>.<member>"):
        ToolRef(plugin="trailing-dot.")


def test_tool_ref_accepts_valid_refs():
    r = ToolRef(plugin="xdm-toolkit.lookup_xdm_path")
    assert r.plugin == "xdm-toolkit.lookup_xdm_path"
    r2 = ToolRef(mcp="filesystem-local.read_file")
    assert r2.mcp == "filesystem-local.read_file"


# ── Schema defaults ───────────────────────────────────────────────────


def test_workflow_defaults_extension_fields():
    d = WorkflowDefaults()
    assert d.required_plugins == []
    assert d.required_mcps == []
    assert d.skill_injection == "auto"


def test_workflow_defaults_accepts_extension_overrides():
    d = WorkflowDefaults(
        required_plugins=["xdm-toolkit"],
        required_mcps=["filesystem-local"],
        skill_injection="explicit",
    )
    assert d.required_plugins == ["xdm-toolkit"]
    assert d.required_mcps == ["filesystem-local"]
    assert d.skill_injection == "explicit"


def test_workflow_defaults_rejects_unknown_skill_injection():
    with pytest.raises(ValueError):
        WorkflowDefaults(skill_injection="ad-hoc")


def test_agent_step_defaults_no_tools_no_skills():
    s = _llm_step()
    assert s.tools == []
    assert s.skills == []
    assert s.archetype is None


# ── Per-step checks ───────────────────────────────────────────────────


def test_check_step_with_no_extensions_is_clean():
    result = check_step(_llm_step(), FakePluginService(), FakeMCPService())
    assert not result.has_errors and not result.has_warnings


def test_check_step_flags_missing_plugin_tool():
    step = _llm_step(tools=[ToolRef(plugin="xdm.lookup")])
    plugins = FakePluginService()  # nothing registered
    result = check_step(step, plugins, FakeMCPService())
    assert result.has_errors
    assert result.plugin_errors[0]["code"] == "plugin_missing"
    assert result.plugin_errors[0]["step_id"] == step.id


def test_check_step_flags_plugin_present_tool_missing():
    step = _llm_step(tools=[ToolRef(plugin="xdm.lookup")])
    plugins = FakePluginService({"xdm": {"tools": {"other_tool"}, "skills": set()}})
    result = check_step(step, plugins, FakeMCPService())
    assert result.has_errors
    assert result.plugin_errors[0]["code"] == "plugin_tool_not_found"


def test_check_step_flags_unregistered_mcp():
    step = _llm_step(tools=[ToolRef(mcp="fs.read")])
    result = check_step(step, FakePluginService(), FakeMCPService())
    assert result.has_errors
    assert result.mcp_errors[0]["code"] == "mcp_not_registered"


def test_check_step_unreachable_mcp_is_warning_not_error():
    """A registered MCP that's not running at validate time gets a warning;
    the pool will spawn it at acquire time."""
    step = _llm_step(tools=[ToolRef(mcp="fs.read")])
    mcp = FakeMCPService(
        servers={"fs": {"tools": {"read"}}},
        unreachable={"fs"},
    )
    result = check_step(step, FakePluginService(), mcp)
    # Unreachable → no error for has_tool (we can't refute), no warning at
    # step scope (workflow-level required_mcps emits the reachability
    # warning).
    assert not result.has_errors


def test_check_step_flags_mcp_tool_not_found():
    step = _llm_step(tools=[ToolRef(mcp="fs.read")])
    mcp = FakeMCPService(servers={"fs": {"tools": {"write"}}})  # read missing
    result = check_step(step, FakePluginService(), mcp)
    assert result.has_errors
    assert result.mcp_errors[0]["code"] == "mcp_tool_not_found"


def test_check_step_skill_missing_is_warning():
    step = _llm_step(skills=["general-skills.concise-writer"])
    result = check_step(step, FakePluginService(), FakeMCPService())
    assert not result.has_errors  # only warnings
    assert result.has_warnings
    assert result.skill_warnings[0]["code"] == "skill_plugin_missing"


def test_check_step_malformed_skill_ref_is_warning():
    step = _llm_step(skills=["not-dotted"])
    result = check_step(step, FakePluginService(), FakeMCPService())
    assert result.skill_warnings[0]["code"] == "skill_ref_malformed"


def test_check_step_skill_in_present_plugin():
    step = _llm_step(skills=["gs.concise"])
    plugins = FakePluginService({"gs": {"tools": set(), "skills": {"concise"}}})
    result = check_step(step, plugins, FakeMCPService())
    assert not result.has_errors and not result.has_warnings


# ── Workflow-level walk ───────────────────────────────────────────────


def test_check_workflow_required_plugin_missing():
    wf = WorkflowDefinition(
        id="w",
        name="W",
        defaults=WorkflowDefaults(required_plugins=["xdm-toolkit"]),
        steps=[_llm_step()],
    )
    result = check_workflow(wf, FakePluginService(), FakeMCPService())
    assert result.has_errors
    assert any(
        e["code"] == "plugin_missing" and e["scope"] == "workflow"
        for e in result.plugin_errors
    )


def test_check_workflow_required_mcp_unreachable_is_warning():
    wf = WorkflowDefinition(
        id="w",
        name="W",
        defaults=WorkflowDefaults(required_mcps=["fs"]),
        steps=[_llm_step()],
    )
    mcp = FakeMCPService(servers={"fs": {"tools": set()}}, unreachable={"fs"})
    result = check_workflow(wf, FakePluginService(), mcp)
    assert not result.has_errors
    assert any(
        w["code"] == "mcp_unreachable" and w["scope"] == "workflow"
        for w in result.mcp_warnings
    )


def test_check_workflow_recurses_into_parallel_branches():
    """A parallel branch's tools must also be validated."""
    branch_a = _llm_step(step_id="b1", tools=[ToolRef(plugin="missing.tool")])
    branch_b = _llm_step(step_id="b2")
    gather = _llm_step(step_id="g")
    parent = AgentStep(
        id="p",
        name="p",
        kind="parallel",
        outputs=["out"],
        branches=[branch_a, branch_b],
        gather=gather,
    )
    wf = WorkflowDefinition(id="w", name="W", steps=[parent])
    result = check_workflow(wf, FakePluginService(), FakeMCPService())
    assert any(
        e["code"] == "plugin_missing" and e["step_id"] == "b1"
        for e in result.plugin_errors
    )


def test_check_workflow_recurses_into_loop_body():
    from api.models.workflow_models import LoopTermination

    body_step = _llm_step(step_id="b", tools=[ToolRef(mcp="fs.read")])
    loop = AgentStep(
        id="lp",
        name="lp",
        kind="loop",
        outputs=["out"],
        body=[body_step],
        max_iterations=2,
        until=LoopTermination(gate="b.out == 'done'"),
    )
    wf = WorkflowDefinition(id="w", name="W", steps=[loop])
    result = check_workflow(wf, FakePluginService(), FakeMCPService())
    assert any(
        e["code"] == "mcp_not_registered" and e["step_id"] == "b"
        for e in result.mcp_errors
    )


# ── Result merge + helpers ────────────────────────────────────────────


def test_result_merge_combines_all_buckets():
    a = ExtensionPreflightResult()
    a.plugin_errors.append({"code": "x"})
    b = ExtensionPreflightResult()
    b.mcp_warnings.append({"code": "y"})
    a.merge(b)
    assert a.has_errors and a.has_warnings
    assert len(a.plugin_errors) == 1 and len(a.mcp_warnings) == 1


def test_flatten_errors_humanizes():
    r = ExtensionPreflightResult()
    r.plugin_errors.append(
        {"code": "plugin_missing", "plugin_id": "p", "step_id": "s1"}
    )
    r.mcp_errors.append(
        {
            "code": "mcp_tool_not_found",
            "server_id": "fs",
            "tool": "read",
            "step_id": "s2",
        }
    )
    lines = r.flatten_errors()
    assert any("plugin plugin_missing: p" in line for line in lines)
    assert any("mcp mcp_tool_not_found: fs.read" in line for line in lines)


# ── WorkflowEngine.validate integration ───────────────────────────────


def test_engine_validate_passes_with_no_extensions(tmp_path, monkeypatch):
    """Workflows that declare no tools/skills/required_* still validate
    cleanly — the pre-flight is purely additive."""
    from api.exceptions import WorkflowValidationError
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    engine = WorkflowEngine(OllamaService())
    wf = WorkflowDefinition(id="w", name="W", steps=[_llm_step()])
    try:
        engine.validate(wf)
    except WorkflowValidationError as e:
        pytest.fail(f"bare workflow should validate cleanly: {e}")


def test_engine_validate_raises_on_extension_errors(monkeypatch):
    from api.exceptions import WorkflowValidationError
    from api.services import extension_preflight
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    # Inject fakes so the pre-flight doesn't touch the real services.
    monkeypatch.setattr(
        extension_preflight, "_default_plugin_service", lambda: FakePluginService()
    )
    monkeypatch.setattr(
        extension_preflight, "_default_mcp_service", lambda: FakeMCPService()
    )

    engine = WorkflowEngine(OllamaService())
    wf = WorkflowDefinition(
        id="w",
        name="W",
        defaults=WorkflowDefaults(required_plugins=["xdm-toolkit"]),
        steps=[_llm_step()],
    )
    with pytest.raises(WorkflowValidationError, match="plugin_missing"):
        engine.validate(wf)


def test_engine_validate_strict_promotes_warnings(monkeypatch):
    from api.exceptions import WorkflowValidationError
    from api.services import extension_preflight
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    monkeypatch.setattr(
        extension_preflight,
        "_default_plugin_service",
        lambda: FakePluginService(),
    )
    monkeypatch.setattr(
        extension_preflight,
        "_default_mcp_service",
        lambda: FakeMCPService(servers={"fs": {"tools": set()}}, unreachable={"fs"}),
    )
    monkeypatch.setenv("STRICT_VALIDATION", "true")

    engine = WorkflowEngine(OllamaService())
    wf = WorkflowDefinition(
        id="w",
        name="W",
        defaults=WorkflowDefaults(required_mcps=["fs"]),
        steps=[_llm_step()],
    )
    with pytest.raises(WorkflowValidationError, match=r"\[strict\].*mcp_unreachable"):
        engine.validate(wf)


def test_engine_validate_stores_extension_result_for_router(monkeypatch):
    from api.services import extension_preflight
    from api.services.workflow_engine import WorkflowEngine
    from api.services.ollama_service import OllamaService

    monkeypatch.setattr(
        extension_preflight,
        "_default_plugin_service",
        lambda: FakePluginService(),
    )
    monkeypatch.setattr(
        extension_preflight,
        "_default_mcp_service",
        lambda: FakeMCPService(servers={"fs": {"tools": set()}}, unreachable={"fs"}),
    )

    engine = WorkflowEngine(OllamaService())
    wf = WorkflowDefinition(
        id="w",
        name="W",
        defaults=WorkflowDefaults(required_mcps=["fs"]),
        steps=[_llm_step()],
    )
    engine.validate(wf)
    ext = engine._last_extension_result  # noqa: SLF001
    assert ext is not None
    assert ext.has_warnings and not ext.has_errors
    assert ext.mcp_warnings[0]["code"] == "mcp_unreachable"
