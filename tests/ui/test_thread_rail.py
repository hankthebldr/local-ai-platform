"""Static-markup regression for the session-scoped thread switcher.

Lets the operator juggle multiple conversations. Pins the bar markup, the
module, and that switching snapshots/restores the chat (history + rendered
messages + pins) lazily — without modifying sendMessage or the chat renderer.
"""


def test_thread_bar_markup_present(index_soup):
    assert index_soup.find(id="thread-bar") is not None, "thread bar missing"
    assert index_soup.find(id="thread-switch") is not None, "switch button missing"
    assert index_soup.find(id="thread-active-name") is not None, "active name missing"
    assert index_soup.find(id="thread-menu") is not None, "thread menu missing"


def test_thread_module_present(index_html_text):
    assert "window.Threads" in index_html_text
    assert 'id="enclave-threads-js"' in index_html_text
    assert 'id="enclave-threads-styles"' in index_html_text


def test_thread_actions_wired(index_html_text):
    assert "Threads.toggleMenu()" in index_html_text
    assert "Threads.create()" in index_html_text
    assert "Threads.pick(" in index_html_text
    assert "Threads.rename(" in index_html_text


def test_switch_snapshots_and_restores_chat_state(index_html_text):
    # Snapshot/restore must cover history + rendered messages + pins.
    assert "_snapshot" in index_html_text
    assert "_restore" in index_html_text
    assert "typeof chatHistory" in index_html_text  # guarded history access
    assert "_enclavePins" in index_html_text  # pins travel with the thread
    assert "getElementById('messages')" in index_html_text  # rendered messages


def test_thread_switch_is_additive_not_destructive(index_html_text):
    # Must mutate the const chatHistory in place (length=0 + push), never
    # reassign it, and never touch sendMessage.
    assert "chatHistory.length = 0" in index_html_text
    assert "Array.prototype.push.apply(chatHistory" in index_html_text
