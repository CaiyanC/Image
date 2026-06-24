import io
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.permission_constants import MANAGEMENT_GROUP_NAME
from app.core.security import get_current_user
from app.main import app
from app.models.group import Group
from app.models.product import Product
from app.models.product_asset import ProductAsset
from app.models.user import User
from app.models.user_group import UserGroup


TEST_SKU = "L6-SMOKE-1"
IMAGE_CATEGORY_NAME = "产品标准图"
IMAGE_SUB_CATEGORY = "白底图"
VIDEO_CATEGORY_NAME = "视频素材"
VIDEO_SUB_CATEGORY = "视频"
DEFAULT_STATUS = "待审核"
BANNED_STATUS = "禁用"
ARCHIVE_CATEGORY_CODE = "08"
ARCHIVE_SUB_CATEGORY = "禁用素材"


@pytest.fixture()
def client():
    tmpdir = tempfile.TemporaryDirectory()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Product.__table__,
            ProductAsset.__table__,
            User.__table__,
            Group.__table__,
            UserGroup.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)

    db = Session()
    db.add(
        User(
            id="l6-smoke-user",
            username="l6-smoke",
            email="l6-smoke@example.com",
            password_hash="unused",
            user_type="human",
            display_name="L6 Smoke",
            is_active=True,
        )
    )
    db.add(Group(id="l6-smoke-management", group_name=MANAGEMENT_GROUP_NAME, description="management"))
    db.add(UserGroup(user_id="l6-smoke-user", group_id="l6-smoke-management", group_role="admin"))
    db.add(
        Product(
            id="l6-smoke-product",
            sku=TEST_SKU,
            barcode="l6-smoke-barcode",
            product_name_cn="L6 Smoke Product",
            product_name_en="L6 Smoke Product",
            brand="alocs",
        )
    )
    db.commit()
    db.close()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    def allow_user():
        class UserStub:
            id = "l6-smoke-user"
            username = "l6-smoke"

        return UserStub()

    original_upload_dir = app.dependency_overrides.get(get_db)
    from app.core.config import settings

    previous_upload_dir = settings.UPLOAD_DIR
    settings.UPLOAD_DIR = tmpdir.name
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = allow_user

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if original_upload_dir is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_upload_dir
        app.dependency_overrides.pop(get_current_user, None)
        settings.UPLOAD_DIR = previous_upload_dir
        tmpdir.cleanup()


def _create_asset(client: TestClient, *, url: str, category_code: str = "01", category_name: str = IMAGE_CATEGORY_NAME):
    response = client.post(
        f"/api/products/{TEST_SKU}/assets",
        json={
            "category_code": category_code,
            "category_name": category_name,
            "sub_category": IMAGE_SUB_CATEGORY,
            "material_type": "whiteBackground",
            "url": url,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_asset_returns_id_sku_and_grouped_seq(client: TestClient):
    first = _create_asset(client, url=f"/uploads/assets/{TEST_SKU}/one.jpg")
    second = _create_asset(client, url=f"/uploads/assets/{TEST_SKU}/two.jpg")

    assert first["id"]
    assert first["sku"] == TEST_SKU
    assert first["seq"] == 1
    assert second["seq"] == 2


def test_list_assets_returns_created_record(client: TestClient):
    created = _create_asset(client, url=f"/uploads/assets/{TEST_SKU}/listed.jpg")

    response = client.get(f"/api/products/{TEST_SKU}/assets")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(item["id"] == created["id"] for item in payload)


def test_upload_asset_accepts_image_and_video(client: TestClient):
    image_response = client.post(
        f"/api/products/{TEST_SKU}/assets/upload",
        data={
            "category_code": "01",
            "category_name": IMAGE_CATEGORY_NAME,
            "sub_category": IMAGE_SUB_CATEGORY,
            "material_type": "whiteBackground",
        },
        files={"files": ("photo.png", io.BytesIO(b"fake image bytes"), "image/png")},
    )
    assert image_response.status_code == 200, image_response.text
    image_payload = image_response.json()
    assert image_payload["count"] == 1
    assert image_payload["items"][0]["asset_type"] == "image"

    video_response = client.post(
        f"/api/products/{TEST_SKU}/assets/upload",
        data={
            "category_code": "06",
            "category_name": VIDEO_CATEGORY_NAME,
            "sub_category": VIDEO_SUB_CATEGORY,
            "material_type": "video",
        },
        files={"files": ("clip.mp4", io.BytesIO(b"fake video bytes"), "video/mp4")},
    )
    assert video_response.status_code == 200, video_response.text
    video_payload = video_response.json()
    assert video_payload["count"] == 1
    assert video_payload["items"][0]["asset_type"] == "video"
    assert video_payload["items"][0]["sub_category"] == VIDEO_SUB_CATEGORY


def test_tags_patch_only_updates_tags(client: TestClient):
    created = _create_asset(client, url=f"/uploads/assets/{TEST_SKU}/tags.jpg")

    response = client.patch(
        f"/api/products/{TEST_SKU}/assets/{created['id']}/tags",
        json={"product_tags": ["套锅"], "risk_tags": ["仅内部参考"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["tags"] == {"product_tags": ["套锅"], "risk_tags": ["仅内部参考"]}
    assert payload["category_code"] == "01"
    assert payload["sub_category"] == IMAGE_SUB_CATEGORY
    assert payload["status_tag"] == DEFAULT_STATUS


def test_status_update_moves_asset_to_archive_and_delete_completes_crud(client: TestClient):
    created = _create_asset(client, url=f"/uploads/assets/{TEST_SKU}/status.jpg")

    update_response = client.put(
        f"/api/products/{TEST_SKU}/assets/{created['id']}",
        json={"status_tag": BANNED_STATUS},
    )

    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["category_code"] == ARCHIVE_CATEGORY_CODE
    assert updated["sub_category"] == ARCHIVE_SUB_CATEGORY

    delete_response = client.delete(f"/api/products/{TEST_SKU}/assets/{created['id']}")
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json() == {"ok": True}

    list_response = client.get(f"/api/products/{TEST_SKU}/assets")
    assert list_response.status_code == 200, list_response.text
    assert all(item["id"] != created["id"] for item in list_response.json())
