"""
End-to-End Dashboard Tests — Playwright

Tests the full dashboard UI: navigation, tabs, workflow DAG, model listing,
chat interface, and agent gallery. Runs against the live FastAPI server.

Usage:
    pytest tests/test_e2e_dashboard.py -v --headed  # visible browser
    pytest tests/test_e2e_dashboard.py -v            # headless

Requires:
    pip install playwright pytest-playwright
    playwright install chromium
    # Server must be running: uvicorn api.main:app --port 8000
"""

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:8000"


@pytest.fixture(scope="module")
def server_check():
    """Verify the server is running before tests"""
    import requests
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        if resp.status_code != 200:
            pytest.skip("API server not running at localhost:8000")
    except Exception:
        pytest.skip("API server not running at localhost:8000")


# ── Navigation & Layout ──────────────────────────────────────────────────


class TestDashboardNavigation:
    def test_loads_homepage(self, page: Page, server_check):
        page.goto(BASE_URL)
        expect(page.locator(".logo-title")).to_be_visible()
        expect(page.locator("text=LOCAL")).to_be_visible()
        expect(page.locator("text=CORTEX")).to_be_visible()

    def test_has_all_tabs(self, page: Page, server_check):
        page.goto(BASE_URL)
        tabs = ["DASHBOARD", "MODELS", "MEMORY", "DISCOVER", "RESEARCH", "WORKFLOWS", "AGENTS"]
        for tab in tabs:
            expect(page.locator(f"button.tab-btn:has-text('{tab}')")).to_be_visible()

    def test_tab_switching(self, page: Page, server_check):
        page.goto(BASE_URL)
        # Click Models tab
        page.click("button.tab-btn:has-text('Models')")
        expect(page.locator("#tab-inventory")).to_be_visible()
        # Click Workflows tab
        page.click("button.tab-btn:has-text('Workflows')")
        expect(page.locator("#tab-workflows")).to_be_visible()
        # Click back to Dashboard
        page.click("button.tab-btn:has-text('Dashboard')")
        expect(page.locator("#tab-dashboard")).to_be_visible()

    def test_clock_and_uptime(self, page: Page, server_check):
        page.goto(BASE_URL)
        clock = page.locator("#clock")
        expect(clock).to_be_visible()
        # Clock should show time (not --:--)
        page.wait_for_timeout(1500)
        expect(clock).not_to_have_text("--:--")


# ── Dashboard Tab ─────────────────────────────────────────────────────────


class TestDashboardTab:
    def test_system_status_panel(self, page: Page, server_check):
        page.goto(BASE_URL)
        expect(page.locator("text=SYSTEM STATUS")).to_be_visible()
        expect(page.locator("text=API")).to_be_visible()
        expect(page.locator("text=Ollama")).to_be_visible()

    def test_api_shows_running(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.wait_for_timeout(2000)
        expect(page.locator("text=Running")).to_be_visible()

    def test_loaded_models_list(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.wait_for_timeout(2000)
        expect(page.locator("text=LOADED MODELS")).to_be_visible()

    def test_performance_gauges(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.wait_for_timeout(2000)
        expect(page.locator("text=PERFORMANCE")).to_be_visible()
        expect(page.locator("text=CPU")).to_be_visible()
        expect(page.locator("text=MEM")).to_be_visible()

    def test_chat_interface_visible(self, page: Page, server_check):
        page.goto(BASE_URL)
        expect(page.locator("text=CHAT INTERFACE")).to_be_visible()
        expect(page.locator("#prompt")).to_be_visible()
        expect(page.locator("#model-select")).to_be_visible()


# ── Models (Inventory) Tab ────────────────────────────────────────────────


class TestModelsTab:
    def test_model_catalog_loads(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Models')")
        page.wait_for_timeout(2000)
        # Should show at least one model card
        cards = page.locator(".inv-card")
        expect(cards.first).to_be_visible(timeout=10000)

    def test_filter_buttons(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Models')")
        page.wait_for_timeout(1000)
        filters = ["ALL", "INSTALLED", "AVAILABLE"]
        for f in filters:
            btn = page.locator(f".filter-btn:has-text('{f}')")
            expect(btn).to_be_visible()

    def test_search_input(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Models')")
        search = page.locator("#inv-search")
        expect(search).to_be_visible()
        search.fill("deepseek")
        page.wait_for_timeout(500)


# ── Workflows Tab ─────────────────────────────────────────────────────────


class TestWorkflowsTab:
    def test_workflow_selector_loads(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(2000)
        select = page.locator("#wf-select")
        expect(select).to_be_visible()
        # Should have at least 2 workflows (data-model-rules + xsiam-normalization-pipeline)
        options = select.locator("option")
        assert options.count() >= 3  # including "-- select workflow --"

    def test_load_workflow_renders_dag(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1500)
        # Select the XSIAM pipeline
        page.select_option("#wf-select", label=page.locator("#wf-select option").all_text_contents()[-1])
        page.click("button:has-text('Load')")
        page.wait_for_timeout(3000)
        # DAG canvas should have SVG nodes
        svg = page.locator("#wf-dag-canvas svg")
        expect(svg).to_be_visible(timeout=10000)
        # Should have node rectangles
        rects = svg.locator("rect")
        assert rects.count() >= 4

    def test_dag_node_click_shows_inspector(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1500)
        page.select_option("#wf-select", label=page.locator("#wf-select option").all_text_contents()[-1])
        page.click("button:has-text('Load')")
        page.wait_for_timeout(3000)
        # Click a node in the SVG
        first_node = page.locator("#wf-dag-canvas svg g.dag-nodes g").first
        if first_node.is_visible():
            first_node.click()
            page.wait_for_timeout(500)
            # Inspector should show step details
            inspector = page.locator("#wf-inspector-content")
            expect(inspector).not_to_have_text("Select a node")

    def test_dag_stats_bar(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1500)
        page.select_option("#wf-select", label=page.locator("#wf-select option").all_text_contents()[-1])
        page.click("button:has-text('Load')")
        page.wait_for_timeout(3000)
        stats = page.locator("#wf-dag-stats")
        expect(stats).to_be_visible()
        expect(stats).to_contain_text("Steps:")
        expect(stats).to_contain_text("Batches:")

    def test_seed_input_validation(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1500)
        page.select_option("#wf-select", label=page.locator("#wf-select option").all_text_contents()[-1])
        page.click("button:has-text('Load')")
        page.wait_for_timeout(2000)
        # Put invalid JSON in seed
        page.fill("#wf-seed", "{invalid json}")
        page.click("#wf-run-btn")
        page.wait_for_timeout(1000)
        # Should show error guidance
        results = page.locator("#wf-results-content")
        expect(results).to_contain_text("Invalid JSON")

    def test_recent_runs_list(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(2000)
        expect(page.locator("text=RECENT RUNS")).to_be_visible()


# ── Workflow Composer ─────────────────────────────────────────────────────


class TestWorkflowComposer:
    def test_composer_mode_toggle(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        expect(page.locator("#wf-composer")).to_be_visible()
        expect(page.locator("#composer-canvas")).to_be_visible()

    def test_add_step_creates_node(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        page.click("button:has-text('+ Add Step')")
        page.wait_for_timeout(500)
        nodes = page.locator(".composer-node")
        assert nodes.count() >= 1

    def test_node_click_shows_editor(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        page.click("button:has-text('+ Add Step')")
        page.wait_for_timeout(500)
        page.click(".composer-node")
        page.wait_for_timeout(500)
        editor = page.locator("#composer-editor")
        expect(editor).to_contain_text("Step ID")
        expect(editor).to_contain_text("System Prompt")

    def test_export_yaml_generates_valid_output(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        page.click("button:has-text('+ Add Step')")
        page.wait_for_timeout(300)
        page.click("button:has-text('+ Add Step')")
        page.wait_for_timeout(300)
        page.fill("#comp-wf-id", "e2e-test-workflow")
        page.fill("#comp-wf-name", "E2E Test Workflow")
        page.click("button:has-text('Export YAML')")
        page.wait_for_timeout(500)
        yaml_output = page.locator("#comp-yaml-output")
        expect(yaml_output).to_be_visible()
        expect(yaml_output).to_contain_text("id: e2e-test-workflow")
        expect(yaml_output).to_contain_text("steps:")

    def test_mode_toggle_preserves_state(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Workflows')")
        page.wait_for_timeout(1000)
        # Switch to composer, add a step
        page.click("#wf-mode-compose")
        page.wait_for_timeout(500)
        page.click("button:has-text('+ Add Step')")
        page.wait_for_timeout(300)
        # Switch back to runner
        page.click("#wf-mode-run")
        page.wait_for_timeout(300)
        expect(page.locator("#wf-composer")).to_be_hidden()
        # Switch back to composer — node should still be there
        page.click("#wf-mode-compose")
        page.wait_for_timeout(300)
        assert page.locator(".composer-node").count() >= 1

    def test_save_endpoint(self, page: Page, server_check):
        """Test the /api/workflows/save endpoint directly"""
        yaml_content = """id: e2e-save-test
name: "E2E Save Test"
version: "1.0"
defaults:
  role: general
steps:
  - id: s1
    name: "Step 1"
    system_prompt: "Do something"
    outputs:
      - result
"""
        resp = page.request.post(f"{BASE_URL}/api/workflows/save", data={
            "workflow_id": "e2e-save-test",
            "yaml_content": yaml_content,
        })
        assert resp.status == 200
        data = resp.json()
        assert data["saved"] is True
        assert data["workflow_id"] == "e2e-save-test"


# ── Agents Tab ────────────────────────────────────────────────────────────


class TestAgentsTab:
    def test_agents_tab_loads(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Agents')")
        page.wait_for_timeout(1000)
        expect(page.locator("#tab-agents")).to_be_visible()

    def test_create_agent_button(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Agents')")
        page.wait_for_timeout(1000)
        create_btn = page.locator("button:has-text('Create Agent')")
        if create_btn.is_visible():
            create_btn.click()
            page.wait_for_timeout(500)
            expect(page.locator("#agent-builder")).to_be_visible()


# ── Research Tab ──────────────────────────────────────────────────────────


class TestResearchTab:
    def test_knowledge_graph_renders(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Research')")
        page.wait_for_timeout(2000)
        svg = page.locator("#graph-svg")
        expect(svg).to_be_visible()

    def test_research_input(self, page: Page, server_check):
        page.goto(BASE_URL)
        page.click("button.tab-btn:has-text('Research')")
        page.wait_for_timeout(1000)
        input_el = page.locator("#research-topic")
        expect(input_el).to_be_visible()


# ── API Health ────────────────────────────────────────────────────────────


class TestAPIEndpoints:
    def test_health_endpoint(self, page: Page, server_check):
        resp = page.request.get(f"{BASE_URL}/health")
        assert resp.status == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_models_endpoint(self, page: Page, server_check):
        resp = page.request.get(f"{BASE_URL}/v1/models")
        assert resp.status == 200
        data = resp.json()
        assert "data" in data

    def test_workflows_list_endpoint(self, page: Page, server_check):
        resp = page.request.get(f"{BASE_URL}/api/workflows")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_workflow_compile_endpoint(self, page: Page, server_check):
        resp = page.request.post(f"{BASE_URL}/api/workflows/compile", data={
            "workflow_id": "data-model-rules"
        })
        assert resp.status == 200
        data = resp.json()
        assert "execution_plan" in data
        assert data["execution_plan"]["total_steps"] >= 1

    def test_workflow_runs_endpoint(self, page: Page, server_check):
        resp = page.request.get(f"{BASE_URL}/api/workflows/runs")
        assert resp.status == 200
        assert isinstance(resp.json(), list)

    def test_graph_endpoint(self, page: Page, server_check):
        resp = page.request.get(f"{BASE_URL}/api/graph")
        assert resp.status == 200
