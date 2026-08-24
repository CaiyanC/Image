import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, _seed_default_groups, _seed_default_permissions
from app.core.permission_constants import (
    CUSTOMER_SERVICE_GROUP_NAME,
    IT_GROUP_NAME,
    MANAGEMENT_GROUP_NAME,
    PERMISSION_DEFS,
    ROUTE_DEFS,
    SYSTEM_ADMIN_PERMISSION,
)
from app.core.security import get_current_super_admin, get_user_permissions, has_permission
from app.models import Group, GroupPermission, Permission, PermissionRoute, Route, User, UserGroup
from app.services import group_service


class PermissionRouteDefaultsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            Group.__table__,
            UserGroup.__table__,
            Permission.__table__,
            GroupPermission.__table__,
            Route.__table__,
            PermissionRoute.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def test_default_team_permissions_and_routes_are_seeded_consistently(self):
        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)

        group_names = {group.group_name for group in self.db.query(Group).all()}
        self.assertIn(MANAGEMENT_GROUP_NAME, group_names)
        self.assertIn(CUSTOMER_SERVICE_GROUP_NAME, group_names)

        management = group_service.get_group_by_name(self.db, MANAGEMENT_GROUP_NAME)
        it_group = group_service.get_group_by_name(self.db, IT_GROUP_NAME)
        customer_service = group_service.get_group_by_name(self.db, CUSTOMER_SERVICE_GROUP_NAME)
        management_permissions = {
            item["permission_key"]
            for item in group_service.get_group_permissions(self.db, management.id)
        }
        customer_service_permissions = {
            item["permission_key"]
            for item in group_service.get_group_permissions(self.db, customer_service.id)
        }
        it_permissions = {
            item["permission_key"]
            for item in group_service.get_group_permissions(self.db, it_group.id)
        }

        department_permission_keys = {
            key for key, _, _ in PERMISSION_DEFS if key != SYSTEM_ADMIN_PERMISSION
        }
        self.assertEqual(management_permissions, department_permission_keys)
        self.assertEqual(it_permissions, department_permission_keys)
        self.assertIn("ai.customer_service", customer_service_permissions)
        self.assertIn("category.read", customer_service_permissions)
        self.assertNotIn("product.delete", customer_service_permissions)

        route_permissions = {
            route.route_path: {
                key for (key,) in self.db.query(Permission.permission_key)
                .join(PermissionRoute, PermissionRoute.permission_id == Permission.id)
                .filter(PermissionRoute.route_id == route.id)
                .all()
            }
            for route in self.db.query(Route).all()
        }
        self.assertIn("product.edit", route_permissions["/products/edit/:sku"])
        self.assertIn("product.read", route_permissions["/products/drafts"])
        self.assertIn("/admin/logs", route_permissions)
        self.assertEqual({path for path, _, _ in ROUTE_DEFS}, set(route_permissions))
        self.assertTrue(all(route_permissions.values()))
        self.assertEqual(route_permissions["/admin/logs"], {SYSTEM_ADMIN_PERMISSION})

    def test_only_admin_role_in_full_access_group_gets_implicit_system_permissions(self):
        self.db.add(Permission(permission_key="system.audit", permission_name="系统审计", permission_type="api"))
        self.db.add_all([
            Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME),
            Group(id="it-group", group_name=IT_GROUP_NAME),
            User(id="management-user", username="manager", email="manager@example.com", password_hash="hash"),
            User(id="it-user", username="it", email="it@example.com", password_hash="hash"),
        ])
        self.db.add_all([
            UserGroup(user_id="management-user", group_id="management-group", group_role="admin"),
            UserGroup(user_id="it-user", group_id="it-group", group_role="member"),
        ])
        self.db.commit()

        self.assertEqual(get_user_permissions(self.db, "management-user"), ["system.audit"])
        self.assertTrue(has_permission(self.db, "management-user", "system.audit"))
        manager = self.db.query(User).filter(User.id == "management-user").one()
        self.assertEqual(get_current_super_admin(manager, self.db).id, "management-user")

        self.assertEqual(get_user_permissions(self.db, "it-user"), [])
        self.assertFalse(has_permission(self.db, "it-user", "system.audit"))
        member = self.db.query(User).filter(User.id == "it-user").one()
        with self.assertRaises(HTTPException) as caught:
            get_current_super_admin(member, self.db)
        self.assertEqual(caught.exception.status_code, 403)

    def test_non_management_group_cannot_use_unassigned_permission(self):
        self.db.add(Permission(id="read-perm", permission_key="product.read", permission_name="查看产品", permission_type="page"))
        self.db.add(Permission(id="delete-perm", permission_key="product.delete", permission_name="删除产品", permission_type="button"))
        self.db.add(Group(id="customer-group", group_name=CUSTOMER_SERVICE_GROUP_NAME))
        self.db.add(GroupPermission(group_id="customer-group", permission_id="read-perm"))
        self.db.add(User(id="customer-user", username="service", email="service@example.com", password_hash="hash"))
        self.db.add(UserGroup(user_id="customer-user", group_id="customer-group", group_role="member"))
        self.db.commit()

        self.assertTrue(has_permission(self.db, "customer-user", "product.read"))
        self.assertFalse(has_permission(self.db, "customer-user", "product.delete"))

    def test_full_access_group_business_permissions_can_be_reduced(self):
        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)
        for group_name in (MANAGEMENT_GROUP_NAME, IT_GROUP_NAME):
            group = group_service.get_group_by_name(self.db, group_name)
            result = group_service.update_group_permissions(self.db, group.id, [])
            self.assertEqual(result, [])

    def test_preset_management_group_cannot_be_deleted(self):
        self.db.add(Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME))
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            group_service.delete_group(self.db, "management-group")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_system_admin_permission_cannot_be_assigned_to_a_whole_group(self):
        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)
        group = group_service.get_group_by_name(self.db, MANAGEMENT_GROUP_NAME)

        with self.assertRaises(HTTPException) as caught:
            group_service.update_group_permissions(self.db, group.id, [SYSTEM_ADMIN_PERMISSION])

        self.assertEqual(caught.exception.status_code, 400)

    def test_preset_management_group_cannot_be_renamed(self):
        self.db.add(Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME))
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            group_service.update_group(self.db, "management-group", name="renamed")

        self.assertEqual(caught.exception.status_code, 400)

    def test_last_active_management_admin_cannot_be_demoted_through_either_service_path(self):
        group = Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME)
        user = User(id="management-user", username="manager", password_hash="hash", is_active=True)
        self.db.add_all([group, user])
        self.db.add(UserGroup(user_id=user.id, group_id=group.id, group_role="admin"))
        self.db.commit()

        with self.assertRaises(HTTPException):
            group_service.add_user_to_group(self.db, group.id, user.id, "member")
        with self.assertRaises(HTTPException):
            group_service.update_user_group_role(self.db, group.id, user.id, "member")

        membership = self.db.query(UserGroup).filter_by(user_id=user.id, group_id=group.id).one()
        self.assertEqual(membership.group_role, "admin")


if __name__ == "__main__":
    unittest.main()
