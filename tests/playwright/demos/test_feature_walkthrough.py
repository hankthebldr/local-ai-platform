"""
Demo walkthroughs — Playwright tests whose primary purpose is to PRODUCE
VIDEO RECORDINGS of the Enclave SPA exercising specific feature surfaces.

Run with the recording flag set so each test produces a per-test webm:

    ENCLAVE_PLAYWRIGHT_RECORD=1 pytest tests/playwright/demos -v

Or use the wrapper:

    scripts/record-demos.sh

The conftest in tests/playwright/ auto-applies the e2e marker, and the
record_video_dir is set on the context when ENCLAVE_PLAYWRIGHT_RECORD=1.
"""

from __future__ import annotations




# Wait helpers ──────────────────────────────────────────────────────────────


def _settle(page, ms: int = 800):
    """A small visible pause so the recording has rhythm."""
    page.wait_for_timeout(ms)


# ── Demo: Chat output rating ────────────────────────────────────────────────


def test_demo_chat_rating_toolbar(signed_in_page):
    """Walkthrough: open Composer, render a fake assistant message via the
    ChatRating API, rate it good then bad, watch the toolbar paint state."""
    page = signed_in_page
    _settle(page)

    page.evaluate(
        """() => {
        const messages = document.getElementById('messages');
        if (!messages) return;
        const mid = ChatRating.nextId();
        messages.innerHTML += `
          <div class="msg assistant" id="${mid}">
            This is a synthesized assistant reply for the rating demo.
            The toolbar below lets the operator mark each output good/bad
            and copy the text. Ratings persist to localStorage AND post
            to /api/feedback/messages for durable analytics.
            ${ChatRating.toolbarHtml(mid, {model: 'demo-model', agent: 'demo'})}
          </div>`;
        window._demoMsgId = mid;
    }"""
    )
    _settle(page, 1200)
    # Click thumbs-up
    page.click(f'#{page.evaluate("() => window._demoMsgId")} .msg-rating-btn.up')
    _settle(page, 900)
    # Then thumbs-down (toggles the up off)
    page.click(f'#{page.evaluate("() => window._demoMsgId")} .msg-rating-btn.down')
    _settle(page, 1500)


# ── Demo: Composer workstream tabs ────────────────────────────────────────


def test_demo_composer_workstream_tabs(signed_in_page):
    """Walkthrough: click each of the three workstream tabs at the bottom
    of the Composer so the History pane fetches from /api/workflows/runs."""
    page = signed_in_page
    _settle(page, 1000)

    page.click('.workstream-tab[data-ws="run"]')
    _settle(page, 1500)
    page.click('.workstream-tab[data-ws="history"]')
    _settle(page, 2200)
    page.click('.workstream-tab[data-ws="step"]')
    _settle(page, 1000)


# ── Demo: Skills Lab research + artifact capture ──────────────────────────


def test_demo_skills_lab_artifact_capture(signed_in_page):
    """Walkthrough: open Skills Lab, simulate a finished research result,
    expand the per-sub-question thinking cards, click capture-as-artifact."""
    page = signed_in_page
    page.evaluate("() => window.switchTab && window.switchTab('research')")
    _settle(page, 1500)

    # Inject a synthetic research result so the demo doesn't need to wait
    # 30s+ for a real model call.
    page.evaluate(
        """() => {
        const data = {
          topic: "Cortex XSIAM detection patterns for credential stuffing",
          model: "demo-model",
          sub_questions: [
            "What signals identify credential stuffing in XSIAM?",
            "Which XDM paths are canonical for failed-auth events?",
            "How do we baseline normal failed-auth rates per user?"
          ],
          research: [
            {
              question: "What signals identify credential stuffing in XSIAM?",
              context: "Failed authentications at unusually high rate from a small IP range; the agent gathered three reference docs on the canonical XDM paths and burst-detection patterns.",
              sources: [
                {url: "https://example.com/cortex-cs", title: "Cortex XSIAM — credential stuffing playbook"},
                {url: "https://example.com/xdm-auth",  title: "XDM paths for auth events"}
              ]
            },
            {
              question: "Which XDM paths are canonical for failed-auth events?",
              context: "Primary: xdm.auth.outcome = 'failure', xdm.source.user.username, xdm.source.ip. See also xdm.event.outcome and xdm.target.host.hostname.",
              sources: [
                {url: "https://example.com/xdm-schema", title: "XDM canonical schema reference"}
              ]
            },
            {
              question: "How do we baseline normal failed-auth rates per user?",
              context: "Rolling 30-day average per user with seasonality decomposition. The agent suggested a comp count() by user binned hourly with stddev-based thresholding.",
              sources: []
            }
          ],
          synthesis: "## Executive Summary\\nCredential stuffing in Cortex XSIAM is detected by combining a per-user failed-auth rate baseline with IP-clustering against the source IP. The xdm.auth.* paths give canonical fields to anchor the rule.\\n\\n## Key Findings\\n- Use xdm.auth.outcome = 'failure' as the primary filter.\\n- Cluster on xdm.source.ip and bin by hour.\\n- Threshold on per-user baseline ± 3 stddev.\\n\\n## Conclusions\\nA simple rule against the XDM auth event + per-user baseline catches the majority of credential-stuffing attempts with low false-positive rate.",
          sources: [
            {url: "https://example.com/cortex-cs", title: "Cortex XSIAM — credential stuffing playbook"},
            {url: "https://example.com/xdm-auth",  title: "XDM paths for auth events"},
            {url: "https://example.com/xdm-schema", title: "XDM canonical schema reference"}
          ]
        };
        renderResearchResults(data);
    }"""
    )
    _settle(page, 1800)

    # Expand the first thinking card.
    page.click(".research-thinking-card:nth-of-type(1) > summary")
    _settle(page, 1500)
    page.click(".research-thinking-card:nth-of-type(2) > summary")
    _settle(page, 1500)

    # Capture the first sub-question as an artifact.
    page.click(".research-thinking-card:nth-of-type(1) .action-btn.cyan")
    _settle(page, 1800)

    # Capture the synthesis.
    page.click(".research-actions .action-btn.accent")
    _settle(page, 1800)

    # Open the artifact library modal.
    page.click(".research-actions .action-btn.cyan")
    _settle(page, 2500)


# ── Demo: Sub-tab fade + system strip + agent workbench ───────────────────


def test_demo_top_level_navigation(signed_in_page):
    """Walkthrough: hop across the top-level tabs so the motion design
    fade + workbench cards + system strip all show on the recording."""
    page = signed_in_page
    _settle(page, 1200)
    for tab in [
        "workflow-index",
        "agents",
        "research",
        "inventory",
        "documents",
        "admin-plugins",
        "admin-skills",
        "admin-mcp",
        "dashboard",
    ]:
        page.evaluate(f"() => window.switchTab && window.switchTab('{tab}')")
        _settle(page, 1100)
