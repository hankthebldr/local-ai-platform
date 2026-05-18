"""
Demo recording walkthrough for the Kanban board inside Workflow Index.
Set ENCLAVE_PLAYWRIGHT_RECORD=1 to capture WebM video.
"""

from __future__ import annotations

import time

import requests


def _settle(page, ms: int = 900):
    page.wait_for_timeout(ms)


def test_demo_kanban_create_and_move(signed_in_page, base_url, api_headers):
    """Walkthrough: pick the Workflow Index tab → see the Kanban board →
    create a project → add 3 tasks across columns → move one via the UI."""
    proj_id = f"demo-kanban-{int(time.time() * 1000) & 0xFFFF:04x}"
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
    requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"Demo Kanban {proj_id}"},
        timeout=10,
    )
    for col, title in (
        ("todo", "Draft XQL rule for AcmeAuth"),
        ("todo", "Review false-positive list"),
        ("doing", "Validate detection against test logs"),
        ("done", "Write SOC runbook"),
    ):
        requests.post(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            json={
                "title": title,
                "column": col,
                "labels": ["xql"] if "XQL" in title else [],
            },
            timeout=10,
        )

    page = signed_in_page
    # IA refresh: Kanban moved out of the Workflow Index card grid into
    # its own first-class Projects tab.
    page.click('button[data-tab="projects"]')
    _settle(page, 1400)
    page.click("#kanban-panel .action-btn.ghost")  # refresh dropdown
    _settle(page, 800)
    page.evaluate(
        f"() => {{ const s=document.getElementById('kanban-project-select'); s.value={proj_id!r}; s.dispatchEvent(new Event('change')); }}"
    )
    _settle(page, 1800)

    page.click('.kanban-col[data-column="todo"] .kanban-col-add')
    _settle(page, 900)
    page.fill("#kanban-modal-title-input", "Capture demo as artifact")
    page.fill("#kanban-modal-desc", "Save the recording so the team can review.")
    page.fill("#kanban-modal-labels", "demo, capture")
    _settle(page, 600)
    page.click("#kanban-modal-submit")
    _settle(page, 1400)

    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
