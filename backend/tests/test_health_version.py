from fastapi.testclient import TestClient

from app.main import app


def test_health_version_returns_runtime_identity(monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "test-commit-123")

    response = TestClient(app).get("/api/health/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["commit"] == "test-commit-123"
    assert payload["code_root"].replace("\\", "/").endswith("/backend")
    assert payload["cwd"]
    assert payload["python_executable"]
    assert isinstance(payload["pid"], int)
    assert payload["started_at"]
    assert payload["env"] in {"dev", "prod", ""}
    assert isinstance(payload["backend_port"], int)
