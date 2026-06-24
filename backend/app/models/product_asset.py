from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index
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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("products.sku", ondelete="RESTRICT"),
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
    angle_scene: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_tag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
