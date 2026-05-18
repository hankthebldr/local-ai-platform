"""
Playwright fixtures for the Enclave SPA.

Run order:
  1. Bring up the stack:   docker compose up -d
  2. Wait for /health:     curl http://localhost:8000/health
  3. Install browser:      playwright install chromium  (one-time, ~150 MB)
  4. Run:                  pytest tests/playwright -v

Every test auto-skips when the stack isn't reachable so partial-stack runs
don't false-fail. Smoke tests run in < 30s; the @slow marker covers the
workflow-execution tests that actually hit the model.
"""

from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("ENCLAVE_PLAYWRIGHT_BASE_URL", "http://localhost:8000")
HEALTH_TIMEOUT = float(os.environ.get("ENCLAVE_PLAYWRIGHT_HEALTH_TIMEOUT", "5"))


def _stack_is_up() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=HEALTH_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


# Every test in this directory carries BOTH the canonical `e2e` marker
# and the legacy `playwright` marker (so older invocations like
# `pytest -m playwright` still work). CI selects with `-m e2e`;
# unit-test runs deselect with `-m "not e2e"`.
def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/playwright" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
            item.add_marker(pytest.mark.playwright)


@pytest.fixture(scope="session", autouse=True)
def _require_stack():
    """Skip every Playwright test if the compose stack isn't responding."""
    if not _stack_is_up():
        pytest.skip(
            f"Enclave stack not reachable at {BASE_URL}/health — "
            "start it with `docker compose up -d` and re-run.",
            allow_module_level=True,
        )


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def license_key() -> str:
    """Fetch the local license key once per session so tests don't each
    pay the modal-flow cost. Mirrors what the SPA does at boot."""
    r = requests.get(f"{BASE_URL}/api/setup/local-license", timeout=5)
    r.raise_for_status()
    key = r.json().get("key", "")
    assert key, "license-key endpoint returned an empty key"
    return key


@pytest.fixture(scope="session")
def api_headers(license_key) -> dict:
    return {"Authorization": f"Bearer {license_key}"}


# ── Browser context customization ─────────────────────────────────────────
# Force a deterministic viewport + locale so screenshots and layout-sensitive
# selectors don't flake between dev machines.


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, request):
    """Browser context defaults.

    Set ENCLAVE_PLAYWRIGHT_RECORD=1 to write per-test WebM videos to
    playwright-results/videos/ — useful for screen-record-style demos
    of feature work. Off by default to keep CI runs fast.
    """
    args = {
        **browser_context_args,
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
    }
    if os.environ.get("ENCLAVE_PLAYWRIGHT_RECORD") == "1":
        out = os.path.abspath(
            os.environ.get("ENCLAVE_PLAYWRIGHT_RECORD_DIR", "playwright-results/videos")
        )
        os.makedirs(out, exist_ok=True)
        args["record_video_dir"] = out
        args["record_video_size"] = {"width": 1440, "height": 900}
    return args


# ── Signed-in page ────────────────────────────────────────────────────────


@pytest.fixture
def signed_in_page(page, base_url, license_key):
    """A page already past the boot/license flow.

    Strategy: inject the license key into localStorage under the same slot
    the SPA reads from (`enclave.licenseKey`), then navigate. This skips
    the auto-fetch + reload boot dance entirely and lands you on the
    Composer with auth headers already injected by the monkey-patched
    fetch wrapper.
    """
    page.goto(f"{base_url}/")  # any page in the origin lets us touch its localStorage
    page.evaluate(
        """(key) => {
            window.localStorage.setItem('enclave.licenseKey', key);
            window.sessionStorage.removeItem('enclave.admin.masterKey');
        }""",
        license_key,
    )
    page.goto(
        f"{base_url}/"
    )  # second nav so the SPA boots with the key already in storage
    # The license-bound boot path doesn't pop the modal; the Composer canvas
    # is the default-active tab and should render its workbench.
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=10_000)
    return page


# ── Quick assertions ──────────────────────────────────────────────────────


@pytest.fixture
def no_console_errors(page):
    """Capture all console.error / page errors emitted during a test and
    fail the test if any unexpected ones fire. Some panels log network
    HTTP-status warnings that aren't bugs; those get filtered."""
    errors: list[str] = []

    def _on_console(msg):
        if msg.type == "error":
            errors.append(msg.text)

    def _on_pageerror(err):
        errors.append(str(err))

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)

    yield errors

    # Ignore well-known noise that doesn't break user experience.
    ignored_patterns = [
        "favicon",
        "Failed to load resource",  # network 404s for optional assets
        "manifest",
    ]
    real_errors = [e for e in errors if not any(p in e for p in ignored_patterns)]
    assert not real_errors, "Unexpected console errors:\n  - " + "\n  - ".join(
        real_errors
    )
