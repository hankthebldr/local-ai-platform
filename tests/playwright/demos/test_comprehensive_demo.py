"""
Comprehensive Enclave product demo — ONE long-form Playwright test that
exercises every major surface in a single take so the screen recorder
produces a single, narratable WebM.

Differs from test_full_product_walkthrough.py:
  - **kicks a real workflow run** so the Runs tab paints live state
    (not just a synthesized result)
  - showcases the post-refresh IA (Runs + Projects + Catalog as
    first-class tabs)
  - demos the newest UX work: rank-banded mini-DAG silhouettes on the
    Workflow Index cards, connected DAG nodes when loading a workflow
    into the composer, and the manual +/-/⟲ zoom controls on the
    Context tab knowledge graph.

Run via the recorder:

    source venv/bin/activate
    scripts/record-demos.sh test_demo_comprehensive

Output (gitignored): playwright-results/videos/<hash>.webm — rename to
``comprehensive_walkthrough.webm`` after the run.

Storyboard (~3:45 wall-clock):
    0:00  Boot reveal — composer + workbench + system strip
    0:15  Top-level tab fade tour (every promoted tab in the new IA)
    0:50  Workflow Index — mini-DAG silhouettes (▣×N pills + chains)
    1:05  Compose `code-review`         — fan-in pattern, connected DAG
    1:20  Compose `xsiam-normalization-pipeline` — complex mesh DAG
    1:35  Kick `email-draft` async + cut to Runs tab
    1:50  Runs DAG zoom in/out/reset + node click
    2:05  Projects + Kanban — create modal + drag affordance
    2:25  Context tab — Documents + Knowledge graph + manual zoom
    2:45  Deep Research synthetic result + capture artifact + library
    3:05  Chat rating toolbar (thumbs up + thumbs down)
    3:15  Catalog (legacy `workflows` tab — in-page management)
    3:30  Admin → System hub (Memory ledger + License Keys)
    3:40  Keyboard shortcuts overlay (? + g-w chord) + heartbeat finale
"""

from __future__ import annotations

import time

import requests


def _settle(page, ms: int = 1100):
    page.wait_for_timeout(ms)


def _scene(page, title: str):
    """Soft chapter marker — tiny toast + a beat, so the recording reads
    as labelled sections when reviewed without an audio track."""
    page.evaluate(
        "(t) => window.Toast && Toast.info('▶ ' + t, '', { ttl: 1900 })", title
    )
    page.wait_for_timeout(900)


def _safe_click(page, selector, timeout=4000):
    """Click if present; swallow misses so one missing affordance can't
    sink the whole take. The demo prioritises continuity over perfect
    coverage of every micro-affordance."""
    try:
        page.click(selector, timeout=timeout)
        return True
    except Exception:
        return False


def test_demo_comprehensive(signed_in_page, base_url, api_headers):
    """Single take, every major Enclave feature, live workflow run."""
    page = signed_in_page

    # ── 0. Boot reveal ──────────────────────────────────────────────────
    _scene(page, "0 · Composer + workbench")
    _settle(page, 1500)
    # Walk the right-rail workbench sub-tabs so the recording shows the
    # per-step configuration surface up front.
    for bench in ("agents", "skills", "plugins", "steps"):
        _safe_click(page, f'.workbench-tab[data-bench="{bench}"]')
        _settle(page, 700)

    # ── 1. Top-level tab fade tour ──────────────────────────────────────
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
        "workflows",  # Catalog
    ):
        page.evaluate(f"() => window.switchTab && window.switchTab('{tab}')")
        _settle(page, 850)

    # ── 2. Workflow Index — mini-DAG silhouettes ───────────────────────
    _scene(page, "2 · Workflow Index — mini-DAG silhouettes")
    page.evaluate("() => window.switchTab && window.switchTab('workflow-index')")
    _settle(page, 1400)
    # Let the lazy DAG-preview loader paint at least a few silhouettes
    # before we screenshot. Fan-in patterns render as a pill+×N badge.
    try:
        page.wait_for_function(
            """() => document.querySelectorAll('.wfi-card-dag-svg').length >= 4""",
            timeout=8000,
        )
    except Exception:
        pass
    _settle(page, 1600)
    # Scroll the grid so the camera catches multiple silhouette shapes
    # (chains vs fan-in pills) before the operator clicks Compose.
    page.evaluate("() => window.scrollBy({top: 220, behavior: 'smooth'})")
    _settle(page, 1500)
    page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
    _settle(page, 1100)

    # ── 3. Compose code-review (fan-in 3 → 1) ──────────────────────────
    _scene(page, "3 · Compose code-review (fan-in)")
    page.evaluate(
        "() => window.WorkflowIndex && WorkflowIndex.openInComposer('code-review')"
    )
    _settle(page, 2200)  # composer tab + drawflow node placement
    # Let the operator see the connected nodes — three passes feeding
    # synthesize.
    _settle(page, 1500)

    # ── 4. Compose xsiam-normalization-pipeline (complex mesh) ─────────
    _scene(page, "4 · Compose xsiam-normalization-pipeline")
    page.evaluate(
        "() => window.WorkflowIndex && WorkflowIndex.openInComposer('xsiam-normalization-pipeline')"
    )
    _settle(page, 2800)

    # ── 5. Kick a real workflow run + cut to Runs ──────────────────────
    _scene(page, "5 · Live run — email-draft")
    # Fire the async run via the API so it's already executing by the
    # time the Runs tab renders.
    run_id = None
    try:
        r = requests.post(
            f"{base_url}/api/workflows/run-async",
            headers=api_headers,
            json={
                "workflow_id": "email-draft",
                "seed": {
                    "topic": "Recap of the workflow-index UX work",
                    "audience": "engineering team",
                },
            },
            timeout=15,
        )
        if r.ok:
            run_id = r.json().get("run_id")
    except Exception:
        pass
    # Land in the Runs tab regardless — even if the run didn't start,
    # the recent-runs list still demos the surface.
    page.evaluate("() => window.switchTab && window.switchTab('runs')")
    _settle(page, 1800)
    # If we have a fresh run, drill into it so the live DAG paints.
    if run_id:
        page.evaluate(
            f"() => window.RunsTab && RunsTab.load && setTimeout(() => RunsTab.select({run_id!r}), 200)"
        )
        _settle(page, 3500)

    # ── 6. Runs DAG zoom controls ──────────────────────────────────────
    _scene(page, "6 · Runs DAG zoom + node click")
    _safe_click(page, '[onclick*="RunsTab.zoomIn"]')
    _settle(page, 900)
    _safe_click(page, '[onclick*="RunsTab.zoomIn"]')
    _settle(page, 900)
    _safe_click(page, '[onclick*="RunsTab.zoomOut"]')
    _settle(page, 900)
    _safe_click(page, '[onclick*="RunsTab.zoomReset"]')
    _settle(page, 1200)

    # ── 7. Projects + Kanban ───────────────────────────────────────────
    _scene(page, "7 · Projects + Kanban")
    proj_id = f"demo-comp-{int(time.time() * 1000) & 0xFFFF:04x}"
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
    requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"Comprehensive demo {proj_id}"},
        timeout=10,
    )
    for col, title, labels in (
        ("todo", "Author the XQL rule for credential stuffing", ["xql", "detection"]),
        ("todo", "Survey vendor pack candidates", ["intake"]),
        ("doing", "Validate detection against test logs", ["validation"]),
        ("done", "Author runbook", ["docs"]),
    ):
        requests.post(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            json={"title": title, "column": col, "labels": labels},
            timeout=10,
        )
    page.evaluate("() => window.switchTab && window.switchTab('projects')")
    _settle(page, 1600)
    _safe_click(page, "#kanban-panel .action-btn.ghost")  # refresh dropdown
    _settle(page, 800)
    page.evaluate(
        f"() => {{ const s=document.getElementById('kanban-project-select'); "
        f"if (s) {{ s.value={proj_id!r}; s.dispatchEvent(new Event('change')); }} }}"
    )
    _settle(page, 1800)
    # Open the create-task modal so the modal-craft is in frame.
    if _safe_click(page, '.kanban-col[data-column="todo"] .kanban-col-add'):
        _settle(page, 800)
        page.fill("#kanban-modal-title-input", "Wire the comprehensive demo recorder")
        page.fill(
            "#kanban-modal-desc",
            "End-to-end Playwright take that captures every Enclave surface.",
        )
        page.fill("#kanban-modal-labels", "demo, capture, docs")
        _settle(page, 700)
        _safe_click(page, "#kanban-modal-submit")
        _settle(page, 1400)

    # ── 8. Context tab — Documents + Knowledge graph + manual zoom ─────
    _scene(page, "8 · Context — Documents + Knowledge graph")
    page.evaluate("() => window.switchTab && window.switchTab('documents')")
    _settle(page, 1800)
    # Tap the manual zoom controls on the knowledge graph so the
    # recording captures the new +/-/⟲ buttons (page-scroll-safe).
    _safe_click(page, 'button[onclick="graphZoomIn()"]')
    _settle(page, 600)
    _safe_click(page, 'button[onclick="graphZoomIn()"]')
    _settle(page, 600)
    _safe_click(page, 'button[onclick="graphZoomOut()"]')
    _settle(page, 600)
    _safe_click(page, 'button[onclick="resetGraphZoom()"]')
    _settle(page, 1100)

    # ── 9. Deep Research synthetic result + capture artifact ───────────
    _scene(page, "9 · Deep Research — capture as artifact")
    # Inject a synthesised research result instead of waiting on the
    # 30s+ live agent so the demo timing stays predictable.
    page.evaluate(
        """() => {
        if (typeof renderResearchResults !== 'function') return;
        renderResearchResults({
          topic: "XSIAM detection patterns for credential stuffing",
          model: "demo-model",
          sub_questions: [
            "Which XDM paths anchor failed-auth events?",
            "How do we baseline normal failed-auth rates per user?",
            "What enrichment queries widen the investigation?"
          ],
          research: [
            { question: "Which XDM paths anchor failed-auth events?",
              context: "Primary: xdm.auth.outcome = 'failure', xdm.source.user.username, xdm.source.ip. Also xdm.event.outcome, xdm.target.host.hostname.",
              sources: [{url:"https://example.com/xdm-auth", title:"XDM auth paths reference"}] },
            { question: "How do we baseline normal failed-auth rates per user?",
              context: "Rolling 30-day per-user average with seasonality decomposition; comp count() by user binned hourly with stddev thresholding.",
              sources: [] },
            { question: "What enrichment queries widen the investigation?",
              context: "Reputation lookups on source IP, geolocation drift on the user, MITRE T1110 sub-techniques.",
              sources: [{url:"https://example.com/mitre-t1110", title:"MITRE T1110 — Brute Force"}] }
          ],
          synthesis: "## Executive Summary\\nCredential stuffing in Cortex XSIAM is detected by combining a per-user failed-auth-rate baseline with IP clustering against the source IP.\\n\\n## Key Findings\\n- xdm.auth.outcome = 'failure' is the primary filter\\n- Cluster on xdm.source.ip + bin by hour\\n- Threshold on per-user baseline ± 3 stddev\\n\\n## Conclusions\\nSimple rule + per-user baseline catches most credential-stuffing attempts with low false-positive rate.",
          sources: [{url:"https://example.com/xdm-auth", title:"XDM auth paths reference"}]
        });
    }"""
    )
    _settle(page, 1800)
    _safe_click(page, ".research-thinking-card:nth-of-type(1) > summary")
    _settle(page, 1300)
    _safe_click(page, ".research-thinking-card:nth-of-type(2) > summary")
    _settle(page, 1100)
    _safe_click(page, ".research-thinking-card:nth-of-type(1) .action-btn.cyan")
    _settle(page, 1500)
    _safe_click(page, ".research-actions .action-btn.accent")
    _settle(page, 1400)
    _safe_click(page, ".research-actions .action-btn.cyan")  # open artifact library
    _settle(page, 2000)
    # Close the library modal so the rating scene reads clean.
    page.keyboard.press("Escape")
    _settle(page, 700)

    # ── 10. Chat rating toolbar ────────────────────────────────────────
    _scene(page, "10 · Chat — rating toolbar")
    page.evaluate("() => window.switchTab && window.switchTab('dashboard')")
    _settle(page, 1100)
    page.evaluate(
        """() => {
        const messages = document.getElementById('messages');
        if (!messages || typeof ChatRating === 'undefined') return;
        const mid = ChatRating.nextId();
        messages.innerHTML += `
          <div class="msg assistant" id="${mid}">
            This is a synthesised assistant reply for the rating demo. The
            toolbar below lets the operator mark each output good/bad and
            copy the text. Ratings persist to localStorage AND post to
            /api/feedback/messages for durable analytics.
            ${ChatRating.toolbarHtml(mid, {model: 'demo-model', agent: 'demo'})}
          </div>`;
        window._demoMid = mid;
        messages.scrollTop = messages.scrollHeight;
    }"""
    )
    _settle(page, 1400)
    mid = page.evaluate("() => window._demoMid")
    if mid:
        _safe_click(page, f"#{mid} .msg-rating-btn.up")
        _settle(page, 900)
        _safe_click(page, f"#{mid} .msg-rating-btn.down")
        _settle(page, 1100)

    # ── 11. Catalog (legacy `workflows` tab) ──────────────────────────
    _scene(page, "11 · Catalog — Models · Plugins · Skills · MCP · Agents · External")
    page.evaluate("() => window.switchTab && window.switchTab('workflows')")
    _settle(page, 1800)
    # Walk the Catalog's internal sub-nav if it's there.
    for sub in ("models", "plugins", "skills", "mcp", "agents", "external"):
        _safe_click(page, f'[data-catalog-section="{sub}"]')
        _settle(page, 750)

    # ── 12. Admin → System hub ────────────────────────────────────────
    _scene(page, "12 · Admin · System hub")
    _safe_click(page, "#admin-trigger")
    _settle(page, 700)
    _safe_click(page, '#admin-menu .admin-menu-item:has-text("System")')
    _settle(page, 1500)
    _safe_click(page, '#tab-memory .system-subnav-link:has-text("License Keys")')
    _settle(page, 1400)

    # ── 13. Keyboard shortcuts overlay + g-chord ──────────────────────
    _scene(page, "13 · Keyboard shortcuts")
    page.keyboard.press("?")
    _settle(page, 1800)
    page.keyboard.press("Escape")
    _settle(page, 600)
    page.keyboard.press("g")
    page.wait_for_timeout(180)
    page.keyboard.press("w")  # jump to Workflow Index via g-w chord
    _settle(page, 1500)

    # ── 14. Heartbeat + toast cascade — closer ────────────────────────
    _scene(page, "14 · Heartbeat + toast cascade")
    page.evaluate(
        """() => {
            if (typeof Heartbeat !== 'undefined' && Heartbeat.tick) Heartbeat.tick();
            if (typeof Toast === 'undefined') return;
            Toast.success('Healthy', 'API + Ollama responding', { ttl: 2200 });
            setTimeout(() => Toast.info('Heartbeat', 'Pings /health every 30s'), 700);
            setTimeout(() => Toast.warn('Demo complete', 'End of comprehensive walkthrough'), 1500);
        }"""
    )
    _settle(page, 3200)

    # ── Cleanup ───────────────────────────────────────────────────────
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
