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


@pytest.fixture(scope="session")
def index_html_text() -> str:
    return _inline_local_css((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def setup_html_text() -> str:
    return (STATIC_DIR / "setup.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def index_soup(index_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(index_html_text, "html.parser")


@pytest.fixture(scope="session")
def setup_soup(setup_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(setup_html_text, "html.parser")
