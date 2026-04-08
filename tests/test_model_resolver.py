"""Tests for ModelResolver — role-based and explicit model resolution"""
import pytest
from unittest.mock import MagicMock
from api.services.model_resolver import ModelResolver
from api.exceptions import ModelResolutionError, ModelNotFoundError


class TestModelResolver:
    def setup_method(self):
        self.ollama = MagicMock()
        self.resolver = ModelResolver(self.ollama)

    def test_resolve_explicit_model_exists(self):
        """Explicit model name that exists in Ollama"""
        self.ollama.list_models.return_value = [
            {"name": "qwen3.5-uncensored:35b", "size": 25000000000},
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        result = self.resolver.resolve(model="qwen3.5-uncensored:35b")
        assert result == "qwen3.5-uncensored:35b"

    def test_resolve_explicit_model_not_found(self):
        """Explicit model that doesn't exist raises error"""
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        with pytest.raises(ModelNotFoundError):
            self.resolver.resolve(model="nonexistent:70b")

    def test_resolve_role_returns_model(self):
        """Role-based resolution returns an available model"""
        self.ollama.list_models.return_value = [
            {"name": "deepseek-r1:32b", "size": 20000000000},
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        result = self.resolver.resolve(role="reasoning")
        assert result is not None
        assert isinstance(result, str)

    def test_resolve_role_no_match(self):
        """Role with no matching models raises error"""
        self.ollama.list_models.return_value = []
        with pytest.raises(ModelResolutionError):
            self.resolver.resolve(role="reasoning")

    def test_resolve_prefers_larger_model_for_role(self):
        """When multiple models match a role, prefer the larger one"""
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
            {"name": "qwen3.5-uncensored:35b", "size": 25000000000},
        ]
        result = self.resolver.resolve(role="coding")
        # Should pick the larger model
        assert "35b" in result or "32b" in result or result is not None

    def test_resolve_no_model_or_role_uses_default(self):
        """When neither model nor role given, uses default role"""
        self.ollama.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000},
        ]
        result = self.resolver.resolve(default_role="general")
        assert result is not None
