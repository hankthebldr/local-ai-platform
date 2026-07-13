"""
Runs tab — cursor paging + additive filter chips (U6, op4-runs-ui).

Verifies the client half of the runs-index contract landed in U5:
  - the list renders server-paged rows from /api/workflows/runs-index
  - the discrete Prev/Next pager REPLACES the current page (bounded list that
    fits the frame) and walks the keyset cursor forward + back
  - the four inline setFilter chips (golden-pinned, byte-for-byte) still drive a
    server refetch through the new health= param — clicking Failed yields only
    failed/error rows
  - the additive delegated chips render: Degraded on the Health row and the
    whole Type row (All·Manual·Scheduled·Autonomous·Test), and a Type click
    refetches + activates

Harness mirrors conftest.py: signed_in_page lands past the boot/license flow;
the run corpus under data/workflows supplies enough rows to page.
"""

from __future__ import annotations

import pytest


def _open_runs(page, base_url):
    """Navigate to the Runs list and wait for the first server page to paint."""
    page.goto(f"{base_url}/#/runs")
    page.wait_for_selector("#tab-runs", state="visible", timeout=10_000)
    # First page of rows (runs-index limit=30) — the corpus is large so at least
    # one row is guaranteed. Generous timeout: the first scan warms caches.
    page.wait_for_selector(".runs-tab-row", timeout=15_000)


def test_chips_render(signed_in_page, base_url):
    """The additive Degraded + Type chips are present alongside the four
    verbatim inline Health chips."""
    page = signed_in_page
    _open_runs(page, base_url)

    # Four inline (golden-pinned) Health chips still present.
    for f in ("all", "running", "completed", "failed"):
        assert (
            page.locator(f'.runs-tab-filter[data-filter="{f}"]').count() == 1
        ), f"inline Health chip {f!r} missing"

    # Additive delegated Degraded chip — data-action, NOT an inline handler.
    degraded = page.locator('[data-action="runs.filter-health"][data-health="degraded"]')
    assert degraded.count() == 1, "delegated Degraded chip missing"

    # Full delegated Type row.
    type_values = page.locator(".runs-tab-typechip").evaluate_all(
        "els => els.map(e => e.dataset.type)"
    )
    assert type_values == ["all", "manual", "scheduled", "autonomous", "test"], (
        f"Type row chips wrong: {type_values!r}"
    )


def test_pager_navigates_pages(signed_in_page, base_url):
    """The discrete pager REPLACES the list on Next (bounded page), advances the
    page label, and Prev returns to the original page-1 rows."""
    page = signed_in_page
    _open_runs(page, base_url)

    # Page 1: Prev disabled (we're at the top), pager pinned below the rows.
    first_run = page.locator(".runs-tab-row").first.get_attribute("data-run-id")
    assert first_run, "no rows on first page"

    # Unfiltered view shows the total page count ("Page 1 of M") derived from the
    # run-index total; skip the assert if the pager is a single hidden page.
    pager = page.locator("#runs-tab-pager")
    if pager.count() == 1 and not pager.is_hidden():
        import re as _re

        label = page.locator(".runs-tab-pager-label").inner_text()
        assert _re.search(r"Page 1 of \d+", label), f"expected 'Page 1 of M', got {label!r}"
    assert (
        page.locator('[data-action="runs.prev-page"]:disabled').count() == 1
        or page.locator("#runs-tab-pager[hidden]").count() == 1
    ), "Prev should be disabled on page 1"

    next_btn = page.locator('[data-action="runs.next-page"]:not([disabled])')
    if next_btn.count() == 0:
        pytest.skip("corpus fit in a single page — no second page to navigate")

    next_btn.click()
    # Next REPLACES the list with page 2 and the label advances.
    page.wait_for_function(
        "() => /Page 2/.test((document.querySelector('.runs-tab-pager-label')||{}).textContent||'')",
        timeout=15_000,
    )
    # Prev is now enabled; clicking it returns to page 1's first row.
    page.locator('[data-action="runs.prev-page"]').click()
    page.wait_for_function(
        "(id) => { const r = document.querySelector('.runs-tab-row'); return r && r.getAttribute('data-run-id') === id; }",
        arg=first_run,
        timeout=15_000,
    )
    # Count badge is per-page rows now (no loaded/scanned slash).
    badge = page.locator("#runs-tab-count").inner_text()
    assert "/" not in badge, f"count badge should be per-page, got {badge!r}"


def test_inline_failed_chip_refetches(signed_in_page, base_url):
    """Clicking the golden inline Failed chip refetches server-side on the
    health= param — every visible row is failed/error."""
    page = signed_in_page
    _open_runs(page, base_url)

    failed_chip = page.locator('.runs-tab-filter[data-filter="failed"]')
    failed_chip.click()
    # Chip becomes active (setFilter toggled it) and the list re-renders.
    page.wait_for_selector('.runs-tab-filter[data-filter="failed"].active', timeout=5_000)
    # Give the refetch a beat to land.
    page.wait_for_timeout(1200)

    statuses = page.locator(".runs-tab-row-status").evaluate_all(
        "els => els.map(e => (e.textContent || '').trim().toLowerCase())"
    )
    if not statuses:
        pytest.skip("no failed runs in the corpus to assert against")
    # Server health=failed ⇒ only failed/error statuses come back. The status
    # span may carry a trailing 'degraded' badge word; check the leading token.
    for s in statuses:
        head = s.split()[0] if s else ""
        assert head in ("failed", "error"), f"non-failed row under Failed filter: {s!r}"


def test_type_chip_refetches(signed_in_page, base_url):
    """Clicking a delegated Type chip activates it and refetches (server type=)."""
    page = signed_in_page
    _open_runs(page, base_url)

    scheduled = page.locator('.runs-tab-typechip[data-type="scheduled"]')
    scheduled.click()
    page.wait_for_selector('.runs-tab-typechip[data-type="scheduled"].active', timeout=5_000)
    page.wait_for_timeout(1000)
    # 'All' Type chip loses active — single-select row.
    assert (
        page.locator('.runs-tab-typechip[data-type="all"].active').count() == 0
    ), "Type row is not single-select"
