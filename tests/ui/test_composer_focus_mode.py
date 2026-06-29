"""Static-markup regression for the third composer layout mode: 'focus'.

The fluid layout is a 3-mode segmented control (chat / canvas / focus). The
Playwright suite covers chat + canvas; focus had no coverage. This pins the
button, its setMode wiring, and the full-bleed-canvas CSS contract.
"""


def test_focus_mode_button_present(index_soup):
    btn = index_soup.find(id="composer-mode-focus")
    assert btn is not None, "#composer-mode-focus button missing"
    assert btn.get("aria-pressed") is not None, "focus button missing aria-pressed"


def test_focus_button_wired_to_setmode(index_html_text):
    assert "ComposerSplit.setMode('focus')" in index_html_text


def test_focus_mode_css_contract(index_html_text):
    # The full-bleed-canvas rule and its consequences.
    assert ".composer-split.mode-focus {" in index_html_text
    # Canvas takes the top row; divider + workstream disappear.
    assert (
        ".composer-split.mode-focus > #composer-divider     { display: none; }"
        in index_html_text
        or ".composer-split.mode-focus > #composer-divider" in index_html_text
    )
    assert ".composer-split.mode-focus > .composer-workstream" in index_html_text
    # Chat docks below the canvas (grid-row: 2).
    assert ".composer-split.mode-focus > .agent-chat-dock" in index_html_text


def test_all_three_modes_offered(index_html_text):
    for mode in ("chat", "canvas", "focus"):
        assert f"ComposerSplit.setMode('{mode}')" in index_html_text
