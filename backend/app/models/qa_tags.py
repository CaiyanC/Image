"""QA tags dictionary and M2M link table."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class QaTag(Base):
    __tablename__ = "qa_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tag_type: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class QaTagRelation(Base):
    __tablename__ = "qa_tag_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    qa_id: Mapped[str] = mapped_column(String(36), ForeignKey("product_qa.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("qa_tags.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("qa_id", "tag_id", name="uq_qa_tag"),)
