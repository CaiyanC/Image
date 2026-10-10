"""Add product supply-chain and outer-carton fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260918_product_supply_chain"
down_revision = "20260917_competitor_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "product_supply_chain" in inspector.get_table_names():
        return

    op.create_table(
        "product_supply_chain",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "product_id",
            sa.String(length=36).with_variant(postgresql.UUID(as_uuid=False), "postgresql"),
            nullable=False,
        ),
        sa.Column("barcode_69", sa.String(length=32), nullable=True),
        sa.Column("cost_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("cost_currency", sa.String(length=8), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("outer_carton_length_cm", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("outer_carton_width_cm", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("outer_carton_height_cm", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("outer_carton_pcs", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_product_supply_chain_product_id"),
    )
    op.create_index(
        "idx_product_supply_chain_supplier",
        "product_supply_chain",
        ["supplier_name"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "product_supply_chain" not in inspector.get_table_names():
        return
    index_names = {item["name"] for item in inspector.get_indexes("product_supply_chain")}
    if "idx_product_supply_chain_supplier" in index_names:
        op.drop_index("idx_product_supply_chain_supplier", table_name="product_supply_chain")
    op.drop_table("product_supply_chain")
