import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.product import Product
from app.services import asset_service


class AssetServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        from app.models.product_asset import ProductAsset

        Base.metadata.create_all(engine, tables=[Product.__table__, ProductAsset.__table__])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.db.add(Product(
            id="product-asset-test",
            sku="ASSET-1",
            barcode="asset-barcode",
            product_name_cn="asset product",
            product_name_en="Asset Product",
            brand="alocs",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_create_asset_applies_defaults_and_seq_grouping(self):
        first = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/ASSET-1/one.jpg",
            },
        )
        second = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/ASSET-1/two.jpg",
            },
        )
        other_group = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "多角度图",
                "material_type": "front",
                "url": "/uploads/assets/ASSET-1/front.jpg",
            },
        )

        self.assertEqual(first.seq, 1)
        self.assertEqual(second.seq, 2)
        self.assertEqual(other_group.seq, 1)
        self.assertEqual(first.brand, "alocs")
        self.assertEqual(first.channel, "General")
        self.assertEqual(first.language_tag, "CN")
        self.assertEqual(first.version_tag, "V1")
        self.assertEqual(first.status_tag, "待审核")
        self.assertRegex(first.date_tag, r"^\d{8}$")
        self.assertEqual(first.tags, "{}")

    def test_patch_tags_only_updates_tags(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/ASSET-1/one.jpg",
                "status_tag": "待审核",
            },
        )

        updated = asset_service.update_asset_tags(
            self.db,
            "ASSET-1",
            asset.id,
            {"product_tags": ["酒精炉"], "risk_tags": ["仅内部参考"]},
        )

        self.assertEqual(updated.category_code, "01")
        self.assertEqual(updated.sub_category, "白底图")
        self.assertEqual(updated.status_tag, "待审核")
        self.assertEqual(
            asset_service.model_to_dict(updated)["tags"],
            {"product_tags": ["酒精炉"], "risk_tags": ["仅内部参考"]},
        )

    def test_update_status_moves_banned_asset_to_archive_category(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/ASSET-1/one.jpg",
            },
        )

        updated = asset_service.update_asset(
            self.db,
            "ASSET-1",
            asset.id,
            {"status_tag": "禁用"},
        )

        self.assertEqual(updated.category_code, "08")
        self.assertEqual(updated.category_name, "参考归档禁用图")
        self.assertEqual(updated.sub_category, "禁用素材")
        self.assertEqual(updated.material_type, "banned")

    def test_missing_sku_raises_404(self):
        with self.assertRaises(HTTPException) as ctx:
            asset_service.create_asset(
                self.db,
                "NO-SUCH-SKU",
                {
                    "category_code": "01",
                    "category_name": "产品标准图",
                    "url": "/uploads/assets/nope.jpg",
                },
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_product_assets_sku_has_database_foreign_key(self):
        inspector = inspect(self.db.bind)
        foreign_keys = inspector.get_foreign_keys("product_assets")
        self.assertTrue(
            any(
                fk.get("constrained_columns") == ["sku"]
                and fk.get("referred_table") == "products"
                and fk.get("referred_columns") == ["sku"]
                for fk in foreign_keys
            ),
            foreign_keys,
        )

    def test_create_asset_persists_review_and_authorization_defaults(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "07",
                "category_name": "AI 生成图",
                "sub_category": "AI 生成图",
                "material_type": "aiGenerated",
                "url": "/uploads/assets/ASSET-1/ai.png",
                "is_real_product": True,
                "is_ai_generated": False,
            },
        )
        self.assertFalse(asset.is_real_product)
        self.assertTrue(asset.is_ai_generated)
        self.assertEqual(asset.review_status, "pending")
        self.assertEqual(asset.authorization_status, "unknown")
        self.assertFalse(asset.is_public)
        self.assertFalse(asset.ai_customer_usable)

    def test_visual_expression_tags_require_their_supporting_tag(self):
        with self.assertRaises(HTTPException) as ctx:
            asset_service.validate_asset_tags({"expression_tags": ["卖点图"]})
        self.assertEqual(ctx.exception.status_code, 422)

        validated = asset_service.validate_asset_tags({
            "expression_tags": ["场景图"],
            "scene_tags": ["家庭露营"],
        })
        self.assertEqual(validated["scene_tags"], ["家庭露营"])

    def test_controlled_tags_reject_new_values_outside_the_dictionary(self):
        with self.assertRaises(HTTPException) as ctx:
            asset_service.validate_asset_tags({"scene_tags": ["studio"]})
        self.assertEqual(ctx.exception.status_code, 422)

    def test_quality_and_duplicate_metadata_are_persisted_and_serialized(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": "/uploads/assets/ASSET-1/one.jpg",
                "quality_status": "suspected_duplicate",
                "quality_reason": "开发环境重复测试",
                "duplicate_status": "suspected_duplicate",
                "duplicate_of_asset_id": "asset-source",
            },
        )

        payload = asset_service.model_to_dict(asset)
        self.assertEqual(payload["quality_status"], "suspected_duplicate")
        self.assertEqual(payload["quality_reason"], "开发环境重复测试")
        self.assertEqual(payload["duplicate_status"], "suspected_duplicate")
        self.assertEqual(payload["duplicate_of_asset_id"], "asset-source")

        updated = asset_service.update_asset(
            self.db,
            "ASSET-1",
            asset.id,
            {"quality_status": "invalid", "quality_reason": "开发环境无效素材测试"},
        )
        self.assertEqual(updated.quality_status, "invalid")
        self.assertEqual(updated.quality_reason, "开发环境无效素材测试")

    def test_batch_auto_flags_exact_checksum_duplicate_without_rejecting_it(self):
        original = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/original.png",
                "checksum_sha256": "a" * 64,
            },
        )

        duplicate = asset_service.create_assets_batch(
            self.db,
            "ASSET-1",
            [{
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/duplicate.png",
                "checksum_sha256": "A" * 64,
            }],
        )[0]

        self.assertEqual(duplicate.quality_status, "suspected_duplicate")
        self.assertEqual(duplicate.duplicate_status, "suspected_duplicate")
        self.assertEqual(duplicate.duplicate_of_asset_id, original.id)
        self.assertIn(original.id, duplicate.quality_reason)


if __name__ == "__main__":
    unittest.main()
