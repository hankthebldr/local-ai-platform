"""Regression for node-bound chat (the chat-led composer's core interaction).

Selecting a canvas node binds the chat to THAT node's agent; the chat opens
already bound to the workflow's starting node; and the chat's model selector
configures the bound node ("chat settings are node config"). Built on the
existing step-engage primitive (composerEnterStepEngage / /api/workflows/test-step).
"""

import re


def test_bind_indicator_shows_agent(index_html_text):
    # The engage badge reads as "chatting with <node> · role @ model".
    assert 'id="step-engage-badge"' in index_html_text
    assert 'id="step-engage-id"' in index_html_text
    assert 'id="step-engage-meta"' in index_html_text
    assert "Chatting with" in index_html_text


def test_node_selection_binds_chat(index_html_text):
    # Selecting a node engages it (binds the chat).
    assert "composerEnterStepEngage(id)" in index_html_text
    # Engage populates the agent meta (role @ model).
    assert re.search(
        r"step-engage-meta.*role.*model|metaEl\.textContent = '· '",
        index_html_text,
        re.S,
    )


def test_chat_starts_on_starting_node(index_html_text):
    # composerLoadDefinition auto-engages the first/root step.
    cld = index_html_text[index_html_text.index("function composerLoadDefinition") :]
    assert "firstStep" in cld and "composerEnterStepEngage(firstNodeId)" in cld


def test_chat_model_configures_bound_node(index_html_text):
    # The chat model selector writes back to the bound node.
    assert 'onchange="onChatModelChanged()"' in index_html_text
    fn = index_html_text[index_html_text.index("function onChatModelChanged") :]
    assert "_composerEngagedNodeId" in fn
    assert "dfUpdateNodeData(nodeId, 'model', model)" in fn
