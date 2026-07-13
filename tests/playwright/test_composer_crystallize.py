"""GP-1b — P0-10: chat crystallize ("run this with my agents") dead-end.

After the four-surface separation the chat lives on its own #tab-chat, but the
Boot Sequence renders its plan card into #composer-split, which sits on the
Composer (#tab-dashboard). While the operator is in Chat that tab is hidden, so
the plan card + confirm button landed on a display:none surface — a dead end.

The fix reveals the Composer (switchTab('dashboard')) inside BootSequence
.dispatch BEFORE rendering, so the card is on the visible tab and confirm is
reachable. (test_composer_chat_led.py stays skipped: its assertions target the
retired chat-LED split — #composer-divider, agent-chat-dock-inside-split — that
this design intentionally removed.)
"""

from __future__ import annotations

import json

_CAPTURE_JSON = json.dumps(
    {
        "goal": "Draft a firm but warm vendor pushback email",
        "inputs": [{"key": "vendor_name", "description": "the vendor"}],
        "checks": ["tone is firm but warm"],
        "model": "hermes3:8b",
    }
)

_SCAFFOLD_JSON = json.dumps(
    {
        "definition": {
            "id": "vendor-email",
            "name": "Vendor Email",
            "version": "0.1",
            "context": {"inputs": [{"key": "vendor_name", "description": "the vendor"}]},
            "defaults": {"role": "reasoning"},
            "steps": [
                {
                    "id": "draft",
                    "name": "Draft email",
                    "role": "reasoning",
                    "system_prompt": "write the email",
                    "inputs": ["seed.vendor_name"],
                    "outputs": ["draft"],
                    "depends_on": [],
                }
            ],
        },
        "source": "llm",
        "bindings": [
            {
                "step_id": "draft",
                "name": "Draft email",
                "role": "reasoning",
                "model": "hermes3:8b",
                "kind": "llm",
            }
        ],
    }
)


def _seed_chat_affordance(page):
    """Push a turn into chatHistory + render the real dispatch affordance, then
    move to the Chat tab where the affordance lives (as an operator would)."""
    page.evaluate(
        """() => {
            chatHistory.push({ role: 'user', content: 'draft a vendor pushback email' });
            chatHistory.push({ role: 'assistant', content: 'Here is a draft you can adapt...' });
            const m = document.getElementById('messages');
            m.insertAdjacentHTML('beforeend',
              '<div class="msg assistant" id="bs-test-msg">Here is a draft...' +
              window.ChatRating.toolbarHtml('bs-test-msg', { model: 'hermes3:8b' }) + '</div>');
            switchTab('chat');
        }"""
    )


def test_crystallize_reveals_composer_and_reaches_confirm(signed_in_page):
    page = signed_in_page
    page.route(
        "**/api/composer/capture-spec",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=_CAPTURE_JSON
        ),
    )
    page.route(
        "**/api/composer/scaffold",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=_SCAFFOLD_JSON
        ),
    )
    page.wait_for_selector("#composer-split", timeout=10_000)
    _seed_chat_affordance(page)

    # We're on the Chat tab now; the Composer (#tab-dashboard) is hidden.
    assert not page.locator("#tab-dashboard").is_visible()

    # Fire the crystallize affordance from the chat.
    page.locator("#bs-test-msg .bs-dispatch").click()

    # P0-10: the plan card renders ON THE VISIBLE Composer tab (not a hidden
    # one), so it's actually visible and the operator can act on it.
    page.wait_for_selector("#bs-plan-card", state="visible", timeout=10_000)
    assert page.locator("#tab-dashboard").is_visible()

    # And it reaches the sign gesture: confirm enables once scaffolded.
    page.wait_for_function(
        "() => { const b = document.querySelector('.bs-cmd-confirm'); return b && !b.disabled; }",
        timeout=15_000,
    )
    assert page.locator("#bs-plan-card .bs-cmd-confirm").is_visible()
