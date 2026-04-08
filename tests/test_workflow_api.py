"""Tests for workflow API endpoints"""
import pytest
from unittest.mock import MagicMock, patch
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
    mock = MagicMock()
    mock.health_check.return_value = True
    mock.list_models.return_value = [
        {"name": "dolphin3:8b", "size": 5000000000}
    ]
    mock.chat.return_value = {
        "content": "Test output",
        "prompt_eval_count": 10,
        "eval_count": 20,
    }
    return mock


@pytest.fixture
def client(mock_ollama):
    with patch("api.routers.workflows.OllamaService", return_value=mock_ollama), \
         patch("api.main.ollama_service", mock_ollama):
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
        data = response.json()
        assert data["valid"] is True
        assert "execution_plan" in data
        assert "parallelism" in data

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

    def test_compile_workflow(self, client):
        response = client.post(
            "/api/workflows/compile",
            json={"definition": VALID_WORKFLOW, "seed_keys": ["task"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] == "test-api-workflow"
        assert "execution_plan" in data
        assert "parallelism_analysis" in data
        assert "steps" in data

    def test_list_runs(self, client):
        response = client.get("/api/workflows/runs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_nonexistent_run(self, client):
        response = client.get("/api/workflows/runs/nonexistent-id")
        assert response.status_code == 404
