"""Theme B — read-route auth sweep: no data surface is scope-less.

A path with no `SCOPE_MAP` prefix is gated by base authentication only, which
means *any* valid key reaches it when auth is on — including a key minted for
`chat` alone. Three data surfaces were in that state:

  · `/api/provenance`    — what every grounded answer was grounded on
  · `/api/agents`        — agent definitions (create / update / delete)
  · `/api/conversations` — saved chat threads, transcripts included

Each now rides the scope of its nearest already-gated sibling rather than
minting a new scope name. That constraint is load-bearing, not cosmetic:
`bootstrap_first_run_key` mints `ALL_SCOPES`, so a scope name outside that list
would 403 every key already in the field. `test_every_mapped_scope_is_grantable`
below pins it for future entries too.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

# (prefix, a real GET path under it, the scope it must require)
GATED_READ_ROUTES = [
    ("/api/provenance", "/api/provenance/responses", "workflows"),
    ("/api/agents", "/api/agents", "workflows"),
    ("/api/conversations", "/api/conversations", "exports"),
]


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    """Auth-enabled client plus a scoped and an unscoped key."""
    cfg = tmp_path / "keycfg"
    cfg.mkdir()
    monkeypatch.setenv("DATA_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("ENCLAVE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_API_AUTH", "true")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MASTER_API_KEY", raising=False)

    from api.services.api_key_service import APIKeyService

    svc = APIKeyService(config_dir=str(cfg))
    keys = {
        "workflows": svc.create_key(name="wf", scopes=["workflows"])["key"],
        "exports": svc.create_key(name="ex", scopes=["exports"])["key"],
        # A legitimate key that simply holds a different scope.
        "chat_only": svc.create_key(name="chatonly", scopes=["chat"])["key"],
    }

    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    try:
        yield TestClient(app), keys
    finally:
        os.environ["ENABLE_API_AUTH"] = "false"


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.parametrize("prefix,path,scope", GATED_READ_ROUTES)
def test_route_is_in_the_scope_map(prefix, path, scope):
    from api.middleware import SCOPE_MAP

    assert SCOPE_MAP.get(prefix) == scope, (
        f"{prefix} must require the '{scope}' scope — without an entry it is "
        "reachable by any valid key"
    )


@pytest.mark.parametrize("prefix,path,scope", GATED_READ_ROUTES)
def test_unscoped_key_is_refused(auth_client, prefix, path, scope):
    client, keys = auth_client
    r = client.get(path, headers=_auth(keys["chat_only"]))
    assert (
        r.status_code == 403
    ), f"a chat-only key reached {path} (status {r.status_code})"
    assert r.json()["error"]["code"] == "insufficient_scope"


@pytest.mark.parametrize("prefix,path,scope", GATED_READ_ROUTES)
def test_correctly_scoped_key_passes_the_gate(auth_client, prefix, path, scope):
    client, keys = auth_client
    r = client.get(path, headers=_auth(keys[scope]))
    # Past the gate. The handler itself may 404/500 on an empty tmp store —
    # what matters is that auth did not reject it.
    assert r.status_code not in (401, 403), f"{path} rejected a {scope} key: {r.text}"


@pytest.mark.parametrize("prefix,path,scope", GATED_READ_ROUTES)
def test_no_key_at_all_is_401(auth_client, prefix, path, scope):
    client, _ = auth_client
    assert client.get(path).status_code == 401


def test_every_mapped_scope_is_grantable():
    """A SCOPE_MAP entry naming a scope outside ALL_SCOPES is a silent lockout:
    the bootstrap master key wouldn't carry it, so the surface would 403 for
    every key in the field. Pins the invariant for future entries."""
    from api.middleware import SCOPE_MAP
    from api.services.api_key_service import ALL_SCOPES

    unknown = {s for s in SCOPE_MAP.values() if s not in ALL_SCOPES}
    assert not unknown, (
        f"SCOPE_MAP references scopes no key can hold: {sorted(unknown)} — "
        f"add them to ALL_SCOPES or reuse an existing scope"
    )


def test_bootstrap_master_key_reaches_every_gated_surface(auth_client):
    """The first-run key is minted with ALL_SCOPES, so the SPA must still
    reach every newly-gated surface — this sweep tightens third-party keys,
    not the operator's own console."""
    client, _ = auth_client
    from api.services.api_key_service import ALL_SCOPES, APIKeyService

    svc = APIKeyService(config_dir=os.environ["DATA_CONFIG_DIR"])
    master = svc.create_key(name="all", scopes=ALL_SCOPES)["key"]
    for _prefix, path, _scope in GATED_READ_ROUTES:
        r = client.get(path, headers=_auth(master))
        assert r.status_code not in (401, 403), f"{path} refused an ALL_SCOPES key"
