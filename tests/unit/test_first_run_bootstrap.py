"""Tests for first-run API key auto-provisioning."""


import pytest

from api.services.api_key_service import (
    ALL_SCOPES,
    APIKeyService,
    bootstrap_first_run_key,
)


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    """Empty keystore in an isolated tmp dir; neutralizes API_KEY env.

    Set API_KEY to "" rather than deleting it: importing ``api.middleware``
    (which the scope test does in its body) runs ``load_dotenv()`` at import
    time, and the repo's ``.env`` carries a placeholder ``API_KEY``. With the
    var deleted, a load_dotenv triggered *after* this fixture would repopulate
    it and make ``bootstrap_first_run_key`` think a legacy key is pinned —
    failing depending on module import order. An empty string is already
    present (so ``load_dotenv(override=False)`` won't touch it) and is falsy
    (so bootstrap still provisions). Order-independent.
    """
    monkeypatch.setenv("API_KEY", "")
    return APIKeyService(config_dir=str(tmp_path))


def test_bootstrap_creates_key_when_store_empty(fresh_keystore):
    result = bootstrap_first_run_key(fresh_keystore)
    assert result is not None
    assert result["name"] == "first-run-master"
    assert set(result["scopes"]) == set(ALL_SCOPES)
    assert result["key"].startswith("sk-first-run-master-")
    # Key should now be retrievable via validate_key
    meta = fresh_keystore.validate_key(result["key"])
    assert meta is not None
    assert meta["name"] == "first-run-master"


def test_bootstrap_is_idempotent(fresh_keystore):
    first = bootstrap_first_run_key(fresh_keystore)
    assert first is not None
    second = bootstrap_first_run_key(fresh_keystore)
    assert second is None, "second call must be a no-op when keys exist"


def test_bootstrap_skipped_when_legacy_api_key_set(fresh_keystore, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-legacy-pinned")
    assert bootstrap_first_run_key(fresh_keystore) is None
    assert fresh_keystore.list_keys() == []


def test_bootstrap_skipped_when_other_keys_already_exist(fresh_keystore):
    # Manually pre-populate the keystore.
    fresh_keystore.create_key(name="ops-pre-existing", scopes=["chat"])
    result = bootstrap_first_run_key(fresh_keystore)
    assert result is None
    # The pre-existing key is intact.
    keys = fresh_keystore.list_keys()
    assert len(keys) == 1
    assert keys[0]["name"] == "ops-pre-existing"


def test_provisioned_key_has_all_scopes_required_by_middleware(fresh_keystore):
    """
    The first-run key must cover every scope the middleware enforces, or the
    operator will get 403s on freshly provisioned installs.
    """
    from api.middleware import SCOPE_MAP

    result = bootstrap_first_run_key(fresh_keystore)
    assert result is not None
    granted = set(result["scopes"])
    required = set(SCOPE_MAP.values())
    missing = required - granted
    assert not missing, f"first-run key missing scopes used by middleware: {missing}"
