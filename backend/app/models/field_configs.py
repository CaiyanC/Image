"""Field-level configuration for visibility, editability, and validation rules."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class FieldConfig(Base):
    __tablename__ = "field_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_label: Mapped[str] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_readonly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_list_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_detail_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_filterable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_searchable: Mapped[bool] = mapped_column(Boolean, default=False)
    placeholder_text: Mapped[str] = mapped_column(String(255), nullable=True)
    help_text: Mapped[str] = mapped_column(Text, nullable=True)
    default_value: Mapped[str] = mapped_column(Text, nullable=True)
    config_scope: Mapped[str] = mapped_column(String(50), nullable=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
