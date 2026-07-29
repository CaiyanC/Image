import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AIProviderCredential(Base):
    __tablename__ = "ai_provider_credentials"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'company' AND scope_id IS NULL) OR "
            "(scope_type IN ('group', 'user') AND scope_id IS NOT NULL)",
            name="ck_ai_provider_credentials_scope",
        ),
        Index(
            "uq_ai_provider_credentials_provider_scope",
            "provider_name",
            "scope_type",
            text("COALESCE(scope_id, '')"),
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    api_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(4), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AIModel(Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        CheckConstraint("api_format IN ('openai', 'gemini')", name="ck_ai_models_api_format"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_format: Mapped[str] = mapped_column(String(16), nullable=False, default="openai")
    api_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AIFeatureModel(Base):
    __tablename__ = "ai_feature_models"
    __table_args__ = (
        UniqueConstraint("feature_key", "model_id", name="uq_ai_feature_models_feature_model"),
        Index(
            "uq_ai_feature_models_one_default",
            "feature_key",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feature_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AIModelAccessRule(Base):
    __tablename__ = "ai_model_access_rules"
    __table_args__ = (
        UniqueConstraint(
            "feature_key",
            "model_id",
            "subject_type",
            "subject_id",
            name="uq_ai_model_access_rules_subject",
        ),
        CheckConstraint("effect IN ('allow', 'deny')", name="ck_ai_model_access_rules_effect"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    feature_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ai_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    effect: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AIModelUsageLog(Base):
    __tablename__ = "ai_model_usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feature_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("ai_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    credential_scope_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
