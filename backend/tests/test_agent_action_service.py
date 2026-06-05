import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.operation_logs import OperationLog
from app.models import (
    Product, ProductBusiness, ProductCertification, ProductContent, ProductKeyword,
    ProductListingChannel, ProductMedia, ProductPrompts, ProductQa, ProductQaNegative,
    ProductSalesRegion, ProductSpecs, Certification, Keyword, ListingChannel, SalesRegion,
)
from app.models.agent_action import AgentAction
from app.services import agent_action_service


class AgentActionServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
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
            AgentAction.__table__,
            OperationLog.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        product = Product(
            id="product-1",
            sku="CS-G25",
            barcode="barcode",
            product_name_cn="小青炉",
            product_name_en="Mini Stove",
            brand="alocs爱路客",
            product_level="B类品",
            lifecycle_status="主推品",
            person_in_charge="Max",
        )
        self.db.add(product)
        self.db.add(ProductSpecs(
            id="specs-1",
            product_id="product-1",
            body_material="不锈钢",
            color="银色",
            surface_finish="硬质氧化",
            heat_source="燃气炉",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_update_action_does_not_change_database_until_confirmed(self):
        action = agent_action_service.create_update_field_action(
            self.db,
            created_by="user-1",
            sku="CS-G25",
            field_path="specs.body_material",
            new_value="304不锈钢",
        )

        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == "product-1").first()
        self.assertEqual(specs.body_material, "不锈钢")
        self.assertEqual(action.status, "pending")
        self.assertEqual(action.original_value, "不锈钢")
        self.assertEqual(action.proposed_value, "304不锈钢")

    def test_confirm_update_action_applies_change_and_marks_confirmed(self):
        action = agent_action_service.create_update_field_action(
            self.db,
            created_by="user-1",
            sku="CS-G25",
            field_path="specs.body_material",
            new_value="304不锈钢",
        )

        result = agent_action_service.confirm_action(
            self.db,
            action_id=action.id,
            confirmed_by="user-2",
            permissions={"product.edit"},
        )

        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == "product-1").first()
        refreshed = self.db.query(AgentAction).filter(AgentAction.id == action.id).first()
        self.assertEqual(specs.body_material, "304不锈钢")
        self.assertEqual(refreshed.status, "confirmed")
        self.assertEqual(result["status"], "confirmed")

    def test_confirm_update_action_detects_stale_original_value(self):
        action = agent_action_service.create_update_field_action(
            self.db,
            created_by="user-1",
            sku="CS-G25",
            field_path="specs.body_material",
            new_value="304不锈钢",
        )
        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == "product-1").first()
        specs.body_material = "铝合金"
        self.db.commit()

        result = agent_action_service.confirm_action(
            self.db,
            action_id=action.id,
            confirmed_by="user-2",
            permissions={"product.edit"},
        )

        refreshed = self.db.query(AgentAction).filter(AgentAction.id == action.id).first()
        self.assertEqual(refreshed.status, "stale")
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["current_value"], "铝合金")

    def test_cancel_action_marks_pending_action_cancelled(self):
        action = agent_action_service.create_update_field_action(
            self.db,
            created_by="user-1",
            sku="CS-G25",
            field_path="specs.body_material",
            new_value="304不锈钢",
        )

        result = agent_action_service.cancel_action(self.db, action.id, cancelled_by="user-2")

        refreshed = self.db.query(AgentAction).filter(AgentAction.id == action.id).first()
        self.assertEqual(refreshed.status, "cancelled")
        self.assertEqual(result["status"], "cancelled")

    def test_capacity_update_preserves_existing_label_value_shape(self):
        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == "product-1").first()
        specs.capacity = '[{"label": "锅", "value": "3700ML"}]'
        self.db.commit()

        action = agent_action_service.create_update_field_action(
            self.db,
            created_by="user-1",
            sku="CS-G25",
            field_path="specs.capacity",
            new_value="2000ml",
        )

        self.assertEqual(action.original_value, '[{"label": "锅", "value": "3700ML"}]')
        self.assertEqual(action.proposed_value, [{"label": "锅", "value": "2000ml"}])

    def test_delete_product_action_serializes_uuid_like_values(self):
        action = agent_action_service.create_delete_product_action(
            self.db,
            created_by="user-1",
            sku="CS-G25",
        )

        payload = json.loads(action.original_value_json)
        self.assertEqual(payload["id"], "product-1")
        self.assertEqual(action.action_type, "delete_product")


if __name__ == "__main__":
    unittest.main()
