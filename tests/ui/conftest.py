"""Shared fixtures for static-markup UI regression tests."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

STATIC_DIR = Path(__file__).resolve().parents[2] / "api" / "static"


@pytest.fixture(scope="session")
def index_html_text() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def setup_html_text() -> str:
    return (STATIC_DIR / "setup.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def index_soup(index_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(index_html_text, "html.parser")


@pytest.fixture(scope="session")
def setup_soup(setup_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(setup_html_text, "html.parser")
