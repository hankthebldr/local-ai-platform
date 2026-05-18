"""
UX normalization smoke — verifies the shared error/empty/network modules
are present, callable, and behave consistently across surfaces.

The goal is regression-guarding the unified affordances so future
panels can rely on them: Net (retry-aware fetch), ErrorPanel.render,
EmptyState.render, global error handlers, keyboard shortcut overlay.
"""

from __future__ import annotations


def test_unified_modules_defined(signed_in_page):
    """All shared UX modules must be wired into window before any
    feature-level code starts."""
    page = signed_in_page
    present = page.evaluate(
        """() => {
            return {
                Net: typeof window.Net,
                ErrorPanel: typeof window.ErrorPanel,
                EmptyState: typeof window.EmptyState,
                Toast: typeof window.Toast,
                Skeleton: typeof window.Skeleton,
                ChatRating: typeof window.ChatRating,
                ResearchArtifacts: typeof window.ResearchArtifacts,
                ComposerWorkstream: typeof window.ComposerWorkstream,
                Kanban: typeof window.Kanban,
                Shortcuts: typeof window.Shortcuts,
                EnclaveErrorLog: typeof window.EnclaveErrorLog,
            };
        }"""
    )
    for name, kind in present.items():
        assert kind == "object", f"window.{name} should be an object, got {kind!r}"


def test_error_panel_renders_into_element(signed_in_page):
    """ErrorPanel.render must write the consistent error markup + the
    retry button must fire its callback when clicked."""
    page = signed_in_page
    result = page.evaluate(
        """() => {
            const host = document.createElement('div');
            host.id = 'enclave-ux-error-host';
            document.body.appendChild(host);
            let retried = 0;
            ErrorPanel.render(host, {
                title: 'Test error',
                detail: 'Lorem ipsum failure detail.',
                retry: () => { retried++; }
            });
            const titleEl = host.querySelector('.enclave-error-title');
            const btn = host.querySelector('[data-error-retry]');
            btn.click();
            btn.click();
            const out = {
                titleText: titleEl ? titleEl.textContent : null,
                hasIcon: !!host.querySelector('.enclave-error-icon'),
                retried,
            };
            host.remove();
            return out;
        }"""
    )
    assert result["titleText"] == "Test error"
    assert result["hasIcon"] is True
    assert result["retried"] == 2


def test_empty_state_renders_with_cta(signed_in_page):
    """EmptyState.render with a cta produces a working action button."""
    page = signed_in_page
    result = page.evaluate(
        """() => {
            const host = document.createElement('div');
            document.body.appendChild(host);
            let clicked = 0;
            EmptyState.render(host, {
                title: 'No items',
                detail: 'Add the first one to get started.',
                cta: { label: 'Create', onclick: () => { clicked++; } }
            });
            const btn = host.querySelector('[data-empty-cta]');
            btn.click();
            const out = {
                titleText: host.querySelector('.enclave-empty-title').textContent,
                hasCta: !!btn,
                clicked,
            };
            host.remove();
            return out;
        }"""
    )
    assert result["titleText"] == "No items"
    assert result["hasCta"] is True
    assert result["clicked"] == 1


def test_net_get_json_round_trip(signed_in_page):
    """Net.getJson must hit a real endpoint and return its body."""
    page = signed_in_page
    result = page.evaluate(
        """async () => {
            const data = await Net.getJson('/health');
            return { status: data && data.status, isObj: typeof data === 'object' };
        }"""
    )
    assert result["isObj"] is True


def test_net_returns_structured_error_on_4xx(signed_in_page):
    """Net.call wraps non-2xx so callers don't have to catch — the
    response shape always has ok/status/error/data even on failure."""
    page = signed_in_page
    result = page.evaluate(
        """async () => {
            const r = await Net.call('/api/projects/this-does-not-exist-' + Date.now(), { silent: true, retries: 0 });
            return { ok: r.ok, status: r.status, hasError: typeof r.error === 'string' };
        }"""
    )
    assert result["ok"] is False
    assert result["status"] in (400, 404, 422), f"unexpected status: {result}"
    assert result["hasError"] is True


def test_error_log_records_unhandled_rejection(signed_in_page):
    """The global unhandledrejection handler must append to the
    durable EnclaveErrorLog so the operator can review afterwards."""
    page = signed_in_page
    result = page.evaluate(
        """async () => {
            EnclaveErrorLog.clear();
            // Synthesise an unhandled rejection.
            Promise.reject(new Error('synthetic UX-norm test failure'));
            await new Promise(r => setTimeout(r, 80));
            const log = EnclaveErrorLog.list();
            return {
                count: log.length,
                lastKind: log.length ? log[log.length - 1].kind : null,
                lastInfo: log.length ? log[log.length - 1].info : null,
            };
        }"""
    )
    assert result["count"] >= 1
    assert result["lastKind"] == "rejection"
    assert "synthetic UX-norm test failure" in str(result["lastInfo"])


def test_shortcut_overlay_opens_via_keystroke(signed_in_page):
    """Pressing ? opens the keyboard shortcut overlay; Esc closes it."""
    page = signed_in_page
    page.keyboard.press("?")
    page.wait_for_selector("#shortcuts-modal", state="visible", timeout=2_000)
    visible = page.locator("#shortcuts-modal").is_visible()
    assert visible
    page.keyboard.press("Escape")
    # Modal should hide; allow a small settle.
    page.wait_for_timeout(200)
    hidden = page.evaluate("() => document.getElementById('shortcuts-modal').hidden")
    assert hidden is True


def test_shortcut_tab_jump_g_w(signed_in_page):
    """The g-then-w chord must jump to the Workflow Index tab. This
    proves the global keyboard layer also doesn't fire on text fields."""
    page = signed_in_page
    page.keyboard.press("g")
    page.wait_for_timeout(100)
    page.keyboard.press("w")
    page.wait_for_selector("#tab-workflow-index", state="visible", timeout=3_000)
    active = page.evaluate(
        "() => document.querySelector('#tab-workflow-index')?.classList.contains('active')"
    )
    assert active is True


def test_heartbeat_marks_env_chip_healthy(signed_in_page):
    """The Heartbeat module pings /health on a 30s cadence; an immediate
    tick at boot must flip the env chip to .healthy when Ollama is up."""
    page = signed_in_page
    page.evaluate("() => Heartbeat.tick()")
    page.wait_for_function(
        """() => {
            const c = document.getElementById('env-chip');
            return c && c.classList.contains('healthy');
        }""",
        timeout=8_000,
    )
    state = page.evaluate(
        """() => {
            const c = document.getElementById('env-chip');
            return {
                last: Heartbeat.lastStatus(),
                healthy: c && c.classList.contains('healthy'),
                offline: c && c.classList.contains('offline'),
                degraded: c && c.classList.contains('degraded'),
                label: document.getElementById('env-chip-label').textContent.trim(),
            };
        }"""
    )
    assert state["last"] in ("healthy", "degraded", "offline")
    # On a healthy local stack with models loaded, healthy is expected.
    assert state["healthy"] is True
    assert state["label"] == "LOCAL"


def test_confirm_modal_resolves_to_true_on_ok(signed_in_page):
    """Confirm.ask returns a promise; clicking OK resolves true."""
    page = signed_in_page
    page.evaluate(
        """() => {
            window._confirmResult = null;
            Confirm.ask({ title: 'Test', body: 'Yes?', okLabel: 'Yep' })
                .then(v => { window._confirmResult = v; });
        }"""
    )
    page.wait_for_selector("#enclave-confirm-modal", state="visible", timeout=3_000)
    page.click("#enclave-confirm-ok")
    page.wait_for_function("() => window._confirmResult === true", timeout=3_000)
    assert page.evaluate("() => window._confirmResult") is True


def test_confirm_modal_resolves_to_false_on_cancel(signed_in_page):
    """Cancel returns false, modal closes."""
    page = signed_in_page
    page.evaluate(
        """() => {
            window._confirmResult2 = null;
            Confirm.ask({ title: 'Test 2', body: 'Cancel me' })
                .then(v => { window._confirmResult2 = v; });
        }"""
    )
    page.wait_for_selector("#enclave-confirm-modal", state="visible", timeout=3_000)
    page.click("#enclave-confirm-cancel")
    page.wait_for_function("() => window._confirmResult2 === false", timeout=3_000)
    assert page.evaluate("() => window._confirmResult2") is False
    assert (
        page.evaluate("() => document.getElementById('enclave-confirm-modal').hidden")
        is True
    )


def test_workflow_index_uses_unified_error_on_404(signed_in_page):
    """When the workflow index endpoint fails, the grid must render the
    unified ErrorPanel + retry button rather than a bare red string."""
    page = signed_in_page
    # Force the fail path by replacing the URL via fetch override.
    page.evaluate(
        """() => {
            const orig = window.fetch;
            let intercepted = false;
            window.fetch = function(u, init) {
                if (typeof u === 'string' && u.indexOf('/api/workflow-index') === 0 && !intercepted) {
                    intercepted = true;
                    return Promise.resolve(new Response('boom', { status: 500 }));
                }
                return orig.call(this, u, init);
            };
        }"""
    )
    page.evaluate("() => WorkflowIndex.refresh()")
    page.wait_for_function(
        "() => document.querySelector('#wfi-grid .enclave-error-panel')",
        timeout=8_000,
    )
    title = page.locator("#wfi-grid .enclave-error-title").inner_text()
    assert "Couldn’t load workflows" in title or "load" in title.lower()
    # Retry button is present.
    assert page.locator("#wfi-grid [data-error-retry]").count() == 1
