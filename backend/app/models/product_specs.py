import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class ProductSpecs(Base):
    __tablename__ = "product_specs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    size_info: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    capacity: Mapped[str] = mapped_column(Text, nullable=True)
    gross_weight_g: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    body_material: Mapped[str] = mapped_column(Text, nullable=False, default="")
    color: Mapped[str] = mapped_column(Text, nullable=False, default="")
    surface_finish: Mapped[str] = mapped_column(Text, nullable=False, default="")
    heat_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    power: Mapped[str] = mapped_column(Text, nullable=True)
    technical_advantages: Mapped[str] = mapped_column(Text, nullable=True)
    usage_instruction: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
