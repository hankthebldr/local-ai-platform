"""Tests for workflow API endpoints"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

VALID_WORKFLOW = {
    "id": "test-api-workflow",
    "name": "Test API Workflow",
    "defaults": {"role": "general", "retries": 0, "retry_delay": 0},
    "steps": [
        {
            "id": "s1",
            "name": "Step 1",
            "role": "fast",
            "system_prompt": "Analyze the input.",
            "inputs": ["seed.task"],
            "outputs": ["result"],
        }
    ],
}


@pytest.fixture
def mock_ollama():
    with patch("api.services.ollama_service.OllamaService") as MockClass:
        instance = MockClass.return_value
        instance.health_check.return_value = True
        instance.list_models.return_value = [
            {"name": "dolphin3:8b", "size": 5000000000}
        ]
        instance.chat.return_value = {
            "content": "Test output",
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        yield instance


@pytest.fixture
def client(mock_ollama):
    with patch("api.routers.workflows.get_ollama_service", return_value=mock_ollama):
        with patch("api.main.ollama_service", mock_ollama):
            from api.main import app

            return TestClient(app)


class TestWorkflowAPI:
    def test_list_workflows(self, client):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_validate_workflow(self, client):
        response = client.post(
            "/api/workflows/validate",
            json={"definition": VALID_WORKFLOW, "seed_keys": ["task"]},
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True

    def test_validate_broken_workflow(self, client):
        broken = {
            "id": "broken",
            "name": "Broken",
            "steps": [
                {
                    "id": "s1",
                    "name": "Step",
                    "role": "fast",
                    "system_prompt": "Do thing.",
                    "inputs": ["nonexistent.data"],
                    "outputs": ["result"],
                }
            ],
        }
        response = client.post(
            "/api/workflows/validate",
            json={"definition": broken, "seed_keys": []},
        )
        assert response.status_code == 422

    def test_list_runs(self, client):
        response = client.get("/api/workflows/runs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_workflow_definition(self, client):
        """GET /api/workflows/{id} returns full definition with steps for the UI."""
        response = client.get("/api/workflows/data-model-rules")
        assert response.status_code == 200
        defn = response.json()
        assert defn["id"] == "data-model-rules"
        assert isinstance(defn["steps"], list)
        assert len(defn["steps"]) >= 1
        # Each step must expose the hooks block (may be empty) so the UI
        # can reliably render hook slots.
        for step in defn["steps"]:
            assert "hooks" in step
            hooks = step["hooks"] or {}
            for slot in (
                "before_step",
                "transform_prompt",
                "validate_output",
                "after_step",
                "on_failure",
            ):
                assert slot in hooks

    def test_get_missing_workflow_returns_404(self, client):
        response = client.get("/api/workflows/does-not-exist")
        assert response.status_code == 404

    def test_get_workflow_rejects_path_traversal(self, client):
        response = client.get("/api/workflows/..%2F..%2Fetc%2Fpasswd")
        assert response.status_code in (400, 404)

    def test_save_workflow_writes_yaml_and_round_trips(
        self, client, tmp_path, monkeypatch
    ):
        """POST /api/workflows/save persists a validated def to workflows/{id}.yaml."""
        monkeypatch.setattr("api.routers.workflows.WORKFLOWS_DIR", str(tmp_path))
        wf = {
            "id": "saved-workflow",
            "name": "Saved",
            "defaults": {"role": "general", "retries": 0, "retry_delay": 0},
            "steps": [
                {
                    "id": "s1",
                    "name": "Step 1",
                    "role": "fast",
                    "system_prompt": "Do thing.",
                    "inputs": ["seed.input"],
                    "outputs": ["result"],
                }
            ],
        }
        r = client.post("/api/workflows/save", json={"definition": wf})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["saved"] is True
        assert body["workflow_id"] == "saved-workflow"

        target = tmp_path / "saved-workflow.yaml"
        assert target.exists(), "yaml file was not written"
        content = target.read_text()
        assert "id: saved-workflow" in content
        assert "Do thing." in content

    def test_save_workflow_refuses_clobber_without_overwrite(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("api.routers.workflows.WORKFLOWS_DIR", str(tmp_path))
        wf = {
            "id": "existing",
            "name": "x",
            "defaults": {"role": "general", "retries": 0, "retry_delay": 0},
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "role": "fast",
                    "system_prompt": "p",
                    "inputs": ["seed.x"],
                    "outputs": ["y"],
                }
            ],
        }
        assert (
            client.post("/api/workflows/save", json={"definition": wf}).status_code
            == 200
        )
        assert (
            client.post("/api/workflows/save", json={"definition": wf}).status_code
            == 409
        )
        assert (
            client.post(
                "/api/workflows/save",
                json={"definition": wf, "overwrite": True},
            ).status_code
            == 200
        )

    def test_save_workflow_validates_before_writing(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("api.routers.workflows.WORKFLOWS_DIR", str(tmp_path))
        broken = {
            "id": "broken-save",
            "name": "broken",
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "role": "fast",
                    "system_prompt": "p",
                    "inputs": ["nonexistent.x"],
                    "outputs": ["y"],
                }
            ],
        }
        r = client.post("/api/workflows/save", json={"definition": broken})
        assert r.status_code == 422
        assert not (tmp_path / "broken-save.yaml").exists()


class TestValidateExtensionWarnings:
    """Phase 5 — validate response carries plugin/mcp/skill warnings when the
    workflow declares required_* or tools/skills with non-fatal gaps."""

    def test_unreachable_required_mcp_returns_warning_in_body(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("ENABLE_API_AUTH", "false")
        from api.services import extension_preflight

        class FakeMCP:
            def has_server(self, sid):
                return sid == "fs"

            def is_reachable(self, sid):
                return False

            def has_tool(self, sid, tool):
                return True

        monkeypatch.setattr(
            extension_preflight, "_default_mcp_service", lambda: FakeMCP()
        )
        wf = {
            "id": "wmcp",
            "name": "wmcp",
            "defaults": {"required_mcps": ["fs"]},
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "role": "fast",
                    "system_prompt": "p",
                    "outputs": ["x"],
                }
            ],
        }
        r = client.post(
            "/api/workflows/validate", json={"definition": wf, "seed_keys": []}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert "warnings" in body
        assert any(w["code"] == "mcp_unreachable" for w in body["warnings"]["mcp"])

    def test_missing_required_plugin_returns_422(self, client, monkeypatch):
        monkeypatch.setenv("ENABLE_API_AUTH", "false")
        from api.services import extension_preflight

        class FakePlugins:
            def has_plugin(self, pid):
                return False

            def has_tool(self, pid, tid):
                return False

            def has_skill(self, pid, sid):
                return False

            def list_plugins(self):
                return []

        monkeypatch.setattr(
            extension_preflight, "_default_plugin_service", lambda: FakePlugins()
        )
        wf = {
            "id": "wplug",
            "name": "wplug",
            "defaults": {"required_plugins": ["xdm-toolkit"]},
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "role": "fast",
                    "system_prompt": "p",
                    "outputs": ["x"],
                }
            ],
        }
        r = client.post(
            "/api/workflows/validate", json={"definition": wf, "seed_keys": []}
        )
        assert r.status_code == 422
        assert "plugin_missing" in r.json()["detail"]
