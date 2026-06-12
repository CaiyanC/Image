from datetime import datetime, timezone, date
from sqlalchemy import String, DateTime, Date, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    barcode: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name_cn: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name_en: Mapped[str] = mapped_column(String(255), nullable=True)
    brand: Mapped[str] = mapped_column(String(100), nullable=False)
    series: Mapped[str] = mapped_column(String(100), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    sub_category: Mapped[str] = mapped_column(String(100), nullable=True)
    product_level: Mapped[str] = mapped_column(String(20), nullable=False, default="C类品")
    launch_date: Mapped[date] = mapped_column(Date, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(50), nullable=False, default="常规品")
    person_in_charge: Mapped[str] = mapped_column(String(100), nullable=True)
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_note: Mapped[str] = mapped_column(Text, nullable=True)
    status_note: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
