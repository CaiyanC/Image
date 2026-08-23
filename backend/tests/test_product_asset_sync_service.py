import tempfile
import unittest
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.config import settings
from app.models.product import Product
from app.models.product_asset import ProductAsset
from app.services import product_asset_sync_service


class ProductAssetSyncServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Product.__table__, ProductAsset.__table__])
        self.db = sessionmaker(bind=engine)()
        self.product = Product(
            id="sync-product",
            sku="SYNC-1",
            barcode="sync-barcode",
            product_name_cn="同步产品",
            brand="alocs",
        )
        self.db.add(self.product)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_media_data_round_trip_uses_product_assets(self):
        media_data = {
            "source_white_bg": ["/uploads/images/one.jpg"],
            "ai_generated": ["/uploads/images/ai.jpg"],
            "channel_versions": {
                "Amazon": [{
                    "version": "V2",
                    "label": "新版",
                    "ecommerce_main": ["/uploads/images/amazon.jpg"],
                    "detail_module": [],
                }],
            },
        }
        product_asset_sync_service.sync_product_assets_from_media_data(
            self.db, self.product, media_data
        )
        self.db.commit()
        assets = self.db.query(ProductAsset).order_by(ProductAsset.source_key).all()

        self.assertEqual(len(assets), 3)
        ai_asset = next(asset for asset in assets if asset.source_key == "ai_generated")
        self.assertTrue(ai_asset.is_ai_generated)
        self.assertFalse(ai_asset.is_real_product)
        rebuilt = product_asset_sync_service.media_data_from_assets(assets)
        self.assertEqual(rebuilt["source_white_bg"], ["/uploads/images/one.jpg"])
        self.assertEqual(
            rebuilt["channel_versions"]["Amazon"][0]["ecommerce_main"],
            ["/uploads/images/amazon.jpg"],
        )

    def test_media_sync_records_metadata_for_local_uploaded_image(self):
        previous_upload_dir = settings.UPLOAD_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            settings.UPLOAD_DIR = temp_dir
            image_dir = Path(temp_dir) / "images"
            image_dir.mkdir()
            path = image_dir / "local.png"
            Image.new("RGB", (30, 20), color="green").save(path, format="PNG")
            try:
                product_asset_sync_service.sync_product_assets_from_media_data(
                    self.db,
                    self.product,
                    {"source_white_bg": ["/uploads/images/local.png"]},
                )
                self.db.commit()
                asset = self.db.query(ProductAsset).filter(ProductAsset.source_key == "source_white_bg").one()
                self.assertEqual(asset.mime_type, "image/png")
                self.assertEqual(asset.file_size_bytes, path.stat().st_size)
                self.assertEqual(asset.width, 30)
                self.assertEqual(asset.height, 20)
                self.assertEqual(asset.resolution, "30x20")
                self.assertEqual(asset.aspect_ratio, "3:2")
                self.assertEqual(len(asset.checksum_sha256), 64)
            finally:
                settings.UPLOAD_DIR = previous_upload_dir


if __name__ == "__main__":
    unittest.main()
