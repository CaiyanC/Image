import unittest
from copy import deepcopy

from sqlalchemy import create_engine
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    OperationLog,
    Product,
    ProductBusiness,
    ProductAsset,
    Certification,
    Keyword,
    ListingChannel,
    KnowledgeChunk,
    KnowledgeDocument,
    ProductCertification,
    ProductContent,
    ProductKeyword,
    ProductListingChannel,
    ProductMedia,
    ProductOperationSnapshot,
    ProductPrompts,
    ProductQa,
    ProductQaNegative,
    ProductSalesRegion,
    ProductSpecs,
    SalesRegion,
    User,
    UserGroup,
)
from app.services import operation_log_service, product_recovery_service, product_service


class ProductRecoveryServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            UserGroup.__table__,
            OperationLog.__table__,
            Product.__table__,
            ProductAsset.__table__,
            ProductSpecs.__table__,
            ProductBusiness.__table__,
            ProductContent.__table__,
            ProductQa.__table__,
            ProductQaNegative.__table__,
            ProductPrompts.__table__,
            ProductMedia.__table__,
            ProductListingChannel.__table__,
            ProductSalesRegion.__table__,
            ProductCertification.__table__,
            ProductKeyword.__table__,
            ListingChannel.__table__,
            SalesRegion.__table__,
            Certification.__table__,
            Keyword.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
            ProductOperationSnapshot.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.db.add(User(id="user-1", username="alice", email="alice@example.com", password_hash="hash"))
        self.db.commit()
        self.product_payload = {
            "sku": "SKU-1",
            "barcode": "BAR-1",
            "product_name_cn": "旧产品",
            "brand": "Brand",
            "category": "Cat",
            "specs": {
                "capacity": "1L",
                "power": "100W",
                "technical_advantages": ["耐用"],
                "usage_instruction": "正常使用",
            },
            "content": {
                "title_cn": "旧标题",
                "long_description_cn": "旧描述",
            },
        }

    def tearDown(self):
        self.db.close()

    def test_restore_snapshot_rolls_product_back_to_before_data(self):
        product_service.create_product(self.db, self.product_payload, creator_id="user-1")
        self.db.add(ProductAsset(
            id="asset-1",
            sku="SKU-1",
            category_code="01",
            category_name="产品标准图",
            sub_category="白底图",
            asset_type="image",
            url="/uploads/assets/sku-1-white.png",
            source_key=None,
            tags='{"scene_tags":["studio"]}',
        ))
        self.db.commit()
        before_data = product_service.get_product_detail(self.db, "SKU-1")
        product_service.update_product(self.db, "SKU-1", {"product_name_cn": "新产品"})
        after_data = product_service.get_product_detail(self.db, "SKU-1")
        log = operation_log_service.log_operation(
            self.db,
            operator_id="user-1",
            action_type="update",
            action_name="编辑产品",
            target_type="product",
            target_id=before_data["id"],
            target_name="SKU-1",
        )
        snapshot = product_recovery_service.create_product_snapshot(
            self.db,
            operation_log_id=log.id,
            operator_id="user-1",
            sku="SKU-1",
            action_type="update",
            before_data=before_data,
            after_data=after_data,
        )

        restored = product_recovery_service.restore_product_snapshot(
            self.db,
            snapshot.id,
            operator_id="user-1",
        )

        detail = product_service.get_product_detail(self.db, "SKU-1")
        self.assertEqual(detail["product_name_cn"], "旧产品")
        self.assertEqual(restored["sku"], "SKU-1")
        self.assertEqual(restored["restored_to"], "before")
        restored_asset = self.db.query(ProductAsset).filter(ProductAsset.sku == "SKU-1").one()
        self.assertEqual(restored_asset.url, "/uploads/assets/sku-1-white.png")
        self.assertEqual(restored_asset.sub_category, "白底图")

    def test_replace_product_rolls_back_when_replacement_insert_fails(self):
        product_service.create_product(self.db, self.product_payload, creator_id="user-1")
        invalid_payload = deepcopy(self.product_payload)
        invalid_payload["product_name_cn"] = "不应保存的新产品"
        invalid_payload["specs"]["gross_weight_g"] = {"invalid": "float"}

        with self.assertRaises(StatementError):
            product_service.replace_product(
                self.db,
                "SKU-1",
                invalid_payload,
                creator_id="user-1",
            )

        self.db.expire_all()
        product = product_service.get_product_by_sku(self.db, "SKU-1")
        self.assertIsNotNone(product)
        self.assertEqual(product.product_name_cn, "旧产品")

    def test_restore_failure_keeps_current_product_and_snapshot_reusable(self):
        product_service.create_product(self.db, self.product_payload, creator_id="user-1")
        current_data = product_service.get_product_detail(self.db, "SKU-1")
        invalid_target = deepcopy(current_data)
        invalid_target["product_name_cn"] = "无效快照产品"
        invalid_target["specs"]["gross_weight_g"] = {"invalid": "float"}
        log = operation_log_service.log_operation(
            self.db,
            operator_id="user-1",
            action_type="update",
            action_name="编辑产品",
            target_type="product",
            target_id=current_data["id"],
            target_name="SKU-1",
        )
        snapshot = product_recovery_service.create_product_snapshot(
            self.db,
            operation_log_id=log.id,
            operator_id="user-1",
            sku="SKU-1",
            action_type="update",
            before_data=invalid_target,
            after_data=current_data,
        )

        with self.assertRaises(StatementError):
            product_recovery_service.restore_product_snapshot(
                self.db,
                snapshot.id,
                operator_id="user-1",
            )

        self.db.expire_all()
        product = product_service.get_product_by_sku(self.db, "SKU-1")
        persisted_snapshot = self.db.get(ProductOperationSnapshot, snapshot.id)
        self.assertIsNotNone(product)
        self.assertEqual(product.product_name_cn, "旧产品")
        self.assertIsNone(persisted_snapshot.restored_at)


if __name__ == "__main__":
    unittest.main()
