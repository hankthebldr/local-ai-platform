"""
Full product walkthrough — a single Playwright test that drives every
major surface in sequence so the video recorder produces ONE cohesive
demo file instead of N per-feature clips.

Run with recording on to capture the video:

    ENCLAVE_PLAYWRIGHT_RECORD=1 \\
        pytest tests/playwright/demos/test_full_product_walkthrough.py -v

Output: playwright-results/videos/<hash>.webm (rename per scripts/record-demos.sh).

Storyboard:
    0:00  Boot — Composer canvas, system strip, workbench
    0:30  Top-level tabs — Workflow Index, Agents, Skill Lab, Models, Context
    1:15  Kanban — pick project, create a task, drag between columns
    2:00  Composer Workstream — Step / Run / History tabs
    2:30  Skills Lab — synthetic research result with thinking cards + capture
    3:15  Chat — render an assistant message + rating toolbar
    3:45  Admin — System hub (Memory · License Keys · Runs)
    4:15  Keyboard shortcuts overlay + g-chord tab jumps
    4:45  Heartbeat + toasts
"""

from __future__ import annotations

import time

import requests


def _settle(page, ms: int = 1100):
    page.wait_for_timeout(ms)


def _scene(page, title: str):
    """Soft scene break — short pause + a toast so the recording reads
    as labelled chapters when reviewed."""
    page.evaluate(
        "(t) => window.Toast && Toast.info('▶ ' + t, '', { ttl: 1800 })", title
    )
    page.wait_for_timeout(900)


def test_demo_full_product_walkthrough(signed_in_page, base_url, api_headers):
    """One take, every feature."""
    page = signed_in_page

    # 0. Land on Composer
    _scene(page, "0 · Composer + workbench")
    _settle(page, 1600)
    page.click('.workbench-tab[data-bench="agents"]')
    _settle(page, 1200)
    page.click('.workbench-tab[data-bench="skills"]')
    _settle(page, 900)
    page.click('.workbench-tab[data-bench="plugins"]')
    _settle(page, 900)
    page.click('.workbench-tab[data-bench="steps"]')
    _settle(page, 600)

    # 1. Walk every top-level tab so the motion fade reads on video.
    # IA refresh: Runs + Projects are first-class top-level tabs now;
    # Skill Lab ('research') was retired and folded into Context
    # ('documents'); the legacy 'workflows' data-tab is Catalog.
    _scene(page, "1 · Top-level navigation")
    for tab in (
        "workflow-index",
        "agents",
        "runs",
        "projects",
        "inventory",
        "documents",
        "admin-plugins",
        "admin-skills",
        "admin-mcp",
    ):
        page.evaluate(f"() => window.switchTab && window.switchTab('{tab}')")
        _settle(page, 900)
    # Land on Projects so the Kanban scene below has the right tab active.
    page.evaluate("() => window.switchTab && window.switchTab('projects')")
    _settle(page, 1200)

    # 2. Kanban — create a project + tasks via API for instant board state,
    # then drive the UI to show the modal + drag. Lives in the Projects tab.
    proj_id = f"demo-walkthrough-{int(time.time() * 1000) & 0xFFFF:04x}"
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
    requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"Walkthrough demo {proj_id}"},
        timeout=10,
    )
    for col, title in (
        ("todo", "Draft XQL rule for credential stuffing"),
        ("todo", "Review pack candidates"),
        ("doing", "Validate detection against test logs"),
        ("done", "Author runbook"),
    ):
        requests.post(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            json={
                "title": title,
                "column": col,
                "labels": ["xql"] if "XQL" in title else [],
            },
            timeout=10,
        )

    _scene(page, "2 · Projects + Kanban")
    page.click("#kanban-panel .action-btn.ghost")  # refresh dropdown
    _settle(page, 700)
    page.evaluate(
        f"() => {{ const s=document.getElementById('kanban-project-select'); s.value={proj_id!r}; s.dispatchEvent(new Event('change')); }}"
    )
    _settle(page, 1500)
    page.click('.kanban-col[data-column="todo"] .kanban-col-add')
    _settle(page, 800)
    page.fill("#kanban-modal-title-input", "Cut release notes")
    page.fill("#kanban-modal-desc", "Summarise everything that landed in PR #69.")
    page.fill("#kanban-modal-labels", "release, docs")
    _settle(page, 700)
    page.click("#kanban-modal-submit")
    _settle(page, 1500)

    # 3. Composer Workstream — three sub-tabs
    page.evaluate("() => window.switchTab && window.switchTab('dashboard')")
    _settle(page, 1200)
    _scene(page, "3 · Composer workstream tabs")
    page.click('.workstream-tab[data-ws="run"]')
    _settle(page, 1400)
    page.click('.workstream-tab[data-ws="history"]')
    _settle(page, 2200)
    page.click('.workstream-tab[data-ws="step"]')
    _settle(page, 1000)

    # 4. Skills Lab — synthetic research output + capture-as-artifact.
    # The Skill Lab tab was retired in the IA refresh; its content
    # (Knowledge Graph + Deep Research) moved into the Context tab.
    # Route through 'documents' so the walkthrough reads as the
    # production IA — the legacy 'research' wrapper is kept hidden.
    page.evaluate("() => window.switchTab && window.switchTab('documents')")
    _settle(page, 1400)
    _scene(page, "4 · Skills Lab — research + capture")
    page.evaluate(
        """() => {
        renderResearchResults({
            topic: 'XSIAM detection patterns for credential stuffing',
            model: 'demo-model',
            sub_questions: [
                'Which XDM paths anchor failed-auth events?',
                'How do we baseline normal failed-auth rates per user?',
                'What enrichment queries widen the investigation?'
            ],
            research: [
                { question: 'Which XDM paths anchor failed-auth events?',
                  context: 'Primary: xdm.auth.outcome = "failure", xdm.source.user.username, xdm.source.ip. Also xdm.event.outcome, xdm.target.host.hostname.',
                  sources: [{url:'https://example.com/xdm-auth', title:'XDM auth paths reference'}] },
                { question: 'How do we baseline normal failed-auth rates per user?',
                  context: 'Rolling 30-day per-user average with seasonality decomposition; comp count() by user binned hourly with stddev thresholding.',
                  sources: [] },
                { question: 'What enrichment queries widen the investigation?',
                  context: 'Reputation lookups on source IP, geolocation drift on the user, MITRE T1110 sub-techniques.',
                  sources: [{url:'https://example.com/mitre-t1110', title:'MITRE T1110 — Brute Force'}] }
            ],
            synthesis: '## Executive Summary\\nCredential stuffing in Cortex XSIAM is detected by combining a per-user failed-auth-rate baseline with IP clustering against the source IP. The xdm.auth.* paths give canonical fields to anchor the rule.\\n\\n## Key Findings\\n- xdm.auth.outcome = "failure" as the primary filter\\n- Cluster on xdm.source.ip + bin by hour\\n- Threshold on per-user baseline ± 3 stddev\\n\\n## Conclusions\\nSimple rule + per-user baseline catches most credential-stuffing attempts with low false-positive rate.',
            sources: [{url:'https://example.com/xdm-auth', title:'XDM auth paths reference'}]
        });
    }"""
    )
    _settle(page, 1800)
    page.click(".research-thinking-card:nth-of-type(1) > summary")
    _settle(page, 1400)
    page.click(".research-thinking-card:nth-of-type(2) > summary")
    _settle(page, 1400)
    page.click(".research-actions .action-btn.accent")  # capture synthesis
    _settle(page, 1600)
    page.click(".research-actions .action-btn.cyan")  # open library
    _settle(page, 2000)
    page.click("#artifact-library-modal .action-btn")  # close
    _settle(page, 800)

    # 5. Chat dock — render a fake assistant message with rating toolbar
    page.evaluate("() => window.switchTab && window.switchTab('dashboard')")
    _settle(page, 1100)
    _scene(page, "5 · Chat output rating")
    page.evaluate(
        """() => {
        const messages = document.getElementById('messages');
        if (!messages) return;
        const mid = ChatRating.nextId();
        messages.innerHTML += `<div class=\"msg user\">Walk me through the detection logic.</div>` +
            `<div class=\"msg assistant\" id=\"${mid}\">` +
            'The rule fires when a user has >3 stddev failed auths within an hour ' +
            'from a clustered source IP. Use xdm.auth.outcome = "failure" + ' +
            'comp count() by xdm.source.user.username binned hourly. ' +
            ChatRating.toolbarHtml(mid, {model:'demo-model', agent:'xsiam-analyst'}) + '</div>';
        window._demoMid = mid;
    }"""
    )
    _settle(page, 1700)
    page.click(f'#{page.evaluate("() => window._demoMid")} .msg-rating-btn.up')
    _settle(page, 1200)

    # 6. Admin → System hub + first-class Runs tab.
    # IA refresh: Runs was promoted out of the System sub-nav into its
    # own top-level tab. The remaining System surfaces (Memory +
    # License Keys) are reachable via the Admin dropdown's System item;
    # Runs lands directly via switchTab('runs').
    _scene(page, "6 · Admin · System hub + Runs")
    page.click("#admin-trigger")
    _settle(page, 800)
    page.click('#admin-menu .admin-menu-item:has-text("System")')
    _settle(page, 1600)
    page.click('#tab-memory .system-subnav-link:has-text("License Keys")')
    _settle(page, 1600)
    # Runs is its own top-level tab in the new IA; jump there directly.
    page.evaluate("() => window.switchTab && window.switchTab('runs')")
    _settle(page, 1800)

    # 7. Keyboard shortcuts overlay
    _scene(page, "7 · Keyboard shortcuts")
    page.keyboard.press("?")
    _settle(page, 1800)
    page.keyboard.press("Escape")
    _settle(page, 600)
    # g-chord jump
    page.keyboard.press("g")
    page.wait_for_timeout(180)
    page.keyboard.press("w")
    _settle(page, 1600)

    # 8. Heartbeat + toasts
    _scene(page, "8 · Heartbeat + toast system")
    page.evaluate(
        """() => {
            Heartbeat.tick();
            Toast.success('Healthy', 'API + Ollama responding', { ttl: 2200 });
            setTimeout(() => Toast.info('Heartbeat', 'Pings /health every 30s'), 700);
            setTimeout(() => Toast.warn('Demo complete', 'End of walkthrough'), 1500);
        }"""
    )
    _settle(page, 3200)

    # Cleanup project (best-effort)
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
