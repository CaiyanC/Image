"""File capabilities and revocation, using only in-memory SQLite and tmp_path."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import files
from app.core.database import Base, get_db
from app.core.permission_constants import MANAGEMENT_GROUP_NAME
from app.core.security import create_access_token
from app.models.generation import Generation
from app.models.group import Group
from app.models.permissions import GroupPermission, Permission
from app.models.product import Product
from app.models.user import User
from app.models.user_group import UserGroup


MEDIA = ["/uploads/images/photo.png", "/uploads/videos/clip.mp4", "/uploads/assets/SKU/asset.png"]
GENERATED = "/uploads/generated/result.png"
REFERENCE = "/uploads/reference-images/reader/reference.png"


@pytest.fixture()
def file_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, Group.__table__, UserGroup.__table__, Permission.__table__,
        GroupPermission.__table__, Product.__table__, Generation.__table__,
    ])
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([
            User(id="reader", username="reader", password_hash="unused", is_active=True, auth_version=0),
            User(id="other", username="other", password_hash="unused", is_active=True, auth_version=0),
            Group(id="readers", group_name="readers"),
            Permission(id="read", permission_key="product.read", permission_name="Read", permission_type="api"),
            Permission(id="download", permission_key="media.download", permission_name="Download", permission_type="api"),
        ])
        db.flush()
        db.add_all([
            UserGroup(user_id="reader", group_id="readers", group_role="member"),
            GroupPermission(group_id="readers", permission_id="read"),
            Generation(id="generation", user_id="reader", type="txt2img", prompt="p", model_name="m",
                       status="completed", result_image_path=GENERATED),
        ])
        db.commit()

    for path in MEDIA + [GENERATED, REFERENCE]:
        destination = tmp_path / path.removeprefix("/uploads/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"original-media-content")
    monkeypatch.setattr(files.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(files, "enforce_rate_limit", lambda **kwargs: None)

    def override_db():
        with sessions() as db:
            yield db

    # A minimal router app avoids production startup, seed jobs and real DBs.
    app = FastAPI()
    app.include_router(files.router)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        # Browser previews use the same authenticated cookie as the sign API.
        client.cookies.set(files.settings.AUTH_COOKIE_NAME, create_access_token({"sub": "reader"}))
        yield client, sessions
    engine.dispose()


def sign(client, path=MEDIA[0], purpose=None, *, batch=False, user="reader"):
    body = {"paths": [path, path]} if batch else {"path": path}
    if purpose is not None:
        body["purpose"] = purpose
    return client.post(
        "/api/files/sign-batch" if batch else "/api/files/sign", json=body,
        headers={"Authorization": f"Bearer {create_access_token({'sub': user})}"},
    )


def grant_download(sessions):
    with sessions() as db:
        db.add(GroupPermission(group_id="readers", permission_id="download"))
        db.commit()


def signed_url(response, batch=False):
    assert response.status_code == 200, response.text
    body = response.json()
    if batch:
        assert len(body["items"]) == 1
        body = body["items"][0]
    assert 0 < body["expires_in"] <= 600
    return body["url"]


@pytest.mark.parametrize("path", MEDIA)
@pytest.mark.parametrize("batch", [False, True])
def test_preview_and_original_download_are_separate(file_env, path, batch):
    client, sessions = file_env
    preview = signed_url(sign(client, path, batch=batch), batch)
    response = client.get(preview + "?purpose=download&download=true")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["cache-control"] == "private, no-store"
    assert sign(client, path, "download", batch=batch).status_code == 403

    grant_download(sessions)
    download = signed_url(sign(client, path, "download", batch=batch), batch)
    assert preview != download
    response = client.get(download)
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content == b"original-media-content"
    # Granting download never upgrades an existing preview capability.
    assert client.get(preview).headers["content-disposition"].startswith("inline;")


@pytest.mark.parametrize("purpose", ["preview", "download"])
@pytest.mark.parametrize("batch", [False, True])
def test_download_permission_does_not_replace_read_permission(file_env, purpose, batch):
    client, sessions = file_env
    grant_download(sessions)
    with sessions() as db:
        db.query(GroupPermission).filter_by(permission_id="read").delete()
        db.commit()
    assert sign(client, purpose=purpose, batch=batch).status_code == 403


@pytest.mark.parametrize("permission", ["media.read", "media.search", "product.read", "product.full.view", "product.edit"])
@pytest.mark.parametrize("path", MEDIA)
@pytest.mark.parametrize("batch", [False, True])
def test_each_media_view_permission_allows_preview_but_not_download(file_env, permission, path, batch):
    client, sessions = file_env
    with sessions() as db:
        db.get(Permission, "read").permission_key = permission
        db.commit()
    preview = signed_url(sign(client, path, batch=batch), batch)
    assert client.get(preview).status_code == 200
    assert sign(client, path, "download", batch=batch).status_code == 403
    grant_download(sessions)
    download = signed_url(sign(client, path, "download", batch=batch), batch)
    assert client.get(download).headers["content-disposition"].startswith("attachment;")
    with sessions() as db:
        db.query(GroupPermission).filter_by(permission_id="read").delete()
        db.commit()
    assert client.get(preview).status_code == 403
    assert client.get(download).status_code == 403


@pytest.mark.parametrize("path", MEDIA)
@pytest.mark.parametrize("permission", ["read", "download"])
def test_existing_download_rechecks_current_permissions(file_env, path, permission):
    client, sessions = file_env
    grant_download(sessions)
    preview = signed_url(sign(client, path))
    download = signed_url(sign(client, path, "download"))
    with sessions() as db:
        db.query(GroupPermission).filter_by(permission_id=permission).delete()
        db.commit()
    assert client.get(download).status_code == 403
    assert client.get(download, headers={"Range": "bytes=0-4"}).status_code == 403
    assert client.get(preview).status_code == (200 if permission == "download" else 403)


@pytest.mark.parametrize("purpose", ["preview", "download"])
@pytest.mark.parametrize("change", ["disable", "delete", "auth_version", "membership"])
def test_existing_capability_is_revoked_when_account_changes(file_env, purpose, change):
    client, sessions = file_env
    grant_download(sessions)
    url = signed_url(sign(client, purpose=purpose))
    with sessions() as db:
        user = db.get(User, "reader")
        if change == "disable":
            user.is_active = False
        elif change == "delete":
            db.query(User).filter_by(id="reader").delete()
        elif change == "auth_version":
            user.auth_version += 1
        else:
            db.query(UserGroup).filter_by(user_id="reader").delete()
        db.commit()
    if change == "auth_version":
        assert client.get(url).status_code == 401  # old login is revoked too
        client.cookies.set(files.settings.AUTH_COOKIE_NAME, create_access_token({"sub": "reader", "ver": 1}))
    assert client.get(url).status_code == (401 if change in ("disable", "delete") else 403)


@pytest.mark.parametrize("path", [GENERATED, REFERENCE])
@pytest.mark.parametrize("batch", [False, True])
def test_owner_download_does_not_require_product_permissions(file_env, path, batch):
    client, sessions = file_env
    with sessions() as db:
        db.query(GroupPermission).delete()
        db.commit()
    url = signed_url(sign(client, path, "download", batch=batch), batch)
    assert client.get(url).headers["content-disposition"].startswith("attachment;")
    assert sign(client, path, "download", batch=batch, user="other").status_code == 403
    if path == GENERATED:
        with sessions() as db:
            db.get(Generation, "generation").user_id = "other"
            db.commit()
        assert client.get(url).status_code == 403


def test_manager_download_is_rechecked_after_demotion(file_env):
    client, sessions = file_env
    with sessions() as db:
        db.get(Group, "readers").group_name = MANAGEMENT_GROUP_NAME
        db.query(UserGroup).filter_by(user_id="reader").first().group_role = "admin"
        db.get(Generation, "generation").user_id = "other"
        db.commit()
    urls = [signed_url(sign(client, path, "download")) for path in MEDIA + [GENERATED]]
    with sessions() as db:
        db.query(UserGroup).filter_by(user_id="reader").first().group_role = "member"
        db.commit()
    assert all(client.get(url).status_code == 403 for url in urls)


@pytest.mark.parametrize("batch", [False, True])
def test_unsupported_scopes_invalid_purpose_and_mixed_batch_fail_closed(file_env, batch):
    client, sessions = file_env
    grant_download(sessions)
    assert sign(client, "/uploads/knowledge-files/secret.txt", "download", batch=batch).status_code == 403
    assert sign(client, "/uploads/unknown/file.png", "download", batch=batch).status_code == 403
    assert sign(client, "/uploads/images/../knowledge-files/secret.txt", "download", batch=batch).status_code == 400
    assert sign(client, purpose="original", batch=batch).status_code == 422
    response = client.post("/api/files/sign-batch", json={"paths": [GENERATED, "/uploads/reference-images/other/x.png"],
                                                        "purpose": "download"},
                           headers={"Authorization": f"Bearer {create_access_token({'sub': 'reader'})}"})
    assert response.status_code == 403


def test_sign_requires_login(file_env):
    client, _ = file_env
    client.cookies.clear()
    assert client.post("/api/files/sign", json={"path": MEDIA[0], "purpose": "download"}).status_code == 401


@pytest.mark.parametrize("path", MEDIA + [GENERATED, REFERENCE])
@pytest.mark.parametrize("purpose", ["preview", "download"])
def test_signed_file_requires_signers_login_even_with_valid_token(file_env, path, purpose):
    client, sessions = file_env
    grant_download(sessions)
    url = signed_url(sign(client, path, purpose))
    # Cookie-only access is how same-origin img/video elements load previews.
    assert client.get(url).status_code == 200
    client.cookies.clear()
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Range": "bytes=0-4"}).status_code == 401
    bearer = {"Authorization": f"Bearer {create_access_token({'sub': 'reader'})}"}
    assert client.get(url, headers=bearer).status_code == 200
    expired = create_access_token({"sub": "reader"}, expires_delta=timedelta(seconds=-1))
    assert client.get(url, headers={"Authorization": f"Bearer {expired}"}).status_code == 401


@pytest.mark.parametrize("path", MEDIA + [GENERATED, REFERENCE])
@pytest.mark.parametrize("purpose", ["preview", "download"])
@pytest.mark.parametrize("other_role", ["no_permissions", "same_permissions", "manager"])
def test_another_employee_cannot_reuse_signers_token(file_env, path, purpose, other_role):
    client, sessions = file_env
    grant_download(sessions)
    if other_role != "no_permissions":
        with sessions() as db:
            db.add(UserGroup(user_id="other", group_id="readers",
                             group_role="admin" if other_role == "manager" else "member"))
            if other_role == "manager":
                db.get(Group, "readers").group_name = MANAGEMENT_GROUP_NAME
            db.commit()
    url = signed_url(sign(client, path, purpose))
    other_token = create_access_token({"sub": "other"})
    # Even a valid signer's cookie cannot override another employee's bearer.
    assert client.get(url, headers={"Authorization": f"Bearer {other_token}"}).status_code == 403
    client.cookies.set(files.settings.AUTH_COOKIE_NAME, other_token)
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"Range": "bytes=0-4"}).status_code == 403


def test_direct_signed_file_call_passes_real_user_and_rechecks_database(file_env):
    client, sessions = file_env
    token = signed_url(sign(client)).rsplit("/", 1)[-1]
    with sessions() as db:
        user = db.get(User, "reader")
        response = files.get_signed_file(token, current_user=user, db=db)
        assert response.headers["content-disposition"].startswith("inline;")
        with pytest.raises(HTTPException) as wrong_user:
            files.get_signed_file(token, current_user=db.get(User, "other"), db=db)
        assert wrong_user.value.status_code == 403
        with sessions() as updated_db:
            updated_db.get(User, "reader").auth_version += 1
            updated_db.commit()
        with pytest.raises(HTTPException) as revoked:
            files.get_signed_file(token, current_user=user, db=db)
        assert revoked.value.status_code == 403


@pytest.mark.parametrize("mutation", [
    "legacy", "missing_exp", "missing_user", "missing_version", "missing_purpose", "bad_version",
    "bad_purpose", "expired", "long_lived", "wrong_audience", "wrong_signature", "tampered_purpose",
])
def test_old_or_invalid_tokens_cannot_bypass_authorization(file_env, mutation):
    client, _ = file_env
    token = signed_url(sign(client)).rsplit("/", 1)[-1]
    payload = jwt.decode(token, options={"verify_signature": False})
    key = files.settings.SECRET_KEY
    if mutation == "legacy":
        payload = {name: payload[name] for name in ("sub", "aud", "exp")}
    elif mutation.startswith("missing_"):
        payload.pop({"missing_exp": "exp", "missing_user": "user_id", "missing_version": "auth_version",
                     "missing_purpose": "purpose"}[mutation])
    elif mutation == "bad_version":
        payload["auth_version"] = "0"
    elif mutation == "bad_purpose":
        payload["purpose"] = "original"
    elif mutation == "expired":
        payload["exp"] = int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp())
    elif mutation == "long_lived":
        payload["exp"] = payload["iat"] + 601
    elif mutation == "wrong_audience":
        payload["aud"] = files.settings.AUTH_TOKEN_AUDIENCE
    elif mutation == "wrong_signature":
        key = "not-the-real-file-signing-key-123456789"
    elif mutation == "tampered_purpose":
        payload["purpose"] = "download"
    forged = jwt.encode(payload, key, algorithm=files._SIGNED_FILE_ALGORITHM)
    if mutation == "tampered_purpose":
        forged = forged.rsplit(".", 1)[0] + "." + token.rsplit(".", 1)[-1]
    assert client.get(f"/api/files/signed/{forged}").status_code == 403


def test_video_ranges_keep_purpose_and_authorization(file_env):
    client, sessions = file_env
    grant_download(sessions)
    for purpose, disposition in [("preview", "inline;"), ("download", "attachment;")]:
        url = signed_url(sign(client, MEDIA[1], purpose))
        response = client.get(url, headers={"Range": "bytes=0-4"})
        assert response.status_code == 206
        assert response.content == b"origi"
        assert response.headers["content-disposition"].startswith(disposition)


def test_missing_file_still_returns_404_after_authorization(file_env):
    client, _ = file_env
    url = signed_url(sign(client, "/uploads/images/missing.png"))
    assert client.get(url).status_code == 404
