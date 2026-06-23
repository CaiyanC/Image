import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.operation_logs import OperationLog
from app.models.product_operation_snapshot import ProductOperationSnapshot
from app.models.user import User
from app.models.user_group import UserGroup
from app.services import operation_log_service


class OperationLogListTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            UserGroup.__table__,
            OperationLog.__table__,
            ProductOperationSnapshot.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.db.add_all([
            User(id="user-a", username="alice", email="alice@example.com", password_hash="hash"),
            User(id="user-b", username="bob", email="bob@example.com", password_hash="hash"),
        ])
        base_time = datetime(2026, 6, 22, 10, 0, 0)
        self.db.add_all([
            OperationLog(
                id="log-1",
                operator_id="user-a",
                action_type="update",
                action_name="编辑产品",
                target_type="product",
                target_id="CW-001",
                target_name="CW-001",
                created_at=base_time,
            ),
            OperationLog(
                id="log-2",
                operator_id="user-b",
                action_type="delete",
                action_name="删除产品",
                target_type="product",
                target_id="CW-002",
                target_name="CW-002",
                created_at=base_time + timedelta(minutes=1),
            ),
            OperationLog(
                id="log-3",
                operator_id="user-a",
                action_type="import",
                action_name="导入产品QA",
                target_type="product_qa",
                target_id="batch",
                target_name="QA batch",
                created_at=base_time + timedelta(minutes=1),
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_list_operation_logs_filters_by_operator_time_and_keyword_with_stable_sort(self):
        result = operation_log_service.list_operation_logs(
            self.db,
            operator_id="user-a",
            search="产品",
            date_from=datetime(2026, 6, 22, 10, 0, 30),
            date_to=datetime(2026, 6, 22, 10, 1, 30),
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], "log-3")
        self.assertEqual(result["items"][0]["operator_name"], "alice")

    def test_list_operation_logs_orders_same_timestamp_by_id_desc(self):
        result = operation_log_service.list_operation_logs(self.db)

        self.assertEqual([item["id"] for item in result["items"][:2]], ["log-3", "log-2"])


if __name__ == "__main__":
    unittest.main()
