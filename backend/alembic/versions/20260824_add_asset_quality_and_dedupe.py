"""Add visual-asset quality and exact-duplicate metadata.

Revision ID: 20260824_asset_quality_dedupe
Revises: 20260824_auth_security
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_asset_quality_dedupe"
down_revision = "20260824_auth_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("product_assets")}
    columns = (
        sa.Column("quality_status", sa.String(length=32), nullable=False, server_default="usable"),
        sa.Column("quality_reason", sa.Text(), nullable=True),
        sa.Column("duplicate_status", sa.String(length=32), nullable=False, server_default="unique"),
        sa.Column("duplicate_of_asset_id", sa.String(length=36), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("product_assets", column)

    op.execute(
        sa.text(
            "UPDATE product_assets SET "
            "quality_status = COALESCE(quality_status, 'usable'), "
            "duplicate_status = COALESCE(duplicate_status, 'unique')"
        )
    )

    index_names = {item["name"] for item in inspector.get_indexes("product_assets")}
    if "idx_product_assets_checksum" not in index_names:
        op.create_index("idx_product_assets_checksum", "product_assets", ["checksum_sha256"])
    if "idx_product_assets_quality_status" not in index_names:
        op.create_index("idx_product_assets_quality_status", "product_assets", ["quality_status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    index_names = {item["name"] for item in inspector.get_indexes("product_assets")}
    if "idx_product_assets_quality_status" in index_names:
        op.drop_index("idx_product_assets_quality_status", table_name="product_assets")
    if "idx_product_assets_checksum" in index_names:
        op.drop_index("idx_product_assets_checksum", table_name="product_assets")

    existing = {column["name"] for column in inspector.get_columns("product_assets")}
    for name in ("duplicate_of_asset_id", "duplicate_status", "quality_reason", "quality_status"):
        if name in existing:
            op.drop_column("product_assets", name)
