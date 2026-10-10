from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ProductSupplyChain(Base):
    """采购、供应商和外箱装箱信息 kept separate from customer-facing specs."""

    __tablename__ = "product_supply_chain"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(36).with_variant(postgresql.UUID(as_uuid=False), "postgresql"),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    barcode_69: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(8), nullable=True, default="CNY")
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outer_carton_length_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    outer_carton_width_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    outer_carton_height_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    outer_carton_pcs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
