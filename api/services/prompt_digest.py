"""Prompt digest normalizer + hybrid recommender, deterministic layer (LB2-U2).

Digest side — rides the shared :mod:`discovery_fetch` service:

  - Sources come from ``discovery_sources.json prompt_digest_sources`` (Admin
    ▸ Sources), filtered to the repos this normalizer understands. Pinned
    defaults: ``anthropics/claude-cookbooks`` + ``openai/openai-cookbook``
    (registry.yaml manifests, verified at repo root) and
    ``google-gemini/cookbook`` (git trees). The hookify rule source is
    DELIBERATELY OMITTED — that repo ships no ``*.local.md`` rule files
    (critique F10); engine-hook presets are seeded from the shipped xdm
    workflows instead (LB2-U1).
  - Manifest-first diff: per-source we resolve the head sha, pull the git
    tree (per-blob shas = the change currency), and fetch bodies ONLY for
    records whose blob sha differs from the persisted digest. Unchanged
    records (and their extracted notebook children) carry forward.
  - Normalization: cookbook notebooks → structural-operation parent records
    (pointer-only body) + extracted prompt children (triple-quoted
    ``*prompt*`` assignments in code cells); commands/agents ``*.md`` →
    prompts (installable as roles); ``SKILL.md`` → templates.
  - License gate at ingest: non-permissive / community provenance records
    are pointer-only (no body); install hard-blocks them again server-side.
  - Persists ``data/discovery/prompt_digest.json`` (whole-file atomic
    replace + prior-file diff via discovery_fetch).

PRIVACY: :func:`refresh` is invoked ONLY from the operator-triggered
``POST /api/prompts/discover/refresh`` route. :func:`read` never fetches.

Recommender side — the DETERMINISTIC layer of the hybrid design (A8):
:func:`score_prompts` ranks installed prompts by (a) tags ∩ task keywords,
(b) declared ``model_fit`` vs the model's role classes (registry tags +
``model_benchmarks.json role_fit``), (c) size-fit (token_estimate vs the
model's context window). Pure, instant, explainable — per-factor breakdown
on every hit. The same scorer powers the prompt detail rail and the LB4-U2
model-side "Recommended prompts" section. The on-demand "Ask Enclave" LLM
layer lives in the router (local model only; nothing leaves the box).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ..logging_config import logger
from . import discovery_fetch
from .agentic_discovery import load_sources_config
from .prompt_meta import MODEL_ROLE_CLASSES, estimate_tokens

KIND = "prompt"

# Repos this normalizer understands, by manifest strategy. Anything else in
# the operator's prompt_digest_sources list is skipped with an honest
# per-source error (fail-soft — never a refresh 500).
REGISTRY_SOURCES = frozenset({"anthropics/claude-cookbooks", "openai/openai-cookbook"})
TREES_SOURCES = frozenset({"google-gemini/cookbook"})

# first-party = the platform's own upstream vendor; curated = pinned default
# sources we normalize deliberately; anything unrecognized would be
# community (pointer-only) — unreachable today because unknown repos are
# skipped, but the gate stays for when the allowlist grows.
_FIRST_PARTY_OWNERS = frozenset({"anthropics"})

_MAX_RECORDS_PER_SOURCE = 40
_MAX_CHILDREN_PER_NOTEBOOK = 6
_MAX_BODY_CHARS = 24_000

# Triple-quoted assignments to *prompt* variables inside notebook code cells
# — the extracted "prompt children" of a structural-operation parent.
_PROMPT_ASSIGN_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*prompt[A-Za-z0-9_]*)\s*=\s*(?:[frbu]{0,2})(\"\"\"|''')(.*?)\2",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def read() -> Dict[str, Any]:
    """The persisted digest + ``fetched_at`` staleness stamp. NEVER fetches."""
    return discovery_fetch.read_digest(KIND)


def find_record(digest_id: str) -> Optional[Dict[str, Any]]:
    """One record from the PERSISTED digest (install path). No network."""
    for rec in read().get("records", []):
        if isinstance(rec, dict) and rec.get("id") == digest_id:
            return rec
    return None


# ── Refresh (operator-triggered ONLY) ───────────────────────────────────────


def refresh() -> Dict[str, Any]:
    """Fetch every allowlisted prompt source and atomically replace the
    digest. Fail-soft per source: a failing repo carries its prior records
    forward and surfaces the error on the digest's sources[] entry; a
    rate-limit stop degrades to a partial digest with the remaining quota
    surfaced. Never raises for content/transport reasons."""
    prior = discovery_fetch.prior_records(KIND)
    records: List[Dict[str, Any]] = []
    sources_meta: List[Dict[str, Any]] = []
    rate_remaining: Optional[int] = None
    rate_limited = False

    for repo in load_sources_config().get("prompt_digest_sources", []):
        entry: Dict[str, Any] = {
            "repo": repo, "ok": False, "error": None, "sha": None, "count": 0,
        }
        if rate_limited:
            entry["error"] = "skipped — github rate budget exhausted"
            records.extend(_carry_prior(repo, prior))
            sources_meta.append(entry)
            continue
        if repo not in REGISTRY_SOURCES and repo not in TREES_SOURCES:
            entry["error"] = "no prompt normalizer for this source (skipped)"
            sources_meta.append(entry)
            continue
        try:
            head = discovery_fetch.repo_head(repo)
            if head.get("rate_remaining") is not None:
                rate_remaining = head["rate_remaining"]
            recs = _collect(repo, head, prior)
            records.extend(recs)
            entry.update(ok=True, sha=head["sha"], count=len(recs))
        except discovery_fetch.RateLimited as rl:
            rate_limited = True
            rate_remaining = rl.remaining
            entry["error"] = "github rate limit exhausted — partial digest"
            records.extend(_carry_prior(repo, prior))
        except Exception as exc:  # noqa: BLE001 — fail-soft, keep prior records
            logger.warning("prompt digest source %s failed: %s", repo, exc)
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
    if repo in REGISTRY_SOURCES or repo in TREES_SOURCES:
        return "curated"
    return "community"


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s or "x"


def _record_id(repo: str, path: str) -> str:
    """Deterministic id satisfying the prompts router's _ID_RE (alnum start,
    [A-Za-z0-9_-], ≤80): slugged repo+path, disambiguated by a path hash."""
    stem = _slug(f"{repo}-{Path(path).with_suffix('').name}")[:60]
    return f"{stem}-{discovery_fetch.sha256_text(f'{repo}/{path}')[:8]}"


def _classify(path: str) -> Tuple[str, str]:
    """(subkind, prompt_kind) for a manifest path."""
    name = Path(path).name.lower()
    if name == "skill.md":
        return "skill-template", "template"
    if path.endswith(".ipynb"):
        return "notebook", "role"
    low = f"/{path.lower()}"
    if "/commands/" in low or "/agents/" in low:
        return "command", "role"
    return "prompt", "role"


def _paths_from_registry(repo: str, head: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """registry.yaml manifest → [(path, manifest_entry)]. Tolerant of the
    two shapes in the wild: a top-level list, or a mapping with list values."""
    raw = discovery_fetch.fetch_raw(repo, head["sha"], "registry.yaml")
    if raw is None:
        raise ValueError(f"{repo}: registry.yaml not found at {head['sha'][:12]}")
    doc = yaml.safe_load(raw)
    entries: List[Any] = []
    if isinstance(doc, list):
        entries = doc
    elif isinstance(doc, dict):
        for v in doc.values():
            if isinstance(v, list):
                entries.extend(v)
    out: List[Tuple[str, Dict[str, Any]]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        path = e.get("path") or e.get("file") or e.get("notebook") or ""
        if isinstance(path, str) and path.strip():
            out.append((path.strip().lstrip("./"), e))
    return out


def _paths_from_tree(blobs: Dict[str, str]) -> List[Tuple[str, Dict[str, Any]]]:
    """Trees-only sources (google-gemini/cookbook): the tree IS the manifest —
    notebooks plus SKILL.md / commands / agents markdown."""
    out = []
    for path in sorted(blobs):
        low = path.lower()
        if low.endswith(".ipynb") or Path(low).name == "skill.md" or (
            low.endswith(".md") and ("/commands/" in f"/{low}" or "/agents/" in f"/{low}")
        ):
            out.append((path, {}))
    return out


def _collect(
    repo: str, head: Dict[str, Any], prior: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Normalize one source into digest records, pulling bodies only for
    added/changed blob shas (manifest-first diff)."""
    tree, _ = discovery_fetch.repo_tree(repo, head["sha"])
    blobs = {
        e["path"]: e.get("sha", "")
        for e in tree
        if isinstance(e, dict) and e.get("type") == "blob" and e.get("path")
    }
    if repo in REGISTRY_SOURCES:
        manifest = _paths_from_registry(repo, head)
    else:
        manifest = _paths_from_tree(blobs)

    provenance = _provenance(repo)
    repo_license = head.get("license") or ""
    out: List[Dict[str, Any]] = []
    for path, mentry in manifest[:_MAX_RECORDS_PER_SOURCE]:
        try:
            path = discovery_fetch._check_path(path)
        except ValueError:
            continue  # hostile/odd manifest path — skip, never abort the source
        blob_sha = blobs.get(path)
        if not blob_sha:
            continue  # manifest references a path the tree doesn't carry
        rid = _record_id(repo, path)
        lic = (mentry.get("license") if isinstance(mentry, dict) else None) or repo_license
        subkind, prompt_kind = _classify(path)
        pointer_only = not discovery_fetch.license_allows_body(lic, provenance)

        prev = prior.get(rid)
        if prev and prev.get("content_sha") == blob_sha:
            # unchanged — carry the record AND its extracted children forward
            out.append(prev)
            out.extend(
                r for r in prior.values() if r.get("parent") == rid
            )
            continue

        body: Optional[str] = None
        if not pointer_only:
            body = discovery_fetch.fetch_raw(repo, head["sha"], path)
        rec = {
            "id": rid,
            "kind": KIND,
            "subkind": subkind,
            "prompt_kind": prompt_kind,
            "title": str(
                (mentry.get("title") or mentry.get("name"))
                if isinstance(mentry, dict) and (mentry.get("title") or mentry.get("name"))
                else Path(path).stem.replace("_", " ").replace("-", " ").title()
            ),
            "tags": [
                t for t in (mentry.get("tags") or []) if isinstance(t, str)
            ] if isinstance(mentry, dict) else [],
            "intended_output": (
                mentry.get("intended_output") if isinstance(mentry, dict) else None
            ),
            "license": lic or "unknown",
            "token_estimate": estimate_tokens(body or ""),
            "source": {
                "origin": "github",
                "repo": repo,
                "path": path,
                "ref": head["sha"],
                "url": f"https://github.com/{repo}/blob/{head['sha']}/{path}",
                "provenance": provenance,
            },
            "content_sha": blob_sha,
            "body": None,
            "body_pointer": f"{discovery_fetch.RAW_BASE}/{repo}/{head['sha']}/{path}",
            "fetched_at": None,  # stamped digest-wide by write_digest
            "manifest_entry": mentry if isinstance(mentry, dict) else {},
        }
        if subkind == "notebook":
            # structural-operation parent stays pointer-only; children carry
            # the extracted prompt text.
            out.append(rec)
            if body:
                out.extend(_notebook_children(rec, body))
            continue
        if body is not None and not pointer_only:
            rec["body"] = body[:_MAX_BODY_CHARS]
        out.append(rec)
    return out


def _notebook_children(parent: Dict[str, Any], nb_text: str) -> List[Dict[str, Any]]:
    """Extract prompt children from a cookbook notebook: triple-quoted
    assignments to ``*prompt*`` variables in code cells."""
    try:
        nb = json.loads(nb_text)
    except (ValueError, TypeError):
        return []
    children: List[Dict[str, Any]] = []
    for cell in nb.get("cells", []) if isinstance(nb, dict) else []:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        src = cell.get("source")
        text = "".join(src) if isinstance(src, list) else (src or "")
        for m in _PROMPT_ASSIGN_RE.finditer(text):
            if len(children) >= _MAX_CHILDREN_PER_NOTEBOOK:
                return children
            name, prompt_text = m.group(1), m.group(3).strip()
            if len(prompt_text) < 40:
                continue  # too short to be a reusable prompt
            n = len(children)
            children.append(
                {
                    **{k: parent[k] for k in ("kind", "license", "source", "manifest_entry")},
                    "id": f"{parent['id']}-p{n}"[:80],
                    "subkind": "notebook-prompt",
                    "prompt_kind": "role",
                    "title": f"{parent['title']} — {name.replace('_', ' ')}",
                    "tags": list(parent.get("tags") or []),
                    "intended_output": parent.get("intended_output"),
                    "token_estimate": estimate_tokens(prompt_text),
                    "content_sha": f"{parent['content_sha']}-p{n}",
                    "body": prompt_text[:_MAX_BODY_CHARS],
                    "body_pointer": parent["body_pointer"],
                    "fetched_at": None,
                    "parent": parent["id"],
                }
            )
    return children


# ── Recommender — deterministic layer (A8 hybrid) ───────────────────────────

_BENCHMARKS_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "discovery" / "model_benchmarks.json"
)
_ROLE_FIT_THRESHOLD = 70  # benchmark role_fit >= this ⇒ the model "is" that class
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+.-]{2,}")
_STOPWORDS = frozenset(
    {"the", "and", "for", "with", "that", "this", "from", "into", "when",
     "then", "your", "our", "are", "has", "have", "will", "should", "must",
     "prompt", "prompts", "model", "task", "use", "using"}
)


def _context_tokens(context: Any) -> Optional[int]:
    """'128K' → 131072; '4K' → 4096; plain ints pass through."""
    if isinstance(context, (int, float)) and context > 0:
        return int(context)
    m = re.match(r"^\s*(\d+)\s*[kK]\s*$", str(context or ""))
    return int(m.group(1)) * 1024 if m else None


def model_profile(model: Optional[str]) -> Dict[str, Any]:
    """Role classes + context window for a model name — registry tags ∪
    ``model_benchmarks.json role_fit``. Unknown models yield an honest
    empty profile (factors degrade to neutral, never raise)."""
    profile: Dict[str, Any] = {
        "model": model, "role_classes": [], "context_tokens": None, "known": False,
    }
    if not model:
        return profile
    name = str(model).split(":", 1)[0].strip().lower()
    classes: set = set()
    try:
        from models.download import MODEL_REGISTRY

        for key, entry in MODEL_REGISTRY.items():
            ollama = str(entry.get("ollama", "")).split(":", 1)[0].lower()
            if name in (key.lower(), ollama):
                classes |= set(entry.get("tags") or []) & set(MODEL_ROLE_CLASSES)
                profile["context_tokens"] = _context_tokens(entry.get("context"))
                profile["known"] = True
                break
    except Exception:  # noqa: BLE001 — registry import must never break reads
        pass
    try:
        bench = json.loads(_BENCHMARKS_FILE.read_text(encoding="utf-8"))
        for key, entry in bench.items():
            if key.startswith("_") or not isinstance(entry, dict):
                continue
            if key.split(":", 1)[0].lower() == name:
                fit = entry.get("role_fit") or {}
                classes |= {
                    c for c, v in fit.items()
                    if c in MODEL_ROLE_CLASSES
                    and isinstance(v, (int, float)) and v >= _ROLE_FIT_THRESHOLD
                }
                profile["known"] = True
                break
    except (OSError, ValueError):
        pass
    profile["role_classes"] = sorted(classes)
    return profile


def _task_keywords(task: str) -> List[str]:
    return [
        w for w in _WORD_RE.findall((task or "").lower()) if w not in _STOPWORDS
    ]


def score_prompts(
    prompts: List[Dict[str, Any]],
    task: str = "",
    model: Optional[str] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    """Deterministic scorer with a per-factor breakdown on every hit.

    Each prompt dict carries: id, kind, name, tags[], category?, technique[]?,
    model_fit[]?, token_estimate?. Factors:
      task_tags — task keywords ∩ (tags ∪ category ∪ technique ∪ name words)
      model_fit — declared model_fit vs the model's role classes (exact
                  model-id pins score highest)
      size_fit  — token_estimate vs the model's context window (approximate,
                  never a gate: ≤50% full, ≤100% half credit, over 0)
    Score = 2·task_tags + 1.5·model_fit + 1·size_fit; ties break on id so
    identical inputs always rank identically.
    """
    profile = model_profile(model)
    kw = _task_keywords(task)
    model_name = str(model or "").split(":", 1)[0].strip().lower()
    results: List[Dict[str, Any]] = []
    for p in prompts:
        hay = {
            str(t).lower()
            for t in (p.get("tags") or [])
            if isinstance(t, str)
        }
        if p.get("category"):
            hay.add(str(p["category"]).lower())
        for t in p.get("technique") or []:
            if isinstance(t, str):
                hay.add(t.lower())
        hay |= set(_WORD_RE.findall(str(p.get("name") or "").lower()))
        matched_tags = sorted(w for w in kw if w in hay)
        tag_score = min(1.0, 0.5 * len(matched_tags))

        fit_entries = [
            str(f).lower() for f in (p.get("model_fit") or []) if isinstance(f, str)
        ]
        matched_fit: List[str] = []
        fit_score = 0.0
        if fit_entries and (profile["role_classes"] or model_name):
            pins = [f for f in fit_entries if f not in MODEL_ROLE_CLASSES]
            if model_name and any(model_name == pin.split(":", 1)[0] for pin in pins):
                fit_score = 1.0
                matched_fit = [model_name]
            else:
                overlap = sorted(set(fit_entries) & set(profile["role_classes"]))
                if overlap:
                    fit_score = min(1.0, 0.5 + 0.25 * (len(overlap) - 1))
                    matched_fit = overlap

        est = p.get("token_estimate")
        est = int(est) if isinstance(est, (int, float)) else 0
        ctx = profile["context_tokens"]
        if not ctx:
            size_score = 0.5  # unknown window — neutral, never a gate
        else:
            ratio = est / ctx if ctx else 0
            size_score = 1.0 if ratio <= 0.5 else (0.5 if ratio <= 1.0 else 0.0)

        score = round(2.0 * tag_score + 1.5 * fit_score + 1.0 * size_score, 4)
        results.append(
            {
                "id": p.get("id"),
                "kind": p.get("kind"),
                "name": p.get("name"),
                "score": score,
                "factors": {
                    "task_tags": {"score": tag_score, "matched": matched_tags},
                    "model_fit": {"score": fit_score, "matched": matched_fit},
                    "size_fit": {
                        "score": size_score,
                        "token_estimate": est,
                        "context_tokens": ctx,
                    },
                },
            }
        )
    results.sort(key=lambda r: (-r["score"], str(r["id"])))
    return {
        "task": task,
        "model": model,
        "model_profile": profile,
        "results": results[: max(1, int(limit))],
    }
