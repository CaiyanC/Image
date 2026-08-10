"""Persist knowledge maintenance jobs and their lifecycle.

Revision ID: 20260810_add_knowledge_jobs
Revises: 20260802_merge_tool_and_qa_heads
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260810_add_knowledge_jobs"
down_revision = "20260802_merge_tool_and_qa_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("active_slot", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_slot", name="uq_knowledge_jobs_active_slot"),
    )
    op.create_index("idx_knowledge_jobs_status", "knowledge_jobs", ["status"], unique=False)
    op.create_index("idx_knowledge_jobs_created_at", "knowledge_jobs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_knowledge_jobs_created_at", table_name="knowledge_jobs")
    op.drop_index("idx_knowledge_jobs_status", table_name="knowledge_jobs")
    op.drop_table("knowledge_jobs")
