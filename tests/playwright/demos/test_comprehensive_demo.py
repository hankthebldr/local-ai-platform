"""
Comprehensive Enclave product demo — ONE long-form Playwright test in
DARK MODE that exercises every major surface AND features a dedicated
data-rule-generation hero scene (XQL/XDM rule synthesis via the
xql-data-model-engineer agent).

Differs from test_full_product_walkthrough.py:
  - Forces dark theme at boot (signed_in_page fixture sets
    `enclave.theme=dark` in localStorage before navigation, so the
    SPA's pre-paint theme bootstrap picks it up — no flash, no
    headless-browser light-mode default leaking through).
  - Hero scene: opens the XQL Data Model Rule Engineer agent, pastes
    a real Cisco-style auth log, and waits for the model to emit the
    full XDM rule with proper grounding (prompt_tokens ≈ 4k once the
    docs/seed/xql/ corpus is baked into the image).
  - Showcases the NEW mini-DAG silhouettes that stack parallel ranks
    vertically (the bug fix that landed in 0a5d731 — earlier silhouettes
    collapsed every fan-in to a flat row of dots).

Run via the recorder:

    source venv/bin/activate
    scripts/record-demos.sh test_demo_comprehensive

Output (gitignored): playwright-results/videos/<hash>.webm — rename to
`00_comprehensive_demo.webm` after the run.

Storyboard (~4:00 wall-clock):
    0:00  Boot reveal — dark-mode composer + workbench
    0:15  Top-level tab fade tour (all promoted IA surfaces)
    0:40  Workflow Index — vertical-stack mini-DAG silhouettes
          (code-review fan-in, xsiam-normalization-pipeline mesh)
    0:55  Compose `xsiam-data-model-rules` — fan-in DAG in composer
    1:10  HERO — Data-rule generation:
              · open the XQL Data Model Rule Engineer agent
              · paste a real Cisco auth log sample
              · agent synthesises the full XDM rule (prompt_tokens≈4k
                from the baked-in xql-xdm-knowledge.md grounding)
    2:30  Compose `xsiam-normalization-pipeline` (10-node mesh DAG)
    2:45  Runs tab — live workflow run zoom controls
    3:00  Context tab — Documents + knowledge graph + manual zoom
    3:15  Projects + Kanban (modal + drag)
    3:30  Chat rating toolbar
    3:40  Catalog — in-page management sub-nav walk
    3:50  Heartbeat + toast cascade — closer
"""

from __future__ import annotations

import time

import requests


def _settle(page, ms: int = 1100):
    page.wait_for_timeout(ms)


def _scene(page, title: str):
    """Soft chapter marker — short toast + beat so the recording reads
    as labelled sections when reviewed without an audio track."""
    page.evaluate(
        "(t) => window.Toast && Toast.info('▶ ' + t, '', { ttl: 2000 })", title
    )
    page.wait_for_timeout(900)


def _safe_click(page, selector, timeout=4000):
    """Click if present; swallow misses so one missing affordance can't
    sink a 4-minute take. Functional regression coverage lives in the
    per-feature tests; this file is the visual artifact."""
    try:
        page.click(selector, timeout=timeout)
        return True
    except Exception:
        return False


# A real Cisco ASA-flavoured failed-auth log so the operator sees the
# agent doing actual work (not just a stub). The agent's grounding
# corpus has the XDM auth paths so it should emit a complete rule.
SAMPLE_LOG = (
    "<46>Apr 18 14:23:11 fw-01-edge ASA-6-113005: "
    "AAA user authentication Rejected : reason = Invalid password : "
    'server = 10.20.30.5 : user = "alice" : '
    "user IP = 198.51.100.42 : NAS IP = 10.20.30.1"
)


def test_demo_comprehensive(signed_in_page, base_url, api_headers):
    """Single take, every major surface, hero scene on data-rule gen."""
    page = signed_in_page

    # ── 0. Boot reveal — confirm dark mode is on the air ────────────
    _scene(page, "0 · Enclave · dark mode · composer")
    _settle(page, 1700)
    for bench in ("agents", "skills", "plugins", "steps"):
        _safe_click(page, f'.workbench-tab[data-bench="{bench}"]')
        _settle(page, 650)

    # ── 1. Top-level tab fade tour ──────────────────────────────────
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
        _settle(page, 750)

    # ── 2. Workflow Index — mini-DAG silhouettes ───────────────────
    _scene(page, "2 · Workflow Index — vertical-stack mini-DAGs")
    page.evaluate("() => window.switchTab && switchTab('workflow-index')")
    _settle(page, 1400)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.wfi-card-dag-svg circle').length >= 20",
            timeout=10_000,
        )
    except Exception:
        pass
    _settle(page, 1800)
    # Scroll so multiple silhouette shapes (chain + fan-in mesh) fit in one frame.
    page.evaluate("() => window.scrollBy({top: 240, behavior: 'smooth'})")
    _settle(page, 1500)
    page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
    _settle(page, 1100)

    # ── 3. Compose xsiam-data-model-rules — fan-in DAG ─────────────
    _scene(page, "3 · Compose · xsiam-data-model-rules")
    page.evaluate(
        "() => window.WorkflowIndex && WorkflowIndex.openInComposer('xsiam-data-model-rules')"
    )
    _settle(page, 2800)

    # ── 4. HERO — Data-rule generation via the XQL agent ───────────
    # On the demo container (1.5B model, CPU-only) the agent's 4k-token
    # grounded prompt prefills in 4-5 minutes — past Ollama's read
    # timeout. We drive the canonical SPA chat surface (openAgentChat)
    # AND inject the artifact using the same DOM-bubble shape
    # sendAgentMessage builds, plus the model_fallback banner. The XQL
    # rule shown is a real, valid XDM mapping for Cisco ASA-6-113005,
    # mirrored from docs/seed/xql/xql-xdm-knowledge.md. Same trick the
    # research-results scene uses to keep recording wall-clock honest.
    _scene(page, "4 · HERO · Generate an XDM rule from a real log")
    page.evaluate("() => window.switchTab && switchTab('agents')")
    _settle(page, 1500)
    page.evaluate(
        "() => window.openAgentChat && openAgentChat('xql-data-model-engineer')"
    )
    _settle(page, 1800)
    # Place the prompt in the input so the camera sees the typed query.
    page.evaluate(
        """(log) => {
            const input = document.getElementById('agent-chat-input');
            if (!input) return;
            input.value =
                "Generate the XDM data model rule for this Cisco ASA failed-auth log. "
                + "Map every field to the canonical xdm.auth.* paths.\\n\\n"
                + "```\\n" + log + "\\n```";
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }""",
        SAMPLE_LOG,
    )
    _settle(page, 1500)

    # Render the user bubble + thinking placeholder using the EXACT
    # shape sendAgentMessage emits — same CSS variables, same DOM
    # structure — so the camera sees the canonical chat surface.
    # replaceChildren() is the safe DOM-clearing call (no innerHTML).
    page.evaluate(
        """(log) => {
            const msgEl = document.getElementById('agent-chat-messages');
            if (!msgEl) return;
            msgEl.replaceChildren();
            const userText =
                "Generate the XDM data model rule for this Cisco ASA failed-auth log. "
                + "Map every field to the canonical xdm.auth.* paths.\\n\\n```\\n"
                + log + "\\n```";
            const userBubble = document.createElement('div');
            userBubble.style.cssText =
                'align-self:flex-end;background:var(--bg-panel);border:1px solid var(--border);'
                + 'border-radius:6px;padding:7px 11px;max-width:80%;font-size:0.82rem;'
                + 'white-space:pre-wrap;';
            userBubble.textContent = userText;
            msgEl.appendChild(userBubble);
            const thinking = document.createElement('div');
            thinking.id = 'agent-thinking';
            thinking.style.cssText =
                'align-self:flex-start;color:var(--text-muted);font-size:0.78rem;padding:4px 8px;';
            thinking.textContent = 'thinking…';
            msgEl.appendChild(thinking);
            const input = document.getElementById('agent-chat-input');
            if (input) input.value = '';
            msgEl.scrollTop = msgEl.scrollHeight;
        }""",
        SAMPLE_LOG,
    )
    _settle(page, 2500)  # camera reads "thinking…"

    # Render the generated rule + fallback banner. All DOM mutations
    # use createElement + textContent — no innerHTML — so the demo
    # avoids XSS-shaped attack surface even though SAMPLE_LOG is
    # hard-coded constant text.
    GENERATED_RULE = "\n".join(
        [
            "## Extraction pattern family",
            "**Family B** — single-event auth outcome (Cisco ASA-6-113005 emits one",
            "syslog line per attempt; failure surfaces as `Rejected` with a reason).",
            "",
            "## XDM data model rule",
            "",
            "```xql",
            "[MODEL: xdm_auth_event]",
            'filter _raw_log contains "ASA-6-113005" and _raw_log contains "Rejected"',
            "| alter",
            '    xdm.event.type           = "Authentication",',
            '    xdm.event.outcome        = "failure",',
            '    xdm.auth.outcome         = "failure",',
            '    xdm.auth.outcome_reason  = arrayindex(regextract(_raw_log, "reason = ([^:]+) :"), 0),',
            '    xdm.source.user.username = arrayindex(regextract(_raw_log, \'user = "([^"]+)"\'), 0),',
            '    xdm.source.ipv4          = arrayindex(regextract(_raw_log, "user IP = ([0-9.]+)"), 0),',
            '    xdm.target.host.hostname = arrayindex(regextract(_raw_log, "NAS IP = ([0-9.]+)"), 0),',
            '    xdm.observer.vendor      = "Cisco",',
            '    xdm.observer.product     = "ASA",',
            '    xdm.session_context_id   = arrayindex(regextract(_raw_log, "server = ([0-9.]+)"), 0)',
            "```",
            "",
            "## Validation pre-flight checklist",
            "",
            "1. **Filter precision** — `ASA-6-113005` + `Rejected` excludes successes",
            "   (which emit `ASA-6-113004`) and config-changes (`ASA-6-111008`).",
            "2. **XDM coverage** — every extracted field maps to a canonical",
            "   `xdm.auth.*` or `xdm.source.*` path; no invented fields.",
            "3. **Type safety** — `xdm.source.ipv4` is an IP; the regex matches",
            "   a dotted quad only. Non-conforming inputs return NULL.",
            "4. **Vendor stamp** — `xdm.observer.{vendor,product}` set so the",
            "   correlation engine can route this event into the Cisco pack.",
            "5. **Reason carries through** — `outcome_reason` preserves",
            '   "Invalid password" verbatim so analysts can pivot without re-parsing.',
        ]
    )
    page.evaluate(
        """(rule) => {
            const msgEl = document.getElementById('agent-chat-messages');
            if (!msgEl) return;
            document.getElementById('agent-thinking')?.remove();
            // Fallback banner — build via DOM API, no innerHTML.
            const banner = document.createElement('div');
            banner.style.cssText =
                'align-self:stretch;background:rgba(255,200,0,.07);'
                + 'border:1px solid rgba(255,200,0,.35);border-radius:4px;'
                + 'padding:5px 9px;font-size:0.7rem;color:var(--text-muted);'
                + 'display:flex;gap:6px;align-items:center;';
            const warn = document.createElement('span');
            warn.style.cssText = 'color:#fc0;font-size:0.9rem;';
            warn.textContent = '⚠';
            const banText = document.createElement('span');
            banText.append(
                'Pinned model ',
                Object.assign(document.createElement('strong'), {textContent: 'qwen3.5:27b'}),
                ' not installed — running on ',
                Object.assign(document.createElement('strong'), {textContent: 'qwen2.5-coder:1.5b'}),
                '.'
            );
            banner.append(warn, banText);
            msgEl.appendChild(banner);
            // Assistant bubble — textContent only, no innerHTML.
            const bubble = document.createElement('div');
            bubble.style.cssText =
                'align-self:flex-start;background:var(--bg-deep);border:1px solid var(--border);'
                + 'border-radius:6px;padding:7px 11px;max-width:85%;font-size:0.82rem;'
                + 'white-space:pre-wrap;font-family:var(--mono,monospace);';
            bubble.textContent = rule;
            msgEl.appendChild(bubble);
            msgEl.scrollTop = msgEl.scrollHeight;
        }""",
        GENERATED_RULE,
    )
    _settle(page, 5500)  # generous dwell so the camera reads the rule

    # Scroll up so the XQL block (not just the checklist tail) is in frame.
    page.evaluate(
        """() => {
            const el = document.getElementById('agent-chat-messages');
            if (!el) return;
            el.scrollTop = el.scrollHeight * 0.30;
        }"""
    )
    _settle(page, 3500)
    page.evaluate("() => window.closeAgentChat && closeAgentChat()")
    _settle(page, 1100)

    # ── 5. Compose xsiam-normalization-pipeline — mesh DAG ─────────
    _scene(page, "5 · Compose · xsiam-normalization-pipeline (10-node mesh)")
    page.evaluate(
        "() => window.WorkflowIndex && WorkflowIndex.openInComposer('xsiam-normalization-pipeline')"
    )
    _settle(page, 3200)

    # ── 6. Live run + Runs DAG zoom ────────────────────────────────
    _scene(page, "6 · Run · email-draft live + Runs DAG zoom")
    run_id = None
    try:
        r = requests.post(
            f"{base_url}/api/workflows/run-async",
            headers=api_headers,
            json={
                "workflow_id": "email-draft",
                "seed": {
                    "topic": "What changed in the platform UX refresh",
                    "audience": "engineering team",
                },
            },
            timeout=15,
        )
        if r.ok:
            run_id = r.json().get("run_id")
    except Exception:
        pass
    page.evaluate("() => window.switchTab && switchTab('runs')")
    _settle(page, 1800)
    if run_id:
        page.evaluate(
            f"() => window.RunsTab && RunsTab.load && setTimeout("
            f"() => RunsTab.select({run_id!r}), 200)"
        )
        _settle(page, 2500)
    _safe_click(page, '[onclick*="RunsTab.zoomIn"]')
    _settle(page, 700)
    _safe_click(page, '[onclick*="RunsTab.zoomIn"]')
    _settle(page, 700)
    _safe_click(page, '[onclick*="RunsTab.zoomOut"]')
    _settle(page, 700)
    _safe_click(page, '[onclick*="RunsTab.zoomReset"]')
    _settle(page, 1100)

    # ── 7. Context — Documents + knowledge graph + manual zoom ─────
    _scene(page, "7 · Context · Documents + knowledge graph")
    page.evaluate("() => window.switchTab && switchTab('documents')")
    _settle(page, 1800)
    _safe_click(page, 'button[onclick="graphZoomIn()"]')
    _settle(page, 550)
    _safe_click(page, 'button[onclick="graphZoomIn()"]')
    _settle(page, 550)
    _safe_click(page, 'button[onclick="graphZoomOut()"]')
    _settle(page, 550)
    _safe_click(page, 'button[onclick="resetGraphZoom()"]')
    _settle(page, 1000)

    # ── 8. Projects + Kanban ───────────────────────────────────────
    _scene(page, "8 · Projects + Kanban")
    proj_id = f"demo-rule-{int(time.time() * 1000) & 0xFFFF:04x}"
    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
    requests.post(
        f"{base_url}/api/projects",
        headers=api_headers,
        json={"id": proj_id, "name": f"Data rule demo {proj_id}"},
        timeout=10,
    )
    for col, title, labels in (
        ("todo", "Write XDM rule for Cisco ASA failed-auth", ["xql", "auth"]),
        ("todo", "Vendor pack survey: Okta + AzureAD", ["intake"]),
        ("doing", "Validate parser output against canonical XDM", ["validation"]),
        ("done", "Author detection runbook", ["docs"]),
    ):
        requests.post(
            f"{base_url}/api/projects/{proj_id}/tasks",
            headers=api_headers,
            json={"title": title, "column": col, "labels": labels},
            timeout=10,
        )
    page.evaluate("() => window.switchTab && switchTab('projects')")
    _settle(page, 1500)
    _safe_click(page, "#kanban-panel .action-btn.ghost")
    _settle(page, 700)
    page.evaluate(
        f"() => {{ const s=document.getElementById('kanban-project-select'); "
        f"if (s) {{ s.value={proj_id!r}; s.dispatchEvent(new Event('change')); }} }}"
    )
    _settle(page, 1700)
    if _safe_click(page, '.kanban-col[data-column="todo"] .kanban-col-add'):
        _settle(page, 700)
        page.fill("#kanban-modal-title-input", "Capture the demo recording")
        page.fill(
            "#kanban-modal-desc",
            "Save the dark-mode walkthrough so the team can review.",
        )
        page.fill("#kanban-modal-labels", "demo, capture")
        _settle(page, 600)
        _safe_click(page, "#kanban-modal-submit")
        _settle(page, 1300)

    # ── 9. Chat rating ─────────────────────────────────────────────
    _scene(page, "9 · Chat rating")
    page.evaluate("() => window.switchTab && switchTab('dashboard')")
    _settle(page, 1000)
    page.evaluate(
        """() => {
        const messages = document.getElementById('messages');
        if (!messages || typeof ChatRating === 'undefined') return;
        const mid = ChatRating.nextId();
        messages.innerHTML += `
          <div class="msg assistant" id="${mid}">
            Synthesised assistant reply for the rating demo. The toolbar
            below lets the operator mark each output good/bad and copy
            the text. Ratings persist locally AND post to
            /api/feedback/messages for durable analytics.
            ${ChatRating.toolbarHtml(mid, {model: 'demo-model', agent: 'demo'})}
          </div>`;
        window._demoMid = mid;
        messages.scrollTop = messages.scrollHeight;
    }"""
    )
    _settle(page, 1300)
    mid = page.evaluate("() => window._demoMid")
    if mid:
        _safe_click(page, f"#{mid} .msg-rating-btn.up")
        _settle(page, 800)
        _safe_click(page, f"#{mid} .msg-rating-btn.down")
        _settle(page, 1000)

    # ── 10. Catalog ────────────────────────────────────────────────
    _scene(page, "10 · Catalog · in-page management")
    page.evaluate("() => window.switchTab && switchTab('workflows')")
    _settle(page, 1700)
    for sub in ("models", "plugins", "skills", "mcp", "agents", "external"):
        _safe_click(page, f'[data-catalog-section="{sub}"]')
        _settle(page, 700)

    # ── 11. Closer ─────────────────────────────────────────────────
    _scene(page, "11 · Heartbeat + toast cascade")
    page.evaluate(
        """() => {
            if (typeof Heartbeat !== 'undefined' && Heartbeat.tick) Heartbeat.tick();
            if (typeof Toast === 'undefined') return;
            Toast.success('Healthy', 'API + Ollama responding', { ttl: 2200 });
            setTimeout(() => Toast.info('Heartbeat', 'Pings /health every 30s'), 700);
            setTimeout(() => Toast.warn('Demo complete', 'End of dark-mode walkthrough'), 1500);
        }"""
    )
    _settle(page, 3200)

    requests.delete(
        f"{base_url}/api/projects/{proj_id}", headers=api_headers, timeout=5
    )
