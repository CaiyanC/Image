"""Add knowledge parse tasks

Revision ID: 20260619_add_knowledge_parse_tasks
Revises: 20260618_add_file_ingestion_stability_constraints
Create Date: 2026-06-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260619_add_knowledge_parse_tasks"
down_revision = "20260618_add_file_ingestion_stability_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_parse_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_knowledge_parse_tasks_document_id", "knowledge_parse_tasks", ["document_id"], unique=False)
    op.create_index("idx_knowledge_parse_tasks_status", "knowledge_parse_tasks", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_knowledge_parse_tasks_status", table_name="knowledge_parse_tasks")
    op.drop_index("idx_knowledge_parse_tasks_document_id", table_name="knowledge_parse_tasks")
    op.drop_table("knowledge_parse_tasks")
