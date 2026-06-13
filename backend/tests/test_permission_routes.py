import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, _seed_default_groups, _seed_default_permissions
from app.core.permission_constants import CUSTOMER_SERVICE_GROUP_NAME, MANAGEMENT_GROUP_NAME
from app.core.security import get_user_permissions, has_permission
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
        customer_service = group_service.get_group_by_name(self.db, CUSTOMER_SERVICE_GROUP_NAME)
        management_permissions = {
            item["permission_key"]
            for item in group_service.get_group_permissions(self.db, management.id)
        }
        customer_service_permissions = {
            item["permission_key"]
            for item in group_service.get_group_permissions(self.db, customer_service.id)
        }

        self.assertIn("product.delete", management_permissions)
        self.assertIn("export.approved", management_permissions)
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

    def test_management_group_gets_all_permissions_without_direct_group_permission_rows(self):
        self.db.add(Permission(permission_key="system.audit", permission_name="系统审计", permission_type="api"))
        self.db.add(Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME))
        self.db.add(User(id="management-user", username="manager", email="manager@example.com", password_hash="hash"))
        self.db.add(UserGroup(user_id="management-user", group_id="management-group", group_role="member"))
        self.db.commit()

        self.assertEqual(get_user_permissions(self.db, "management-user"), ["system.audit"])
        self.assertTrue(has_permission(self.db, "management-user", "system.audit"))

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

    def test_preset_management_group_cannot_be_deleted(self):
        self.db.add(Group(id="management-group", group_name=MANAGEMENT_GROUP_NAME))
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            group_service.delete_group(self.db, "management-group")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
