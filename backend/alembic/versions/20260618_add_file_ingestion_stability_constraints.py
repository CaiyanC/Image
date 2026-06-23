"""Add file ingestion stability constraints and indexes

Revision ID: 20260618_add_file_ingestion_stability_constraints
Revises: 20260618_add_file_fields_to_knowledge_documents
Create Date: 2026-06-18 00:00:00.000000
"""

from alembic import op
import logging
import sqlalchemy as sa


revision = "20260618_add_file_ingestion_stability_constraints"
down_revision = "20260618_add_file_fields_to_knowledge_documents"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    _ensure_no_duplicate_file_documents()
    _ensure_no_duplicate_chunks()

    op.create_index(
        "idx_knowledge_documents_parse_status",
        "knowledge_documents",
        ["parse_status"],
        unique=False,
    )
    op.create_index(
        "idx_knowledge_chunks_document_id",
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "idx_knowledge_chunks_embedding_status",
        "knowledge_chunks",
        ["embedding_status"],
        unique=False,
    )
    op.create_index(
        "idx_knowledge_chunks_source_type",
        "knowledge_chunks",
        ["source_type"],
        unique=False,
    )

    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.create_unique_constraint(
            "uq_knowledge_documents_source_type_file_hash",
            ["source_type", "file_hash"],
        )

    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.create_unique_constraint(
            "uq_knowledge_chunks_document_id_chunk_index",
            ["document_id", "chunk_index"],
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.drop_constraint("uq_knowledge_chunks_document_id_chunk_index", type_="unique")

    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.drop_constraint("uq_knowledge_documents_source_type_file_hash", type_="unique")

    op.drop_index("idx_knowledge_chunks_source_type", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_embedding_status", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_documents_parse_status", table_name="knowledge_documents")


def _ensure_no_duplicate_file_documents() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        """
        SELECT source_type, file_hash, COUNT(*) AS total
        FROM knowledge_documents
        WHERE source_type = 'file' AND file_hash IS NOT NULL
        GROUP BY source_type, file_hash
        HAVING COUNT(*) > 1
        """
    )).mappings().all()
    if not rows:
        return

    logger.warning("duplicate file documents detected before migration: %s", rows)
    raise RuntimeError(
        "knowledge_documents has duplicate source_type + file_hash rows. "
        "Please deduplicate historical file documents before running this migration."
    )


def _ensure_no_duplicate_chunks() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        """
        SELECT document_id, chunk_index, COUNT(*) AS total
        FROM knowledge_chunks
        WHERE document_id IS NOT NULL
        GROUP BY document_id, chunk_index
        HAVING COUNT(*) > 1
        """
    )).mappings().all()
    if not rows:
        return

    logger.warning("duplicate knowledge chunks detected before migration: %s", rows)
    raise RuntimeError(
        "knowledge_chunks has duplicate document_id + chunk_index rows. "
        "Please deduplicate historical chunks before running this migration."
    )
