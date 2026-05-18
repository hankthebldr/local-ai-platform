#!/usr/bin/env python3
"""Official MCP Registry provider.

Pulls the centralized metadata for community-built MCP servers from
the official registry at modelcontextprotocol.io. The registry exposes
a REST API with an OpenAPI specification — when reachable we fetch
``/v0/servers`` (the listing endpoint per the spec) and project each
record into the platform's unified ``DiscoveryItem`` shape.

The endpoint shape is documented at https://registry.modelcontextprotocol.io/openapi.json
and follows roughly:

  GET https://registry.modelcontextprotocol.io/v0/servers?limit=50
  ->
  {
    "servers": [
      {
        "id": "io.github.modelcontextprotocol/brave-search",
        "name": "brave-search",
        "description": "Web + local search via Brave Search API",
        "repository": { "url": "https://github.com/.../brave-search" },
        "version": "0.1.0",
        "packages": [...]
      },
      ...
    ],
    "next": "<cursor>"
  }

Because the registry is community-facing and the precise field names
may evolve, this provider does defensive shape-checking on every
attribute and falls back to ``unknown`` rather than crashing the feed.
Network failures bubble up as an error string on the DiscoveryFeed so
the UI can show a clear status.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

from ..agentic_discovery import DiscoveryFeed, DiscoveryItem, register_provider

REGISTRY_BASE = os.getenv(
    "MCP_REGISTRY_BASE", "https://registry.modelcontextprotocol.io"
)
REGISTRY_LIMIT = int(os.getenv("MCP_REGISTRY_LIMIT", "60"))
REGISTRY_TIMEOUT = float(os.getenv("MCP_REGISTRY_TIMEOUT", "10"))


def _safe_get(d: Dict[str, Any], *path, default=None):
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _to_item(raw: Dict[str, Any]) -> DiscoveryItem:
    """Project one registry record into a DiscoveryItem."""
    # Identifier — prefer the canonical reverse-DNS id when present.
    item_id = raw.get("id") or raw.get("identifier") or raw.get("name") or "unknown"
    # Canonical URL — repository URL if available, otherwise homepage.
    url = (
        _safe_get(raw, "repository", "url", default="")
        or raw.get("homepage", "")
        or raw.get("source_url", "")
        or ""
    )
    install: Dict[str, Any] = {}
    # Many records list one or more "packages" with installation hints
    # (npm name, docker image, pypi package). Pass them through so the
    # UI can render the right one-liner per platform.
    packages = raw.get("packages") or []
    if isinstance(packages, list) and packages:
        install["packages"] = packages
    # Tools — when present, the registry record names them; otherwise
    # the platform discovers them at MCP-handshake time. We pass them
    # along under the same key our other providers use so the UI's
    # tool chips render uniformly.
    tools_raw = raw.get("tools") or []
    tools: List[Dict[str, Any]] = []
    if isinstance(tools_raw, list):
        for t in tools_raw:
            if isinstance(t, dict):
                tools.append(
                    {
                        "name": t.get("name") or t.get("id") or "tool",
                        "description": t.get("description") or "",
                    }
                )

    metadata = {
        "author": _safe_get(raw, "publisher", "name", default=raw.get("author", "")),
        "tags": raw.get("tags") or raw.get("categories") or [],
        "license": _safe_get(raw, "license") or "unknown",
        "downloads": raw.get("downloads", 0),
        "rating": raw.get("rating"),
    }

    return DiscoveryItem(
        id=str(item_id),
        source="mcp-registry",
        kind="mcp",
        name=raw.get("name") or str(item_id),
        description=raw.get("description") or "",
        version=raw.get("version") or "unknown",
        url=url,
        install=install,
        tools=tools,
        resources=[],
        prompts=[],
        metadata=metadata,
    )


def fetch() -> DiscoveryFeed:
    """Hit the official registry and return a populated feed."""
    url = f"{REGISTRY_BASE.rstrip('/')}/v0/servers"
    params = {"limit": REGISTRY_LIMIT}
    items: List[DiscoveryItem] = []
    error = None
    try:
        r = requests.get(url, params=params, timeout=REGISTRY_TIMEOUT)
        if r.status_code != 200:
            error = f"registry returned HTTP {r.status_code}"
        else:
            data = r.json()
            # Tolerate both shapes — `servers: [...]` and a bare list.
            raw_list = data.get("servers") if isinstance(data, dict) else data
            if not isinstance(raw_list, list):
                error = "registry response missing 'servers' array"
                raw_list = []
            for raw in raw_list[:REGISTRY_LIMIT]:
                if not isinstance(raw, dict):
                    continue
                try:
                    items.append(_to_item(raw))
                except Exception as exc:  # noqa: BLE001
                    # Skip a single bad record rather than failing the feed.
                    continue
    except requests.RequestException as exc:
        error = f"network: {exc.__class__.__name__}: {exc}"

    return DiscoveryFeed(
        source="mcp-registry",
        name="MCP Registry (official)",
        description=(
            "Centralized metadata for community-built MCP servers. "
            "Backed by Anthropic / GitHub / Microsoft."
        ),
        homepage="https://modelcontextprotocol.io/registry",
        kinds=["mcp"],
        implemented=True,
        items=items,
        error=error,
    )


register_provider(
    source="mcp-registry",
    name="MCP Registry (official)",
    description=(
        "Centralized metadata for community-built MCP servers. "
        "Backed by Anthropic / GitHub / Microsoft."
    ),
    homepage="https://modelcontextprotocol.io/registry",
    kinds=["mcp"],
    fetch=fetch,
    implemented=True,
)
