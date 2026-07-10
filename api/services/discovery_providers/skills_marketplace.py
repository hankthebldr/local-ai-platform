#!/usr/bin/env python3
"""Skills.sh marketplace provider — GitHub-backed.

skills.sh is a public directory of Agent Skills. Its own REST API
(``https://skills.sh/api/v1/skills``) is gated behind a Vercel OIDC
token — only mintable from a Vercel-hosted workload, or locally via
``vercel link`` + ``vercel env pull`` (a ~12h ephemeral token). That
auth model is a poor fit for a self-hosted sovereign appliance, so we
don't depend on it.

Instead we ingest the **GitHub repositories that back the directory**.
Every skills.sh entry resolves to ``{owner}/{repo}/{skill}`` on GitHub,
and each skill is a directory containing a ``SKILL.md`` (YAML
frontmatter + body). We crawl a curated allow-list of public skill
repos via the GitHub trees API, parse each ``SKILL.md``'s frontmatter,
and project it into the unified ``DiscoveryItem`` shape with both
install paths attached:

  - ``install.command``   — ``npx skills add <owner/repo>`` (skills.sh CLI)
  - ``install.skill_md_url`` — raw SKILL.md URL; Enclave's native
    importer (``POST /api/skills/import``) consumes this directly, so a
    discovered skill is one click to install with no skills.sh account.

Rate-limit shape: the trees call is the only request that hits the
GitHub REST API (60/hr unauthenticated, 5000/hr with a token) — one per
repo. The per-skill ``SKILL.md`` fetches go to raw.githubusercontent.com
(a CDN, not API-rate-limited). Set ``ENCLAVE_GITHUB_TOKEN`` (or
``GITHUB_TOKEN``) to raise the trees-call ceiling. The feed is cached
upstream for ``CACHE_TTL`` so we don't crawl on every page hit.

Config (file > env > default, consulted at FETCH time — LB0-U2):
  data/config/discovery_sources.json   operator-owned allow-list + token
                                       (Admin ▸ Sources; PUT /api/discover/config
                                       takes effect on the next refresh, no restart)
  ENCLAVE_SKILL_REPOS     comma-separated owner/repo allow-list (env fallback)
  ENCLAVE_GITHUB_TOKEN    GitHub token for higher rate limits (or GITHUB_TOKEN)
  ENCLAVE_SKILLS_MAX_PER_REPO   per-repo SKILL.md cap (default 30)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

from ..agentic_discovery import (
    DiscoveryFeed,
    DiscoveryItem,
    load_sources_config,
    register_provider,
)

SOURCE = "skills-sh"
NAME = "Skills.sh (GitHub-backed)"
DESCRIPTION = (
    "Public Agent Skills directory. Ingested from the GitHub repos that "
    "back skills.sh (its API is Vercel-OIDC gated, so we crawl the source "
    "repos directly) — each SKILL.md is one-click installable via Enclave's "
    "native importer or `npx skills add`."
)
HOMEPAGE = "https://skills.sh"

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
_TIMEOUT = float(os.getenv("ENCLAVE_SKILLS_TIMEOUT", "12"))
_MAX_PER_REPO = int(os.getenv("ENCLAVE_SKILLS_MAX_PER_REPO", "30"))


def _repos() -> List[str]:
    """Allow-list of skill repos, resolved at FETCH time.

    Delegates to the shared discovery-sources config (file > env >
    default — defaults live in ``agentic_discovery.DEFAULT_SKILL_REPOS``),
    so an operator PUT to /api/discover/config governs the very next
    refresh without a restart.
    """
    return list(load_sources_config()["skill_repos"])


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    tok = load_sources_config().get("github_token") or ""
    if tok:
        h["Authorization"] = f"Bearer {tok.strip()}"
    return h


def _slug(text: str) -> str:
    """Lowercase, hyphenated, id-safe slug (mirrors skills router)."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:64] or "skill"


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """Parse the leading ``---`` YAML frontmatter block of a SKILL.md."""
    t = (text or "").lstrip()
    if not t.startswith("---"):
        return {}
    end = t.find("\n---", 3)
    if end == -1:
        return {}
    try:
        meta = yaml.safe_load(t[3:end]) or {}
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _repo_tree(repo: str) -> Tuple[List[str], str]:
    """Return (skill_md_paths, ref) for a repo, trying main then master.

    Raises requests.RequestException / HTTPError on a hard failure so the
    caller can record it on the feed; a 404 on `main` falls back to `master`.
    """
    for ref in ("main", "master"):
        r = requests.get(
            f"{GITHUB_API}/repos/{repo}/git/trees/{ref}?recursive=1",
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        if r.status_code == 404 and ref == "main":
            continue
        r.raise_for_status()
        tree = r.json().get("tree", [])
        paths = [
            t["path"]
            for t in tree
            if isinstance(t, dict)
            and isinstance(t.get("path"), str)
            and t["path"].lower().endswith("skill.md")
        ]
        return paths[:_MAX_PER_REPO], ref
    return [], "main"


def _to_item(repo: str, ref: str, path: str) -> DiscoveryItem:
    """Project one SKILL.md into a DiscoveryItem (fetches frontmatter)."""
    raw_url = f"{RAW_BASE}/{repo}/{ref}/{path}"
    meta: Dict[str, Any] = {}
    try:
        resp = requests.get(raw_url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            meta = _parse_frontmatter(resp.text)
    except requests.RequestException:
        pass

    # Name: frontmatter name → parent directory → repo.
    parts = path.split("/")
    dirname = parts[-2] if len(parts) > 1 else repo.split("/")[-1]
    name = str(meta.get("name") or dirname)
    owner = repo.split("/")[0]

    return DiscoveryItem(
        id=f"{repo}/{_slug(name)}",
        source=SOURCE,
        kind="skill",
        name=name,
        description=str(meta.get("description") or ""),
        version=str(meta.get("version") or "unknown"),
        url=f"https://github.com/{repo}/blob/{ref}/{path}",
        install={
            # skills.sh CLI — adds the whole repo's skills.
            "command": f"npx skills add {repo}",
            # Enclave-native one-click: POST this to /api/skills/import.
            "skill_md_url": raw_url,
            "import_endpoint": "/api/skills/import",
            "repo": repo,
            "ref": ref,
            "path": path,
        },
        tools=[],
        resources=[],
        prompts=[],
        metadata={
            "author": owner,
            "repo": repo,
            "path": path,
            "tags": meta.get("tags") or meta.get("keywords") or [],
            "license": meta.get("license") or "unknown",
            "homepage": f"https://skills.sh/{repo}",
        },
    )


def fetch() -> DiscoveryFeed:
    """Crawl the allow-list of skill repos and return a populated feed."""
    items: List[DiscoveryItem] = []
    errors: List[str] = []
    for repo in _repos():
        try:
            paths, ref = _repo_tree(repo)
        except requests.RequestException as exc:
            errors.append(f"{repo}: {exc.__class__.__name__}: {exc}")
            continue
        for path in paths:
            try:
                items.append(_to_item(repo, ref, path))
            except Exception:  # noqa: BLE001
                # Skip a single bad skill rather than failing the whole feed.
                continue

    # Surface a partial-failure note without nuking items we did get.
    error: Optional[str] = None
    if errors and not items:
        error = "; ".join(errors)
    elif errors:
        error = f"partial: {len(errors)} repo(s) failed — " + "; ".join(errors)

    return DiscoveryFeed(
        source=SOURCE,
        name=NAME,
        description=DESCRIPTION,
        homepage=HOMEPAGE,
        kinds=["skill"],
        implemented=True,
        items=items,
        error=error,
    )


register_provider(
    source=SOURCE,
    name=NAME,
    description=DESCRIPTION,
    homepage=HOMEPAGE,
    kinds=["skill"],
    fetch=fetch,
    implemented=True,
)
