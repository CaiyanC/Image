import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class ProductContent(Base):
    __tablename__ = "product_content"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    title_en: Mapped[str] = mapped_column(Text, nullable=True)
    title_cn: Mapped[str] = mapped_column(Text, nullable=False, default="")
    long_description_en: Mapped[str] = mapped_column(Text, nullable=True)
    long_description_cn: Mapped[str] = mapped_column(Text, nullable=False, default="")
    long_description_ja: Mapped[str] = mapped_column(Text, nullable=True)
    search_keywords: Mapped[str] = mapped_column(Text, nullable=True)
    amazon_title: Mapped[str] = mapped_column(Text, nullable=True)
    website_title: Mapped[str] = mapped_column(Text, nullable=True)
    bullet_points: Mapped[str] = mapped_column(Text, nullable=True)
    a_plus_content: Mapped[str] = mapped_column(Text, nullable=True)
    listing_cn: Mapped[str] = mapped_column(Text, nullable=True)
    listing_en: Mapped[str] = mapped_column(Text, nullable=True)
    listing_ja: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
