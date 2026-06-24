"""add product_assets table

Revision ID: 20260623_add_product_assets
Revises: 20260619_add_knowledge_parse_tasks
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260623_add_product_assets"
down_revision = "20260619_add_knowledge_parse_tasks"
branch_labels = None
depends_on = None


def _assert_no_orphan_assets():
    conn = op.get_bind()
    orphan_count = conn.execute(sa.text(
        "SELECT COUNT(*) "
        "FROM product_assets pa "
        "LEFT JOIN products p ON p.sku = pa.sku "
        "WHERE p.sku IS NULL"
    )).scalar_one()
    if orphan_count:
        raise RuntimeError(f"Cannot add foreign key: product_assets has {orphan_count} orphan sku rows")


def upgrade():
    _assert_no_orphan_assets()
    op.create_table(
        "product_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("category_code", sa.String(length=2), nullable=False),
        sa.Column("category_name", sa.String(length=64), nullable=False),
        sa.Column("sub_category", sa.String(length=64), nullable=True),
        sa.Column("asset_type", sa.String(length=10), nullable=False, server_default="image"),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("brand", sa.String(length=64), nullable=False, server_default="alocs"),
        sa.Column("material_type", sa.String(length=64), nullable=True),
        sa.Column("angle_scene", sa.String(length=128), nullable=True),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("language_tag", sa.String(length=32), nullable=True),
        sa.Column("version_tag", sa.String(length=32), nullable=True),
        sa.Column("date_tag", sa.String(length=16), nullable=True),
        sa.Column("status_tag", sa.String(length=32), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"], ondelete="RESTRICT"),
    )
    op.create_index("idx_product_assets_sku", "product_assets", ["sku"])
    op.create_index("idx_product_assets_sku_category", "product_assets", ["sku", "category_code"])
    op.create_index(
        "idx_product_assets_seq_group",
        "product_assets",
        ["sku", "category_code", "sub_category", "material_type"],
    )


def downgrade():
    op.drop_index("idx_product_assets_seq_group", table_name="product_assets")
    op.drop_index("idx_product_assets_sku_category", table_name="product_assets")
    op.drop_index("idx_product_assets_sku", table_name="product_assets")
    op.drop_table("product_assets")
