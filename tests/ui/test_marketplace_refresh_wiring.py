"""Theme B — the operator keeps a way to pull the remote catalogs.

Making GET egress-free is only half the change: if nothing in the UI can reach
the new refresh routes, the marketplaces silently freeze at whatever the cache
holds. These pin the affordances.

The shell contract is unchanged and deliberately so — `adapter.load()` is a
READ and must never call a refresh route (already pinned by
`test_skills_shell.py::test_skills_refresh_discovery_is_operator_triggered_only`).
The fetch belongs in the operator-triggered path instead.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[2] / "api" / "static" / "js" / "library"
SKILLS_JS = (JS / "skills.js").read_text(encoding="utf-8")
MCP_JS = (JS / "mcp.js").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    m = re.search(rf"async function {name}\((.*?)\n  }}", src, re.S)
    assert m, f"{name}() not found"
    return m.group(0)


# ── skills: the existing ⟳ now refreshes BOTH remote sources ───────────────


def test_skills_refresh_pulls_the_configured_catalog_url():
    """`ENCLAVE_SKILLS_CATALOG_URL` used to be fetched by a stale-TTL read.
    Its refresh now rides the operator's existing ⟳ alongside skills.sh."""
    body = _fn(SKILLS_JS, "refreshDiscovery")
    assert "/api/skills/discover/refresh" in body, (
        "the ⟳ no longer refreshes the configured catalog URL, so that "
        "marketplace can never update now that reads are egress-free"
    )
    assert "/api/discover/skills-sh/refresh" in body, "skills.sh refresh lost"
    # A refresh egresses — a retry would double-fetch the marketplace.
    assert body.count("retries: 0") >= 2


def test_skills_catalog_refresh_is_failsoft_and_precedes_the_reread():
    """A dead/absent catalog URL must not abort the refresh, and the fetch has
    to be awaited before load() or the re-read serves the pre-refresh cache."""
    body = _fn(SKILLS_JS, "refreshDiscovery")
    catalog_at = body.index("/api/skills/discover/refresh")
    assert (
        "catch (_)" in body[catalog_at : catalog_at + 400]
    ), "the catalog refresh must be fail-soft"
    assert (
        body.index("await load()") > catalog_at
    ), "load() must re-read AFTER the refresh fills the cache"


def test_skills_adapter_load_stays_a_pure_read():
    """Belt and braces with the existing shell test: no refresh route inside
    the adapter's load(), or opening the tab egresses again."""
    m = re.search(r"async load\((.*?)\n    },", SKILLS_JS, re.S)
    assert m and "/refresh" not in m.group(1)


# ── mcp: a ⟳ in the marketplace modal ──────────────────────────────────────


def test_mcp_marketplace_modal_has_a_refresh_control():
    assert 'data-action="mcp.mkt-refresh"' in MCP_JS, (
        "the MCP marketplace modal has no ⟳, so a configured remote catalog "
        "can never be pulled now that its GET is egress-free"
    )
    assert "'mcp.mkt-refresh':" in MCP_JS, "mcp.mkt-refresh has no handler"


def test_mcp_refresh_posts_the_refresh_route_once():
    body = _fn(MCP_JS, "refreshMarketplace")
    assert "/api/mcp/discover/refresh" in body
    assert "method: 'POST'" in body
    assert "retries: 0" in body, "a refresh egresses — never double-fetch"
    assert "catch (_)" in body, "a dead remote must leave the local catalog up"


def test_mcp_refresh_tears_down_its_own_overlay_before_reopening():
    """The marketplace is a dynamically-created `.mcp-mkt-overlay`, NOT the
    `#mcp-edit-modal` that _closeModal() hides — closing the wrong one stacks
    a second overlay on every refresh click."""
    body = _fn(MCP_JS, "refreshMarketplace")
    assert ".mcp-mkt-overlay" in body
    assert (
        "_closeModal()" not in body
    ), "_closeModal() hides #mcp-edit-modal, not the marketplace overlay"
    assert body.index(".mcp-mkt-overlay") < body.index("await browseMarketplace()")


def test_mcp_marketplace_read_path_does_not_refresh():
    """Opening the modal is a read: it GETs the catalog and must not POST."""
    body = _fn(MCP_JS, "browseMarketplace")
    assert "/api/mcp/discover'" in body or '"/api/mcp/discover"' in body
    assert "/api/mcp/discover/refresh" not in body
