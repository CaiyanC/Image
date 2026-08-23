import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models.generation import Generation
from app.models.product import Product
from app.models.product_asset import ProductAsset
from app.models.user import User
from app.services import generation_service, storage_reconciliation_service


def test_generation_delete_removes_all_local_result_files():
    with tempfile.TemporaryDirectory() as temp_dir:
        generated_dir = Path(temp_dir) / "generated"
        generated_dir.mkdir()
        first = generated_dir / "first.png"
        second = generated_dir / "second.png"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        previous_generated_dir = settings.GENERATED_DIR
        settings.GENERATED_DIR = str(generated_dir)
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[User.__table__, Product.__table__, Generation.__table__])
        session = sessionmaker(bind=engine)()
        try:
            session.add(User(id="owner", username="owner", password_hash="hash", is_active=True))
            session.add(Generation(
                id="generation-1",
                user_id="owner",
                type="txt2img",
                prompt="test",
                model_name="model",
                status="completed",
                result_image_path="/uploads/generated/first.png",
                result_images=["/uploads/generated/first.png", "/uploads/generated/second.png"],
            ))
            session.commit()
            generation_service.delete_generation(session, "generation-1", "owner")
            assert session.get(Generation, "generation-1") is None
            assert not first.exists()
            assert not second.exists()
        finally:
            session.close()
            engine.dispose()
            settings.GENERATED_DIR = previous_generated_dir


def test_storage_reconciliation_is_dry_run_by_default_and_cleans_only_old_orphans():
    with tempfile.TemporaryDirectory() as temp_dir:
        upload_root = Path(temp_dir) / "uploads"
        asset_dir = upload_root / "assets" / "SKU-1"
        image_dir = upload_root / "images"
        asset_dir.mkdir(parents=True)
        image_dir.mkdir(parents=True)
        referenced = asset_dir / "kept.png"
        orphan = image_dir / "abandoned.png"
        recent = image_dir / "recent.png"
        referenced.write_bytes(b"kept")
        orphan.write_bytes(b"orphan")
        recent.write_bytes(b"recent")
        os.utime(orphan, (1, 1))

        previous_upload_dir = settings.UPLOAD_DIR
        settings.UPLOAD_DIR = str(upload_root)
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Product.__table__, ProductAsset.__table__])
        session = sessionmaker(bind=engine)()
        try:
            session.add(Product(
                id="product-1",
                sku="SKU-1",
                barcode="barcode",
                product_name_cn="测试",
                brand="alocs",
            ))
            session.add(ProductAsset(
                id="asset-1",
                sku="SKU-1",
                category_code="01",
                category_name="产品标准图",
                asset_type="image",
                url="/uploads/assets/SKU-1/kept.png",
            ))
            session.commit()

            report = storage_reconciliation_service.reconcile_upload_storage(
                session,
                minimum_age_hours=24,
            )
            assert orphan.exists()
            assert {item["path"] for item in report["orphan_files"]} == {
                "images/abandoned.png",
                "images/recent.png",
            }

            applied = storage_reconciliation_service.reconcile_upload_storage(
                session,
                apply_cleanup=True,
                minimum_age_hours=24,
            )
            assert applied["removed"] == ["images/abandoned.png"]
            assert referenced.exists()
            assert recent.exists()
        finally:
            session.close()
            engine.dispose()
            settings.UPLOAD_DIR = previous_upload_dir
