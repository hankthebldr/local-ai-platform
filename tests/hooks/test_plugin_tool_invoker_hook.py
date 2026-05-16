"""Unit tests for PluginToolInvokerHook."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.hooks.builtins.plugin_tool_invoker import (
    PluginToolInvokerHook,
    _substitute_item,
    set_plugin_service,
)
from api.models.workflow_models import WorkflowContext
from api.services.hook_bus import HookContext


@pytest.fixture
def fake_service():
    service = MagicMock()
    set_plugin_service(service)
    yield service
    # Reset back to lazy/None so other tests aren't poisoned.
    set_plugin_service(None)


def _ctx_with_workspace(seed=None, workspace=None, step_id="validate_and_revise"):
    context = WorkflowContext(seed=seed or {}, workspace=workspace or {})
    workflow_run = SimpleNamespace(context=context)
    step = SimpleNamespace(id=step_id)
    return HookContext(workflow=workflow_run, step=step, prompt=None), context


def test_name_and_stage():
    hook = PluginToolInvokerHook(plugin_id="p", tool_id="t", store_as="r")
    assert hook.name == "plugin_tool_invoker"
    assert hook.stage == "before_step"


def test_single_shot_invocation_writes_workspace(fake_service):
    fake_service.call_tool.return_value = {"verdict": "READY-TO-DEPLOY"}
    hook = PluginToolInvokerHook(
        plugin_id="xdm-toolkit",
        tool_id="validate_xql",
        store_as="validator_report",
        params_from={"rule": "write_rule.rule"},
    )
    ctx, context = _ctx_with_workspace(
        workspace={"write_rule": {"rule": "[MODEL: dataset=x] alter foo = 1"}},
    )

    result = hook(ctx)

    assert result.action == "continue"
    fake_service.call_tool.assert_called_once_with(
        "xdm-toolkit", "validate_xql", {"rule": "[MODEL: dataset=x] alter foo = 1"}
    )
    assert context.get_workspace("validate_and_revise", "validator_report") == {
        "verdict": "READY-TO-DEPLOY"
    }


def test_for_each_invokes_per_item(fake_service):
    fake_service.call_tool.side_effect = [
        {"verdict": "READY-TO-DEPLOY"},
        {"verdict": "NEEDS-FIXES"},
    ]
    hook = PluginToolInvokerHook(
        plugin_id="xdm-toolkit",
        tool_id="validate_xql",
        store_as="validator_reports",
        for_each="write_rules.rules",
        param_template={"rule": "{{ item.rule }}"},
    )
    ctx, context = _ctx_with_workspace(
        workspace={
            "write_rules": {
                "rules": [
                    {"cluster_id": "auth", "rule": "RULE_A"},
                    {"cluster_id": "net", "rule": "RULE_B"},
                ]
            }
        },
        step_id="validate_all",
    )

    result = hook(ctx)

    assert result.action == "continue"
    assert fake_service.call_tool.call_count == 2
    assert fake_service.call_tool.call_args_list[0].args == (
        "xdm-toolkit",
        "validate_xql",
        {"rule": "RULE_A"},
    )
    assert fake_service.call_tool.call_args_list[1].args == (
        "xdm-toolkit",
        "validate_xql",
        {"rule": "RULE_B"},
    )
    reports = context.get_workspace("validate_all", "validator_reports")
    assert reports == [
        {"verdict": "READY-TO-DEPLOY"},
        {"verdict": "NEEDS-FIXES"},
    ]


def test_failure_returns_fail_action_with_feedback(fake_service):
    fake_service.call_tool.side_effect = RuntimeError("boom")
    hook = PluginToolInvokerHook(
        plugin_id="p",
        tool_id="t",
        store_as="r",
        params_from={"x": "seed.x"},
    )
    ctx, _ = _ctx_with_workspace(seed={"x": 1})

    result = hook(ctx)

    assert result.action == "fail"
    assert "boom" in (result.feedback or "")


def test_idempotent_when_workspace_already_populated(fake_service):
    """Re-dispatch must not double-invoke the tool."""
    fake_service.call_tool.return_value = {"verdict": "READY-TO-DEPLOY"}
    hook = PluginToolInvokerHook(
        plugin_id="p",
        tool_id="t",
        store_as="r",
        params_from={"rule": "seed.rule"},
    )
    ctx, context = _ctx_with_workspace(seed={"rule": "RULE"})
    hook(ctx)
    hook(ctx)
    assert fake_service.call_tool.call_count == 1


def test_substitute_item_nested_paths():
    assert _substitute_item("{{ item.rule }}", {"rule": "X"}) == "X"
    assert _substitute_item("{{ item.a.b }}", {"a": {"b": 7}}) == 7
    assert _substitute_item({"k": "{{ item.x }}"}, {"x": "v"}) == {"k": "v"}
    assert _substitute_item(["a", "{{ item.x }}"], {"x": "Y"}) == ["a", "Y"]


def test_for_each_rejects_non_list(fake_service):
    hook = PluginToolInvokerHook(
        plugin_id="p",
        tool_id="t",
        store_as="r",
        for_each="seed.thing",
        param_template={"x": "{{ item }}"},
    )
    ctx, _ = _ctx_with_workspace(seed={"thing": "not-a-list"})
    result = hook(ctx)
    assert result.action == "fail"
    assert "list" in (result.feedback or "").lower()
