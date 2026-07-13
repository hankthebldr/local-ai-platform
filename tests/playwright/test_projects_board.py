"""
Projects tab — Board · Backlog · Timeline · Docs segments (U3).

Exercises the segmented control, the re-adopted Kanban panel inside the Board
segment, the deferred-single-click task drawer (vs the dblclick edit modal),
the Timeline Unscheduled lane, and the Docs bind + markdown edit round-trip.

The backend task log + workspace routes are covered elsewhere; these are the
UI-integration assertions the F1/U3 gate needs.
"""

from __future__ import annotations

import time

import requests


def _mk_project(base_url, api_headers, prefix):
    proj_id = f"{prefix}-{int(time.time() * 1000) & 0xFFFFFF:06x}"
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
    r = requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"U3 {proj_id}"},
        timeout=10,
    )
    assert r.status_code in (200, 201), r.text[:200]
    return proj_id


def _add_task(base_url, api_headers, proj_id, **body):
    body.setdefault("column", "todo")
    r = requests.post(
        f"{base_url}/api/projects/{proj_id}/tasks",
        headers=api_headers,
        json=body,
        timeout=10,
    )
    assert r.status_code == 200, r.text[:200]
    return r.json()


def _select_project(page, proj_id):
    """Open the Projects tab and select proj_id in the Kanban dropdown."""
    page.click('button[data-tab="projects"]')
    page.wait_for_selector("#kanban-board", state="visible", timeout=5_000)
    page.click("#kanban-panel .action-btn.ghost")  # refresh dropdown
    page.wait_for_function(
        f"""() => {{
            const sel = document.getElementById('kanban-project-select');
            return sel && Array.from(sel.options).some(o => o.value === {proj_id!r});
        }}""",
        timeout=8_000,
    )
    page.evaluate(
        f"() => {{ const s=document.getElementById('kanban-project-select'); s.value={proj_id!r}; s.dispatchEvent(new Event('change')); }}"
    )


def test_kanban_panel_inside_board_segment(signed_in_page, base_url, api_headers):
    """The relocated Kanban panel must be re-adopted inside the Board
    segment, and the segmented control must expose all four segments."""
    page = signed_in_page
    page.click('button[data-tab="projects"]')
    page.wait_for_selector("#projects-seg-board", state="visible", timeout=5_000)
    # kanban-panel is a descendant of the Board segment container.
    assert page.locator("#projects-seg-board #kanban-panel").count() == 1
    for seg in ("board", "backlog", "timeline", "docs"):
        assert page.locator(f'.proj-seg-btn[data-segment="{seg}"]').count() == 1
    # Additive columns present on the board.
    for col in ("backlog", "todo", "doing", "review", "done"):
        assert page.locator(f'.kanban-col[data-column="{col}"]').count() == 1


def test_segments_switch(signed_in_page, base_url, api_headers):
    """Clicking a segment button reveals its panel and hides the others."""
    page = signed_in_page
    page.click('button[data-tab="projects"]')
    page.wait_for_selector("#projects-seg-board", state="visible", timeout=5_000)

    page.click('.proj-seg-btn[data-segment="backlog"]')
    page.wait_for_selector("#projects-seg-backlog", state="visible", timeout=4_000)
    assert page.locator("#projects-seg-board").is_hidden()

    page.click('.proj-seg-btn[data-segment="timeline"]')
    page.wait_for_selector("#projects-seg-timeline", state="visible", timeout=4_000)

    page.click('.proj-seg-btn[data-segment="board"]')
    page.wait_for_selector("#projects-seg-board", state="visible", timeout=4_000)
    assert page.locator("#projects-seg-timeline").is_hidden()


def test_task_drawer_open_and_save(signed_in_page, base_url, api_headers):
    """A deferred single-click on a card opens the drawer; editing a field
    and saving persists through to the board."""
    proj_id = _mk_project(base_url, api_headers, "u3-drawer")
    _add_task(base_url, api_headers, proj_id, title="Drawer target", column="todo")
    try:
        page = signed_in_page
        _select_project(page, proj_id)
        page.wait_for_selector(
            '.kanban-col[data-column="todo"] .kanban-card', timeout=8_000
        )
        # Single-click the card title (bubbles to the card's kanban.card action).
        page.click('.kanban-col[data-column="todo"] .kanban-card .kanban-card-title')
        page.wait_for_selector("#proj-task-drawer", state="visible", timeout=4_000)
        page.wait_for_selector("#drw-title", timeout=4_000)
        # Edit title + set a priority, then save.
        page.fill("#drw-title", "Drawer edited")
        page.select_option("#drw-priority", "p1")
        page.click('[data-action="proj.drawer-save"]')
        # Drawer closes and the board reflects the new title.
        page.wait_for_selector("#proj-task-drawer", state="hidden", timeout=4_000)
        page.wait_for_function(
            """() => {
                const b = document.querySelector('.kanban-col[data-column="todo"] .kanban-col-body');
                return b && b.textContent.includes('Drawer edited');
            }""",
            timeout=6_000,
        )
        # Verify server-side persistence.
        tasks = requests.get(
            f"{base_url}/api/projects/{proj_id}/tasks", headers=api_headers, timeout=10
        ).json()
        assert any(
            t["title"] == "Drawer edited" and t.get("priority") == "p1" for t in tasks
        ), tasks
    finally:
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )


def test_dblclick_opens_edit_modal_not_drawer(
    signed_in_page, base_url, api_headers
):
    """Double-clicking a card must open the edit modal only — the deferred
    single-click drawer must be cancelled by the dblclick."""
    proj_id = _mk_project(base_url, api_headers, "u3-dbl")
    _add_task(base_url, api_headers, proj_id, title="Dbl target", column="todo")
    try:
        page = signed_in_page
        _select_project(page, proj_id)
        page.wait_for_selector(
            '.kanban-col[data-column="todo"] .kanban-card', timeout=8_000
        )
        page.dblclick(
            '.kanban-col[data-column="todo"] .kanban-card .kanban-card-title'
        )
        page.wait_for_selector("#kanban-modal", state="visible", timeout=4_000)
        # The drawer must NOT have opened.
        assert page.locator("#proj-task-drawer").is_hidden()
        # And the modal is in edit mode (title prefilled).
        assert page.input_value("#kanban-modal-title-input") == "Dbl target"
    finally:
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )


def test_timeline_unscheduled_lane(signed_in_page, base_url, api_headers):
    """The Timeline segment must render a dated lane for tasks with a due
    date and a dedicated Unscheduled lane for tasks without one."""
    proj_id = _mk_project(base_url, api_headers, "u3-tl")
    _add_task(
        base_url, api_headers, proj_id, title="Has due", column="todo",
        due_date="2099-01-15",
    )
    _add_task(base_url, api_headers, proj_id, title="No due", column="todo")
    try:
        page = signed_in_page
        _select_project(page, proj_id)
        page.click('.proj-seg-btn[data-segment="timeline"]')
        page.wait_for_selector(
            "#projects-seg-timeline .proj-tl-lane.unscheduled", timeout=6_000
        )
        # Scheduled lane carries the due date; unscheduled lane holds "No due".
        tl_text = page.locator("#projects-timeline-body").inner_text()
        assert "2099-01-15" in tl_text
        unsched = page.locator(".proj-tl-lane.unscheduled").inner_text()
        assert "No due" in unsched
    finally:
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )


def test_backlog_table_and_open(signed_in_page, base_url, api_headers):
    """The Backlog segment renders a grooming table; clicking a task title
    opens the drawer."""
    proj_id = _mk_project(base_url, api_headers, "u3-bk")
    _add_task(base_url, api_headers, proj_id, title="Groom me", column="backlog",
              priority="p0")
    try:
        page = signed_in_page
        _select_project(page, proj_id)
        page.click('.proj-seg-btn[data-segment="backlog"]')
        page.wait_for_selector(
            "#projects-backlog-body .proj-backlog-table", timeout=6_000
        )
        assert "Groom me" in page.locator("#projects-backlog-body").inner_text()
        page.click('[data-action="proj.backlog-open"]')
        page.wait_for_selector("#proj-task-drawer", state="visible", timeout=4_000)
        assert page.input_value("#drw-title") == "Groom me"
    finally:
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )


def test_docs_bind_and_edit_round_trip(signed_in_page, base_url, api_headers):
    """Docs segment: bind a context workspace (default root), then open the
    seeded index.md, edit it, save, and confirm the change round-trips."""
    proj_id = _mk_project(base_url, api_headers, "u3-docs")
    ws_name = f"proj-{proj_id}".lower()
    try:
        page = signed_in_page
        _select_project(page, proj_id)
        page.click('.proj-seg-btn[data-segment="docs"]')
        # Not bound yet → bind affordance.
        page.wait_for_selector('[data-action="proj.docs-bind"]', timeout=6_000)
        page.click('[data-action="proj.docs-bind"]')
        # After bind the tree lists the seeded markdown files.
        page.wait_for_selector(
            '.proj-docs-file[data-path="index.md"]', timeout=8_000
        )
        page.click('.proj-docs-file[data-path="index.md"]')
        page.wait_for_selector("#proj-docs-content", timeout=6_000)
        marker = f"U3 round-trip {int(time.time())}"
        page.fill("#proj-docs-content", f"# Edited\n\n{marker}\n")
        page.click('[data-action="proj.docs-save"]')
        # Confirm persisted via the workspace API.
        page.wait_for_timeout(600)
        r = requests.get(
            f"{base_url}/api/workspaces/{ws_name}/file",
            params={"path": "index.md"},
            headers=api_headers,
            timeout=10,
        )
        assert r.status_code == 200, r.text[:200]
        assert marker in r.json().get("content", "")
    finally:
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )
        # Best-effort workspace cleanup so we don't leave orphan registrations.
        requests.delete(
            f"{base_url}/api/workspaces/{ws_name}", headers=api_headers, timeout=5
        )
