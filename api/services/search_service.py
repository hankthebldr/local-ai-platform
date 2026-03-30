#!/usr/bin/env python3
"""
Search Service — Web search with cascading backends for RAG-style augmentation.

Priority order:
  1. SearXNG (self-hosted, privacy-first)
  2. DuckDuckGo HTML (no API key, zero deps)
  3. Brave Search API (optional key, highest quality)

Search results are formatted as a system message for injection into the
chat context before the LLM call.
"""

import json
import os
import re
import html
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus

import aiohttp
from dotenv import load_dotenv

from ..logging_config import logger

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────
# Config can be updated at runtime via the settings API.
# Priority: runtime config file > environment variables > defaults.

_CONFIG_DIR = Path(__file__).parent.parent.parent / "data" / "config"
_SEARCH_CONFIG_FILE = _CONFIG_DIR / "search_settings.json"


def _load_config() -> dict:
    """Load search config from file, falling back to env vars."""
    file_config = {}
    if _SEARCH_CONFIG_FILE.exists():
        try:
            file_config = json.loads(_SEARCH_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "searxng_url": file_config.get("searxng_url", os.getenv("SEARXNG_URL", "")),
        "brave_api_key": file_config.get("brave_api_key", os.getenv("BRAVE_SEARCH_API_KEY", "")),
        "search_timeout": file_config.get("search_timeout", int(os.getenv("SEARCH_TIMEOUT", "10"))),
        "max_results": file_config.get("max_results", int(os.getenv("MAX_SEARCH_RESULTS", "5"))),
        "default_backend": file_config.get("default_backend", "auto"),
    }


def save_config(config: dict):
    """Persist search config to disk."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _SEARCH_CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_config() -> dict:
    """Get current search config (public API for settings endpoint)."""
    cfg = _load_config()
    # Mask the API key for display (show last 4 chars)
    key = cfg.get("brave_api_key", "")
    cfg["brave_api_key_masked"] = f"***{key[-4:]}" if len(key) > 4 else ("set" if key else "")
    # Report which backend will actually be used
    cfg["active_backend"] = _resolve_backend(cfg)
    return cfg


def _resolve_backend(cfg: dict) -> str:
    """Determine which backend will be used given current config."""
    if cfg.get("default_backend") not in ("auto", "", None):
        return cfg["default_backend"]
    if cfg.get("searxng_url"):
        return "searxng"
    if cfg.get("brave_api_key"):
        return "brave"
    return "duckduckgo"


# Legacy module-level vars (kept for tests that patch them directly)
SEARXNG_URL = os.getenv("SEARXNG_URL", "")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "10"))
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "5"))


# ── Data Structures ───────────────────────────────────────────────────────

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self):
        return asdict(self)


@dataclass
class SearchResponse:
    query: str
    results: List[SearchResult] = field(default_factory=list)
    backend: str = ""
    error: Optional[str] = None

    def to_dict(self):
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "backend": self.backend,
            "error": self.error,
        }


# ── Intent Detection ──────────────────────────────────────────────────────

# Patterns that strongly suggest the user wants current/web information
_SEARCH_PATTERNS = [
    # Question words
    r"\b(who|what|when|where|why|how)\b.*\?",
    # Recency signals
    r"\b(latest|recent|current|today|yesterday|this week|this month|this year|2025|2026)\b",
    # Lookup signals
    r"\b(search|look up|find|google|check|tell me about)\b",
    # News/events
    r"\b(news|update|announcement|release|launched|happened)\b",
    # Factual queries
    r"\b(price|stock|weather|score|result|status)\b",
    # Comparison / recommendation
    r"\b(best|top|compare|vs|versus|alternative)\b",
]

_SEARCH_RE = [re.compile(p, re.IGNORECASE) for p in _SEARCH_PATTERNS]


def detect_search_intent(message: str) -> bool:
    """
    Heuristic check: does this message likely need web search?
    Returns True if 2+ patterns match (reduces false positives).
    """
    matches = sum(1 for pattern in _SEARCH_RE if pattern.search(message))
    return matches >= 2


# ── Context Formatting ────────────────────────────────────────────────────

_CONTEXT_TEMPLATE = """You have access to the following web search results for the query: "{query}"

{results_text}

INSTRUCTIONS:
- Use the search results above to provide an accurate, up-to-date answer.
- Cite your sources using [1], [2], etc. corresponding to the numbered results.
- If the search results don't contain enough information, say so and answer from your own knowledge.
- Be concise and factual."""


def format_search_context(query: str, results: List[SearchResult]) -> str:
    """Format search results into a system message for context injection."""
    if not results:
        return ""

    results_text = "\n\n".join(
        f"[{i+1}] {r.title}\n    URL: {r.url}\n    {r.snippet}"
        for i, r in enumerate(results)
    )

    return _CONTEXT_TEMPLATE.format(query=query, results_text=results_text)


# ── Search Backends ───────────────────────────────────────────────────────

async def _search_searxng(query: str, max_results: int) -> List[SearchResult]:
    """Search via self-hosted SearXNG instance."""
    if not SEARXNG_URL:
        return []

    url = f"{SEARXNG_URL.rstrip('/')}/search"
    params = {
        "q": query,
        "format": "json",
        "categories": "general",
        "language": "en",
        "safesearch": "0",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT)) as resp:
                if resp.status != 200:
                    logger.warning(f"SearXNG returned status {resp.status}")
                    return []
                data = await resp.json()

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            ))
        logger.info(f"SearXNG returned {len(results)} results for '{query}'")
        return results

    except Exception as e:
        logger.warning(f"SearXNG search failed: {e}")
        return []


async def _search_ddg(query: str, max_results: int) -> List[SearchResult]:
    """Search DuckDuckGo via HTML parsing (no API key needed)."""
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query, "b": ""}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT)) as resp:
                if resp.status != 200:
                    logger.warning(f"DDG returned status {resp.status}")
                    return []
                body = await resp.text()

        results = []
        # Parse result blocks from DDG HTML
        # Each result is in a div with class "result" containing:
        #   - <a class="result__a"> for title + URL
        #   - <a class="result__snippet"> for snippet
        result_blocks = re.findall(
            r'<div[^>]*class="[^"]*result\b[^"]*"[^>]*>(.*?)</div>\s*</div>',
            body, re.DOTALL
        )

        if not result_blocks:
            # Fallback: try a simpler pattern
            result_blocks = re.findall(
                r'class="result__body">(.*?)</div>',
                body, re.DOTALL
            )

        for block in result_blocks[:max_results]:
            # Extract title and URL
            title_match = re.search(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

            if not title_match:
                continue

            raw_url = title_match.group(1)
            # DDG wraps URLs in a redirect — extract the actual URL
            actual_url_match = re.search(r'uddg=([^&]+)', raw_url)
            if actual_url_match:
                from urllib.parse import unquote
                raw_url = unquote(actual_url_match.group(1))

            title = _strip_html(title_match.group(2))
            snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""

            if title and raw_url:
                results.append(SearchResult(title=title, url=raw_url, snippet=snippet))

        logger.info(f"DDG returned {len(results)} results for '{query}'")
        return results

    except Exception as e:
        logger.warning(f"DDG search failed: {e}")
        return []


async def _search_brave(query: str, max_results: int) -> List[SearchResult]:
    """Search via Brave Search API (requires API key)."""
    if not BRAVE_SEARCH_API_KEY:
        return []

    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": query, "count": max_results}
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT)) as resp:
                if resp.status != 200:
                    logger.warning(f"Brave returned status {resp.status}")
                    return []
                data = await resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:max_results]:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            ))
        logger.info(f"Brave returned {len(results)} results for '{query}'")
        return results

    except Exception as e:
        logger.warning(f"Brave search failed: {e}")
        return []


# ── Utilities ──────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text.strip()


# ── Main Search Function ──────────────────────────────────────────────────

async def search(query: str, max_results: int = 0) -> SearchResponse:
    """
    Run a web search using cascading backends.
    Reads runtime config to determine backend priority and credentials.
    Default cascade: DuckDuckGo (no key) → SearXNG (if configured) → Brave (if key set).
    """
    cfg = _load_config()
    if max_results <= 0:
        max_results = cfg.get("max_results", 5)
    timeout = cfg.get("search_timeout", 10)

    # Override module-level vars for backend functions
    global SEARXNG_URL, BRAVE_SEARCH_API_KEY, SEARCH_TIMEOUT
    SEARXNG_URL = cfg.get("searxng_url", "")
    BRAVE_SEARCH_API_KEY = cfg.get("brave_api_key", "")
    SEARCH_TIMEOUT = timeout

    logger.info(f"Web search: '{query}' (max_results={max_results}, backend={_resolve_backend(cfg)})")

    preferred = cfg.get("default_backend", "auto")

    # If a specific backend is requested, try it first
    if preferred == "searxng" and SEARXNG_URL:
        results = await _search_searxng(query, max_results)
        if results:
            return SearchResponse(query=query, results=results, backend="searxng")
    elif preferred == "brave" and BRAVE_SEARCH_API_KEY:
        results = await _search_brave(query, max_results)
        if results:
            return SearchResponse(query=query, results=results, backend="brave")
    elif preferred == "duckduckgo":
        results = await _search_ddg(query, max_results)
        if results:
            return SearchResponse(query=query, results=results, backend="duckduckgo")

    # Auto cascade: DDG first (no key needed), then SearXNG, then Brave
    results = await _search_ddg(query, max_results)
    if results:
        return SearchResponse(query=query, results=results, backend="duckduckgo")

    if SEARXNG_URL:
        results = await _search_searxng(query, max_results)
        if results:
            return SearchResponse(query=query, results=results, backend="searxng")

    if BRAVE_SEARCH_API_KEY:
        results = await _search_brave(query, max_results)
        if results:
            return SearchResponse(query=query, results=results, backend="brave")

    logger.warning(f"All search backends failed for query: '{query}'")
    return SearchResponse(query=query, results=[], error="All search backends failed")
