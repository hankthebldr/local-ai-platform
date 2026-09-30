"""Theme B — the first-run master key is handed to LOOPBACK only.

`GET /api/setup/local-license` returns the operator's first-run MASTER key so
the SPA can auto-sign-in on first boot. It gated on `ip.is_private`, which
Python's ipaddress defines as RFC1918 **plus** 169.254.0.0/16 link-local **plus
100.64.0.0/10** — the CGNAT range Tailscale hands out. So on any box joined to
a tailnet or sitting on a shared LAN, every peer could simply GET the master
key. That is exactly the exposure the 1.4.x fleet work will widen.

Now: loopback by default, and LAN / Docker-bridge / tailnet peers only with an
explicit `ENCLAVE_TRUST_PRIVATE_NET=true` opt-in (which docker-compose.yml
sets for its own bridge topology).
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def key_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "first-run-key.txt").write_text("enc_master_secret", encoding="utf-8")
    monkeypatch.setenv("DATA_CONFIG_DIR", str(cfg))
    return cfg


@pytest.fixture()
def app(key_file, monkeypatch):
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    monkeypatch.delenv("ENCLAVE_TRUST_PRIVATE_NET", raising=False)
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    return api.main.app


def _get(app, host: str, headers: dict | None = None):
    """Drive the endpoint as if the peer address were `host`.

    TestClient reports ('testclient', 50000) as the peer by default, which
    parses as neither an IP nor 'localhost' — so every request would be
    refused and every assertion would pass vacuously. Its `client=` tuple is
    written straight into scope["client"], which is what request.client.host
    (and therefore _is_local_client) reads.
    """
    with TestClient(app, client=(host, 12345)) as c:
        return c.get("/api/setup/local-license", headers=headers or {})


def test_harness_really_sets_the_peer_address(app):
    """Guard the guard: if `client=` ever stopped reaching scope["client"],
    every refusal test above would pass for the wrong reason."""
    with TestClient(app, client=("203.0.113.77", 1234)) as c:
        r = c.get("/api/setup/echo-peer-probe")
    # No such route — but the point is the request was built and dispatched
    # with our peer; the positive-path assertions below prove the value lands.
    assert r.status_code == 404
    assert (
        _get(app, "127.0.0.1").status_code == 200
    ), "peer injection is not reaching request.client.host"


# ── loopback is always trusted ─────────────────────────────────────────────


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.53", "::1", "localhost"])
def test_loopback_peers_get_the_key(app, host):
    r = _get(app, host)
    assert r.status_code == 200, f"{host} should be trusted: {r.text}"
    assert r.json()["key"] == "enc_master_secret"


def test_ipv4_mapped_loopback_is_trusted(app):
    """A dual-stack listener reports ::ffff:127.0.0.1; ip.is_loopback is False
    for that, so it must be unwrapped or local first-run silently 403s."""
    assert _get(app, "::ffff:127.0.0.1").status_code == 200


# ── private / tailnet peers are refused by default ─────────────────────────


@pytest.mark.parametrize(
    "host,why",
    [
        ("192.168.1.50", "RFC1918 LAN peer"),
        ("10.0.0.9", "RFC1918 LAN peer"),
        ("172.17.0.5", "Docker bridge"),
        ("100.101.102.103", "Tailscale CGNAT 100.64.0.0/10"),
        ("169.254.10.10", "link-local"),
        ("fd00::1", "IPv6 unique-local"),
    ],
)
def test_private_peers_are_refused_by_default(app, host, why):
    r = _get(app, host)
    assert r.status_code == 403, f"{why} ({host}) must not receive the master key"


def test_public_peer_is_refused(app):
    assert _get(app, "8.8.8.8").status_code == 403


# ── the explicit opt-in restores the private-net path ──────────────────────


@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes", "on"])
def test_opt_in_allows_private_peers(app, monkeypatch, flag):
    monkeypatch.setenv("ENCLAVE_TRUST_PRIVATE_NET", flag)
    assert (
        _get(app, "172.17.0.5").status_code == 200
    ), "the Docker-compose bridge topology must still work with the opt-in"
    assert _get(app, "192.168.1.50").status_code == 200


def test_opt_in_still_refuses_public_peers(app, monkeypatch):
    """The opt-in widens to private ranges — never to the whole internet."""
    monkeypatch.setenv("ENCLAVE_TRUST_PRIVATE_NET", "true")
    assert _get(app, "8.8.8.8").status_code == 403


def test_opt_in_is_read_at_call_time(app, monkeypatch):
    """Read per-request, not at import — otherwise the setting silently needs
    a restart and tests/config changes appear to do nothing."""
    assert _get(app, "10.0.0.9").status_code == 403
    monkeypatch.setenv("ENCLAVE_TRUST_PRIVATE_NET", "true")
    assert _get(app, "10.0.0.9").status_code == 200
    monkeypatch.setenv("ENCLAVE_TRUST_PRIVATE_NET", "false")
    assert _get(app, "10.0.0.9").status_code == 403


# ── a proxied request is never trusted (GP-2 P0-14, still holds) ───────────


@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "X-Real-IP"])
def test_forwarding_header_refuses_even_from_loopback(app, header):
    """Behind a reverse proxy the peer IS loopback but the real client is
    unknown — the strongest signal we have that we cannot prove locality."""
    r = _get(app, "127.0.0.1", headers={header: "203.0.113.9"})
    assert r.status_code == 403, f"{header} must force a refusal"


def test_forwarding_header_refuses_even_with_the_opt_in(app, monkeypatch):
    monkeypatch.setenv("ENCLAVE_TRUST_PRIVATE_NET", "true")
    r = _get(app, "172.17.0.5", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 403


# ── the compose topology documents its own opt-in ─────────────────────────


def test_docker_compose_sets_the_opt_in():
    """Loopback-only would break Docker Compose first-run auto-sign-in (the
    container sees a bridge peer). Compose is an operator-controlled local
    topology, so it opts in explicitly rather than the default being weak."""
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "ENCLAVE_TRUST_PRIVATE_NET" in compose, (
        "docker-compose.yml must set ENCLAVE_TRUST_PRIVATE_NET or its "
        "first-run auto-sign-in breaks under the new loopback-only default"
    )
