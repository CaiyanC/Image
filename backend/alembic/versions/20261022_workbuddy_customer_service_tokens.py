"""Add scoped, revocable WorkBuddy customer-service connector tokens."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261022_workbuddy_cs_tokens"
down_revision = "20261021_product_field_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workbuddy_customer_service_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=36).with_variant(postgresql.UUID(as_uuid=False), "postgresql"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_workbuddy_customer_service_tokens_hash"),
    )
    op.create_index(
        "idx_workbuddy_customer_service_tokens_user",
        "workbuddy_customer_service_tokens",
        ["user_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_workbuddy_customer_service_tokens_user", table_name="workbuddy_customer_service_tokens")
    op.drop_table("workbuddy_customer_service_tokens")
