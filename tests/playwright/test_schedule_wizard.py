"""
Schedules rail + LibraryWizard scheduled-run wizard (Operate U8).

Exercises the Runs|Schedules rail toggle, the Workflow→Configure→Confirm wizard
(create round-trips through GET /api/schedules), and the run-now pivot that
lands on #/runs/<id>. The scoped write-401 lock row is asserted only when the
server actually enforces auth (skipped in the default auth-off harness).

The wizard submit rides post('/api/schedules', body, AdminAuth.authHeaders());
in the auth-off fast loop require_master_key is a no-op, so submit succeeds
with the license bearer the SPA already injects.
"""

from __future__ import annotations

import time

import pytest
import requests


def _first_workflow_id(base_url):
    r = requests.get(f"{base_url}/api/workflow-index", timeout=10)
    r.raise_for_status()
    wfs = r.json().get("workflows", [])
    assert wfs, "workflow-index returned no workflows"
    return wfs[0]["id"]


def _auth_enforced(base_url):
    """True when the server rejects an unauthenticated master-key write."""
    r = requests.post(
        f"{base_url}/api/schedules",
        json={
            "name": "probe",
            "workflow_id": "does-not-matter",
            "cadence": {"kind": "interval", "every_seconds": 300},
        },
        timeout=10,
    )
    # 401 → auth on. 422/200 → auth off (gate is a no-op; body/workflow rejected
    # downstream by validation, not by the key gate).
    return r.status_code == 401


def _open_schedules_rail(page):
    page.click('button[data-tab="runs"]')
    page.wait_for_selector("#tab-runs", state="visible", timeout=8_000)
    page.click('.runs-rail-mode[data-mode="schedules"]')
    page.wait_for_selector("#runs-mode-schedules", state="visible", timeout=5_000)
    page.wait_for_selector("#schedules-shell .lib-shell", timeout=6_000)


def test_rail_toggle_switches_modes(signed_in_page, base_url):
    """Runs|Schedules toggle reveals the schedules shell and + Schedule, and
    hides the runs list — without wiping #tab-runs."""
    page = signed_in_page
    page.click('button[data-tab="runs"]')
    page.wait_for_selector("#runs-mode-runs", state="visible", timeout=8_000)
    # Default is Runs mode.
    assert page.locator("#runs-mode-schedules").is_hidden()
    assert page.locator("#runs-schedule-new").is_hidden()

    page.click('.runs-rail-mode[data-mode="schedules"]')
    page.wait_for_selector("#runs-mode-schedules", state="visible", timeout=5_000)
    assert page.locator("#runs-mode-runs").is_hidden()
    assert page.locator("#runs-schedule-new").is_visible()
    # The host tab is intact — the toggle bar is still there.
    assert page.locator(".runs-rail-modebar").count() == 1

    # Back to Runs.
    page.click('.runs-rail-mode[data-mode="runs"]')
    page.wait_for_selector("#runs-mode-runs", state="visible", timeout=5_000)
    assert page.locator("#runs-mode-schedules").is_hidden()


def test_wizard_create_round_trips(signed_in_page, base_url, api_headers):
    """+ Schedule → Workflow → Configure → Confirm → submit; the created
    schedule appears in GET /api/schedules and back in the rail list."""
    page = signed_in_page
    wf_id = _first_workflow_id(base_url)
    name = f"u8-wiz-{int(time.time() * 1000) & 0xFFFFFF:06x}"
    created_id = None
    try:
        _open_schedules_rail(page)
        page.click("#runs-schedule-new")
        page.wait_for_selector("#lib-wizard-modal", state="visible", timeout=5_000)

        # Step 1 — Workflow (radio list from /api/workflow-index).
        page.wait_for_selector('input[name="sched-wf"]', timeout=6_000)
        page.check(f'input[name="sched-wf"][value="{wf_id}"]')
        page.click('[data-action="lib.wizard.next"]')

        # Step 2 — Configure (name + cadence).
        page.wait_for_selector("#sched-name", timeout=5_000)
        page.fill("#sched-name", name)
        page.select_option("#sched-cadence-kind", "daily")
        # Cadence-kind change reveals the clock block.
        page.wait_for_selector(".sched-cad-clock:not([hidden])", timeout=3_000)
        page.fill("#sched-at", "09:30")
        page.click('[data-action="lib.wizard.next"]')

        # Step 3 — Confirm → submit.
        page.wait_for_selector(".sched-confirm", timeout=5_000)
        page.click('[data-action="lib.wizard.submit"]')
        page.wait_for_selector("#lib-wizard-result .admin-modal-sub", timeout=8_000)

        # Server-side round-trip.
        rows = requests.get(
            f"{base_url}/api/schedules", headers=api_headers, timeout=10
        ).json()["schedules"]
        match = [s for s in rows if s["name"] == name]
        assert match, f"schedule {name} not found in {[s['name'] for s in rows]}"
        created_id = match[0]["id"]
        assert match[0]["workflow_id"] == wf_id
        assert match[0]["cadence"]["kind"] == "daily"
        assert match[0]["cadence"]["at"] == "09:30"

        # Close the wizard; the rail list should carry the new schedule.
        page.click('[data-action="lib.wizard.cancel"]')
        page.wait_for_function(
            f"""() => {{
                const el = document.querySelector('#schedules-shell');
                return el && el.textContent.includes({name!r});
            }}""",
            timeout=6_000,
        )
    finally:
        if created_id:
            requests.delete(
                f"{base_url}/api/schedules/{created_id}",
                headers=api_headers,
                timeout=5,
            )


def test_run_now_pivots_to_run(signed_in_page, base_url, api_headers):
    """Selecting a schedule, opening the Run pane, and clicking Run now
    dispatches a run and pivots to #/runs/<id> in the Runs list."""
    page = signed_in_page
    wf_id = _first_workflow_id(base_url)
    name = f"u8-run-{int(time.time() * 1000) & 0xFFFFFF:06x}"
    r = requests.post(
        f"{base_url}/api/schedules",
        headers=api_headers,
        json={
            "name": name,
            "workflow_id": wf_id,
            "cadence": {"kind": "interval", "every_seconds": 3600},
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text[:300]
    sched_id = r.json()["id"]
    try:
        _open_schedules_rail(page)
        page.wait_for_selector(f'.lib-row[data-id="{sched_id}"]', timeout=6_000)
        page.click(f'.lib-row[data-id="{sched_id}"]')
        # Run subnav → Run now.
        page.wait_for_selector('[data-action="sched.run-now"]', timeout=5_000)
        page.click('.lib-subnav-pill[data-section="test"]')
        page.wait_for_selector('.sched-test [data-action="sched.run-now"]', timeout=5_000)
        page.click('.sched-test [data-action="sched.run-now"]')
        # Pivot: Runs mode restored + hash carries the new run id.
        page.wait_for_function(
            "() => location.hash.startsWith('#/runs/')", timeout=10_000
        )
        page.wait_for_selector("#runs-mode-runs", state="visible", timeout=5_000)
        assert page.locator("#runs-mode-schedules").is_hidden()
    finally:
        requests.delete(
            f"{base_url}/api/schedules/{sched_id}", headers=api_headers, timeout=5
        )


def test_composer_schedule_requires_saved_workflow(signed_in_page, base_url):
    """The Composer ⏰ Schedule button refuses an unsaved canvas: it must NOT
    open the wizard (a Toast tells the operator to save first)."""
    page = signed_in_page
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=8_000)
    # The button ships on the Composer toolbar (may be scrolled off-screen).
    assert page.locator('[data-action="composer.schedule"]').count() == 1
    # Fresh canvas → signal band reads 'unsaved'. Dispatch a programmatic click
    # (the toolbar sits under the empty-state overlay); the delegated Actions
    # listener on document still fires.
    page.eval_on_selector('[data-action="composer.schedule"]', "el => el.click()")
    page.wait_for_timeout(400)
    # Wizard must not have opened for an unsaved workflow.
    assert page.locator("#lib-wizard-modal").count() == 0 or page.locator(
        "#lib-wizard-modal"
    ).is_hidden()


def test_write_401_renders_scoped_lock_row(page, base_url, license_key):
    """With auth enforced and NO key, a schedule write 401s and renders the
    scoped lock row inside the rail — the host #tab-runs must stay intact."""
    if not _auth_enforced(base_url):
        pytest.skip("server runs with auth off — scoped-lock path is a no-op")
    # Land on the SPA WITHOUT injecting a license key (unauthenticated).
    seed_headers = {"Authorization": f"Bearer {license_key}"}
    r = requests.post(
        f"{base_url}/api/schedules",
        headers=seed_headers,
        json={
            "name": f"u8-lock-{int(time.time())}",
            "workflow_id": _first_workflow_id(base_url),
            "cadence": {"kind": "interval", "every_seconds": 3600},
        },
        timeout=10,
    )
    sched_id = r.json().get("id") if r.status_code == 200 else None
    try:
        page.goto(f"{base_url}/")
        page.evaluate("() => window.localStorage.removeItem('enclave.licenseKey')")
        page.goto(f"{base_url}/")
        page.wait_for_selector("#tab-dashboard", timeout=10_000)
        _open_schedules_rail(page)
        if sched_id:
            page.click(f'.lib-row[data-id="{sched_id}"]')
            page.wait_for_selector('[data-action="sched.toggle"]', timeout=5_000)
            page.click('.sched-ov-toggle [data-action="sched.toggle"]')
            page.wait_for_selector("#schedules-shell .sched-lock-row", timeout=5_000)
        # The host tab was NOT wiped by renderLock.
        assert page.locator(".runs-rail-modebar").count() == 1
    finally:
        if sched_id:
            requests.delete(
                f"{base_url}/api/schedules/{sched_id}",
                headers=seed_headers,
                timeout=5,
            )
