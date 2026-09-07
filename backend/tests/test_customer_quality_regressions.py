"""Regressions reproduced from the fixed 100-question customer benchmark."""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.product import Product
from app.services import customer_service_semantic_rag_v2_service as formal
from app.services import customer_service_workbuddy_agent_service as agent
from app.services import customer_enterprise_guardrail_service as guard
from app.services.customer_facing_answer_contract import render_customer_answer


@pytest.mark.parametrize('question,expected', [
    ('CT-T04(BM)的热源？', ['CT-T04(BM)']),
    ('CT-T04（BM）的热源？', ['CT-T04(BM)']),
    ('CT-T04-BM的热源？', ['CT-T04-BM']),
    ('CT-T04和CT-T04(BM)比较', ['CT-T04', 'CT-T04(BM)']),
    ('KW-K31-白天鹅壶是什么颜色？', ['KW-K31-白']),
    ('CT-T04的热源？', ['CT-T04']),
])
def test_full_catalogue_variant_is_not_truncated(question, expected):
    engine = create_engine('sqlite:///:memory:')
    Product.__table__.create(engine)
    with Session(engine) as db:
        for i, sku in enumerate(['CT-T04', 'CT-T04-BM', 'CT-T04(BM)', 'KW-K31', 'KW-K31-白']):
            db.add(Product(id=f'variant-{i}', sku=sku, barcode=f'variant-{i}',
                           product_name_cn=sku, brand='test', category='test'))
        db.commit()
        assert formal._explicit_skus(db, question) == expected
    engine.dispose()


@pytest.mark.parametrize('text', [
    '避免金属工具刮擦锅内壁。',
    '清洁工具需要另行准备。',
    '这是一套户外工具，不附送收纳袋。',
])
def test_public_answer_preserves_physical_tools(text):
    assert agent._sanitize_public_answer(text) == text


@pytest.mark.parametrize('explicit,page,context,expected', [
    (['CW-C78'], 'CW-K03', ['CW-K04PRO-37'], ['CW-C78']),
    (['CW-C78', 'CW-C93'], None, ['CW-K03'], ['CW-C78', 'CW-C93']),
    ([], 'CW-C78', ['CW-K03'], ['CW-C78']),
    ([], None, ['CW-C78'], ['CW-C78']),
])
def test_experience_scope_prefers_customer_identity(monkeypatch, explicit, page, context, expected):
    scopes = []

    async def prefetch(*args, **kwargs):
        return [{'sku': 'CW-K03'}, {'sku': 'CW-K04PRO-37'}]

    async def retrieve(*args, **kwargs):
        scopes.append(kwargs['skus'])
        return []

    async def chat(*args, **kwargs):
        return json.dumps({'answer': '先看您是否还需要做饭。', 'response_mode': 'conversational',
                           'answer_type': 'faq', 'identity_status': 'confirmed'})

    monkeypatch.setattr(agent, '_prefetch_semantic_catalog', prefetch)
    monkeypatch.setattr(agent.customer_experience_rag_service, 'retrieve_experience_guidance', retrieve)
    monkeypatch.setattr(agent.customer_llm_service, 'chat_completion', chat)
    asyncio.run(agent._run_agent(None, question='已有烧水壶，还需要买整套吗？帮我判断',
                                history=[], page_sku=page, context_skus=context, explicit_skus=explicit))
    assert scopes == [expected]


@pytest.mark.parametrize('question', ['那你能保证肯定送吗？我现在就买。', '今天能买到吗？', '明天能送到吗？'])
def test_purchase_time_words_are_not_weather(question):
    result = guard.evaluate_question(question)
    assert result is None or 'realtime_weather_unavailable' not in result.get('warnings', [])


def test_real_weather_boundary_remains():
    result = guard.evaluate_question('明天会下雨吗？')
    assert result and '实时天气' in result['answer']


@pytest.mark.parametrize('accessory,authority,accepted', [('GA01', True, True), ('FAKE-999', True, False), ('GA01', False, False)])
def test_source_named_accessory_is_not_an_unknown_product(accessory, authority, accepted):
    evidence = [{'sku': 'CS-G23-42', 'evidence_id': 'e1', 'source_type': 'product_qa',
                 'fact_authority': authority, 'content': '卡式罐需要GA01转接头，不要自行改接气路。'}]
    answer = f'卡式罐需要{accessory}转接头，不要自行改接气路。'
    result = formal._validated_answer(
        {'answer': answer, 'selected_skus': ['CS-G23-42'], 'evidence_ids': ['e1'],
         'answer_type': 'product_detail'}, evidence=evidence, candidate_skus=['CS-G23-42'],
        question='CS-G23-42用哪种转接头？', identity_ambiguity=False)
    assert (result[0] == answer) is accepted


def test_unknown_parenthetical_variant_does_not_bind_base():
    assert formal._sku_tokens_with_catalogue('CT-T04(UNKNOWN)适配吗？', ['CT-T04']) == ['CT-T04(UNKNOWN)']


@pytest.mark.parametrize('text', ['CW-C93（220g）', 'CW-C93(220g)', 'CW-C93（1kg）'])
def test_parenthetical_measurement_does_not_become_unknown_variant(text):
    assert formal._sku_tokens_with_catalogue(text, ['CW-C93']) == ['CW-C93']


def test_real_catalogue_measurement_variant_still_wins():
    assert formal._sku_tokens_with_catalogue('CW-C93(220G)', ['CW-C93','CW-C93(220G)']) == ['CW-C93(220G)']


@pytest.mark.parametrize('raw,expected', [
    ('资料库显示这款容量是1.4L。', '已确认这款容量是1.4L。'),
    ('正式产品资料标注颜色为黑色，并非红色。', '已确认颜色为黑色，并非红色。'),
    ('资料未直接确认室内使用安全许可，请遵守通风要求。', '暂时无法确认室内使用安全许可，请遵守通风要求。'),
    ('资料只标注450ml，无法确认属于哪个部件。', '目前只确认450ml，无法确认属于哪个部件。'),
    ('资料没有单独列出壶盖尺寸。', '暂时无法单独确认壶盖尺寸。'),
    ('资料没有将收纳袋登记为固定随附配置。', '目前尚未将收纳袋确认为固定随附配置。'),
    ('按资料，容量为3L，不是10L。', '容量为3L，不是10L。'),
    ('避免金属工具刮擦，不要干烧。', '避免金属工具刮擦，不要干烧。'),
    ('不可明火加热，除非该产品明确支持。', '不可明火加热，除非该产品明确支持。'),
    ('没有配件，不支持电磁炉，禁止干烧。', '没有配件，不支持电磁炉，禁止干烧。'),
    ('这款的资料未列出适用热源。', '这款暂时无法确认适用热源。'),
    ('资料确认的是硬质氧化。', '已确认的是硬质氧化。'),
    ('CW-C78的主数据确认是多件套，但没有在当前主数据中列出完整配件清单。',
     'CW-C78已确认是多件套，但暂时无法确认完整配件清单。'),
])
def test_attribution_renderer_preserves_claims_and_safety(raw, expected):
    assert render_customer_answer(raw) == expected
    assert render_customer_answer(expected) == expected


@pytest.mark.parametrize('raw,expected', [
    ('现有资料未分别标明部件尺寸。', '暂时无法分别确认部件尺寸。'),
    ('资料未进一步区分各部件。', '暂时无法进一步区分各部件。'),
    ('资料未说明450ml属于整套还是单杯。', '暂时无法确认450ml属于整套还是单杯。'),
    ('资料还列有收纳尺寸。', '另有收纳尺寸。'),
    ('资料中列有木柴。', '可确认的包括木柴。'),
    ('资料描述为耐磨耐用，但不能保证永久不坏。', '描述为耐磨耐用，但不能保证永久不坏。'),
    ('资料将其描述为耐用。', '这款被描述为耐用。'),
    ('现有资料只提供整体尺寸。', '目前只确认整体尺寸。'),
    ('资料都明确覆盖户外场景。', '都明确覆盖户外场景。'),
    ('使用资料：没有分别登记尺寸；适用人数资料偏向两人。',
     '使用注意：暂时无法分别确认尺寸；适用人数偏向两人。'),
    ('额定功率未填写，暂时无法确认具体数值。', '额定功率暂时无法确认具体数值。'),
    ('商品问答写作300g，主数据标注毛重320g，应以毛重320g为准。',
     '补充说明写作300g，已确认毛重320g，应以毛重320g为准。'),
])
def test_real_v4_attribution_regressions(raw, expected):
    assert render_customer_answer(raw) == expected
    assert render_customer_answer(expected) == expected
