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
from app.models.operation_logs import OperationLog
from app.models.permissions import GroupPermission, Permission
from app.models.product import Product
from app.models.product_asset import ProductAsset, ProductAssetLink
from app.models.competitor_asset import CompetitorAsset
from app.models.user import User
from app.models.user_group import UserGroup


class AssetApiTest(unittest.TestCase):
    def test_word_faq_upload_is_a_pending_document_asset(self):
        from zipfile import ZipFile
        archive = io.BytesIO()
        with ZipFile(archive, 'w') as package:
            package.writestr('[Content_Types].xml', '<Types/>')
            package.writestr('word/document.xml', '<document/>')
        response = self.client.post('/api/products/API-ASSET-1/assets/upload',
            data={'category_code': '03', 'category_name': '使用说明图', 'sub_category': '其他说明', 'material_type': 'otherDesc'},
            files={'files': ('faq.docx', archive.getvalue(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()['items'][0]
        self.assertEqual(asset['asset_type'], 'document')
        self.assertEqual(asset['file_format'], 'docx')
        self.assertEqual(asset['review_status'], 'pending')
        self.assertFalse(asset['ai_customer_usable'])
        stored = Path(settings.UPLOAD_DIR) / asset['url'].removeprefix('/uploads/')
        self.assertEqual(stored.read_bytes(), archive.getvalue())

    def test_fake_word_upload_does_not_create_assets(self):
        response = self.client.post('/api/products/API-ASSET-1/assets/upload',
            data={'category_code': '03', 'category_name': '使用说明图', 'sub_category': '其他说明', 'material_type': 'otherDesc'},
            files={'files': ('faq.docx', b'not word', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        self.assertEqual(response.status_code, 400, response.text)
        with self.Session() as db:
            self.assertEqual(db.query(ProductAsset).count(), 0)

    def test_manual_pdf_upload_and_content_validation(self):
        import fitz
        manual = fitz.open()
        manual.new_page().insert_text((30, 30), "Manual test")
        pdf = manual.tobytes()
        manual.close()
        payload = {"category_code": "03", "category_name": "使用说明图", "sub_category": "中文说明", "material_type": "manualZh"}
        uploaded = self.client.post("/api/products/API-ASSET-1/assets/upload", data=payload,
            files=[("files", ("manual.pdf", pdf, "application/pdf"))])
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["items"][0]["asset_type"], "document")
        self.assertEqual(uploaded.json()["items"][0]["mime_type"], "application/pdf")
        rejected = self.client.post("/api/products/API-ASSET-1/assets/upload", data=payload,
            files=[("files", ("fake.pdf", b"not a PDF", "application/pdf"))])
        self.assertEqual(rejected.status_code, 400, rejected.text)

    def test_lifecycle_review_is_audited_and_log_failure_rolls_back(self):
        base = "/api/products/API-ASSET-1/assets"
        created = self.client.post(base, json={
            "category_code": "01",
            "category_name": "产品标准图",
            "url": "/uploads/assets/API-ASSET-1/lifecycle.png",
        })
        self.assertEqual(created.status_code, 200, created.text)
        asset_id = created.json()["id"]
        changes = {
            "review_status": "approved",
            "authorization_status": "authorized",
            "is_public": True,
            "ai_reference_usable": True,
        }
        with patch("app.services.operation_log_service.log_operation", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.put(f"{base}/{asset_id}", json=changes)
        with self.Session() as db:
            row = db.get(ProductAsset, asset_id)
            self.assertEqual(row.review_status, "pending")
            self.assertEqual(row.authorization_status, "unknown")
            self.assertFalse(row.is_public)
            self.assertFalse(row.ai_reference_usable)

        updated = self.client.put(f"{base}/{asset_id}", json=changes)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json()["is_public"])
        self.assertTrue(updated.json()["ai_reference_usable"])
        with self.Session() as db:
            log = db.query(OperationLog).filter_by(
                action_type="asset_lifecycle_review",
                target_id=asset_id,
            ).one()
            self.assertEqual(log.request_data["before"]["review_status"], "pending")
            self.assertEqual(log.response_data["after"]["review_status"], "approved")
            self.assertEqual(log.response_data["after"]["authorization_status"], "***")

    def test_quality_audit_failure_rolls_back_all_four_write_routes(self):
        base = "/api/products/API-ASSET-1/assets"
        payload = {"category_code": "01", "category_name": "产品标准图", "url": "/uploads/checked.png"}
        original = self.client.post(base, json=payload).json()
        checks = {"quality_check_tags": ["完整性通过"]}
        with patch("app.services.operation_log_service.log_operation", side_effect=RuntimeError("audit failed")):
            requests = [
                lambda: self.client.post(base, json={**payload, "tags": checks}),
                lambda: self.client.post(f"{base}/batch", json=[{**payload, "tags": checks}, {**payload, "tags": checks}]),
                lambda: self.client.put(f"{base}/{original['id']}", json={"tags": checks, "maintainer": "Should rollback"}),
                lambda: self.client.patch(f"{base}/{original['id']}/tags", json=checks),
            ]
            for invoke in requests:
                with self.assertRaises(RuntimeError):
                    invoke()
                with self.Session() as db:
                    self.assertEqual(db.query(ProductAsset).count(), 1)
                    row = db.get(ProductAsset, original["id"])
                    self.assertEqual(row.maintainer, original["maintainer"])
                    self.assertEqual(row.tags, "{}")
                    self.assertEqual(db.query(OperationLog).count(), 0)

    def test_upload_audit_failure_rolls_back_only_new_records_and_files(self):
        existing = self.client.post("/api/products/API-ASSET-1/assets", json={
            "category_code": "01", "category_name": "产品标准图", "url": "/uploads/existing.png",
        })
        self.assertEqual(existing.status_code, 200)
        image = io.BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(image, format="PNG")
        for path, form in [("/api/products/API-ASSET-1/assets/upload", {"category_code": "01", "category_name": "产品标准图"}),
                           ("/api/competitor-assets/upload", {"brand": "A"})]:
            with patch("app.services.operation_log_service.log_operation", side_effect=RuntimeError("audit failed")):
                with self.assertRaises(RuntimeError):
                    self.client.post(path, data=form, files={"files": ("new.png", image.getvalue(), "image/png")})
            with self.Session() as db:
                self.assertEqual(db.query(ProductAsset).count(), 1)
                self.assertIsNotNone(db.get(ProductAsset, existing.json()["id"]))
                self.assertEqual(db.query(CompetitorAsset).count(), 0)
                self.assertEqual(db.query(OperationLog).count(), 0)
            self.assertEqual(list(Path(settings.UPLOAD_DIR).rglob("*.png")), [])
            self.assertEqual(list(Path(settings.UPLOAD_DIR).rglob("*.jpg")), [])

    def test_competitor_metadata_edit_permissions_audit_and_rollback(self):
        image = io.BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(image, format="PNG")
        uploaded = self.client.post("/api/competitor-assets/upload", data={"brand": "A"},
                                    files={"files": ("ref.png", image.getvalue(), "image/png")})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        original = uploaded.json()["items"][0]
        path = f"/api/competitor-assets/{original['id']}"
        for payload in ({"url": "/uploads/replace.png"}, {"uploaded_by": "other"}, {"is_public": True}, {"brand": None}, {"brand": "  "}):
            self.assertEqual(self.client.patch(path, json=payload).status_code, 422)
        with patch("app.core.security.has_permission", return_value=False):
            self.assertEqual(self.client.patch(path, json={"brand": "B"}).status_code, 403)
        changed = self.client.patch(path, json={"brand": " B ", "maintainer": "Designer", "source_note": "Catalogue"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["brand"], "B")
        self.assertEqual(changed.json()["url"], original["url"])
        self.assertEqual(changed.json()["uploaded_by"], original["uploaded_by"])
        with self.Session() as db:
            log = db.query(OperationLog).filter_by(action_type="competitor_asset_update").one()
            self.assertEqual(log.operator_id, "test-user")
            self.assertEqual(log.request_data["before"]["brand"], "A")
            self.assertEqual(log.response_data["after"]["brand"], "B")
        with patch("app.api.competitor_assets.operation_log_service.log_operation", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.client.patch(path, json={"brand": "C"})
        with self.Session() as db:
            self.assertEqual(db.get(CompetitorAsset, original["id"]).brand, "B")
        cleared = self.client.patch(path, json={"source_note": None})
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["source_note"])
        self.assertEqual(cleared.json()["maintainer"], "Designer")

    def test_competitor_upload_is_independent_and_audited(self):
        image = io.BytesIO()
        Image.new("RGB", (16, 16), color=(10, 20, 30)).save(image, format="PNG")
        response = self.client.post("/api/competitor-assets/upload", data={"brand": " Brand A ", "maintainer": "Designer"},
                                    files={"files": ("ref.png", image.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertTrue(item["url"].startswith("/uploads/competitors/"))
        self.assertTrue(item["thumbnail_url"].startswith("/uploads/competitors/"))
        self.assertEqual(item["uploaded_by"], "test-user")
        self.assertEqual(item["maintainer"], "Designer")
        self.assertNotIn("sku", item)
        self.assertEqual(self.client.get("/api/products/API-ASSET-1/assets").json(), [])
        self.assertEqual(self.client.get("/api/competitor-assets/brands").json()["items"], [{"brand": "Brand A", "image_count": 1, "video_count": 0}])
        self.assertEqual(len(self.client.get("/api/competitor-assets", params={"brand": "Brand A", "asset_type": "image"}).json()["items"]), 1)
        with self.Session() as db:
            self.assertEqual(db.query(OperationLog).filter_by(action_type="competitor_asset_upload").one().operator_id, "test-user")

    def test_competitor_file_signing_requires_specific_access(self):
        from app.api.files import _authorize_sign_request, _authorize_sign_batch
        from fastapi import HTTPException
        user = User(id="limited")
        path = "/uploads/competitors/batch/ref.png"
        with patch("app.api.files.has_permission", side_effect=lambda db, user_id, key: key == "media.read"):
            for action in (_authorize_sign_request, lambda db, user, path: _authorize_sign_batch(db, user, [path])):
                with self.assertRaises(HTTPException) as raised:
                    action(None, user, path)
                self.assertEqual(raised.exception.status_code, 403)
        with patch("app.api.files.has_permission", side_effect=lambda db, user_id, key: key == "competitor.view"):
            _authorize_sign_request(None, user, path)
            _authorize_sign_batch(None, user, [path])
            with self.assertRaises(HTTPException) as raised:
                _authorize_sign_request(None, user, path, "download")
            self.assertEqual(raised.exception.status_code, 403)

    def test_competitor_database_failure_compensates_saved_files(self):
        image = io.BytesIO()
        Image.new("RGB", (8, 8), color=(5, 6, 7)).save(image, format="PNG")
        with patch("app.api.competitor_assets.service.create_uploaded_asset", side_effect=RuntimeError("db failed")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/competitor-assets/upload", data={"brand": "A"},
                                 files={"files": ("ref.png", image.getvalue(), "image/png")})
        self.assertEqual(list(Path(settings.UPLOAD_DIR).rglob("*.png")), [])
        self.assertEqual(list(Path(settings.UPLOAD_DIR).rglob("*.jpg")), [])
        with self.Session() as db:
            self.assertEqual(db.query(CompetitorAsset).count(), 0)

    def test_initial_quality_checks_log_each_created_asset(self):
        base = "/api/products/API-ASSET-1/assets"
        payload = {
            "category_code": "01", "category_name": "产品标准图",
            "url": "/uploads/assets/API-ASSET-1/checked.jpg",
            "tags": {"quality_check_tags": ["完整性通过"]},
        }
        single = self.client.post(base, json=payload)
        self.assertEqual(single.status_code, 200, single.text)
        batch = self.client.post(f"{base}/batch", json=[payload, {**payload, "tags": {}}])
        self.assertEqual(batch.status_code, 200, batch.text)
        expected_ids = {single.json()["id"], batch.json()[0]["id"]}
        with self.Session() as db:
            logs = db.query(OperationLog).filter_by(action_type="asset_quality_check").all()
            self.assertEqual({log.target_id for log in logs}, expected_ids)
            self.assertEqual(len(logs), 2)
            for log in logs:
                self.assertEqual(log.operator_id, "test-user")
                self.assertEqual(log.request_data["before"], [])
                self.assertEqual(log.response_data["after"], ["完整性通过"])

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
                ProductAssetLink.__table__,
                CompetitorAsset.__table__,
                User.__table__,
                Group.__table__,
                UserGroup.__table__,
                Permission.__table__,
                GroupPermission.__table__,
                OperationLog.__table__,
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

    def test_quality_checks_require_review_permission_and_record_reviewer(self):
        base = "/api/products/API-ASSET-1/assets"
        payload = {"category_code": "01", "category_name": "产品标准图", "url": "/uploads/quality.jpg"}
        created = self.client.post(base, json=payload)
        self.assertEqual(created.status_code, 200)
        asset_id = created.json()["id"]
        checks = {"quality_check_tags": ["完整性通过", "复用性需修改"]}
        with patch("app.api.assets.has_permission", return_value=False):
            self.assertEqual(self.client.patch(f"{base}/{asset_id}/tags", json=checks).status_code, 403)
            self.assertEqual(self.client.put(f"{base}/{asset_id}", json={"tags": checks}).status_code, 403)
            self.assertEqual(self.client.post(base, json={**payload, "tags": checks}).status_code, 403)
        updated = self.client.patch(f"{base}/{asset_id}/tags", json=checks)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["tags"]["quality_check_tags"], checks["quality_check_tags"])
        self.assertFalse(updated.json()["is_public"])
        with self.Session() as db:
            log = db.query(OperationLog).filter_by(action_type="asset_quality_check", target_id=asset_id).one()
            self.assertEqual(log.operator_id, "test-user")
            self.assertEqual(log.response_data["after"], checks["quality_check_tags"])
        with patch("app.api.assets.has_permission", return_value=False):
            # A full edit cannot erase checks through an unguarded nested tags object.
            self.assertEqual(self.client.put(f"{base}/{asset_id}", json={"tags": {}}).status_code, 403)
            self.assertEqual(self.client.patch(f"{base}/{asset_id}/tags", json={"subject_tags": ["主体"]}).status_code, 200)
        self.assertEqual(self.client.get(f"{base}/{asset_id}").json()["tags"]["quality_check_tags"], checks["quality_check_tags"])

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
                "sub_category": "场景短视频（≤30秒）",
                "material_type": "video",
            },
            files={"files": ("bad.png", io.BytesIO(b"not really image"), "image/png")},
        )

        self.assertEqual(response.status_code, 400)

    def test_scene_upload_merges_subcategory_and_explicit_environment_tags(self):
        image_data = io.BytesIO()
        Image.new("RGB", (16, 16), color=(20, 80, 140)).save(image_data, format="PNG")
        response = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data={
                "category_code": "04",
                "category_name": "场景内容图",
                "sub_category": "森林",
                "material_type": "forest",
                "maintainer": "视觉设计师",
                "material_type_tags": ["白底图", "配件图", "多角度图"],
                "composition_tags": ["纯产品"],
                "scene_tags": ["森林", "湖边"],
                "channel_tags": ["Amazon", "天猫"],
            },
            files={"files": ("scene.png", image_data.getvalue(), "image/png")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        tags = item["tags"]
        self.assertEqual(tags["material_type_tags"], ["白底图", "配件图", "多角度图"])
        self.assertEqual(tags["scene_tags"], ["森林", "湖边"])
        self.assertEqual(tags["composition_tags"], ["纯产品"])
        self.assertEqual(tags["expression_tags"], ["场景图"])
        self.assertEqual(tags["channel_tags"], ["Amazon", "天猫"])
        self.assertEqual(item["channel"], "Amazon")
        self.assertEqual(item["maintainer"], "视觉设计师")

    def test_upload_stores_multiple_category_associations_on_one_asset(self):
        image_data = io.BytesIO()
        Image.new("RGB", (16, 16), color=(220, 220, 220)).save(image_data, format="PNG")
        response = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data={
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "category_tags": ["05/国内电商"],
            },
            files={"files": ("white-domestic.png", image_data.getvalue(), "image/png")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertEqual(item["tags"]["category_tags"], ["01/白底图", "05/国内电商"])
        self.assertEqual(
            len(self.client.get("/api/assets/search", params={"category_tags": "05/国内电商"}).json()["items"]),
            1,
        )

    def test_upload_accepts_video_category_video(self):
        import av
        clip = io.BytesIO()
        with av.open(clip, mode="w", format="mp4") as container:
            stream = container.add_stream("mpeg4", rate=1)
            stream.width = stream.height = 16
            stream.pix_fmt = "yuv420p"
            frame = av.VideoFrame.from_image(Image.new("RGB", (16, 16), "white"))
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        response = self.client.post(
            "/api/products/API-ASSET-1/assets/upload",
            data={
                "category_code": "06",
                "category_name": "视频素材",
                "sub_category": "场景短视频（≤30秒）",
                "material_type": "video",
                "maintainer": "素材负责人",
                "subject_tags": ["主体", "配件"],
                "composition_tags": ["纯产品"],
                "view_tags": ["正视"],
            },
            files={"files": ("clip.mp4", io.BytesIO(clip.getvalue()), "video/mp4")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["asset_type"], "video")
        self.assertEqual(payload["items"][0]["sub_category"], "场景短视频（≤30秒）")
        self.assertEqual(payload["items"][0]["material_type"], "sceneShortVideo")
        self.assertEqual(payload["items"][0]["maintainer"], "素材负责人")
        self.assertEqual(payload["items"][0]["tags"]["subject_tags"], ["主体", "配件"])
        self.assertEqual(payload["items"][0]["tags"]["composition_tags"], ["纯产品"])
        self.assertEqual(payload["items"][0]["tags"]["view_tags"], ["正视"])
        self.assertEqual(payload["items"][0]["tags"]["video_duration_status"], ["measured"])
        self.assertEqual(float(payload["items"][0]["tags"]["video_duration_seconds"][0]), 1.0)
        forged_tags = {**payload["items"][0]["tags"], "video_duration_seconds": ["60"]}
        self.assertEqual(self.client.put(f"/api/products/API-ASSET-1/assets/{payload['items'][0]['id']}", json={"tags": forged_tags}).status_code, 422)
        replaced = self.client.put(f"/api/products/API-ASSET-1/assets/{payload['items'][0]['id']}", json={"url": "/uploads/different.mp4"})
        self.assertEqual(replaced.status_code, 422, replaced.text)
        self.assertEqual(self.client.get(f"/api/products/API-ASSET-1/assets/{payload['items'][0]['id']}").json()["url"], payload["items"][0]["url"])
        rejected = self.client.post("/api/products/API-ASSET-1/assets/upload", data={
            "category_code": "06", "category_name": "视频素材", "sub_category": "场景长视频（>30秒）",
        }, files={"files": ("clip.mp4", io.BytesIO(clip.getvalue()), "video/mp4")})
        self.assertEqual(rejected.status_code, 400)

        with self.Session() as db:
            log = db.query(OperationLog).filter_by(
                action_type="asset_upload",
                target_id="API-ASSET-1",
            ).one()
            self.assertEqual(log.operator_id, "test-user")
            self.assertEqual(log.operator_name_snapshot, "tester")
            self.assertEqual(log.response_data["asset_ids"], [payload["items"][0]["id"]])

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
                    "maintainer": "视觉设计师" if sku == "API-ASSET-1" else "产品经理",
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

        by_maintainer = self.client.get("/api/assets/search", params={"maintainer": "视觉"})
        self.assertEqual(by_maintainer.status_code, 200, by_maintainer.text)
        self.assertEqual([item["sku"] for item in by_maintainer.json()["items"]], ["API-ASSET-1"])

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
                    "quality_check_tags": ["完整性通过"],
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
                ("quality_check_tags", "完整性通过"),
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

        alternatives = self.client.get(
            "/api/assets/search",
            params=[
                ("quality_check_tags", "完整性通过"),
                ("quality_check_tags", "完整性需修改"),
            ],
        )
        self.assertEqual(alternatives.status_code, 200, alternatives.text)
        self.assertEqual([item["sku"] for item in alternatives.json()["items"]], ["API-ASSET-1"])

    def test_taxonomy_and_lifecycle_filters_are_available(self):
        taxonomy = self.client.get("/api/assets/taxonomy")
        self.assertEqual(taxonomy.status_code, 200, taxonomy.text)
        payload = taxonomy.json()
        self.assertEqual([item["code"] for item in payload["categories"]], ["01", "02", "03", "04", "05", "06", "07", "08"])
        ecommerce = next(item for item in payload["categories"] if item["code"] == "05")
        self.assertEqual(
            [item["name"] for item in ecommerce["sub_categories"]],
            ["国内电商", "跨境电商", "国内品牌", "跨境品牌"],
        )
        self.assertEqual(payload["dimensions"]["scene_tags"]["values"], ["徒步", "汽车露营", "骑行", "摩旅", "狩猎", "垂钓", "硬核露营", "车露", "家庭露营", "雪地", "森林", "湖边", "室内"])
        self.assertIn("suspected_duplicate", payload["quality_statuses"])
        self.assertIn("cross_sku_reuse", payload["duplicate_statuses"])
        self.assertEqual(payload["review_statuses"], ["pending", "approved", "rejected", "disabled", "archived"])
        self.assertIn("authorized", payload["authorization_statuses"])

        invalid_authorization = self.client.post(
            "/api/products/API-ASSET-1/assets",
            json={
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/API-ASSET-1/invalid-authorization.jpg",
                "authorization_status": "custom_grant",
            },
        )
        self.assertEqual(invalid_authorization.status_code, 422, invalid_authorization.text)

        invalid_classification = self.client.post(
            "/api/products/API-ASSET-1/assets",
            json={
                "category_code": "05",
                "category_name": "电商与品牌图",
                "sub_category": "国内电商",
                "material_type": "aPlus",
                "url": "/uploads/assets/API-ASSET-1/wrong-placement.jpg",
            },
        )
        self.assertEqual(invalid_classification.status_code, 422, invalid_classification.text)

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

        disabled_scope = self.client.get(
            "/api/assets/search",
            params={
                "is_public": "false",
                "ai_customer_usable": "false",
                "ai_marketing_usable": "false",
                "ai_reference_usable": "false",
            },
        )
        self.assertEqual(disabled_scope.status_code, 200, disabled_scope.text)
        self.assertEqual([item["id"] for item in disabled_scope.json()["items"]], [asset["id"]])
        self.assertEqual(
            self.client.get("/api/assets/search", params={"is_public": "true"}).json()["items"],
            [],
        )

        expression_only = self.client.get("/api/assets/search", params={"expression_tags": "卖点图"})
        self.assertEqual(expression_only.status_code, 200, expression_only.text)

        invalid_tag = self.client.get("/api/assets/search", params={"scene_tags": "studio"})
        self.assertEqual(invalid_tag.status_code, 422)


if __name__ == "__main__":
    unittest.main()
