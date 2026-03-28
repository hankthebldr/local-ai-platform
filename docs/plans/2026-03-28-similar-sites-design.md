# Similar Sites Finder — Design Document

**Date**: 2026-03-28
**Status**: Approved (v2 — added geo-based search)
**Module**: `similar_sites/`

## Overview

A local web application that takes a URL and finds similar websites, optionally scoped to a geographic region. Uses a hybrid approach: scrape and analyze the input site's content, then search the web for related sites — filtered by country/region when specified — score them for similarity, and present grouped results.

**Example use cases:**
- "Find sites similar to Shopify" → global results
- "Find sites similar to Shopify **in Thailand**" → Thai e-commerce platforms, local alternatives
- "Find sites similar to this Thai news site" → other Thai news outlets, SE Asian media

Lives within local-ai-platform as a separate FastAPI app (port 8001), independently runnable, with a clean JSON API designed for future LLM integration.

## Architecture

```
User enters URL + optional region → Web UI (browser, port 8001)
                                      ↓
                                FastAPI backend
                                      ↓
              ┌───────────────────────┼───────────────────────┐
          Scraper                 GeoResolver              Search Engine
       (extract content,      (resolve region →          (DuckDuckGo, swappable)
        keywords, meta)        country code, TLD,              ↓
              ↓                 locale, geo-keywords)    Raw search results
        Site Profile                  ↓                        ↓
        (title, desc,           GeoContext               Similarity Scorer
         keywords, category)    (code, name, TLDs,       (compare profiles +
              ↓                  locale, terms)            geo relevance)
              └───────────┬───────────┴────────────────────────┘
                          ↓
                  Grouped & Ranked Results
                  (with geo-relevance indicators)
                          ↓
                    JSON API response → Web UI renders results
```

## Module Structure

```
similar_sites/
├── __init__.py
├── app.py              # FastAPI app, serves UI + API
├── scraper.py          # URL content extraction
├── analyzer.py         # Keyword/category extraction from scraped content
├── geo.py              # Region resolution, country TLDs, locale mapping
├── search.py           # Search backend interface + DuckDuckGo impl
├── scorer.py           # Similarity scoring, geo-relevance, grouping
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
- Detect page language from `<html lang="...">` or `<meta>` tags (feeds into geo context)

### Step 2 — Analysis (`analyzer.py`)
- Build a site profile from scraped data:
  - **Keywords**: TF-IDF on body text, top 10-15 terms
  - **Category**: Simple classifier based on keywords (tech, news, shopping, blog, SaaS, etc.)
  - **Domain type**: blog, e-commerce, docs, forum, etc.
- Uses `scikit-learn` TfidfVectorizer — no LLM needed

### Step 3 — Geo Resolution (`geo.py`)

New core module. Resolves a user-provided region into a structured `GeoContext` that the search and scoring layers consume.

**Input:** User can specify region in flexible ways:
- Country name: `"Thailand"`, `"Japan"`, `"Brazil"`
- Country code: `"th"`, `"jp"`, `"br"`
- Region: `"Southeast Asia"`, `"Europe"`, `"Latin America"`
- `None` → global search (no geo filter)

**GeoContext dataclass:**
```python
@dataclass
class GeoContext:
    country_code: str          # ISO 3166-1 alpha-2, e.g. "th"
    country_name: str          # "Thailand"
    region_name: str           # "Southeast Asia"
    ddg_region: str            # DuckDuckGo region code, e.g. "th-th"
    country_tlds: list[str]    # [".th", ".co.th"]
    geo_keywords: list[str]    # ["Thailand", "Thai", "Bangkok"]
    locale_hint: str           # "th" — language code for search bias
```

**Built-in data:**
- A `COUNTRY_REGISTRY` dict mapping ~50 most common countries with:
  - Name, code, region, TLDs, DDG region code, common geo-keywords, language
- Covers all major markets; extensible by adding entries
- Fuzzy matching on input: `"thai"` → Thailand, `"uk"` → United Kingdom

**Region support:**
- If user provides a region like `"Southeast Asia"`, resolve to a `GeoContext` per country in that region
- Search queries run against each country, results merged and deduplicated

**No external API needed** — this is a static lookup table shipped with the module.

### Step 4 — Search (`search.py`)

- Abstract `SearchBackend` interface: `search(query, num_results, region?) -> list[SearchResult]`
- DuckDuckGo implementation via `duckduckgo-search` library
  - Uses DDG `region` parameter when `GeoContext` is provided (e.g. `region="th-th"`)
- Constructs queries adapted for geo context:

**Without region (global):**
  - `"sites like {domain}"`
  - `"{category} {top keywords} site"`
  - `"alternatives to {site title}"`

**With region (e.g. Thailand):**
  - `"sites like {domain} in Thailand"`
  - `"{category} {top keywords} site Thailand"`
  - `"alternatives to {site title} Thai"`
  - `"{category} site {country_tld}"` (e.g. `"shopping site .th"`)
  - `"best {category} websites Thailand {year}"`

- Deduplicates results, excludes input URL
- When geo-filtered, boosts results with matching country TLD in their domain

### Step 5 — Scoring & Grouping (`scorer.py`)

- Score similarity: keyword overlap + category match (0-100 base)
- **Geo-relevance scoring** (when region specified):
  - **TLD match** (+15): domain ends with country TLD (`.th`, `.co.th`)
  - **Geo-keyword in content** (+10): title/description mentions country name or geo-keywords
  - **Regional domain** (+5): domain from same broader region
- Group into: **Competitors**, **Same Niche**, **Related Content**, **Similar Tech/Tools**
  - When geo-filtered, add a **Local Alternatives** group for results with strong geo-relevance
- Each result includes a `geo_match` field: `"local"`, `"regional"`, or `"global"`
- Sort within groups by score descending
- Return 15-20 results across groups

## API

### `POST /api/find-similar`
**Request:**
```json
{
  "url": "https://shopify.com",
  "region": "th"
}
```

The `region` field is optional. Accepts:
- Country code: `"th"`, `"jp"`
- Country name: `"Thailand"`, `"Japan"`
- Region name: `"Southeast Asia"`
- Omit or `null` for global search

**Response:**
```json
{
  "input": {
    "url": "https://shopify.com",
    "title": "Shopify",
    "category": "saas",
    "keywords": ["ecommerce", "online store", "shop"],
    "geo": {
      "country": "Thailand",
      "country_code": "th",
      "region": "Southeast Asia"
    }
  },
  "groups": [
    {
      "label": "Local Alternatives",
      "sites": [
        {
          "url": "https://www.lnwshop.com",
          "title": "LnwShop - Thai E-commerce Platform",
          "description": "Create your online store in Thailand",
          "score": 82,
          "reason": "Same SaaS/ecommerce category; Thai TLD; overlapping keywords",
          "geo_match": "local"
        }
      ]
    },
    {
      "label": "Competitors",
      "sites": [
        {
          "url": "https://www.wix.com",
          "title": "Wix.com",
          "description": "Create a website with Wix",
          "score": 75,
          "reason": "Same SaaS category, overlapping keywords",
          "geo_match": "global"
        }
      ]
    }
  ]
}
```

### `GET /api/regions`
Returns the list of supported regions for the UI dropdown.

```json
{
  "countries": [
    {"code": "th", "name": "Thailand", "region": "Southeast Asia"},
    {"code": "jp", "name": "Japan", "region": "East Asia"},
    ...
  ],
  "regions": ["Southeast Asia", "East Asia", "Europe", "North America", ...]
}
```

### `GET /`
Serves the Web UI.

## Web UI

- Single-page app via Jinja2 template
- Dark background, cyan/magenta/blue accents (matching CLI Rich theme)
- **URL input field** + **region selector** (searchable dropdown with country flags/names, "Global" default) + **"Find Similar" button**
- Region selector populated from `GET /api/regions`
- Loading spinner with status text ("Scraping...", "Analyzing...", "Searching in Thailand...")
- Grouped card layout with score badges, clickable URLs, similarity reasons
- **Geo-match badge** on each result: "Local", "Regional", or "Global" tag
- Collapsible groups with count indicators
- When geo-filtered, "Local Alternatives" group appears first with a distinct accent color

## CLI

- `python -m similar_sites.cli https://example.com` — global search
- `python -m similar_sites.cli https://example.com --region th` — Thailand
- `python -m similar_sites.cli https://example.com --region "Southeast Asia"` — multi-country
- Uses Rich library (consistent with `cli/chat.py`)
- Grouped results as Rich tables/panels
- Geo-match column in output table
- Calls backend code directly (no HTTP needed)

## Dependencies (new)

- `httpx` — async HTTP client
- `beautifulsoup4` — HTML parsing
- `duckduckgo-search` — search backend
- `scikit-learn` — TF-IDF keyword extraction
- `jinja2` — templating (likely already present)

No additional dependencies for geo — it's a static lookup table, no geocoding API needed.

## Future LLM Integration (not built now)

Designed interface boundaries so these upgrades require no pipeline changes:
- `analyzer.py` → swap TF-IDF for local LLM categorization via Ollama
- `scorer.py` → use local model embeddings for semantic similarity
- `search.py` → LLM-assisted query generation
- `geo.py` → LLM could auto-detect likely region from site content/language
- Main API (port 8000) can call `POST /api/find-similar` directly

## Future Geo Enhancements (not built now)

- Auto-detect region from input URL's TLD (`.th` → Thailand)
- IP geolocation of input URL's server
- Language detection on scraped content → suggest region
- Multi-region comparison: "Show me alternatives in Thailand AND Vietnam"
