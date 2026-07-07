"""Shared fixtures for static-markup UI regression tests."""

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

STATIC_DIR = Path(__file__).resolve().parents[2] / "api" / "static"


def _inline_local_css(html: str) -> str:
    """Resolve any `<link rel=stylesheet href=/static/css/*.css>` back inline.

    Phase-1 moved the main stylesheet out of index.html into css/app.css. The
    browser resolves that link into the same cascade, so for static assertions
    the effective served document is index.html WITH the linked CSS spliced in.
    Modeling that here keeps every CSS-rule test (`:root {}`, `@media`, token
    checks) working unchanged, while element/DOM assertions are unaffected (a
    <link> vs an equivalent <style> in <head> doesn't change the body DOM).
    Real-browser visual parity is proved separately by the phase-1 screenshot
    diff. Vendor CSS (fonts, drawflow) is left as a link — not our surface.
    """

    def _repl(m: re.Match) -> str:
        tag = m.group(0)
        href = re.search(r'href="([^"]+)"', tag)
        if not href or not href.group(1).startswith("/static/css/"):
            return tag
        css = STATIC_DIR / href.group(1).lstrip("/").replace("static/", "", 1)
        if not css.exists():
            return tag
        return "<style>\n" + css.read_text(encoding="utf-8") + "</style>"

    return re.sub(r"<link\b[^>]*>", _repl, html)


def _served_js_corpus() -> str:
    """Concatenation of every served ES module under /static/js.

    Phase-2 moved the inline monolith `<script>` out into `js/**`. Static tests
    that assert JS *behaviour* (a module string, an API path, a `window.X =`
    bridge) were written against the pre-split inline code, so the effective
    document they should scan is index.html + the served JS. We append that JS
    wrapped in a single <script> so (a) regex/`in` assertions resolve, (b)
    `test_static_markup`'s `<script>…</script>` strip removes it cleanly, and
    (c) BeautifulSoup treats it as script text, never as DOM elements. As
    phase-2 carves main.js into per-domain modules, rglob keeps this complete.
    """
    js_dir = STATIC_DIR / "js"
    if not js_dir.is_dir():
        return ""
    parts = [js.read_text(encoding="utf-8") for js in sorted(js_dir.rglob("*.js"))]
    return "\n".join(parts)


def _effective_index() -> str:
    """index.html with local CSS inlined — the DOM/markup surface (no JS)."""
    return _inline_local_css((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def index_html_text() -> str:
    html = _effective_index()
    js = _served_js_corpus()
    if js:
        html += "\n<script>\n" + js + "\n</script>\n"
    return html


@pytest.fixture(scope="session")
def setup_html_text() -> str:
    return (STATIC_DIR / "setup.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def index_soup() -> BeautifulSoup:
    # DOM-only: parse the CSS-inlined HTML WITHOUT the appended JS corpus, so
    # module code (which contains HTML strings in template literals) can never
    # leak spurious elements into the parsed tree.
    return BeautifulSoup(_effective_index(), "html.parser")


@pytest.fixture(scope="session")
def setup_soup(setup_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(setup_html_text, "html.parser")
