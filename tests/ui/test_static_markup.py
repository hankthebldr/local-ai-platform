"""Regression assertions for api/static/*.html.

Each Week-1 task adds one test. A failing test BEFORE the fix demonstrates the
bug; a passing test AFTER demonstrates the fix. Tests are deliberately coarse —
they target invariants, not implementation.
"""

from __future__ import annotations

import re


def test_index_html_loads(index_soup):
    """Sanity: index.html parses as HTML and has a <title>."""
    title = index_soup.find("title")
    assert title is not None
    assert title.text.strip() != ""


def test_index_header_says_enclave_not_cortex(index_html_text):
    """Header branding must read 'Enclave', not 'CORTEX' or 'LOCAL AI PLATFORM'."""
    assert "CORTEX" not in index_html_text, "legacy CORTEX branding still present"
    assert (
        "LOCAL AI PLATFORM" not in index_html_text
    ), "legacy LOCAL AI PLATFORM still present"
    assert (
        "Mission Control" not in index_html_text
    ), "legacy 'Mission Control' tagline still present"


def test_index_footer_version_matches_api(index_html_text):
    """Footer version must match the version declared in api/__init__.py."""
    from api import __version__ as _api_version

    assert (
        f"Enclave v{_api_version}" in index_html_text
    ), f"footer must read 'Enclave v{_api_version}'"


def test_mobile_media_query_contains_all_responsive_rules(index_html_text):
    """The mobile @media block must wrap all six responsive rule blocks."""
    m = re.search(
        r"@media\s*\(\s*max-width:\s*800px\s*\)\s*\{",
        index_html_text,
    )
    assert m is not None, "mobile @media block not found"
    start = m.end()
    depth = 1
    i = start
    while i < len(index_html_text) and depth > 0:
        c = index_html_text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    block = index_html_text[start : i - 1]
    for selector in [
        ".research-layout",
        ".dashboard-grid",
        ".header",
        ".inv-grid",
        ".mem-grid",
        ".tab-btn",
    ]:
        assert selector in block, f"{selector} is not inside the mobile media query"


def test_chat_input_is_textarea(index_soup):
    """Chat prompt must be a <textarea> so Shift+Enter can insert newlines."""
    el = index_soup.find(id="prompt")
    assert el is not None, "#prompt element missing"
    assert el.name == "textarea", f"#prompt is <{el.name}>, must be <textarea>"


def test_chat_input_has_shift_enter_handler(index_html_text):
    """JS must distinguish Enter (send) from Shift+Enter (newline)."""
    assert (
        "e.shiftKey" in index_html_text or "shiftKey" in index_html_text
    ), "Shift+Enter branch missing from keydown handler"


def test_switchtab_does_not_rely_on_bare_event_global(index_html_text):
    """switchTab must accept the element explicitly, not read a bare global."""
    # Extract the switchTab function body.
    m = re.search(r"function\s+switchTab\s*\(([^)]*)\)\s*\{", index_html_text)
    assert m is not None, "switchTab function not found"
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    # Signature must include an element param alongside name.
    assert (
        len(params) >= 2
    ), f"switchTab signature is {params!r}; must accept (name, el)"
    # And no caller may still rely on the implicit `event` global:
    # find function body bounds.
    start = m.end()
    depth = 1
    i = start
    while i < len(index_html_text) and depth > 0:
        c = index_html_text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    body = index_html_text[start : i - 1]
    assert (
        "event.currentTarget" not in body
    ), "switchTab still references event.currentTarget — use the el parameter"


def test_index_does_not_load_external_cdns(index_html_text):
    """Privacy promise: no external CDN loads in the shipped HTML."""
    for needle in [
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
    ]:
        assert (
            needle not in index_html_text
        ), f"external CDN reference remains: {needle}"


def test_setup_does_not_load_external_cdns(setup_html_text):
    """Setup wizard must also run offline."""
    for needle in [
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
    ]:
        assert (
            needle not in setup_html_text
        ), f"setup.html external CDN reference remains: {needle}"


def test_color_tokens_are_honest(index_html_text):
    """Token values must match their semantic name.

    --amber rendering as green and --warn missing entirely were caught
    in the audit; this guards against regression.
    """
    m = re.search(r":root\s*\{([^}]*)\}", index_html_text)
    assert m is not None, ":root CSS variable block not found"
    root = m.group(1)

    def hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def is_green(hex_str: str) -> bool:
        r, g, b = hex_to_rgb(hex_str)
        return g > r and g > b

    # If --warn is defined, its base hex (not an alias) must actually be
    # amber/orange — i.e. NOT green-dominant.
    warn = re.search(r"--warn:\s*#([0-9A-Fa-f]{6})\b", root)
    assert (
        warn is not None
    ), "--warn token missing — introduce a real amber for warnings"
    assert not is_green(
        warn.group(1)
    ), f"--warn resolves to green #{warn.group(1)} — must be amber/orange"

    # --danger must also exist as a real red.
    danger = re.search(r"--danger:\s*#([0-9A-Fa-f]{6})\b", root)
    assert danger is not None, "--danger token missing"
    dr, dg, db = hex_to_rgb(danger.group(1))
    assert dr > dg and dr > db, f"--danger #{danger.group(1)} is not red-dominant"


def test_no_sci_fi_caps_verbs_in_button_text(index_html_text):
    """Button text should be sentence case; uppercase styling comes from CSS."""
    # We search for these as whole-word literals on lines that look like
    # markup/text, not as substrings inside CSS class names like .transmit.
    for verb in ["TRANSMIT", "EXECUTE", "DIVE"]:
        # Exclude occurrences inside element-content like >TRANSMIT< or 'TRANSMIT'
        pattern = r">\s*" + verb + r"\s*<|textContent\s*=\s*['\"]" + verb + r"['\"]"
        m = re.search(pattern, index_html_text)
        assert (
            m is None
        ), f"'{verb}' still appears in button text or JS — use sentence case"


def test_focus_visible_outline_exists(index_html_text):
    """Global :focus-visible rule must exist for keyboard accessibility."""
    m = re.search(
        r":focus-visible\s*\{[^}]*outline\s*:",
        index_html_text,
    )
    assert m is not None, "no global :focus-visible outline rule found"


def test_api_mounts_static_directory():
    """api/main.py must mount /static so vendor assets and favicon serve.

    Pre-existing silent bug: StaticFiles was imported but never mounted,
    so favicon and every /static/* request 404'd. Task 6's self-hosted
    fonts exposed this — test ensures the mount remains wired up.
    """
    from pathlib import Path

    main_py = (Path(__file__).resolve().parents[2] / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    assert (
        'app.mount("/static"' in main_py
    ), "api/main.py must mount /static — vendor/ and favicon depend on it"
    assert (
        "StaticFiles(directory=STATIC_DIR)" in main_py
    ), "mount must use StaticFiles(directory=STATIC_DIR)"


def test_vendor_css_references_only_local_paths(index_html_text):
    """Task 6 sibling check: every stylesheet <link> must be local-only."""
    # Match any <link> with rel="stylesheet", regardless of attribute order.
    hrefs: list[str] = []
    for tag in re.finditer(r"<link[^>]+>", index_html_text):
        tag_text = tag.group(0)
        if 'rel="stylesheet"' not in tag_text and "rel='stylesheet'" not in tag_text:
            continue
        m = re.search(r'href=["\']([^"\']+)["\']', tag_text)
        if m:
            hrefs.append(m.group(1))
    assert hrefs, "no stylesheet <link> tags found"
    for href in hrefs:
        assert href.startswith("/") or href.startswith(
            "./"
        ), f"stylesheet href '{href}' is not a relative/root-relative path"
        assert "//" not in href.replace("http://", "").replace(
            "https://", ""
        ), f"stylesheet href '{href}' looks external"


def test_workflows_tab_has_roles_subsection(index_html_text):
    """Workflows tab must expose a Roles subsection so role_ref is browseable."""
    assert (
        'id="wf-roles-list"' in index_html_text
    ), "roles list container missing from Workflows tab"
    assert "/api/roles" in index_html_text, "frontend does not call /api/roles"


def test_pipeline_renderer_references_hooks(index_html_text):
    """Pipeline renderer must reference step.hooks and prompt.role_ref."""
    assert (
        "step.hooks" in index_html_text or 'step["hooks"]' in index_html_text
    ), "pipeline renderer does not reference step.hooks — hooks will not render"
    assert (
        "role_ref" in index_html_text
    ), "pipeline renderer does not reference prompt.role_ref"


def test_results_renderer_shows_retries_and_model(index_html_text):
    """Results renderer must surface retries count and model_used."""
    assert (
        "retries" in index_html_text
    ), "results renderer does not reference StepResult.retries"
    assert (
        "model_used" in index_html_text
    ), "results renderer does not reference StepResult.model_used"


def test_chat_panel_sits_on_first_dashboard_row(index_html_text):
    """Chat must be the primary surface — row 1, spanning all columns."""
    m = re.search(
        r"\.dashboard-grid\s+\.panel-chat\s*\{([^}]+)\}",
        index_html_text,
    )
    assert m is not None, ".panel-chat grid rule not found"
    body = m.group(1)
    assert (
        "grid-row: 1" in body
    ), "panel-chat is not on grid-row 1 — chat should sit above the metrics row"
    assert "grid-column: 1 / -1" in body, "panel-chat must span all dashboard columns"


def test_results_have_context_inspector(index_html_text):
    """Workflow results must render the three-layer context (seed/workspace/shared)."""
    assert (
        "renderContextInspector" in index_html_text
    ), "renderContextInspector function missing — context-store has no UI"
    # The inspector must pull all three layers, not just one.
    for layer in ("seed", "workspace", "shared"):
        assert (
            f"ctx.{layer}" in index_html_text
        ), f"context inspector never reads ctx.{layer}"


def test_chat_has_system_prompt_row(index_html_text):
    """Chat must expose a system-prompt row wired to the role library."""
    assert (
        'id="system-prompt"' in index_html_text
    ), "system-prompt <textarea> missing from chat panel"
    assert (
        'id="sysprompt-role-select"' in index_html_text
    ), "role dropdown for system prompt missing"
    # sendMessage must actually prepend the system message when present.
    assert (
        "getSystemPromptMessage" in index_html_text
    ), "sendMessage must prepend the saved system prompt"
    assert (
        "role: 'system'" in index_html_text
    ), "no role=system turn is ever emitted — system prompt wiring broken"


def test_header_uses_installer_enclave_mark(index_html_text):
    """Header logo must match the canonical Enclave mark used by the installer."""
    # Reject the legacy hexagon + 'EN/CL' typographic placeholder
    assert (
        'class="logo-hex"' not in index_html_text
    ), "legacy .logo-hex still in header — swap to .logo-mark"
    # Assert the canonical mark is present (nested rects)
    assert (
        'class="logo-mark"' in index_html_text
    ), ".logo-mark container missing from header"
    # And the 4 nested rects — signature of the installer Enclave mark
    rect_count = index_html_text.count("<rect ")
    assert (
        rect_count >= 4
    ), f"installer Enclave mark expects 4 nested <rect> elements; found {rect_count}"


def test_admin_dropdown_present(index_soup):
    """An Admin dropdown trigger must exist in the tab strip."""
    trigger = index_soup.find(id="admin-trigger")
    assert trigger is not None, "#admin-trigger missing from tab strip"
    assert trigger.get("aria-haspopup") == "menu"
    assert trigger.get("aria-expanded") == "false"


def test_admin_menu_has_three_items(index_soup):
    """Admin menu must list API Keys, Plugins, Exports."""
    menu = index_soup.find(id="admin-menu")
    assert menu is not None
    items = menu.find_all(attrs={"role": "menuitem"})
    panels = {i.get("data-panel") for i in items}
    assert {"admin-keys", "admin-plugins", "admin-exports"}.issubset(panels)


def test_admin_panel_containers_exist(index_soup):
    """Three .tab-content panels must exist (initially hidden)."""
    for pid in ("tab-admin-keys", "tab-admin-plugins", "tab-admin-exports"):
        el = index_soup.find(id=pid)
        assert el is not None, f"#{pid} container missing"


def test_admin_auth_uses_session_storage(index_html_text):
    """Auth state must be in sessionStorage, never localStorage."""
    assert "sessionStorage" in index_html_text, "AdminAuth missing"
    assert (
        "enclave.admin.masterKey" in index_html_text
    ), "expected sessionStorage key 'enclave.admin.masterKey'"


def test_admin_auth_does_not_persist_in_local_storage(index_html_text):
    """Master key must never be written to localStorage."""
    # Crude but effective: there should be NO 'localStorage.setItem' anywhere
    # near the master-key wiring. Refine if false positives appear.
    import re

    matches = re.findall(
        r"localStorage\.setItem\([^)]*master[^)]*\)", index_html_text, re.I
    )
    assert not matches, f"master key written to localStorage: {matches}"


def test_admin_signin_modal_present(index_soup):
    """A modal for entering the master key must exist."""
    modal = index_soup.find(id="admin-signin-modal")
    assert modal is not None
    pwd = modal.find("input", attrs={"type": "password"})
    assert pwd is not None, "modal must include a <input type=password>"


def test_render_markdown_helper_present(index_html_text):
    """A renderMarkdown helper must be defined in the script block."""
    assert (
        "function renderMarkdown" in index_html_text
        or "renderMarkdown =" in index_html_text
        or "window.renderMarkdown" in index_html_text
    ), "renderMarkdown helper missing"


def test_api_keys_panel_has_list_container(index_html_text):
    """The API Keys panel must include a list container and a refresh button."""
    assert 'id="api-keys-list"' in index_html_text
    assert (
        "loadApiKeysPanel" in index_html_text or "ApiKeysPanel.load" in index_html_text
    )


def test_api_keys_panel_has_new_key_button(index_html_text):
    assert (
        "showCreateKeyModal" in index_html_text
        or "showNewKeyModal" in index_html_text
        or "ApiKeysPanel.showCreate" in index_html_text
    ), "expected a 'New Key' trigger function"


def test_create_key_modal_present(index_soup):
    modal = index_soup.find(id="create-key-modal")
    assert modal is not None
    name = modal.find(id="new-key-name")
    scopes_field = modal.find(id="new-key-scopes")
    assert name is not None and scopes_field is not None


def test_create_key_modal_has_one_time_reveal_warning(index_html_text):
    """The reveal area must say the key is shown once."""
    needle = "only time"
    assert (
        needle in index_html_text.lower()
    ), "expected one-time-reveal warning copy in create-key modal"


def test_create_key_modal_has_copy_button(index_html_text):
    assert (
        "navigator.clipboard.writeText" in index_html_text
        or "copyKey" in index_html_text
    ), "expected a clipboard copy mechanism"


def test_api_keys_panel_has_audit_strip(index_html_text):
    """Audit log strip must be present and call /api/keys/audit."""
    assert 'id="api-keys-audit"' in index_html_text
    assert "/api/keys/audit" in index_html_text


def test_api_keys_panel_has_rotate_and_revoke_handlers(index_html_text):
    assert "ApiKeysPanel.rotate" in index_html_text
    assert "ApiKeysPanel.revoke" in index_html_text


def test_plugins_panel_has_warning_banner(index_html_text):
    """Plugins panel must show a non-dismissable warning about in-process exec."""
    assert (
        "execute plugin code" in index_html_text.lower()
    ), "expected warning copy about in-process plugin execution"


def test_plugins_panel_has_two_pane_layout(index_html_text):
    assert 'id="plugins-list"' in index_html_text
    assert 'id="plugin-detail"' in index_html_text


def test_plugins_panel_has_tool_tester(index_html_text):
    """Each tool accordion must contain a Run button + result container."""
    assert (
        "tool-tester-run" in index_html_text
        or "PluginsPanel.runTool" in index_html_text
    ), "expected a tool-tester run handler"


def test_plugins_panel_has_param_form_renderer(index_html_text):
    assert (
        "renderToolForm" in index_html_text or "buildToolForm" in index_html_text
    ), "expected a tool-form renderer"


def test_exports_panel_has_list(index_html_text):
    assert 'id="exports-list"' in index_html_text
    assert "ExportsPanel.refresh" in index_html_text


def test_exports_panel_has_view_modal(index_html_text):
    assert 'id="export-view-modal"' in index_html_text


def test_exports_panel_has_zip_action(index_html_text):
    assert "/api/exports/zip" in index_html_text
    assert "ExportsPanel.downloadZip" in index_html_text


def test_exports_panel_has_bulk_delete(index_html_text):
    assert "ExportsPanel.bulkDelete" in index_html_text


def test_exports_zip_uses_get_with_names_param(index_html_text):
    """Zip endpoint takes a comma-separated names param via GET."""
    import re

    # Look for fetch('/api/exports/zip?names=...') or similar.
    assert re.search(
        r"/api/exports/zip\?names=", index_html_text
    ), "expected zip request to use ?names= query"
