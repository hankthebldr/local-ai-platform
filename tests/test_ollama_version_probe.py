"""Tests for Ollama version probe + floor enforcement.

Phase 1 / Task 1.4d.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch


class TestOllamaServiceGetVersion:
    def test_get_version_returns_string(self):
        from api.services.ollama_service import OllamaService

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"version": "0.23.4"}
            mock_get.return_value.raise_for_status = lambda: None
            v = OllamaService().get_version()
            assert v == "0.23.4"

    def test_get_version_returns_none_on_unreachable(self):
        from api.services.ollama_service import OllamaService

        with patch("requests.get", side_effect=Exception("connection refused")):
            v = OllamaService().get_version()
            assert v is None


class TestVersionFloorEnforcement:
    def test_old_version_refuses_in_strict_mode(self):
        from api.services.architecture import probe_ollama_version

        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value="0.15.0",
        ):
            with pytest.raises(RuntimeError, match="Ollama version"):
                probe_ollama_version(strict=True)

    def test_old_version_warns_in_lenient_mode(self, caplog):
        import logging
        from api.services.architecture import probe_ollama_version

        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value="0.15.0",
        ):
            with caplog.at_level(logging.WARNING, logger="api.services.architecture"):
                result = probe_ollama_version(strict=False)
            assert result["version"] == "0.15.0"
            assert result["reachable"] is True
            assert result["meets_floor"] is False
            assert any("below floor" in r.message for r in caplog.records)

    def test_intermediate_version_warns_phase_5_degradation(self, caplog):
        import logging
        from api.services.architecture import probe_ollama_version

        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value="0.21.0",
        ):
            with caplog.at_level(logging.WARNING, logger="api.services.architecture"):
                result = probe_ollama_version(strict=False)
            assert result["meets_floor"] is False
            assert result["version"] == "0.21.0"

    def test_pinned_version_meets_floor(self):
        from api.services.architecture import probe_ollama_version

        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value="0.23.4",
        ):
            result = probe_ollama_version(strict=False)
            assert result["meets_floor"] is True

    def test_newer_version_meets_floor(self):
        from api.services.architecture import probe_ollama_version

        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value="0.25.1",
        ):
            result = probe_ollama_version(strict=False)
            assert result["meets_floor"] is True

    def test_unreachable_version_does_not_meet_floor(self):
        from api.services.architecture import probe_ollama_version

        with patch(
            "api.services.ollama_service.OllamaService.get_version",
            return_value=None,
        ):
            result = probe_ollama_version(strict=False)
            assert result["meets_floor"] is False
            assert result["reachable"] is False
            assert result["version"] is None

    def test_custom_floor_via_env(self):
        """ENCLAVE_OLLAMA_VERSION_FLOOR overrides the default 0.23.4 floor."""
        import os
        from api.services.architecture import probe_ollama_version

        with patch.dict(os.environ, {"ENCLAVE_OLLAMA_VERSION_FLOOR": "0.20.0"}):
            with patch(
                "api.services.ollama_service.OllamaService.get_version",
                return_value="0.22.0",
            ):
                result = probe_ollama_version(strict=False)
                assert result["meets_floor"] is True  # 0.22 >= 0.20
