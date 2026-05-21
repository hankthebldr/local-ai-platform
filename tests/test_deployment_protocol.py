"""Tests for the Deployment protocol + supporting types.

Phase 1 / Task 1.1 of architecture-aware orchestration.
See docs/plans/2026-05-19-architecture-aware-orchestration-implementation.md
"""

from __future__ import annotations


from api.services.deployment import (
    DeploymentMode,
    ConfigValidationResult,
    ResourceLimits,
)


class TestDeploymentMode:
    def test_enum_string_values(self):
        assert DeploymentMode.DMG_NATIVE.value == "dmg_native"
        assert DeploymentMode.CONTAINER.value == "container"
        assert DeploymentMode.HOST_NATIVE.value == "host_native"

    def test_deployment_mode_membership(self):
        # Three supported modes; this is the closed set.
        assert len(list(DeploymentMode)) == 3


class TestConfigValidationResult:
    def test_clean_result(self):
        result = ConfigValidationResult(warnings=[], errors=[])
        assert result.is_clean is True
        assert result.has_errors is False
        assert result.has_warnings is False

    def test_warnings_only(self):
        result = ConfigValidationResult(
            warnings=[{"code": "missing_num_thread", "message": "..."}],
            errors=[],
        )
        assert result.is_clean is False
        assert result.has_warnings is True
        assert result.has_errors is False

    def test_errors_block_run(self):
        result = ConfigValidationResult(
            warnings=[],
            errors=[
                {"code": "missing_sched_spread", "message": "required for multi-GPU"}
            ],
        )
        assert result.has_errors is True
        assert result.is_clean is False


class TestResourceLimits:
    def test_unlimited(self):
        # No cgroup, no enforced limit
        limits = ResourceLimits(memory_gb=None, cpu_cores=None, source="unlimited")
        assert limits.memory_gb is None
        assert limits.source == "unlimited"

    def test_cgroup_v2_limit(self):
        limits = ResourceLimits(memory_gb=32.0, cpu_cores=8.0, source="cgroup_v2")
        assert limits.memory_gb == 32.0
        assert limits.source == "cgroup_v2"

    def test_psutil_host_total(self):
        limits = ResourceLimits(memory_gb=96.0, cpu_cores=24.0, source="psutil_host")
        assert limits.source == "psutil_host"
