"""Playwright smokes for the chat-led Composer redesign.

One smoke per shipped phase; each is resilient to a partial stack (the
session-scoped `_require_stack` fixture skips the whole module when the API
isn't reachable). LLM-dependent flows are marked `@pytest.mark.slow`.

Phase 0 (this file's first tests) is pure layout: a draggable chat | spine
split, a dormant workflow spine until a workflow is primed, and a collapsed
platform-management drawer. No behaviour change to chat or the canvas.
"""

from __future__ import annotations

import json

import pytest


def test_split_layout_renders(signed_in_page, no_console_errors):
    """The chat-led split, dormant spine, and mgmt drawer all render, and
    the spine is dormant (no workflow primed) on a fresh canvas."""
    page = signed_in_page
    split = page.locator("#composer-split")
    split.wait_for(state="visible", timeout=10_000)

    # Chat dock lives inside the split (column 1) and is visible.
    assert page.locator("#composer-split #agent-chat-dock").is_visible()

    # Dormant ghost shows until a workflow is primed.
    assert page.locator("#composer-spine-dormant").is_visible()
    assert "is-primed" not in (split.get_attribute("class") or "")

    # The live canvas/workstream are hidden while dormant.
    assert not page.locator("#composer-split .composer-grid").is_visible()

    # Management drawer is present and collapsed by default, wrapping the
    # workflow toolbar (which therefore no longer dominates the screen).
    drawer = page.locator("details.composer-mgmt-drawer")
    assert drawer.count() == 1
    assert drawer.get_attribute("open") is None
    assert drawer.locator(".composer-toolbar").count() == 1


def test_divider_drag_resizes(signed_in_page, no_console_errors):
    """Dragging the divider changes the persisted --chat-frac variable."""
    page = signed_in_page
    page.locator("#composer-split").wait_for(state="visible", timeout=10_000)

    def chat_frac() -> str:
        return page.evaluate(
            "() => getComputedStyle(document.getElementById('composer-split'))"
            ".getPropertyValue('--chat-frac').trim()"
        )

    divider = page.locator("#composer-divider")
    box = divider.bounding_box()
    assert box, "divider has no layout box"

    before = chat_frac()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] - 180, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()
    after = chat_frac()

    assert after and after != before, f"--chat-frac unchanged ({before!r} -> {after!r})"
    # Dragging left shrinks the chat fraction.
    assert float(after.rstrip("%")) < float((before or "62%").rstrip("%"))


# ── Boot Sequence: the chat -> workflow "Promote" interaction ──────────────

_CAPTURE_JSON = json.dumps(
    {
        "goal": "Draft a firm but warm vendor pushback email",
        "inputs": [{"key": "vendor_name", "description": "the vendor"}],
        "checks": ["tone is firm but warm", "no over-promising"],
        "model": "hermes3:8b",
    }
)

_SCAFFOLD_JSON = json.dumps(
    {
        "definition": {
            "id": "vendor-email",
            "name": "Vendor Email",
            "description": "draft + validate",
            "version": "0.1",
            "schema_version": 1,
            "context": {
                "inputs": [{"key": "vendor_name", "description": "the vendor"}]
            },
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
                },
                {
                    "id": "validate",
                    "name": "Validate tone",
                    "role": "reviewer",
                    "system_prompt": "check tone",
                    "inputs": ["draft.draft"],
                    "outputs": ["final"],
                    "depends_on": ["draft"],
                },
            ],
        },
        "source": "llm",
        "matched_workflow_id": None,
        "bindings": [
            {
                "step_id": "draft",
                "name": "Draft email",
                "role": "reasoning",
                "model": "hermes3:8b",
                "kind": "llm",
            },
            {
                "step_id": "validate",
                "name": "Validate tone",
                "role": "reviewer",
                "model": "qwen2.5-coder:7b",
                "kind": "llm",
            },
        ],
    }
)


def _seed_assistant_message(page):
    """Push a turn into chatHistory and render an assistant message carrying the
    real dispatch affordance (via the shipped ChatRating.toolbarHtml)."""
    page.evaluate("""() => {
            chatHistory.push({role:'user', content:'write a firm but warm vendor pushback email'});
            chatHistory.push({role:'assistant', content:'Here is a draft you can adapt...'});
            const m = document.getElementById('messages');
            m.insertAdjacentHTML('beforeend',
              '<div class="msg assistant" id="bs-test-msg">Here is a draft...' +
              window.ChatRating.toolbarHtml('bs-test-msg', {model:'hermes3:8b'}) + '</div>');
        }""")


def test_dispatch_affordance_present(signed_in_page, no_console_errors):
    """Every assistant message carries the intuitive (non-jargon) affordance."""
    page = signed_in_page
    page.wait_for_selector("#composer-split", timeout=10_000)
    _seed_assistant_message(page)
    btn = page.locator("#bs-test-msg .bs-dispatch")
    assert btn.count() == 1
    assert "run this with my agents" in btn.inner_text().lower()
    # No jargon.
    assert "workflow" not in btn.inner_text().lower()


def test_boot_sequence_full_flow(signed_in_page, no_console_errors):
    """dispatch -> compile-log plan card (local decomposition) -> confirm ->
    dormant spine primes into a live DAG. Endpoints are stubbed so the UI
    choreography is exercised deterministically (the backend is unit-tested)."""
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
    _seed_assistant_message(page)

    page.locator("#bs-test-msg .bs-dispatch").click()

    # The compile-log card appears and fills (confirm enables once scaffolded).
    page.wait_for_selector("#bs-plan-card", timeout=10_000)
    page.wait_for_function(
        "() => { const b = document.querySelector('.bs-cmd-confirm'); return b && !b.disabled; }",
        timeout=15_000,
    )

    # The local decomposition is shown: a roster of steps, each with a local
    # model pill — and the local-first truth line.
    assert page.locator("#bs-plan-card .bs-probe").count() == 2
    assert (
        "@ hermes3:8b"
        in page.locator("#bs-plan-card .bs-model-name").first.inner_text()
    )
    assert "leave this machine" in page.locator("#bs-plan-card .bs-tally").inner_text()
    # Goal stanza is editable.
    assert page.locator(
        '#bs-plan-card .bs-stanza[data-field="goal"] .bs-stanza-val'
    ).is_visible()

    # Confirm -> the spine primes and a live DAG materializes.
    page.locator(".bs-cmd-confirm").click()
    page.wait_for_function(
        "() => document.getElementById('composer-split').classList.contains('is-primed')",
        timeout=10_000,
    )
    # The real DAG materialized — assert the authoritative product state
    # (dfNodeData), which is what the canvas renders from.
    page.wait_for_function(
        "() => { try { return Object.keys(dfNodeData || {}).length >= 2; } catch (e) { return false; } }",
        timeout=10_000,
    )
    # START/END anchors + step nodes are all in the DOM.
    assert page.locator("#drawflow-canvas .drawflow-node").count() >= 2
    # Card is gone after the reveal.
    page.wait_for_function(
        "() => !document.getElementById('bs-plan-card')", timeout=10_000
    )


def test_editing_spec_rescaffolds_on_confirm(signed_in_page, no_console_errors):
    """Regression for the review finding: editing inputs/checks then confirming
    must re-scaffold (not silently discard edits). We count scaffold calls."""
    page = signed_in_page
    scaffold_calls = {"n": 0}

    def _scaffold(route):
        scaffold_calls["n"] += 1
        route.fulfill(status=200, content_type="application/json", body=_SCAFFOLD_JSON)

    page.route(
        "**/api/composer/capture-spec",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=_CAPTURE_JSON
        ),
    )
    page.route("**/api/composer/scaffold", _scaffold)
    page.wait_for_selector("#composer-split", timeout=10_000)
    _seed_assistant_message(page)
    page.locator("#bs-test-msg .bs-dispatch").click()
    page.wait_for_function(
        "() => { const b = document.querySelector('.bs-cmd-confirm'); return b && !b.disabled; }",
        timeout=15_000,
    )
    assert scaffold_calls["n"] == 1  # initial scaffold

    # Edit the checks stanza, then confirm -> must re-scaffold.
    page.evaluate("""() => {
            const el = document.querySelector('#bs-plan-card [data-field="checks"] .bs-stanza-val');
            el.textContent = 'a brand new check the operator typed';
        }""")
    page.locator(".bs-cmd-confirm").click()
    page.wait_for_function(
        "() => document.getElementById('composer-split').classList.contains('is-primed')",
        timeout=10_000,
    )
    assert (
        scaffold_calls["n"] == 2
    ), "editing the spec should trigger a re-scaffold on confirm"


def test_dispatch_cancel_keeps_chat(signed_in_page, no_console_errors):
    """'keep talking' dismisses the plan card without priming the spine."""
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
    _seed_assistant_message(page)
    page.locator("#bs-test-msg .bs-dispatch").click()
    page.wait_for_selector("#bs-plan-card", timeout=10_000)
    page.locator(".bs-cmd-cancel").click()
    page.wait_for_function(
        "() => !document.getElementById('bs-plan-card')", timeout=5_000
    )
    assert "is-primed" not in (
        page.locator("#composer-split").get_attribute("class") or ""
    )
