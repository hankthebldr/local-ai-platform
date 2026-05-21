"""Tests for the three Deployment impls (DMG, Container, HostNative).

Phase 1 / Task 1.4b.
"""

from __future__ import annotations

import pytest

from tests.mocks.deployment.mock_dmg import patch_dmg
from tests.mocks.deployment.mock_container import patch_container
from tests.mocks.deployment.mock_host_native import patch_host_native


class TestDmgDeployment:
    def test_capabilities(self):
        with patch_dmg(host_memory_gb=48.0) as ctx:
            from api.services.deployment_impl.dmg import DmgDeployment

            d = DmgDeployment.detect()
            assert d.mode.value == "dmg_native"
            assert (
                d.user_storage_root
                == ctx["home"] / "Library/Application Support/Enclave"
            )
            assert d.system_storage_root == ctx["bundle"]
            assert d.ollama_url == "http://127.0.0.1:11434"

    def test_effective_memory_applies_host_headroom(self):
        # 48 GB host, 20% headroom → 38.4 GB effective
        with patch_dmg(host_memory_gb=48.0):
            from api.services.deployment_impl.dmg import DmgDeployment

            d = DmgDeployment.detect()
            assert d.effective_memory_gb() == pytest.approx(38.4, abs=0.1)

    def test_ensure_user_storage_creates_subdirs(self):
        with patch_dmg() as ctx:
            from api.services.deployment_impl.dmg import DmgDeployment

            d = DmgDeployment.detect()
            d.ensure_user_storage()
            assert (d.user_storage_root / "plugins").exists()
            assert (d.user_storage_root / "mcp" / "binaries").exists()
            assert (d.user_storage_root / "cache").exists()
            assert (d.user_storage_root / "workflows").exists()

    def test_recommended_env_no_cuda_on_mac(self):
        with patch_dmg():
            from api.services.deployment_impl.dmg import DmgDeployment
            from api.services.arch_impl.unified import UnifiedArchitecture
            from api.services.architecture import ArchClass

            arch = UnifiedArchitecture(
                arch_class=ArchClass.APPLE_UNIFIED,
                total_memory_gb=48.0,
                bandwidth_gbps=273.0,
            )
            d = DmgDeployment.detect()
            env = d.recommended_env(arch)
            # CUDA env vars must NOT be set for Mac DMG
            assert env.get("CUDA_VISIBLE_DEVICES") is None
            assert "OLLAMA_HOST" in env


class TestContainerDeployment:
    def test_capabilities_with_cgroup_v2_limit(self):
        with patch_container(cgroup_memory_max_gb=32.0, host_memory_gb=96.0) as ctx:
            from api.services.deployment_impl.container import ContainerDeployment

            d = ContainerDeployment.detect()
            assert d.mode.value == "container"
            assert d.user_storage_root == ctx["user_data"]
            assert d.system_storage_root.as_posix() == "/app"
            assert "ollama" in d.ollama_url

    def test_effective_memory_respects_cgroup(self):
        # 32 GB cgroup limit on a 96 GB host → cgroup wins, 10% headroom → 28.8 GB
        with patch_container(cgroup_memory_max_gb=32.0, host_memory_gb=96.0):
            from api.services.deployment_impl.container import ContainerDeployment

            d = ContainerDeployment.detect()
            assert d.effective_memory_gb() == pytest.approx(28.8, abs=0.1)

    def test_effective_memory_falls_back_to_host_when_no_cgroup_limit(self):
        # No cgroup limit set → use host total minus 10% headroom inside container
        with patch_container(cgroup_memory_max_gb=None, host_memory_gb=96.0):
            from api.services.deployment_impl.container import ContainerDeployment

            d = ContainerDeployment.detect()
            assert d.effective_memory_gb() == pytest.approx(86.4, abs=0.1)

    def test_resource_limits_source_cgroup_v2(self):
        with patch_container(cgroup_memory_max_gb=32.0):
            from api.services.deployment_impl.container import ContainerDeployment

            d = ContainerDeployment.detect()
            assert d.resource_limits.source == "cgroup_v2"
            assert d.resource_limits.memory_gb == 32.0

    def test_resource_limits_source_unlimited_no_cgroup(self):
        with patch_container(cgroup_memory_max_gb=None):
            from api.services.deployment_impl.container import ContainerDeployment

            d = ContainerDeployment.detect()
            assert d.resource_limits.source == "psutil_host"


class TestHostNativeDeployment:
    def test_uses_cwd_for_storage(self):
        with patch_host_native() as ctx:
            from api.services.deployment_impl.host_native import HostNativeDeployment

            d = HostNativeDeployment.detect()
            assert d.mode.value == "host_native"
            assert d.system_storage_root == ctx["cwd"]
            assert d.user_storage_root == ctx["home"] / ".enclave"

    def test_effective_memory_with_host_headroom(self):
        # 96 GB host with 20% headroom → 76.8 GB effective
        with patch_host_native(host_memory_gb=96.0):
            from api.services.deployment_impl.host_native import HostNativeDeployment

            d = HostNativeDeployment.detect()
            assert d.effective_memory_gb() == pytest.approx(76.8, abs=0.1)

    def test_ollama_url_localhost(self):
        with patch_host_native():
            from api.services.deployment_impl.host_native import HostNativeDeployment

            d = HostNativeDeployment.detect()
            assert "127.0.0.1" in d.ollama_url or "localhost" in d.ollama_url


class TestProtocolConformance:
    def test_dmg_satisfies_deployment_protocol(self):
        from api.services.deployment import Deployment

        with patch_dmg():
            from api.services.deployment_impl.dmg import DmgDeployment

            d = DmgDeployment.detect()
            assert isinstance(d, Deployment)

    def test_container_satisfies_deployment_protocol(self):
        from api.services.deployment import Deployment

        with patch_container():
            from api.services.deployment_impl.container import ContainerDeployment

            d = ContainerDeployment.detect()
            assert isinstance(d, Deployment)

    def test_host_native_satisfies_deployment_protocol(self):
        from api.services.deployment import Deployment

        with patch_host_native():
            from api.services.deployment_impl.host_native import HostNativeDeployment

            d = HostNativeDeployment.detect()
            assert isinstance(d, Deployment)
