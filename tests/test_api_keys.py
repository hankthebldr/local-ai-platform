#!/usr/bin/env python3
"""Tests for API Key Service"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def key_service():
    """API key service with temp directory for YAML storage"""
    tmpdir = tempfile.mkdtemp()
    os.environ["DATA_CONFIG_DIR"] = tmpdir
    from api.services.api_key_service import APIKeyService
    svc = APIKeyService(config_dir=tmpdir)
    yield svc
    shutil.rmtree(tmpdir)


class TestKeyCreation:
    def test_create_key_returns_full_key(self, key_service):
        result = key_service.create_key(name="test-dev", scopes=["chat", "models"])
        assert result["key"].startswith("sk-test-dev-")
        assert len(result["key"]) > 40
        assert result["id"].startswith("key_")
        assert result["name"] == "test-dev"

    def test_create_key_persists_to_yaml(self, key_service):
        key_service.create_key(name="persist-test", scopes=["chat"])
        keys = key_service.list_keys()
        assert len(keys) == 1
        assert keys[0]["name"] == "persist-test"
        assert "key" not in keys[0]
        assert keys[0]["prefix"].startswith("sk-persist-test-")

    def test_create_key_with_rate_limit(self, key_service):
        result = key_service.create_key(name="limited", scopes=["chat"], rate_limit_rpm=30)
        keys = key_service.list_keys()
        assert keys[0]["rate_limit_rpm"] == 30


class TestKeyValidation:
    def test_validate_valid_key(self, key_service):
        result = key_service.create_key(name="valid", scopes=["chat", "completions"])
        meta = key_service.validate_key(result["key"])
        assert meta is not None
        assert meta["name"] == "valid"
        assert meta["scopes"] == ["chat", "completions"]

    def test_validate_invalid_key(self, key_service):
        assert key_service.validate_key("sk-fake-notreal") is None

    def test_validate_revoked_key(self, key_service):
        result = key_service.create_key(name="revokable", scopes=["chat"])
        key_service.revoke_key(result["id"])
        assert key_service.validate_key(result["key"]) is None

    def test_validate_expired_key(self, key_service):
        result = key_service.create_key(
            name="expired", scopes=["chat"],
            expires_at="2020-01-01T00:00:00Z"
        )
        assert key_service.validate_key(result["key"]) is None


class TestKeyManagement:
    def test_revoke_key(self, key_service):
        result = key_service.create_key(name="to-revoke", scopes=["chat"])
        key_service.revoke_key(result["id"])
        keys = key_service.list_keys()
        assert keys[0]["enabled"] is False

    def test_rotate_key(self, key_service):
        result = key_service.create_key(name="to-rotate", scopes=["chat", "models"])
        old_id = result["id"]
        new_result = key_service.rotate_key(old_id)
        keys = key_service.list_keys()
        old = [k for k in keys if k["id"] == old_id][0]
        assert old["enabled"] is False
        assert key_service.validate_key(new_result["key"]) is not None
        assert new_result["scopes"] == ["chat", "models"]

    def test_update_usage(self, key_service):
        result = key_service.create_key(name="usage-test", scopes=["chat"])
        key_service.update_usage(result["id"], tokens_used=150)
        key_service.update_usage(result["id"], tokens_used=50)
        keys = key_service.list_keys()
        assert keys[0]["usage"]["total_requests"] == 2
        assert keys[0]["usage"]["total_tokens"] == 200


import importlib
from fastapi.testclient import TestClient

# ── Router Tests ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api_client():
    """Test client with master key set"""
    os.environ["ENABLE_API_AUTH"] = "true"
    os.environ["MASTER_API_KEY"] = "master-test-key-12345"
    os.environ["RATE_LIMIT_RPM"] = "0"
    # Reload all modules that cache env vars at import time
    import api.middleware
    importlib.reload(api.middleware)
    import api.routers.api_keys
    importlib.reload(api.routers.api_keys)
    import api.main
    importlib.reload(api.main)
    from api.main import app
    return TestClient(app)


class TestKeyRouter:
    MASTER_HEADER = {"Authorization": "Bearer master-test-key-12345"}

    def test_create_key_via_api(self, api_client):
        resp = api_client.post(
            "/api/keys",
            json={"name": "router-test", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"].startswith("sk-router-test-")
        assert data["id"].startswith("key_")

    def test_list_keys_via_api(self, api_client):
        resp = api_client.get("/api/keys", headers=self.MASTER_HEADER)
        assert resp.status_code == 200
        keys = resp.json()
        assert isinstance(keys, list)
        assert len(keys) >= 1
        for k in keys:
            assert "key_hash" not in k

    def test_create_key_requires_master_key(self, api_client):
        resp = api_client.post(
            "/api/keys",
            json={"name": "unauth", "scopes": ["chat"]},
        )
        assert resp.status_code == 401

    def test_revoke_key_via_api(self, api_client):
        create_resp = api_client.post(
            "/api/keys",
            json={"name": "to-delete", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        key_id = create_resp.json()["id"]
        del_resp = api_client.delete(
            f"/api/keys/{key_id}", headers=self.MASTER_HEADER
        )
        assert del_resp.status_code == 200

    def test_usage_endpoint(self, api_client):
        create_resp = api_client.post(
            "/api/keys",
            json={"name": "usage-key", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        key_id = create_resp.json()["id"]
        resp = api_client.get(
            f"/api/keys/{key_id}/usage", headers=self.MASTER_HEADER
        )
        assert resp.status_code == 200
        assert resp.json()["total_requests"] == 0


class TestMultiKeyAuth:
    """Test that created keys work for authenticating API requests"""

    MASTER_HEADER = {"Authorization": "Bearer master-test-key-12345"}

    def test_created_key_authenticates_models(self, api_client):
        # Create a key with chat scope
        resp = api_client.post(
            "/api/keys",
            json={"name": "auth-test", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        raw_key = resp.json()["key"]

        # Use it to access /v1/models
        resp = api_client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200

    def test_revoked_key_rejected(self, api_client):
        resp = api_client.post(
            "/api/keys",
            json={"name": "revoke-auth", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        raw_key = resp.json()["key"]
        key_id = resp.json()["id"]

        # Revoke it
        api_client.delete(f"/api/keys/{key_id}", headers=self.MASTER_HEADER)

        # Should be rejected
        resp = api_client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 401


def test_require_master_helper_lives_in_middleware():
    """Smoke: helper is importable from middleware so plugins.py can use it."""
    from api.middleware import require_master_key
    assert callable(require_master_key)
