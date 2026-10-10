import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class ProductBusiness(Base):
    __tablename__ = "product_business"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    top_selling_points: Mapped[str] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str] = mapped_column(Text, nullable=True)
    suitable_people: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audience_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_positioning: Mapped[str | None] = mapped_column(String(100), nullable=True)
    positioning: Mapped[str] = mapped_column(Text, nullable=True)
    price_positioning: Mapped[str] = mapped_column(Text, nullable=True)
    emotional_value: Mapped[str] = mapped_column(Text, nullable=True)
    usage_scenarios: Mapped[str] = mapped_column(Text, nullable=True)
    competitor_benchmark: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
