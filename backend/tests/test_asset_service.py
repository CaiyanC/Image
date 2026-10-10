import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.product import Product
from app.services import asset_service


class AssetServiceTest(unittest.TestCase):
    def test_one_asset_can_link_multiple_existing_products_without_duplication(self):
        self.db.add(Product(id="linked-product", sku="ASSET-2", barcode="linked-barcode", product_name_cn="共享测试产品", product_name_en="Shared product", brand="alocs"))
        self.db.commit()
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图", "url": "/uploads/shared.jpg",
            "related_skus": ["ASSET-1", "ASSET-2", "ASSET-2"],
        })
        self.assertEqual(asset.related_skus, ["ASSET-1", "ASSET-2"])
        self.assertEqual([a.id for a in asset_service.list_assets(self.db, "ASSET-2")], [asset.id])
        self.assertEqual(asset_service.get_asset(self.db, "ASSET-2", asset.id, allow_related=True).id, asset.id)
        with self.assertRaises(HTTPException):
            asset_service.delete_asset(self.db, "ASSET-2", asset.id)
        asset_service.update_asset(self.db, "ASSET-1", asset.id, {"related_skus": []})
        self.assertEqual(asset_service.list_assets(self.db, "ASSET-2"), [])

    def test_pdf_manual_is_document_and_new_video_content_type_is_valid(self):
        manual = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "03", "category_name": "使用说明图", "sub_category": "中文说明",
            "material_type": "manualZh", "asset_type": "document", "url": "/uploads/manual.pdf",
        })
        self.assertEqual(manual.language_tag, "CN")
        video = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "06", "category_name": "视频素材", "sub_category": "测试视频",
            "material_type": "testingVideo", "asset_type": "video", "url": "/uploads/test.mp4",
            "video_duration_seconds": 12.5,
        })
        self.assertEqual(asset_service.model_to_dict(video)["video_duration_seconds"], 12.5)

    def test_video_category_edits_use_measured_duration(self):
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "06", "category_name": "视频素材", "asset_type": "video",
            "sub_category": "白底视频", "url": "/uploads/test.mp4",
            "tags": {"video_duration_seconds": ["12.5"], "video_duration_status": ["measured"]},
        })
        with self.assertRaises(HTTPException) as raised:
            asset_service.update_asset(self.db, "ASSET-1", asset.id, {"sub_category": "场景长视频（>30秒）"})
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(asset.sub_category, "白底视频")
        updated = asset_service.update_asset(self.db, "ASSET-1", asset.id, {"sub_category": "场景短视频（≤30秒）"})
        self.assertEqual(updated.sub_category, "场景短视频（≤30秒）")
        with self.assertRaises(HTTPException):
            asset_service.update_asset(self.db, "ASSET-1", asset.id, {"asset_type": "image"})
        with self.assertRaises(HTTPException):
            asset_service.update_asset(self.db, "ASSET-1", asset.id, {"material_type": "sceneLongVideo"})

    def test_ecommerce_edit_rejects_cross_market_placement(self):
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "05", "category_name": "电商与品牌图",
            "sub_category": "跨境电商", "material_type": "aPlus", "url": "/uploads/test.jpg",
        })
        with self.assertRaises(HTTPException):
            asset_service.update_asset(self.db, "ASSET-1", asset.id, {"sub_category": "国内电商"})
        self.assertEqual(asset.sub_category, "跨境电商")
        updated = asset_service.update_asset(self.db, "ASSET-1", asset.id, {"sub_category": "国内电商", "material_type": "detailPage"})
        self.assertEqual(updated.material_type, "detailPage")

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        from app.models.product_asset import ProductAsset, ProductAssetLink

        Base.metadata.create_all(engine, tables=[Product.__table__, ProductAsset.__table__, ProductAssetLink.__table__])
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

    def test_upload_slot_tags_are_taxonomy_safe(self):
        scene = asset_service.default_upload_tags("04", "森林")
        self.assertEqual(scene["expression_tags"], ["场景图"])
        self.assertEqual(scene["scene_tags"], ["森林"])
        asset_service.validate_asset_tags(scene)
        car_scene = asset_service.default_upload_tags("04", "车露营")
        self.assertEqual(car_scene["scene_tags"], ["车露"])
        asset_service.validate_asset_tags(car_scene)
        for slot, language in (("中文说明", "中文"), ("英文说明", "英文")):
            tags = asset_service.default_upload_tags("03", slot)
            self.assertEqual(tags["language_tags"], [language])
            asset_service.validate_asset_tags(tags)

    def test_classification_hierarchy_rejects_new_invalid_combinations(self):
        valid = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "05", "category_name": "电商与品牌图",
            "sub_category": "国内电商", "material_type": "mainImage",
            "url": "/uploads/assets/ASSET-1/domestic-main.jpg",
        })
        self.assertEqual(valid.material_type, "mainImage")

        defaulted = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "sub_category": "白底图",
            "url": "/uploads/assets/ASSET-1/defaulted.jpg",
        })
        self.assertEqual(defaulted.material_type, "whiteBackground")

        invalid_payloads = (
            {"category_code": "01", "category_name": "错误名称"},
            {"category_code": "01", "category_name": "产品标准图", "sub_category": "未知分类"},
            {"category_code": "05", "category_name": "电商与品牌图", "sub_category": "国内电商", "material_type": "aPlus"},
            {"category_code": "06", "category_name": "视频素材", "asset_type": "image"},
        )
        for index, payload in enumerate(invalid_payloads):
            with self.subTest(payload=payload):
                with self.assertRaises(HTTPException) as raised:
                    asset_service.create_asset(self.db, "ASSET-1", {
                        **payload,
                        "url": f"/uploads/assets/ASSET-1/invalid-{index}.jpg",
                    })
                self.assertEqual(raised.exception.status_code, 422)

    def test_nonclassification_edit_preserves_legacy_classification(self):
        from app.models.product_asset import ProductAsset

        legacy = ProductAsset(
            id="legacy-classification",
            sku="ASSET-1",
            category_code="05",
            category_name="渠道销售图",
            sub_category="社媒宣发",
            material_type="socialMedia",
            asset_type="image",
            url="/uploads/assets/ASSET-1/legacy.jpg",
        )
        self.db.add(legacy)
        self.db.commit()

        updated = asset_service.update_asset(
            self.db, "ASSET-1", legacy.id, {"maintainer": "历史素材维护人"},
        )
        self.assertEqual(updated.category_name, "渠道销售图")
        self.assertEqual(updated.sub_category, "社媒宣发")
        self.assertEqual(updated.maintainer, "历史素材维护人")

    def test_independent_object_and_composition_roundtrip_and_search(self):
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "sub_category": "白底图", "material_type": "whiteBackground",
            "url": "/uploads/assets/ASSET-1/independent.jpg",
            "tags": {"subject_tags": ["配件", "收纳袋"], "composition_tags": ["纯产品"]},
        })
        self.assertEqual(asset_service.model_to_dict(asset)["tags"]["subject_tags"], ["配件", "收纳袋"])
        results = asset_service.search_assets(self.db, subject_tags=["配件"], composition_tags=["纯产品"])
        self.assertEqual([item.id for item in results], [asset.id])
        self.assertEqual(asset_service.search_assets(self.db, subject_tags=["主体"]), [])
        updated = asset_service.update_asset_tags(self.db, "ASSET-1", asset.id, {"subject_tags": ["主体"]})
        self.assertEqual(asset_service.model_to_dict(updated)["tags"]["composition_tags"], ["纯产品"])
        cleared = asset_service.update_asset_tags(self.db, "ASSET-1", asset.id, {"subject_tags": []})
        self.assertNotIn("subject_tags", asset_service.model_to_dict(cleared)["tags"])
        self.assertEqual(asset_service.model_to_dict(cleared)["tags"]["composition_tags"], ["纯产品"])

    def test_legacy_classification_fields_participate_in_tag_search(self):
        legacy_multi_angle = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "sub_category": "多角度图", "material_type": "front",
            "url": "/uploads/assets/ASSET-1/legacy-front.jpg",
        })
        legacy_accessory = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "sub_category": "配件图", "material_type": "accessory",
            "url": "/uploads/assets/ASSET-1/legacy-accessory.jpg",
        })

        self.assertEqual(
            [item.id for item in asset_service.search_assets(self.db, material_type_tags=["多角度图"], view_tags=["正视"])],
            [legacy_multi_angle.id],
        )
        self.assertEqual(
            [item.id for item in asset_service.search_assets(self.db, subject_tags=["配件"])],
            [legacy_accessory.id],
        )

        legacy_scene = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "04", "category_name": "场景内容图",
            "sub_category": "森林", "material_type": "forest",
            "url": "/uploads/assets/ASSET-1/legacy-forest.jpg",
        })
        derived_scene_tags = asset_service.effective_asset_tags(legacy_scene)
        self.assertEqual(derived_scene_tags["scene_tags"], ["森林"])
        self.assertNotIn("material_type_tags", derived_scene_tags)

    def test_category_associations_are_searchable_without_copying_the_asset(self):
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "sub_category": "白底图", "material_type": "whiteBackground",
            "url": "/uploads/assets/ASSET-1/white-domestic.jpg",
            "tags": {"category_tags": ["01/白底图", "05/国内电商"]},
        })

        effective = asset_service.effective_asset_tags(asset)
        self.assertEqual(effective["category_tags"], ["01/白底图", "05/国内电商"])
        self.assertEqual(
            [item.id for item in asset_service.search_assets(self.db, category_tags=["05/国内电商"])],
            [asset.id],
        )
        self.assertEqual(
            [item.id for item in asset_service.search_assets(self.db, category_tags=["01/白底图"])],
            [asset.id],
        )
        with self.assertRaises(HTTPException):
            asset_service.validate_asset_tags({"category_tags": ["05/不存在"]})

    def test_independent_fields_reject_unknown_or_conflicting_values(self):
        for tags in ({"subject_tags": ["未知对象"]}, {"composition_tags": ["带人物", "纯产品"]}, {"view_tags": ["正视", "侧视"]}, {"view_tags": ["未知视角"]}):
            with self.assertRaises(HTTPException) as raised:
                asset_service.validate_asset_tags(tags)
            self.assertEqual(raised.exception.status_code, 422)
        # Search can match either composition without describing one conflicting asset.
        asset_service.validate_asset_tags({"composition_tags": ["带人物", "纯产品"]}, enforce_expression_requirements=False)

    def test_quality_checks_validate_each_criterion_without_implicit_publication(self):
        for criterion in ("完整性", "瑕疵检查", "质感", "复用性"):
            asset_service.validate_asset_tags({"quality_check_tags": [f"{criterion}通过"]})
            with self.assertRaises(HTTPException):
                asset_service.validate_asset_tags({"quality_check_tags": [f"{criterion}通过", f"{criterion}需修改"]})
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "url": "/uploads/assets/ASSET-1/checked.jpg",
            "tags": {"quality_check_tags": ["完整性通过", "瑕疵检查通过", "质感通过", "复用性通过"]},
        })
        self.assertEqual(asset.review_status, "pending")
        self.assertFalse(asset.is_public)
        self.assertFalse(asset.ai_reference_usable)

    def test_legacy_scene_expression_and_new_composition_cannot_conflict(self):
        for expression, composition in (("人物场景图", "纯产品"), ("纯产品场景图", "带人物")):
            with self.assertRaises(HTTPException) as raised:
                asset_service.validate_asset_tags({"expression_tags": [expression], "composition_tags": [composition], "scene_tags": ["森林"]})
            self.assertEqual(raised.exception.status_code, 422)
        with self.assertRaises(HTTPException):
            asset_service.validate_asset_tags({"expression_tags": ["人物场景图", "纯产品场景图"], "scene_tags": ["森林"]})
        asset_service.validate_asset_tags({"expression_tags": ["人物场景图"], "composition_tags": ["带人物"], "scene_tags": ["森林"]})
        # Multiple search alternatives are not one asset's annotation.
        asset_service.validate_asset_tags({"expression_tags": ["人物场景图", "纯产品场景图"]}, enforce_expression_requirements=False)

    def test_manual_language_is_consistent_across_create_update_and_tag_patch(self):
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "03", "category_name": "使用说明图",
            "sub_category": "英文说明", "url": "/uploads/assets/ASSET-1/manual.jpg",
        })
        self.assertEqual(asset.language_tag, "EN")
        self.assertEqual(asset_service.model_to_dict(asset)["tags"]["language_tags"], ["英文"])
        with self.assertRaises(HTTPException):
            asset_service.update_asset(self.db, "ASSET-1", asset.id, {"language_tag": "CN"})
        with self.assertRaises(HTTPException):
            asset_service.update_asset_tags(self.db, "ASSET-1", asset.id, {"language_tags": ["中文"]})
        updated = asset_service.update_asset(self.db, "ASSET-1", asset.id, {"sub_category": "中文说明"})
        self.assertEqual(updated.language_tag, "CN")
        self.assertEqual(asset_service.model_to_dict(updated)["tags"]["language_tags"], ["中文"])

    def test_overview_reports_material_storage_bytes(self):
        self.assertEqual(asset_service.list_product_asset_overview(self.db)["items"][0]["total_size_bytes"], 0)
        for index, size in enumerate((1024, 2048)):
            asset_service.create_asset(self.db, "ASSET-1", {
                "category_code": "01",
                "category_name": "产品标准图",
                "sub_category": "白底图",
                "material_type": "whiteBackground",
                "url": f"/uploads/assets/ASSET-1/storage-{index}.jpg",
                "file_size_bytes": size,
            })
        self.assertEqual(asset_service.list_product_asset_overview(self.db)["items"][0]["total_size_bytes"], 3072)

    def test_overview_prefers_standard_front_view_without_modifying_assets(self):
        created = []
        for material in ("detail", "front", "side"):
            created.append(asset_service.create_asset(self.db, "ASSET-1", {
                "category_code": "01", "category_name": "产品标准图",
                "sub_category": "多角度图", "material_type": material,
                "url": f"/uploads/assets/ASSET-1/{material}.jpg",
            }))
        overview = asset_service.list_product_asset_overview(self.db)["items"][0]
        self.assertEqual(overview["cover_asset_id"], created[1].id)
        self.assertEqual(overview["image_count"], 3)
        self.assertEqual([asset.material_type for asset in created], ["detail", "front", "side"])

    def test_cover_excludes_blocked_or_nonproduct_images_and_returns_none(self):
        asset = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "material_type": "front", "url": "/uploads/assets/ASSET-1/front.jpg",
        })
        for field, blocked in (("category_code", "08"), ("status_tag", "禁用"),
                               ("quality_status", "invalid"), ("review_status", "rejected"),
                               ("is_latest_version", False), ("is_real_product", False),
                               ("is_ai_generated", True), ("is_competitor", True)):
            original = getattr(asset, field)
            setattr(asset, field, blocked)
            self.assertIsNone(asset_service.select_product_cover([asset]), field)
            setattr(asset, field, original)
        self.assertIsNone(asset_service.select_product_cover([]))
        self.assertEqual(asset_service.select_product_cover([asset]).id, asset.id)

    def test_independent_view_overrides_legacy_angle_for_cover_and_search(self):
        side = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "material_type": "front", "angle_scene": "正视",
            "url": "/uploads/assets/ASSET-1/side-view.jpg",
            "tags": {"view_tags": ["侧视"]},
        })
        front = asset_service.create_asset(self.db, "ASSET-1", {
            "category_code": "01", "category_name": "产品标准图",
            "material_type": "whiteBackground",
            "url": "/uploads/assets/ASSET-1/front-view.jpg",
            "tags": {"view_tags": ["正视"]},
        })
        self.assertEqual(asset_service.select_product_cover([side, front]).id, front.id)
        self.assertEqual([a.id for a in asset_service.search_assets(self.db, view_tags=["正视"])], [front.id])

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
        self.assertEqual(updated.category_name, "历史与禁用归档")
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
                "sub_category": "AI 产品图",
                "material_type": "aiProduct",
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

    def test_incomplete_asset_lifecycle_cannot_be_marked_usable(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/internal.png",
                "review_status": "approved",
                "authorization_status": "internal_test",
                "is_public": True,
                "ai_customer_usable": True,
                "ai_marketing_usable": True,
                "ai_reference_usable": True,
            },
        )

        self.assertFalse(asset.is_public)
        self.assertFalse(asset.ai_customer_usable)
        self.assertFalse(asset.ai_marketing_usable)
        self.assertFalse(asset.ai_reference_usable)

        usable = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/approved.png",
                "review_status": "approved",
                "authorization_status": "approved",
                "is_public": True,
                "ai_customer_usable": True,
                "ai_marketing_usable": True,
                "ai_reference_usable": True,
            },
        )
        self.assertTrue(usable.is_public)
        self.assertTrue(usable.ai_customer_usable)
        self.assertTrue(usable.ai_marketing_usable)
        self.assertTrue(usable.ai_reference_usable)

    def test_unknown_lifecycle_values_are_rejected_and_cannot_grant_ai_use(self):
        for field, value in (("review_status", "looks_good"), ("authorization_status", "custom_grant")):
            with self.subTest(field=field):
                with self.assertRaises(HTTPException) as raised:
                    asset_service.create_asset(
                        self.db,
                        "ASSET-1",
                        {
                            "category_code": "01",
                            "category_name": "产品标准图",
                            "url": f"/uploads/assets/ASSET-1/{field}.png",
                            field: value,
                        },
                    )
                self.assertEqual(raised.exception.status_code, 422)

        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/legacy-custom-authorization.png",
                "review_status": "approved",
                "authorization_status": "approved",
                "is_public": True,
                "ai_reference_usable": True,
            },
        )
        asset.authorization_status = "legacy_custom_grant"
        self.assertFalse(asset_service.is_ai_reference_ready(asset))

    def test_search_uses_normalized_review_and_authorization_values(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/search-normalized.png",
                "review_status": "approved",
                "authorization_status": "authorized",
                "is_public": True,
                "ai_customer_usable": True,
                "ai_marketing_usable": True,
                "ai_reference_usable": True,
            },
        )

        results = asset_service.search_assets(
            self.db,
            review_status=" Approved ",
            authorization_status=" AUTHORIZED ",
        )
        self.assertEqual([item.id for item in results], [asset.id])
        self.assertEqual(
            [item.id for item in asset_service.search_assets(
                self.db,
                is_public=True,
                ai_customer_usable=True,
                ai_marketing_usable=True,
                ai_reference_usable=True,
            )],
            [asset.id],
        )
        self.assertEqual(asset_service.search_assets(self.db, is_public=False), [])

    def test_update_cannot_reenable_internal_test_asset(self):
        asset = asset_service.create_asset(
            self.db,
            "ASSET-1",
            {
                "category_code": "01",
                "category_name": "产品标准图",
                "url": "/uploads/assets/ASSET-1/reviewed.png",
                "review_status": "approved",
                "authorization_status": "approved",
                "is_public": True,
                "ai_customer_usable": True,
            },
        )

        updated = asset_service.update_asset(
            self.db,
            "ASSET-1",
            asset.id,
            {
                "authorization_status": "internal_test",
                "is_public": True,
                "ai_customer_usable": True,
            },
        )
        self.assertFalse(updated.is_public)
        self.assertFalse(updated.ai_customer_usable)

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
