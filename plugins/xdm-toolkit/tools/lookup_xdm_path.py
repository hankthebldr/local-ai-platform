"""
lookup_xdm_path — map a vendor field name (or short description) to
candidate XDM paths.

Phase 3 rewrite: replaces the Phase 0 30-row seed catalogue with a real
synonym index derived from `docs/seed/xql/field_anchors.json` (375 XDM
paths, each with vendor-field synonyms collected from the corpus and
frequency counts).

Confidence model:
  HIGH    exact synonym match (case-insensitive) on the query token
  MEDIUM  substring match on a synonym, OR exact leaf-name match on the
          xdm path
  LOW     fuzzy fallback (token-overlap heuristic)

Companion-pair partners and XDM_CONST enum values are still served from
the typed schema (plugins/xdm-toolkit/tools/_data/xdm_schema.json) so
the results stay consistent with the analyse_xql tool.

Heuristic, not a real semantic embedding lookup — the agent
xdm-schema-navigator handles ambiguous cases with full LLM context. This
tool is the fast path for obvious matches during agentic loops.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ANCHORS_PATH = Path(__file__).resolve().parents[3] / "docs" / "seed" / "xql" / "field_anchors.json"

# Companion pairs whose strict-subset partners trigger ERR when only one
# side is mapped (per Phase 0 operator decision: IP / MAC / port / user /
# host pairs are ERR-grade, the rest are WARN).
_COMPANION_PAIRS: List[Tuple[str, str]] = [
    ("xdm.source.ipv4", "xdm.source.host.ipv4_addresses"),
    ("xdm.target.ipv4", "xdm.target.host.ipv4_addresses"),
    ("xdm.source.host.mac_addresses", "xdm.source.host.hostname"),
    ("xdm.target.host.mac_addresses", "xdm.target.host.hostname"),
    ("xdm.source.port", "xdm.target.port"),
    ("xdm.source.user.username", "xdm.source.user.upn"),
    ("xdm.target.user.username", "xdm.target.user.upn"),
    ("xdm.source.host.hostname", "xdm.source.host.fqdn"),
    ("xdm.target.host.hostname", "xdm.target.host.fqdn"),
    ("xdm.network.application_protocol", "xdm.network.application_protocol_category"),
    ("xdm.auth.outcome", "xdm.auth.outcome_reason"),
    ("xdm.event.outcome", "xdm.event.outcome_reason"),
]


@lru_cache(maxsize=1)
def _anchors() -> Dict[str, Any]:
    """Load the anchor DB once; cache it."""
    if not _ANCHORS_PATH.is_file():
        return {"anchors": {}, "anchor_count": 0}
    return json.loads(_ANCHORS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _synonym_index() -> List[Tuple[str, str, int, int]]:
    """Return [(synonym_lower, xdm_path, synonym_count, path_frequency), ...]."""
    out: List[Tuple[str, str, int, int]] = []
    for path, meta in _anchors().get("anchors", {}).items():
        freq = int(meta.get("frequency", 0))
        for syn in meta.get("synonyms", []):
            name = syn.get("synonym", "")
            if not name:
                continue
            out.append((name.lower(), path, int(syn.get("count", 1)), freq))
    return out


@lru_cache(maxsize=1)
def _all_paths() -> List[str]:
    return sorted(_anchors().get("anchors", {}).keys())


def _xdm_const_for(path: str) -> List[str] | None:
    """Best-effort XDM_CONST enum lookup against the local schema JSON."""
    try:
        from ._schema import xdm_field_enum  # local relative import works at runtime
        return xdm_field_enum(path)
    except Exception:
        return None


def _companion_partner(path: str) -> str | None:
    for a, b in _COMPANION_PAIRS:
        if path == a:
            return b
        if path == b:
            return a
    return None


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _score_matches(query: str) -> List[Dict[str, Any]]:
    """Return ranked candidate matches with confidence labels."""
    q = _normalise(query)
    if not q:
        return []
    q_tokens = set(q.split("_"))
    syn_idx = _synonym_index()

    # path -> (confidence, raw_score)
    best: Dict[str, Tuple[str, float]] = {}

    def consider(path: str, confidence: str, score: float) -> None:
        order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        prev = best.get(path)
        if prev is None or order[confidence] > order[prev[0]] or (
            order[confidence] == order[prev[0]] and score > prev[1]
        ):
            best[path] = (confidence, score)

    # Pass 1: exact synonym match (HIGH).
    for syn_lower, path, count, freq in syn_idx:
        syn_norm = _normalise(syn_lower)
        if syn_norm == q:
            consider(path, "HIGH", count * 1000 + freq)

    # Pass 2: substring on synonym OR exact leaf name (MEDIUM).
    for syn_lower, path, count, freq in syn_idx:
        syn_norm = _normalise(syn_lower)
        if q in syn_norm or syn_norm in q:
            consider(path, "MEDIUM", count * 10 + freq * 0.1)
    for path in _all_paths():
        leaf = path.rsplit(".", 1)[-1].lower()
        if leaf == q:
            consider(path, "MEDIUM", 50.0)

    # Pass 3: token overlap fallback (LOW).
    if not best:
        for path in _all_paths():
            path_tokens = set(re.split(r"[._]", path.lower()))
            overlap = len(q_tokens & path_tokens)
            if overlap > 0:
                consider(path, "LOW", overlap)

    ranked = sorted(best.items(), key=lambda item: (
        {"HIGH": 3, "MEDIUM": 2, "LOW": 1}[item[1][0]],
        item[1][1],
    ), reverse=True)

    out: List[Dict[str, Any]] = []
    for path, (confidence, score) in ranked:
        enum = _xdm_const_for(path)
        out.append({
            "xdm_path": path,
            "confidence": confidence,
            "score": round(score, 2),
            "companion": _companion_partner(path),
            "xdm_const_values": enum,
        })
    return out


def execute(query: str = "", top_k: int = 5, **_unused) -> Dict[str, Any]:
    """Plugin entrypoint.

    Args:
        query: vendor field name (e.g. "src_ip") or short description
               (e.g. "source IP address").
        top_k: 1..10. Defaults to 5.

    Returns:
        {
            "query": str,
            "matches": [{xdm_path, confidence, score, companion, xdm_const_values}],
            "total_anchors": int,
        }
    """
    if not isinstance(query, str) or not query.strip():
        return {"query": query, "matches": [], "total_anchors": _anchors().get("anchor_count", 0)}
    k = max(1, min(int(top_k or 5), 10))
    matches = _score_matches(query.strip())[:k]
    return {
        "query": query,
        "matches": matches,
        "total_anchors": _anchors().get("anchor_count", 0),
    }
