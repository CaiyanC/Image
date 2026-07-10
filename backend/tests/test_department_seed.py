import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, _seed_default_groups, _seed_default_permissions
from app.core.permission_constants import (
    BRAND_GROUP_NAME,
    DEFAULT_GROUPS,
    EXECUTIVE_OFFICE_GROUP_NAME,
)
from app.models.group import Group
from app.models.permissions import GroupPermission, Permission
from app.models.routes import PermissionRoute, Route
from app.models.user import User
from app.models.user_group import UserGroup


class DepartmentSeedTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__, Group.__table__, UserGroup.__table__,
                Permission.__table__, GroupPermission.__table__,
                Route.__table__, PermissionRoute.__table__,
            ],
        )
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_legacy_groups_migrate_members_and_seed_departments(self):
        self.db.add(User(id="legacy-user", username="legacy", password_hash="hash"))
        management = Group(id="legacy-management", group_name="管理层")
        ai_content = Group(id="legacy-ai-content", group_name="AI内容岗")
        test_group = Group(id="test-group", group_name="test-group-file_old")
        self.db.add_all([management, ai_content, test_group])
        self.db.flush()
        self.db.add(UserGroup(user_id="legacy-user", group_id=ai_content.id, group_role="member"))
        self.db.commit()

        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)

        names = {group.group_name for group in self.db.query(Group).all()}
        self.assertEqual({name for name, _ in DEFAULT_GROUPS}, names)
        membership = self.db.query(UserGroup).filter(UserGroup.user_id == "legacy-user").one()
        self.assertEqual(membership.group.group_name, BRAND_GROUP_NAME)
        executive = self.db.query(Group).filter(Group.group_name == EXECUTIVE_OFFICE_GROUP_NAME).one()
        self.assertGreater(self.db.query(GroupPermission).filter(GroupPermission.group_id == executive.id).count(), 0)


if __name__ == "__main__":
    unittest.main()
