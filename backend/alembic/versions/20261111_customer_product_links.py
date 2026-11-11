"""Add marketplace product link mappings for customer service."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20261111_customer_product_links"
down_revision = "20261022_workbuddy_cs_tokens"
branch_labels = None
depends_on = None


def upgrade():
    # The application also creates missing model tables on startup.
    if not op.get_context().as_sql and sa.inspect(op.get_bind()).has_table("customer_product_links"):
        return
    op.create_table(
        "customer_product_links",
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("product_id", sa.String(36).with_variant(UUID(as_uuid=False), "postgresql"), nullable=False),
        sa.Column("snapshot_text", sa.Text(), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("platform", "item_id", "product_id"),
    )


def downgrade():
    op.drop_table("customer_product_links")
