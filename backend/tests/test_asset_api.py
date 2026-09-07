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
from app.core.security import create_access_token
from app.main import app
from app.models.group import Group
from app.models.permissions import GroupPermission, Permission
from app.models.product import Product
from app.models.product_asset import ProductAsset
from app.models.user import User
from app.models.user_group import UserGroup


class AssetApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.previous_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = self.tmpdir.name
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                Product.__table__,
                ProductAsset.__table__,
                User.__table__,
                Group.__table__,
                UserGroup.__table__,
                Permission.__table__,
                GroupPermission.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.auth_version = 7
        db = self.Session()
        db.add(User(
            id="test-user",
            username="tester",
            email="tester@example.com",
            password_hash="unused",
            user_type="human",
            display_name="Tester",
            is_active=True,
            auth_version=self.auth_version,
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

        app.dependency_overrides[get_db] = override_db
        # Authenticate against the persisted User through the real dependency.
        # File capabilities must carry its actual auth_version, not a stub default.
        self.client = TestClient(app, headers={
            "Authorization": f"Bearer {create_access_token({'sub': 'test-user', 'ver': self.auth_version})}",
        })
        self.file_rate_limit = patch("app.api.files.enforce_rate_limit", return_value=None)
        self.file_rate_limit.start()
        self.addCleanup(self.file_rate_limit.stop)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        settings.UPLOAD_DIR = self.previous_upload_dir
        self.engine.dispose()
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

    def test_edit_only_can_preview_existing_assets_without_download_upload_or_review(self):
        base_url = "/api/products/API-ASSET-1/assets"
        media_path = "/uploads/assets/API-ASSET-1/existing.png"
        payload = {"category_code": "01", "category_name": "产品标准图", "url": media_path}
        created = self.client.post(base_url, json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        asset_id = created.json()["id"]
        stored_file = Path(settings.UPLOAD_DIR) / media_path.removeprefix("/uploads/")
        stored_file.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), color=(20, 80, 140)).save(stored_file, format="PNG")

        # Replace the fixture's management membership with exactly product.edit.
        with self.Session() as db:
            db.get(Group, "management-group").group_name = "edit-only"
            db.query(UserGroup).filter_by(user_id="test-user").one().group_role = "member"
            permission = Permission(permission_key="product.edit", permission_name="Edit", permission_type="api")
            db.add(permission)
            db.flush()
            db.add(GroupPermission(group_id="management-group", permission_id=permission.id))
            db.commit()

        listed = self.client.get(base_url)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()], [asset_id])
        self.assertEqual(self.client.get(f"{base_url}?grouped=true").status_code, 200)
        detail = self.client.get(f"{base_url}/{asset_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["url"], media_path)
        signed = self.client.post("/api/files/sign", json={"path": media_path})
        self.assertEqual(signed.status_code, 200, signed.text)
        preview_url = signed.json()["url"]
        preview = self.client.get(preview_url)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.headers["content-disposition"].startswith("inline;"))
        download = self.client.post("/api/files/sign", json={"path": media_path, "purpose": "download"})
        self.assertEqual(download.status_code, 403, download.text)
        self.assertIn("media.download", download.text)

        for response in (
            self.client.post(base_url, json=payload),
            self.client.post(f"{base_url}/batch", json=[payload]),
            self.client.post(f"{base_url}/upload", data={"category_code": "01", "category_name": "产品标准图"},
                             files={"files": ("new.png", stored_file.read_bytes(), "image/png")}),
            self.client.put(f"{base_url}/{asset_id}", json={"status_tag": "已审核"}),
            self.client.delete(f"{base_url}/{asset_id}"),
        ):
            self.assertEqual(response.status_code, 403, response.text)
            self.assertIn("media.upload", response.text)

        # Explicit upload permission still must not imply review or download.
        with self.Session() as db:
            permission = Permission(permission_key="media.upload", permission_name="Upload", permission_type="api")
            db.add(permission)
            db.flush()
            db.add(GroupPermission(group_id="management-group", permission_id=permission.id))
            db.commit()
        review = self.client.put(f"{base_url}/{asset_id}", json={"status_tag": "已审核"})
        self.assertEqual(review.status_code, 403, review.text)
        self.assertIn("media.review", review.text)
        approved_upload = self.client.post(
            f"{base_url}/upload",
            data={"category_code": "01", "category_name": "产品标准图", "status_tag": "已审核"},
            files={"files": ("approved.png", stored_file.read_bytes(), "image/png")},
        )
        self.assertEqual(approved_upload.status_code, 403, approved_upload.text)
        self.assertIn("media.review", approved_upload.text)
        self.assertEqual(self.client.post("/api/files/sign", json={"path": media_path, "purpose": "download"}).status_code, 403)
        with self.Session() as db:
            self.assertEqual(db.query(ProductAsset).count(), 1)
            self.assertEqual(db.get(ProductAsset, asset_id).status_tag, "待审核")
            db.query(GroupPermission).filter_by(group_id="management-group").delete()
            db.commit()
        self.assertEqual(self.client.get(base_url).status_code, 403)
        self.assertEqual(self.client.get(f"{base_url}/{asset_id}").status_code, 403)
        self.assertEqual(self.client.get(preview_url).status_code, 403)

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
        preview_url = signed.json()["url"]
        previewed = self.client.get(preview_url)
        self.assertEqual(previewed.status_code, 200)
        self.assertTrue(previewed.headers["content-disposition"].startswith("inline;"))

        signed_download = self.client.post("/api/files/sign", json={"path": asset["url"], "purpose": "download"})
        self.assertEqual(signed_download.status_code, 200, signed_download.text)
        download_url = signed_download.json()["url"]
        downloaded = self.client.get(download_url)
        self.assertEqual(downloaded.status_code, 200)
        self.assertTrue(downloaded.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(downloaded.content, original.read_bytes())

        # Mutate a separate DB session after signing: both capabilities must
        # re-read account state even when the request supplies a fresh login.
        with self.Session() as db:
            user = db.get(User, "test-user")
            self.assertIsNotNone(user)
            self.assertEqual(user.auth_version, self.auth_version)
            user.auth_version += 1
            self.auth_version = user.auth_version
            db.commit()
        self.client.headers["Authorization"] = (
            f"Bearer {create_access_token({'sub': 'test-user', 'ver': self.auth_version})}"
        )
        self.assertEqual(self.client.get(preview_url).status_code, 403)
        self.assertEqual(self.client.get(download_url).status_code, 403)
        refreshed = self.client.post("/api/files/sign", json={"path": asset["url"], "purpose": "download"})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        refreshed_url = refreshed.json()["url"]
        self.assertEqual(self.client.get(refreshed_url).status_code, 200)

        deleted = self.client.delete(f"/api/products/API-ASSET-1/assets/{asset['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(original.exists())
        self.assertFalse(thumbnail.exists())
        self.assertEqual(self.client.get(refreshed_url).status_code, 404)

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

    def test_global_search_supports_all_tag_dimensions(self):
        first = self.client.post(
            "/api/products/API-ASSET-1/assets",
            json={
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/API-ASSET-1/tagged.jpg",
                "tags": {
                    "product_tags": ["套锅"],
                    "material_type_tags": ["白底图"],
                    "usage_tags": ["产品页"],
                    "version_tags": ["当前版本"],
                    "risk_tags": ["仅内部参考"],
                    "channel_tags": ["Amazon"],
                    "language_tags": ["中文"],
                },
            },
        )
        self.assertEqual(first.status_code, 200, first.text)

        second = self.client.post(
            "/api/products/API-ASSET-2/assets",
            json={
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/API-ASSET-2/tagged.jpg",
                "tags": {"product_tags": ["水壶"]},
            },
        )
        self.assertEqual(second.status_code, 200, second.text)

        response = self.client.get(
            "/api/assets/search",
            params=[
                ("product_tags", "套锅"),
                ("material_type_tags", "白底图"),
                ("usage_tags", "产品页"),
                ("version_tags", "当前版本"),
                ("risk_tags", "仅内部参考"),
                ("channel_tags", "Amazon"),
                ("language_tags", "中文"),
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["sku"] for item in response.json()["items"]], ["API-ASSET-1"])

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
