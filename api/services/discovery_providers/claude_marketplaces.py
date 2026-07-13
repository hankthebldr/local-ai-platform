#!/usr/bin/env python3
"""Claude Code plugin marketplaces — real digest provider (LB5-U1, A11).

Replaces the ``claude-marketplaces`` stub with a digest-backed normalizer
over the shared :mod:`..discovery_fetch` service (the LB2-U2 seam the
prompt digest already rides):

  - **Allowlisted pinned sources** from ``discovery_sources.json
    plugin_marketplaces`` (Admin ▸ Sources — the ONLY override; no env var,
    critique F14). Pinned defaults: ``anthropics/claude-plugins-official``,
    ``anthropics/claude-code``, ``anthropics/skills``,
    ``anthropics/knowledge-work-plugins``.
  - **Manifest resolution ladder** (critique F13 — none of the four pinned
    sources expose a repo-root ``marketplace.json``):
      1. ``.claude-plugin/marketplace.json`` — one manifest, ``plugins[]``
         entries;
      2. fallback: per-plugin ``**/.claude-plugin/plugin.json`` enumeration
         (the knowledge-work-plugins shape).
  - **Pointer-only records** — name, description, category, repo+sha,
    per-record license (surfaced BEFORE any import), component counts
    (commands/agents/skills/hooks/mcp) and SKILL.md pointers that bridge
    into the existing ``POST /api/skills/import``. No plugin body is ever
    copied; auto-conversion into Enclave plugins is deliberately cut (v1).
  - **Version-resolution ladder**: declared semver > pinned head sha >
    unknown — surfaced as ``version_resolution`` on every record.
  - **Persisted digest** ``data/discovery/plugin_digest.json`` (whole-file
    atomic replace) with added/changed sha diffing vs the PRIOR file.

PRIVACY INVARIANT: the registered provider ``fetch()`` builds its feed from
the PERSISTED digest and NEVER touches the network, so Discovered-tab
activation (``GET /api/discover/claude-marketplaces``) serves the last
digest + staleness stamp offline. Network egress happens ONLY in
:func:`refresh`, which the operator-gated
``POST /api/discover/claude-marketplaces/refresh`` route invokes via the
provider's registered refresh hook.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ...logging_config import logger
from .. import discovery_fetch
from ..agentic_discovery import (
    DiscoveryFeed,
    DiscoveryItem,
    load_sources_config,
    register_provider,
)

SOURCE = "claude-marketplaces"
KIND = "plugin"
NAME = "Claude Plugin Marketplaces"
DESCRIPTION = (
    "Pinned Claude Code plugin marketplaces on GitHub — pointer-only digest "
    "records (name, license, component counts, SKILL.md pointers). Refresh "
    "is operator-triggered; reads serve the persisted digest offline."
)
HOMEPAGE = "https://github.com/anthropics/claude-plugins-official"

MARKETPLACE_MANIFEST = ".claude-plugin/marketplace.json"
PLUGIN_MANIFEST_SUFFIX = ".claude-plugin/plugin.json"

_FIRST_PARTY_OWNERS = frozenset({"anthropics"})
_MAX_RECORDS_PER_SOURCE = 60


# ── Read paths (NEVER fetch) ────────────────────────────────────────────────


def read() -> Dict[str, Any]:
    """The persisted plugin digest + ``fetched_at`` staleness stamp."""
    return discovery_fetch.read_digest(KIND)


def find_record(digest_id: str) -> Optional[Dict[str, Any]]:
    """One record from the PERSISTED digest. No network."""
    for rec in read().get("records", []):
        if isinstance(rec, dict) and rec.get("id") == digest_id:
            return rec
    return None


def _feed() -> DiscoveryFeed:
    """Registered provider fetch — a digest READ projected into the unified
    DiscoveryItem shape. Zero network, so cache-miss GETs stay offline."""
    digest = read()
    diff = digest.get("diff") or {}
    added = set(diff.get("added") or [])
    changed = set(diff.get("changed") or [])
    fetched_at = digest.get("fetched_at")
    items: List[DiscoveryItem] = []
    for rec in digest.get("records", []):
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        src = rec.get("source") or {}
        items.append(
            DiscoveryItem(
                id=rec["id"],
                source=SOURCE,
                kind=KIND,
                name=str(rec.get("title") or rec["id"]),
                description=str(rec.get("description") or ""),
                version=str(rec.get("version") or "unknown"),
                url=str(src.get("url") or ""),
                install={
                    # SKILL.md pointers bridge through the existing importer.
                    "import_endpoint": "/api/skills/import",
                    "skills": rec.get("skills") or [],
                    "repo": src.get("repo"),
                    "ref": src.get("ref"),
                },
                metadata={
                    "category": rec.get("category"),
                    "license": rec.get("license") or "unknown",
                    "components": rec.get("components") or {},
                    "version_resolution": rec.get("version_resolution") or "unknown",
                    "provenance": src.get("provenance"),
                    "repo": src.get("repo"),
                    "path": src.get("path"),
                    "ref": src.get("ref"),
                    "manifest_entry": rec.get("manifest_entry") or {},
                    "fetched_at": fetched_at,
                    "diff": (
                        "added" if rec["id"] in added
                        else "changed" if rec["id"] in changed
                        else None
                    ),
                },
            )
        )
    return DiscoveryFeed(
        source=SOURCE,
        name=NAME,
        description=DESCRIPTION,
        homepage=HOMEPAGE,
        kinds=[KIND],
        implemented=True,
        items=items,
        error=None if fetched_at else (
            "no digest yet — operator Refresh fetches the pinned marketplaces"
        ),
    )


# ── Refresh (operator-triggered ONLY) ───────────────────────────────────────


def refresh() -> Dict[str, Any]:
    """Fetch every allowlisted marketplace source and atomically replace the
    plugin digest. Fail-soft per source: a failing/malformed repo carries its
    prior records forward and surfaces the error on the digest's sources[]
    entry; a rate-limit stop degrades to a partial digest. Never raises for
    content/transport reasons."""
    prior = discovery_fetch.prior_records(KIND)
    records: List[Dict[str, Any]] = []
    sources_meta: List[Dict[str, Any]] = []
    rate_remaining: Optional[int] = None
    rate_limited = False

    for repo in load_sources_config().get("plugin_marketplaces", []):
        entry: Dict[str, Any] = {
            "repo": repo, "ok": False, "error": None, "sha": None,
            "count": 0, "strategy": None,
        }
        if rate_limited:
            entry["error"] = "skipped — github rate budget exhausted"
            records.extend(_carry_prior(repo, prior))
            sources_meta.append(entry)
            continue
        try:
            head = discovery_fetch.repo_head(repo)
            if head.get("rate_remaining") is not None:
                rate_remaining = head["rate_remaining"]
            recs, strategy = _collect(repo, head, prior)
            records.extend(recs)
            entry.update(ok=True, sha=head["sha"], count=len(recs), strategy=strategy)
        except discovery_fetch.RateLimited as rl:
            rate_limited = True
            rate_remaining = rl.remaining
            entry["error"] = "github rate limit exhausted — partial digest"
            records.extend(_carry_prior(repo, prior))
        except Exception as exc:  # noqa: BLE001 — fail-soft, keep prior records
            logger.warning("plugin digest source %s failed: %s", repo, exc)
            entry["error"] = str(exc)
            records.extend(_carry_prior(repo, prior))
        sources_meta.append(entry)

    return discovery_fetch.write_digest(
        KIND, records, sources=sources_meta, rate_remaining=rate_remaining
    )


def _carry_prior(repo: str, prior: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        r for r in prior.values() if (r.get("source") or {}).get("repo") == repo
    ]


def _provenance(repo: str) -> str:
    owner = repo.split("/", 1)[0].lower()
    if owner in _FIRST_PARTY_OWNERS:
        return "first-party"
    from ..agentic_discovery import DEFAULT_PLUGIN_MARKETPLACES

    return "curated" if repo in DEFAULT_PLUGIN_MARKETPLACES else "community"


def _record_id(repo: str, key: str) -> str:
    """Deterministic _ID_RE-safe id (mirrors prompt_digest): slugged
    repo+key, disambiguated by a hash of the full pair."""
    import re

    stem = re.sub(r"[^A-Za-z0-9]+", "-", f"{repo}-{key}".lower()).strip("-")[:60]
    return f"{stem or 'plugin'}-{discovery_fetch.sha256_text(f'{repo}::{key}')[:8]}"


def _version_ladder(declared: Any, sha: str) -> Tuple[str, str]:
    """declared semver > pinned head sha > unknown."""
    v = str(declared or "").strip()
    if v:
        return v, "declared"
    if sha:
        return sha[:12], "sha-pinned"
    return "unknown", "unknown"


def _components(
    blobs: Dict[str, str], repo: str, sha: str, root: Optional[str]
) -> Tuple[Dict[str, int], List[Dict[str, str]]]:
    """Count Claude Code plugin components under an in-repo plugin root and
    collect SKILL.md pointers for the skills-import bridge. ``root`` None
    means the plugin body lives in an external repo — counts unknown."""
    counts = {"commands": 0, "agents": 0, "skills": 0, "hooks": 0, "mcp": 0}
    skills: List[Dict[str, str]] = []
    if root is None:
        return {}, []
    prefix = root.rstrip("/") + "/" if root.rstrip("/") else ""
    for path in sorted(blobs):
        if prefix and not path.startswith(prefix):
            continue
        rel = path[len(prefix):]
        low = rel.lower()
        if low.startswith("commands/") and low.endswith(".md"):
            counts["commands"] += 1
        elif low.startswith("agents/") and low.endswith(".md"):
            counts["agents"] += 1
        elif low.startswith("skills/") and low.rsplit("/", 1)[-1] == "skill.md":
            counts["skills"] += 1
            parts = rel.split("/")
            skills.append(
                {
                    "name": parts[1] if len(parts) > 2 else parts[-1],
                    "path": path,
                    "skill_md_url": f"{discovery_fetch.RAW_BASE}/{repo}/{sha}/{path}",
                }
            )
        elif low.startswith("hooks/"):
            counts["hooks"] += 1
        elif low == ".mcp.json":
            counts["mcp"] += 1
    return counts, skills


def _entry_root(entry: Dict[str, Any]) -> Optional[str]:
    """An entry's in-repo plugin root, or None for external/hostile sources.

    ``source`` may be a relative path ("./plugins/foo") or an object
    pointing at another repo. Paths get the shared charset/dot-segment
    check — a hostile manifest path degrades to 'external' (no counts),
    never an exception, never a URL splice."""
    src = entry.get("source")
    if not isinstance(src, str):
        return None
    path = src.strip()
    if path.startswith("./"):
        path = path[2:]
    path = path.strip("/")
    if not path:  # "./" — plugin body at the repo root
        return ""
    try:
        return discovery_fetch._check_path(path)
    except ValueError:
        return None  # hostile/odd path — degrade to external, never traverse


def _collect(
    repo: str, head: Dict[str, Any], prior: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], str]:
    """Normalize one marketplace source via the manifest resolution ladder."""
    tree, _ = discovery_fetch.repo_tree(repo, head["sha"])
    blobs = {
        e["path"]: e.get("sha", "")
        for e in tree
        if isinstance(e, dict) and e.get("type") == "blob" and e.get("path")
    }
    if MARKETPLACE_MANIFEST in blobs:
        return _from_marketplace(repo, head, blobs, prior), "marketplace.json"
    return _from_plugin_manifests(repo, head, blobs, prior), "plugin.json"


def _base_record(
    repo: str, head: Dict[str, Any], *, rid: str, subkind: str, title: str,
    description: str, tags: List[str], category: Optional[str],
    license_id: str, version: str, version_resolution: str,
    components: Dict[str, int], skills: List[Dict[str, str]],
    manifest_path: str, content_sha: str, manifest_entry: Dict[str, Any],
) -> Dict[str, Any]:
    sha = head["sha"]
    return {
        "id": rid,
        "kind": KIND,
        "subkind": subkind,
        "title": title,
        "description": description,
        "tags": tags,
        "category": category,
        "intended_output": None,
        "license": license_id or "unknown",
        "token_estimate": None,
        "version": version,
        "version_resolution": version_resolution,
        "components": components,
        "skills": skills,
        "source": {
            "origin": "github",
            "repo": repo,
            "path": manifest_path,
            "ref": sha,
            "url": f"https://github.com/{repo}/blob/{sha}/{manifest_path}",
            "provenance": _provenance(repo),
        },
        "content_sha": content_sha,
        # Pointer-only ALWAYS — plugin bodies are never copied (v1 cut).
        "body": None,
        "body_pointer": f"{discovery_fetch.RAW_BASE}/{repo}/{sha}/{manifest_path}",
        "fetched_at": None,  # stamped digest-wide by write_digest
        "manifest_entry": manifest_entry,
    }


def _from_marketplace(
    repo: str, head: Dict[str, Any], blobs: Dict[str, str],
    prior: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Ladder rung 1 — one ``.claude-plugin/marketplace.json``, plugins[]
    entries. Per-entry content sha = sha256 of the canonical entry JSON, so
    diff badges track individual entries, not the whole manifest blob."""
    raw = discovery_fetch.fetch_raw(repo, head["sha"], MARKETPLACE_MANIFEST)
    if raw is None:
        raise ValueError(f"{repo}: {MARKETPLACE_MANIFEST} unreadable at head")
    doc = json.loads(raw)  # ValueError on malformed → fail-soft upstream
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    if not isinstance(plugins, list):
        raise ValueError(f"{repo}: malformed marketplace.json — no plugins[]")
    repo_license = head.get("license") or ""
    out: List[Dict[str, Any]] = []
    for entry in plugins[:_MAX_RECORDS_PER_SOURCE]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        rid = _record_id(repo, name)
        content_sha = discovery_fetch.sha256_text(
            json.dumps(entry, sort_keys=True)
        )
        prev = prior.get(rid)
        if prev and prev.get("content_sha") == content_sha:
            out.append(prev)  # unchanged entry — carry forward untouched
            continue
        components, skills = _components(
            blobs, repo, head["sha"], _entry_root(entry)
        )
        version, resolution = _version_ladder(entry.get("version"), head["sha"])
        out.append(
            _base_record(
                repo, head, rid=rid, subkind="marketplace-entry", title=name,
                description=str(entry.get("description") or ""),
                tags=[t for t in (entry.get("keywords") or []) if isinstance(t, str)],
                category=(str(entry["category"]) if entry.get("category") else None),
                license_id=str(entry.get("license") or repo_license or ""),
                version=version, version_resolution=resolution,
                components=components, skills=skills,
                manifest_path=MARKETPLACE_MANIFEST, content_sha=content_sha,
                manifest_entry=entry,
            )
        )
    return out


def _from_plugin_manifests(
    repo: str, head: Dict[str, Any], blobs: Dict[str, str],
    prior: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Ladder rung 2 — enumerate per-plugin ``.claude-plugin/plugin.json``
    manifests. Manifest-first diff: the plugin.json blob sha is the change
    currency; unchanged records skip the raw fetch entirely."""
    manifest_paths = sorted(
        p for p in blobs
        if p == PLUGIN_MANIFEST_SUFFIX or p.endswith("/" + PLUGIN_MANIFEST_SUFFIX)
    )
    repo_license = head.get("license") or ""
    out: List[Dict[str, Any]] = []
    for mpath in manifest_paths[:_MAX_RECORDS_PER_SOURCE]:
        blob_sha = blobs.get(mpath, "")
        rid = _record_id(repo, mpath)
        prev = prior.get(rid)
        if prev and prev.get("content_sha") == blob_sha:
            out.append(prev)  # unchanged — no body pull (manifest-first diff)
            continue
        meta: Dict[str, Any] = {}
        raw = discovery_fetch.fetch_raw(repo, head["sha"], mpath)
        if raw:
            try:
                parsed = json.loads(raw)
                meta = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                meta = {}  # single bad manifest — record survives from paths
        root = mpath[: -len(PLUGIN_MANIFEST_SUFFIX)].rstrip("/")
        name = str(
            meta.get("name")
            or (root.rsplit("/", 1)[-1] if root else repo.split("/", 1)[-1])
        )
        components, skills = _components(blobs, repo, head["sha"], root)
        version, resolution = _version_ladder(meta.get("version"), head["sha"])
        out.append(
            _base_record(
                repo, head, rid=rid, subkind="plugin-manifest", title=name,
                description=str(meta.get("description") or ""),
                tags=[t for t in (meta.get("keywords") or []) if isinstance(t, str)],
                category=(str(meta["category"]) if meta.get("category") else None),
                license_id=str(meta.get("license") or repo_license or ""),
                version=version, version_resolution=resolution,
                components=components, skills=skills,
                manifest_path=mpath, content_sha=blob_sha,
                manifest_entry=meta,
            )
        )
    return out


register_provider(
    source=SOURCE,
    name=NAME,
    description=DESCRIPTION,
    homepage=HOMEPAGE,
    kinds=[KIND],
    fetch=_feed,          # digest READ — never touches the network
    refresh=refresh,      # network + digest write — POST .../refresh only
    implemented=True,
)
