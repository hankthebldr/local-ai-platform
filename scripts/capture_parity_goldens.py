#!/usr/bin/env python3
"""Capture parity goldens for the index.html ES-module split.

The no-feature-loss safety net (see
docs/superpowers/specs/2026-06-28-composer-dominant-workspace-design.md).
Run this against the CURRENT (pre-split) index.html and commit the goldens.
After the split, tests/parity/test_parity.py asserts nothing was dropped.

Captures (static, browser-free):
  - golden/inline_handlers.json : every on*= handler in static markup + the
    leading symbol it invokes. Post-split that symbol MUST still be reachable
    as a window global (via the legacy-bridge) or the handler silently breaks.

The runtime window-globals golden (golden/window_globals.json) is captured
separately from a live browser (Object.keys(window) minus an about:blank
baseline) because bare `function foo(){}` in the classic monolith is only
observable at runtime, not by static parse.

Usage:
  python scripts/capture_parity_goldens.py            # write goldens
  python scripts/capture_parity_goldens.py --check     # print, don't write
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "api" / "static" / "index.html"
GOLDEN_DIR = REPO / "tests" / "parity" / "golden"

# The inline-handler surface is the STATIC markup — everything outside the
# <script> and <style> blocks. Handlers in JS template strings don't count
# (the app uses data-action delegation there), so we strip script/style blocks
# entirely, then scan the remaining markup.
_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
# on<event>="<expr>"  — capture event + the leading identifier of the handler.
# Restrict <event> to real DOM events so we don't match e.g. content="width=...".
_HANDLER = re.compile(
    r"""\bon(click|change|input|submit|keydown|keyup|keypress|focus|blur|"""
    r"""mousedown|mouseup|mouseover|mouseout|mouseenter|mouseleave|"""
    r"""dblclick|contextmenu|wheel|scroll|load|error|drop|dragover|dragstart|"""
    r"""paste|toggle)\s*=\s*["']\s*([A-Za-z_$][\w$]*)""",
    re.IGNORECASE,
)


# JS builtins / keywords that can lead a handler expression (e.g.
# onchange="this.value", onclick="if(x)..."). These are always available and
# are NOT part of the app's bridge contract.
_BUILTINS = {
    "this", "if", "window", "document", "navigator", "event", "return",
    "void", "true", "false", "null", "undefined", "console", "location",
    "history", "localStorage", "sessionStorage", "alert", "confirm",
    "setTimeout", "setInterval", "JSON", "Math", "Object", "Array", "Date",
    "for", "while", "var", "let", "const", "function", "new", "delete",
    "typeof", "parseInt", "parseFloat",
}


def _static_region(html: str) -> str:
    """Markup with <script>/<style> blocks removed — the static handler surface."""
    return _BLOCK.sub("", html)


def _classify(html: str, symbol: str) -> str:
    """How is `symbol` reachable in the pre-split monolith?

    window  : `window.SYM =` assignment — already bridged, survives the split.
    lexical : top-level `const/let/var/function SYM` only — reachable by inline
              handlers TODAY (classic-script global lexical binding) but will
              break under ES modules unless explicitly window-bridged. This is
              the must-bridge checklist for Stage 1.
    unknown : neither — investigate (could be an alias or a parse miss).
    """
    if re.search(rf"\bwindow\.{re.escape(symbol)}\s*=", html):
        return "window"
    if re.search(rf"\b(?:const|let|var|function)\s+{re.escape(symbol)}\b", html):
        return "lexical"
    return "unknown"


def capture_inline_handlers(html: str) -> dict:
    region = _static_region(html)
    handlers: dict[str, list[str]] = {}
    for event, symbol in _HANDLER.findall(region):
        if symbol in _BUILTINS:
            continue
        handlers.setdefault(symbol, []).append(event.lower())
    symbols = sorted(handlers)
    classification = {s: _classify(html, s) for s in symbols}
    must_bridge = sorted(s for s, c in classification.items() if c == "lexical")
    unknown = sorted(s for s, c in classification.items() if c == "unknown")
    return {
        "_meta": {
            "source": "static markup of api/static/index.html (<script>/<style> stripped)",
            "purpose": (
                "Every symbol here is invoked by an inline on*= handler. After the "
                "ES-module split each MUST be reachable as a window global "
                "(legacy-bridge.js), or the handler silently no-ops. 'must_bridge' "
                "lists symbols reachable today ONLY via a classic-script global "
                "lexical const/let/function — these break under modules unless "
                "explicitly assigned to window."
            ),
            "handler_count": sum(len(v) for v in handlers.values()),
            "symbol_count": len(symbols),
            "must_bridge_count": len(must_bridge),
            "unknown_count": len(unknown),
        },
        "symbols": symbols,
        "classification": classification,
        "must_bridge": must_bridge,
        "unknown": unknown,
        "by_symbol": {k: sorted(set(v)) for k, v in sorted(handlers.items())},
    }


def main() -> int:
    check = "--check" in sys.argv
    html = INDEX.read_text(encoding="utf-8")
    inline = capture_inline_handlers(html)
    print(
        f"inline handlers: {inline['_meta']['handler_count']} attrs → "
        f"{inline['_meta']['symbol_count']} distinct symbols"
    )
    if check:
        print(json.dumps(inline, indent=2))
        return 0
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    out = GOLDEN_DIR / "inline_handlers.json"
    out.write_text(json.dumps(inline, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
