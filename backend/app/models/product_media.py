import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class ProductMedia(Base):
    __tablename__ = "product_media"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    media_layer: Mapped[str] = mapped_column(String(50), nullable=False, default="raw")
    media_group: Mapped[str] = mapped_column(String(100), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=True)
    channel_name: Mapped[str] = mapped_column(String(100), nullable=True)
    page_type: Mapped[str] = mapped_column(String(100), nullable=True)
    media_version: Mapped[str] = mapped_column(String(50), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=True)
    file_format: Mapped[str] = mapped_column(String(20), nullable=True)
    media_level: Mapped[str] = mapped_column(String(10), nullable=False, default="C")
    is_real_product: Mapped[bool] = mapped_column(Boolean, default=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_competitor: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_customer_usable: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_marketing_usable: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_reference_usable: Mapped[bool] = mapped_column(Boolean, default=False)
    editable_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    authorization_status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    forbidden_usage: Mapped[str] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(20), nullable=True)
    tag_list: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
