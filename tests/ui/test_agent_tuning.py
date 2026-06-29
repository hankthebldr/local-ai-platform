"""Regression for per-agent tuning + the seed affordance (node-bound chat).

Up/down votes in a node-bound chat become persisted per-agent behavior tuning
(keyed by step identity so it carries across workflows), applied as a
system-prompt guidance block when that agent runs. Plus an in-chat affordance
to seed the bound agent with context.
"""


def test_agent_tuning_module(index_html_text):
    assert "window.AgentTuning" in index_html_text
    fn = index_html_text[index_html_text.index("window.AgentTuning") :]
    # keyed by step id (semantic) for cross-workflow reuse
    assert "d.id || ('role:'" in fn
    # accumulates preferred / avoided exemplars
    assert "prefer" in fn and "avoid" in fn
    assert "function guidance" in fn or "guidance(nodeId)" in fn


def test_votes_feed_tuning_when_bound(index_html_text):
    # ChatRating.rate records tuning for the bound node.
    assert "AgentTuning.record(bn, kind, record.text)" in index_html_text


def test_tuning_applied_to_agent_prompt(index_html_text):
    # The engaged step's system prompt gets the tuning guidance appended.
    assert "AgentTuning.guidance(window._composerEngagedNodeId)" in index_html_text


def test_bind_header_shows_tuning_and_seed(index_html_text):
    assert 'id="step-engage-tuning"' in index_html_text
    assert 'onclick="composerSeedAgent()"' in index_html_text


def test_seed_appends_context_to_bound_node(index_html_text):
    fn = index_html_text[index_html_text.index("function composerSeedAgent") :]
    assert "[Seed context]" in fn
    assert "system_prompt" in fn
