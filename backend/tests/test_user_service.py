import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.group import Group
from app.models.user import User
from app.models.user_group import UserGroup
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


if __name__ == "__main__":
    unittest.main()
