import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.group import Group
from app.models.user import User
from app.models.user_group import UserGroup
from app.models.generation import Generation
from app.models.operation_logs import OperationLog
from app.services import user_service


class UserServicePaginationTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[User.__table__, Group.__table__, UserGroup.__table__])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        for index in range(220):
            self.db.add(User(
                id=f"user-{index}",
                username=f"user-{index:03d}",
                email=f"user-{index}@example.com",
                password_hash="hash",
                user_type="human",
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_get_users_clamps_unbounded_pagination(self):
        users = user_service.get_users(self.db, skip=-100, limit=10000)

        self.assertEqual(len(users), 200)


class UserDeletionRetentionTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[User.__table__, Group.__table__, UserGroup.__table__, Generation.__table__, OperationLog.__table__],
        )
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_delete_user_retains_generation_and_operation_audit(self):
        user = User(id="deleted-user", username="deleted", password_hash="hash", is_active=True)
        self.db.add(user)
        self.db.add(Generation(
            id="generation-1",
            user_id=user.id,
            type="txt2img",
            prompt="test",
            model_name="model",
        ))
        self.db.add(OperationLog(
            id="operation-1",
            operator_id=user.id,
            operator_name_snapshot="deleted",
            action_type="create",
            action_name="create test",
            target_type="test",
            target_id="target-1",
            target_name="target",
        ))
        self.db.commit()

        user_service.delete_user(self.db, user.id, current_user_id="another-user")

        self.assertIsNone(self.db.query(User).filter(User.id == user.id).first())
        self.assertIsNone(self.db.query(Generation).filter_by(id="generation-1").one().user_id)
        retained_log = self.db.query(OperationLog).filter_by(id="operation-1").one()
        self.assertIsNone(retained_log.operator_id)
        self.assertEqual(retained_log.operator_name_snapshot, "deleted")


if __name__ == "__main__":
    unittest.main()
