"""
Artifacts tab — outputs, workspaces, format sets (Operate U11 · O5).

Exercises the new Operate Artifacts surface:
  · nav order is Workflows · Projects · Runs · Artifacts · Context;
  · the tab opens into a three-pane switcher (Outputs · Workspaces · Format Sets);
  · Outputs lists rows from the seeded run inventory and the Open-run pivot lands
    on #tab-runs with the run selected;
  · a Format Set's Preview renders the serialized [format:…] constraint sentinel;
  · "Schedule a run here" opens the U8 wizard prefilled with the workspace.

All reads ride the scope-authed GET routes; in the auth-off fast loop the
master-key gate is a no-op, so the panes render with the license bearer the SPA
already injects. Writes are not exercised here (covered by the backend units).
"""

from __future__ import annotations

import pytest
import requests


# ── helpers ──────────────────────────────────────────────────────────────


def _open_artifacts(page):
    page.click('button[data-tab="artifacts"]')
    page.wait_for_selector("#tab-artifacts", state="visible", timeout=8_000)


def _first_run_artifact(base_url, api_headers):
    r = requests.get(f"{base_url}/api/artifacts?limit=5", headers=api_headers, timeout=10)
    r.raise_for_status()
    items = r.json().get("items", [])
    for it in items:
        prov = it.get("provenance") or {}
        if it.get("source") == "run" and prov.get("run_id"):
            return it
    return items[0] if items else None


# ── nav order (F20/C10) ──────────────────────────────────────────────────


def test_nav_order_workflows_projects_runs_artifacts_context(signed_in_page):
    """The Operate nav renders in the one canonical order and Artifacts is a
    delegated switch-tab button (no new inline onclick)."""
    page = signed_in_page
    order = page.eval_on_selector_all(
        ".tab-nav .tab-btn",
        "els => els.map(e => e.getAttribute('data-tab'))",
    )
    # The five Operate tabs must appear in this relative order.
    operate = [t for t in order if t in
               ("workflow-index", "projects", "runs", "artifacts", "context")]
    assert operate == ["workflow-index", "projects", "runs", "artifacts", "context"], operate

    btn = page.locator('.tab-nav .tab-btn[data-tab="artifacts"]')
    assert btn.count() == 1
    # Delegated handler — no inline onclick was added for Artifacts.
    assert btn.get_attribute("onclick") is None
    assert btn.get_attribute("data-action") == "switch-tab"


# ── tab shell + three panes ──────────────────────────────────────────────


def test_tab_opens_three_panes(signed_in_page):
    page = signed_in_page
    _open_artifacts(page)
    # Default pane = Outputs, its shell mounts.
    page.wait_for_selector("#artifacts-outputs-shell .lib-shell", timeout=8_000)
    assert page.locator("#artifacts-pane-outputs").is_visible()
    assert page.locator("#artifacts-pane-workspaces").is_hidden()
    assert page.locator("#artifacts-pane-formats").is_hidden()

    # Switch to Workspaces.
    page.click('.artifacts-pane-btn[data-pane="workspaces"]')
    page.wait_for_selector("#artifacts-workspaces-shell .lib-shell", timeout=8_000)
    assert page.locator("#artifacts-pane-workspaces").is_visible()
    assert page.locator("#artifacts-pane-outputs").is_hidden()

    # Switch to Format Sets.
    page.click('.artifacts-pane-btn[data-pane="formats"]')
    page.wait_for_selector("#artifacts-formats-shell .lib-shell", timeout=8_000)
    assert page.locator("#artifacts-pane-formats").is_visible()


# ── outputs rows + open-run pivot ────────────────────────────────────────


def test_outputs_rows_and_open_run_pivot(signed_in_page, base_url, api_headers):
    page = signed_in_page
    art = _first_run_artifact(base_url, api_headers)
    if not art:
        pytest.skip("no artifacts in the inventory to exercise the outputs pane")
    run_id = (art.get("provenance") or {}).get("run_id")

    _open_artifacts(page)
    page.wait_for_selector("#artifacts-outputs-shell .lib-row", timeout=10_000)
    assert page.locator("#artifacts-outputs-shell .lib-row").count() >= 1

    # Select the seeded run artifact + open its overview.
    page.click(f'#artifacts-outputs-shell .lib-row[data-id="{art["id"]}"]')
    page.wait_for_selector("#artifacts-outputs-shell .lib-actions-row", timeout=6_000)

    if run_id:
        # Open-run pivot lands on #tab-runs with the run selected.
        page.click('#artifacts-outputs-shell [data-action="artifacts.open-run"]')
        page.wait_for_selector("#tab-runs", state="visible", timeout=8_000)
        page.wait_for_function(
            f"() => (location.hash || '').includes({run_id!r})",
            timeout=6_000,
        )


# ── format-set preview renders the sentinel ──────────────────────────────


def test_format_set_preview_renders_sentinel(signed_in_page):
    page = signed_in_page
    _open_artifacts(page)
    page.click('.artifacts-pane-btn[data-pane="formats"]')
    page.wait_for_selector("#artifacts-formats-shell .lib-row", timeout=10_000)

    # Select the first built-in format set.
    page.click("#artifacts-formats-shell .lib-row >> nth=0")
    page.wait_for_selector('[data-action="artifacts.fmt-preview"]', timeout=6_000)
    page.click('[data-action="artifacts.fmt-preview"]')
    # Preview section renders the serialized constraint lines.
    page.wait_for_selector('[data-testid="fmt-preview"]', timeout=6_000)
    txt = page.locator('[data-testid="fmt-preview"]').inner_text()
    assert "[format:" in txt and "[/format]" in txt, txt[:200]


# ── ws-schedule opens the prefilled wizard ───────────────────────────────


def test_ws_schedule_opens_prefilled_wizard(signed_in_page, base_url, api_headers):
    page = signed_in_page
    wss = requests.get(f"{base_url}/api/workspaces", headers=api_headers, timeout=10).json()
    workspaces = wss.get("workspaces", [])
    if not workspaces:
        pytest.skip("no workspaces to schedule against")
    ws_name = workspaces[0]["name"]

    _open_artifacts(page)
    page.click('.artifacts-pane-btn[data-pane="workspaces"]')
    page.wait_for_selector(f'#artifacts-workspaces-shell .lib-row[data-id="{ws_name}"]', timeout=10_000)
    page.click(f'#artifacts-workspaces-shell .lib-row[data-id="{ws_name}"]')
    page.wait_for_selector('[data-action="artifacts.ws-schedule"]', timeout=6_000)
    page.click('[data-action="artifacts.ws-schedule"] >> nth=0')

    # The U8 wizard opens; advancing to Configure shows the workspace preselected.
    page.wait_for_selector("#lib-wizard-modal", state="visible", timeout=6_000)
    page.wait_for_selector('input[name="sched-wf"]', timeout=6_000)
    # Pick any workflow, advance to Configure, assert the workspace prefilled.
    page.click('input[name="sched-wf"] >> nth=0')
    page.click('[data-action="lib.wizard.next"]')
    page.wait_for_selector("#sched-workspace", timeout=6_000)
    # The workspace <select> is populated async from /api/workspaces; poll until
    # the prefilled value settles.
    page.wait_for_function(
        f"""() => {{
            const el = document.getElementById('sched-workspace');
            return el && el.value === {ws_name!r};
        }}""",
        timeout=6_000,
    )
    page.click('[data-action="lib.wizard.cancel"]')
