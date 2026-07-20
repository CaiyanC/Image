import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.product import Product
from app.models.product_associations import (
    Certification,
    Keyword,
    ListingChannel,
    ProductCertification,
    ProductKeyword,
    ProductListingChannel,
    ProductSalesRegion,
    SalesRegion,
)
from app.models.product_business import ProductBusiness
from app.models.product_content import ProductContent
from app.models.product_media import ProductMedia
from app.models.product_prompts import ProductPrompts
from app.models.product_qa import ProductQa, ProductQaNegative
from app.models.product_specs import ProductSpecs
from app.services import customer_cache_service
from app.services import draft_service, product_service
from app.services.product_service import _normalize_size_info


class ProductServiceSizeInfoTest(unittest.TestCase):
    def test_extracts_unit_from_single_unit_dimensions(self):
        result = _normalize_size_info([
            {"unit": "", "label": "展开尺寸(带手柄)", "value": "36.5*28.6*6cm"},
            {"unit": "", "label": "煎锅", "value": "φ28.6*6cm"},
            {"unit": "", "label": "展开尺寸", "value": "15.2×11.7cm"},
        ])

        self.assertEqual(result[0]["unit"], "cm")
        self.assertEqual(result[0]["value"], "36.5*28.6*6")
        self.assertEqual(result[1]["unit"], "cm")
        self.assertEqual(result[1]["value"], "φ28.6*6")
        self.assertEqual(result[2]["unit"], "cm")
        self.assertEqual(result[2]["value"], "15.2×11.7")

    def test_keeps_mixed_unit_dimensions_in_value(self):
        raw_value = "9.5x6.7mm（炉体）+12×13.4cm（炉架）"

        result = _normalize_size_info([
            {"unit": "", "label": "收纳尺寸", "value": raw_value},
        ])

        self.assertEqual(result[0]["unit"], "")
        self.assertEqual(result[0]["value"], raw_value)

    def test_preserves_inner_units_when_only_trailing_unit_is_extracted(self):
        result = _normalize_size_info([
            {"unit": "", "label": "[大锅]", "value": "(约)直径17XH10cm/(约)1.7L"},
            {"unit": "", "label": "登山杖展开尺寸", "value": "110cm-135cm"},
        ])

        self.assertEqual(result[0]["unit"], "")
        self.assertEqual(result[0]["value"], "(约)直径17XH10cm/(约)1.7L")
        self.assertEqual(result[1]["unit"], "cm")
        self.assertEqual(result[1]["value"], "110cm-135")

    def test_preserves_existing_unit(self):
        result = _normalize_size_info([
            {"unit": "cm", "label": "展开尺寸", "value": "36.5*28.6*6"},
        ])

        self.assertEqual(result[0]["unit"], "cm")
        self.assertEqual(result[0]["value"], "36.5*28.6*6")

    def test_preserves_decimal_dimension_when_extracting_attached_unit(self):
        result = _normalize_size_info([
            {"unit": "", "label": "", "value": "8.2x23cm"},
            {"unit": "", "label": "", "value": "2.2L锅18.5*11cm"},
            {"unit": "", "label": "", "value": "0.8L水壶13*7.5cm"},
        ])

        self.assertEqual(result[0]["unit"], "cm")
        self.assertEqual(result[0]["value"], "8.2x23")
        self.assertEqual(result[1]["unit"], "cm")
        self.assertEqual(result[1]["value"], "2.2L锅18.5*11")
        self.assertEqual(result[2]["unit"], "cm")
        self.assertEqual(result[2]["value"], "0.8L水壶13*7.5")


class ProductServiceVectorSyncTest(unittest.TestCase):
    def setUp(self):
        customer_cache_service.product_detail_cache.clear()
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Product.__table__])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.db.add(Product(
            id="product-pending",
            sku="PENDING-1",
            barcode="barcode-pending",
            product_name_cn="待同步产品",
            product_name_en="Pending Product",
            brand="alocs",
            person_in_charge="Max",
            sync_flag=False,
        ))
        self.db.add(Product(
            id="product-synced",
            sku="SYNCED-1",
            barcode="barcode-synced",
            product_name_cn="已同步产品",
            product_name_en="Synced Product",
            brand="alocs",
            person_in_charge="Max",
            sync_flag=True,
        ))
        self.db.add(Product(
            id="product-failed",
            sku="FAILED-1",
            barcode="barcode-failed",
            product_name_cn="同步失败产品",
            product_name_en="Failed Product",
            brand="alocs",
            person_in_charge="Max",
            sync_flag=False,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_sync_pending_products_retries_only_unsynced_products(self):
        calls = []
        original_sync = product_service.sync_product_to_vector_db

        def fake_sync(db, sku):
            calls.append(sku)
            if sku == "FAILED-1":
                return {"sku": sku, "error": "embedding unavailable"}
            current = product_service.get_product_by_sku(db, sku)
            current.sync_flag = True
            db.commit()
            return {"sku": sku, "documents": 1, "chunks": 2}

        product_service.sync_product_to_vector_db = fake_sync
        try:
            result = product_service.sync_pending_products_to_vector_db(self.db)
        finally:
            product_service.sync_product_to_vector_db = original_sync

        self.assertEqual(set(calls), {"PENDING-1", "FAILED-1"})
        self.assertNotIn("SYNCED-1", calls)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(product_service.get_product_by_sku(self.db, "PENDING-1").sync_flag)
        self.assertFalse(product_service.get_product_by_sku(self.db, "FAILED-1").sync_flag)


class ProductServiceSpecsUpdateTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                Product.__table__,
                ProductSpecs.__table__,
                ProductBusiness.__table__,
                ProductContent.__table__,
                ProductMedia.__table__,
                ProductPrompts.__table__,
                ProductQa.__table__,
                ProductQaNegative.__table__,
                ListingChannel.__table__,
                ProductListingChannel.__table__,
                SalesRegion.__table__,
                ProductSalesRegion.__table__,
                Certification.__table__,
                ProductCertification.__table__,
                Keyword.__table__,
                ProductKeyword.__table__,
            ],
        )
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        product_service.create_product(
            self.db,
            {
                "sku": "SPECS-JSON-1",
                "barcode": "barcode-specs-json",
                "product_name_cn": "规格 JSON 测试产品",
                "brand": "alocs",
                "specs_data": {
                    "size_info": [{"label": "展开尺寸", "value": "10*20cm"}],
                    "capacity": [{"label": "锅", "value": "1000ML"}],
                    "power": "N/A",
                    "technical_advantages": ["轻量"],
                    "usage_instruction": "测试说明",
                },
                "content_data": {
                    "title_cn": "规格 JSON 测试",
                    "long_description_cn": "用于验证规格更新 JSON 字段",
                },
            },
        )

    def tearDown(self):
        customer_cache_service.product_detail_cache.clear()
        self.db.close()

    def test_update_product_specs_serializes_json_fields(self):
        cached_before_update = product_service.get_product_detail(self.db, "SPECS-JSON-1")
        self.assertEqual(cached_before_update["specs"]["capacity"], [{"label": "锅", "value": "1000ML"}])

        result = product_service.update_product_specs(
            self.db,
            "SPECS-JSON-1",
            {
                "size_info": [{"label": "收纳尺寸", "value": "12×13cm"}],
                "capacity": [{"label": "锅", "value": "2000ML"}],
                "technical_advantages": ["耐腐蚀", "导热快"],
                "gross_weight_g": 777,
                "body_material": "titanium",
            },
        )

        self.assertEqual(result["specs"]["capacity"], [{"label": "锅", "value": "2000ML"}])
        self.assertEqual(result["specs"]["technical_advantages"], ["耐腐蚀", "导热快"])
        self.assertEqual(result["specs"]["gross_weight_g"], 777)
        self.assertEqual(result["specs"]["body_material"], "titanium")
        self.assertEqual(result["specs"]["size_info"][0]["unit"], "cm")

        detail_after_update = product_service.get_product_detail(self.db, "SPECS-JSON-1")
        self.assertEqual(detail_after_update["specs"]["capacity"], [{"label": "锅", "value": "2000ML"}])


class ProductImportSafetyTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                Product.__table__,
                ProductQa.__table__,
                ProductQaNegative.__table__,
                ProductPrompts.__table__,
            ],
        )
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.product = Product(
            id="safe-import-product",
            sku="SAFE-IMPORT-1",
            barcode="safe-import-barcode",
            product_name_cn="原产品名称",
            brand="alocs",
        )
        self.db.add(self.product)
        self.db.add(ProductQa(
            id="existing-qa",
            product_id=self.product.id,
            question="已有问题",
            answer="已有答案",
        ))
        self.db.add(ProductQaNegative(
            id="existing-negative",
            product_id=self.product.id,
            high_freq_negative_words="破损",
            response_tone="原有回复",
        ))
        self.db.add(ProductPrompts(
            id="existing-prompt",
            product_id=self.product.id,
            sku=self.product.sku,
            prompt_text="原有提示词",
        ))
        self.db.commit()

    def tearDown(self):
        customer_cache_service.product_detail_cache.clear()
        self.db.close()

    def test_qa_batch_import_defaults_to_append_and_skips_existing_question(self):
        result = product_service.import_qa_batch(
            self.db,
            [{
                "sku": self.product.sku,
                "qa_items": [
                    {"question": "已 有 问题", "answer": "新的重复答案"},
                    {"question": "新增问题", "answer": "新增答案"},
                ],
            }],
        )

        questions = [qa.question for qa in self.db.query(ProductQa).order_by(ProductQa.question).all()]
        self.assertEqual(questions, ["已有问题", "新增问题"])
        self.assertEqual(result["results"][0]["qa_skipped_duplicate"], 1)

    def test_qa_batch_import_replace_remains_explicitly_destructive(self):
        product_service.import_qa_batch(
            self.db,
            [{
                "sku": self.product.sku,
                "qa_items": [{"question": "替换后问题", "answer": "替换后答案"}],
            }],
            mode="replace",
        )

        questions = [qa.question for qa in self.db.query(ProductQa).all()]
        self.assertEqual(questions, ["替换后问题"])

    def test_publishing_l1_l4_draft_preserves_existing_relations(self):
        draft = SimpleNamespace(
            id="l1-l4-draft",
            sku=self.product.sku,
            created_by="tester",
            draft_data={
                "product_name_cn": "导入后名称",
                "barcode": self.product.barcode,
                "brand": self.product.brand,
            },
        )

        with (
            patch.object(draft_service, "get_draft_by_id", return_value=draft),
            patch.object(draft_service, "get_product_by_sku", return_value=self.product),
            patch.object(product_service, "_validate_product_data"),
            patch.object(product_service, "sync_product_m2m"),
            patch.object(draft_service, "get_product_detail", return_value={"sku": self.product.sku}),
            patch.object(self.db, "delete"),
        ):
            draft_service.publish_draft(self.db, draft.id, "tester")

        self.assertEqual(self.product.product_name_cn, "导入后名称")
        self.assertEqual(self.db.query(ProductQa).count(), 1)
        self.assertEqual(self.db.query(ProductQaNegative).count(), 1)
        self.assertEqual(self.db.query(ProductPrompts).count(), 1)


class ProductServicePaginationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Product.__table__])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        for index in range(125):
            self.db.add(Product(
                id=f"product-{index}",
                sku=f"SKU-{index:03d}",
                barcode=f"barcode-{index}",
                product_name_cn=f"产品 {index}",
                product_name_en=f"Product {index}",
                brand="alocs",
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_get_products_clamps_unbounded_pagination(self):
        items, total = product_service.get_products(self.db, skip=-50, limit=10000)

        self.assertEqual(total, 125)
        self.assertEqual(len(items), 100)


if __name__ == "__main__":
    unittest.main()
