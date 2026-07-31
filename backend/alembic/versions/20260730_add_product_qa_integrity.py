"""Add auditable customer-evidence status to product QA.

Revision ID: 20260730_product_qa_integrity
Revises: 20260623_add_product_assets
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_product_qa_integrity"
down_revision = "20260623_add_product_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_qa",
        sa.Column("integrity_status", sa.String(length=20), nullable=False, server_default="review"),
    )
    op.add_column("product_qa", sa.Column("integrity_reason", sa.Text(), nullable=True))
    op.add_column("product_qa", sa.Column("integrity_model", sa.String(length=100), nullable=True))
    op.add_column("product_qa", sa.Column("integrity_audited_at", sa.DateTime(), nullable=True))
    op.create_index("idx_product_qa_integrity", "product_qa", ["product_id", "integrity_status"])


def downgrade() -> None:
    op.drop_index("idx_product_qa_integrity", table_name="product_qa")
    op.drop_column("product_qa", "integrity_audited_at")
    op.drop_column("product_qa", "integrity_model")
    op.drop_column("product_qa", "integrity_reason")
    op.drop_column("product_qa", "integrity_status")
