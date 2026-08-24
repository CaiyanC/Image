from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import jwt

from app.api import auth as auth_api
from app.core.database import Base, get_db
from app.core.config import settings
from app.core.permission_constants import MANAGEMENT_GROUP_NAME
from app.core.security import get_password_hash
from app.models import Group, GroupPermission, Permission, User, UserGroup


def _auth_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Group.__table__,
            UserGroup.__table__,
            Permission.__table__,
            GroupPermission.__table__,
        ],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(
        id="auth-user",
        username="auth-user",
        password_hash=get_password_hash("correct-password"),
        is_active=True,
    )
    group = Group(id="auth-admin-group", group_name=MANAGEMENT_GROUP_NAME)
    session.add_all([user, group])
    session.add(UserGroup(user_id=user.id, group_id=group.id, group_role="admin"))
    session.commit()

    api = FastAPI()
    api.include_router(auth_api.router)

    def override_db():
        yield session

    api.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(auth_api, "enforce_rate_limit", lambda **_: None)
    return TestClient(api), session, user


def test_browser_login_uses_http_only_cookie_without_exposing_token(monkeypatch):
    client, session, _ = _auth_client(monkeypatch)
    try:
        response = client.post(
            "/api/auth/login",
            json={"username": "auth-user", "password": "correct-password"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"] is None
        assert response.json()["token_type"] == "cookie"
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "path=/api" in cookie

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "auth-user"
    finally:
        session.close()


def test_script_token_is_separate_and_password_version_revokes_old_token(monkeypatch):
    client, session, user = _auth_client(monkeypatch)
    try:
        response = client.post(
            "/api/auth/token",
            json={"username": "auth-user", "password": "correct-password"},
        )
        assert response.status_code == 200
        token = response.json()["access_token"]
        assert token
        assert "set-cookie" not in response.headers

        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        user.auth_version += 1
        session.commit()
        assert client.get("/api/auth/me", headers=headers).status_code == 401
    finally:
        session.close()


def test_malformed_signed_token_returns_401_instead_of_server_error(monkeypatch):
    client, session, _ = _auth_client(monkeypatch)
    try:
        token = jwt.encode(
            {
                "sub": "auth-user",
                "ver": "not-an-integer",
                "typ": "access",
                "iss": settings.AUTH_TOKEN_ISSUER,
                "aud": settings.AUTH_TOKEN_AUDIENCE,
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
    finally:
        session.close()
