"""Independent competitor reference storage, without SKU or publication grants."""
from alembic import op
import sqlalchemy as sa

revision = "20260917_competitor_assets"
down_revision = "20260831_cs_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competitor_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brand", sa.String(64), nullable=False),
        sa.Column("asset_type", sa.String(10), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("original_file_name", sa.String(255), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("maintainer", sa.String(100), nullable=True),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("asset_type IN ('image', 'video')", name="ck_competitor_asset_type"),
    )
    op.create_index("idx_competitor_assets_brand_type", "competitor_assets", ["brand", "asset_type"])


def downgrade() -> None:
    op.drop_index("idx_competitor_assets_brand_type", table_name="competitor_assets")
    op.drop_table("competitor_assets")

