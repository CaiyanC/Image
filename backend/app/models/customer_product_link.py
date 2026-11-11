"""Verified relations between marketplace listings and internal products."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class CustomerProductLink(Base):
    __tablename__ = "customer_product_links"

    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(36).with_variant(UUID(as_uuid=False), "postgresql"),
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True,
    )
    snapshot_text: Mapped[str | None] = mapped_column(Text)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
