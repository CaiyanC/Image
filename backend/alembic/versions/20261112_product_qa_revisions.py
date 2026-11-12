"""Associate proposed answers with the QA they would replace."""

from alembic import op
import sqlalchemy as sa


revision = "20261112_product_qa_revisions"
down_revision = "20261111_customer_product_links"
branch_labels = None
depends_on = None


def upgrade():
    existing = (
        set() if op.get_context().as_sql
        else {column["name"] for column in sa.inspect(op.get_bind()).get_columns("product_qa")}
    )
    for name, size in (("revision_of_qa_id", 36), ("revision_base_hash", 64)):
        if name not in existing:
            op.add_column("product_qa", sa.Column(name, sa.String(size), nullable=True))


def downgrade():
    op.drop_column("product_qa", "revision_base_hash")
    op.drop_column("product_qa", "revision_of_qa_id")
