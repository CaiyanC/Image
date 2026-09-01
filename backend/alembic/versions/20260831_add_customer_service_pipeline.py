"""Keep customer-service conversation state isolated by pipeline.

Revision ID: 20260831_customer_service_pipeline
Revises: 20260824_asset_quality_dedupe
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20260831_cs_pipeline"
down_revision = "20260824_asset_quality_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "customer_service_conversations" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("customer_service_conversations")}
    if "pipeline" not in columns:
        op.add_column(
            "customer_service_conversations",
            sa.Column("pipeline", sa.String(length=50), nullable=False, server_default="legacy"),
        )

    indexes = {index["name"] for index in inspector.get_indexes("customer_service_conversations")}
    if "idx_customer_service_conversations_pipeline" not in indexes:
        op.create_index(
            "idx_customer_service_conversations_pipeline",
            "customer_service_conversations",
            ["user_id", "pipeline", "updated_at"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "customer_service_conversations" not in tables:
        return

    indexes = {index["name"] for index in inspector.get_indexes("customer_service_conversations")}
    if "idx_customer_service_conversations_pipeline" in indexes:
        op.drop_index("idx_customer_service_conversations_pipeline", table_name="customer_service_conversations")

    columns = {column["name"] for column in inspector.get_columns("customer_service_conversations")}
    if "pipeline" in columns:
        op.drop_column("customer_service_conversations", "pipeline")
