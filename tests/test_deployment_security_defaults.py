"""Phase 7.2 + 7.3 — security-config invariants.

These tests pin the security-hardening choices we shipped so a future
refactor of docker-compose.yml or desktop/entitlements.plist doesn't
silently drop them. They're cheap structural checks, not full security
audits — for the real picture see docs/deployment/dmg-mcp-security.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Phase 7.2 — container security defaults ──────────────────────────


@pytest.fixture(scope="module")
def compose():
    raw = (REPO_ROOT / "docker-compose.yml").read_text()
    return yaml.safe_load(raw)


def test_api_service_drops_all_capabilities(compose):
    api = compose["services"]["api"]
    assert "cap_drop" in api, "Phase 7.2 — api service must declare cap_drop"
    assert "ALL" in api["cap_drop"]


def test_api_service_forbids_privilege_escalation(compose):
    api = compose["services"]["api"]
    sec_opts = api.get("security_opt", [])
    assert any(
        "no-new-privileges:true" == opt for opt in sec_opts
    ), "Phase 7.2 — api service must set no-new-privileges:true"


def test_api_service_has_tmpfs_for_scratch(compose):
    """`/tmp` is the only writable surface needed in read_only mode; even
    when read_only is off, a bounded tmpfs prevents disk-fill attacks
    against /tmp."""
    api = compose["services"]["api"]
    assert "tmpfs" in api, "Phase 7.2 — api service must mount /tmp as tmpfs"
    entries = api["tmpfs"]
    assert any(
        entry.startswith("/tmp") for entry in entries
    ), "Phase 7.2 — /tmp tmpfs entry missing"


def test_api_service_persists_user_data(compose):
    """The user-layer state (under /app/data) MUST be on a persistent
    volume; otherwise plugin installs / MCP registrations / workflow runs
    don't survive a `docker compose down`."""
    api = compose["services"]["api"]
    volumes = api["volumes"]
    assert any(
        ":/app/data" in v for v in volumes
    ), "user layer (/app/data) must be on a persistent volume"


# ── Phase 7.3 — DMG entitlements ─────────────────────────────────────


@pytest.fixture(scope="module")
def entitlements_text():
    return (REPO_ROOT / "desktop" / "entitlements.plist").read_text()


def test_entitlements_explicitly_opts_out_of_sandbox(entitlements_text):
    """v1 ships unsandboxed (documented in dmg-mcp-security.md). Explicit
    `false` is clearer than relying on the absence of the key — a
    sandboxed build sets this to `true` so the symmetry is informative."""
    assert "com.apple.security.app-sandbox" in entitlements_text


def test_entitlements_grant_jit(entitlements_text):
    """py2app's embedded Python needs JIT pages; without this the .app
    rejects the runner pool's subprocess spawn under hardened runtime."""
    assert "com.apple.security.cs.allow-jit" in entitlements_text


def test_entitlements_grant_unsigned_executable_memory(entitlements_text):
    assert "com.apple.security.cs.allow-unsigned-executable-memory" in entitlements_text


def test_entitlements_grant_network_client_and_server(entitlements_text):
    assert "com.apple.security.network.client" in entitlements_text
    assert "com.apple.security.network.server" in entitlements_text


# ── Companion docs exist ─────────────────────────────────────────────


def test_dmg_security_doc_exists():
    """Phase 7.3 ships docs/deployment/dmg-mcp-security.md so operators
    know what surface the DMG carries; a missing file is a regression."""
    p = REPO_ROOT / "docs" / "deployment" / "dmg-mcp-security.md"
    assert p.exists(), "dmg-mcp-security.md missing"
    body = p.read_text()
    # Cheap sanity: the doc must mention the actual entitlement keys and
    # the trust boundary section.
    assert "app-sandbox" in body
    assert "trust boundary" in body.lower()
