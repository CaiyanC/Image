import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.competitor_asset import CompetitorAsset
from app.services import competitor_asset_service as service


class CompetitorAssetServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        CompetitorAsset.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_brand_and_media_grouping_without_any_product_table(self):
        for brand, kind in [(" Brand A ", "image"), ("Brand A", "video"), ("Brand B", "image")]:
            service.create_uploaded_asset(self.db, brand=brand, uploaded_by="uploader", maintainer="designer",
                                          metadata={"asset_type": kind, "url": "/uploads/reference.png", "is_public": True})
        self.db.commit()
        self.assertEqual(inspect(self.engine).get_table_names(), ["competitor_assets"])
        self.assertEqual(service.list_brand_counts(self.db), [
            {"brand": "Brand A", "image_count": 1, "video_count": 1},
            {"brand": "Brand B", "image_count": 1, "video_count": 0},
        ])
        row = service.list_assets(self.db, brand="Brand A", asset_type="video")[0]
        self.assertEqual(row.maintainer, "designer")
        self.assertEqual(row.uploaded_by, "uploader")
        self.assertNotIn("sku", CompetitorAsset.__table__.columns)
        self.assertNotIn("is_public", CompetitorAsset.__table__.columns)
        self.assertEqual(service.list_assets(self.db, brand="Brand A", offset=2), [])

    def test_invalid_brand_kind_and_pagination_rejected(self):
        for brand in (" ", "x" * 65):
            with self.assertRaises(HTTPException):
                service.normalize_brand(brand)
        with self.assertRaises(HTTPException):
            service.list_assets(self.db, brand="A", asset_type="document")
        with self.assertRaises(HTTPException):
            service.list_assets(self.db, brand="A", limit=101)
        with self.assertRaises(HTTPException):
            service.create_uploaded_asset(self.db, brand="A", uploaded_by="u", metadata={"asset_type": "document"})

    def test_migration_creates_only_independent_storage_and_preserves_existing_rows(self):
        path = Path(__file__).parents[1] / "alembic" / "versions" / "20260917_add_competitor_assets.py"
        spec = importlib.util.spec_from_file_location("competitor_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE existing_records (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO existing_records VALUES (1)")
            with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                migration.upgrade()
                actual_columns = {item["name"] for item in inspect(connection).get_columns("competitor_assets")}
                self.assertEqual(actual_columns, set(CompetitorAsset.__table__.columns.keys()))
                self.assertEqual(inspect(connection).get_foreign_keys("competitor_assets"), [])
                migration.downgrade()
            self.assertEqual(connection.exec_driver_sql("SELECT id FROM existing_records").scalar(), 1)
            self.assertNotIn("competitor_assets", inspect(connection).get_table_names())
        engine.dispose()
