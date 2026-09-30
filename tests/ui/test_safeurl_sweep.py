"""Theme B — the `safeUrl()` sweep is COMPLETE, and stays complete.

`a0e9243` (GP-2 commit 6) added `escAttr()`/`safeUrl()` and fixed the sinks in
`main.js`, but three modules still interpolated an EXTERNAL-catalog URL into an
`href` via `esc()`: `library/discover.js` (marketplace item link),
`library/plugins.js` (plugin manifest upstream link) and `library/prompts.js`
(pointer-only prompt source). `esc()` escapes `&<>` but NOT quotes, and does
nothing about the scheme — so a catalog entry carrying `javascript:…` rendered
a clickable XSS anchor, and one carrying a `"` broke out of the attribute.

Two layers here, both browser-free so they hold in CI where the Playwright
suite (`test_xss_sanitizers.py`) skips:

  1. A source scan asserting NO served module ever binds `esc()` straight into
     an `href`/`src` — the regression guard that keeps the sweep swept.
  2. A node-executed unit test of the real `safeUrl()`/`escAttr()` exports, so
     the sanitizers themselves keep coverage without a browser.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parents[2] / "api" / "static" / "js"
DOM_MODULE = JS_DIR / "core" / "dom.js"

# `href="${esc(` / `src="${esc(` — the exact unsafe binding. Single or double
# quoted attribute, any whitespace the formatter might introduce.
_UNSAFE_URL_BINDING = re.compile(r"""(?:href|src)\s*=\s*["']\$\{\s*esc\(""")


def _served_modules() -> list[Path]:
    return sorted(p for p in JS_DIR.rglob("*.js") if "vendor" not in p.parts)


def test_no_module_binds_esc_into_a_url_attribute():
    """Every untrusted URL sink goes through safeUrl(), not esc()."""
    offenders: list[str] = []
    for path in _served_modules():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _UNSAFE_URL_BINDING.search(line):
                rel = path.relative_to(JS_DIR.parents[2])
                offenders.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert (
        not offenders
    ), "href/src bound through esc() — use safeUrl() (core/dom.js):\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.parametrize(
    "module",
    ["library/discover.js", "library/plugins.js", "library/prompts.js"],
)
def test_swept_modules_import_and_use_safeurl(module: str):
    """The three modules this sweep fixed really call safeUrl (not just import
    it), so a future edit that drops the call fails loudly here."""
    src = (JS_DIR / module).read_text(encoding="utf-8")
    assert "safeUrl" in src.split("\n")[0:60][0] or "safeUrl" in src, module
    assert re.search(
        r"import\s*\{[^}]*\bsafeUrl\b[^}]*\}\s*from", src
    ), f"{module} does not import safeUrl from core/dom.js"
    assert re.search(
        r"""(?:href|src)\s*=\s*["']\$\{\s*safeUrl\(""", src
    ), f"{module} imports safeUrl but no longer binds it into a URL attribute"


def test_markdown_link_renderer_is_double_guarded():
    """Model output is rendered through `renderMarkdown`, so its link sink is
    the highest-traffic URL sink in the app. It carries BOTH guards and this
    pins both: the scheme allowlist (only http(s)/root-relative ever becomes
    an anchor) and safeUrl on the href itself."""
    src = DOM_MODULE.read_text(encoding="utf-8")
    assert "!/^https?:\\/\\//.test(u) && !u.startsWith('/')" in src, (
        "renderMarkdown lost its scheme allowlist — a javascript: markdown "
        "link would become a clickable anchor"
    )
    assert (
        'href="${safeUrl(u)}"' in src
    ), "renderMarkdown no longer sanitizes its href through safeUrl"


# ── node-executed sanitizer unit tests (no browser) ────────────────────────

_NODE = shutil.which("node") or "/opt/node22/bin/node"

_HARNESS = """
import {{ safeUrl, escAttr }} from {module!r};
const cases = {cases};
const out = {{}};
for (const [fn, arg] of cases) out[fn + '|' + arg] = (fn === 'safeUrl' ? safeUrl : escAttr)(arg);
process.stdout.write(JSON.stringify(out));
"""


def _run_node(cases: list[tuple[str, str]]) -> dict[str, str]:
    if not Path(_NODE).exists():  # pragma: no cover - environment dependent
        pytest.skip("node not available for browser-free sanitizer tests")
    script = _HARNESS.format(module=str(DOM_MODULE), cases=json.dumps(cases))
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_safeurl_blocks_dangerous_schemes_without_a_browser():
    cases = [
        ("safeUrl", "javascript:alert(1)"),
        ("safeUrl", "  JavaScript:alert(1)"),
        ("safeUrl", "data:text/html,<script>x</script>"),
        ("safeUrl", "vbscript:msgbox(1)"),
    ]
    out = _run_node(cases)
    for fn, arg in cases:
        assert out[f"{fn}|{arg}"] == "#", f"{arg!r} was not neutralized"


def test_safeurl_preserves_legitimate_urls_and_escapes_quotes():
    cases = [
        ("safeUrl", "https://example.com/a?b=1&c=2"),
        ("safeUrl", "/relative/path"),
        ("safeUrl", 'https://x.test/" onmouseover="alert(1)'),
        ("escAttr", 'a" onmouseover="alert(1)'),
    ]
    out = _run_node(cases)
    assert out["safeUrl|https://example.com/a?b=1&c=2"] == (
        "https://example.com/a?b=1&amp;c=2"
    )
    assert out["safeUrl|/relative/path"] == "/relative/path"
    # A quote-breakout attempt survives only as escaped text — it cannot close
    # the attribute and start an event handler.
    breakout = out['safeUrl|https://x.test/" onmouseover="alert(1)']
    assert '"' not in breakout and "&quot;" in breakout
    assert '"' not in out['escAttr|a" onmouseover="alert(1)']
