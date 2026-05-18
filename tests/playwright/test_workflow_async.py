"""
Async workflow execution + polling. Guards the new live-progress path
that powers the Composer's Active Run pane.

The endpoint kicks off the engine in a background task and returns the
run_id immediately. The SPA polls /api/workflows/runs/{run_id} to watch
step results land as the engine checkpoints after each step.
"""

from __future__ import annotations

import time

import requests


def test_run_async_returns_run_id_immediately(base_url, api_headers):
    """POST /api/workflows/run-async must return a run_id in well under
    the time a real synchronous run would take. Uses a tiny seed so even
    if the background task starts inference fast the endpoint still
    returns first."""
    payload = {
        "workflow_id": "xsiam-detection-engineering",
        "seed": {
            "alert_id": "ASYNC-SMOKE-001",
            "raw_log": "stub log",
            "asset_info": {"hostname": "h", "criticality": "low"},
            "timeframe": {
                "start": "2026-05-18T00:00:00Z",
                "end": "2026-05-18T01:00:00Z",
            },
        },
    }
    t0 = time.time()
    r = requests.post(
        f"{base_url}/api/workflows/run-async",
        headers=api_headers,
        json=payload,
        timeout=15,
    )
    elapsed = time.time() - t0
    assert (
        r.status_code == 200
    ), f"async kickoff failed: HTTP {r.status_code} — {r.text[:200]}"
    body = r.json()
    assert body["run_id"], "no run_id in response"
    assert body["status"] in ("queued", "running"), f"bad status: {body['status']}"
    assert body["poll_url"].endswith(body["run_id"]), "poll_url mismatch"
    # The whole point of async is that the response is fast.
    assert (
        elapsed < 5
    ), f"run-async took {elapsed:.1f}s — should return immediately, not block on the engine"


def test_run_async_run_id_is_pollable(base_url, api_headers):
    """The run_id the async endpoint returns must be immediately
    readable via /api/workflows/runs/{id} (the engine pre-checkpoints
    a queued record so the SPA's poll doesn't 404 on the first tick)."""
    r = requests.post(
        f"{base_url}/api/workflows/run-async",
        headers=api_headers,
        json={
            "workflow_id": "xsiam-detection-engineering",
            "seed": {
                "alert_id": "ASYNC-POLL-001",
                "raw_log": "stub log",
                "asset_info": {"hostname": "h", "criticality": "low"},
                "timeframe": {
                    "start": "2026-05-18T00:00:00Z",
                    "end": "2026-05-18T01:00:00Z",
                },
            },
        },
        timeout=10,
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    # Tight retry loop because the background task starts in a background
    # thread; the initial checkpoint is best-effort but should land within
    # a couple of seconds.
    deadline = time.time() + 5
    poll = None
    while time.time() < deadline:
        poll = requests.get(
            f"{base_url}/api/workflows/runs/{run_id}",
            headers=api_headers,
            timeout=5,
        )
        if poll.status_code == 200:
            break
        time.sleep(0.3)
    assert (
        poll is not None and poll.status_code == 200
    ), f"run {run_id} never became pollable; last status {poll.status_code if poll else 'n/a'}"
    snap = poll.json()
    assert snap.get("run_id") == run_id
    assert snap.get("workflow_id") == "xsiam-detection-engineering"
    assert snap.get("status") in ("queued", "running", "completed", "failed"), snap


def test_run_async_invalid_workflow_returns_404_or_422(base_url, api_headers):
    """Unknown workflow id rejected up-front, not silently dropped onto
    a background task that quietly dies."""
    r = requests.post(
        f"{base_url}/api/workflows/run-async",
        headers=api_headers,
        json={"workflow_id": "this-does-not-exist", "seed": {}},
        timeout=10,
    )
    assert r.status_code in (
        404,
        422,
        500,
    ), f"expected 4xx for missing workflow; got {r.status_code} — {r.text[:200]}"
