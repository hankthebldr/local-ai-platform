"""Static-markup regression for the Cmd/Ctrl-K command palette (window.Shortcuts).

The palette is shipped but untested. These pin: the module, both modifier keys,
the fail-silent-in-text-input guard, the tab-jump action, and the trigger button.
"""


def test_shortcuts_module_defined(index_html_text):
    # phase-2 U2: Shortcuts carved to core/shortcuts.js (ES module) + window-bridged.
    assert "export const Shortcuts = (function" in index_html_text
    assert "window.Shortcuts = Shortcuts" in index_html_text


def test_shortcuts_toggle_exists(index_html_text):
    assert "Shortcuts.toggle()" in index_html_text


def test_cmd_and_ctrl_k_both_handled(index_html_text):
    # Mac (metaKey) and Linux/Win (ctrlKey) both open the palette.
    assert "metaKey" in index_html_text
    assert "ctrlKey" in index_html_text
    assert "'k'" in index_html_text or '"k"' in index_html_text


def test_shortcuts_fail_silent_in_text_inputs(index_html_text):
    # A guard must exist so typing 'k' in a field never triggers the palette.
    assert "_isTextTarget" in index_html_text


def test_shortcuts_drive_tab_navigation(index_html_text):
    # The palette / g-sequence jumps tabs via switchTab.
    assert "switchTab(" in index_html_text
