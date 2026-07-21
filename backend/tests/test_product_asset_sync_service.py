import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
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


if __name__ == "__main__":
    unittest.main()
