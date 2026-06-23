import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    OperationLog,
    Product,
    ProductBusiness,
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


if __name__ == "__main__":
    unittest.main()
