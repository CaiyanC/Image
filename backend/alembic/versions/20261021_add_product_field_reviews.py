"""Persist field verification evidence for customer-safe product facts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261021_product_field_reviews"
down_revision = "20261008_business_asset_plan"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_field_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "product_id",
            sa.String(length=36).with_variant(postgresql.UUID(as_uuid=False), "postgresql"),
            nullable=False,
        ),
        sa.Column("field_key", sa.String(length=100), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="unreviewed", nullable=False),
        sa.Column("evidence_source_name", sa.Text(), nullable=True),
        sa.Column("evidence_locator", sa.Text(), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("customer_visible", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reviewed_value", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.String(length=36).with_variant(postgresql.UUID(as_uuid=False), "postgresql"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "field_key", name="uq_product_field_reviews_product_field"),
    )
    op.create_index(
        "idx_product_field_reviews_product_status",
        "product_field_reviews",
        ["product_id", "status"],
    )


def downgrade():
    op.drop_index("idx_product_field_reviews_product_status", table_name="product_field_reviews")
    op.drop_table("product_field_reviews")
