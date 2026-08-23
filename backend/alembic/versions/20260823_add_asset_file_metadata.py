"""Add durable file metadata to product assets.

Revision ID: 20260823_asset_file_metadata
Revises: 20260810_external_tools
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_asset_file_metadata"
down_revision = "20260810_external_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("product_assets")}
    columns = (
        sa.Column("original_file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("product_assets", column)


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("product_assets")}
    for name in ("height", "width", "checksum_sha256", "file_size_bytes", "mime_type", "original_file_name"):
        if name in existing:
            op.drop_column("product_assets", name)
