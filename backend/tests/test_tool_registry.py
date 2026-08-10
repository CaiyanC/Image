import unittest
import tempfile
from io import BytesIO
from unittest.mock import patch

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
from app.core.config import settings
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

    def test_registry_registers_external_entry_with_department_permission(self):
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

        external = tool_registry_service.create_tool(
            self.db,
            {
                "tool_key": "inventory_dashboard",
                "name": "库存看板",
                "entry_type": "external",
                "external_url": "http://localhost:5280/app",
                "open_mode": "new_tab",
            },
        )
        self.assertEqual(external.entry_type, "external")
        self.assertEqual(external.external_url, "http://localhost:5280/app")
        self.assertEqual(external.permission_key, "tool.inventory_dashboard.use")
        permission = self.db.query(Permission).filter_by(
            permission_key="tool.inventory_dashboard.use"
        ).one()
        management_group_names = {
            name
            for (name,) in self.db.query(Group.group_name)
            .join(GroupPermission, GroupPermission.group_id == Group.id)
            .filter(GroupPermission.permission_id == permission.id)
            .all()
        }
        self.assertEqual(management_group_names, {"总经办", "IT部"})

        visible = tool_registry_service.list_visible_tools(
            self.db,
            [ECOMMERCE_DATA_FILL_PERMISSION],
        )
        self.assertEqual([tool.tool_key for tool in visible], ["ecommerce_data_fill"])

    def test_external_entry_rejects_unsafe_url_and_delete_cleans_permission(self):
        from fastapi import HTTPException
        from app.services import tool_registry_service

        _seed_default_groups(self.db)
        _seed_default_permissions(self.db)

        for unsafe_url in ("javascript:alert(1)", "http://user:pass@localhost:5280"):
            with self.subTest(unsafe_url=unsafe_url), self.assertRaises(HTTPException) as ctx:
                tool_registry_service.create_tool(
                    self.db,
                    {
                        "tool_key": "unsafe_tool",
                        "entry_type": "external",
                        "external_url": unsafe_url,
                    },
                )
            self.assertEqual(ctx.exception.status_code, 422)

        tool_registry_service.create_tool(
            self.db,
            {
                "tool_key": "temporary_tool",
                "entry_type": "external",
                "external_url": "http://127.0.0.1:5290",
            },
        )
        tool_registry_service.delete_tool(self.db, "temporary_tool")
        self.assertIsNone(self.db.query(Tool).filter_by(tool_key="temporary_tool").first())
        self.assertIsNone(
            self.db.query(Permission).filter_by(permission_key="tool.temporary_tool.use").first()
        )


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
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = self.tmpdir.name

    def tearDown(self):
        app.dependency_overrides.clear()
        settings.UPLOAD_DIR = self.original_upload_dir
        self.tmpdir.cleanup()

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

    def test_management_can_register_update_and_delete_external_tool(self):
        def manager_user():
            return type("UserStub", (), {"id": "manager-user", "username": "manager"})()

        app.dependency_overrides[get_current_super_admin] = manager_user
        created = self.client.post(
            "/api/admin/tools",
            json={
                "tool_key": "local_report",
                "name": "本地报表",
                "entry_type": "external",
                "external_url": "http://localhost:5390",
                "open_mode": "new_tab",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["entry_type"], "external")
        self.assertEqual(created.json()["permission_key"], "tool.local_report.use")

        updated = self.client.put(
            "/api/admin/tools/local_report",
            json={"external_url": "http://localhost:5391/reports", "open_mode": "same_tab"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["external_url"], "http://localhost:5391/reports")
        self.assertEqual(updated.json()["open_mode"], "same_tab")

        deleted = self.client.delete("/api/admin/tools/local_report")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["tool_key"], "local_report")

    def test_finance_user_can_submit_an_excel_run_without_exposing_the_task_queue(self):
        with patch("app.api.tools.run_ecommerce_data_fill_tool_run.apply_async") as enqueue:
            response = self.client.post(
                "/api/tools/ecommerce-data-fill/runs",
                data={"mode": "ecommerce", "parameters_json": "{}"},
                files={
                    "files": (
                        "source.xlsx",
                        BytesIO(b"test spreadsheet contents"),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["tool_key"], "ecommerce_data_fill")
        self.assertEqual(body["input_files"][0]["display_name"], "source.xlsx")
        enqueue.assert_called_once_with(args=[body["id"]], task_id=body["id"])

    def test_tool_run_enqueue_failure_returns_503_and_marks_run_failed(self):
        with patch(
            "app.api.tools.run_ecommerce_data_fill_tool_run.apply_async",
            side_effect=ConnectionError("redis down"),
        ):
            response = self.client.post(
                "/api/tools/ecommerce-data-fill/runs",
                data={"mode": "ecommerce", "parameters_json": "{}"},
                files={
                    "files": (
                        "source.xlsx",
                        BytesIO(b"test spreadsheet contents"),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                },
            )

        self.assertEqual(response.status_code, 503, response.text)
        db = self.Session()
        try:
            run = db.query(ToolRun).order_by(ToolRun.created_at.desc()).first()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")
            self.assertEqual(run.error_message, "Task queue unavailable")
        finally:
            db.close()
