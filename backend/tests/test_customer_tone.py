"""Expression regressions must preserve facts, safety and capability boundaries."""
import pytest
from app.services.customer_answer_prompt import build_customer_answer_prompt
from app.services.customer_service_triage import classify, safe_reply
from app.services import customer_followup_context_contract as followup

def test_tone_is_versioned_and_bounded(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'CUSTOMER_SERVICE_PLAN_ENABLED', True)
    prompt = build_customer_answer_prompt()
    for term in ['customer-tone-20261008-v1', '暂时不用再推荐', '不要每句加语气词',
                 '毛重/净重', '不能为亲切新增商品事实', '平台具体按钮名称']:
        assert term in prompt
    monkeypatch.setattr(settings, 'CUSTOMER_SERVICE_PLAN_ENABLED', False)
    assert 'customer-tone-20261008-v1' not in build_customer_answer_prompt()

@pytest.mark.parametrize('question', [
    '太好了，谢谢你，暂时不用再推荐啦。', '不用继续推荐了',
    '先别再推荐', '不需要再给我推荐了', '不要再推荐了'])
def test_declining_recommendations_clears_replacement_task(question):
    previous = {'version':1,'form':'kettle','capacity_ml':800,
                'capacity_relation':'near','anchor_sku':'ANCHOR','require_regular':True}
    context, applies, reset = followup.prepare_followup_context(
        question, previous=previous, anchor_product=None)
    assert context=={} and not applies and reset

@pytest.mark.parametrize('question', ['请再推荐一款', '换个类似的水壶', '不要一样容量，推荐大一点的'])
def test_positive_recommendation_requests_still_work(question):
    previous = {'version':1,'form':'kettle','capacity_ml':800,'capacity_relation':'near'}
    context, applies, _ = followup.prepare_followup_context(question,previous=previous,anchor_product=None)
    assert context and applies

def test_emotional_first_replies_stay_within_authority():
    q='订单物流两天没动，周五急着出行，明天能发货吗？'
    reply=safe_reply(classify(q),question=q)
    assert '着急' in reply and '不能保证' in reply and '查不到' in reply
    assert '实时价格' not in reply and '实时库存' not in reply
    q='我买了两套，本来期待有赠品，结果没有，有点失望'
    reply=safe_reply(classify(q),question=q)
    assert '失望' in reply and '不能保证' in reply and '尚未接通' in reply
    assert '已申请' not in reply and '已转' not in reply
    reply=safe_reply(classify('预算紧，有优惠或赠品吗'),question='预算紧，有优惠或赠品吗')
    assert '预算' in reply and '没有收到' not in reply

def test_safety_action_remains_first_and_serious():
    q='炉子正在漏气，有点慌，能点火吗'
    reply=safe_reply(classify(q),question=q)
    assert reply.startswith('请立即停止使用') and '不要继续点火' in reply
    assert '您的安全最重要' in reply and '应急' in reply
    assert not any(t in reply for t in ['放心','亲','呀','哦','已转'])
