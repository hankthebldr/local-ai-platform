# Similar Sites Finder — Design Document

**Date**: 2026-03-28
**Status**: Approved
**Module**: `similar-sites/`

## Overview

A local web application that takes a URL and finds similar websites using a hybrid approach: scrape and analyze the input site's content, then search the web for related sites, score them for similarity, and present grouped results.

Lives within local-ai-platform as a separate FastAPI app (port 8001), independently runnable, with a clean JSON API designed for future LLM integration.

## Architecture

```
User enters URL → Web UI (browser, port 8001)
                    ↓
              FastAPI backend
                    ↓
         ┌─────────┴──────────┐
     Scraper                Search Engine
  (extract content,       (DuckDuckGo, swappable)
   keywords, meta)              ↓
         ↓              Raw search results
   Site Profile                 ↓
   (title, desc,         Similarity Scorer
    keywords, category)   (compare profiles)
         └─────────┬──────────┘
                    ↓
            Grouped & Ranked Results
                    ↓
              JSON API response → Web UI renders results
```

## Module Structure

```
similar-sites/
├── app.py              # FastAPI app, serves UI + API
├── scraper.py          # URL content extraction
├── analyzer.py         # Keyword/category extraction from scraped content
├── search.py           # Search backend interface + DuckDuckGo impl
├── scorer.py           # Similarity scoring & grouping
├── templates/
│   └── index.html      # Single-page Web UI (Jinja2)
├── static/
│   ├── style.css       # Project color scheme (cyan/magenta/blue, dark bg)
│   └── app.js          # Frontend logic (fetch, render results)
├── cli.py              # CLI entry point
└── requirements.txt    # Module-specific deps
```

## Core Pipeline

### Step 1 — Scraping (`scraper.py`)
- Fetch URL with `httpx` (async, timeout handling)
- Extract: title, meta description, meta keywords, OG tags, headings, body text (~2000 words)
- Strip HTML with `BeautifulSoup`
- Extract outbound links and their domains

### Step 2 — Analysis (`analyzer.py`)
- Build a site profile from scraped data:
  - **Keywords**: TF-IDF on body text, top 10-15 terms
  - **Category**: Simple classifier based on keywords (tech, news, shopping, blog, SaaS, etc.)
  - **Domain type**: blog, e-commerce, docs, forum, etc.
- Uses `scikit-learn` TfidfVectorizer — no LLM needed

### Step 3 — Search (`search.py`)
- Abstract `SearchBackend` interface: `search(query, num_results) -> list[SearchResult]`
- DuckDuckGo implementation via `duckduckgo-search` library
- Constructs 2-3 queries from site profile:
  - `"sites like {domain}"`
  - `"{category} {top keywords} site"`
  - `"alternatives to {site title}"`
- Deduplicates results, excludes input URL

### Step 4 — Scoring & Grouping (`scorer.py`)
- Quick-scrape each result (title + meta description only)
- Score similarity: keyword overlap + category match (0-100 scale)
- Group into: **Competitors**, **Same Niche**, **Related Content**, **Similar Tech/Tools**
- Sort within groups by score descending
- Return 15-20 results across groups

## API

### `POST /api/find-similar`
**Request:**
```json
{"url": "https://example.com"}
```

**Response:**
```json
{
  "input": {"url": "...", "title": "...", "category": "..."},
  "groups": [
    {
      "label": "Competitors",
      "sites": [
        {
          "url": "...",
          "title": "...",
          "description": "...",
          "score": 87,
          "reason": "Same SaaS category, overlapping keywords"
        }
      ]
    }
  ]
}
```

### `GET /`
Serves the Web UI.

## Web UI

- Single-page app via Jinja2 template
- Dark background, cyan/magenta/blue accents (matching CLI Rich theme)
- URL input + "Find Similar" button
- Loading spinner with status text ("Scraping...", "Analyzing...", "Searching...")
- Grouped card layout with score badges, clickable URLs, similarity reasons
- Collapsible groups with count indicators

## CLI

- `python similar-sites/cli.py https://example.com`
- Uses Rich library (consistent with `cli/chat.py`)
- Grouped results as Rich tables/panels
- Calls backend code directly (no HTTP needed)

## Dependencies (new)

- `httpx` — async HTTP client
- `beautifulsoup4` — HTML parsing
- `duckduckgo-search` — search backend
- `scikit-learn` — TF-IDF keyword extraction
- `jinja2` — templating (likely already present)

## Future LLM Integration (not built now)

Designed interface boundaries so these upgrades require no pipeline changes:
- `analyzer.py` → swap TF-IDF for local LLM categorization via Ollama
- `scorer.py` → use local model embeddings for semantic similarity
- `search.py` → LLM-assisted query generation
- Main API (port 8000) can call `POST /api/find-similar` directly
