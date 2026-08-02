"""Merge tool-platform and product-QA migration heads.

Revision ID: 20260802_merge_tool_and_qa_heads
Revises: 20260728_add_ai_model_governance, 20260730_product_qa_integrity
Create Date: 2026-08-02
"""


revision = "20260802_merge_tool_and_qa_heads"
down_revision = (
    "20260728_add_ai_model_governance",
    "20260730_product_qa_integrity",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
