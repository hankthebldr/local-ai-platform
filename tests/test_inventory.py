#!/usr/bin/env python3
"""
Inventory Router Tests — Unit tests (mocked) and Integration tests (real Ollama)

Unit tests:   Always run, no external dependencies
Integration:  Require Ollama running with at least one model

Run all:      pytest tests/test_inventory.py -v
Run unit:     pytest tests/test_inventory.py -v -k "not integration"
Run integ:    pytest tests/test_inventory.py -v -k "integration"
"""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Test client with auth disabled — force-reimports to avoid cross-test pollution"""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import importlib
    import api.middleware
    importlib.reload(api.middleware)
    import api.main
    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


# ── Unit Tests: System Info ───────────────────────────────────────────────


class TestSystemInfo:
    """Unit tests for /api/inventory/system endpoint"""

    def test_system_returns_200(self, client):
        resp = client.get("/api/inventory/system")
        assert resp.status_code == 200

    def test_system_has_hardware(self, client):
        data = client.get("/api/inventory/system").json()
        assert "hardware" in data
        hw = data["hardware"]
        assert "profile" in hw
        assert "name" in hw
        assert "ram_gb" in hw
        assert "threads" in hw
        assert hw["ram_gb"] > 0
        assert hw["threads"] > 0

    def test_system_has_memory(self, client):
        data = client.get("/api/inventory/system").json()
        mem = data["memory"]
        assert "total_gb" in mem
        assert "used_gb" in mem
        assert "available_gb" in mem
        assert "percent" in mem
        assert mem["total_gb"] > 0
        assert 0 <= mem["percent"] <= 100

    def test_system_has_disk(self, client):
        data = client.get("/api/inventory/system").json()
        disk = data["disk"]
        assert "total_gb" in disk
        assert "free_gb" in disk
        assert "percent" in disk
        assert disk["total_gb"] > 0

    def test_system_has_cpu(self, client):
        data = client.get("/api/inventory/system").json()
        cpu = data["cpu"]
        assert "count" in cpu
        assert "count_physical" in cpu
        assert cpu["count"] > 0


# ── Unit Tests: Catalog ───────────────────────────────────────────────────


class TestCatalogUnit:
    """Unit tests for /api/inventory/catalog with mocked Ollama"""

    @patch("api.routers.inventory.requests.get")
    def test_catalog_returns_models(self, mock_get, client):
        """Catalog should return models from registry even when Ollama is down"""
        mock_get.side_effect = Exception("Connection refused")

        resp = client.get("/api/inventory/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "total" in data
        assert "hardware" in data
        assert data["total"] > 0

    @patch("api.routers.inventory.requests.get")
    def test_catalog_models_have_required_fields(self, mock_get, client):
        """Each catalog model must have expected fields"""
        mock_get.side_effect = Exception("Connection refused")

        data = client.get("/api/inventory/catalog").json()
        for m in data["models"]:
            assert "id" in m
            assert "name" in m
            assert "size" in m
            assert "description" in m
            assert "tags" in m
            assert "installed" in m
            assert "fits_ram" in m
            assert isinstance(m["tags"], list)
            assert isinstance(m["installed"], bool)

    @patch("api.routers.inventory.requests.get")
    def test_catalog_tag_filter(self, mock_get, client):
        """Tag filter should narrow results"""
        mock_get.side_effect = Exception("Connection refused")

        all_resp = client.get("/api/inventory/catalog").json()
        coding_resp = client.get("/api/inventory/catalog?tag=coding").json()

        assert coding_resp["total"] <= all_resp["total"]
        for m in coding_resp["models"]:
            assert "coding" in m["tags"]

    @patch("api.routers.inventory.requests.get")
    def test_catalog_installed_status_with_ollama(self, mock_get, client):
        """Models should be marked installed when found in Ollama"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "models": [
                {"name": "dolphin3:latest", "size": 5000000000},
            ]
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        data = client.get("/api/inventory/catalog").json()

        installed = [m for m in data["models"] if m["installed"]]
        assert data["installed_count"] >= 1
        # dolphin3 should be marked installed
        dolphin = next((m for m in data["models"] if m["id"] == "dolphin3"), None)
        if dolphin:
            assert dolphin["installed"] is True


# ── Unit Tests: Status ────────────────────────────────────────────────────


class TestStatusUnit:
    """Unit tests for /api/inventory/status"""

    @patch("api.routers.inventory.requests.get")
    def test_status_returns_counts(self, mock_get, client):
        mock_get.side_effect = Exception("Connection refused")

        resp = client.get("/api/inventory/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "installed" in data
        assert "available" in data
        assert "installed_count" in data
        assert "available_count" in data
        assert "total_registry" in data
        assert isinstance(data["installed"], list)
        assert isinstance(data["available"], list)

    @patch("api.routers.inventory.requests.get")
    def test_status_counts_add_up(self, mock_get, client):
        mock_get.side_effect = Exception("Connection refused")

        data = client.get("/api/inventory/status").json()
        assert data["installed_count"] + data["available_count"] == data["total_registry"]


# ── Unit Tests: Memory ────────────────────────────────────────────────────


class TestMemoryUnit:
    """Unit tests for /api/inventory/memory"""

    @patch("api.routers.inventory.requests.get")
    def test_memory_with_running_models(self, mock_get, client):
        mock_response = Mock()
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "dolphin3:latest",
                    "size": 5000000000,
                    "size_vram": 0,
                    "digest": "abc123def456",
                    "expires_at": "2026-03-28T20:00:00Z",
                    "details": {"family": "llama"},
                }
            ]
        }
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        resp = client.get("/api/inventory/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running_count"] == 1
        rm = data["running_models"][0]
        assert rm["name"] == "dolphin3:latest"
        assert rm["size_gb"] > 0
        assert "system_memory" in data

    @patch("api.routers.inventory.requests.get")
    def test_memory_empty_when_ollama_down(self, mock_get, client):
        mock_get.side_effect = Exception("Connection refused")

        resp = client.get("/api/inventory/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running_count"] == 0
        assert data["running_models"] == []


# ── Unit Tests: Pull / Remove / Unload ────────────────────────────────────


class TestPullUnit:
    """Unit tests for pull/remove/unload endpoints"""

    @patch("api.routers.inventory.requests.post")
    def test_pull_starts(self, mock_post, client):
        """Pull should start a background job"""
        # Mock the streaming response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.iter_lines.return_value = [
            b'{"status":"success"}'
        ]
        mock_post.return_value = mock_response

        resp = client.post(
            "/api/inventory/pull",
            json={"model": "test-model:latest"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("started", "already_pulling")
        assert data["model"] == "test-model:latest"

    def test_pull_missing_model(self, client):
        resp = client.post("/api/inventory/pull", json={})
        assert resp.status_code == 422

    @patch("api.routers.inventory.requests.delete")
    def test_remove_success(self, mock_delete, client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "OK"
        mock_delete.return_value = mock_response

        resp = client.post(
            "/api/inventory/remove",
            json={"model": "test-model:latest"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    @patch("api.routers.inventory.requests.delete")
    def test_remove_failure(self, mock_delete, client):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "model not found"
        mock_delete.return_value = mock_response

        resp = client.post(
            "/api/inventory/remove",
            json={"model": "nonexistent:latest"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_remove_missing_model(self, client):
        resp = client.post("/api/inventory/remove", json={})
        assert resp.status_code == 422

    @patch("api.routers.inventory.requests.post")
    def test_unload_success(self, mock_post, client):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        resp = client.post(
            "/api/inventory/unload",
            json={"model": "dolphin3:latest"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "unloaded"

    def test_unload_missing_model(self, client):
        resp = client.post("/api/inventory/unload", json={})
        assert resp.status_code == 422


class TestPullProgress:
    """Unit tests for pull progress polling"""

    def test_progress_not_found(self, client):
        resp = client.get("/api/inventory/pull-progress/nonexistent-model")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"


# ── Unit Tests: Hardware Detection ────────────────────────────────────────


class TestHardwareDetection:
    """Unit tests for the detect_hardware function"""

    def test_detect_returns_valid_profile(self):
        from api.routers.inventory import detect_hardware

        hw = detect_hardware()
        assert "profile" in hw
        assert "name" in hw
        assert "ram_gb" in hw
        assert "threads" in hw
        assert "max_model_ram_gb" in hw
        assert hw["ram_gb"] > 0
        assert hw["max_model_ram_gb"] > 0
        assert hw["threads"] > 0

    def test_detect_max_model_ram_less_than_total(self):
        from api.routers.inventory import detect_hardware

        hw = detect_hardware()
        assert hw["max_model_ram_gb"] <= hw["ram_gb"]


# ── Integration Tests ─────────────────────────────────────────────────────


class TestIntegrationCatalog:
    """Integration: catalog against real Ollama"""

    @pytest.mark.integration
    def test_catalog_shows_installed(self, client):
        resp = client.get("/api/inventory/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed_count"] > 0
        installed = [m for m in data["models"] if m["installed"]]
        assert len(installed) > 0

    @pytest.mark.integration
    def test_catalog_installed_have_info(self, client):
        data = client.get("/api/inventory/catalog").json()
        installed = [m for m in data["models"] if m["installed"]]
        for m in installed:
            if m.get("installed_info"):
                assert "size_gb" in m["installed_info"]


class TestIntegrationMemory:
    """Integration: memory against real Ollama"""

    @pytest.mark.integration
    def test_memory_returns(self, client):
        resp = client.get("/api/inventory/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "running_models" in data
        assert "running_count" in data
        assert "system_memory" in data


class TestIntegrationStatus:
    """Integration: status against real Ollama"""

    @pytest.mark.integration
    def test_status_has_installed(self, client):
        resp = client.get("/api/inventory/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_ollama"] > 0


# ── Unit Tests: Scoring System ─────────────────────────────────────────────


class TestModelScoring:
    """Unit tests for catalog scoring prioritization"""

    def test_abliterated_scores_highest(self):
        from api.routers.inventory import score_model

        abliterated = {
            "tags": ["abliterated", "uncensored"],
            "context": "128K",
            "fits_ram": True,
            "installed": False,
        }
        vanilla = {
            "tags": ["reasoning"],
            "context": "128K",
            "fits_ram": True,
            "installed": False,
        }
        assert score_model(abliterated) > score_model(vanilla)

    def test_large_context_scores_higher(self):
        from api.routers.inventory import score_model

        large_ctx = {
            "tags": ["abliterated"],
            "context": "128K",
            "fits_ram": True,
            "installed": False,
        }
        small_ctx = {
            "tags": ["abliterated"],
            "context": "4K",
            "fits_ram": True,
            "installed": False,
        }
        assert score_model(large_ctx) > score_model(small_ctx)

    def test_fits_ram_bonus(self):
        from api.routers.inventory import score_model

        fits = {"tags": ["abliterated"], "context": "128K", "fits_ram": True, "installed": False}
        no_fit = {"tags": ["abliterated"], "context": "128K", "fits_ram": False, "installed": False}
        assert score_model(fits) > score_model(no_fit)

    def test_installed_bonus(self):
        from api.routers.inventory import score_model

        installed = {"tags": ["abliterated"], "context": "128K", "fits_ram": True, "installed": True}
        not_inst = {"tags": ["abliterated"], "context": "128K", "fits_ram": True, "installed": False}
        assert score_model(installed) > score_model(not_inst)

    def test_parse_context_k(self):
        from api.routers.inventory import _parse_context_k

        assert _parse_context_k("128K") == 128
        assert _parse_context_k("256K") == 256
        assert _parse_context_k("32K") == 32
        assert _parse_context_k("4K") == 4
        assert _parse_context_k("—") == 0
        assert _parse_context_k("") == 0

    @patch("api.routers.inventory.requests.get")
    def test_catalog_sorted_by_score(self, mock_get, client):
        """Catalog should return models sorted by score descending"""
        mock_get.side_effect = Exception("Connection refused")

        data = client.get("/api/inventory/catalog").json()
        models = data["models"]
        scores = [m.get("score", 0) for m in models]
        assert scores == sorted(scores, reverse=True), "Catalog should be sorted by score descending"

    @patch("api.routers.inventory.requests.get")
    def test_catalog_models_have_score(self, mock_get, client):
        """Each catalog model should have a score field"""
        mock_get.side_effect = Exception("Connection refused")

        data = client.get("/api/inventory/catalog").json()
        for m in data["models"]:
            assert "score" in m
            assert isinstance(m["score"], (int, float))
            assert m["score"] >= 0


# ── Unit Tests: Discovery Service ──────────────────────────────────────────


class TestDiscoveryService:
    """Unit tests for the discovery service"""

    def test_abliteration_detection(self):
        from api.services.discovery_service import _is_abliterated

        assert _is_abliterated({"modelId": "user/model-abliterated", "tags": []})
        assert _is_abliterated({"modelId": "user/model", "tags": ["uncensored"]})
        assert _is_abliterated({"modelId": "user/unsensored-model", "tags": []})
        assert _is_abliterated({"modelId": "user/heretic-model", "tags": []})
        assert not _is_abliterated({"modelId": "user/normal-model", "tags": ["text-generation"]})

    def test_gguf_detection(self):
        from api.services.discovery_service import _is_gguf_available

        assert _is_gguf_available({"tags": ["gguf"], "siblings": []})
        assert _is_gguf_available({"tags": [], "siblings": [{"rfilename": "model.Q4_K_M.gguf"}]})
        assert _is_gguf_available({"modelId": "user/model-GGUF", "tags": [], "siblings": []})
        assert not _is_gguf_available({"modelId": "user/model", "tags": ["pytorch"], "siblings": []})

    def test_param_size_extraction(self):
        from api.services.discovery_service import _extract_param_size

        assert _extract_param_size({"modelId": "user/model-7b", "tags": []}) == "7B"
        assert _extract_param_size({"modelId": "user/model-70b-instruct", "tags": []}) == "70B"
        assert _extract_param_size({"modelId": "user/model", "tags": ["8b"]}) == "8B"

    def test_gguf_size_estimation(self):
        from api.services.discovery_service import _estimate_gguf_size_gb

        # 7B Q4_K_M should be ~3.9GB
        size = _estimate_gguf_size_gb("7B", "Q4_K_M")
        assert 3 < size < 5

        # 70B Q4_K_M should be ~38.5GB
        size = _estimate_gguf_size_gb("70B", "Q4_K_M")
        assert 35 < size < 42

        # None should return 0
        assert _estimate_gguf_size_gb(None) == 0

    def test_discovery_scoring(self):
        from api.services.discovery_service import score_discovered_model

        high = {
            "is_abliterated": True,
            "context_window": 128000,
            "has_gguf": True,
            "is_trusted_author": True,
            "downloads": 5000,
            "likes": 100,
            "fits_ram": True,
        }
        low = {
            "is_abliterated": False,
            "context_window": 4000,
            "has_gguf": False,
            "is_trusted_author": False,
            "downloads": 10,
            "likes": 0,
            "fits_ram": True,
        }
        assert score_discovered_model(high) > score_discovered_model(low)

    def test_trusted_authors_list(self):
        from api.services.discovery_service import TRUSTED_AUTHORS

        assert len(TRUSTED_AUTHORS) >= 5
        assert "huihui_ai" in TRUSTED_AUTHORS
        assert "cognitivecomputations" in TRUSTED_AUTHORS
        assert "DavidAU" in TRUSTED_AUTHORS


# ── Unit Tests: Discovery Endpoints ────────────────────────────────────────


class TestDiscoveryEndpoints:
    """Unit tests for discovery API endpoints"""

    @patch("api.routers.inventory.load_discovery_cache")
    @patch("api.routers.inventory.is_cache_fresh")
    def test_discover_returns_models(self, mock_fresh, mock_cache, client):
        # Theme B: a plain GET serves the CACHE and never runs discovery, so
        # the payload now comes from load_discovery_cache. Response shape is
        # unchanged (plus the new never_discovered flag).
        mock_fresh.return_value = True
        mock_cache.return_value = {
            "timestamp": "2026-03-28T12:00:00+00:00",
            "count": 2,
            "models": [
                {"repo_id": "user/model-1", "score": 80, "is_abliterated": True},
                {"repo_id": "user/model-2", "score": 60, "is_abliterated": True},
            ],
        }

        resp = client.get("/api/inventory/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "count" in data
        assert "trusted_authors" in data
        assert data["count"] == 2
        assert data["never_discovered"] is False

    @patch("api.routers.inventory.get_cached_or_discover")
    @patch("api.routers.inventory.is_cache_fresh")
    def test_discover_force_refresh(self, mock_fresh, mock_discover, client):
        mock_fresh.return_value = False
        mock_discover.return_value = {"timestamp": "now", "count": 0, "models": []}

        resp = client.get("/api/inventory/discover?force=true")
        assert resp.status_code == 200
        mock_discover.assert_called_once()
        # Should have been called with force=True
        call_kwargs = mock_discover.call_args
        assert call_kwargs[1].get("force") is True

    def test_discover_refresh_endpoint(self, client):
        resp = client.post("/api/inventory/discover/refresh")
        assert resp.status_code == 200
        assert resp.json()["status"] == "refreshing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
