import pytest
from app.services.customer_facing_answer_contract import render_customer_answer

@pytest.mark.parametrize('text,expected',[
    ('资料未明确配有煎盘。','暂时无法确认配有煎盘。'),
    ('产品资料未明确能否加热。','暂时无法确认能否加热。'),
    ('资料未明确禁止加热。','暂时无法确认禁止加热。'),
    ('资料只明确支持明火。','目前只确认支持明火。'),
    ('竹套版（SKU：CT-T04(BM））','竹套版（SKU：CT-T04(BM)）'),
])
def test_source_uncertainty_preserves_the_following_proposition(text,expected):
    assert render_customer_answer(text)==expected
    assert render_customer_answer(expected)==expected


@pytest.mark.parametrize('text,expected', [
    ('容量是1L。标签: manual_history_review, rag_boundary, batch_2356_2395', '容量是1L。'),
    ('这款支持液体酒精（manual_history_review）。', '这款支持液体酒精。'),
    ('颜色标签：黑色，材质是铝合金。', '颜色标签：黑色，材质是铝合金。'),
])
def test_customer_answer_removes_internal_audit_markers_only(text, expected):
    assert render_customer_answer(text) == expected
