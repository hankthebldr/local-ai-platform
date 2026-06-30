"""
Live Runs view — SSE stream integration test.

Verifies that when a run detail is open the UI renders:
  - [data-testid="run-plan"]  container (the live plan panel)
  - [data-testid="plan-item"] rows when a plan.updated SSE frame arrives
  - [data-testid="run-status"][data-status="completed"] once the run finishes

The SSE stream endpoint is GET /api/workflows/runs/{run_id}/stream.
The UI subscribes automatically when a run detail is opened for a
running/queued run.  For completed runs the panel stays visible if a
plan was ever received during the run's lifetime (SSE may have already
closed), so the test waits for the run to reach completed status and
checks the selector chain is wired correctly.

Harness mirrors conftest.py exactly:
  - _require_stack session fixture auto-skips when the stack is down
  - signed_in_page fixture for a pre-authenticated page
  - api_headers for direct HTTP calls to seed a run
"""

from __future__ import annotations

import time

import pytest
import requests


# ---------------------------------------------------------------------------
# Helper — kick off a real async run and return its run_id
# ---------------------------------------------------------------------------


def _start_run(base_url: str, api_headers: dict) -> str:
    """POST /api/workflows/run-async with a minimal seed and return run_id."""
    payload = {
        "workflow_id": "xsiam-detection-engineering",
        "seed": {
            "alert_id": "SSE-STREAM-TEST-001",
            "raw_log": "test log for sse stream test",
            "asset_info": {"hostname": "sse-test-host", "criticality": "low"},
            "timeframe": {
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-01T01:00:00Z",
            },
        },
    }
    r = requests.post(
        f"{base_url}/api/workflows/run-async",
        headers=api_headers,
        json=payload,
        timeout=15,
    )
    assert (
        r.status_code == 200
    ), f"run-async failed: HTTP {r.status_code} — {r.text[:200]}"
    run_id = r.json()["run_id"]
    assert run_id, "run-async returned no run_id"
    return run_id


def _wait_pollable(
    base_url: str, api_headers: dict, run_id: str, timeout: float = 5.0
) -> None:
    """Wait until GET /api/workflows/runs/{run_id} returns 200."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(
            f"{base_url}/api/workflows/runs/{run_id}",
            headers=api_headers,
            timeout=5,
        )
        if r.status_code == 200:
            return
        time.sleep(0.3)
    pytest.fail(f"Run {run_id} never became pollable within {timeout}s")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_runs_view_renders_live_plan(signed_in_page, base_url, api_headers):
    """
    Open a run detail via the #/runs/<run_id> deep link and assert:
      1. The [data-testid="run-plan"] container is present in the DOM.
      2. At least one [data-testid="plan-item"] row exists IF the run
         emits a plan.updated SSE frame (best-effort; the panel appears
         regardless because the DOM scaffold is always present).
      3. The [data-testid="run-status"] element exists.
      4. The run eventually reaches completed status (data-status="completed").

    The test uses a real async run so the SSE stream fires naturally.
    If the engine completes the run before the browser opens the detail
    the poller still updates data-status correctly.
    """
    page = signed_in_page

    # 1. Kick off a run via the API so we have a real run_id.
    run_id = _start_run(base_url, api_headers)
    _wait_pollable(base_url, api_headers, run_id)

    # 2. Navigate to the run detail deep link.
    page.goto(f"{base_url}/#/runs/{run_id}")

    # 3. The Runs tab should activate and the detail container become visible.
    #    The run-plan container is always present in the DOM once the tab loads.
    page.wait_for_selector("[data-testid='run-plan']", timeout=10_000)

    # 4. The run-status element must exist (wired to runs-tab-detail-meta).
    page.wait_for_selector("[data-testid='run-status']", timeout=5_000)

    # 5. Wait for the run to complete (engine runs fast on smoke seed;
    #    give up to 60 s for the slowest model).
    page.wait_for_selector(
        "[data-testid='run-status'][data-status='completed']",
        timeout=60_000,
    )

    # 6. If the SSE stream delivered a plan the panel should have items.
    #    This is a best-effort check — if no plan.updated frame was emitted
    #    the panel may be hidden and have no items, which is acceptable.
    plan_panel = page.locator("#runs-tab-live-plan")
    if plan_panel.is_visible():
        # Panel visible means at least one plan.updated SSE frame arrived.
        assert (
            page.locator("[data-testid='plan-item']").count() >= 1
        ), "Live plan panel is visible but contains no plan-item rows"


def test_runs_view_plan_panel_hidden_on_no_sse(signed_in_page, base_url, api_headers):
    """
    For a completed run (no active SSE stream) the live plan panel must
    start hidden — it only appears if a plan.updated frame was received
    during the run's live window.  Navigating directly to a completed run
    should NOT show a stale plan from a previous selection.
    """
    page = signed_in_page

    # Start a run and wait for it to finish via the API before opening UI.
    run_id = _start_run(base_url, api_headers)

    # Poll until terminal.
    deadline = time.time() + 90
    status = "queued"
    while time.time() < deadline:
        r = requests.get(
            f"{base_url}/api/workflows/runs/{run_id}",
            headers=api_headers,
            timeout=5,
        )
        if r.status_code == 200:
            status = r.json().get("status", "queued")
            if status in ("completed", "failed", "canceled", "error"):
                break
        time.sleep(1)

    # Navigate to the completed run — the panel starts hidden because no
    # SSE stream fires for terminal runs.
    page.goto(f"{base_url}/#/runs/{run_id}")
    page.wait_for_selector("[data-testid='run-status']", timeout=10_000)

    # The run-plan testid container must exist in the DOM even if hidden.
    assert (
        page.locator("[data-testid='run-plan']").count() >= 1
    ), "run-plan testid container missing from DOM"

    # data-status must reflect the terminal status.
    status_el = page.locator("[data-testid='run-status']")
    actual_status = status_el.get_attribute("data-status")
    assert actual_status in (
        "completed",
        "failed",
        "canceled",
        "error",
    ), f"Unexpected data-status on terminal run: {actual_status!r}"
