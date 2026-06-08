import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.product import Product
from app.services import product_service
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

    def test_preserves_existing_unit(self):
        result = _normalize_size_info([
            {"unit": "cm", "label": "展开尺寸", "value": "36.5*28.6*6"},
        ])

        self.assertEqual(result[0]["unit"], "cm")
        self.assertEqual(result[0]["value"], "36.5*28.6*6")


class ProductServiceVectorSyncTest(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
