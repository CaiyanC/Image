import pytest
from app.services.customer_facing_answer_contract import render_customer_answer

@pytest.mark.parametrize('text,expected', [
    ('暂不能从资料确认是否附送。', '暂不能从现有信息确认是否附送。'),
    ('不能仅凭主数据确认完整清单。', '不能仅凭现有信息确认完整清单。'),
    ('可以从资料确认容量1.4L。', '可以从现有信息确认容量1.4L。'),
    ('资料未分别标注尺寸。', '暂时无法分别确认尺寸。'),
    ('两款资料都明确支持明火。', '两款都明确支持明火。'),
    ('商品问答也直接支持此结论。', '也直接支持此结论。'),
    ('**使用资料**：禁止干烧，除非另有说明。', '**使用说明**：禁止干烧，除非另有说明。'),
    ('从说明书确认操作，禁止干烧。', '从说明书确认操作，禁止干烧。'),
    ('资料只明确这是一口锅，不能确认有煎盘。', '目前只确认这是一口锅，不能确认有煎盘。'),
    ('当前资料未明确其为一体设计。', '暂时无法确认其为一体设计。'),
    ('其定位资料偏向单人。', '其定位偏向单人。'),
])
def test_prepositions_modifiers_and_safety_are_preserved(text, expected):
    assert render_customer_answer(text) == expected
    assert render_customer_answer(expected) == expected
