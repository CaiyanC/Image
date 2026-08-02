"""Add managed tools and isolated tool runs.

Revision ID: 20260727_add_tools_and_tool_runs
Revises: 20260623_add_product_assets
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260727_add_tools_and_tool_runs"
down_revision = "20260623_add_product_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tools",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tool_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="通用工具"),
        sa.Column("icon_key", sa.String(length=64), nullable=False, server_default="tool"),
        sa.Column("route_path", sa.String(length=255), nullable=False),
        sa.Column("permission_key", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tool_key", name="uq_tools_tool_key"),
        sa.UniqueConstraint("route_path", name="uq_tools_route_path"),
    )
    op.create_index("ix_tools_tool_key", "tools", ["tool_key"])

    op.create_table(
        "tool_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tool_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by",
            sa.String(length=36).with_variant(postgresql.UUID(as_uuid=False), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("input_files", sa.JSON(), nullable=False),
        sa.Column("output_files", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tool_key"], ["tools.tool_key"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tool_runs_tool_key", "tool_runs", ["tool_key"])
    op.create_index("ix_tool_runs_created_by", "tool_runs", ["created_by"])
    op.create_index("ix_tool_runs_status", "tool_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tool_runs_status", table_name="tool_runs")
    op.drop_index("ix_tool_runs_created_by", table_name="tool_runs")
    op.drop_index("ix_tool_runs_tool_key", table_name="tool_runs")
    op.drop_table("tool_runs")
    op.drop_index("ix_tools_tool_key", table_name="tools")
    op.drop_table("tools")
