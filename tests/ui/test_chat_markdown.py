"""Regression for rich-markdown chat output + code-block hand-off.

Chat replies now render through renderMarkdown (chat mode): fenced code blocks
get a header bar (language + Copy + "→ step" hand-off to the composer), tables,
blockquotes, inline code. Also pins the fix for the standalone-code-block
restore bug (the paragraph pass trimmed the ` CODE ` sentinel's spaces, so a
block on its own line never restored — affected plugins/exports too).
"""


def test_chat_renders_through_markdown(index_html_text):
    # The chat content path (renderCitations) now uses renderMarkdown chat mode.
    assert "window.renderMarkdown(text, { chat: true })" in index_html_text
    # Step-engage chat path too.
    assert "window.renderMarkdown(content, { chat: true })" in index_html_text


def test_chat_code_handoff_module(index_html_text):
    assert "window.ChatCode" in index_html_text
    assert "ChatCode.copy(" in index_html_text
    assert "ChatCode.toStep(" in index_html_text
    # → step pins the code as a workflow step (reuses the pin path).
    assert (
        "window._enclavePins"
        in index_html_text[index_html_text.index("window.ChatCode") :]
    )


def test_markdown_chat_code_bar(index_html_text):
    assert ".md-codewrap" in index_html_text
    assert ".md-codebar" in index_html_text
    assert ".md-codebtn" in index_html_text
    # The chat code block emits the language label + the two action buttons.
    assert "md-codelang" in index_html_text


def test_markdown_code_restore_is_space_independent(index_html_text):
    # The bug fix: unique CODEBLOCK sentinel + bare restore + paragraph passthrough.
    assert "CODEBLOCK${codeBlocks.length - 1}" in index_html_text
    assert "/CODEBLOCK(\\d+)/g" in index_html_text
    assert "/^CODEBLOCK\\d+$/.test(t)" in index_html_text


def test_markdown_tables_and_quotes(index_html_text):
    assert ".md-table" in index_html_text
    assert ".md-quote" in index_html_text


def test_nonchat_markdown_unchanged(index_html_text):
    # Plugins/exports call renderMarkdown(text) with no chat flag → plain <pre>.
    assert (
        "renderMarkdown(s.body" in index_html_text
        or "renderMarkdown(text)" in index_html_text
    )
