#!/usr/bin/env python3
"""Tests for the tier-3 OpenShell sandbox backend + its opt-in detection.

The real OpenShell gateway is alpha and not present in CI, so the subprocess
boundary is mocked. These tests pin the contract Enclave relies on: the
SandboxBackend Protocol shape, the CodeExecSpec→policy mapping (the real
egress allowlist the container tier punts on), result projection, fail-safe
behavior, and the opt-in registration gate.
"""

from __future__ import annotations

import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.services.sandbox import CodeExecSpec, SandboxBackend
from api.services.sandbox_impl.openshell import OpenShellSandbox


@pytest.fixture
def scratch():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _spec(scratch, **kw):
    base = dict(language="python", code="print('hi')", scratch_path=scratch)
    base.update(kw)
    return CodeExecSpec(**base)


def test_satisfies_protocol():
    assert isinstance(OpenShellSandbox(), SandboxBackend)


def test_capabilities_tier3_with_allowlist():
    caps = OpenShellSandbox().capabilities()
    assert caps.isolation_tier == 3
    # The differentiator vs tier-2 container: a real allowlist network mode.
    assert "allowlist" in caps.network_modes
    assert "none" in caps.network_modes


def test_policy_none_denies_network(scratch):
    sb = OpenShellSandbox()
    policy = sb._render_policy(_spec(scratch, network="none"))
    assert "mode: none" in policy
    assert "block_cloud: true" in policy  # inference privacy router always on


def test_policy_allowlist_lists_local_inference(scratch, monkeypatch):
    monkeypatch.setenv("OPENSHELL_EGRESS_ALLOWLIST", "localhost:11434,localhost:8000")
    sb = OpenShellSandbox()
    policy = sb._render_policy(_spec(scratch, network="allowlist"))
    assert "mode: allowlist" in policy
    assert "- localhost:11434" in policy
    assert "- localhost:8000" in policy


def test_execute_success_projects_result(scratch):
    sb = OpenShellSandbox()
    fake = SimpleNamespace(returncode=0, stdout="hello\n", stderr="")
    with patch(
        "api.services.sandbox_impl.openshell.subprocess.run", return_value=fake
    ) as m:
        res = sb.execute(_spec(scratch, code="print('hello')"))
    assert res.exit_code == 0
    assert res.stdout == "hello\n"
    assert res.tier_used == 3
    assert res.violations == []
    # The entry + policy files are written but excluded from files_produced.
    assert "__entry__.py" not in res.files_produced
    assert "__openshell_policy__.yaml" not in res.files_produced
    # The invocation passed our generated policy + mounted the scratch as /work.
    argv = m.call_args[0][0]
    assert "--policy" in argv and "--mount" in argv
    assert any(a.endswith(":/work:rw") for a in argv)


def test_execute_timeout_is_contained(scratch):
    import subprocess as _sp

    sb = OpenShellSandbox()
    with patch(
        "api.services.sandbox_impl.openshell.subprocess.run",
        side_effect=_sp.TimeoutExpired(cmd="openshell", timeout=1),
    ):
        res = sb.execute(_spec(scratch, timeout_s=1))
    assert res.exit_code == -9
    assert "timeout exceeded" in res.violations
    assert res.tier_used == 3


def test_execute_missing_binary_fails_safe(scratch):
    sb = OpenShellSandbox()
    with patch(
        "api.services.sandbox_impl.openshell.subprocess.run",
        side_effect=FileNotFoundError(),
    ):
        res = sb.execute(_spec(scratch))
    assert res.exit_code == -1
    assert "openshell unavailable" in res.violations


# ── Detection gating ────────────────────────────────────────────────────


def _registry_names():
    from api.services.sandbox_detection import detect_sandboxes

    return {b.name for b in detect_sandboxes().backends()}


def test_not_registered_without_optin(monkeypatch):
    monkeypatch.delenv("ENCLAVE_ENABLE_OPENSHELL", raising=False)
    assert "openshell" not in _registry_names()


def test_registered_when_optin_and_present(monkeypatch):
    monkeypatch.setenv("ENCLAVE_ENABLE_OPENSHELL", "true")
    with (
        patch(
            "api.services.sandbox_detection.shutil.which",
            return_value="/usr/bin/openshell",
        ),
        patch.object(OpenShellSandbox, "ping", return_value=(True, "openshell 0.0.57")),
    ):
        names = _registry_names()
    assert "openshell" in names


def test_optin_but_probe_fails_skips(monkeypatch):
    monkeypatch.setenv("ENCLAVE_ENABLE_OPENSHELL", "true")
    # which() returns truthy for openshell; ping() fails → not registered.
    with (
        patch(
            "api.services.sandbox_detection.shutil.which",
            side_effect=lambda b: "/usr/bin/" + b,
        ),
        patch.object(OpenShellSandbox, "ping", return_value=(False, "no gateway")),
    ):
        names = _registry_names()
    assert "openshell" not in names
