"""Tests for /api/system/* endpoints.

Phase 1 / Task 1.5.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from tests.mocks.arch.mock_apple_unified import patch_apple_unified
from tests.mocks.deployment.mock_host_native import patch_host_native
from tests.mocks.deployment.mock_container import patch_container


def _make_app():
    """Build a minimal FastAPI app with just the system router."""
    from api.routers.system import router

    app = FastAPI()
    app.include_router(router)
    return app


class TestSystemArchitectureEndpoint:
    def test_returns_triple(self):
        # Set up detected state
        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()

            with patch(
                "api.services.ollama_service.OllamaService.get_version",
                return_value="0.23.4",
            ):
                client = TestClient(_make_app())
                r = client.get("/api/system/architecture")
                assert r.status_code == 200
                body = r.json()
                assert "arch" in body
                assert "deployment" in body
                assert "ollama" in body
                assert body["arch"]["name"] == "apple_unified"
                assert body["deployment"]["mode"] == "host_native"

    def test_arch_exposes_capabilities(self):
        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.get("/api/system/architecture")
            arch = r.json()["arch"]
            assert arch["memory_model"] == "unified"
            assert arch["pool_count"] == 1
            assert arch["total_memory_gb"] == 48.0
            assert arch["supports_placement"] is False


class TestSystemPressureEndpoint:
    def test_returns_pressure_snapshot(self):
        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.get("/api/system/pressure")
            assert r.status_code == 200
            body = r.json()
            assert body["level"] in ("ok", "warning", "critical")
            assert "per_pool" in body
            assert isinstance(body["per_pool"], list)


class TestDeploymentPayloadViaArchitectureEndpoint:
    """The /api/system/deployment endpoint was removed in PR #90 — its
    payload is now embedded in /api/system/architecture's `.deployment`
    field. This test guards the consolidated shape so future callers can
    rely on it.
    """

    def test_deployment_subobject_carries_full_payload(self):
        with patch_container(cgroup_memory_max_gb=32.0), patch_apple_unified(
            total_gb=48.0
        ):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.get("/api/system/architecture")
            assert r.status_code == 200
            deployment = r.json()["deployment"]
            assert deployment["mode"] == "container"
            assert "storage_root" in deployment
            assert "ollama_url" in deployment
            assert deployment["effective_memory_gb"] == pytest.approx(28.8, abs=0.1)

    def test_removed_endpoint_returns_404(self):
        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.get("/api/system/deployment")
            assert r.status_code == 404


class TestSystemRefreshEndpoint:
    def test_refresh_re_detects(self):
        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.post("/api/system/architecture/refresh")
            assert r.status_code == 200
            body = r.json()
            assert "arch" in body
            assert "deployment" in body


class TestSystemHealthEndpoint:
    """Phase 6.3 — /api/system/health embeds config validation."""

    def test_health_returns_ok_for_clean_apple_dmg(self):
        from unittest.mock import patch as _patch

        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            # Empty env → warnings only on Apple DMG (no errors), so status
            # remains "ok" overall.
            with _patch(
                "api.services.config_validator.probe_daemon_env",
                return_value={
                    "OLLAMA_HOST": "127.0.0.1:11434",
                    "OLLAMA_MAX_LOADED_MODELS": "3",
                    "OLLAMA_NUM_PARALLEL": "1",
                },
            ):
                client = TestClient(_make_app())
                r = client.get("/api/system/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert "config_validation" in body
            assert body["config_validation"]["is_clean"] is True

    def test_health_surfaces_missing_sched_spread_as_degraded(self):
        from unittest.mock import patch as _patch

        from tests.mocks.arch.mock_nvidia import patch_nvidia_multi

        with patch_host_native(), patch_nvidia_multi(
            gpus=[
                {"vram_total_gb": 80.0, "vram_free_gb": 75.0, "vram_used_gb": 5.0},
                {"vram_total_gb": 80.0, "vram_free_gb": 78.0, "vram_used_gb": 2.0},
            ]
        ):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            with _patch(
                "api.services.config_validator.probe_daemon_env",
                return_value={},
            ):
                client = TestClient(_make_app())
                r = client.get("/api/system/health")
            assert r.status_code == 200
            body = r.json()
            errors = body["config_validation"]["errors"]
            assert any(e["code"] == "missing_sched_spread" for e in errors)
            assert body["status"] == "degraded"


class TestConfigRecommendationsEndpoint:
    """Phase 6.3 — /api/system/config/recommendations returns env + snippets."""

    def test_recommendations_for_apple_dmg(self):
        with patch_host_native(), patch_apple_unified(total_gb=48.0):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.get("/api/system/config/recommendations")
            assert r.status_code == 200
            body = r.json()
            assert body["arch"] == "apple_unified"
            assert "OLLAMA_HOST" in body["recommended_env"]
            assert "OLLAMA_MAX_LOADED_MODELS" in body["recommended_env"]
            # Apple deployment is host_native (or dmg_native); docker-compose
            # snippet should be the "not applicable" note.
            assert "not applicable" in body["docker_compose_snippet"]
            assert "[Service]" in body["systemd_snippet"]

    def test_recommendations_for_nvidia_multi_container(self):
        from tests.mocks.arch.mock_nvidia import patch_nvidia_multi
        from tests.mocks.deployment.mock_container import patch_container

        with patch_container(cgroup_memory_max_gb=128.0), patch_nvidia_multi(
            gpus=[
                {"vram_total_gb": 80.0, "vram_free_gb": 75.0, "vram_used_gb": 5.0},
                {"vram_total_gb": 80.0, "vram_free_gb": 78.0, "vram_used_gb": 2.0},
            ]
        ):
            from api.services.architecture import detect_architecture
            from api.services.deployment import detect_deployment

            detect_deployment()
            detect_architecture()
            client = TestClient(_make_app())
            r = client.get("/api/system/config/recommendations")
            assert r.status_code == 200
            body = r.json()
            assert body["arch"] == "gpu_nvidia_multi"
            assert "OLLAMA_SCHED_SPREAD" in body["recommended_env"]
            # docker-compose snippet should include the GPU reservation block
            assert "nvidia" in body["docker_compose_snippet"]
            assert "capabilities: [gpu]" in body["docker_compose_snippet"]
            # systemd snippet not applicable for container deployment
            assert "not applicable" in body["systemd_snippet"]
