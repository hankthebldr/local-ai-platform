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
    assert "window.ResearchFlow" in index_html_text
    assert 'id="enclave-flow5-js"' in index_html_text
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
    f5 = index_html_text[index_html_text.index('id="enclave-flow5-js"') :]
    assert "encl-wstep" in f5
    assert "window.SeedChip" in f5 and "sc.html(" in f5  # seed chips via the helper
    assert "AssetPeek.seedChat(null, id)" in f5


def test_flow5_reads_existing_research(index_html_text):
    f5 = index_html_text[index_html_text.index('id="enclave-flow5-js"') :]
    assert "research-output" in f5
    assert "window._lastResearch" in f5
