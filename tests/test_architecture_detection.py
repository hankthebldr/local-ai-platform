"""Tests for top-level detect_architecture() + singleton accessor.

Phase 1 / Task 1.4.
"""

from __future__ import annotations

import pytest

from tests.mocks.arch.mock_apple_unified import patch_apple_unified
from tests.mocks.arch.mock_cpu_x86 import patch_cpu_x86
from tests.mocks.arch.mock_nvidia import patch_nvidia_single, patch_nvidia_multi
from tests.mocks.arch.mock_unknown import patch_no_detection


class TestDetectArchitecture:
    def test_detect_apple_unified_on_mac(self):
        from api.services.architecture import detect_architecture

        with patch_apple_unified(total_gb=48.0):
            arch = detect_architecture()
            assert arch.name.value == "apple_unified"

    def test_detect_cpu_x86_on_linux_no_gpu(self):
        from api.services.architecture import detect_architecture

        with patch_cpu_x86(total_gb=96.0):
            arch = detect_architecture()
            assert arch.name.value == "cpu_x86"

    def test_detect_gpu_nvidia_single(self):
        from api.services.architecture import detect_architecture

        with patch_nvidia_single(vram_gb=80.0):
            arch = detect_architecture()
            assert arch.name.value == "gpu_nvidia_single"

    def test_detect_gpu_nvidia_multi(self):
        from api.services.architecture import detect_architecture

        with patch_nvidia_multi(gpus=[{"vram_gb": 80.0}, {"vram_gb": 80.0}]):
            arch = detect_architecture()
            assert arch.name.value == "gpu_nvidia_multi"

    def test_detect_unknown_when_all_probes_fail(self):
        from api.services.architecture import detect_architecture

        with patch_no_detection():
            arch = detect_architecture()
            assert arch.name.value == "unknown"


class TestSingletonAccessor:
    def test_current_returns_detected_arch(self):
        from api.services.architecture import Architecture, detect_architecture

        with patch_apple_unified(total_gb=64.0):
            detected = detect_architecture()
            current = Architecture.current()
            assert current is detected

    def test_current_raises_before_detect(self):
        from api.services import architecture as arch_mod
        from api.services.architecture import Architecture

        # Force reset of the singleton for this test
        arch_mod._current_architecture = None
        with pytest.raises(RuntimeError, match="before detect_architecture"):
            Architecture.current()

    def test_repeated_detect_replaces_singleton(self):
        """detect_architecture is idempotent: calling twice replaces singleton."""
        from api.services.architecture import Architecture, detect_architecture

        with patch_apple_unified(total_gb=48.0):
            a1 = detect_architecture()
        with patch_nvidia_single(vram_gb=80.0):
            a2 = detect_architecture()
        assert Architecture.current() is a2
        assert a1 is not a2
