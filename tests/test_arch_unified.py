"""Tests for UnifiedArchitecture (apple_unified + cpu_x86).

Phase 1 / Task 1.2.
"""

from __future__ import annotations

import pytest

from tests.mocks.arch.mock_apple_unified import patch_apple_unified
from tests.mocks.arch.mock_cpu_x86 import patch_cpu_x86


class TestAppleUnified:
    def test_detect_capabilities(self):
        with patch_apple_unified(total_gb=96.0):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            assert arch.name.value == "apple_unified"
            assert arch.memory_model == "unified"
            assert arch.pool_count == 1
            assert arch.total_memory_gb == 96.0
            assert arch.per_pool_gb == [96.0]
            assert arch.warm_reload_cost_class == "cheap"
            assert arch.failure_class == "soft_degradation"
            assert arch.supports_placement is False
            assert arch.bandwidth_estimate_gbps > 0  # arch-specific estimate

    def test_snapshot_ok_when_low_usage(self):
        with patch_apple_unified(total_gb=96.0, used_gb=10.0, swap_active=False):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "ok"
            assert snap.per_pool[0]["free_gb"] == pytest.approx(86.0, abs=0.1)
            assert snap.swap_active is False

    def test_snapshot_critical_when_pressure_and_swap(self):
        # 90% used + swap active = critical
        with patch_apple_unified(total_gb=96.0, used_gb=88.0, swap_active=True):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "critical"
            assert snap.swap_active is True

    def test_snapshot_warning_when_pressure_no_swap(self):
        # 90% used + no swap = warning (degrading but not critical)
        with patch_apple_unified(total_gb=96.0, used_gb=88.0, swap_active=False):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "warning"


class TestCpuX86:
    def test_detect_capabilities(self):
        with patch_cpu_x86(total_gb=96.0):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            assert arch.name.value == "cpu_x86"
            assert arch.memory_model == "unified"  # single pool, structurally unified
            assert arch.pool_count == 1
            assert arch.total_memory_gb == 96.0
            assert (
                arch.warm_reload_cost_class == "cheap"
            )  # page cache works on Linux too
            assert (
                arch.failure_class == "subprocess_kill"
            )  # OOM-killer, not swap-thrash
            assert arch.supports_placement is False

    def test_snapshot_ok_when_available(self):
        with patch_cpu_x86(total_gb=96.0, available_gb=80.0):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "ok"

    def test_snapshot_critical_when_low_available(self):
        # < 10% available = critical (OOM-killer territory)
        with patch_cpu_x86(total_gb=96.0, available_gb=8.0):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "critical"

    def test_snapshot_warning_when_modest_pressure(self):
        # 10-20% available = warning
        with patch_cpu_x86(total_gb=96.0, available_gb=14.0):
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "warning"


class TestProtocolConformance:
    def test_apple_unified_satisfies_protocol(self):
        from api.services.architecture import Architecture

        with patch_apple_unified():
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            assert isinstance(arch, Architecture)

    def test_cpu_x86_satisfies_protocol(self):
        from api.services.architecture import Architecture

        with patch_cpu_x86():
            from api.services.arch_impl.unified import UnifiedArchitecture

            arch = UnifiedArchitecture.detect()
            assert isinstance(arch, Architecture)
