"""Add AI model governance tables.

Revision ID: 20260728_add_ai_model_governance
Revises: 20260727_add_tools_and_tool_runs
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_add_ai_model_governance"
down_revision = "20260727_add_tools_and_tool_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("api_base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(length=4), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(scope_type = 'company' AND scope_id IS NULL) OR "
            "(scope_type IN ('group', 'user') AND scope_id IS NOT NULL)",
            name="ck_ai_provider_credentials_scope",
        ),
    )
    op.create_index("ix_ai_provider_credentials_provider_name", "ai_provider_credentials", ["provider_name"])
    op.create_index("ix_ai_provider_credentials_scope_type", "ai_provider_credentials", ["scope_type"])
    op.create_index("ix_ai_provider_credentials_scope_id", "ai_provider_credentials", ["scope_id"])
    op.create_index(
        "uq_ai_provider_credentials_provider_scope",
        "ai_provider_credentials",
        ["provider_name", "scope_type", sa.text("COALESCE(scope_id, '')")],
        unique=True,
    )

    op.create_table(
        "ai_models",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("request_model_name", sa.String(length=255), nullable=False),
        sa.Column("api_format", sa.String(length=16), nullable=False, server_default="openai"),
        sa.Column("api_endpoint", sa.String(length=500), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("api_format IN ('openai', 'gemini')", name="ck_ai_models_api_format"),
    )
    op.create_index("ix_ai_models_provider_name", "ai_models", ["provider_name"])
    op.create_index("ix_ai_models_capability", "ai_models", ["capability"])

    op.create_table(
        "ai_feature_models",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("feature_key", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["ai_models.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("feature_key", "model_id", name="uq_ai_feature_models_feature_model"),
    )
    op.create_index("ix_ai_feature_models_feature_key", "ai_feature_models", ["feature_key"])
    op.create_index("ix_ai_feature_models_model_id", "ai_feature_models", ["model_id"])
    op.create_index(
        "uq_ai_feature_models_one_default",
        "ai_feature_models",
        ["feature_key"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )

    op.create_table(
        "ai_model_access_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("feature_key", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("effect", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["ai_models.id"], ondelete="CASCADE"),
        sa.CheckConstraint("effect IN ('allow', 'deny')", name="ck_ai_model_access_rules_effect"),
        sa.UniqueConstraint(
            "feature_key", "model_id", "subject_type", "subject_id",
            name="uq_ai_model_access_rules_subject",
        ),
    )
    op.create_index("ix_ai_model_access_rules_feature_key", "ai_model_access_rules", ["feature_key"])
    op.create_index("ix_ai_model_access_rules_model_id", "ai_model_access_rules", ["model_id"])
    op.create_index("ix_ai_model_access_rules_subject_type", "ai_model_access_rules", ["subject_type"])
    op.create_index("ix_ai_model_access_rules_subject_id", "ai_model_access_rules", ["subject_id"])

    op.create_table(
        "ai_model_usage_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("feature_key", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("credential_scope_type", sa.String(length=16), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_id"], ["ai_models.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_model_usage_logs_user_id", "ai_model_usage_logs", ["user_id"])
    op.create_index("ix_ai_model_usage_logs_feature_key", "ai_model_usage_logs", ["feature_key"])
    op.create_index("ix_ai_model_usage_logs_model_id", "ai_model_usage_logs", ["model_id"])
    op.create_index("ix_ai_model_usage_logs_result", "ai_model_usage_logs", ["result"])
    op.create_index("ix_ai_model_usage_logs_created_at", "ai_model_usage_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_model_usage_logs_created_at", table_name="ai_model_usage_logs")
    op.drop_index("ix_ai_model_usage_logs_result", table_name="ai_model_usage_logs")
    op.drop_index("ix_ai_model_usage_logs_model_id", table_name="ai_model_usage_logs")
    op.drop_index("ix_ai_model_usage_logs_feature_key", table_name="ai_model_usage_logs")
    op.drop_index("ix_ai_model_usage_logs_user_id", table_name="ai_model_usage_logs")
    op.drop_table("ai_model_usage_logs")
    op.drop_index("ix_ai_model_access_rules_subject_id", table_name="ai_model_access_rules")
    op.drop_index("ix_ai_model_access_rules_subject_type", table_name="ai_model_access_rules")
    op.drop_index("ix_ai_model_access_rules_model_id", table_name="ai_model_access_rules")
    op.drop_index("ix_ai_model_access_rules_feature_key", table_name="ai_model_access_rules")
    op.drop_table("ai_model_access_rules")
    op.drop_index("uq_ai_feature_models_one_default", table_name="ai_feature_models")
    op.drop_index("ix_ai_feature_models_model_id", table_name="ai_feature_models")
    op.drop_index("ix_ai_feature_models_feature_key", table_name="ai_feature_models")
    op.drop_table("ai_feature_models")
    op.drop_index("ix_ai_models_capability", table_name="ai_models")
    op.drop_index("ix_ai_models_provider_name", table_name="ai_models")
    op.drop_table("ai_models")
    op.drop_index("ix_ai_provider_credentials_scope_id", table_name="ai_provider_credentials")
    op.drop_index("uq_ai_provider_credentials_provider_scope", table_name="ai_provider_credentials")
    op.drop_index("ix_ai_provider_credentials_scope_type", table_name="ai_provider_credentials")
    op.drop_index("ix_ai_provider_credentials_provider_name", table_name="ai_provider_credentials")
    op.drop_table("ai_provider_credentials")
