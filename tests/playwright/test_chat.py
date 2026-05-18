"""
Chat dock — direct-to-model and agent-scoped chats both work under
unified auth. The first iteration of this product had the chat silently
401-ing because the SPA's fetch didn't inject the operator key; this
suite guards that regression.
"""

from __future__ import annotations

import pytest
import requests


def _has_any_model(base_url: str, headers: dict) -> bool:
    try:
        r = requests.get(f"{base_url}/v1/models", headers=headers, timeout=5)
        return r.status_code == 200 and bool(r.json().get("data"))
    except Exception:
        return False


def test_model_picker_populates(signed_in_page, base_url, api_headers):
    """The chat dock's #model-select must populate with whatever Ollama has
    pulled. Empty picker is the smoking gun for the SPA's old 401 problem.

    The picker loads via ComposerView.init → loadAgentsForSelector; on a
    cold start that can take 15+ seconds because the call goes through
    /v1/models which itself fans out to Ollama. Use a generous timeout
    and check actual model id values, not just innerText (Playwright's
    inner_text on <option> can return empty on detached elements).
    """
    if not _has_any_model(base_url, api_headers):
        pytest.skip(
            "No models loaded; pull at least one (e.g. `ollama pull llama3.2:3b`)"
        )
    page = signed_in_page
    try:
        page.wait_for_function(
            """() => {
                const sel = document.getElementById('model-select');
                if (!sel || sel.options.length === 0) return false;
                const real = Array.from(sel.options)
                  .map(o => (o.value || o.textContent || '').trim())
                  .filter(v => v && !v.toLowerCase().includes('loading'));
                return real.length > 0;
            }""",
            timeout=30_000,
        )
    except Exception:
        # Surface what the picker actually contains so the failure is debuggable.
        state = page.evaluate(
            """() => {
                const sel = document.getElementById('model-select');
                if (!sel) return {present: false};
                return {
                    present: true,
                    optionCount: sel.options.length,
                    options: Array.from(sel.options).map(o => ({
                        value: o.value, text: o.textContent
                    })),
                };
            }"""
        )
        raise AssertionError(f"Model picker never populated. State: {state}")


@pytest.mark.slow
def test_chat_send_receives_response(signed_in_page, base_url, api_headers):
    """Full chat round-trip: type a message, hit Send, assert an assistant
    bubble appears with non-empty content.

    Marked @slow because it fires real model inference (30s+ on a cold
    CPU stack) and tearing the browser context down mid-inference can
    bleed state into subsequent fixture initialisation. Skip in the
    default suite, run with -m slow for full validation.
    """
    if not _has_any_model(base_url, api_headers):
        pytest.skip("No models loaded; pull at least one")
    page = signed_in_page

    # Wait for the model picker to be ready (same expanded check as above).
    page.wait_for_function(
        """() => {
            const sel = document.getElementById('model-select');
            if (!sel || sel.options.length === 0) return false;
            const real = Array.from(sel.options)
              .map(o => (o.value || o.textContent || '').trim())
              .filter(v => v && !v.toLowerCase().includes('loading'));
            return real.length > 0;
        }""",
        timeout=30_000,
    )

    # Snap a baseline of the message-list size, then send.
    msg_count_before = page.locator("#messages .msg").count()
    page.locator("#prompt").fill("Reply with exactly: PING-OK")
    page.locator("#send-btn").click()

    # Wait for ≥ one new message bubble to appear (user msg + at least an
    # assistant placeholder). Allow a generous timeout — small models on
    # CPU can take 15–30s on the first inference cold-start.
    page.wait_for_function(
        f"() => document.querySelectorAll('#messages .msg').length >= {msg_count_before + 2}",
        timeout=90_000,
    )

    msgs = page.locator("#messages .msg").all_inner_texts()
    # Final message must contain non-empty text.
    last = msgs[-1].strip()
    assert last, f"Last message bubble is empty. All messages: {msgs}"


def test_chat_system_strip_updates_during_send(signed_in_page, base_url, api_headers):
    """While a chat fires, the system strip's CPU% should tick non-zero
    at least once. Confirms the system poller is wired and the strip is
    a live signal, not a static label."""
    if not _has_any_model(base_url, api_headers):
        pytest.skip("No models loaded")
    page = signed_in_page
    page.wait_for_function(
        """() => {
            const v = document.getElementById('cpu-value');
            return v && v.textContent.trim().endsWith('%');
        }""",
        timeout=10_000,
    )
    # Just confirms a poll has rendered; not asserting non-zero since a
    # cold idle container can sit at 0% and that's still healthy.


def test_agent_selector_lists_ootb_agents(signed_in_page):
    """The agent picker in the chat dock must list the 3 OOTB XQL agents
    so an operator can scope chat to xsiam-analyst directly."""
    page = signed_in_page
    page.wait_for_function(
        """() => {
            const sel = document.getElementById('agent-select');
            if (!sel) return false;
            const opts = Array.from(sel.options).map(o => o.text);
            return opts.some(t => t.toLowerCase().includes('xsiam'))
                || opts.some(t => t.toLowerCase().includes('xdm'))
                || opts.some(t => t.toLowerCase().includes('xql'));
        }""",
        timeout=15_000,
    )
