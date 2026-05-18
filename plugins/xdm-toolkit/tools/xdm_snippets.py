"""
xdm_snippets — look up XQL/XDM code snippets by category, tag, or
pattern-family hint.

Reads from docs/seed/xql/snippets.json (112 entries) shipped in Phase 1.
Returns ranked candidates with the snippet body, difficulty, and any
XDM fields the snippet touches.

Tool contract:
    Input:
      query: str          — free-text query (matched against title, tags,
                            description). Optional.
      category: str       — exact category filter, e.g. "Data Model Rules".
                            Optional.
      pattern: "A"|"B"|"C"|"D"
                          — pattern family hint. Maps to category/tag
                            keywords. Optional.
      tags: List[str]     — required tags (all must match). Optional.
      top_k: int          — 1..20, default 5.
    Output:
      {
        "query": str,
        "matches": [{id, title, category, code, tags, difficulty,
                     relatedFields, score}],
        "total_snippets": int,
      }
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_SNIPPETS_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs" / "seed" / "xql" / "snippets.json"
)


_PATTERN_HINTS = {
    "A": {"keywords": ["json_extract", "json", "extract"], "categories": ["Field Extraction", "Data Model Rules"]},
    "B": {"keywords": ["split", "arrayindex", "positional", "syslog"], "categories": ["Field Extraction", "Parsing Rules"]},
    "C": {"keywords": ["regex", "regextract", "label", "key=value"], "categories": ["Field Extraction", "Parsing Rules"]},
    "D": {"keywords": ["arrow", "->", "object", "nested"], "categories": ["Data Model Rules"]},
}


@lru_cache(maxsize=1)
def _all_snippets() -> List[Dict[str, Any]]:
    if not _SNIPPETS_PATH.is_file():
        return []
    data = json.loads(_SNIPPETS_PATH.read_text(encoding="utf-8"))
    return list(data.get("snippets", []))


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _score(snippet: Dict[str, Any], query_tokens: set[str], pattern_keywords: set[str]) -> float:
    score = 0.0
    title = _normalise(snippet.get("title", ""))
    desc = _normalise(snippet.get("description", ""))
    tags = {_normalise(t) for t in snippet.get("tags", [])}

    # Token overlap on title (highest weight).
    for tok in query_tokens:
        if tok in title.split():
            score += 8.0
        elif tok in title:
            score += 4.0
        if tok in desc:
            score += 1.0
        for tag in tags:
            if tok in tag:
                score += 3.0
    # Pattern keyword hits.
    for kw in pattern_keywords:
        if kw in title or kw in desc or kw in " ".join(tags):
            score += 2.0
    return score


def execute(
    query: str = "",
    category: str = "",
    pattern: str = "",
    tags: List[str] | None = None,
    top_k: int = 5,
    **_unused,
) -> Dict[str, Any]:
    snippets = _all_snippets()
    if not snippets:
        return {"query": query, "matches": [], "total_snippets": 0}

    # Filters
    if category:
        cat_norm = category.strip()
        snippets = [s for s in snippets if s.get("category") == cat_norm]
    if tags:
        wanted = {_normalise(t) for t in tags}
        snippets = [
            s for s in snippets
            if wanted.issubset({_normalise(t) for t in s.get("tags", [])})
        ]

    pattern_hint = _PATTERN_HINTS.get(pattern.upper().strip()) if pattern else None
    pattern_keywords = set(pattern_hint["keywords"]) if pattern_hint else set()
    pattern_categories = set(pattern_hint["categories"]) if pattern_hint else set()
    if pattern_hint and not category:
        snippets = [s for s in snippets if s.get("category") in pattern_categories]

    # Score + rank.
    q_tokens = set(_normalise(query).split()) if query else set()
    scored: List[tuple[float, Dict[str, Any]]] = []
    for s in snippets:
        sc = _score(s, q_tokens, pattern_keywords)
        if q_tokens or pattern_keywords:
            if sc <= 0:
                continue
        scored.append((sc, s))

    scored.sort(key=lambda t: t[0], reverse=True)

    k = max(1, min(int(top_k or 5), 20))
    out_matches: List[Dict[str, Any]] = []
    for sc, s in scored[:k]:
        out_matches.append({
            "id": s.get("id"),
            "title": s.get("title"),
            "category": s.get("category"),
            "code": s.get("code"),
            "tags": s.get("tags", []),
            "difficulty": s.get("difficulty"),
            "relatedFields": s.get("relatedFields", []),
            "score": round(sc, 2),
        })

    return {
        "query": query,
        "matches": out_matches,
        "total_snippets": len(_all_snippets()),
    }
