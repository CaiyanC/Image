import unittest
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models import Tool, ToolRun, User


class ToolRunServiceContractTest(unittest.TestCase):
    def test_tool_run_service_exposes_safe_run_directory_resolver(self):
        from app.services import tool_run_service

        self.assertTrue(callable(tool_run_service.run_directory))
        self.assertTrue(callable(tool_run_service.resolve_run_file))


class ToolRunServiceSecurityTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[User.__table__, Tool.__table__, ToolRun.__table__])
        self.db = sessionmaker(bind=engine)()
        self.db.add_all([
            User(id="owner", username="owner", password_hash="unused"),
            Tool(
                tool_key="ecommerce_data_fill",
                name="fill",
                route_path="/tools/ecommerce-data-fill",
                permission_key="finance.ecommerce_data_fill",
            ),
        ])
        self.db.commit()
        self.run = ToolRun(tool_key="ecommerce_data_fill", created_by="owner", parameters={})
        self.db.add(self.run)
        self.db.commit()
        self.db.refresh(self.run)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = self.tmpdir.name

    def tearDown(self):
        settings.UPLOAD_DIR = self.original_upload_dir
        self.db.close()
        self.tmpdir.cleanup()

    def test_run_files_cannot_escape_run_directory_or_cross_owner_boundary(self):
        from fastapi import HTTPException
        from app.services import tool_run_service

        with self.assertRaises(HTTPException) as access_error:
            tool_run_service.ensure_run_access(self.run, user_id="other", is_management=False)
        self.assertEqual(access_error.exception.status_code, 403)

        with self.assertRaises(HTTPException) as path_error:
            tool_run_service.resolve_run_file(self.run, "../../.env")
        self.assertEqual(path_error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
