import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=True)
    field_path: Mapped[str] = mapped_column(String(120), nullable=True)
    field_label: Mapped[str] = mapped_column(String(120), nullable=True)
    original_value_json: Mapped[str] = mapped_column(Text, nullable=True)
    proposed_value_json: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(36), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def original_value(self) -> Any:
        return _loads(self.original_value_json)

    @property
    def proposed_value(self) -> Any:
        return _loads(self.proposed_value_json)

    @property
    def result(self) -> Any:
        return _loads(self.result_json)


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
