"""Business classification, multi-SKU assets and measured video metadata."""
from alembic import op
import sqlalchemy as sa

revision = '20261008_business_asset_plan'
down_revision = '20260918_product_supply_chain'
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in {
        'product_business': [('suitable_people', sa.String(100)), ('audience_tags', sa.Text()), ('value_positioning', sa.String(100))],
        'product_assets': [('video_duration_seconds', sa.Float()), ('availability_status', sa.String(32)), ('material_layer', sa.String(100))],
    }.items():
        existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}
        for name, kind in columns:
            if name not in existing:
                op.add_column(table, sa.Column(name, kind, nullable=True))
    if 'reference_only' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('product_assets')}:
        op.add_column('product_assets', sa.Column('reference_only', sa.Boolean(), nullable=False, server_default=sa.false()))
    if not sa.inspect(op.get_bind()).has_table('product_asset_links'):
        op.create_table('product_asset_links',
            sa.Column('asset_id', sa.String(36), sa.ForeignKey('product_assets.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('sku', sa.String(100), sa.ForeignKey('products.sku', ondelete='CASCADE', onupdate='CASCADE'), primary_key=True))
        op.create_index('ix_product_asset_links_sku', 'product_asset_links', ['sku'])


def downgrade():
    op.drop_table('product_asset_links')
    for name in ('video_duration_seconds', 'reference_only', 'availability_status', 'material_layer'):
        op.drop_column('product_assets', name)
    for name in ('suitable_people', 'audience_tags', 'value_positioning'):
        op.drop_column('product_business', name)
