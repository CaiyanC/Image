import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(80), nullable=True)
    parser_output_json: Mapped[str] = mapped_column(Text, nullable=True)
    actions_json: Mapped[str] = mapped_column(Text, nullable=True)
    results_json: Mapped[str] = mapped_column(Text, nullable=True)
    sources_json: Mapped[str] = mapped_column(Text, nullable=True)
    final_output_json: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="started")
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def parser_output(self) -> Any:
        return _loads(self.parser_output_json, {})

    @property
    def actions(self) -> Any:
        return _loads(self.actions_json, [])

    @property
    def results(self) -> Any:
        return _loads(self.results_json, [])

    @property
    def sources(self) -> Any:
        return _loads(self.sources_json, [])

    @property
    def final_output(self) -> Any:
        return _loads(self.final_output_json, {})


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
