"""Runtime parity gate — the browser half of the no-feature-loss net.

Companion to tests/parity/test_parity.py (pure-Python, always-on). This one
boots the served SPA in a real Chromium and asserts the two runtime invariants
the static test can't see:

  1. Object.keys(window) ⊇ golden/window_globals.json  — every app global the
     pre-split monolith exposed is still present. Pre-split this is trivially
     true; POST-split it only stays true if js/shell/legacy-bridge.js re-exposes
     each name on window. So this assertion tightens automatically across the
     ES-module fan-out and fails loudly if the bridge drops a symbol.
  2. Zero console errors / page errors on a clean boot (well-known asset-404 /
     favicon / manifest noise filtered, per conftest's convention).

Runs against a live server (see conftest `_require_stack`); auto-skips when the
stack is down. Set ENCLAVE_PLAYWRIGHT_BASE_URL to point at your dev port
(the Ralph harness runs the app on :8001).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
GOLDEN = REPO / "tests" / "parity" / "golden" / "window_globals.json"

# Same noise filter conftest.no_console_errors uses: optional-asset 404s and
# favicon/manifest chatter aren't user-facing bugs; a 401 IS (missing creds).
_IGNORE_SUBSTR = ("favicon", "manifest")


def _is_noise(text: str) -> bool:
    if any(p in text for p in _IGNORE_SUBSTR):
        return True
    if "Failed to load resource" in text and "401" not in text:
        return True
    return False


@pytest.fixture(scope="module")
def golden_globals() -> list[str]:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    # The bridge floor is the stored function + object surface (the golden
    # deliberately excludes the lone typeof-'other' boolean flag).
    return sorted(set(data["functions"]) | set(data["objects"]))


def _boot(page, base_url, license_key):
    """Boot the SPA once, with the license pre-seeded so there's no auto-fetch
    + reload race, and console/page-error listeners attached BEFORE navigation
    so boot-time errors are actually captured."""
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # add_init_script runs before any page script on every navigation → the
    # single goto below is a clean, license-bound boot. The Python API takes no
    # arg param, so the key is inlined (json.dumps → safe quoting).
    page.add_init_script(
        "try { localStorage.setItem('enclave.licenseKey', "
        + json.dumps(license_key)
        + "); localStorage.setItem('enclave.theme', 'dark'); } catch (e) {}"
    )
    page.goto(f"{base_url}/", wait_until="networkidle")
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=15_000)
    return errors


def test_window_superset_and_clean_boot(page, base_url, license_key, golden_globals):
    """Object.keys(window) ⊇ golden AND zero console errors on boot."""
    errors = _boot(page, base_url, license_key)

    window_keys = set(page.evaluate("() => Object.keys(window)"))
    missing = sorted(g for g in golden_globals if g not in window_keys)
    assert not missing, (
        "Runtime window surface dropped globals the golden requires — their "
        "inline on*= handlers will silently no-op. Post-split, bridge them in "
        f"js/shell/legacy-bridge.js:\n  {missing}"
    )

    real = [e for e in errors if not _is_noise(e)]
    assert not real, "Console/page errors on boot:\n  - " + "\n  - ".join(real)
