"""Regression for S1 (Composer canvas-dominant) — the completion slice.

S0 extracted the chat dock into #tab-chat; S1 finishes the Composer as a
canvas-first single surface. This pins the two S1 repairs on top of the
S0 layout tests (test_composer_vertical_layout / test_composer_focus_mode):

1. G5 quarantine — setWfMode() drove legacy Catalog-runner chrome
   (#wf-mode-run/#wf-mode-compose/#wf-composer*) that no longer exists in
   the DOM; unguarded getElementById chains there turned the Composer
   "Run ▶" pivot (dfRunWorkflow → setWfMode('run')) into a TypeError.
   The function must survive (window-global parity) but null-guard every
   legacy anchor.

2. Ollama-down reach — the Promote (.bs-dispatch) / Pin (.msg-pin-btn)
   affordances moved to #tab-chat with the dock, so the ollama-down
   disable must land on #agent-chat-dock too, not only #composer-split.
"""


def test_setwfmode_quarantined_null_safe(index_html_text):
    # The legacy chrome is gone from the markup…
    for retired_id in ("wf-mode-run", "wf-mode-compose", "wf-composer-controls"):
        assert f'id="{retired_id}"' not in index_html_text, (
            f"legacy Catalog runner chrome #{retired_id} resurfaced"
        )
    # …so no caller may dereference it unguarded (the old crash shape).
    for crash in (
        "getElementById('wf-mode-run').classList",
        "getElementById('wf-mode-compose').classList",
        "getElementById('wf-composer-controls').style",
        "getElementById('wf-composer').style",
    ):
        assert crash not in index_html_text, f"unguarded legacy deref survives: {crash}"
    # The quarantined function itself survives (window-global parity).
    assert "function setWfMode(" in index_html_text


def test_run_pivot_still_calls_setwfmode(index_html_text):
    # dfRunWorkflow's post-save pivot keeps its call — quarantine means
    # null-safe, not deleted.
    assert "setWfMode('run')" in index_html_text


def test_ollama_down_reaches_chat_dock(index_html_text):
    # CSS: the disable selector must scope to the relocated dock.
    assert ".agent-chat-dock.ollama-down .bs-dispatch" in index_html_text
    assert ".agent-chat-dock.ollama-down .msg-pin-btn" in index_html_text
    # JS: the poller stamps the class on the dock as well as the split.
    assert "getElementById('agent-chat-dock')" in index_html_text
    assert "_dock.classList.toggle('ollama-down'" in index_html_text
