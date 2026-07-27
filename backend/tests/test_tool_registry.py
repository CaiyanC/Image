import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.core import database
from app.core.database import Base, _seed_default_groups, _seed_default_permissions, seed_default_tools
from app.core.permission_constants import (
    ECOMMERCE_DATA_FILL_PERMISSION,
    FINANCE_GROUP_NAME,
    TOOL_MANAGE_PERMISSION,
)
from app.models import Group, GroupPermission, Permission, PermissionRoute, Route, Tool, ToolRun, User, UserGroup


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


if __name__ == "__main__":
    unittest.main()
