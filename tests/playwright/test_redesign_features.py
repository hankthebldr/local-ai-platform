"""E2E runtime smoke for the chat-led redesign features.

Static-markup tests (tests/ui/) lock the structure; this confirms the six new
modules actually initialize and render in a real browser without throwing.
Auto-skips when the stack is unreachable (see conftest's signed_in_page).

Run (stack up):  ENCLAVE_PLAYWRIGHT_BASE_URL=http://localhost:8001 \
                 RATE_LIMIT_RPM=0 pytest tests/playwright/test_redesign_features.py
"""


def test_redesign_modules_initialize(signed_in_page):
    page = signed_in_page
    page.wait_for_timeout(1200)  # let init() + the journey interval run once
    mods = page.evaluate("""() => ({
            OpPath: typeof window.OpPath, Pins: typeof window.Pins,
            Threads: typeof window.Threads, Compare: typeof window.Compare,
            InstallWizard: typeof window.InstallWizard, RunLens: typeof window.RunLens
        })""")
    assert all(v == "object" for v in mods.values()), f"missing modules: {mods}"


def test_operator_path_ladder_renders(signed_in_page):
    page = signed_in_page
    page.wait_for_timeout(1200)
    stages = page.evaluate(
        "() => (document.getElementById('op-path-stages')||{}).childElementCount || 0"
    )
    assert stages == 5, f"expected 5 ladder stages, got {stages}"


def test_thread_switcher_creates_threads(signed_in_page):
    page = signed_in_page
    page.wait_for_timeout(800)
    assert (
        page.evaluate(
            "() => (document.getElementById('thread-active-name')||{}).textContent"
        )
        == "Thread 1"
    )
    page.evaluate("() => window.Threads.create()")
    assert (
        page.evaluate(
            "() => (document.getElementById('thread-active-name')||{}).textContent"
        )
        == "Thread 2"
    )


def test_install_wizard_opens_four_phases(signed_in_page):
    page = signed_in_page
    page.wait_for_timeout(500)
    page.evaluate("() => window.InstallWizard.open('qwen2.5:0.5b')")
    phases = page.evaluate(
        "() => document.getElementById('iw-phases').childElementCount"
    )
    assert phases == 4, f"expected 4 wizard phases, got {phases}"
    page.evaluate("() => window.InstallWizard.close()")
