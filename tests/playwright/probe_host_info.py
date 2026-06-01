"""Ad-hoc browser probe: does the SPA render host info on Models + Admin?

Not a pytest test — a diagnostic script. Run:
    ENCLAVE_PLAYWRIGHT_BASE_URL=http://localhost:8001 \
        python tests/playwright/probe_host_info.py

Reports console errors, failed requests, whether a sign-in modal is blocking,
and whether the BD790i/Blackwell host strings appear on the Models + Admin tabs.
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ENCLAVE_PLAYWRIGHT_BASE_URL", "http://localhost:8001")


def main() -> int:
    console_errors = []
    failed = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("requestfailed", lambda r: failed.append(r.url))
        page.on(
            "response",
            lambda r: failed.append(f"{r.status} {r.url}") if r.status >= 400 else None,
        )

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(2500)

        # Is a sign-in / auth modal visible and blocking?
        modal_visible = page.evaluate("""() => {
                const m = document.getElementById('admin-signin-modal')
                       || document.querySelector('[id*=signin], [class*=signin]');
                if (!m) return false;
                const s = getComputedStyle(m);
                return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            }""")

        body = page.inner_text("body")
        signed_in = page.evaluate(
            "() => window.Auth && window.Auth.isSignedIn ? window.Auth.isSignedIn() : null"
        )

        # Look for the host strings the inventory endpoint returns.
        host_hits = {
            s: (s in body) for s in ("7945HX", "Blackwell", "BD790i", "bd790i")
        }

        print(f"BASE_URL            : {BASE}")
        print(f"Auth.isSignedIn()   : {signed_in}")
        print(f"sign-in modal shown : {modal_visible}")
        print(f"host strings in DOM : {host_hits}")
        print(
            f"4xx/5xx responses   : {sorted(set(x for x in failed if x[:1].isdigit()))[:8]}"
        )
        print(f"console errors      : {console_errors[:5]}")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
