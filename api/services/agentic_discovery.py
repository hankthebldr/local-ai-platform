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

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..logging_config import logger

CACHE_TTL = 300  # seconds — default feed cache when the config has no override


# ── Discovery sources config (LB0-U2) ────────────────────────────────
#
# ``data/config/discovery_sources.json`` is the single operator-owned
# source of truth for every fetch-source knob: the skills-sh repo
# allowlist, plugin marketplace allowlists, prompt-digest sources,
# remote catalog URLs, per-source cache TTLs (the max age applied to
# operator-triggered refreshes — nothing here is a poller), and an
# optional GitHub token. Merge order: file > env > default (the
# search_settings pattern). Providers consult it AT FETCH TIME — never
# at import-time registration — so a PUT via ``/api/discover/config``
# takes effect without a restart.

_CONFIG_DIR = Path(__file__).parent.parent.parent / "data" / "config"
_SOURCES_CONFIG_FILE = _CONFIG_DIR / "discovery_sources.json"

# 'config' is reserved so GET /api/discover/config can never collide
# with a provider feed at GET /api/discover/{source}.
RESERVED_SOURCES = frozenset({"config"})

DEFAULT_SKILL_REPOS = [
    "anthropics/skills",
    "obra/superpowers",
    "vercel-labs/skills",
]
DEFAULT_PLUGIN_MARKETPLACES = [
    "anthropics/claude-plugins-official",
    "anthropics/claude-code",
    "anthropics/skills",
    "anthropics/knowledge-work-plugins",
]
DEFAULT_PROMPT_DIGEST_SOURCES = [
    "anthropics/claude-cookbooks",
    "openai/openai-cookbook",
    "google-gemini/cookbook",
]


def _env_csv(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    return [r.strip() for r in raw.split(",") if r.strip()] if raw else []


def _read_sources_file() -> Dict[str, Any]:
    """Raw file layer (no env/default merge). {} when absent or corrupt."""
    try:
        if _SOURCES_CONFIG_FILE.exists():
            data = json.loads(_SOURCES_CONFIG_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001 — corrupt file degrades to env/defaults
        logger.warning("discovery_sources.json unreadable — using env/defaults")
    return {}


def load_sources_config() -> Dict[str, Any]:
    """Effective source config: file > env > default.

    Cheap enough to call on every fetch — which is exactly the point:
    a PUT through the admin route is live on the very next refresh.
    """
    f = _read_sources_file()
    urls = f.get("catalog_urls") if isinstance(f.get("catalog_urls"), dict) else {}
    ttls = f.get("cache_ttls") if isinstance(f.get("cache_ttls"), dict) else {}
    return {
        "skill_repos": list(
            f.get("skill_repos")
            or _env_csv("ENCLAVE_SKILL_REPOS")
            or DEFAULT_SKILL_REPOS
        ),
        "plugin_marketplaces": list(
            f.get("plugin_marketplaces") or DEFAULT_PLUGIN_MARKETPLACES
        ),
        "prompt_digest_sources": list(
            f.get("prompt_digest_sources") or DEFAULT_PROMPT_DIGEST_SOURCES
        ),
        "catalog_urls": {
            "skills": (urls.get("skills") or "").strip()
            or os.getenv("ENCLAVE_SKILLS_CATALOG_URL", "").strip(),
            "mcp": (urls.get("mcp") or "").strip()
            or os.getenv("ENCLAVE_MCP_CATALOG_URL", "").strip(),
        },
        "cache_ttls": {"default": CACHE_TTL, **ttls},
        "github_token": (
            f.get("github_token")
            or os.getenv("ENCLAVE_GITHUB_TOKEN", "").strip()
            or os.getenv("GITHUB_TOKEN", "").strip()
        ),
    }


def masked_sources_config() -> Dict[str, Any]:
    """Effective config with the token masked — the only shape the API
    ever returns on read. The raw token never leaves the box."""
    cfg = load_sources_config()
    tok = cfg.pop("github_token", "") or ""
    cfg["github_token_set"] = bool(tok)
    cfg["github_token_masked"] = (
        f"***{tok[-4:]}" if len(tok) > 4 else ("set" if tok else "")
    )
    return cfg


def update_sources_config(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Merge operator-provided fields over the FILE layer and persist.

    Only keys present in ``changes`` are written; untouched knobs keep
    falling through to env/default. Token semantics: absent/None → keep,
    masked echo ('***…'/'set') → keep, '' → clear, else → set. Atomic
    tmp+replace with chmod 0600 (the file may hold a GitHub token).
    """
    raw = _read_sources_file()
    for key in ("skill_repos", "plugin_marketplaces", "prompt_digest_sources"):
        if changes.get(key) is not None:
            raw[key] = [str(v).strip() for v in changes[key] if str(v).strip()]
    if changes.get("catalog_urls") is not None:
        merged = dict(raw.get("catalog_urls") or {})
        merged.update({k: (v or "").strip() for k, v in changes["catalog_urls"].items()})
        raw["catalog_urls"] = merged
    if changes.get("cache_ttls") is not None:
        merged = dict(raw.get("cache_ttls") or {})
        merged.update(changes["cache_ttls"])
        raw["cache_ttls"] = merged
    if changes.get("github_token") is not None:
        tok = str(changes["github_token"])
        if tok == "":
            raw.pop("github_token", None)
        elif not tok.startswith("***") and tok != "set":
            raw["github_token"] = tok
        # masked echo → keep the stored token untouched
    _SOURCES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SOURCES_CONFIG_FILE.with_name(_SOURCES_CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, _SOURCES_CONFIG_FILE)
    return masked_sources_config()


def cache_ttl_for(source: str) -> float:
    """Per-source feed cache TTL in seconds, consulted at fetch time."""
    ttls = load_sources_config().get("cache_ttls") or {}
    try:
        return float(ttls.get(source, ttls.get("default", CACHE_TTL)))
    except (TypeError, ValueError):
        return float(CACHE_TTL)


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
            and now - self._fetched_at < cache_ttl_for(self.source)
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
    if source in RESERVED_SOURCES:
        raise ValueError(
            f"'{source}' is a reserved discovery source name "
            "(collides with /api/discover/config)"
        )
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
