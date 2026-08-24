import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, _seed_default_groups, _seed_default_permissions
from app.core.permission_constants import (
    BRAND_GROUP_NAME,
    DEFAULT_GROUPS,
    EXECUTIVE_OFFICE_GROUP_NAME,
    FINANCE_GROUP_NAME,
    IT_GROUP_NAME,
    PERMISSION_DEFS,
    SYSTEM_ADMIN_PERMISSION,
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
        all_permission_keys = {
            key for key, _, _ in PERMISSION_DEFS if key != SYSTEM_ADMIN_PERMISSION
        }
        for group_name in (EXECUTIVE_OFFICE_GROUP_NAME, IT_GROUP_NAME):
            group = self.db.query(Group).filter(Group.group_name == group_name).one()
            permission_keys = {
                key for (key,) in self.db.query(Permission.permission_key)
                .join(GroupPermission, GroupPermission.permission_id == Permission.id)
                .filter(GroupPermission.group_id == group.id)
                .all()
            }
            self.assertEqual(permission_keys, all_permission_keys)

    def test_restart_preserves_custom_permissions_for_preset_department(self):
        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)
        finance = self.db.query(Group).filter(Group.group_name == FINANCE_GROUP_NAME).one()
        chosen = self.db.query(Permission).filter(Permission.permission_key == "history.view").one()
        self.db.query(GroupPermission).filter(GroupPermission.group_id == finance.id).delete()
        self.db.add(GroupPermission(group_id=finance.id, permission_id=chosen.id))
        self.db.commit()

        _seed_default_permissions(self.db)

        permission_keys = {
            key for (key,) in self.db.query(Permission.permission_key)
            .join(GroupPermission, GroupPermission.permission_id == Permission.id)
            .filter(GroupPermission.group_id == finance.id)
            .all()
        }
        self.assertEqual(permission_keys, {"history.view"})

    def test_legacy_merge_preserves_admin_role_and_permission_union(self):
        user = User(id="merge-user", username="merge", password_hash="hash")
        target = Group(id="brand-target", group_name=BRAND_GROUP_NAME)
        legacy = Group(id="brand-legacy", group_name="AI内容岗")
        first = Permission(id="permission-1", permission_key="test.first", permission_name="first")
        second = Permission(id="permission-2", permission_key="test.second", permission_name="second")
        self.db.add_all([user, target, legacy, first, second])
        self.db.flush()
        self.db.add_all([
            UserGroup(user_id=user.id, group_id=target.id, group_role="member"),
            UserGroup(user_id=user.id, group_id=legacy.id, group_role="admin"),
            GroupPermission(group_id=target.id, permission_id=first.id),
            GroupPermission(group_id=legacy.id, permission_id=second.id),
        ])
        self.db.commit()

        _seed_default_groups(self.db)

        self.assertIsNone(self.db.query(Group).filter(Group.group_name == "AI内容岗").first())
        membership = self.db.query(UserGroup).filter_by(user_id=user.id, group_id=target.id).one()
        self.assertEqual(membership.group_role, "admin")
        permission_ids = {
            permission_id for (permission_id,) in self.db.query(GroupPermission.permission_id)
            .filter(GroupPermission.group_id == target.id).all()
        }
        self.assertEqual(permission_ids, {first.id, second.id})

    def test_restart_preserves_intentionally_empty_preset_permissions(self):
        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)
        finance = self.db.query(Group).filter(Group.group_name == FINANCE_GROUP_NAME).one()
        self.db.query(GroupPermission).filter(GroupPermission.group_id == finance.id).delete()
        self.db.commit()

        _seed_default_permissions(self.db)

        self.assertEqual(
            self.db.query(GroupPermission).filter(GroupPermission.group_id == finance.id).count(),
            0,
        )


if __name__ == "__main__":
    unittest.main()
