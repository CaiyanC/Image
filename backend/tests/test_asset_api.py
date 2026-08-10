import io
import tempfile
import unittest

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


class AssetApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
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
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        db.add(User(
            id="test-user",
            username="tester",
            email="tester@example.com",
            password_hash="unused",
            user_type="human",
            display_name="Tester",
            is_active=True,
        ))
        db.add(Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME, description="management"))
        db.add(UserGroup(user_id="test-user", group_id="management-group", group_role="admin"))
        db.add(Product(
            id="api-product-asset",
            sku="API-ASSET-1",
            barcode="api-barcode",
            product_name_cn="api asset product",
            product_name_en="API Asset Product",
            brand="alocs",
        ))
        db.add(Product(
            id="api-product-asset-2",
            sku="API-ASSET-2",
            barcode="api-barcode-2",
            product_name_cn="second api asset product",
            product_name_en="Second API Asset Product",
            brand="alocs",
        ))
        db.commit()
        db.close()

        def override_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        def allow_user():
            class UserStub:
                id = "test-user"
                username = "tester"
            return UserStub()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = allow_user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.tmpdir.cleanup()

    def test_create_list_update_and_patch_tags(self):
        created = self.client.post(
            "/api/products/API-ASSET-1/assets",
            json={
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/API-ASSET-1/one.jpg",
            },
        )
        self.assertEqual(created.status_code, 200)
        asset = created.json()
        self.assertEqual(asset["seq"], 1)
        self.assertEqual(asset["status_tag"], "待审核")

        listed = self.client.get("/api/products/API-ASSET-1/assets?category=01")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        tags = self.client.patch(
            f"/api/products/API-ASSET-1/assets/{asset['id']}/tags",
            json={"product_tags": ["套锅"]},
        )
        self.assertEqual(tags.status_code, 200)
        self.assertEqual(tags.json()["tags"], {"product_tags": ["套锅"]})

        moved = self.client.put(
            f"/api/products/API-ASSET-1/assets/{asset['id']}",
            json={"status_tag": "归档历史版本"},
        )
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["category_code"], "08")
        self.assertEqual(moved.json()["sub_category"], "历史版本")

    def test_upload_rejects_image_in_video_category(self):
        response = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data={
                "category_code": "06",
                "category_name": "视频素材",
                "sub_category": "视频",
                "material_type": "video",
            },
            files={"files": ("bad.png", io.BytesIO(b"not really image"), "image/png")},
        )

        self.assertEqual(response.status_code, 400)

    def test_upload_accepts_video_category_video(self):
        response = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data={
                "category_code": "06",
                "category_name": "视频素材",
                "sub_category": "视频",
                "material_type": "video",
            },
            files={"files": ("clip.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypisom" + b"x" * 20), "video/mp4")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["asset_type"], "video")
        self.assertEqual(payload["items"][0]["sub_category"], "视频")
        self.assertEqual(payload["items"][0]["material_type"], "video")


    def test_global_search_matches_tag_values_within_dimension(self):
        for sku, channel, tags in [
            ("API-ASSET-1", "Amazon", {"expression_tags": ["场景图"], "scene_tags": ["徒步"]}),
            ("API-ASSET-2", "Amazon", {"expression_tags": ["场景图"], "scene_tags": ["家庭露营"]}),
            ("API-ASSET-2", "eBay", {"expression_tags": ["场景图"], "scene_tags": ["家庭露营"]}),
        ]:
            response = self.client.post(
                f"/api/products/{sku}/assets",
                json={
                    "category_code": "04",
                    "category_name": "场景内容图",
                    "sub_category": "家庭露营",
                    "url": f"/uploads/assets/{sku}/{channel}.jpg",
                    "channel": channel,
                    "tags": tags,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)

        response = self.client.get(
            "/api/assets/search",
            params=[("scene_tags", "家庭露营"), ("scene_tags", "徒步"), ("channel", "Amazon")],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["sku"] for item in response.json()["items"]], ["API-ASSET-1", "API-ASSET-2"])

        invalid_limit = self.client.get("/api/assets/search", params={"limit": 101})
        self.assertEqual(invalid_limit.status_code, 422)


if __name__ == "__main__":
    unittest.main()
