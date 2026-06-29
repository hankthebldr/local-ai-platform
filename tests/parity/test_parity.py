"""Parity gate for the index.html → ES-module split (no feature loss).

Pure-Python, runs in the normal pytest suite (no browser). It enforces the
inline-handler bridge contract across the refactor:

  - PRE-split:  every inline on*= handler symbol is defined in the monolith
                (window.X= assignment, or a top-level const/let/function).
  - POST-split: the same symbols must be re-exposed on window by the legacy
                bridge — the test scans the served JS corpus (index.html +
                js/**/*.js), so it tightens automatically once modules exist.

The runtime superset check (Object.keys(window) ⊇ golden) and zero-console
boot live in the Playwright parity test added with Stage 1; this file is the
cheap, always-on regression guard. Regenerate goldens with:

    python scripts/capture_parity_goldens.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
INDEX = REPO / "api" / "static" / "index.html"
GOLDEN = REPO / "tests" / "parity" / "golden" / "inline_handlers.json"
JS_DIR = REPO / "api" / "static" / "js"


def _load_capture_module():
    """Import scripts/capture_parity_goldens.py without a package install."""
    path = REPO / "scripts" / "capture_parity_goldens.py"
    spec = importlib.util.spec_from_file_location("capture_parity_goldens", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cap():
    return _load_capture_module()


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def golden() -> dict:
    assert GOLDEN.exists(), (
        "Parity golden missing. Capture it from the PRE-split app first: "
        "python scripts/capture_parity_goldens.py"
    )
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _served_js_corpus(html: str) -> str:
    """All JS the browser executes: the monolith + any extracted modules."""
    corpus = [html]
    if JS_DIR.is_dir():
        for js in sorted(JS_DIR.rglob("*.js")):
            corpus.append(js.read_text(encoding="utf-8"))
    return "\n".join(corpus)


def test_no_handler_drift(cap, html, golden):
    """The set of inline-handler symbols must match the committed golden.

    Catches an accidentally-added handler referencing a new symbol (which would
    need bridging) or a silently-dropped handler. Intentional changes: rerun the
    capture script and commit the new golden.
    """
    current = cap.capture_inline_handlers(html)
    assert current["symbols"] == golden["symbols"], (
        "Inline-handler symbol set drifted from golden.\n"
        f"  added:   {sorted(set(current['symbols']) - set(golden['symbols']))}\n"
        f"  removed: {sorted(set(golden['symbols']) - set(current['symbols']))}\n"
        "If intentional: python scripts/capture_parity_goldens.py"
    )


def test_every_handler_symbol_is_reachable(cap, html):
    """No inline handler may reference an undefined symbol (pre or post split).

    Classifies against the FULL served JS corpus, so after the split a symbol
    re-exposed via window.X= in legacy-bridge.js still counts as reachable.
    """
    corpus = _served_js_corpus(html)
    current = cap.capture_inline_handlers(html)
    unreachable = [
        s for s in current["symbols"] if cap._classify(corpus, s) == "unknown"
    ]
    assert not unreachable, (
        "Inline handlers reference symbols not defined anywhere in the served JS "
        f"(broken/dropped during extraction): {unreachable}"
    )


@pytest.mark.skipif(
    not JS_DIR.is_dir(), reason="pre-split: js/ modules not created yet"
)
def test_post_split_symbols_are_window_bridged(cap, html, golden):
    """Once modules exist, EVERY handler symbol must be window-bridged.

    Module top-level const/let/function are not global; inline handlers can only
    reach window properties. So post-split each symbol needs `window.X =` in the
    served corpus (legacy-bridge.js). This assertion is inert pre-split and
    becomes the hard gate the moment js/ appears.
    """
    corpus = _served_js_corpus(html)
    not_bridged = [s for s in golden["symbols"] if cap._classify(corpus, s) != "window"]
    assert not not_bridged, (
        "Post-split, these inline-handler symbols are NOT exposed on window via the "
        f"legacy bridge — their handlers will silently no-op: {not_bridged}"
    )


def test_golden_is_self_consistent(golden):
    """Sanity: the committed golden has no unknown symbols and a non-empty bridge list."""
    assert golden["unknown"] == [], f"golden has unknown symbols: {golden['unknown']}"
    assert golden[
        "must_bridge"
    ], "expected a non-empty must_bridge checklist for Stage 1"
