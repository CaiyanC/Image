import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.config import settings
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
        self.previous_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = self.tmpdir.name
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
        settings.UPLOAD_DIR = self.previous_upload_dir
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

    def test_ai_image_upload_sign_read_and_delete_is_a_closed_lifecycle(self):
        image_data = io.BytesIO()
        Image.new("RGB", (64, 32), color=(20, 80, 140)).save(image_data, format="PNG")
        response = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data={"category_code": "07", "category_name": "AI 生成图"},
            files={"files": ("customer-original.png", image_data.getvalue(), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()["items"][0]
        self.assertTrue(asset["is_ai_generated"])
        self.assertFalse(asset["is_real_product"])
        self.assertEqual(asset["original_file_name"], "customer-original.png")
        self.assertEqual(asset["mime_type"], "image/png")
        self.assertEqual(asset["width"], 64)
        self.assertEqual(asset["height"], 32)
        self.assertEqual(asset["resolution"], "64x32")
        self.assertEqual(asset["aspect_ratio"], "2:1")
        self.assertEqual(len(asset["checksum_sha256"]), 64)

        original = Path(settings.UPLOAD_DIR) / asset["url"].removeprefix("/uploads/")
        thumbnail = Path(settings.UPLOAD_DIR) / asset["thumbnail_url"].removeprefix("/uploads/")
        self.assertTrue(original.is_file())
        self.assertTrue(thumbnail.is_file())

        signed = self.client.post("/api/files/sign", json={"path": asset["url"]})
        self.assertEqual(signed.status_code, 200, signed.text)
        downloaded = self.client.get(signed.json()["url"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertGreater(len(downloaded.content), 0)

        deleted = self.client.delete(f"/api/products/API-ASSET-1/assets/{asset['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(original.exists())
        self.assertFalse(thumbnail.exists())

    def test_upload_flags_exact_duplicate_for_manual_review(self):
        image_data = io.BytesIO()
        Image.new("RGB", (64, 32), color=(20, 80, 140)).save(image_data, format="PNG")
        content = image_data.getvalue()
        payload = {
            "category_code": "01",
            "category_name": "产品标准图",
            "sub_category": "白底图",
            "material_type": "whiteBackground",
        }

        first = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data=payload,
            files={"files": ("first.png", content, "image/png")},
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_asset = first.json()["items"][0]

        second = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data=payload,
            files={"files": ("second.png", content, "image/png")},
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_asset = second.json()["items"][0]

        self.assertEqual(first_asset["duplicate_status"], "unique")
        self.assertEqual(second_asset["quality_status"], "suspected_duplicate")
        self.assertEqual(second_asset["duplicate_status"], "suspected_duplicate")
        self.assertEqual(second_asset["duplicate_of_asset_id"], first_asset["id"])

    def test_upload_cannot_mark_asset_approved_without_media_review(self):
        image_data = io.BytesIO()
        Image.new("RGB", (16, 16), color=(20, 80, 140)).save(image_data, format="PNG")
        with patch("app.api.assets.has_permission", return_value=False):
            response = self.client.post(
                "/api/products/API-ASSET-1/assets/upload",
                data={
                    "category_code": "01",
                    "category_name": "产品标准图",
                    "status_tag": "已审核",
                },
                files={"files": ("approved-without-review.png", image_data.getvalue(), "image/png")},
            )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)
        self.assertEqual(self.client.get("/api/products/API-ASSET-1/assets").json(), [])

    def test_upload_removes_saved_files_when_database_batch_fails(self):
        image_data = io.BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(image_data, format="PNG")
        with patch("app.api.assets.asset_service.create_assets_batch", side_effect=RuntimeError("db failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    "/api/products/API-ASSET-1/assets/upload",
                    data={"category_code": "01", "category_name": "产品标准图"},
                    files={"files": ("rollback.png", image_data.getvalue(), "image/png")},
                )
        asset_dir = Path(settings.UPLOAD_DIR) / "assets" / "API-ASSET-1"
        self.assertEqual(list(asset_dir.glob("*")), [])


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

    def test_taxonomy_and_lifecycle_filters_are_available(self):
        taxonomy = self.client.get("/api/assets/taxonomy")
        self.assertEqual(taxonomy.status_code, 200, taxonomy.text)
        payload = taxonomy.json()
        self.assertEqual(payload["dimensions"]["scene_tags"]["values"], ["徒步", "硬核露营", "车露", "家庭露营", "雪地", "森林", "湖边", "室内"])
        self.assertIn("suspected_duplicate", payload["quality_statuses"])
        self.assertIn("cross_sku_reuse", payload["duplicate_statuses"])

        created = self.client.post(
            "/api/products/API-ASSET-1/assets",
            json={
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/API-ASSET-1/quality-test.jpg",
                "quality_status": "suspected_duplicate",
                "quality_reason": "开发环境重复测试",
                "duplicate_status": "suspected_duplicate",
                "duplicate_of_asset_id": "known-source",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        asset = created.json()
        self.assertEqual(asset["quality_status"], "suspected_duplicate")
        self.assertEqual(asset["duplicate_status"], "suspected_duplicate")

        filtered = self.client.get("/api/assets/search", params={"quality_status": "suspected_duplicate"})
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual([item["id"] for item in filtered.json()["items"]], [asset["id"]])

        expression_only = self.client.get("/api/assets/search", params={"expression_tags": "卖点图"})
        self.assertEqual(expression_only.status_code, 200, expression_only.text)

        invalid_tag = self.client.get("/api/assets/search", params={"scene_tags": "studio"})
        self.assertEqual(invalid_tag.status_code, 422)


if __name__ == "__main__":
    unittest.main()
