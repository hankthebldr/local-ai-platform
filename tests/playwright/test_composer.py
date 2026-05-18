"""
Composer workbench — Agents / Skills / Plugins / MCPs panes load the OOTB
content shipped with the repo. Regression guard for "the Composer is empty
even though the backend has 3 agents and 3 plugins" — which has happened
twice during the build-out.
"""

from __future__ import annotations


def _wait_workbench(page, timeout: int = 15_000):
    """The workbench fires three parallel fetches at Composer init; wait
    until all five panes have rendered something other than 'Loading…'."""
    page.wait_for_function(
        """() => {
            const panes = ['agents', 'skills', 'plugins', 'mcps'];
            return panes.every(p => {
                const el = document.getElementById('bench-' + p + '-list');
                if (!el) return false;
                return !el.textContent.includes('Loading…');
            });
        }""",
        timeout=timeout,
    )


def test_workbench_agents_pane_lists_ootb_xql_agents(signed_in_page):
    """Drag-into-canvas Agents pane must list the 3 OOTB XQL agents.

    The agents load asynchronously via /api/agents; wait specifically for
    all 3 cards to render rather than reading text once and asserting
    against an in-flight snapshot."""
    page = signed_in_page
    page.click('.workbench-tab[data-bench="agents"]')
    _wait_workbench(page)
    # Wait until 3 card elements are in the DOM (load finished, not just kicked off).
    page.wait_for_function(
        """() => {
            const list = document.getElementById('bench-agents-list');
            if (!list) return false;
            return list.querySelectorAll('.workbench-item').length >= 3;
        }""",
        timeout=15_000,
    )
    text = page.locator("#bench-agents-list").inner_text()
    # Match agent NAMES as they appear in agents/*.yaml `name:` field.
    # The xsiam-analyst agent's display name is "XSIAM Data Model Analyst".
    for expected in (
        "XSIAM Data Model Analyst",
        "XDM Schema Navigator",
        "XQL Data Model Rule Engineer",
    ):
        assert (
            expected in text
        ), f"workbench Agents pane missing {expected!r}; got: {text[:400]}"
    cards = page.locator("#bench-agents-list .workbench-item")
    assert cards.count() >= 3, f"expected ≥3 draggable agent cards, got {cards.count()}"
    for i in range(cards.count()):
        assert (
            cards.nth(i).get_attribute("draggable") == "true"
        ), f"agent card #{i} is not draggable; drag-onto-canvas spawn will not work"


def test_workbench_skills_pane_lists_xdm_toolkit_skills(signed_in_page):
    """xdm-toolkit ships with 2 skills — they should appear in the Skills pane."""
    page = signed_in_page
    page.click('.workbench-tab[data-bench="skills"]')
    _wait_workbench(page)
    pane = page.locator("#bench-skills-list")
    # Skills are markdown bodies attached to plugins; xdm-toolkit ships two.
    # Sanity check: pane is not empty.
    assert (
        "No skills" not in pane.inner_text()
    ), "Skills pane reports empty despite xdm-toolkit shipping with skills"


def test_workbench_plugins_pane_lists_xdm_toolkit(signed_in_page):
    """xdm-toolkit plugin ships 3 tools — Plugins pane should surface them."""
    page = signed_in_page
    page.click('.workbench-tab[data-bench="plugins"]')
    _wait_workbench(page)
    text = page.locator("#bench-plugins-list").inner_text()
    assert (
        "xdm-toolkit" in text or "XDM" in text
    ), f"Plugins pane missing xdm-toolkit; got: {text[:200]}"


def test_workbench_mcps_pane_renders_even_when_empty(signed_in_page):
    """MCP servers list is empty by default. The pane must still render an
    empty-state message, not stay on 'Loading…' forever."""
    page = signed_in_page
    page.click('.workbench-tab[data-bench="mcps"]')
    _wait_workbench(page)
    text = page.locator("#bench-mcps-list").inner_text()
    assert "Loading" not in text


def test_composer_canvas_is_full_width(signed_in_page):
    """The composer-right rail was removed; the canvas must now stretch
    into the freed column."""
    page = signed_in_page
    grid = page.locator(".composer-grid").first
    cols = page.evaluate(
        "(el) => getComputedStyle(el).gridTemplateColumns",
        grid.element_handle(),
    )
    # Expect two tracks (left workbench + canvas), not three.
    assert (
        len(cols.split()) == 2
    ), f".composer-grid must be a 2-column layout; got: {cols}"


def test_step_config_relocated_below_chat_dock(signed_in_page):
    """Step Config must live below the agent-chat-dock now, not in a right rail."""
    page = signed_in_page
    step_config = page.locator("#step-config-panel")
    assert step_config.count() == 1, "Step Config panel missing or duplicated"
    # Its IDs must survive for the click-a-node handler.
    assert page.locator("#df-config-panel").count() == 1
    assert page.locator("#df-config-title").count() == 1


def test_system_strip_in_chat_dock_shows_host_values(signed_in_page):
    """The relocated System strip lives in the chat dock header and must
    surface the env-injected host hardware (ENCLAVE_HOST_* vars)."""
    page = signed_in_page
    # Wait for the system poller to fire at least once.
    page.wait_for_function(
        """() => {
            const cores = document.getElementById('cpu-cores');
            return cores && cores.textContent.trim() !== '--';
        }""",
        timeout=10_000,
    )
    cores_text = page.locator("#cpu-cores").inner_text()
    ram_text = page.locator("#mem-detail").inner_text()
    # Cores should be the host's physical-cpu count (≥4 on any dev box).
    assert any(
        c.isdigit() for c in cores_text
    ), f"cpu-cores not numeric: {cores_text!r}"
    cores_val = int("".join(c for c in cores_text if c.isdigit()))
    assert cores_val >= 4, f"cpu-cores={cores_val} — likely VM slice, not host"
    # RAM total should be the host GB (look for any 2-digit GB number).
    assert "GB" in ram_text, f"mem-detail missing GB unit: {ram_text!r}"
