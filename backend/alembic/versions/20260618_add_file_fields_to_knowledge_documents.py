"""Add file metadata fields to knowledge_documents

Revision ID: 20260618_add_file_fields_to_knowledge_documents
Revises: 
Create Date: 2026-06-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260618_add_file_fields_to_knowledge_documents"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("file_name", sa.String(length=255), nullable=True))
    op.add_column("knowledge_documents", sa.Column("file_path", sa.Text(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("file_type", sa.String(length=50), nullable=True))
    op.add_column("knowledge_documents", sa.Column("file_hash", sa.String(length=128), nullable=True))
    op.add_column("knowledge_documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("parse_status", sa.String(length=30), nullable=False, server_default="pending"))
    op.add_column("knowledge_documents", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("related_skus_json", sa.Text(), nullable=True))
    op.alter_column("knowledge_documents", "parse_status", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge_documents", "related_skus_json")
    op.drop_column("knowledge_documents", "parse_error")
    op.drop_column("knowledge_documents", "parse_status")
    op.drop_column("knowledge_documents", "page_count")
    op.drop_column("knowledge_documents", "file_hash")
    op.drop_column("knowledge_documents", "file_type")
    op.drop_column("knowledge_documents", "file_path")
    op.drop_column("knowledge_documents", "file_name")
