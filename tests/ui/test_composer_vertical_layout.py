"""Regression for the S0 separated layout: Chat tab + canvas-dominant Composer.

Re-anchored for S0 (chat extraction): the chat-top / canvas-bottom vertical
split (with its drag divider and --chat-frac height fraction) was retired.
The agent-chat dock now lives VERBATIM in its own #tab-chat, and the
Composer split is a canvas-first single column (canvas · workstream strip).
This pins the new placement, the dock's verbatim move (IDs intact), the
divider's removal, and the data-action nav entry for the Chat tab.
"""

import re


def test_split_is_canvas_first_single_column(index_html_text):
    m = re.search(r"\.composer-split\s*\{[^}]*\}", index_html_text, re.S)
    assert m, ".composer-split rule not found"
    block = m.group(0)
    assert (
        "grid-template-rows: minmax(0, 1fr) auto" in block
    ), "split is not canvas-first (canvas row should lead and flex)"
    assert (
        "grid-template-columns: minmax(0, 1fr)" in block
    ), "split should be a single column"


def test_canvas_top_workstream_bottom_placement(index_html_text):
    assert "> .composer-grid        { grid-row: 1;" in index_html_text  # canvas leads
    assert (
        "> .composer-workstream  { grid-row: 2;" in index_html_text
    )  # workstream strip below


def test_chat_dock_moved_verbatim_into_chat_tab(index_soup):
    tab = index_soup.find(id="tab-chat")
    assert tab is not None, "#tab-chat missing"
    dock = tab.find(id="agent-chat-dock")
    assert dock is not None, "#agent-chat-dock not inside #tab-chat"
    # Verbatim move: the load-bearing IDs (poller targets, threads, engage
    # badge, pins, prompt) ride along unchanged and stay unique.
    for anchor in (
        "thread-bar",
        "chat-system-strip",
        "messages",
        "step-engage-badge",
        "nba-container",
        "pins-meter",
        "prompt",
        "send-btn",
    ):
        assert dock.find(id=anchor) is not None, f"#{anchor} missing from moved dock"
    # And the dock is OUT of the Composer tab.
    dash = index_soup.find(id="tab-dashboard")
    assert dash.find(id="agent-chat-dock") is None, "dock still in #tab-dashboard"


def test_divider_retired(index_soup, index_html_text):
    assert index_soup.find(id="composer-divider") is None, "divider should be gone"
    assert "cursor: row-resize" not in index_html_text
    # The persisted split fraction died with the divider.
    assert "--chat-frac" not in index_html_text
    assert "enclave.composer.split" not in index_html_text


def test_chat_nav_button_uses_data_action(index_soup):
    btn = index_soup.select_one('.tab-nav .tab-btn[data-tab="chat"]')
    assert btn is not None, "Chat nav button missing"
    assert btn.get("data-action") == "switch-tab", "Chat nav must use data-action"
    assert btn.get("data-tab-target") == "chat"
    assert btn.get("onclick") is None, "Chat nav button must not add an inline handler"


def test_chat_tab_fills_viewport(index_html_text):
    # The extracted dock keeps the full-height transcript behaviour it had
    # inside the split (no fallback to the standalone 400px clamp).
    m = re.search(
        r"#tab-chat \.agent-chat-dock \.chat-messages\s*\{[^}]*max-height:\s*none",
        index_html_text,
        re.S,
    )
    assert m is not None, "chat transcript no longer flexes to full height"
