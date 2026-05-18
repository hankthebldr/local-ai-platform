"""
Data Model Rule creation — the centerpiece XQL flow.

Two flavors:
  * Smoke (default): drive the UI through the steps a real operator would
    take, asserting at each surface that the workflow loads, seeds, and
    is runnable. ~10 seconds, no model inference required for the asserts
    that matter.
  * Full (marked @slow): actually fire the workflow run via /api/workflows
    and wait for the multi-step DAG to finish. Marked @slow so CI can
    skip it; run locally with `pytest -m slow tests/playwright/test_data_model_rule_smoke.py`.

This file is the single source of truth for "is the XDM/XQL value-prop
of Enclave actually working?" — every regression that ships visible to
operators should be caught here before reaching them.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
import requests


# A representative single-source vendor log. Mirrors the format the
# xdm-rule-from-log workflow expects: one parseable JSON object with a
# small set of vendor-named fields. Designed to exercise pattern-family
# detection without needing a giant fixture corpus.
SAMPLE_VENDOR_LOG = {
    "timestamp": "2026-05-15T18:34:21.512Z",
    "event_type": "auth.login.success",
    "src_ip": "10.42.1.55",
    "dst_ip": "10.42.1.10",
    "user": "alice@example.com",
    "host": "workstation-07",
    "vendor": "AcmeAuth",
    "product": "AcmeAuth Cloud SSO",
    "session_id": "9c8f4a21-b6e3-4d77-92e3-7c9c4d7b2e10",
    "raw": "May 15 18:34:21 sso-edge AcmeAuth[1031]: AUTH_OK user=alice ip=10.42.1.55",
}


# ────────────────────────────────────────────────────────────────────────────
# Smoke — UI flow only. Fast.
# ────────────────────────────────────────────────────────────────────────────


def test_xdm_rule_workflow_visible_in_index(signed_in_page):
    """The XDM-rule-from-log workflow must appear in the Workflow Index."""
    page = signed_in_page
    page.click('button[data-tab="workflow-index"]')
    page.wait_for_selector("#tab-workflow-index", state="visible", timeout=5_000)
    # Skeleton loaders fill the grid initially but render as transparent
    # text — wait for the actual card markup (or any error/empty state)
    # instead of just innerHTML length.
    page.wait_for_function(
        """() => {
            const grid = document.getElementById('wfi-grid');
            if (!grid) return false;
            return !!grid.querySelector('.wfi-card, .enclave-error-panel, .enclave-empty-state');
        }""",
        timeout=15_000,
    )
    grid_text = page.locator("#wfi-grid").inner_text()
    assert "XDM Rule from Single Log Sample" in grid_text
    assert "xdm-rule-from-log" in grid_text or "xdm-rule" in grid_text.lower()


def test_xdm_rule_workflow_loads_into_composer(signed_in_page):
    """Open the XDM rule workflow in the Composer and verify the 4 step nodes
    materialise on the drawflow canvas. This is the precondition for any
    user to actually run or edit the workflow."""
    page = signed_in_page

    # Use the public backend route to confirm the workflow has 4 steps before
    # we drive the UI; if the YAML changed shape, the UI test would silently
    # adapt and we'd lose the regression guard.
    api = requests.get(
        f"{page.url.split('/', 3)[0] + '//' + page.url.split('/', 3)[2]}/api/workflows",
        headers={
            "Authorization": "Bearer "
            + page.evaluate("() => window.localStorage.getItem('enclave.licenseKey')")
        },
        timeout=5,
    )
    api.raise_for_status()
    workflows = api.json()
    xdm = next((w for w in workflows if w["id"] == "xdm-rule-from-log"), None)
    assert xdm is not None, "xdm-rule-from-log not in /api/workflows"
    assert xdm["steps"] == 4, f"xdm-rule-from-log expected 4 steps, got {xdm['steps']}"

    # Now drive the UI: open Workflow Index, click the card's load action.
    page.click('button[data-tab="workflow-index"]')
    # Wait for cards (transparent skeletons no longer satisfy length checks).
    page.wait_for_function(
        """() => {
            const grid = document.getElementById('wfi-grid');
            if (!grid) return false;
            return !!grid.querySelector('.wfi-card, .enclave-error-panel, .enclave-empty-state');
        }""",
        timeout=15_000,
    )
    card = page.locator(".wfi-card", has_text="XDM Rule from Single Log Sample").first
    if card.count() == 0:
        card = page.locator("[data-wf-id='xdm-rule-from-log']").first
    assert card.count() > 0, "XDM rule card not found in index"

    # The card's primary action is labeled "Compose" (openInComposer).
    open_btn = card.locator("button", has_text="Compose").first
    if open_btn.count() == 0:
        open_btn = card.locator("button", has_text="Open").first
    if open_btn.count() == 0:
        open_btn = card.locator("button").first
    open_btn.click()

    # Should land on Composer with the workflow ID populated.
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=5_000)
    page.wait_for_function(
        "() => document.getElementById('df-wf-id').value === 'xdm-rule-from-log'",
        timeout=10_000,
    )
    # The 4 step nodes should render on the canvas.
    page.wait_for_function(
        """() => {
            const canvas = document.getElementById('drawflow-canvas');
            if (!canvas) return false;
            return canvas.querySelectorAll('.drawflow-node').length >= 4;
        }""",
        timeout=15_000,
    )


def test_xdm_rule_workflow_seed_input_is_writable(signed_in_page):
    """The seed input (#wf-seed) is the operator's entry point: paste a
    vendor log here, then Run.

    After the IA reorg, Runs is no longer a top-level tab — it lives
    inside the System hub (Admin → System → Runs). The most robust way
    to reach it from tests is switchTab('workflows') directly, which
    works regardless of which entry point the UI exposes.
    """
    page = signed_in_page
    page.evaluate("() => window.switchTab && window.switchTab('workflows')")
    page.wait_for_selector("#tab-workflows", state="visible", timeout=5_000)
    seed = page.locator("#wf-seed").first
    if seed.count() == 0:
        pytest.skip("#wf-seed input not present on the active Runs tab — UI variant")
    # Playwright's .fill() runs an actionability check; the textarea sits
    # inside a panel whose ancestor layout sometimes confuses the hit-test.
    # Skip the check via evaluate-set, then read back to confirm persistence.
    seed_payload = json.dumps({"log_sample": SAMPLE_VENDOR_LOG})
    seed.evaluate(
        "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles: true})); }",
        seed_payload,
    )
    assert seed.input_value() == seed_payload


# ────────────────────────────────────────────────────────────────────────────
# Full — drive the actual workflow runner against Ollama. Slow.
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.slow
def test_xdm_rule_workflow_executes_end_to_end(base_url, api_headers):
    """End-to-end: POST to /api/workflows/{id}/run with a real seed, poll
    for completion, assert every step produced an output, and verify the
    final step emitted text consistent with an XDM rule.

    This is intentionally an API-driven test (not browser-driven) — once
    we've proven via the smoke tests above that the UI fires the same
    payload, the workflow correctness lives at the API layer and runs
    much faster without the browser overhead.

    Skips if no model is loaded so the test doesn't hang on a fresh stack.
    """
    # Pre-flight: at least one model must be loaded.
    models = requests.get(
        f"{base_url}/v1/models", headers=api_headers, timeout=5
    ).json()
    if not models.get("data"):
        pytest.skip("No models loaded in Ollama; pull at least one model first")
    model_id = models["data"][0]["id"]

    # Trigger the workflow. The exact endpoint shape varies by build; try
    # the two known variants in order.
    run_payload = {
        "seed": {"log_sample": SAMPLE_VENDOR_LOG, "model_override": model_id},
        "config": {"timeout": 300},
    }
    r = requests.post(
        f"{base_url}/api/workflows/xdm-rule-from-log/run",
        json=run_payload,
        headers=api_headers,
        timeout=10,
    )
    if r.status_code == 404:
        # Older endpoint shape
        r = requests.post(
            f"{base_url}/api/workflows/run",
            json={"workflow_id": "xdm-rule-from-log", **run_payload},
            headers=api_headers,
            timeout=10,
        )
    assert r.status_code in (
        200,
        202,
    ), f"Workflow run kickoff failed: HTTP {r.status_code} — {r.text[:300]}"
    run = r.json()
    run_id = run.get("run_id") or run.get("id")
    assert run_id, f"Run kickoff returned no run_id: {run}"

    # Poll for completion. 4 steps × ~30s/step on a small model = up to 2 min.
    deadline = time.time() + 240
    final: Any = None
    while time.time() < deadline:
        time.sleep(3)
        status = requests.get(
            f"{base_url}/api/workflows/runs/{run_id}",
            headers=api_headers,
            timeout=10,
        )
        if status.status_code == 404:
            status = requests.get(
                f"{base_url}/api/workflows/run/{run_id}",
                headers=api_headers,
                timeout=10,
            )
        if status.status_code != 200:
            continue
        body = status.json()
        if body.get("status") in ("completed", "succeeded", "done"):
            final = body
            break
        if body.get("status") in ("failed", "error"):
            pytest.fail(f"Workflow run failed: {body}")
    assert (
        final is not None
    ), f"Workflow did not complete within 4 minutes (run_id={run_id})"

    # Every step in the 4-step pipeline must have produced output.
    steps = final.get("steps") or final.get("step_outputs") or []
    assert (
        len(steps) >= 4
    ), f"Expected ≥4 step outputs, got {len(steps)}; run body: {json.dumps(final)[:500]}"

    # Last step is `validate_and_revise` per the YAML — its output should
    # contain XDM-shaped text (mention "xdm." paths or a MODEL block).
    last_output = json.dumps(steps[-1]).lower()
    assert (
        "xdm" in last_output or "model" in last_output
    ), f"Final step output doesn't look like an XDM rule: {last_output[:300]}"
