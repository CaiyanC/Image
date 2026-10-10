"""Independent internal reference assets; never a company's ProductAsset."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class CompetitorAsset(Base):
    __tablename__ = "competitor_assets"
    __table_args__ = (
        CheckConstraint("asset_type IN ('image', 'video')", name="ck_competitor_asset_type"),
        Index("idx_competitor_assets_brand_type", "brand", "asset_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    brand: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintainer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

