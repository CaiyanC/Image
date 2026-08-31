from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ProductAsset(Base):
    __tablename__ = "product_assets"
    __table_args__ = (
        Index("idx_product_assets_sku", "sku"),
        Index("idx_product_assets_sku_category", "sku", "category_code"),
        Index(
            "idx_product_assets_seq_group",
            "sku",
            "category_code",
            "sub_category",
            "material_type",
        ),
        Index("idx_product_assets_checksum", "checksum_sha256"),
        Index("idx_product_assets_quality_status", "quality_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("products.sku", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    category_code: Mapped[str] = mapped_column(String(2), nullable=False)
    category_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sub_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(10), nullable=False, default="image")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str] = mapped_column(String(64), nullable=False, default="alocs")
    material_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    angle_scene: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_tag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="usable", server_default="usable"
    )
    quality_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unique", server_default="unique"
    )
    duplicate_of_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    asset_level: Mapped[str] = mapped_column(String(10), nullable=False, default="C")
    is_real_product: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_competitor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_latest_version: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_customer_usable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_marketing_usable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_reference_usable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    editable_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    authorization_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    forbidden_usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintainer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
