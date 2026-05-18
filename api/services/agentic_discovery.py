#!/usr/bin/env python3
"""
Agentic Discovery Service — unified ingestion for external sources of
MCP servers, system prompts, plugins, and other agentic building blocks.

Distinct from ``discovery_service.py`` (which focuses on HuggingFace
model discovery). This module manages the **schema + provider
registry** for everything else the platform can pull from upstream
registries — the official MCP Registry, Smithery, GitHub's
.prompt.yaml initiative, Composio, etc.

Per the user's "schema uniformity" recommendation, every provider
maps incoming records into the same ``DiscoveryItem`` shape, which is
a thin superset of the official MCP capability set (tools / resources
/ prompts). The UI can then render any provider's items with one
grammar.

  DiscoveryItem
    .id           : str   — source-unique stable identifier
    .source       : str   — provider id ("mcp-registry", "smithery", …)
    .kind         : str   — "mcp" | "plugin" | "prompt" | "skill" | "tool"
    .name         : str
    .description  : str
    .version      : str   — semver or "unknown"
    .url          : str   — canonical link (repo, registry entry, …)
    .install      : dict  — provider-specific install spec
    .tools        : list  — MCP-shaped tool definitions
    .resources    : list  — MCP-shaped resource definitions
    .prompts      : list  — MCP-shaped prompt definitions
    .metadata     : dict  — author, tags, license, rating, downloads, …

Providers are pure functions registered in ``register_provider``. Each
returns a ``DiscoveryFeed`` containing the list of items plus health
flags (``implemented``, ``last_synced``, ``error``). Feeds are cached
in-process for ``CACHE_TTL`` seconds — discovery requests are I/O-
bound and we don't want to fan out to every upstream on every page hit.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..logging_config import logger

CACHE_TTL = 300  # seconds — discovery feeds cache for 5 min


# ── Unified schema ───────────────────────────────────────────────────


@dataclass
class DiscoveryItem:
    """One installable item from any external source."""

    id: str
    source: str
    kind: str  # 'mcp' | 'plugin' | 'prompt' | 'skill' | 'tool'
    name: str
    description: str = ""
    version: str = "unknown"
    url: str = ""
    install: Dict[str, Any] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    prompts: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiscoveryFeed:
    """A provider's complete feed at a point in time."""

    source: str
    name: str
    description: str
    homepage: str
    kinds: List[str]  # the kinds of items this provider returns
    implemented: bool  # False for stubbed providers
    items: List[DiscoveryItem] = field(default_factory=list)
    last_synced: float = 0.0  # unix timestamp
    error: Optional[str] = None

    def to_dict(self, *, with_items: bool = True) -> Dict[str, Any]:
        d = {
            "source": self.source,
            "name": self.name,
            "description": self.description,
            "homepage": self.homepage,
            "kinds": self.kinds,
            "implemented": self.implemented,
            "last_synced": self.last_synced,
            "error": self.error,
            "count": len(self.items),
        }
        if with_items:
            d["items"] = [i.to_dict() for i in self.items]
        return d


# ── Provider registry ────────────────────────────────────────────────


class _ProviderEntry:
    """One registered provider + its lazy fetch + cache state."""

    def __init__(
        self,
        source: str,
        name: str,
        description: str,
        homepage: str,
        kinds: List[str],
        fetch: Callable[[], DiscoveryFeed],
        implemented: bool = True,
    ):
        self.source = source
        self.name = name
        self.description = description
        self.homepage = homepage
        self.kinds = kinds
        self.fetch = fetch
        self.implemented = implemented
        self._cached: Optional[DiscoveryFeed] = None
        self._fetched_at: float = 0.0

    def get(self, *, force: bool = False) -> DiscoveryFeed:
        """Return the feed, using the cache when fresh."""
        now = time.time()
        if (
            not force
            and self._cached is not None
            and now - self._fetched_at < CACHE_TTL
        ):
            return self._cached
        try:
            feed = self.fetch()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discovery provider %s failed: %s", self.source, exc)
            feed = DiscoveryFeed(
                source=self.source,
                name=self.name,
                description=self.description,
                homepage=self.homepage,
                kinds=self.kinds,
                implemented=self.implemented,
                last_synced=now,
                error=str(exc),
            )
        feed.last_synced = now
        self._cached = feed
        self._fetched_at = now
        return feed


_REGISTRY: Dict[str, _ProviderEntry] = {}


def register_provider(
    source: str,
    name: str,
    description: str,
    homepage: str,
    kinds: List[str],
    fetch: Callable[[], DiscoveryFeed],
    implemented: bool = True,
) -> None:
    _REGISTRY[source] = _ProviderEntry(
        source=source,
        name=name,
        description=description,
        homepage=homepage,
        kinds=kinds,
        fetch=fetch,
        implemented=implemented,
    )


def list_providers() -> List[Dict[str, Any]]:
    """Return metadata for every registered provider (no item fetch)."""
    return [
        {
            "source": p.source,
            "name": p.name,
            "description": p.description,
            "homepage": p.homepage,
            "kinds": p.kinds,
            "implemented": p.implemented,
            "last_synced": p._fetched_at,
            "cached_count": (len(p._cached.items) if p._cached else 0),
        }
        for p in _REGISTRY.values()
    ]


def get_feed(source: str, *, force: bool = False) -> DiscoveryFeed:
    if source not in _REGISTRY:
        raise KeyError(source)
    return _REGISTRY[source].get(force=force)


def get_all_feeds(*, force: bool = False) -> List[Dict[str, Any]]:
    """Fetch every provider's feed (serial; parallel-safe upstream)."""
    return [p.get(force=force).to_dict() for p in _REGISTRY.values()]


def stub_fetch(
    source: str,
    name: str,
    description: str,
    homepage: str,
    kinds: List[str],
    note: str = "provider stub — ingestion pipeline not yet wired",
):
    """Return a fetch() that produces an empty feed marked unimplemented.

    The UI surfaces these so operators can see what's *possible* even
    before the pipeline is live. The ``note`` becomes the feed's
    error string so we don't need a separate "status" field on the
    UI side.
    """

    def _fetch():
        return DiscoveryFeed(
            source=source,
            name=name,
            description=description,
            homepage=homepage,
            kinds=kinds,
            implemented=False,
            items=[],
            error=note,
        )

    return _fetch


# ── Provider registration ────────────────────────────────────────────
#
# Importing the providers package registers each one. Kept at the
# bottom so the helpers above are defined first.

from . import discovery_providers  # noqa: E402, F401  (registers)
