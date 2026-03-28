# Similar Sites Finder — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local web app that takes a URL, scrapes and analyzes its content, searches for similar sites, scores/groups them, and presents results in a Web UI.

**Architecture:** Separate FastAPI app in `similar-sites/` on port 8001. Pipeline: scrape → analyze (TF-IDF) → search (DuckDuckGo, swappable) → score/group → return JSON. Web UI served via Jinja2. CLI via Rich.

**Tech Stack:** FastAPI, httpx, BeautifulSoup4, scikit-learn (TfidfVectorizer), duckduckgo-search, Jinja2, Rich

**Design Doc:** `docs/plans/2026-03-28-similar-sites-design.md`

---

### Task 1: Scaffold Module + Dependencies

**Files:**
- Create: `similar-sites/__init__.py`
- Create: `similar-sites/requirements.txt`
- Create: `tests/test_similar_sites/__init__.py`

**Step 1: Create the module directory and empty init**

```bash
mkdir -p similar-sites
touch similar-sites/__init__.py
mkdir -p tests/test_similar_sites
touch tests/test_similar_sites/__init__.py
```

**Step 2: Write requirements.txt**

Create `similar-sites/requirements.txt`:
```
httpx>=0.25.0
beautifulsoup4>=4.12.0
duckduckgo-search>=4.0.0
scikit-learn>=1.3.0
jinja2>=3.1.0
rich>=13.0.0
```

**Step 3: Install dependencies**

```bash
source venv/bin/activate
pip install beautifulsoup4 duckduckgo-search scikit-learn
```

Note: `httpx`, `jinja2`, `rich` are already in the main `setup/requirements.txt`.

**Step 4: Commit**

```bash
git add similar-sites/ tests/test_similar_sites/
git commit -m "feat(similar-sites): scaffold module and dependencies"
```

---

### Task 2: Scraper (`similar-sites/scraper.py`)

**Files:**
- Create: `similar-sites/scraper.py`
- Create: `tests/test_similar_sites/test_scraper.py`

**Step 1: Write the failing test**

Create `tests/test_similar_sites/test_scraper.py`:
```python
"""Tests for similar-sites scraper module."""
import pytest
from unittest.mock import AsyncMock, patch

# Minimal HTML fixture
SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Example Tech Blog</title>
    <meta name="description" content="A blog about Python and machine learning">
    <meta name="keywords" content="python, machine learning, AI, tutorials">
    <meta property="og:title" content="Example Tech Blog - ML Tutorials">
    <meta property="og:description" content="Learn ML with Python">
</head>
<body>
    <h1>Welcome to Example Tech Blog</h1>
    <h2>Latest Posts</h2>
    <p>We cover Python programming, machine learning algorithms, and AI tools.
    Our tutorials help developers learn data science and deep learning frameworks
    like PyTorch and TensorFlow.</p>
    <a href="https://pytorch.org">PyTorch</a>
    <a href="https://tensorflow.org">TensorFlow</a>
    <a href="/about">About</a>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_scrape_returns_site_profile():
    """scrape_url should return a SiteProfile with extracted metadata."""
    from similar_sites.scraper import scrape_url, SiteProfile

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = lambda: None

    with patch("similar_sites.scraper.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        profile = await scrape_url("https://example.com")

    assert isinstance(profile, SiteProfile)
    assert profile.title == "Example Tech Blog"
    assert "Python" in profile.meta_description or "python" in profile.meta_description.lower()
    assert len(profile.headings) >= 2
    assert "pytorch.org" in [link.domain for link in profile.outbound_links]


@pytest.mark.asyncio
async def test_scrape_extracts_outbound_links():
    """Should extract external links but not internal ones."""
    from similar_sites.scraper import scrape_url

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = SAMPLE_HTML
    mock_response.raise_for_status = lambda: None

    with patch("similar_sites.scraper.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        profile = await scrape_url("https://example.com")

    # Only external links, not /about
    domains = [link.domain for link in profile.outbound_links]
    assert "pytorch.org" in domains
    assert "tensorflow.org" in domains
    assert "example.com" not in domains


@pytest.mark.asyncio
async def test_scrape_handles_timeout():
    """Should raise a clean error on timeout."""
    from similar_sites.scraper import scrape_url, ScrapeError

    with patch("similar_sites.scraper.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client_cls.return_value = mock_client

        with pytest.raises(ScrapeError, match="timeout"):
            await scrape_url("https://example.com")


import httpx  # needed for the timeout test side_effect
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_similar_sites/test_scraper.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'similar_sites'`

**Step 3: Write implementation**

Create `similar-sites/scraper.py`:
```python
"""Scrape a URL and extract a structured site profile."""

from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup


class ScrapeError(Exception):
    """Raised when scraping fails."""
    pass


@dataclass
class OutboundLink:
    url: str
    domain: str
    text: str = ""


@dataclass
class SiteProfile:
    url: str
    domain: str
    title: str = ""
    meta_description: str = ""
    meta_keywords: list[str] = field(default_factory=list)
    og_title: str = ""
    og_description: str = ""
    headings: list[str] = field(default_factory=list)
    body_text: str = ""
    outbound_links: list[OutboundLink] = field(default_factory=list)


async def scrape_url(url: str, timeout: float = 15.0) -> SiteProfile:
    """Fetch a URL and extract structured metadata into a SiteProfile."""
    parsed = urlparse(url)
    domain = parsed.netloc

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "SimilarSitesFinder/1.0"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.TimeoutException as e:
        raise ScrapeError(f"timeout fetching {url}: {e}")
    except httpx.HTTPStatusError as e:
        raise ScrapeError(f"HTTP {e.response.status_code} fetching {url}")
    except httpx.RequestError as e:
        raise ScrapeError(f"request error fetching {url}: {e}")

    soup = BeautifulSoup(response.text, "html.parser")

    # Title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Meta tags
    meta_desc = _get_meta(soup, "description")
    meta_kw_raw = _get_meta(soup, "keywords")
    meta_keywords = [k.strip() for k in meta_kw_raw.split(",") if k.strip()] if meta_kw_raw else []

    # Open Graph
    og_title = _get_meta(soup, "og:title", attr="property")
    og_desc = _get_meta(soup, "og:description", attr="property")

    # Headings
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"], limit=20):
        text = tag.get_text(strip=True)
        if text:
            headings.append(text)

    # Body text (first ~2000 words)
    body_text = ""
    body = soup.find("body")
    if body:
        for script_or_style in body.find_all(["script", "style", "nav", "footer", "header"]):
            script_or_style.decompose()
        raw_text = body.get_text(separator=" ", strip=True)
        words = raw_text.split()
        body_text = " ".join(words[:2000])

    # Outbound links
    outbound_links = []
    seen_domains = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        absolute = urljoin(url, href)
        link_parsed = urlparse(absolute)
        link_domain = link_parsed.netloc

        if not link_domain or link_domain == domain:
            continue
        if link_domain in seen_domains:
            continue

        seen_domains.add(link_domain)
        outbound_links.append(OutboundLink(
            url=absolute,
            domain=link_domain,
            text=a_tag.get_text(strip=True)[:100],
        ))

    return SiteProfile(
        url=url,
        domain=domain,
        title=title,
        meta_description=meta_desc,
        meta_keywords=meta_keywords,
        og_title=og_title,
        og_description=og_desc,
        headings=headings,
        body_text=body_text,
        outbound_links=outbound_links,
    )


def _get_meta(soup: BeautifulSoup, name: str, attr: str = "name") -> str:
    tag = soup.find("meta", attrs={attr: name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""
```

**Step 4: Add sys.path config so tests can import `similar_sites`**

Create `similar-sites/conftest.py` — actually, better: add a `conftest.py` at project root that adds `similar-sites` to sys.path.

Create `conftest.py` at project root (if it doesn't exist) or add to it:
```python
import sys
from pathlib import Path

# Allow imports from similar-sites/ as "similar_sites"
sys.path.insert(0, str(Path(__file__).parent / "similar-sites"))
```

Also, the package needs to be importable as `similar_sites` (underscore). Rename consideration: since Python can't import hyphenated module names, we need a package inside `similar-sites/` called `similar_sites/`, OR we just name the directory `similar_sites/` from the start.

**Decision: Use `similar_sites/` (underscore) as the directory name** to avoid import hacks. Update all references.

```
similar_sites/
├── __init__.py
├── scraper.py
├── ...
```

The `conftest.py` at project root:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "similar_sites"))
```

Actually simpler: since `similar_sites/` is a package at the project root, Python will find it naturally when pytest runs from the project root. No conftest changes needed — pytest.ini already sets `testpaths = tests` and runs from the root.

**Step 5: Run tests**

```bash
pytest tests/test_similar_sites/test_scraper.py -v
```
Expected: all 3 tests PASS

**Step 6: Commit**

```bash
git add similar_sites/scraper.py tests/test_similar_sites/test_scraper.py
git commit -m "feat(similar-sites): add URL scraper with site profile extraction"
```

---

### Task 3: Analyzer (`similar_sites/analyzer.py`)

**Files:**
- Create: `similar_sites/analyzer.py`
- Create: `tests/test_similar_sites/test_analyzer.py`

**Step 1: Write the failing test**

Create `tests/test_similar_sites/test_analyzer.py`:
```python
"""Tests for similar-sites analyzer module."""
import pytest


def test_analyze_returns_keywords():
    """analyze_profile should extract top keywords via TF-IDF."""
    from similar_sites.analyzer import analyze_profile
    from similar_sites.scraper import SiteProfile

    profile = SiteProfile(
        url="https://example.com",
        domain="example.com",
        title="Python Machine Learning Blog",
        meta_description="A blog about Python and machine learning tutorials",
        meta_keywords=["python", "machine learning"],
        headings=["Python ML Tutorials", "Deep Learning Guide"],
        body_text="Python machine learning tutorials for developers. "
                  "Learn PyTorch TensorFlow deep learning neural networks. "
                  "Data science programming with Python frameworks. " * 10,
    )

    result = analyze_profile(profile)

    assert len(result.keywords) >= 5
    assert len(result.keywords) <= 15
    # Core terms should appear
    keyword_lower = [k.lower() for k in result.keywords]
    assert any("python" in k for k in keyword_lower)
    assert any("learning" in k or "machine" in k for k in keyword_lower)


def test_analyze_assigns_category():
    """analyze_profile should assign a category."""
    from similar_sites.analyzer import analyze_profile
    from similar_sites.scraper import SiteProfile

    profile = SiteProfile(
        url="https://shop.example.com",
        domain="shop.example.com",
        title="Best Online Shopping Deals",
        meta_description="Shop electronics, clothing, and more",
        headings=["Top Deals", "Categories", "Cart"],
        body_text="Buy products online. Shopping cart checkout. "
                  "Electronics deals clothing accessories price discount sale. " * 10,
    )

    result = analyze_profile(profile)

    assert result.category in [
        "tech", "news", "shopping", "blog", "saas", "education",
        "entertainment", "social", "reference", "other"
    ]


def test_analyze_detects_domain_type():
    """analyze_profile should detect the domain type."""
    from similar_sites.analyzer import analyze_profile, AnalysisResult
    from similar_sites.scraper import SiteProfile

    profile = SiteProfile(
        url="https://docs.example.com",
        domain="docs.example.com",
        title="API Documentation",
        meta_description="Developer documentation and API reference",
        headings=["Getting Started", "API Reference", "Examples"],
        body_text="Documentation guide API reference endpoint parameters. "
                  "Install configure setup developer guide tutorial. " * 10,
    )

    result = analyze_profile(profile)

    assert isinstance(result, AnalysisResult)
    assert result.domain_type in [
        "blog", "ecommerce", "docs", "forum", "news", "saas", "portfolio", "other"
    ]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_similar_sites/test_analyzer.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'similar_sites.analyzer'`

**Step 3: Write implementation**

Create `similar_sites/analyzer.py`:
```python
"""Analyze a scraped site profile to extract keywords, category, and domain type."""

from dataclasses import dataclass, field
from sklearn.feature_extraction.text import TfidfVectorizer

from .scraper import SiteProfile


@dataclass
class AnalysisResult:
    keywords: list[str] = field(default_factory=list)
    category: str = "other"
    domain_type: str = "other"


# Keyword sets for classification
CATEGORY_SIGNALS: dict[str, list[str]] = {
    "tech": ["software", "programming", "developer", "api", "code", "github", "framework", "python", "javascript"],
    "news": ["news", "breaking", "headline", "reporter", "journalism", "article", "press"],
    "shopping": ["shop", "buy", "cart", "price", "deal", "discount", "product", "store", "checkout", "sale"],
    "blog": ["blog", "post", "author", "comment", "published", "article", "opinion"],
    "saas": ["pricing", "signup", "dashboard", "plan", "subscribe", "trial", "platform", "solution"],
    "education": ["learn", "course", "tutorial", "lesson", "student", "teach", "education", "training"],
    "entertainment": ["video", "stream", "watch", "play", "game", "movie", "music", "entertainment"],
    "social": ["profile", "friend", "follow", "share", "community", "feed", "message"],
    "reference": ["wiki", "encyclopedia", "definition", "reference", "dictionary", "documentation"],
}

DOMAIN_TYPE_SIGNALS: dict[str, list[str]] = {
    "blog": ["blog", "post", "author", "published", "comment", "article"],
    "ecommerce": ["cart", "buy", "shop", "price", "checkout", "product", "order"],
    "docs": ["documentation", "api", "reference", "guide", "getting started", "install", "configure"],
    "forum": ["forum", "thread", "reply", "topic", "discussion", "member", "post"],
    "news": ["news", "headline", "reporter", "press", "breaking"],
    "saas": ["dashboard", "pricing", "signup", "trial", "plan", "features"],
    "portfolio": ["portfolio", "projects", "about me", "contact", "resume", "work"],
}


def analyze_profile(profile: SiteProfile) -> AnalysisResult:
    """Extract keywords, category, and domain type from a site profile."""
    # Combine text sources for analysis
    text_parts = [
        profile.title or "",
        profile.meta_description or "",
        " ".join(profile.meta_keywords),
        " ".join(profile.headings),
        profile.body_text or "",
    ]
    combined_text = " ".join(text_parts).strip()

    if not combined_text:
        return AnalysisResult()

    # Extract keywords via TF-IDF
    keywords = _extract_keywords(combined_text, max_keywords=15)

    # Classify category and domain type
    text_lower = combined_text.lower()
    category = _classify(text_lower, CATEGORY_SIGNALS)
    domain_type = _classify(text_lower, DOMAIN_TYPE_SIGNALS)

    return AnalysisResult(
        keywords=keywords,
        category=category,
        domain_type=domain_type,
    )


def _extract_keywords(text: str, max_keywords: int = 15) -> list[str]:
    """Extract top keywords using TF-IDF."""
    vectorizer = TfidfVectorizer(
        max_features=max_keywords,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
    )
    try:
        tfidf_matrix = vectorizer.fit_transform([text])
    except ValueError:
        return []

    feature_names = vectorizer.get_feature_names_out()
    scores = tfidf_matrix.toarray()[0]

    # Sort by score descending
    scored = sorted(zip(feature_names, scores), key=lambda x: x[1], reverse=True)
    return [word for word, score in scored if score > 0][:max_keywords]


def _classify(text: str, signal_map: dict[str, list[str]]) -> str:
    """Score text against signal word lists and return the best match."""
    best_label = "other"
    best_score = 0

    for label, signals in signal_map.items():
        score = sum(1 for s in signals if s in text)
        if score > best_score:
            best_score = score
            best_label = label

    return best_label
```

**Step 4: Run tests**

```bash
pytest tests/test_similar_sites/test_analyzer.py -v
```
Expected: all 3 tests PASS

**Step 5: Commit**

```bash
git add similar_sites/analyzer.py tests/test_similar_sites/test_analyzer.py
git commit -m "feat(similar-sites): add TF-IDF keyword analyzer with category classification"
```

---

### Task 4: Search Backend (`similar_sites/search.py`)

**Files:**
- Create: `similar_sites/search.py`
- Create: `tests/test_similar_sites/test_search.py`

**Step 1: Write the failing test**

Create `tests/test_similar_sites/test_search.py`:
```python
"""Tests for similar-sites search backend."""
import pytest
from unittest.mock import patch, MagicMock


def test_search_backend_interface():
    """SearchBackend must define a search method."""
    from similar_sites.search import SearchBackend

    # ABC check
    with pytest.raises(TypeError):
        SearchBackend()


def test_duckduckgo_backend_returns_results():
    """DuckDuckGoBackend.search should return SearchResult objects."""
    from similar_sites.search import DuckDuckGoBackend, SearchResult

    mock_results = [
        {"title": "Site A", "href": "https://site-a.com", "body": "Description of site A"},
        {"title": "Site B", "href": "https://site-b.com", "body": "Description of site B"},
    ]

    backend = DuckDuckGoBackend()

    with patch("similar_sites.search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = mock_results
        mock_ddgs_cls.return_value = mock_ddgs

        results = backend.search("python tutorials", num_results=5)

    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)
    assert results[0].title == "Site A"
    assert results[0].url == "https://site-a.com"


def test_build_queries_from_profile():
    """build_search_queries should generate diverse queries from a site profile."""
    from similar_sites.search import build_search_queries
    from similar_sites.scraper import SiteProfile
    from similar_sites.analyzer import AnalysisResult

    profile = SiteProfile(
        url="https://example.com",
        domain="example.com",
        title="Example Tech Blog",
    )
    analysis = AnalysisResult(
        keywords=["python", "machine learning", "tutorials"],
        category="tech",
    )

    queries = build_search_queries(profile, analysis)

    assert len(queries) >= 2
    assert len(queries) <= 4
    assert any("example" in q.lower() or "similar" in q.lower() or "like" in q.lower() for q in queries)


def test_search_deduplicates_and_excludes_input():
    """search_similar should deduplicate results and exclude the input URL."""
    from similar_sites.search import DuckDuckGoBackend, search_similar, SearchResult
    from similar_sites.scraper import SiteProfile
    from similar_sites.analyzer import AnalysisResult

    profile = SiteProfile(url="https://example.com", domain="example.com", title="Example")
    analysis = AnalysisResult(keywords=["test"], category="tech")

    mock_results = [
        {"title": "Example", "href": "https://example.com", "body": "The input site itself"},
        {"title": "Site A", "href": "https://site-a.com", "body": "Desc A"},
        {"title": "Site A Dupe", "href": "https://site-a.com/page", "body": "Desc A again"},
        {"title": "Site B", "href": "https://site-b.com", "body": "Desc B"},
    ]

    with patch("similar_sites.search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = mock_results
        mock_ddgs_cls.return_value = mock_ddgs

        results = search_similar(profile, analysis, DuckDuckGoBackend())

    urls = [r.url for r in results]
    # Input URL excluded
    assert "https://example.com" not in urls
    # Results present
    assert "https://site-a.com" in urls
    assert "https://site-b.com" in urls
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_similar_sites/test_search.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'similar_sites.search'`

**Step 3: Write implementation**

Create `similar_sites/search.py`:
```python
"""Search backends for finding similar sites."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

from duckduckgo_search import DDGS

from .scraper import SiteProfile
from .analyzer import AnalysisResult


@dataclass
class SearchResult:
    title: str
    url: str
    description: str


class SearchBackend(ABC):
    """Abstract interface for search backends."""

    @abstractmethod
    def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        pass


class DuckDuckGoBackend(SearchBackend):
    """DuckDuckGo search backend via duckduckgo-search library."""

    def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        with DDGS() as ddgs:
            raw = ddgs.text(query, max_results=num_results)

        results = []
        for item in raw:
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("href", ""),
                description=item.get("body", ""),
            ))
        return results


def build_search_queries(profile: SiteProfile, analysis: AnalysisResult) -> list[str]:
    """Generate search queries from a site profile and analysis."""
    queries = []

    # Query 1: "sites like {domain}"
    queries.append(f"sites like {profile.domain}")

    # Query 2: "alternatives to {title}"
    if profile.title:
        short_title = " ".join(profile.title.split()[:5])
        queries.append(f"alternatives to {short_title}")

    # Query 3: "{category} {top keywords} site"
    if analysis.keywords:
        top_kw = " ".join(analysis.keywords[:3])
        queries.append(f"{analysis.category} {top_kw} site")

    return queries


def search_similar(
    profile: SiteProfile,
    analysis: AnalysisResult,
    backend: SearchBackend,
    results_per_query: int = 10,
) -> list[SearchResult]:
    """Run search queries and return deduplicated results, excluding the input URL."""
    queries = build_search_queries(profile, analysis)
    input_domain = urlparse(profile.url).netloc

    all_results: list[SearchResult] = []
    seen_domains: set[str] = set()

    for query in queries:
        try:
            raw = backend.search(query, num_results=results_per_query)
        except Exception:
            continue

        for result in raw:
            result_domain = urlparse(result.url).netloc

            # Exclude input site
            if result_domain == input_domain:
                continue

            # Deduplicate by domain
            if result_domain in seen_domains:
                continue

            seen_domains.add(result_domain)
            all_results.append(result)

    return all_results
```

**Step 4: Run tests**

```bash
pytest tests/test_similar_sites/test_search.py -v
```
Expected: all 4 tests PASS

**Step 5: Commit**

```bash
git add similar_sites/search.py tests/test_similar_sites/test_search.py
git commit -m "feat(similar-sites): add search backend with DuckDuckGo and query builder"
```

---

### Task 5: Scorer & Grouper (`similar_sites/scorer.py`)

**Files:**
- Create: `similar_sites/scorer.py`
- Create: `tests/test_similar_sites/test_scorer.py`

**Step 1: Write the failing test**

Create `tests/test_similar_sites/test_scorer.py`:
```python
"""Tests for similar-sites scorer and grouper."""
import pytest


def test_score_result_returns_score_and_reason():
    """score_result should return a 0-100 score and a reason string."""
    from similar_sites.scorer import score_result
    from similar_sites.search import SearchResult
    from similar_sites.analyzer import AnalysisResult

    analysis = AnalysisResult(
        keywords=["python", "machine learning", "tutorials", "deep learning"],
        category="tech",
    )
    result = SearchResult(
        title="Python ML Tutorial Site",
        url="https://ml-tutorials.com",
        description="Learn Python machine learning with hands-on tutorials and deep learning examples",
    )

    score, reason = score_result(result, analysis)

    assert 0 <= score <= 100
    assert isinstance(reason, str)
    assert len(reason) > 0
    # High overlap should give decent score
    assert score >= 30


def test_score_unrelated_result_is_low():
    """An unrelated result should score low."""
    from similar_sites.scorer import score_result
    from similar_sites.search import SearchResult
    from similar_sites.analyzer import AnalysisResult

    analysis = AnalysisResult(
        keywords=["python", "machine learning", "tutorials"],
        category="tech",
    )
    result = SearchResult(
        title="Best Pizza Restaurants NYC",
        url="https://pizza-nyc.com",
        description="Find the best pizza places in New York City with reviews and ratings",
    )

    score, reason = score_result(result, analysis)

    assert score < 30


def test_group_results():
    """group_results should organize scored results into labeled groups."""
    from similar_sites.scorer import group_results, ScoredResult

    scored = [
        ScoredResult(title="Competitor A", url="https://a.com", description="desc", score=90, reason="High overlap", group="Competitors"),
        ScoredResult(title="Niche B", url="https://b.com", description="desc", score=70, reason="Same niche", group="Same Niche"),
        ScoredResult(title="Related C", url="https://c.com", description="desc", score=40, reason="Some overlap", group="Related Content"),
        ScoredResult(title="Competitor D", url="https://d.com", description="desc", score=85, reason="High overlap", group="Competitors"),
    ]

    groups = group_results(scored)

    assert isinstance(groups, list)
    labels = [g["label"] for g in groups]
    assert "Competitors" in labels

    # Competitors group should have 2 items, sorted by score desc
    comp_group = next(g for g in groups if g["label"] == "Competitors")
    assert len(comp_group["sites"]) == 2
    assert comp_group["sites"][0]["score"] >= comp_group["sites"][1]["score"]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_similar_sites/test_scorer.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'similar_sites.scorer'`

**Step 3: Write implementation**

Create `similar_sites/scorer.py`:
```python
"""Score search results for similarity and group them."""

from dataclasses import dataclass
from .search import SearchResult
from .analyzer import AnalysisResult


@dataclass
class ScoredResult:
    title: str
    url: str
    description: str
    score: int
    reason: str
    group: str


def score_result(result: SearchResult, analysis: AnalysisResult) -> tuple[int, str]:
    """Score a search result against the analysis. Returns (score 0-100, reason)."""
    result_text = f"{result.title} {result.description}".lower()
    reasons = []
    score = 0

    # Keyword overlap scoring (up to 60 points)
    if analysis.keywords:
        matched = [kw for kw in analysis.keywords if kw.lower() in result_text]
        overlap_ratio = len(matched) / len(analysis.keywords)
        keyword_score = int(overlap_ratio * 60)
        score += keyword_score
        if matched:
            reasons.append(f"Matching keywords: {', '.join(matched[:3])}")

    # Category signal scoring (up to 25 points)
    from .analyzer import CATEGORY_SIGNALS
    if analysis.category in CATEGORY_SIGNALS:
        cat_signals = CATEGORY_SIGNALS[analysis.category]
        cat_matches = sum(1 for s in cat_signals if s in result_text)
        cat_score = min(25, cat_matches * 5)
        score += cat_score
        if cat_matches > 0:
            reasons.append(f"Same category: {analysis.category}")

    # Title similarity bonus (up to 15 points)
    if analysis.keywords:
        title_lower = result.title.lower()
        title_matches = sum(1 for kw in analysis.keywords[:5] if kw.lower() in title_lower)
        title_score = min(15, title_matches * 5)
        score += title_score

    score = min(100, score)
    reason = "; ".join(reasons) if reasons else "Weak match"
    return score, reason


def classify_group(score: int, analysis: AnalysisResult, result: SearchResult) -> str:
    """Assign a result to a group based on its score."""
    if score >= 70:
        return "Competitors"
    elif score >= 45:
        return "Same Niche"
    elif score >= 25:
        return "Related Content"
    else:
        return "Similar Tech/Tools"


def score_and_group(
    results: list[SearchResult],
    analysis: AnalysisResult,
    max_results: int = 20,
) -> list[ScoredResult]:
    """Score all results and assign groups."""
    scored = []
    for result in results:
        score, reason = score_result(result, analysis)
        group = classify_group(score, analysis, result)
        scored.append(ScoredResult(
            title=result.title,
            url=result.url,
            description=result.description,
            score=score,
            reason=reason,
            group=group,
        ))

    # Sort by score descending, limit
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:max_results]


def group_results(scored: list[ScoredResult]) -> list[dict]:
    """Organize scored results into labeled groups."""
    group_order = ["Competitors", "Same Niche", "Related Content", "Similar Tech/Tools"]
    groups_map: dict[str, list[dict]] = {}

    for r in scored:
        if r.group not in groups_map:
            groups_map[r.group] = []
        groups_map[r.group].append({
            "url": r.url,
            "title": r.title,
            "description": r.description,
            "score": r.score,
            "reason": r.reason,
        })

    # Sort within groups by score descending
    for sites in groups_map.values():
        sites.sort(key=lambda s: s["score"], reverse=True)

    # Return in defined order, skip empty groups
    return [
        {"label": label, "sites": groups_map[label]}
        for label in group_order
        if label in groups_map
    ]
```

**Step 4: Run tests**

```bash
pytest tests/test_similar_sites/test_scorer.py -v
```
Expected: all 3 tests PASS

**Step 5: Commit**

```bash
git add similar_sites/scorer.py tests/test_similar_sites/test_scorer.py
git commit -m "feat(similar-sites): add similarity scorer and result grouper"
```

---

### Task 6: FastAPI App (`similar_sites/app.py`)

**Files:**
- Create: `similar_sites/app.py`
- Create: `tests/test_similar_sites/test_app.py`

**Step 1: Write the failing test**

Create `tests/test_similar_sites/test_app.py`:
```python
"""Tests for similar-sites FastAPI app."""
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app():
    from similar_sites.app import app
    return app


@pytest.mark.asyncio
async def test_root_serves_html(app):
    """GET / should return HTML page."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Similar Sites" in response.text


@pytest.mark.asyncio
async def test_find_similar_requires_url(app):
    """POST /api/find-similar without url should return 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/find-similar", json={})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_find_similar_returns_grouped_results(app):
    """POST /api/find-similar should return grouped results."""
    from similar_sites.scraper import SiteProfile
    from similar_sites.analyzer import AnalysisResult
    from similar_sites.search import SearchResult

    mock_profile = SiteProfile(
        url="https://example.com",
        domain="example.com",
        title="Example Site",
        meta_description="An example",
        body_text="example content",
    )
    mock_analysis = AnalysisResult(
        keywords=["example", "content"],
        category="tech",
        domain_type="blog",
    )
    mock_search_results = [
        SearchResult(title="Similar A", url="https://a.com", description="Desc A"),
    ]

    with patch("similar_sites.app.scrape_url", new_callable=AsyncMock, return_value=mock_profile), \
         patch("similar_sites.app.analyze_profile", return_value=mock_analysis), \
         patch("similar_sites.app.search_similar", return_value=mock_search_results), \
         patch("similar_sites.app.score_and_group") as mock_score, \
         patch("similar_sites.app.group_results") as mock_group:

        from similar_sites.scorer import ScoredResult
        mock_score.return_value = [ScoredResult(
            title="Similar A", url="https://a.com", description="Desc A",
            score=75, reason="High overlap", group="Competitors",
        )]
        mock_group.return_value = [{"label": "Competitors", "sites": [
            {"url": "https://a.com", "title": "Similar A", "description": "Desc A", "score": 75, "reason": "High overlap"}
        ]}]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/find-similar", json={"url": "https://example.com"})

    assert response.status_code == 200
    data = response.json()
    assert "input" in data
    assert "groups" in data
    assert data["input"]["url"] == "https://example.com"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_similar_sites/test_app.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'similar_sites.app'`

**Step 3: Write implementation**

Create `similar_sites/app.py`:
```python
"""FastAPI application for Similar Sites Finder."""

import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl

from .scraper import scrape_url, ScrapeError
from .analyzer import analyze_profile
from .search import search_similar, DuckDuckGoBackend
from .scorer import score_and_group, group_results

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="Similar Sites Finder",
    description="Find websites similar to a given URL",
    version="1.0.0",
)

# Static files and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


class FindSimilarRequest(BaseModel):
    url: HttpUrl


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the web UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/find-similar")
async def find_similar(body: FindSimilarRequest):
    """Find sites similar to the given URL."""
    url = str(body.url)

    # Step 1: Scrape
    try:
        profile = await scrape_url(url)
    except ScrapeError as e:
        return {"error": str(e)}, 400

    # Step 2: Analyze
    analysis = analyze_profile(profile)

    # Step 3: Search
    backend = DuckDuckGoBackend()
    search_results = search_similar(profile, analysis, backend)

    # Step 4: Score and group
    scored = score_and_group(search_results, analysis)
    groups = group_results(scored)

    return {
        "input": {
            "url": url,
            "title": profile.title,
            "category": analysis.category,
            "domain_type": analysis.domain_type,
            "keywords": analysis.keywords[:5],
        },
        "groups": groups,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SIMILAR_SITES_PORT", "8001"))
    uvicorn.run("similar_sites.app:app", host="0.0.0.0", port=port, reload=True)
```

**Step 4: Create template and static dirs (empty placeholders for now)**

```bash
mkdir -p similar_sites/templates similar_sites/static
touch similar_sites/templates/.gitkeep similar_sites/static/.gitkeep
```

Create minimal `similar_sites/templates/index.html` so the test passes:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Similar Sites Finder</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div id="app">
        <h1>Similar Sites Finder</h1>
        <p>Enter a URL to find similar websites.</p>
    </div>
    <script src="/static/app.js"></script>
</body>
</html>
```

Create empty `similar_sites/static/style.css` and `similar_sites/static/app.js`.

**Step 5: Run tests**

```bash
pytest tests/test_similar_sites/test_app.py -v
```
Expected: all 3 tests PASS

**Step 6: Commit**

```bash
git add similar_sites/app.py similar_sites/templates/ similar_sites/static/ tests/test_similar_sites/test_app.py
git commit -m "feat(similar-sites): add FastAPI app with find-similar endpoint and template"
```

---

### Task 7: Web UI — HTML, CSS, JS

**Files:**
- Modify: `similar_sites/templates/index.html`
- Create: `similar_sites/static/style.css`
- Create: `similar_sites/static/app.js`

**Step 1: Write the full HTML template**

Replace `similar_sites/templates/index.html` with the full single-page UI. It should include:
- Dark background (#1a1a2e or similar)
- URL input form with cyan-accented submit button
- Results area with grouped cards
- Loading spinner with status messages
- Score badges on each result card
- Collapsible group headers with count
- Responsive layout

Color palette (from CLI theme):
- Primary: `#00e5ff` (bright cyan)
- Secondary: `#ff4081` (bright magenta)
- Accent: `#448aff` (bright blue)
- Background: `#0d1117`
- Card background: `#161b22`
- Text: `#e6edf3`

**Step 2: Write `style.css`** with the full stylesheet matching above palette.

**Step 3: Write `app.js`** with:
- Form submit handler (POST to `/api/find-similar`)
- Loading state management (show spinner, update status text)
- Result rendering (create DOM elements for grouped cards)
- Collapsible group toggle
- Error handling (display error messages)

**Step 4: Manual test** — run the app and verify the UI loads:

```bash
cd similar_sites && python -m similar_sites.app
```

Open http://localhost:8001 in browser, verify the page loads with the input form.

**Step 5: Commit**

```bash
git add similar_sites/templates/ similar_sites/static/
git commit -m "feat(similar-sites): add web UI with dark theme and grouped results display"
```

---

### Task 8: CLI (`similar_sites/cli.py`)

**Files:**
- Create: `similar_sites/cli.py`
- Create: `tests/test_similar_sites/test_cli.py`

**Step 1: Write the failing test**

Create `tests/test_similar_sites/test_cli.py`:
```python
"""Tests for similar-sites CLI."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def test_cli_requires_url(capsys):
    """CLI should fail with error if no URL provided."""
    from similar_sites.cli import main
    import sys

    with pytest.raises(SystemExit) as exc_info:
        with patch("sys.argv", ["cli.py"]):
            main()

    assert exc_info.value.code != 0
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_similar_sites/test_cli.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'similar_sites.cli'`

**Step 3: Write implementation**

Create `similar_sites/cli.py`:
```python
#!/usr/bin/env python3
"""CLI for Similar Sites Finder."""

import argparse
import asyncio
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .scraper import scrape_url, ScrapeError
from .analyzer import analyze_profile
from .search import search_similar, DuckDuckGoBackend
from .scorer import score_and_group, group_results

console = Console()


async def find_similar(url: str) -> dict:
    """Run the full pipeline and return results dict."""
    console.print(f"\n[dim]Scraping[/dim] [bright_cyan]{url}[/bright_cyan]...")
    profile = await scrape_url(url)

    console.print(f"[dim]Analyzing content...[/dim]")
    analysis = analyze_profile(profile)

    console.print(f"[dim]Searching for similar sites...[/dim]")
    backend = DuckDuckGoBackend()
    search_results = search_similar(profile, analysis, backend)

    console.print(f"[dim]Scoring {len(search_results)} results...[/dim]")
    scored = score_and_group(search_results, analysis)
    groups = group_results(scored)

    return {
        "input": {
            "url": url,
            "title": profile.title,
            "category": analysis.category,
            "keywords": analysis.keywords[:5],
        },
        "groups": groups,
    }


def display_results(data: dict):
    """Render results using Rich."""
    inp = data["input"]
    console.print(Panel.fit(
        f"[bold bright_cyan]{inp['title']}[/bold bright_cyan]\n"
        f"[dim]URL:[/dim] {inp['url']}\n"
        f"[dim]Category:[/dim] [bright_white]{inp['category']}[/bright_white]\n"
        f"[dim]Keywords:[/dim] {', '.join(inp['keywords'])}",
        title="[bold bright_blue]Input Site[/bold bright_blue]",
        border_style="bright_blue",
    ))

    if not data["groups"]:
        console.print("\n[bright_yellow]No similar sites found.[/bright_yellow]")
        return

    for group in data["groups"]:
        table = Table(title=f"[bold bright_magenta]{group['label']}[/bold bright_magenta] ({len(group['sites'])})")
        table.add_column("Score", style="bright_cyan", width=6, justify="right")
        table.add_column("Site", style="bright_white")
        table.add_column("Why", style="dim")

        for site in group["sites"]:
            table.add_row(
                str(site["score"]),
                f"[link={site['url']}]{site['title']}[/link]\n[dim]{site['url']}[/dim]",
                site["reason"],
            )

        console.print(table)
        console.print()


def main():
    parser = argparse.ArgumentParser(description="Find similar websites")
    parser.add_argument("url", help="URL to find similar sites for")
    args = parser.parse_args()

    try:
        data = asyncio.run(find_similar(args.url))
        display_results(data)
    except ScrapeError as e:
        console.print(f"[bright_red]Error:[/bright_red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bright_red]Error:[/bright_red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tests/test_similar_sites/test_cli.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add similar_sites/cli.py tests/test_similar_sites/test_cli.py
git commit -m "feat(similar-sites): add Rich CLI for similar site discovery"
```

---

### Task 9: Integration Test

**Files:**
- Create: `tests/test_similar_sites/test_integration.py`

**Step 1: Write integration test**

Create `tests/test_similar_sites/test_integration.py`:
```python
"""Integration test — full pipeline with mocked HTTP."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


MOCK_HTML = """
<html><head>
<title>FastAPI Framework</title>
<meta name="description" content="FastAPI is a modern Python web framework">
<meta name="keywords" content="python, fastapi, web framework, api">
</head><body>
<h1>FastAPI</h1>
<p>Build APIs quickly with Python type hints. High performance async framework
for building REST APIs. Automatic OpenAPI docs. Production ready.</p>
<a href="https://flask.palletsprojects.com">Flask</a>
<a href="https://djangoproject.com">Django</a>
</body></html>
"""


@pytest.mark.asyncio
async def test_full_pipeline():
    """End-to-end: scrape → analyze → search → score → group."""
    from similar_sites.scraper import scrape_url
    from similar_sites.analyzer import analyze_profile
    from similar_sites.search import search_similar, DuckDuckGoBackend, SearchResult
    from similar_sites.scorer import score_and_group, group_results

    # Mock the HTTP call for scraping
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = MOCK_HTML
    mock_response.raise_for_status = lambda: None

    with patch("similar_sites.scraper.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        profile = await scrape_url("https://fastapi.tiangolo.com")

    assert profile.title == "FastAPI Framework"

    analysis = analyze_profile(profile)
    assert len(analysis.keywords) > 0
    assert analysis.category in ["tech", "reference", "other", "education", "blog"]

    # Mock search results
    mock_search = [
        {"title": "Flask Web Framework", "href": "https://flask.palletsprojects.com", "body": "Python micro web framework"},
        {"title": "Django Project", "href": "https://djangoproject.com", "body": "Python web framework for perfectionists"},
        {"title": "Express.js", "href": "https://expressjs.com", "body": "Node.js web application framework"},
        {"title": "Best Pizza NYC", "href": "https://pizza.com", "body": "Order pizza delivery online"},
    ]

    with patch("similar_sites.search.DDGS") as mock_ddgs_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = mock_search
        mock_ddgs_cls.return_value = mock_ddgs

        search_results = search_similar(profile, analysis, DuckDuckGoBackend())

    assert len(search_results) >= 2

    scored = score_and_group(search_results, analysis)
    groups = group_results(scored)

    assert isinstance(groups, list)
    assert len(groups) > 0

    # Flask/Django should score higher than pizza
    all_sites = [s for g in groups for s in g["sites"]]
    urls = [s["url"] for s in all_sites]
    if "https://pizza.com" in urls and "https://flask.palletsprojects.com" in urls:
        flask_score = next(s["score"] for s in all_sites if "flask" in s["url"])
        pizza_score = next(s["score"] for s in all_sites if "pizza" in s["url"])
        assert flask_score > pizza_score
```

**Step 2: Run all tests**

```bash
pytest tests/test_similar_sites/ -v
```
Expected: all tests PASS

**Step 3: Commit**

```bash
git add tests/test_similar_sites/test_integration.py
git commit -m "test(similar-sites): add integration test for full pipeline"
```

---

### Task 10: Launch Config & Final Wiring

**Files:**
- Modify: `.claude/launch.json` — add similar-sites server
- Modify: `similar_sites/__init__.py` — add version

**Step 1: Update launch.json**

Add a second configuration for the similar-sites server:
```json
{
    "name": "similar-sites",
    "runtimeExecutable": "/Users/henry/Github/Github_desktop/local-ai-platform/venv/bin/uvicorn",
    "runtimeArgs": ["similar_sites.app:app", "--host", "0.0.0.0", "--port", "8001", "--reload"],
    "port": 8001
}
```

**Step 2: Add version to `__init__.py`**

```python
"""Similar Sites Finder — find websites similar to a given URL."""
__version__ = "0.1.0"
```

**Step 3: Run full test suite**

```bash
pytest tests/test_similar_sites/ -v
```
Expected: all tests PASS

**Step 4: Manual verification**

Start the server and verify it loads:
```bash
python -m similar_sites.app
```

**Step 5: Commit**

```bash
git add .claude/launch.json similar_sites/__init__.py
git commit -m "feat(similar-sites): add launch config and finalize module"
```

---

### Summary

| Task | Component | Tests |
|------|-----------|-------|
| 1 | Scaffold + deps | — |
| 2 | Scraper | 3 tests |
| 3 | Analyzer | 3 tests |
| 4 | Search backend | 4 tests |
| 5 | Scorer/Grouper | 3 tests |
| 6 | FastAPI app | 3 tests |
| 7 | Web UI (HTML/CSS/JS) | manual |
| 8 | CLI | 1 test |
| 9 | Integration test | 1 test |
| 10 | Launch config + wiring | — |

**Total: 10 tasks, 18 tests, ~10 commits**
