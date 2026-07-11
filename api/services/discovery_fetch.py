"""Shared operator-triggered discovery fetcher (LB2-U2, A6).

ONE fetcher for every digest-backed discovery track — prompts here, plugins
(LB5-U1) and future task/skill digests ride the same seams:

  - **Allowlist at fetch time** — sources come from
    ``data/config/discovery_sources.json`` (Admin ▸ Sources, LB0-U2) via
    ``agentic_discovery.load_sources_config()``, read on every refresh so a
    PUT governs the very next fetch without a restart.
  - **Sha-pinned raw fetches** — bodies come from
    ``raw.githubusercontent.com/<owner>/<repo>/<head_sha>/<path>``; the head
    commit sha is resolved once per source per refresh.
  - **Manifest-first diff** — callers fetch a cheap authoritative index
    (registry.yaml / git trees / marketplace manifests), compare per-record
    ``content_sha`` against the stored digest, and pull bodies ONLY for
    added/changed records (the normalizer owns that loop; this module owns
    the primitives + persistence).
  - **Rate-budget fail-soft** — the unauthenticated GitHub API budget
    (60/hr) is respected: a rate-limit 403 raises :class:`RateLimited` with
    the remaining quota so callers degrade to a partial digest instead of
    failing the refresh; the remaining quota is surfaced on the digest doc.
  - **Whole-digest atomic replace** — ``write_digest`` persists
    ``data/discovery/<kind>_digest.json`` via tmp+replace and computes
    added/changed/removed against the PRIOR file at refresh time. No
    append-only log, no tombstones (YAGNI cut, critique C17).
  - **License gate** — per-record license classified against a permissive
    SPDX allowlist; ``proprietary``/``unknown`` licenses and community-tier
    provenance are pointer-only (body-copy install hard-blocked upstream).

PRIVACY INVARIANT: nothing in this module runs on a timer or on a read GET.
It is invoked ONLY from operator-triggered ``POST .../refresh`` route call
sites (a test pins that for the modules introduced with it — pre-existing
TTL-on-read fetches are named follow-up #15).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..logging_config import logger
from .agentic_discovery import load_sources_config

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
_TIMEOUT = float(os.getenv("ENCLAVE_DISCOVERY_TIMEOUT", "12"))

# Runtime-mutable state lives under data/ (== user_storage_root in
# containers) — same seam as agentic_discovery's data/config sibling.
_DIGEST_DIR = Path(__file__).resolve().parents[2] / "data" / "discovery"

# Digest kinds are code-supplied, but the charset allowlist + containment
# discipline applies to ANYTHING that becomes a filename (the glob-traversal
# incident lesson) — belt and braces even for internal callers.
_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
# owner/repo — mirrors the /api/discover/config validator (discover.py).
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}/[A-Za-z0-9_.-]{1,120}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_DOT_SEGMENTS = {".", ".."}

# Permissive SPDX ids — body copies may be ingested and installed. Anything
# else (incl. NOASSERTION/empty/proprietary) is pointer-only.
PERMISSIVE_LICENSES = frozenset(
    {
        "mit",
        "apache-2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "0bsd",
        "isc",
        "mpl-2.0",
        "cc0-1.0",
        "cc-by-4.0",
        "unlicense",
    }
)


class RateLimited(RuntimeError):
    """GitHub API rate budget exhausted — callers fail soft to a partial
    digest and surface ``remaining`` on the digest doc."""

    def __init__(self, remaining: int = 0):
        super().__init__(f"github api rate limit exhausted (remaining={remaining})")
        self.remaining = remaining


def license_allows_body(license_id: Optional[str], provenance: str = "curated") -> bool:
    """True when a record's BODY may be copied/installed. Community-tier
    provenance ingests pointer-only regardless of the declared license."""
    if (provenance or "").strip().lower() == "community":
        return False
    return (license_id or "").strip().lower() in PERMISSIVE_LICENSES


# ── GitHub primitives (token + allowlist consulted at FETCH time) ──────────


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    tok = load_sources_config().get("github_token") or ""
    if tok:
        h["Authorization"] = f"Bearer {tok.strip()}"
    return h


def _check_repo(repo: str) -> str:
    repo = (repo or "").strip()
    if not _REPO_RE.match(repo) or any(
        seg in _DOT_SEGMENTS for seg in repo.split("/")
    ):
        raise ValueError(f"invalid owner/repo {repo!r}")
    return repo


def _rate_remaining(resp: requests.Response) -> Optional[int]:
    raw = resp.headers.get("X-RateLimit-Remaining", "")
    return int(raw) if raw.isdigit() else None


def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Any, Optional[int]]:
    """One GitHub REST API GET. Returns (json, rate_remaining).

    Raises :class:`RateLimited` when the budget is exhausted (403/429 with a
    zero remaining header) and ``requests`` errors on hard failures.
    """
    r = requests.get(
        f"{GITHUB_API}{path}", headers=_headers(), params=params, timeout=_TIMEOUT
    )
    remaining = _rate_remaining(r)
    if r.status_code in (403, 429) and (remaining == 0 or remaining is None):
        raise RateLimited(remaining or 0)
    r.raise_for_status()
    return r.json(), remaining


def repo_head(repo: str) -> Dict[str, Any]:
    """Resolve a source repo's head: default branch, head commit sha, and
    repo-level license spdx id. Two API calls; sha pins every raw fetch."""
    repo = _check_repo(repo)
    info, rem1 = api_get(f"/repos/{repo}")
    branch = (info.get("default_branch") or "main").strip() or "main"
    lic = ((info.get("license") or {}).get("spdx_id") or "").strip()
    if lic.upper() == "NOASSERTION":
        lic = ""
    commit, rem2 = api_get(f"/repos/{repo}/commits/{branch}")
    sha = (commit.get("sha") or "").strip()
    if not _SHA_RE.match(sha):
        raise ValueError(f"{repo}: no resolvable head sha on '{branch}'")
    return {
        "repo": repo,
        "default_branch": branch,
        "sha": sha,
        "license": lic,
        "rate_remaining": rem2 if rem2 is not None else rem1,
    }


def repo_tree(repo: str, sha: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Recursive git tree at a pinned sha — the cheap authoritative index
    (per-blob shas are the manifest-first diff currency). One API call."""
    repo = _check_repo(repo)
    if not _SHA_RE.match((sha or "").strip()):
        raise ValueError(f"invalid tree sha {sha!r}")
    data, remaining = api_get(f"/repos/{repo}/git/trees/{sha}", params={"recursive": "1"})
    tree = data.get("tree") if isinstance(data, dict) else None
    return (tree if isinstance(tree, list) else []), remaining


def _check_path(path: str) -> str:
    """Repo-relative path allowlist for raw fetches: no absolute paths, no
    dot segments, conservative charset — it gets spliced into a URL. A
    leading dot is allowed for dot-DIRECTORY manifests ('.claude-plugin/…',
    LB5-U1); '.'/'..' segments stay hard-rejected."""
    path = (path or "").strip()
    if (
        not path
        or len(path) > 400
        or not re.match(r"^[A-Za-z0-9.][A-Za-z0-9_. /()+-]*$", path)
        or any(seg in _DOT_SEGMENTS for seg in path.split("/"))
    ):
        raise ValueError(f"invalid repo path {path!r}")
    return path


def fetch_raw(repo: str, sha: str, path: str) -> Optional[str]:
    """Sha-pinned raw body fetch (CDN — not API-rate-limited). None on a
    miss; raises requests errors on transport failure."""
    repo = _check_repo(repo)
    if not _SHA_RE.match((sha or "").strip()):
        raise ValueError(f"invalid pin sha {sha!r}")
    path = _check_path(path)
    r = requests.get(f"{RAW_BASE}/{repo}/{sha}/{path}", timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    return r.text


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ── Digest persistence (whole-file atomic replace + prior-file diff) ───────


def digest_path(kind: str) -> Path:
    """data/discovery/<kind>_digest.json with charset + containment checks."""
    if not _KIND_RE.match(kind or ""):
        raise ValueError(f"invalid digest kind {kind!r}")
    base = _DIGEST_DIR.resolve()
    candidate = (base / f"{kind}_digest.json").resolve()
    candidate.relative_to(base)  # ValueError on escape — cannot happen post-regex
    return candidate


def _empty_digest(kind: str) -> Dict[str, Any]:
    return {
        "kind": kind,
        "fetched_at": None,
        "records": [],
        "sources": [],
        "rate_remaining": None,
        "diff": {"added": [], "changed": [], "removed": []},
    }


def read_digest(kind: str) -> Dict[str, Any]:
    """The persisted digest doc (read path — NEVER fetches). Corrupt or
    absent files degrade to the empty shape; never raises on content."""
    p = digest_path(kind)
    try:
        if not p.is_file():
            return _empty_digest(kind)
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            return _empty_digest(kind)
        data.setdefault("kind", kind)
        data.setdefault("fetched_at", None)
        data.setdefault("sources", [])
        data.setdefault("rate_remaining", None)
        data.setdefault("diff", {"added": [], "changed": [], "removed": []})
        return data
    except (OSError, ValueError):
        logger.warning("%s digest unreadable — serving empty digest", kind)
        return _empty_digest(kind)


def prior_records(kind: str) -> Dict[str, Dict[str, Any]]:
    """id → record map of the persisted digest — the manifest-first diff
    baseline normalizers consult to skip unchanged bodies."""
    out: Dict[str, Dict[str, Any]] = {}
    for rec in read_digest(kind).get("records", []):
        if isinstance(rec, dict) and isinstance(rec.get("id"), str):
            out[rec["id"]] = rec
    return out


def write_digest(
    kind: str,
    records: List[Dict[str, Any]],
    *,
    sources: Optional[List[Dict[str, Any]]] = None,
    rate_remaining: Optional[int] = None,
) -> Dict[str, Any]:
    """Atomically replace the whole digest, computing added/changed/removed
    against the PRIOR file (current-vs-previous is all diff badges need)."""
    prior = read_digest(kind)
    prev = {
        r.get("id"): r.get("content_sha")
        for r in prior.get("records", [])
        if isinstance(r, dict) and r.get("id")
    }
    cur = {
        r.get("id"): r.get("content_sha")
        for r in records
        if isinstance(r, dict) and r.get("id")
    }
    doc = {
        "kind": kind,
        "fetched_at": time.time(),
        "records": records,
        "sources": sources or [],
        "rate_remaining": rate_remaining,
        "diff": {
            "added": sorted(i for i in cur if i not in prev),
            "changed": sorted(i for i in cur if i in prev and prev[i] != cur[i]),
            "removed": sorted(i for i in prev if i not in cur),
        },
    }
    p = digest_path(kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic
    logger.info(
        "%s digest written: %d records (+%d ~%d -%d)",
        kind,
        len(records),
        len(doc["diff"]["added"]),
        len(doc["diff"]["changed"]),
        len(doc["diff"]["removed"]),
    )
    return doc
