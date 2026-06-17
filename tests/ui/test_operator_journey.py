"""Static-markup regression for the operator-journey surfaces:
the topbar adoption ladder + the next-best-action nudges (window.OpPath).

These are new in the chat-led redesign. Pins the markup anchors, the five
honest ladder stages, the nudge engine, and that state is derived from REAL
signals (chat history, canvas nodes, run/workflow existence) — not invented
globals — with defensive typeof guards.
"""


def test_journey_markup_anchors_present(index_soup):
    assert index_soup.find(id="op-path-bar") is not None, "ladder bar missing"
    assert index_soup.find(id="op-path-stages") is not None, "ladder stages missing"
    assert index_soup.find(id="op-path-count") is not None, "ladder count missing"
    assert index_soup.find(id="op-path-pop") is not None, "ladder popover missing"
    assert index_soup.find(id="nba-container") is not None, "nudge container missing"


def test_journey_module_and_css_present(index_html_text):
    assert "window.OpPath" in index_html_text
    assert 'id="enclave-journey-js"' in index_html_text
    assert 'id="enclave-journey-styles"' in index_html_text
    assert ".op-stage.done" in index_html_text
    assert ".op-stage.hot" in index_html_text


def test_ladder_has_five_honest_stages(index_html_text):
    for label in (
        "Seed a chat",
        "Scaffold a plan",
        "Run it",
        "Save the workflow",
        "Schedule on the fleet",
    ):
        assert label in index_html_text, f"ladder stage '{label}' missing"
    # The fleet stage is honestly marked future, not faked as available.
    assert "future: true" in index_html_text


def test_journey_reads_real_signals_defensively(index_html_text):
    # Derives state from actual app globals/endpoints, with typeof guards.
    assert "typeof chatHistory" in index_html_text
    assert "typeof dfNodeData" in index_html_text
    assert "/api/workflows/runs?limit=1" in index_html_text
    assert "fetch('/api/workflows')" in index_html_text


def test_nudges_are_dismissible_and_action_real_handlers(index_html_text):
    # The three nudges and their persistence + real action wiring.
    for key in ("'scaffold'", "'run'", "'save'"):
        assert key in index_html_text
    assert "enclave.nba.dismissed" in index_html_text  # localStorage persistence
    assert "dfRunWorkflowFromComposer" in index_html_text  # real run handler
    assert ".bs-dispatch" in index_html_text  # real scaffold affordance
