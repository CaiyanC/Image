"""Allow managed tools to launch external applications.

Revision ID: 20260810_external_tools
Revises: 20260810_add_knowledge_jobs
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_external_tools"
down_revision = "20260810_add_knowledge_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tools",
        sa.Column("entry_type", sa.String(length=20), nullable=False, server_default="internal"),
    )
    op.add_column(
        "tools",
        sa.Column("external_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "tools",
        sa.Column("open_mode", sa.String(length=20), nullable=False, server_default="same_tab"),
    )


def downgrade() -> None:
    op.drop_column("tools", "open_mode")
    op.drop_column("tools", "external_url")
    op.drop_column("tools", "entry_type")
