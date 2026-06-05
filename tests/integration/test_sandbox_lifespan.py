def test_lifespan_initializes_sandbox_registry():
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app):  # enters the lifespan
        from api.services.sandbox_registry import get_current_sandbox_registry

        reg = get_current_sandbox_registry()
        assert any(b.name == "subprocess" for b in reg.backends())
