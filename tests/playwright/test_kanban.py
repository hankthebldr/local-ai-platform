"""
Kanban (Projects + Tasks inside the Workflow Index tab) — backend and
basic UI smoke. The backend endpoints live under /api/projects/{id}/tasks
and are append-only JSONL events resolved on read.
"""

from __future__ import annotations

import time

import requests


def test_projects_tasks_endpoints_exist(base_url, api_headers):
    """Tasks endpoints must round-trip create → list → patch → delete."""
    proj_id = f"kanban-smoke-{int(time.time() * 1000) & 0xFFFFFF:06x}"
    # Best-effort cleanup if a prior aborted run left it behind.
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )

    # 1. Create project
    r = requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"Kanban smoke {proj_id}"},
        timeout=10,
    )
    assert r.status_code in (
        200,
        201,
    ), f"project create failed: {r.status_code} {r.text[:200]}"

    try:
        # 2. List tasks — empty initially
        r = requests.get(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json() == []

        # 3. Create 3 tasks across 3 columns
        ids = []
        for col, title in (("todo", "First"), ("doing", "Second"), ("done", "Third")):
            r = requests.post(
                f"{base_url}/api/projects/{proj_id}/tasks",
                headers=api_headers,
                json={"title": title, "column": col, "labels": [col]},
                timeout=10,
            )
            assert r.status_code == 200, f"task create failed: {r.text[:200]}"
            ids.append(r.json()["id"])

        # 4. List shows all 3 in correct columns
        tasks = requests.get(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            timeout=10,
        ).json()
        assert len(tasks) == 3
        by_col = {t["column"] for t in tasks}
        assert by_col == {"todo", "doing", "done"}

        # 5. Move first task todo → doing
        r = requests.patch(
            f"{base_url}/api/projects/{proj_id}/tasks/{ids[0]}",
            headers=api_headers,
            json={"column": "doing"},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["column"] == "doing"

        # 6. Delete the task
        r = requests.delete(
            f"{base_url}/api/projects/{proj_id}/tasks/{ids[0]}",
            headers=api_headers,
            timeout=10,
        )
        assert r.status_code == 200
        tasks = requests.get(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            timeout=10,
        ).json()
        assert all(t["id"] != ids[0] for t in tasks)
        assert len(tasks) == 2

        # 7. Invalid column rejected
        r = requests.post(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            json={"title": "Bad column", "column": "invalid"},
            timeout=10,
        )
        assert r.status_code == 400

    finally:
        # Cleanup project
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )


def test_kanban_board_renders_in_workflow_index(signed_in_page):
    """The Kanban board markup must be visible when the Workflow Index
    tab is active."""
    page = signed_in_page
    page.click('button[data-tab="workflow-index"]')
    page.wait_for_selector("#tab-workflow-index", state="visible", timeout=5_000)
    page.wait_for_selector("#kanban-board", state="visible", timeout=5_000)
    cols = page.locator(".kanban-col[data-column]")
    assert cols.count() == 3
    labels = [c.locator(".kanban-col-title").inner_text().lower() for c in cols.all()]
    assert any("to do" in l for l in labels)
    assert any("in progress" in l for l in labels)
    assert any("done" in l for l in labels)


def test_kanban_project_select_populates(signed_in_page, base_url, api_headers):
    """The project dropdown must list every project /api/projects returns."""
    page = signed_in_page
    page.click('button[data-tab="workflow-index"]')
    page.wait_for_selector("#kanban-project-select", state="visible", timeout=5_000)
    page.wait_for_function(
        """() => {
            const sel = document.getElementById('kanban-project-select');
            return sel && sel.options.length >= 1;
        }""",
        timeout=10_000,
    )


def test_kanban_card_renders_on_drag(signed_in_page, base_url, api_headers):
    """End-to-end UI smoke: create a project + task via API, then select
    it in the Kanban head; the card must appear in the To do column."""
    proj_id = f"kanban-ui-{int(time.time() * 1000) & 0xFFFFFF:06x}"
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
    requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"Kanban UI {proj_id}"},
        timeout=10,
    )
    requests.post(
        f"{base_url}/api/projects/{proj_id}/tasks",
        headers=api_headers,
        json={"title": "Visible card", "column": "todo", "labels": ["smoke"]},
        timeout=10,
    )

    try:
        page = signed_in_page
        page.click('button[data-tab="workflow-index"]')
        page.wait_for_selector("#kanban-board", state="visible", timeout=5_000)

        # Click refresh first so the new project is in the dropdown.
        page.click("#kanban-panel .action-btn.ghost")  # refresh button
        page.wait_for_function(
            f"""() => {{
                const sel = document.getElementById('kanban-project-select');
                if (!sel) return false;
                return Array.from(sel.options).some(o => o.value === {proj_id!r});
            }}""",
            timeout=8_000,
        )
        # Select the project; Kanban.setActive fetches tasks and renders cards.
        page.evaluate(
            f"() => {{ const s=document.getElementById('kanban-project-select'); s.value={proj_id!r}; s.dispatchEvent(new Event('change')); }}"
        )
        page.wait_for_function(
            """() => {
                const body = document.querySelector('.kanban-col[data-column="todo"] .kanban-col-body');
                return body && body.querySelector('.kanban-card');
            }""",
            timeout=8_000,
        )
        text = page.locator(
            '.kanban-col[data-column="todo"] .kanban-col-body'
        ).inner_text()
        assert "Visible card" in text
    finally:
        requests.delete(
            f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
        )
