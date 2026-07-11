"""Static-markup regression for flow 5: research → context → agent.

The 5th storyboarded flow. Turns existing deep-research output into a reusable
agent (research = the context bundle, carried into the agent), verified by a
seeded chat. Pins the wizard, the 4 phases, reuse of the real agent-generate/
save endpoints, and the canonical atoms (WizardStepper, SeedChip, seedChat).
"""


def test_flow5_markup_present(index_soup):
    assert index_soup.find(id="rc-backdrop") is not None, "flow-5 modal missing"
    assert index_soup.find(id="rc-phases") is not None, "phase rail missing"
    assert index_soup.find(id="rc-body") is not None
    assert index_soup.find(id="rc-actions") is not None


def test_flow5_module_and_entry_point(index_html_text):
    assert (
        "window.ResearchFlow" in index_html_text
    )  # module code (phase-2: now in js/main.js)
    # Entry point lives in the research results panel.
    assert "Build an agent from this" in index_html_text
    assert "ResearchFlow.open()" in index_html_text


def test_flow5_four_phases(index_html_text):
    assert "['Research', 'Context', 'Agent', 'Verify']" in index_html_text


def test_flow5_reuses_real_agent_endpoints(index_html_text):
    # Agent generated FROM the research context via the real endpoints.
    assert "/api/agents/generate" in index_html_text
    assert "/api/agents/generate/save" in index_html_text
    assert "include_source_as_context: true" in index_html_text


def test_flow5_reuses_canonical_atoms(index_html_text):
    # WizardStepper (encl-wstep), SeedChip, and verify-by-seedChat.
    # phase-2 moved flow5 out of its <script id> wrapper into js/main.js; anchor the
    # region on its stable block comment instead of the (now-gone) wrapper id.
    f5 = index_html_text[index_html_text.index("Flow 5 — research") :]
    assert "encl-wstep" in f5
    assert "window.SeedChip" in f5 and "sc.html(" in f5  # seed chips via the helper
    assert "AssetPeek.seedChat(null, id)" in f5


def test_flow5_reads_existing_research(index_html_text):
    # phase-2 moved flow5 out of its <script id> wrapper into js/main.js; anchor the
    # region on its stable block comment instead of the (now-gone) wrapper id.
    f5 = index_html_text[index_html_text.index("Flow 5 — research") :]
    assert "research-output" in f5
    assert "window._lastResearch" in f5


# ── RX-1: stateful research session — thread + two-column reading layout ────


def test_rx1_session_two_column_markup(index_soup):
    # The reading session surface: LEFT thread, RIGHT reading view.
    assert index_soup.find(id="research-session") is not None, "session wrapper missing"
    assert index_soup.find(id="research-thread") is not None, "thread column missing"
    assert index_soup.find(id="research-surface") is not None, "reading surface missing"
    # The legacy per-sub-question output MUST stay alive (only-add).
    assert index_soup.find(id="research-output") is not None


def test_rx1_followup_input_is_delegated_not_inline(index_soup):
    inp = index_soup.find(id="research-followup-input")
    assert inp is not None, "sticky follow-up input missing"
    # No new inline on*= handler on the input (data-action delegation only).
    inline = [a for a in (inp.attrs or {}) if a.startswith("on")]
    assert not inline, f"follow-up input carries inline handler(s): {inline}"
    btn = index_soup.find(id="research-followup-btn")
    assert btn is not None and btn.get("data-action") == "research.followup"


def test_rx1_followup_wiring_in_js(index_html_text):
    # The follow-up posts to the stateful endpoint and renders reading cards.
    assert "/api/research/followup" in index_html_text
    assert "renderResearchSession" in index_html_text
    assert "submitResearchFollowup" in index_html_text
    assert "'research.followup'" in index_html_text


def test_rx1_web_search_off_by_default(index_soup):
    # The web-search opt-in exists and is UNCHECKED by default (privacy).
    web = index_soup.find(id="research-followup-web")
    assert web is not None, "web-search opt-in missing"
    assert web.get("checked") in (None, False), "web search must default OFF"


def test_rx1_reading_surface_is_full_width(index_html_text):
    # No letterbox on the reading body — the report reads like a page.
    assert ".research-reading-body { max-width: none;" in index_html_text
