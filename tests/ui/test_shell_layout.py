#!/usr/bin/env python3
"""Guard the left-rail sidebar layout contract.

The persistent left-rail nav + internal main-scroll are a pure-CSS grid on
<body>, which ONLY works because `.tab-nav`, `#main-content`, and `.footer`
are DIRECT children of <body> (the `body > .tab-nav { grid-area: nav }` rules
match nothing otherwise). A structural edit once left `<div class="shell">`
open around the whole app, nesting those elements inside `.shell` — the grid
silently broke, taking the sidebar and the page scroll with it. This test
pins the contract so that regression can never land un-caught again.
"""

from pathlib import Path

from bs4 import BeautifulSoup

INDEX = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


def _soup():
    return BeautifulSoup(INDEX.read_text(encoding="utf-8"), "html.parser")


def test_rail_layout_children_are_direct_body_children():
    body = _soup().body
    direct = [c for c in body.find_all(recursive=False)]

    def _is_body_child(selector_fn, label):
        assert any(selector_fn(c) for c in direct), (
            f"{label} must be a DIRECT child of <body> for the left-rail grid "
            f"(body > … grid-area) to apply — found it nested instead."
        )

    _is_body_child(lambda c: "tab-nav" in (c.get("class") or []), ".tab-nav")
    _is_body_child(lambda c: c.get("id") == "main-content", "#main-content")
    _is_body_child(lambda c: "footer" in (c.get("class") or []), ".footer")


def test_shell_wraps_only_the_header():
    """`.shell` is the header region (grid-area: shell); it must NOT wrap the
    nav/main/footer — if it does, they stop being body children."""
    shell = _soup().find("div", class_="shell")
    assert shell is not None, ".shell wrapper missing (grid targets body > .shell)"
    assert shell.find("div", class_="tab-nav") is None, ".shell must not contain .tab-nav"
    assert shell.find(id="main-content") is None, ".shell must not contain #main-content"
    assert shell.find("div", class_="footer") is None, ".shell must not contain .footer"
