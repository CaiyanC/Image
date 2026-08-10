from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_cors_allows_configured_origin_and_rejects_unconfigured_origin():
    client = TestClient(app)
    allowed_origin = settings.CORS_ORIGINS[0]
    allowed = client.options(
        "/api/health/live",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == allowed_origin
    assert allowed.headers["access-control-allow-credentials"] == "true"

    rejected = client.options(
        "/api/health/live",
        headers={
            "Origin": "https://attacker.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
