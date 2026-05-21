"""Tests for NvidiaSingleArchitecture and NvidiaMultiArchitecture.

Phase 1 / Task 1.3. All tests use mocked NVML; no GPU hardware needed.
"""

from __future__ import annotations

import pytest

from tests.mocks.arch.mock_nvidia import patch_nvidia_single, patch_nvidia_multi


class TestNvidiaSingle:
    def test_a100_80gb(self):
        with patch_nvidia_single(vram_gb=80.0, name="NVIDIA A100 80GB"):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            arch = NvidiaSingleArchitecture.detect()
            assert arch.name.value == "gpu_nvidia_single"
            assert arch.memory_model == "discrete"
            assert arch.pool_count == 1
            assert arch.total_memory_gb == 80.0
            assert arch.per_pool_gb == [80.0]
            assert arch.warm_reload_cost_class == "expensive"
            assert arch.failure_class == "hard_oom"
            assert arch.supports_placement is False
            assert arch.gpus[0]["name"] == "NVIDIA A100 80GB"
            assert arch.gpus[0]["pcie_gen"] == 4

    def test_l4_24gb(self):
        with patch_nvidia_single(vram_gb=24.0, name="NVIDIA L4"):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            arch = NvidiaSingleArchitecture.detect()
            assert arch.total_memory_gb == 24.0
            assert arch.gpus[0]["name"] == "NVIDIA L4"

    def test_snapshot_ok_when_vram_free(self):
        with patch_nvidia_single(vram_gb=80.0):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            arch = NvidiaSingleArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "ok"
            assert snap.per_pool[0]["free_gb"] == pytest.approx(80.0, abs=0.1)

    def test_classify_cuda_oom(self):
        with patch_nvidia_single(vram_gb=80.0):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            arch = NvidiaSingleArchitecture.detect()
            err = arch.classify_error(RuntimeError("CUDA out of memory"))
            assert err.error_class == "memory"
            assert err.error_code == "vram_oom"
            assert err.recoverable is True
            assert err.suggested_action == "evict_and_retry"

    def test_classify_runner_crash(self):
        with patch_nvidia_single(vram_gb=80.0):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            arch = NvidiaSingleArchitecture.detect()
            err = arch.classify_error(RuntimeError("runner subprocess died"))
            assert err.error_class == "runner"
            assert err.error_code == "runner_crashed"


class TestNvidiaMulti:
    def test_h100_dual_with_nvlink(self):
        with patch_nvidia_multi(
            gpus=[{"vram_gb": 80.0, "name": "H100"}, {"vram_gb": 80.0, "name": "H100"}],
            nvlink_pairs=[(0, 1)],
        ):
            from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

            arch = NvidiaMultiArchitecture.detect()
            assert arch.name.value == "gpu_nvidia_multi"
            assert arch.pool_count == 2
            assert arch.total_memory_gb == 160.0
            assert arch.per_pool_gb == [80.0, 80.0]
            assert arch.supports_placement is True
            assert (0, 1) in arch.nvlink_topology

    def test_quad_a100_no_nvlink(self):
        with patch_nvidia_multi(
            gpus=[{"vram_gb": 80.0}] * 4,
            nvlink_pairs=[],
        ):
            from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

            arch = NvidiaMultiArchitecture.detect()
            assert arch.pool_count == 4
            assert arch.total_memory_gb == 320.0
            assert arch.nvlink_topology == []

    def test_snapshot_per_gpu(self):
        with patch_nvidia_multi(gpus=[{"vram_gb": 80.0}, {"vram_gb": 80.0}]):
            from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

            arch = NvidiaMultiArchitecture.detect()
            snap = arch.snapshot()
            assert len(snap.per_pool) == 2
            assert snap.per_pool[0]["pool_id"] == 0
            assert snap.per_pool[1]["pool_id"] == 1

    def test_snapshot_critical_when_any_gpu_low(self):
        # Mock one GPU at 5% free (below 10% critical)
        with patch_nvidia_multi(
            gpus=[
                {"vram_gb": 80.0, "vram_free_gb": 4.0},
                {"vram_gb": 80.0, "vram_free_gb": 60.0},
            ]
        ):
            from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

            arch = NvidiaMultiArchitecture.detect()
            snap = arch.snapshot()
            assert snap.level == "critical"


class TestProtocolConformance:
    def test_single_satisfies_protocol(self):
        from api.services.architecture import Architecture

        with patch_nvidia_single():
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            arch = NvidiaSingleArchitecture.detect()
            assert isinstance(arch, Architecture)

    def test_multi_satisfies_protocol(self):
        from api.services.architecture import Architecture

        with patch_nvidia_multi():
            from api.services.arch_impl.nvidia_multi import NvidiaMultiArchitecture

            arch = NvidiaMultiArchitecture.detect()
            assert isinstance(arch, Architecture)
