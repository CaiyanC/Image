"""L5 QA answers — multi-language answer variants per QA item."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class ProductQaAnswer(Base):
    __tablename__ = "qa_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    qa_id: Mapped[str] = mapped_column(String(36), ForeignKey("product_qa.id", ondelete="CASCADE"), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_lang: Mapped[str] = mapped_column(String(20), nullable=True)
    answer_type: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
