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


def test_api_responses_include_baseline_security_headers():
    response = TestClient(app).get("/api/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"]


def test_cookie_authenticated_mutation_rejects_untrusted_origin():
    client = TestClient(app)
    client.cookies.set(settings.AUTH_COOKIE_NAME, "not-a-real-token", path="/api")
    rejected = client.post(
        "/api/auth/logout",
        headers={"Origin": "https://attacker.invalid"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "Invalid request origin"

    accepted = client.post(
        "/api/auth/logout",
        headers={"Origin": settings.CORS_ORIGINS[0]},
    )
    assert accepted.status_code == 204
