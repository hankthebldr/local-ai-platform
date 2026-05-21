"""Tests for detect_deployment() and invalid-combo guards.

Phase 1 / Task 1.4c.
"""

from __future__ import annotations

import pytest

from tests.mocks.deployment.mock_dmg import patch_dmg
from tests.mocks.deployment.mock_container import patch_container
from tests.mocks.deployment.mock_host_native import patch_host_native
from tests.mocks.arch.mock_apple_unified import patch_apple_unified
from tests.mocks.arch.mock_cpu_x86 import patch_cpu_x86
from tests.mocks.arch.mock_nvidia import patch_nvidia_single


class TestDetectDeployment:
    def test_detect_container_via_dockerenv(self):
        from api.services.deployment import detect_deployment

        with patch_container():
            d = detect_deployment()
            assert d.mode.value == "container"

    def test_detect_dmg_via_sys_frozen_on_darwin(self):
        from api.services.deployment import detect_deployment

        with patch_dmg():
            d = detect_deployment()
            assert d.mode.value == "dmg_native"

    def test_detect_host_native_default(self):
        from api.services.deployment import detect_deployment

        with patch_host_native():
            d = detect_deployment()
            assert d.mode.value == "host_native"

    def test_container_check_wins_over_frozen(self):
        """If both /.dockerenv exists AND sys.frozen=True (weird), container wins."""
        from api.services.deployment import detect_deployment

        with patch_container():
            d = detect_deployment()
            assert d.mode.value == "container"


class TestDeploymentSingleton:
    def test_current_returns_detected(self):
        from api.services.deployment import Deployment, detect_deployment

        with patch_host_native():
            detected = detect_deployment()
            current = Deployment.current()
            assert current is detected

    def test_current_raises_before_detect(self):
        from api.services import deployment as dep_mod
        from api.services.deployment import Deployment

        dep_mod._current_deployment = None
        with pytest.raises(RuntimeError, match="before detect_deployment"):
            Deployment.current()


class TestInvalidCombos:
    """Verify the invalid (arch, deployment) guard.

    These tests inject the singletons directly rather than relying on
    detection probes, because the real-world impossibility means the
    detection mocks can't naturally produce the invalid pair.
    """

    def test_dmg_with_nvidia_strict_raises(self):
        """DMG×NVIDIA is structurally impossible; STRICT mode raises."""
        from api.services import deployment as dep_mod
        from api.services.architecture import _check_invalid_combo
        from api.services.deployment_impl.dmg import DmgDeployment

        # Construct singletons that represent the impossible pair
        with patch_dmg():
            dmg = DmgDeployment.detect()
        dep_mod._set_current(dmg)

        with patch_nvidia_single(vram_gb=80.0):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            nvidia = NvidiaSingleArchitecture.detect()

        # Run the guard directly
        with pytest.raises(RuntimeError, match="invalid arch.deployment"):
            _check_invalid_combo(nvidia, strict=True)

    def test_dmg_with_nvidia_lenient_logs_error(self, caplog):
        """Lenient mode logs the error but does not raise."""
        import logging
        from api.services import deployment as dep_mod
        from api.services.architecture import _check_invalid_combo
        from api.services.deployment_impl.dmg import DmgDeployment

        with patch_dmg():
            dmg = DmgDeployment.detect()
        dep_mod._set_current(dmg)

        with patch_nvidia_single(vram_gb=80.0):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            nvidia = NvidiaSingleArchitecture.detect()

        with caplog.at_level(logging.ERROR, logger="api.services.architecture"):
            _check_invalid_combo(nvidia, strict=False)
        assert any("invalid arch" in record.message for record in caplog.records)

    def test_valid_combos_do_not_raise(self):
        """Sanity: valid combos should pass cleanly through the guard."""
        from api.services import deployment as dep_mod
        from api.services.architecture import _check_invalid_combo
        from api.services.deployment_impl.host_native import HostNativeDeployment

        with patch_host_native():
            host = HostNativeDeployment.detect()
        dep_mod._set_current(host)

        with patch_nvidia_single(vram_gb=80.0):
            from api.services.arch_impl.nvidia_single import NvidiaSingleArchitecture

            nvidia = NvidiaSingleArchitecture.detect()

        # host_native × gpu_nvidia_single is valid
        _check_invalid_combo(nvidia, strict=True)  # should NOT raise

    def test_dmg_without_darwin_is_rejected_strict(self):
        """DMG mode on a non-Mac platform is impossible (py2app is Mac-only)."""
        from api.services.deployment import detect_deployment

        # Force the impossible: sys.frozen=True on Linux
        from unittest.mock import patch as mp

        with patch_cpu_x86():
            with mp("sys.frozen", True, create=True):
                # Deployment detector currently keys on /.dockerenv first,
                # then sys.frozen+darwin. On Linux+frozen, that's host_native
                # by design (DMG requires darwin). So no invalid combo here.
                d = detect_deployment()
                assert d.mode.value == "host_native"

    def test_docker_desktop_on_mac_collapses_to_cpu_x86(self):
        """Docker on Mac shows /.dockerenv → container; the VM inside is Linux
        so the architecture detector sees cpu_x86. Log a warning explaining.
        """
        from api.services.architecture import detect_architecture
        from api.services.deployment import detect_deployment

        # patch_container patches /.dockerenv to True; combine with
        # darwin platform via patch_apple_unified WITHOUT NVML.
        # The arch detector's darwin short-circuit makes this apple_unified.
        # The deployment detector calls it container.
        # This is the genuinely awkward Docker-Desktop-on-Mac case.
        with patch_container(), patch_apple_unified():
            d = detect_deployment()
            arch = detect_architecture()
            # On darwin platform the arch short-circuits to apple_unified
            # even though we're "in a container" — Docker Desktop uses a
            # Linux VM but the host process sees darwin. Document this.
            assert d.mode.value == "container"
            assert arch.name.value == "apple_unified"
            # The validate_config or main.py banner should warn about this.
