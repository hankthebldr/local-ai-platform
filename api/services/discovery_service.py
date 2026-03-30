#!/usr/bin/env python3
"""
Discovery Service — Auto-discover abliterated/uncensored models from HuggingFace

Monitors trusted authors and searches for high-context, abliterated GGUF models.
Results are scored and ranked for the Discover tab.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
from ..logging_config import logger

# ── Configuration ──────────────────────────────────────────────────────────

HF_API_BASE = "https://huggingface.co/api"
HF_TOKEN = os.getenv("HF_TOKEN", "")  # Optional, for higher rate limits

# Cache file for discovered models (persists across restarts)
CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
DISCOVERY_CACHE = CACHE_DIR / "discovered_models.json"

# How often to auto-refresh (seconds) — default 6 hours
DISCOVERY_INTERVAL = int(os.getenv("DISCOVERY_INTERVAL", "21600"))

# ── Trusted Authors ────────────────────────────────────────────────────────
# These are the prolific creators of abliterated/uncensored models.
# The service monitors their repos for new releases.

TRUSTED_AUTHORS = [
    "huihui_ai",            # Prolific abliterator (qwen, llama, mistral variants)
    "DavidAU",              # Creative uncensored merges (MOE, Hivemind, etc.)
    "cognitivecomputations", # Eric Hartford — Dolphin series
    "jaahas",               # Qwen uncensored series
    "mradermacher",         # Large-scale GGUF converter + abliterator
    "TheDrummer",           # Rocinante, UnslopNemo uncensored
    "NousResearch",         # Hermes series
    "Gryphe",               # MythoMax creative models
    "bartowski",            # High-quality GGUF quants
    "unsloth",              # Efficient fine-tunes
]

# Search keywords for broader discovery beyond trusted authors
DISCOVERY_KEYWORDS = [
    "abliterated",
    "uncensored GGUF",
    "heretic uncensored",
    "unsensored",
    "unfiltered GGUF",
]

# Minimum thresholds for a model to be worth showing
MIN_DOWNLOADS = 50
MIN_LIKES = 5


# ── HuggingFace API ───────────────────────────────────────────────────────

def _hf_headers() -> dict:
    headers = {"Accept": "application/json"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    return headers


def search_hf_models(
    query: str,
    author: Optional[str] = None,
    limit: int = 30,
    sort: str = "downloads",
) -> List[Dict]:
    """Search HuggingFace model hub."""
    params = {
        "search": query,
        "limit": limit,
        "sort": sort,
        "direction": "-1",
        "full": "true",
    }
    if author:
        params["author"] = author

    try:
        resp = requests.get(
            f"{HF_API_BASE}/models",
            params=params,
            headers=_hf_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"HF search failed (query={query}, author={author}): {e}")
        return []


def get_model_details(repo_id: str) -> Optional[Dict]:
    """Get detailed model info from HuggingFace."""
    try:
        resp = requests.get(
            f"{HF_API_BASE}/models/{repo_id}",
            headers=_hf_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"HF model detail failed ({repo_id}): {e}")
        return None


# ── Model Analysis ─────────────────────────────────────────────────────────

def _extract_context_window(model_data: dict) -> Optional[int]:
    """Try to extract context window from model card or config."""
    # Check tags for context hints
    tags = model_data.get("tags", [])
    for tag in tags:
        tag_lower = tag.lower()
        for ctx in ["256k", "128k", "64k", "32k", "16k", "8k", "4k"]:
            if ctx in tag_lower:
                return int(ctx.replace("k", "")) * 1000
    # Check model card text
    card = model_data.get("cardData", {}) or {}
    # Check config for max_position_embeddings
    config = card.get("model-index", [])
    return None


def _is_abliterated(model_data: dict) -> bool:
    """Check if a model is abliterated/uncensored."""
    name = (model_data.get("modelId") or model_data.get("id", "")).lower()
    tags = [t.lower() for t in model_data.get("tags", [])]
    all_text = name + " " + " ".join(tags)

    abliteration_signals = [
        "abliterated", "abliterate", "uncensored", "unsensored",
        "heretic", "unfiltered", "unrestricted",
    ]
    return any(signal in all_text for signal in abliteration_signals)


def _is_gguf_available(model_data: dict) -> bool:
    """Check if model has GGUF files or is a GGUF repo."""
    tags = [t.lower() for t in model_data.get("tags", [])]
    name = (model_data.get("modelId") or model_data.get("id", "")).lower()
    siblings = model_data.get("siblings", [])

    if "gguf" in tags or "gguf" in name:
        return True
    # Check file list for .gguf files
    for f in siblings:
        if f.get("rfilename", "").endswith(".gguf"):
            return True
    return False


def _extract_param_size(model_data: dict) -> Optional[str]:
    """Try to extract parameter size from model name/tags."""
    name = (model_data.get("modelId") or model_data.get("id", "")).lower()
    tags = [t.lower() for t in model_data.get("tags", [])]

    import re
    # Look for patterns like 7b, 8b, 13b, 14b, 27b, 32b, 70b
    for text in [name] + tags:
        match = re.search(r"(\d+\.?\d*)\s*b\b", text)
        if match:
            return match.group(1) + "B"
    return None


def _estimate_gguf_size_gb(param_size: Optional[str], quant: str = "Q4_K_M") -> float:
    """Rough estimate of GGUF file size for a given param count and quant."""
    if not param_size:
        return 0
    try:
        params_b = float(param_size.replace("B", "").replace("b", ""))
    except ValueError:
        return 0

    # Rough bytes-per-param for common quants
    bpp = {"Q3_K_M": 0.45, "Q4_K_M": 0.55, "Q5_K_M": 0.65, "Q6_K": 0.75, "Q8_0": 1.0}
    return round(params_b * bpp.get(quant, 0.55), 1)


# ── Scoring ────────────────────────────────────────────────────────────────

def score_discovered_model(model: dict) -> float:
    """
    Score a discovered model for ranking in the Discover tab.

    Higher = more desirable for the user's priorities:
      - abliterated/uncensored    +40
      - large context (128K+)     +30
      - large context (64K+)      +20
      - GGUF available            +20
      - trusted author            +15
      - high downloads (>1000)    +10
      - high likes (>50)          +5
      - recent (< 30 days old)    +10
      - fits RAM                  +10
    """
    score = 0.0

    if model.get("is_abliterated"):
        score += 40

    ctx = model.get("context_window") or 0
    if ctx >= 128000:
        score += 30
    elif ctx >= 64000:
        score += 20
    elif ctx >= 32000:
        score += 10

    if model.get("has_gguf"):
        score += 20
    if model.get("is_trusted_author"):
        score += 15

    downloads = model.get("downloads", 0)
    if downloads >= 1000:
        score += 10
    elif downloads >= 100:
        score += 5

    likes = model.get("likes", 0)
    if likes >= 50:
        score += 5

    # Recency bonus
    created = model.get("created_at")
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days
            if age_days <= 30:
                score += 10
            elif age_days <= 90:
                score += 5
        except Exception:
            pass

    if model.get("fits_ram", True):
        score += 10

    return score


# ── Discovery Engine ───────────────────────────────────────────────────────

def discover_models(max_model_ram_gb: float = 50) -> List[Dict]:
    """
    Run full discovery: search trusted authors + keyword searches on HuggingFace.
    Returns scored and deduplicated model list.
    """
    logger.info("Starting model discovery from HuggingFace...")
    seen_ids = set()
    results = []

    # 1. Search trusted authors for abliterated/uncensored models
    for author in TRUSTED_AUTHORS:
        for keyword in ["abliterated", "uncensored"]:
            models = search_hf_models(query=keyword, author=author, limit=15)
            for m in models:
                repo_id = m.get("modelId") or m.get("id", "")
                if repo_id in seen_ids:
                    continue
                seen_ids.add(repo_id)

                if not _is_abliterated(m):
                    continue

                downloads = m.get("downloads", 0)
                likes = m.get("likes", 0)
                if downloads < MIN_DOWNLOADS and likes < MIN_LIKES:
                    continue

                param_size = _extract_param_size(m)
                est_size = _estimate_gguf_size_gb(param_size)
                ctx = _extract_context_window(m)
                has_gguf = _is_gguf_available(m)

                entry = {
                    "repo_id": repo_id,
                    "author": repo_id.split("/")[0] if "/" in repo_id else "",
                    "name": repo_id.split("/")[-1] if "/" in repo_id else repo_id,
                    "param_size": param_size,
                    "estimated_size_gb": est_size,
                    "context_window": ctx,
                    "has_gguf": has_gguf,
                    "is_abliterated": True,
                    "is_trusted_author": True,
                    "downloads": downloads,
                    "likes": likes,
                    "tags": m.get("tags", []),
                    "created_at": m.get("createdAt") or m.get("lastModified"),
                    "pipeline_tag": m.get("pipeline_tag", ""),
                    "fits_ram": est_size <= max_model_ram_gb if est_size > 0 else True,
                }
                entry["score"] = score_discovered_model(entry)
                results.append(entry)

    # 2. Broad keyword searches
    for keyword in DISCOVERY_KEYWORDS:
        models = search_hf_models(query=keyword, limit=30, sort="likes")
        for m in models:
            repo_id = m.get("modelId") or m.get("id", "")
            if repo_id in seen_ids:
                continue
            seen_ids.add(repo_id)

            if not _is_abliterated(m):
                continue

            downloads = m.get("downloads", 0)
            likes = m.get("likes", 0)
            if downloads < MIN_DOWNLOADS and likes < MIN_LIKES:
                continue

            param_size = _extract_param_size(m)
            est_size = _estimate_gguf_size_gb(param_size)
            ctx = _extract_context_window(m)
            has_gguf = _is_gguf_available(m)
            author = repo_id.split("/")[0] if "/" in repo_id else ""

            entry = {
                "repo_id": repo_id,
                "author": author,
                "name": repo_id.split("/")[-1] if "/" in repo_id else repo_id,
                "param_size": param_size,
                "estimated_size_gb": est_size,
                "context_window": ctx,
                "has_gguf": has_gguf,
                "is_abliterated": True,
                "is_trusted_author": author in TRUSTED_AUTHORS,
                "downloads": downloads,
                "likes": likes,
                "tags": m.get("tags", []),
                "created_at": m.get("createdAt") or m.get("lastModified"),
                "pipeline_tag": m.get("pipeline_tag", ""),
                "fits_ram": est_size <= max_model_ram_gb if est_size > 0 else True,
            }
            entry["score"] = score_discovered_model(entry)
            results.append(entry)

    # Sort by score
    results.sort(key=lambda m: m.get("score", 0), reverse=True)

    logger.info(f"Discovery complete: {len(results)} models found")
    return results


# ── Cache Management ───────────────────────────────────────────────────────

def save_discovery_cache(models: List[Dict]):
    """Save discovered models to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(models),
        "models": models,
    }
    DISCOVERY_CACHE.write_text(json.dumps(cache, indent=2, default=str))
    logger.info(f"Discovery cache saved: {len(models)} models")


def load_discovery_cache() -> Optional[Dict]:
    """Load cached discovery results."""
    if not DISCOVERY_CACHE.exists():
        return None
    try:
        cache = json.loads(DISCOVERY_CACHE.read_text())
        return cache
    except Exception as e:
        logger.error(f"Failed to load discovery cache: {e}")
        return None


def is_cache_fresh() -> bool:
    """Check if the cached results are still within the refresh interval."""
    cache = load_discovery_cache()
    if not cache:
        return False
    try:
        ts = datetime.fromisoformat(cache["timestamp"])
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < DISCOVERY_INTERVAL
    except Exception:
        return False


def get_cached_or_discover(max_model_ram_gb: float = 50, force: bool = False) -> Dict:
    """
    Return cached results if fresh, otherwise run discovery.
    Use force=True to bypass cache.
    """
    if not force and is_cache_fresh():
        cache = load_discovery_cache()
        return cache

    models = discover_models(max_model_ram_gb=max_model_ram_gb)
    save_discovery_cache(models)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(models),
        "models": models,
    }
