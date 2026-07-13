"""Static-markup regression for the composer's full-screen canvas path.

Re-anchored for S0 (chat extraction): the 3-mode segmented control
(chat / canvas / focus) was retired when the chat dock moved to its own
#tab-chat — the Composer is canvas-dominant now, and "focus" survives
independently via the canvas fullscreen toggle (#canvas-fullscreen-btn →
dfToggleFullscreen → .composer-canvas-panel.is-fullscreen). This pins the
surviving control, its wiring + CSS contract, and the retirement invariant
(no ComposerSplit mode API left anywhere in the served corpus).
"""


def test_fullscreen_button_present(index_soup):
    btn = index_soup.find(id="canvas-fullscreen-btn")
    assert btn is not None, "#canvas-fullscreen-btn missing"
    assert btn.get("aria-label") is not None, "fullscreen button missing aria-label"


def test_fullscreen_button_wired_to_toggle(index_html_text):
    assert "dfToggleFullscreen()" in index_html_text
    # Esc exits fullscreen (the "no way back" fix lives here now).
    assert "_dfFullscreenEscBound" in index_html_text


def test_fullscreen_css_contract(index_html_text):
    # The panel-level fullscreen class drives the full-bleed canvas.
    assert ".composer-canvas-panel.is-fullscreen" in index_html_text
    assert ".composer-canvas-panel.is-fullscreen #drawflow-canvas" in index_html_text


def test_mode_toggle_fully_retired(index_html_text):
    # S0: zero setMode callers or definitions may survive anywhere in the
    # served corpus, and the mode buttons must be gone from the markup.
    assert "setMode(" not in index_html_text
    for retired_id in (
        "composer-mode-chat",
        "composer-mode-canvas",
        "composer-mode-focus",
        "composer-fmode-chat",
        "composer-fmode-canvas",
        "composer-fmode-focus",
    ):
        assert f'id="{retired_id}"' not in index_html_text, (
            f"retired mode button #{retired_id} resurfaced"
        )
