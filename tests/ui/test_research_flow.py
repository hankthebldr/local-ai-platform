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


# ── RX-2: actionable results, Obsidian store, shared exploratory node rail ───


def test_rx2_store_subnav_present_and_delegated(index_soup):
    nav = index_soup.find(class_="research-subnav")
    assert nav is not None, "Store subnav missing"
    btns = nav.find_all("button")
    views = {b.get("data-view") for b in btns}
    assert {"explore", "store"} <= views
    for b in btns:
        assert b.get("data-action") == "research.subnav"
        # No new inline handlers on the subnav buttons.
        assert not [a for a in (b.attrs or {}) if a.startswith("on")]


def test_rx2_store_panel_and_tree_markup(index_soup):
    assert index_soup.find(id="research-store-panel") is not None, "store panel missing"
    assert index_soup.find(id="research-store-tree") is not None, "store tree missing"
    assert index_soup.find(id="research-store-preview") is not None, "store preview missing"
    # Refresh is delegated, not inline.
    refresh = index_soup.select_one('[data-action="research.store-refresh"]')
    assert refresh is not None


def test_rx2_node_rail_mount_present(index_soup):
    mount = index_soup.find(id="research-node-rail")
    assert mount is not None, "node-rail mount missing from the session-detail panel"
    # The legacy per-node action footer stays alive (only-add).
    assert index_soup.find(id="session-detail-actions") is not None


def test_rx2_shared_rail_module_is_canonical(index_html_text):
    # RX-2 owns the canonical shared node-rail; the pane-guard is declared once.
    assert "shell/context-node-rail.js" in index_html_text
    assert "ContextNodeRail" in index_html_text
    # The research rail REGISTERS into the shared module (kind:'research-node'),
    # it does not reimplement rail plumbing.
    assert "research/research-node-rail.js" in index_html_text
    assert "ContextNodeRail.register('research-node'" in index_html_text
    # The single pane-guard drives the rail through activate().
    assert "ContextNodeRail.activate('research-node'" in index_html_text


def test_rx2_node_rail_verbs_wired(index_html_text):
    for action in (
        "'research.node-read'",
        "'research.compare-node'",
        "'research.build-upon'",
        "'research.graph-walk'",
    ):
        assert action in index_html_text, f"node-rail verb {action} not wired"
    # The exploratory endpoints are the operator-triggered POSTs.
    assert "/api/research/compare-node" in index_html_text
    assert "/api/research/graph-walk" in index_html_text


def test_rx2_actionable_result_rows(index_html_text):
    # Per-source/per-result actions — promote / save / cite — data-action only.
    for action in (
        "'research.save-source'",
        "'research.cite'",
        "'research.promote-artifact'",
    ):
        assert action in index_html_text, f"result action {action} not wired"
    assert "/api/research/save-source" in index_html_text
    # Cite drops an Obsidian-style wikilink into the follow-up input.
    assert "[[source:" in index_html_text


def test_rx2_store_reuses_skills_tree_grammar(index_html_text):
    # The store browser rides the LB3 .skills-tree grammar (no bespoke tree CSS).
    assert "research/research-store.js" in index_html_text
    assert "skills-tree-file" in index_html_text


def test_rx2_store_active_hides_explore_siblings(index_html_text):
    # One CSS rule (only-add) hides every explore sibling in the Store view.
    assert "#tab-research.store-active" in index_html_text
