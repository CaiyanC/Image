"""Run with unittest to avoid the shared conftest's app.main import/startup.

All HTTP routes use a standalone FastAPI instance and an in-memory SQLite DB.
"""

import asyncio
import json
import unittest
from datetime import datetime
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import JSON, MetaData, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import drafts, products
from app.core import database
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models import Product, ProductAsset, ProductMedia, ProductSpecs, ProductContent, User, Group, UserGroup
from app.models.product_draft import ProductDraft
from app.models.product_qa import ProductQa, ProductQaNegative
from app.models.product_operation_snapshot import ProductOperationSnapshot
from app.models.permissions import Permission, GroupPermission
from app.services import draft_service, product_service, product_asset_sync_service, product_recovery_service
from app.services.product_write_authorization import authorize_product_replacement


class ProductMediaAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        tables = {
            "users", "groups", "user_groups", "permissions", "group_permissions",
            "products", "product_assets", "product_media", "product_specs", "product_business",
            "product_content", "product_qa", "product_qa_negative", "product_prompts",
            "listing_channels", "product_listing_channels", "sales_regions", "product_sales_regions",
            "certifications", "product_certifications", "keywords", "product_keywords",
            "knowledge_documents", "knowledge_chunks", "product_operation_snapshots",
        }
        Base.metadata.create_all(self.engine, tables=[Base.metadata.tables[name] for name in tables])
        # Compile only this test's cloned draft table with SQLite JSON; never
        # mutate production model metadata or install a global JSONB compiler.
        draft_metadata = MetaData()
        Product.__table__.to_metadata(draft_metadata)
        draft_table = ProductDraft.__table__.to_metadata(draft_metadata)
        draft_table.c.draft_data.type = JSON()
        draft_metadata.create_all(self.engine, tables=[draft_table])
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = User(id="writer", username="writer", email="writer@test.invalid", password_hash="unused")
        self.db.add_all([
            self.user, Group(id="writers", group_name="Scoped writers"),
            UserGroup(user_id="writer", group_id="writers", group_role="member"),
        ])
        self.payload = {"sku": "A", "barcode": "A", "product_name_cn": "Alpha", "brand": "Brand"}
        self.db.add_all([
            Product(id="product-a", **self.payload),
            Product(id="product-b", sku="B", barcode="B", product_name_cn="Beta", brand="Brand"),
            ProductSpecs(product_id="product-a", capacity="1L", power="100W",
                         technical_advantages='["durable"]', usage_instruction="Use normally"),
            ProductContent(product_id="product-a", title_cn="Title", long_description_cn="Description"),
        ])
        self.db.commit()
        self.permissions("product.edit", "media.upload")

        app = FastAPI()
        app.include_router(drafts.router)
        app.include_router(products.router)

        def session():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = session
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.audit_review_product_qas = products._audit_review_product_qas
        for target, name, replacement in (
            (database.engine, "connect", lambda *a, **k: self.fail("Real database access")),
            (products.operation_log_service, "log_operation", lambda *a, **k: None),
            (products, "_record_product_snapshot", lambda *a, **k: None),
            (products, "_audit_review_product_qas", AsyncMock(return_value=[])),
            (product_service, "sync_product_to_vector_db", lambda *a, **k: {}),
            (draft_service, "sync_product_to_vector_db", lambda *a, **k: {}),
        ):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def permissions(self, *keys):
        self.db.query(GroupPermission).delete()
        for key in keys:
            permission = self.db.query(Permission).filter_by(permission_key=key).first()
            if permission is None:
                permission = Permission(permission_key=key, permission_name=key)
                self.db.add(permission)
                self.db.flush()
            self.db.add(GroupPermission(group_id="writers", permission_id=permission.id))
        self.db.commit()

    def media(self, **extra):
        row = ProductMedia(
            id="legacy-a", product_id="product-a", sku="A", media_group="raw",
            file_name="a.jpg", file_path="https://test.invalid/a.jpg", **extra,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def asset(self, **extra):
        row = ProductAsset(
            id="asset-a", sku="A", category_code="01", category_name="Standard",
            url="https://test.invalid/a.jpg", **extra,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def asset_payload(self, row):
        return {
            column.name: getattr(row, column.name) for column in row.__table__.columns
            if column.name not in {"created_at", "updated_at"}
        }

    def full_payload(self, **changes):
        return {
            **self.payload, "specs": {
                "capacity": "1L", "power": "100W", "technical_advantages": ["durable"],
                "usage_instruction": "Use normally",
            }, "content": {"title_cn": "Title", "long_description_cn": "Description"}, **changes,
        }

    def full(self, **changes):
        return self.client.put("/api/products/A/full", json=self.full_payload(**changes))

    def draft(self, data, *, sku="A", owner="writer"):
        row = ProductDraft(sku=sku, draft_data=data, created_by=owner)
        self.db.add(row)
        self.db.commit()
        return row

    def publish(self, draft):
        return self.client.post(f"/api/products/drafts/{draft.id}/publish")

    def qa(self, *, qa_id="qa-a", status="approved"):
        row = ProductQa(id=qa_id, product_id="product-a", question=qa_id, answer="Answer",
                        tags='["care"]', priority=1, integrity_status=status,
                        integrity_reason="Original reason", integrity_model="auditor",
                        integrity_audited_at=datetime(2026, 1, 2))
        self.db.add(row)
        self.db.commit()
        return row

    def test_create_only_cannot_publish_nested_qa_or_negative(self):
        self.permissions("product.create")
        for section in ({"qa_items": [{"question": "Q", "answer": "A"}]},
                        {"qa_negative": {"response_tone": "Friendly"}}):
            with self.subTest(section=section):
                draft = self.draft(self.full_payload(sku="NEW", **section), sku="NEW")
                response = self.publish(draft)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn("product.qa.manage", response.text)
                self.db.expire_all()
                self.assertIsNotNone(self.db.get(ProductDraft, draft.id))
                self.assertIsNone(self.db.query(Product).filter_by(sku="NEW").first())

    def test_direct_create_authorizes_nested_qa_and_media(self):
        self.permissions("product.create")
        for extra in ({"qa_items": [{"question": "Q"}]},
                      {"qa_negative": {"response_tone": "Friendly"}},
                      {"media_data": {"source_white_bg": ["https://test.invalid/new.jpg"]}},
                      {"assets": [{"category_code": "01", "category_name": "Standard", "url": "new.jpg"}]}):
            with self.subTest(extra=extra):
                response = self.client.post("/api/products", json=self.full_payload(sku="NEW", **extra))
                self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNone(self.db.query(Product).filter_by(sku="NEW").first())
        response = self.client.post("/api/products", json=self.full_payload(sku="NEW", qa_items=[]))
        self.assertEqual(response.status_code, 200, response.text)

    def test_create_with_qa_manage_or_edit_can_add_review_qa(self):
        for index, permission in enumerate(("product.qa.manage", "product.edit")):
            with self.subTest(permission=permission):
                self.permissions("product.create", permission)
                sku = f"NEW-{index}"
                payload = self.full_payload(sku=sku, qa_items=[{"question": "Q", "answer": "A"}],
                                            qa_negative={"response_tone": "Friendly"})
                response = (self.client.post("/api/products", json=payload) if index == 0
                            else self.publish(self.draft(payload, sku=sku)))
                self.assertEqual(response.status_code, 200, response.text)
                product = self.db.query(Product).filter_by(sku=sku).one()
                qa = self.db.query(ProductQa).filter_by(product_id=product.id).one()
                self.assertEqual(qa.integrity_status, "review")
                self.assertIsNone(qa.integrity_model)
                self.assertIsNone(qa.integrity_audited_at)

    def test_new_qa_cannot_inject_audit_metadata_via_create_or_draft(self):
        self.permissions("product.create", "product.qa.manage")
        for field, value in (("integrity_status", "approved"), ("integrity_model", "forged"),
                             ("integrity_reason", "trusted"), ("integrity_audited_at", "2026-01-01")):
            payload = self.full_payload(sku="NEW", qa_items=[{"question": "Q", field: value}])
            for endpoint in ("create", "draft"):
                with self.subTest(field=field, endpoint=endpoint):
                    response = (self.client.post("/api/products", json=payload) if endpoint == "create"
                                else self.publish(self.draft(payload, sku="NEW")))
                    self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNone(self.db.query(Product).filter_by(sku="NEW").first())

    def test_full_noop_qa_preserves_all_records_and_audit_metadata(self):
        rows = [self.qa(), self.qa(qa_id="qa-review", status="review"), self.qa(qa_id="qa-rejected", status="rejected")]
        negative = ProductQaNegative(id="negative-a", product_id="product-a", response_tone="Friendly")
        self.db.add(negative)
        self.db.commit()
        self.db.expire_all()  # compare DB timestamp values, not SQLite's pre-flush timezone objects
        before = {row.id: product_service.model_to_dict(row) for row in [*rows, negative]}
        self.permissions("product.edit")
        details = product_service.get_product_detail(self.db, "A")
        response = self.full(qa_items=list(reversed(details["qa_items"])), qa_negative=details["qa_negative"])
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        pid = self.db.query(Product).filter_by(sku="A").one().id
        self.assertNotEqual(pid, "product-a")
        for row_id, record in before.items():
            model = ProductQaNegative if row_id == "negative-a" else ProductQa
            saved = product_service.model_to_dict(self.db.get(model, row_id))
            self.assertEqual(saved, {**record, "product_id": pid})
        self.assertEqual(products._audit_review_product_qas.call_args.kwargs["preserved_ids"],
                         {"qa-a", "qa-review", "qa-rejected"})
        auditor = AsyncMock()
        with patch.object(products.product_qa_integrity_service, "audit_product_qa_item", auditor):
            asyncio.run(self.audit_review_product_qas(
                self.db, self.db.query(Product).filter_by(sku="A").one(), self.user,
                preserved_ids={"qa-a", "qa-review", "qa-rejected"},
            ))
        auditor.assert_not_called()

    def test_draft_noop_id_free_json_qa_keeps_identity_and_approval(self):
        row = self.qa()
        self.db.refresh(row)
        before = product_service.model_to_dict(row)
        self.permissions("product.edit")
        response = self.publish(self.draft({"qa_items": [{
            "question": "qa-a", "answer": "Answer", "tags": ["care"], "priority": 1,
        }]}))
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(product_service.model_to_dict(self.db.get(ProductQa, "qa-a")), before)

    def test_full_omitted_qa_preserves_while_explicit_empty_deletes(self):
        self.qa()
        self.permissions("product.edit")
        response = self.full()
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(ProductQa, "qa-a").integrity_status, "approved")
        response = self.full(qa_items=[])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(ProductQa).count(), 0)

    def test_changed_qa_review_reset_does_not_touch_unchanged_sibling(self):
        for endpoint in ("draft", "full"):
            with self.subTest(endpoint=endpoint):
                self.db.query(ProductQa).delete()
                self.db.commit()
                product = self.db.query(Product).filter_by(sku="A").one()
                for qa_id in ("unchanged", "changed"):
                    self.db.add(ProductQa(id=qa_id, product_id=product.id, question=qa_id, answer="A",
                                         integrity_status="approved", integrity_model="original"))
                self.db.commit()
                self.permissions("product.edit")
                qas = [{"id": "unchanged", "question": "unchanged", "answer": "A", "integrity_status": "approved"},
                       {"id": "changed", "question": "changed", "answer": "Different", "integrity_status": "approved"}]
                response = (self.full(qa_items=qas) if endpoint == "full" else self.publish(self.draft({"qa_items": qas})))
                self.assertEqual(response.status_code, 200, response.text)
                self.db.expire_all()
                self.assertEqual(self.db.get(ProductQa, "unchanged").integrity_status, "approved")
                changed = self.db.query(ProductQa).filter_by(answer="Different").one()
                self.assertEqual(changed.integrity_status, "review")
                self.assertIsNone(changed.integrity_model)

    def test_full_and_draft_cannot_forge_approval_or_cross_sku_qa(self):
        self.qa(status="review")
        self.permissions("product.edit")
        for qa_id, status, expected in (("qa-a", "approved", 403), ("other-product-qa", "review", 404)):
            payload = {"qa_items": [{"id": qa_id, "question": "qa-a", "answer": "Answer", "tags": ["care"],
                                     "priority": 1, "integrity_status": status}]}
            for endpoint in ("full", "draft"):
                with self.subTest(endpoint=endpoint, qa_id=qa_id):
                    response = (self.full(**payload) if endpoint == "full" else self.publish(self.draft(payload)))
                    self.assertEqual(response.status_code, expected, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(ProductQa, "qa-a").integrity_status, "review")

    def test_legacy_all_operations_require_both_permissions(self):
        self.media()
        for keys in ((), ("product.edit",), ("media.upload",), ("media.review", "tag.edit")):
            self.permissions(*keys)
            for method, path, payload in (
                ("post", "/api/products/A/media", {"file_name": "new.jpg"}),
                ("put", "/api/products/A/media/legacy-a", {"file_name": "changed.jpg"}),
                ("delete", "/api/products/A/media/legacy-a", None),
            ):
                with self.subTest(keys=keys, method=method):
                    response = self.client.request(method, path, **({"json": payload} if payload else {}))
                    self.assertEqual(response.status_code, 403, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(ProductMedia, "legacy-a").file_name, "a.jpg")

    def test_legacy_review_fields_require_review_on_create_and_update(self):
        self.media()
        fields = {
            "review_status": "approved", "authorization_status": "authorized", "media_level": "A",
            "is_public": True, "ai_customer_usable": True, "ai_marketing_usable": True,
            "ai_reference_usable": True, "forbidden_usage": "advertising", "is_competitor": True,
            "is_real_product": False, "is_ai_generated": True, "editable_flag": True,
        }
        for key, value in fields.items():
            for method, path in (("post", "/api/products/A/media"), ("put", "/api/products/A/media/legacy-a")):
                with self.subTest(field=key, method=method):
                    response = self.client.request(method, path, json={key: value})
                    self.assertEqual(response.status_code, 403, response.text)
                    self.assertIn("media.review", response.text)

    def test_legacy_tags_require_tag_edit_including_null_clear(self):
        self.media(tag_list='["original"]')
        for value in (["new"], None):
            response = self.client.put("/api/products/A/media/legacy-a", json={"tag_list": value})
            self.assertEqual(response.status_code, 403)
            self.assertIn("tag.edit", response.text)
        response = self.client.post("/api/products/A/media", json={"tag_list": ["new"]})
        self.assertEqual(response.status_code, 403)

    def test_legacy_unchanged_approved_fields_and_json_tags_are_allowed(self):
        self.media(review_status="approved", tag_list='["original"]')
        response = self.client.put("/api/products/A/media/legacy-a", json={
            "review_status": "approved", "tag_list": ["original"], "file_name": "renamed.jpg",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_legacy_file_swap_cannot_reuse_approval(self):
        self.media(review_status="approved")
        response = self.client.put("/api/products/A/media/legacy-a", json={"file_path": "other.jpg"})
        self.assertEqual(response.status_code, 403, response.text)
        self.permissions("product.edit", "media.upload", "media.review")
        response = self.client.put("/api/products/A/media/legacy-a", json={"file_path": "other.jpg"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_legacy_cross_sku_fails_in_routes_and_service(self):
        self.media()
        for method in ("put", "delete"):
            response = self.client.request(method, "/api/products/B/media/legacy-a", **(
                {"json": {"file_name": "evil.jpg"}} if method == "put" else {}
            ))
            self.assertEqual(response.status_code, 404, response.text)
        for operation in (
            lambda: product_service.update_product_media(self.db, "legacy-a", {}, sku="B"),
            lambda: product_service.delete_product_media(self.db, "legacy-a", sku="B"),
        ):
            with self.assertRaises(HTTPException) as caught:
                operation()
            self.assertEqual(caught.exception.status_code, 404)
        self.assertIsNotNone(self.db.get(ProductMedia, "legacy-a"))

    def test_legacy_corrupt_sku_product_binding_fails_closed(self):
        row = self.media()
        row.product_id = "product-b"
        self.db.commit()
        response = self.client.delete("/api/products/A/media/legacy-a")
        self.assertEqual(response.status_code, 404)

    def test_legacy_permitted_create_update_delete(self):
        response = self.client.post("/api/products/A/media", json={"file_name": "new.jpg", "file_path": "new.jpg"})
        self.assertEqual(response.status_code, 200, response.text)
        path = f"/api/products/A/media/{response.json()['id']}"
        self.assertEqual(self.client.put(path, json={"file_name": "renamed.jpg"}).status_code, 200)
        self.assertEqual(self.client.delete(path).status_code, 200)

    def test_full_unchanged_approved_snapshot_does_not_need_media_permissions(self):
        row = self.asset(review_status="approved", authorization_status="authorized", is_public=True,
                         tags='{"risk_tags": ["restricted"], "scene_tags": ["studio"]}')
        snapshot = self.asset_payload(row)
        snapshot["tags"] = json.loads(snapshot["tags"])
        self.permissions("product.edit")
        response = self.full(product_name_cn="Renamed", assets=[snapshot])
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        saved = self.db.query(ProductAsset).filter_by(sku="A").one()
        self.assertEqual(saved.review_status, "approved")
        self.assertTrue(saved.is_public)
        self.assertEqual(json.loads(saved.tags), snapshot["tags"])

    def test_full_asset_add_delete_and_change_require_upload(self):
        row = self.asset()
        self.permissions("product.edit")
        item = self.asset_payload(row)
        for assets in ([], [{**item, "notes": "changed"}], [item, {
            "category_code": "01", "category_name": "Standard", "url": "https://test.invalid/new.jpg",
        }]):
            with self.subTest(assets=assets):
                response = self.full(assets=assets)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertIn("media.upload", response.text)
        self.assertEqual(self.db.query(ProductAsset).count(), 1)

    def test_full_review_and_tag_changes_require_separate_permissions(self):
        row = self.asset()
        item = self.asset_payload(row)
        for key, value, permission in (
            ("review_status", "approved", "media.review"),
            ("authorization_status", "authorized", "media.review"),
            ("quality_status", "unusable", "media.review"),
            ("is_competitor", True, "media.review"),
            ("tags", {"scene_tags": ["studio"]}, "tag.edit"),
        ):
            response = self.full(assets=[{**item, key: value}])
            self.assertEqual(response.status_code, 403, response.text)
            self.assertIn(permission, response.text)
        self.permissions("product.edit", "media.upload", "tag.edit")
        response = self.full(assets=[{**item, "tags": {"risk_tags": ["restricted"]}}])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)

    def test_full_omitted_review_field_is_actual_reset_and_requires_review(self):
        row = self.asset(review_status="approved")
        item = self.asset_payload(row)
        del item["review_status"]
        response = self.full(assets=[item])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)

    def test_full_asset_file_swap_cannot_keep_approved_status(self):
        row = self.asset(review_status="approved")
        item = {**self.asset_payload(row), "url": "https://test.invalid/evil.jpg"}
        response = self.full(assets=[item])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)

    def test_full_foreign_sku_id_and_duplicate_approved_id_are_rejected(self):
        row = self.asset(review_status="approved")
        item = self.asset_payload(row)
        for change, status in (({"sku": "B"}, 400), ({"id": "foreign-asset"}, 404)):
            response = self.full(assets=[{**item, **change}])
            self.assertEqual(response.status_code, status, response.text)
        response = self.full(assets=[item, item])
        self.assertEqual(response.status_code, 403, response.text)

    def test_full_media_aliases_require_upload(self):
        self.permissions("product.edit")
        for key in ("media_data", "media"):
            response = self.full(**{key: {"source_white_bg": ["https://test.invalid/new.jpg"]}})
            self.assertEqual(response.status_code, 403, response.text)
            self.assertIn("media.upload", response.text)

    def test_full_unchanged_media_data_preserves_approval_and_tags(self):
        product_asset_sync_service.sync_product_assets_from_media_data(self.db, self.db.get(Product, "product-a"), {
            "source_white_bg": ["https://test.invalid/a.jpg"],
        })
        self.db.commit()
        row = self.db.query(ProductAsset).one()
        row.review_status = "approved"
        row.is_public = True
        row.tags = '{"scene_tags":["studio"]}'
        row.notes = "Manually maintained note"
        self.db.commit()
        self.permissions("product.edit")
        response = self.full(media_data={"source_white_bg": ["https://test.invalid/a.jpg"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        saved = self.db.query(ProductAsset).one()
        self.assertEqual(saved.review_status, "approved")
        self.assertEqual(json.loads(saved.tags), {"scene_tags": ["studio"]})
        self.assertEqual(saved.notes, "Manually maintained note")

    def test_full_generated_risk_state_requires_review(self):
        response = self.full(media_data={"ref_banned": ["https://test.invalid/a.jpg"]})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)

    def test_full_duplicate_unchanged_source_urls_preserve_both_reviews(self):
        media_data = {"source_white_bg": ["https://test.invalid/a.jpg"] * 2}
        product_asset_sync_service.sync_product_assets_from_media_data(
            self.db, self.db.get(Product, "product-a"), media_data,
        )
        self.db.commit()
        for row in self.db.query(ProductAsset).all():
            row.review_status = "approved"
        self.db.commit()
        self.permissions("product.edit")
        response = self.full(media_data=media_data)
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual([row.review_status for row in self.db.query(ProductAsset).all()], ["approved"] * 2)

    def test_full_review_and_risk_changes_persist_when_authorized(self):
        row = self.asset()
        self.permissions("product.edit", "media.upload", "media.review", "tag.edit")
        response = self.full(assets=[{
            **self.asset_payload(row), "review_status": "approved", "is_public": True,
            "tags": {"risk_tags": ["restricted"]},
        }])
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        saved = self.db.query(ProductAsset).one()
        self.assertEqual(saved.review_status, "approved")
        self.assertEqual(json.loads(saved.tags), {"risk_tags": ["restricted"]})

    def test_full_validation_uses_live_asset_state_over_cached_detail(self):
        row = self.asset(review_status="approved")
        snapshot = self.asset_payload(row)
        product_service.get_product_detail(self.db, "A")  # prime the cache
        row.review_status = "disabled"
        self.db.commit()
        response = self.full(assets=[snapshot])
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)

    def test_full_preserves_manual_assets_when_section_omitted(self):
        self.asset(review_status="approved")
        self.permissions("product.edit")
        response = self.full()
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(ProductAsset).one().review_status, "approved")

    def test_full_new_pending_media_is_allowed_with_upload(self):
        response = self.full(media_data={"source_white_bg": ["https://test.invalid/a.jpg"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(ProductAsset).one().review_status, "pending")

    def test_replacement_validator_is_read_only_and_returns_payload(self):
        original = {**self.payload, "media_data": {"source_white_bg": ["https://test.invalid/a.jpg"]}}
        copy = deepcopy(original)
        result = authorize_product_replacement(self.db, self.user, "A", original)
        self.assertEqual(original, copy)
        self.assertEqual(self.db.query(ProductAsset).count(), 0)
        self.assertEqual(len(result["assets"]), 1)

    def test_full_preserves_legacy_without_upload_and_rebinds_product(self):
        self.media(review_status="approved")
        self.permissions("product.edit")
        response = self.full()
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        row = self.db.get(ProductMedia, "legacy-a")
        self.assertEqual(row.review_status, "approved")
        self.assertEqual(row.sku, "A")
        self.assertNotEqual(row.product_id, "product-a")
        self.assertEqual(row.product_id, self.db.query(Product).filter_by(sku="A").one().id)

    def test_full_accepts_unchanged_legacy_list_and_preserves_all_ids(self):
        first = self.media(review_status="approved", tag_list='["retained"]')
        second = ProductMedia(id="legacy-second", product_id="product-a", sku="A", media_group="raw",
                              file_name="second.jpg", file_path="second.jpg", is_public=True)
        self.db.add(second)
        self.db.commit()
        items = [self.asset_payload(second), self.asset_payload(first)]
        items[1]["tag_list"] = ["retained"]
        self.permissions("product.edit")
        response = self.full(media=items)
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        rows = self.db.query(ProductMedia).all()
        self.assertEqual({row.id for row in rows}, {"legacy-a", "legacy-second"})
        self.assertEqual(len({row.product_id for row in rows}), 1)

    def test_full_rejects_any_legacy_list_change_even_with_all_write_permissions(self):
        row = self.media(review_status="approved")
        original = self.asset_payload(row)
        self.permissions("product.edit", "media.upload", "media.review", "tag.edit")
        for items in ([], [{**original, "review_status": "pending"}], [original, original],
                      [{**original, "file_name": "changed.jpg"}], [{**original, "id": "foreign"}],
                      [{**original, "sku": "B"}], [{**original, "is_real_product": None}], [None]):
            response = self.full(media=items)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn("/media", response.text)
        with self.assertRaises(HTTPException) as caught:
            product_service.replace_product(self.db, "A", self.full_payload(media=[]))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIsNotNone(self.db.get(Product, "product-a"))

    def test_legacy_reinsertion_failure_rolls_back_the_entire_replacement(self):
        self.media(review_status="approved")

        def fail_insert(*args):
            raise RuntimeError("legacy reinsertion failed")

        event.listen(ProductMedia, "before_insert", fail_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "legacy reinsertion"):
                product_service.replace_product(self.db, "A", self.full_payload(product_name_cn="Changed"))
        finally:
            event.remove(ProductMedia, "before_insert", fail_insert)
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, "product-a").product_name_cn, "Alpha")
        row = self.db.get(ProductMedia, "legacy-a")
        self.assertEqual(row.product_id, "product-a")
        self.assertEqual(row.review_status, "approved")

    def test_draft_create_permission_cannot_overwrite_existing_product(self):
        draft = self.draft({"product_name_cn": "Unauthorized"})
        self.permissions("product.create", "media.upload", "media.review")
        response = self.publish(draft)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("product.edit", response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, "product-a").product_name_cn, "Alpha")
        self.assertIsNotNone(self.db.get(ProductDraft, draft.id))

    def test_draft_edit_only_partial_save_preserves_assets_and_legacy(self):
        self.media(review_status="approved")
        self.asset(review_status="approved", tags='{"risk_tags":["restricted"]}')
        draft = self.draft({"product_name_cn": "Changed"})
        draft_id = draft.id
        self.permissions("product.edit")
        response = self.publish(draft)
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, "product-a").product_name_cn, "Changed")
        self.assertEqual(self.db.get(ProductMedia, "legacy-a").review_status, "approved")
        self.assertEqual(self.db.get(ProductAsset, "asset-a").review_status, "approved")
        self.assertIsNone(self.db.get(ProductDraft, draft_id))

    def test_draft_rejects_legacy_list_changes(self):
        self.media(review_status="approved")
        draft = self.draft({"media": []})
        response = self.publish(draft)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("/media", response.text)

    def test_draft_review_and_risk_payloads_cannot_bypass_checks(self):
        row = self.asset()
        self.permissions("product.edit", "media.upload", "tag.edit")
        for change in ({"review_status": "approved"}, {"tags": {"risk_tags": ["restricted"]}},
                       {"authorization_status": "authorized"}, {"is_public": True}):
            draft = self.draft({"assets": [{**self.asset_payload(row), **change}]})
            response = self.publish(draft)
            self.assertEqual(response.status_code, 403, response.text)
            self.assertIn("media.review", response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(ProductAsset, "asset-a").review_status, "pending")

    def test_draft_media_merge_preserves_omitted_sources_and_governance(self):
        product_asset_sync_service.sync_product_assets_from_media_data(
            self.db, self.db.get(Product, "product-a"), {"source_white_bg": ["https://test.invalid/old.jpg"]},
        )
        self.db.commit()
        self.db.query(ProductAsset).one().review_status = "approved"
        self.db.commit()
        self.asset(review_status="approved")  # manual record must also survive
        draft = self.draft({"media_data": {"source_multi_angle": ["https://test.invalid/new.jpg"]}})
        response = self.publish(draft)
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        rows = self.db.query(ProductAsset).all()
        self.assertEqual(len(rows), 3)
        self.assertEqual(next(row for row in rows if row.source_key == "source_white_bg").review_status, "approved")
        self.assertEqual(next(row for row in rows if row.source_key == "source_multi_angle").review_status, "pending")

    def test_draft_governance_changes_persist_only_with_review_authority(self):
        row = self.asset()
        self.permissions("product.edit", "media.upload", "media.review", "tag.edit")
        draft = self.draft({"assets": [{**self.asset_payload(row), "review_status": "approved",
                                       "tags": {"risk_tags": ["restricted"]}}]})
        response = self.publish(draft)
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.query(ProductAsset).one().review_status, "approved")
        self.assertEqual(json.loads(self.db.query(ProductAsset).one().tags), {"risk_tags": ["restricted"]})

    def test_new_draft_requires_create_and_media_permissions(self):
        payload = self.full_payload(sku="NEW", barcode="NEW")
        draft = self.draft(payload, sku="NEW")
        self.permissions("product.edit")
        self.assertEqual(self.publish(draft).status_code, 403)
        self.permissions("product.create")
        response = self.publish(draft)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(self.db.query(Product).filter_by(sku="NEW").first())

    def test_new_draft_cannot_inject_approved_assets(self):
        draft = self.draft(self.full_payload(sku="NEW", barcode="NEW", assets=[{
            "category_code": "01", "category_name": "Standard", "url": "https://test.invalid/new.jpg",
            "review_status": "approved",
        }]), sku="NEW")
        self.permissions("product.create", "media.upload")
        response = self.publish(draft)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)
        self.assertIsNone(self.db.query(Product).filter_by(sku="NEW").first())
        self.assertIsNotNone(self.db.get(ProductDraft, draft.id))

    def test_draft_owner_is_not_used_as_acting_user(self):
        draft = self.draft({"product_name_cn": "Other owner's draft"}, owner="other-user")
        self.permissions("product.create", "product.edit", "media.upload", "media.review")
        response = self.publish(draft)
        self.assertEqual(response.status_code, 404, response.text)
        with self.assertRaises(TypeError):
            draft_service.publish_draft(self.db, draft.id)

    def test_management_actor_can_publish_another_owners_draft(self):
        from app.core.permission_constants import MANAGEMENT_GROUP_NAME
        self.db.get(Group, "writers").group_name = MANAGEMENT_GROUP_NAME
        self.db.query(UserGroup).filter_by(user_id="writer").one().group_role = "admin"
        self.db.commit()
        draft = self.draft({"product_name_cn": "Published by management"}, owner="other-user")
        response = self.publish(draft)
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, "product-a").product_name_cn, "Published by management")

    def test_draft_api_keeps_assets_for_publish_time_authorization(self):
        self.permissions("product.create", "product.edit", "media.upload")
        response = self.client.post("/api/products/drafts", json={
            "sku": "A", "assets": [{"category_code": "01", "category_name": "Standard",
                                       "url": "https://test.invalid/new.jpg", "review_status": "approved"}],
        })
        self.assertEqual(response.status_code, 200, response.text)
        draft_id = response.json()["id"]
        response = self.client.post(f"/api/products/drafts/{draft_id}/publish")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)
        self.assertEqual(self.db.query(ProductAsset).count(), 0)

    def test_draft_failed_asset_insert_rolls_back_other_product_changes(self):
        self.asset()
        draft = self.draft({"product_name_cn": "Must roll back", "media_data": {
            "source_white_bg": ["https://test.invalid/new.jpg"],
        }})

        def fail_insert(*args):
            raise RuntimeError("draft asset insertion failed")

        event.listen(ProductAsset, "before_insert", fail_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "draft asset insertion"):
                draft_service.publish_draft(self.db, draft.id, acting_user=self.user)
        finally:
            event.remove(ProductAsset, "before_insert", fail_insert)
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, "product-a").product_name_cn, "Alpha")
        self.assertIsNotNone(self.db.get(ProductAsset, "asset-a"))
        self.assertIsNotNone(self.db.get(ProductDraft, draft.id))

    def test_new_draft_failed_asset_insert_does_not_create_product(self):
        draft = self.draft(self.full_payload(sku="NEW", barcode="NEW", media_data={
            "source_white_bg": ["https://test.invalid/new.jpg"],
        }), sku="NEW")
        self.permissions("product.create", "media.upload")

        def fail_insert(*args):
            raise RuntimeError("new asset insertion failed")

        event.listen(ProductAsset, "before_insert", fail_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "new asset insertion"):
                draft_service.publish_draft(self.db, draft.id, acting_user=self.user)
        finally:
            event.remove(ProductAsset, "before_insert", fail_insert)
        self.db.expire_all()
        self.assertIsNone(self.db.query(Product).filter_by(sku="NEW").first())
        self.assertIsNotNone(self.db.get(ProductDraft, draft.id))

    def snapshot(self, payload):
        row = ProductOperationSnapshot(operation_log_id="log", operator_id="writer", sku="A",
                                       action_type="replace", before_data=payload)
        self.db.add(row)
        self.db.commit()
        return row

    def test_restore_delete_permission_alone_cannot_overwrite_product(self):
        snapshot = self.snapshot(self.full_payload(product_name_cn="Restored"))
        self.permissions("product.delete")
        response = self.client.post(f"/api/products/operation-snapshots/{snapshot.id}/restore")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("product.edit", response.text)

    def test_restore_cannot_bypass_review_and_leaves_snapshot_reusable(self):
        row = self.asset()
        item = self.asset_payload(row)
        item.pop("id")
        snapshot = self.snapshot(self.full_payload(assets=[{**item, "review_status": "approved"}]))
        self.permissions("product.delete", "product.edit", "media.upload")
        response = self.client.post(f"/api/products/operation-snapshots/{snapshot.id}/restore")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("media.review", response.text)
        self.db.expire_all()
        self.assertIsNone(self.db.get(ProductOperationSnapshot, snapshot.id).restored_at)
        self.assertEqual(self.db.get(ProductAsset, "asset-a").review_status, "pending")
        self.permissions("product.delete", "product.edit", "media.upload", "media.review")
        response = self.client.post(f"/api/products/operation-snapshots/{snapshot.id}/restore")
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertIsNotNone(self.db.get(ProductOperationSnapshot, snapshot.id).restored_at)
        self.assertEqual(self.db.query(ProductAsset).one().review_status, "approved")

    def test_candidates_permissions_and_minimal_contract(self):
        for purpose, keys in (("qa", ("product.qa.manage",)), ("qa", ("product.edit",)),
                              ("media", ("media.read",)), ("full", ("product.full.view",)),
                              ("file", ("knowledge.files.manage",))):
            self.permissions(*keys)
            response = self.client.get(f"/api/products/candidates?purpose={purpose}&q=Alpha&limit=100")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"items": [{
                "sku": "A", "product_name_cn": "Alpha", "product_name_en": None, "brand": "Brand",
            }]})
        self.permissions("product.read")
        for purpose in ("qa", "media", "full", "file"):
            self.assertEqual(self.client.get(f"/api/products/candidates?purpose={purpose}").status_code, 403)
        self.assertEqual(self.client.get("/api/products/candidates?purpose=invalid").status_code, 422)

    def test_candidates_purpose_does_not_grant_other_purposes_and_limits_rows(self):
        self.permissions("media.read")
        self.assertEqual(self.client.get("/api/products/candidates?purpose=full").status_code, 403)
        self.assertEqual(self.client.get("/api/products/candidates?purpose=qa").status_code, 403)
        response = self.client.get("/api/products/candidates?purpose=media&limit=1")
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(self.client.get("/api/products/candidates?purpose=media&limit=101").status_code, 422)
        response = self.client.get("/api/products/candidates", params={"purpose": "media", "q": "%"})
        self.assertEqual(response.json(), {"items": []})

    def test_full_view_requires_full_permission(self):
        self.permissions("product.read")
        self.assertEqual(self.client.get("/api/products/A/full-view").status_code, 403)
        self.permissions("product.full.view")
        response = self.client.get("/api/products/A/full-view")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sku"], "A")

    def test_product_single_get_allows_edit_but_list_still_requires_read(self):
        self.permissions("product.edit")
        for path in ("/api/products/A", "/api/products/by-sku/A"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["sku"], "A")
        for path in ("/api/products", "/api/products/search?q=A", "/api/products/A/full-view"):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.permissions("product.create")
        self.assertEqual(self.client.get("/api/products/A").status_code, 403)
        self.permissions("product.read")
        self.assertEqual(self.client.get("/api/products/A").status_code, 403)

    def test_edit_only_can_load_create_read_update_and_publish_existing_product_draft(self):
        self.media(review_status="approved")
        self.asset(review_status="approved")
        self.permissions("product.edit")
        response = self.client.get("/api/products/A")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/products/drafts", json={
            "sku": "A", "draft_data": {"product_name_cn": "Edit-only draft"},
        })
        self.assertEqual(response.status_code, 200, response.text)
        draft_id = response.json()["id"]
        response = self.client.get(f"/api/products/drafts/{draft_id}")
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.put(f"/api/products/drafts/{draft_id}", json={"product_name_cn": "Edited"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/products/drafts/{draft_id}/publish")
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, "product-a").product_name_cn, "Edited")
        self.assertEqual(self.db.get(ProductMedia, "legacy-a").review_status, "approved")
        self.assertEqual(self.db.get(ProductAsset, "asset-a").review_status, "approved")

    def test_draft_authoring_checks_target_permission_and_owner(self):
        other = self.draft({"product_name_cn": "Other draft"}, owner="other")
        self.permissions("product.edit")
        self.assertEqual(self.client.post("/api/products/drafts", json={"sku": "NEW"}).status_code, 403)
        self.assertEqual(self.client.get(f"/api/products/drafts/{other.id}").status_code, 404)
        self.assertEqual(self.client.put(f"/api/products/drafts/{other.id}", json={"sku": "A"}).status_code, 404)
        response = self.client.get("/api/products/drafts")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])
        self.permissions("product.create")
        response = self.client.post("/api/products/drafts", json={"sku": "A"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_create_only_can_read_and_update_own_new_product_draft(self):
        self.permissions("product.create")
        response = self.client.post("/api/products/drafts", json={"sku": "NEW"})
        self.assertEqual(response.status_code, 200, response.text)
        draft_id = response.json()["id"]
        self.assertEqual(self.client.get(f"/api/products/drafts/{draft_id}").status_code, 200)
        response = self.client.put(f"/api/products/drafts/{draft_id}", json={"product_name_cn": "New name"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.put(f"/api/products/drafts/{draft_id}", json={"sku": "A"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_sync_status_and_audit_guards(self):
        self.permissions("ai.call", "product.read")
        for method, path in (("post", "/sync-to-vector"), ("post", "/sync-pending-to-vector"),
                             ("post", "/A/sync-to-vector"), ("get", "/vector-status"),
                             ("get", "/audit-overview")):
            response = self.client.request(method, "/api/products" + path)
            self.assertEqual(response.status_code, 403, response.text)
        self.permissions("knowledge.manage")
        self.assertEqual(self.client.get("/api/products/vector-status").status_code, 200)
        self.permissions("knowledge.sync")
        self.assertEqual(self.client.post("/api/products/A/sync-to-vector").status_code, 200)


if __name__ == "__main__":
    unittest.main()
