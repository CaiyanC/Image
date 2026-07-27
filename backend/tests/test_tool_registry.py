import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app import models
from app.core import database
from app.core.database import Base, _seed_default_groups, _seed_default_permissions, seed_default_tools
from app.core.permission_constants import (
    ECOMMERCE_DATA_FILL_PERMISSION,
    FINANCE_GROUP_NAME,
    TOOL_MANAGE_PERMISSION,
)
from app.models import Group, GroupPermission, OperationLog, Permission, PermissionRoute, Route, Tool, ToolRun, User, UserGroup
from app.core.security import get_current_user
from app.core.security import get_current_super_admin
from app.main import app


class ToolRegistryContractTest(unittest.TestCase):
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
            Tool.__table__,
            ToolRun.__table__,
            OperationLog.__table__,
        ])
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_tool_model_is_exposed_from_models_package(self):
        self.assertTrue(
            hasattr(models, "Tool"),
            "Tool registry model must be exposed through app.models",
        )

    def test_default_tool_seed_is_available(self):
        self.assertTrue(
            hasattr(database, "seed_default_tools"),
            "Tool registry must expose an idempotent default seed function",
        )

    def test_tool_run_model_is_exposed_from_models_package(self):
        self.assertTrue(
            hasattr(models, "ToolRun"),
            "File-based tools require a persisted ToolRun model",
        )

    def test_default_seed_creates_finance_tool_and_permissions_idempotently(self):
        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)
        seed_default_tools(self.db)
        seed_default_tools(self.db)

        finance = self.db.query(Group).filter_by(group_name=FINANCE_GROUP_NAME).one()
        finance_permission_keys = {
            key
            for (key,) in self.db.query(Permission.permission_key)
            .join(GroupPermission, GroupPermission.permission_id == Permission.id)
            .filter(GroupPermission.group_id == finance.id)
            .all()
        }
        tools = self.db.query(Tool).order_by(Tool.sort_order).all()

        self.assertIn(ECOMMERCE_DATA_FILL_PERMISSION, finance_permission_keys)
        self.assertNotIn(TOOL_MANAGE_PERMISSION, finance_permission_keys)
        self.assertEqual([tool.tool_key for tool in tools].count("ecommerce_data_fill"), 1)
        ecommerce_tool = next(tool for tool in tools if tool.tool_key == "ecommerce_data_fill")
        self.assertEqual(ecommerce_tool.route_path, "/tools/ecommerce-data-fill")
        self.assertEqual(ecommerce_tool.permission_key, ECOMMERCE_DATA_FILL_PERMISSION)

    def test_registry_service_exposes_controlled_entry_allowlist(self):
        from app.services import tool_registry_service

        self.assertEqual(
            tool_registry_service.ALLOWED_TOOL_ENTRIES["ecommerce_data_fill"]["route_path"],
            "/tools/ecommerce-data-fill",
        )

    def test_registry_rejects_unregistered_entry_and_filters_visible_tools(self):
        from fastapi import HTTPException
        from app.services import tool_registry_service

        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)
        seed_default_tools(self.db)

        with self.assertRaises(HTTPException) as ctx:
            tool_registry_service.create_tool(
                self.db,
                {"tool_key": "external_script", "route_path": "https://example.com"},
            )
        self.assertEqual(ctx.exception.status_code, 422)

        visible = tool_registry_service.list_visible_tools(
            self.db,
            [ECOMMERCE_DATA_FILL_PERMISSION],
        )
        self.assertEqual([tool.tool_key for tool in visible], ["ecommerce_data_fill"])


if __name__ == "__main__":
    unittest.main()


class ToolDirectoryApiTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            Group.__table__,
            UserGroup.__table__,
            Permission.__table__,
            GroupPermission.__table__,
            Route.__table__,
            PermissionRoute.__table__,
            Tool.__table__,
            ToolRun.__table__,
            OperationLog.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        _seed_default_groups(db)
        _seed_default_permissions(db)
        seed_default_tools(db)
        finance = db.query(Group).filter_by(group_name=FINANCE_GROUP_NAME).one()
        db.add(User(id="finance-user", username="finance", password_hash="unused"))
        db.add(UserGroup(user_id="finance-user", group_id=finance.id, group_role="member"))
        db.commit()
        db.close()

        def override_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        def finance_user():
            return type("UserStub", (), {"id": "finance-user", "username": "finance"})()

        app.dependency_overrides[database.get_db] = override_db
        app.dependency_overrides[get_current_user] = finance_user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_finance_user_sees_every_tool_backed_by_its_existing_permissions(self):
        response = self.client.get("/api/tools")

        self.assertEqual(response.status_code, 200)
        tool_keys = [item["tool_key"] for item in response.json()]
        self.assertIn("ecommerce_data_fill", tool_keys)
        self.assertIn("ai_create", tool_keys)
        self.assertNotIn("customer_service", tool_keys)

    def test_management_can_list_registered_tools(self):
        def manager_user():
            return type("UserStub", (), {"id": "manager-user", "username": "manager"})()

        app.dependency_overrides[get_current_super_admin] = manager_user
        response = self.client.get("/api/admin/tools")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ecommerce_data_fill", [item["tool_key"] for item in response.json()])

    def test_management_can_register_a_code_allowlisted_tool(self):
        db = self.Session()
        db.query(Tool).filter_by(tool_key="customer_service").delete()
        db.commit()
        db.close()

        def manager_user():
            return type("UserStub", (), {"id": "manager-user", "username": "manager"})()

        app.dependency_overrides[get_current_super_admin] = manager_user
        response = self.client.post(
            "/api/admin/tools",
            json={
                "tool_key": "customer_service",
                "name": "客户协同",
                "category": "业务工具",
                "route_path": "https://ignored.example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["route_path"], "/customer-service")
        self.assertEqual(response.json()["permission_key"], "ai.customer_service")
