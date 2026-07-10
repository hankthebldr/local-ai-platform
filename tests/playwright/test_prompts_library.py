"""
Prompts library — the read-only Role Library (Research) was promoted to a
first-class Library object: roles AND templates, editable, renderable through
the frozen composer. This guards the new #tab-prompts tab: reachable from the
Library nav group, lists the seeded roles/templates, and renders a live preview.
"""

from __future__ import annotations


def test_prompts_tab_in_library_nav(signed_in_page):
    page = signed_in_page
    btn = page.locator('.tab-nav button[data-tab="prompts"]')
    assert btn.count() == 1, "Prompts tab missing from the nav"
    assert "prompt" in btn.inner_text().lower()


def test_prompts_tab_lists_seeded_roles_and_templates(signed_in_page):
    page = signed_in_page
    page.click('.tab-nav button[data-tab="prompts"]')
    page.wait_for_selector("#tab-prompts", state="visible", timeout=5_000)
    # Wait for the async /api/prompts fetch to populate the list.
    page.wait_for_function(
        """() => {
            const el = document.getElementById('prompts-list');
            return el && el.querySelectorAll('[data-action="prompts.select"]').length > 0;
        }""",
        timeout=15_000,
    )
    text = page.locator("#prompts-list").inner_text().lower()
    assert "roles" in text and "templates" in text, f"group headers missing: {text[:200]}"
    assert "python developer" in text, f"seeded role not listed: {text[:300]}"


def test_prompts_select_and_render_preview(signed_in_page):
    page = signed_in_page
    page.click('.tab-nav button[data-tab="prompts"]')
    page.wait_for_selector("#tab-prompts", state="visible", timeout=5_000)
    # Select the python_developer role.
    row = page.locator('#prompts-list [data-action="prompts.select"][data-key="role/python_developer"]')
    row.wait_for(state="visible", timeout=15_000)
    row.click()
    # Detail shows the body + the render button.
    page.wait_for_selector('#prompts-detail [data-action="prompts.render"]', state="visible", timeout=5_000)
    page.click('#prompts-detail [data-action="prompts.render"]')
    # Render output surfaces the composed SYSTEM/USER preview.
    page.wait_for_function(
        """() => {
            const el = document.getElementById('prompts-render-out');
            return el && !el.hidden && el.innerText.toUpperCase().includes('SYSTEM');
        }""",
        timeout=15_000,
    )
