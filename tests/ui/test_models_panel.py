"""LB4-U2 — Models library master-detail panel on the LibraryShell.

Two layers, mirroring test_skills_shell.py / test_library_shell.py:

1. Static assertions (bs4 / served-JS corpus): #models-shell is the single
   visible models surface on tab-inventory while the pre-shell catalog
   surface parks in the hidden #inv-legacy-holder with ids unchanged (F2);
   CatalogModelsShare is retargeted to return nodes to the holder; the
   inventory tab activation performs exactly ONE inventory fetch
   (ModelsPanel.activate, no loadCatalog); the models.* action grammar is
   complete with the shared legacy ids routed by data-shell="models"; the
   adapter rides the LB0 row contract (fit dot classes straight from the
   /catalog fit payload, runner badge, task-tag chips); privacy — the
   adapter load NEVER reads /api/inventory/discover (its read path can
   still fetch — follow-up #15); tags PATCH + pull + remove are retries:0
   with Confirm on remove; the Test slot mounts the LB1 TestPane model
   adapter; Recommended prompts rides GET /api/prompts/recommend?model=
   with a LibraryShell.open jump.

2. Runtime tests (Playwright against the dev server, skipped when
   unreachable): exactly one visible models surface, the legacy nodes still
   relocate to the Catalog page and return to the hidden holder, the NVFP4 /
   first-row Weights section renders populated (never empty), fit dot
   classes match the live /catalog fit payload, and the Recommended prompts
   section renders the deterministic scorer output.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
PANEL_JS = (STATIC / "js" / "library" / "models-panel.js").read_text(encoding="utf-8")
MODELS_JS = (STATIC / "js" / "library" / "models.js").read_text(encoding="utf-8")
SHELL_JS = (STATIC / "js" / "library" / "shell.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")


# ── 1. Static: models.* action grammar ─────────────────────────────────────


def test_models_panel_ships_every_spec_action():
    for action in [
        "models.select", "models.pull", "models.remove", "models.review",
        "models.test", "models.edit-tags", "models.intent",
        "models.refresh-discover",
    ]:
        assert f"'{action}'" in PANEL_JS, f"models-panel.js missing action {action}"


def test_models_adapter_contract_fields():
    assert "kind: 'model'" in PANEL_JS
    assert "tabId: 'inventory'" in PANEL_JS
    assert "countBadgeId: 'inv-count'" in PANEL_JS, "#inv-count must be fed"
    m = re.search(r"auth:\s*'(\w+)'", PANEL_JS)
    assert m and m.group(1) == "optional", (
        "model adapter is read-open with merged AdminAuth headers on writes — "
        "'optional' tier, never a wall"
    )
    assert "selectAction: 'models.select'" in PANEL_JS
    # Spec detail sections in spec order (Summary → Weights → Performance →
    # Hardware fit → Relations → Recommended prompts → Test).
    assert re.search(
        r"sectionOrder:\s*\['overview',\s*'weights',\s*'performance',\s*'fit',"
        r"\s*'relations',\s*'prompts',\s*'test'\]", PANEL_JS)
    for key in ["weights:", "performance:", "fit:", "relations:", "prompts:"]:
        assert key in PANEL_JS, f"detail section {key} missing"


def test_models_panel_no_inline_handlers_or_window_globals():
    assert not re.search(r"\son[a-z]+\s*=\s*\"", PANEL_JS), "inline handler in models-panel.js"
    assert not re.search(r"window\.[A-Za-z_$][\w$]*\s*=[^=]", PANEL_JS), (
        "new window global assigned in models-panel.js"
    )


def test_models_rows_ride_the_lb0_row_contract():
    # fit dot (class from the /catalog fit payload), runner badge, task-tag
    # chips with the +n overflow — through the contract fields, not bespoke
    # card markup.
    assert "dot: { cls: `fit-${esc(cls)}`" in PANEL_JS, (
        "fit dot class must come straight from the fit payload class"
    )
    for needle in ["chips", "badges", "models-runner runner-", "taskTags.slice(0, 3)"]:
        assert needle in PANEL_JS, f"row-contract wiring missing: {needle}"
    assert "+${taskTags.length - 3}" in PANEL_JS


# ── 2. Static: hidden legacy holder + single visible surface (F2) ──────────


def test_single_visible_models_surface_static(index_soup):
    tab = index_soup.find(id="tab-inventory")
    assert tab is not None
    shell = tab.find(id="models-shell")
    assert shell is not None, "#models-shell missing from tab-inventory"
    holder = tab.find(id="inv-legacy-holder")
    assert holder is not None, "#inv-legacy-holder missing from tab-inventory"
    assert holder.has_attr("hidden"), "legacy holder must ship hidden"
    # Legacy nodes parked inside the holder, ids UNCHANGED.
    for el_id in ["inv-stats", "inv-grid", "inv-search", "hw-info"]:
        assert holder.find(id=el_id) is not None, f"#{el_id} not parked in the holder"
    # The shell must NOT be inside the holder.
    assert holder.find(id="models-shell") is None
    # Relocator id survives elsewhere in the document (only-add).
    assert index_soup.find(id="discover-section") is not None
    # Toolbar affordances: intent dropdown + operator-triggered discover refresh.
    intent = tab.find(id="models-intent")
    assert intent is not None and intent.get("data-action") == "models.intent"
    refresh = tab.find(id="models-refresh-discover")
    assert refresh is not None and refresh.get("data-action") == "models.refresh-discover"


def test_relocator_retargeted_to_the_holder():
    # showInModelsTab() returns nodes to #inv-legacy-holder (fallback:
    # tab-inventory pre-holder); the relocated id set is unchanged.
    assert "inv-legacy-holder" in MODELS_JS
    assert "const ids = ['inv-stats', 'inv-grid', 'discover-section'];" in MODELS_JS
    assert "showInCatalog" in MODELS_JS and "showInModelsTab" in MODELS_JS


def test_inventory_tab_activation_single_fetch():
    m = re.search(r"if \(name === 'inventory'\) \{(.*?)\n  \}", MAIN_JS, re.S)
    assert m, "switchTab inventory branch missing"
    branch = m.group(1)
    assert "ModelsPanel.activate()" in branch
    assert "loadCatalog(" not in branch, (
        "inventory tab must not call loadCatalog — the shell's catalog read "
        "is the tab's ONE /api/inventory fetch (F2)"
    )
    assert "CatalogModelsShare.showInModelsTab()" in branch
    # The "Installed Locally" residency panel was retired; the inventory tab no
    # longer calls its loader (Unload moved into the model drill-down).
    assert "loadInstalledLocal()" not in branch
    # The Catalog page keeps the legacy loader alive.
    wf = re.search(r"if \(name === 'workflows'\) \{(.*?)\n  \}", MAIN_JS, re.S)
    assert wf and "loadCatalog" in wf.group(1), "Catalog page lost loadCatalog"


def test_shared_action_ids_route_shell_clicks_to_the_panel():
    # only-add: legacy grid handlers stay byte-equivalent; data-shell="models"
    # branches into ModelsPanel.
    assert "el.dataset.shell === 'models'" in MAIN_JS
    for needle in ["ModelsPanel.remove(", "ModelsPanel.pull(", "ModelsPanel.test("]:
        assert needle in MAIN_JS, f"shell routing missing: {needle}"
    for legacy in ["removeModel(el.dataset.model)",
                   "pullModel(el.dataset.model, el.dataset.modelId)",
                   "testModel(el.dataset.model)",
                   "reviewModel(el.dataset.repo)"]:
        assert legacy in MAIN_JS, f"legacy handler lost: {legacy}"


# ── 3. Static: privacy + write discipline ───────────────────────────────────


def test_adapter_load_never_reads_the_discover_route():
    load_block = re.search(r"async load\(\)(.*?)\n    },", PANEL_JS, re.S)
    assert load_block, "adapter load() missing"
    assert "/api/inventory/discover" not in load_block.group(1), (
        "adapter.load must not touch /api/inventory/discover — its read path "
        "can still fetch (TTL-on-read, follow-up #15); discovery data fills "
        "only via the operator's refresh button"
    )
    assert "/api/inventory/catalog" in load_block.group(1)


def test_discover_refresh_is_operator_triggered_master_key_post():
    m = re.search(r"async function refreshDiscover\(\)(.*?)\n  \}", PANEL_JS, re.S)
    assert m, "refreshDiscover missing"
    body = m.group(1)
    assert "/api/inventory/discover/refresh" in body
    assert "retries: 0" in body
    assert "method: 'POST'" in body


def test_tags_patch_wiring():
    m = re.search(r"async function saveTags\(id\)(.*?)\n  \}", PANEL_JS, re.S)
    assert m, "saveTags missing"
    body = m.group(1)
    assert "/tags" in body and "method: 'PATCH'" in body
    assert "retries: 0" in body
    assert "_headers()" in body, "tags PATCH must carry AdminAuth headers"


def test_remove_confirm_gated_retries_zero():
    m = re.search(r"async function remove\(id\)(.*?)\n  \}", PANEL_JS, re.S)
    assert m, "remove missing"
    body = m.group(1)
    assert "Confirm.ask" in body
    assert "/api/inventory/remove" in body
    assert "retries: 0" in body


def test_pull_retries_zero_with_progress_poll():
    m = re.search(r"async function pull\(id, model\)(.*?)\n  \}", PANEL_JS, re.S)
    assert m, "pull missing"
    body = m.group(1)
    assert "/api/inventory/pull'" in body and "retries: 0" in body
    assert "/api/inventory/pull-progress/" in body


# ── 4. Static: detail sections wiring ───────────────────────────────────────


def test_test_slot_mounts_lb1_model_adapter_with_backend_ctx():
    assert "TestPane.mount('model'" in PANEL_JS
    # vLLM-pinned models get the disabled-with-reason Warm (ctx.backend).
    assert "backend: _runner(m) === 'vllm' ? 'vllm' : ''" in PANEL_JS


def test_recommended_prompts_scorer_and_jump():
    assert "/api/prompts/recommend?model=" in PANEL_JS
    assert "LibraryShell.open('prompt'" in PANEL_JS
    # per-factor breakdown rendered, not hidden
    for factor in ["task_tags", "model_fit", "size_fit"]:
        assert factor in PANEL_JS, f"factor {factor} missing from breakdown"


def test_intent_recommendations_wiring():
    assert "/api/inventory/recommendations?intent=" in PANEL_JS
    assert "models-rec-strip" in PANEL_JS
    # Pull affordance on not-installed ranked models
    assert "x.pull && x.pull.model" in PANEL_JS


def test_weights_degrades_to_registry_fields():
    m = re.search(r"async function _renderWeights\(el, id\)(.*?)\n  \}", PANEL_JS, re.S)
    assert m, "_renderWeights missing"
    body = m.group(1)
    # registry/catalog intrinsics render unconditionally…
    for field in ["arch_family", "params_b", "quant", "context_tokens", "size_gb", "min_arch"]:
        assert field in body, f"registry field {field} missing from Weights"
    # …and the model_info join only rides installed models.
    assert "m.installed" in body and "/api/inventory/model/" in PANEL_JS


def test_performance_reads_curated_arch_class_meta():
    m = re.search(r"async function _renderPerformance\(el, id\)(.*?)\n  \}", PANEL_JS, re.S)
    assert m, "_renderPerformance missing"
    assert "arch_class_perf" in m.group(1)
    assert "/api/inventory/enrichment" in PANEL_JS
    assert "/api/system/architecture" in PANEL_JS


def test_shell_supports_adapter_section_order_additively():
    # LB4-U2 additive shell seam: adapter-supplied order/labels, default
    # behavior untouched when absent.
    assert "a.sectionOrder || SECTION_ORDER" in SHELL_JS
    assert "a.sectionLabels && a.sectionLabels[s]" in SHELL_JS


def test_models_css_grammar_present(index_html_text):
    for sel in [".lib-dot.fit-no-fit", ".lib-dot.fit-unknown",
                ".models-rec-strip", ".models-rec-row", ".models-perf-table",
                ".models-fit-bar", ".models-prompt-row", ".models-toolbar",
                ".lib-badge.models-runner"]:
        assert sel in index_html_text, f"CSS selector {sel} missing"


# ── 5. Runtime (Playwright, skip when server down) ─────────────────────────

BASE_URL = os.environ.get("ENCLAVE_PLAYWRIGHT_BASE_URL", "http://localhost:8000")


def _server_up() -> bool:
    import requests

    try:
        return requests.get(f"{BASE_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False


requires_server = pytest.mark.skipif(
    not _server_up(), reason=f"Enclave dev server not reachable at {BASE_URL}"
)


def _catalog():
    import requests

    return requests.get(f"{BASE_URL}/api/inventory/catalog", timeout=20).json()


@pytest.fixture()
def shell_page(page):
    """Booted, signed-in SPA page (mirrors tests/playwright signed_in_page)."""
    import requests

    key = requests.get(f"{BASE_URL}/api/setup/local-license", timeout=5).json().get("key", "")
    page.goto(f"{BASE_URL}/")
    page.evaluate(
        """(key) => {
            window.localStorage.setItem('enclave.licenseKey', key);
            window.localStorage.setItem('enclave.theme', 'dark');
        }""",
        key,
    )
    page.goto(f"{BASE_URL}/")
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=10_000)
    return page


def _open_models_tab(page):
    page.evaluate("() => switchTab('inventory')")
    page.wait_for_selector("#tab-inventory", state="visible", timeout=5_000)
    page.wait_for_selector("#models-shell .lib-row", timeout=15_000)


@requires_server
def test_exactly_one_visible_models_surface(shell_page):
    page = shell_page
    _open_models_tab(page)
    state = page.evaluate(
        """() => ({
            shellVisible: !!document.querySelector('#models-shell')?.offsetParent,
            holderHidden: document.getElementById('inv-legacy-holder')?.hidden === true,
            gridVisible: !!document.getElementById('inv-grid')?.offsetParent,
            gridInHolder: !!document.querySelector('#inv-legacy-holder #inv-grid'),
        })"""
    )
    assert state["shellVisible"], "#models-shell must be the visible surface"
    assert state["holderHidden"], "#inv-legacy-holder must stay hidden on the tab"
    assert not state["gridVisible"], "legacy #inv-grid must not render alongside the shell"
    assert state["gridInHolder"], "legacy #inv-grid must be parked inside the holder"


@requires_server
def test_legacy_nodes_relocate_to_catalog_and_return_to_holder(shell_page):
    page = shell_page
    _open_models_tab(page)
    # → Catalog page: the SAME nodes move into the Catalog Models mount.
    page.evaluate("() => switchTab('workflows')")
    page.wait_for_selector("#catalog-models-mount #inv-grid", timeout=10_000)
    # ← Models tab: nodes return to the hidden holder, not the visible tab.
    page.evaluate("() => switchTab('inventory')")
    # attached, not visible — the holder is (deliberately) hidden
    page.wait_for_selector("#inv-legacy-holder #inv-grid", state="attached", timeout=10_000)
    assert page.evaluate(
        "() => !!document.querySelector('#tab-inventory #inv-grid')"
    ), "#inv-grid must remain a descendant of #tab-inventory (pinned by e2e)"
    assert not page.evaluate("() => !!document.getElementById('inv-grid')?.offsetParent")


@requires_server
def test_fit_dot_classes_match_catalog_fit_payload(shell_page):
    page = shell_page
    cat = _catalog()
    with_fit = [m for m in cat.get("models", []) if (m.get("fit") or {}).get("class")]
    assert with_fit, "catalog carries no fit payload — LB4-U1 regression?"
    _open_models_tab(page)
    checked = 0
    for m in with_fit[:5]:
        cls = page.evaluate(
            """(id) => {
                const row = document.querySelector(`#models-shell .lib-row[data-id="${id}"]`);
                const dot = row && row.querySelector('.lib-dot');
                return dot ? dot.className : null;
            }""",
            m["id"],
        )
        if cls is None:
            continue  # row filtered/collapsed — other entries cover it
        assert f"fit-{m['fit']['class']}" in cls, (
            f"row dot for {m['id']} carries '{cls}', expected fit-{m['fit']['class']}"
        )
        checked += 1
    assert checked > 0, "no shell rows matched catalog ids"


def _select_model(page, model_id):
    page.evaluate(
        """(id) => document.querySelector(`#models-shell .lib-row[data-id="${id}"]`)?.click()""",
        model_id,
    )
    page.wait_for_selector("#lib-model-detail .lib-subnav-pill", timeout=5_000)


@requires_server
def test_weights_section_populated_from_registry_fields(shell_page):
    page = shell_page
    cat = _catalog()
    models = cat.get("models", [])
    # Prefer the flagship NVFP4 / vLLM entry — the degrade-to-registry branch
    # the spec pins ("never empty"); fall back to the first catalog model.
    target = next(
        (m for m in models if "nvfp4" in str(m.get("id", "")).lower()
         or (m.get("runner") == "vllm")
         or (m.get("installed_info") or {}).get("backend") == "vllm"),
        models[0] if models else None,
    )
    assert target, "empty catalog"
    _open_models_tab(page)
    _select_model(page, target["id"])
    page.click('#lib-model-detail .lib-subnav-pill[data-section="weights"]')
    page.wait_for_timeout(1200)
    text = page.evaluate(
        "() => document.querySelector('#lib-model-detail .lib-section[data-section=\"weights\"]')?.innerText || ''"
    )
    assert text.strip(), "Weights section rendered empty"
    for label in ["Family", "Quantization", "Weights size", "Min arch"]:
        assert label in text, f"Weights section missing '{label}' row"


@requires_server
def test_recommended_prompts_renders_scorer_output(shell_page):
    page = shell_page
    cat = _catalog()
    models = cat.get("models", [])
    assert models, "empty catalog"
    _open_models_tab(page)
    _select_model(page, models[0]["id"])
    page.click('#lib-model-detail .lib-subnav-pill[data-section="prompts"]')
    # the shell's lazy "Loading…" placeholder also carries .model-empty —
    # wait until the section settled on scorer rows or a real empty-state
    page.wait_for_function(
        """() => {
            const s = document.querySelector('#lib-model-detail .lib-section[data-section="prompts"]');
            return s && s.innerText && !s.innerText.includes('Loading…');
        }""",
        timeout=10_000,
    )
    rows = page.locator('#lib-model-detail .lib-section[data-section="prompts"] .models-prompt-row')
    if rows.count() == 0:
        pytest.skip("no installed prompts scored — scorer corpus empty on this box")
    first = rows.first
    # per-factor breakdown chips + the open-in-Prompts jump
    assert first.locator(".models-prompt-factors .lib-chip").count() >= 3
    assert first.locator('[data-action="models.open-prompt"]').count() == 1
